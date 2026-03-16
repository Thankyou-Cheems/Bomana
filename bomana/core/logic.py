# -*- coding: utf-8 -*-
"""Game logic core."""

import math
import os
import threading
import time
from typing import Optional, Tuple, Any, List, Dict

import requests

from bomana.config import (
    ENABLE_CCRP,
    ENABLE_ZONES,
    ENABLE_AIRFIELDS,
    ENABLE_FUEL,
    ENABLE_CHECKLIST,
    ENABLE_CLOG_PROBE,
    GameConfig,
    ZoneConfig,
    FuelConfig,
    NetworkConfig,
    ClogConfig,
    BombConfig,
    Theme,
    OverspeedConfig,
    PanelConfig,
)
from bomana.core.state import (
    TelemetryData,
    Zone,
    Airfield,
    MapObjData,
    MapInfo,
    Phase,
    LifeState,
    FuelState,
    ZoneNavigationState,
    AttitudeConfidenceState,
    GameState,
    ZoneDisplayInfo,
    AirfieldDisplayInfo,
    UISnapshot,
)
from bomana.core.telemetry import Budget, HttpJson, TelemetryFetcher, MapInfoFetcher, MapObjectsFetcher
from bomana.core.ballistics import calculate_bomb_trajectory, calculate_release_timing
from bomana.core.clog_probe import collect_players_one_shot
from bomana.core.overspeed import OverspeedAnalyzer
from bomana.utils.math_utils import (
    calculate_heading_from_vector,
    calculate_bearing,
    calculate_distance,
    normalize_angle,
    calculate_relative_bearing,
    get_direction_text,
    calculate_heading_tape_scale,
    get_cdi_tolerance,
    calculate_zone_turn_indicator,
    calculate_zone_status,
    calculate_airfield_turn_indicator,
    calculate_airfield_status,
    format_distance_ete,
    format_distance_dynamic,
    get_deviation_color,
    generate_cdi_indicator,
)
from bomana.utils.file_utils import StateManager

# ============================================================================
# 游戏逻辑核心
# ============================================================================

class GameLogic:
    """游戏逻辑核心类
    
    职责：
    1. 轮询8111接口获取数据
    2. 状态机管理（IDLE → HANGAR → ARMING → ALIVE → ...）
    3. 导航计算（战区目标选择、地速计算）
    4. 生成UI快照（线程安全的数据传递）
    
    设计模式：
    - 使用锁保护共享状态
    - 独立线程执行tick循环
    - 通过snapshot()传递数据给UI
    
    v6.0.1 优化：
    - Session禁用代理检查，减少网络延迟
    - 弹道计算移至tick线程，降低UI线程负载
    """

    # v6.8.0 姿态可信度检测参数（供 HUD 回退决策）
    ATTITUDE_MISSING_CONFIRM_SEC = 1.0
    ATTITUDE_ZERO_CONFIRM_SEC = 3.0
    ATTITUDE_ZERO_EPS_DEG = 0.35
    ATTITUDE_JITTER_DECAY_PER_SEC = 1.5
    ATTITUDE_JITTER_TRIGGER_SCORE = 3.0
    ATTITUDE_JITTER_PITCH_RATE_DEG_S = 260.0
    ATTITUDE_JITTER_ROLL_RATE_DEG_S = 420.0
    
    def __init__(self):
        self._lock = threading.Lock()
        self.session = requests.Session()
        # 性能优化：禁用代理环境检查，减少每次请求的开销
        self.session.trust_env = False
        self.http = HttpJson(self.session)
        self.tel = TelemetryFetcher(self.http)
        self.map_info_fetcher = MapInfoFetcher(self.http)
        self.map = MapObjectsFetcher(self.http)
        self.overspeed = OverspeedAnalyzer()
        self.state = GameState()
        self._clog_probe_thread: Optional[threading.Thread] = None
        if self._is_clog_probe_enabled():
            self.state.clog_probe_status = "idle"
        else:
            self.state.clog_probe_status = "disabled"
    
    @property
    def is_api_down(self) -> bool:
        """轻量级API状态检查（用于轮询间隔控制）
        
        避免在_poll_loop中生成完整snapshot只为检查api_down状态。
        """
        with self._lock:
            return self.state.api_down

    def _is_clog_probe_enabled(self) -> bool:
        """是否启用 clog 一次性解析（实验功能）。"""
        env_force = str(os.environ.get("BOMANA_ENABLE_CLOG_PROBE", "")).strip().lower()
        env_enabled = env_force in ("1", "true", "yes", "on")
        return bool((ENABLE_CLOG_PROBE and ClogConfig.ENABLED) or env_enabled)

    def _schedule_clog_probe_locked(self, now: float, life_index: int) -> None:
        """为当前生命安排一次延迟 clog 解析（锁内）。"""
        s = self.state
        if not self._is_clog_probe_enabled():
            s.clog_probe_status = "disabled"
            s.clog_probe_life_index = 0
            s.clog_probe_scheduled_at = None
            s.clog_probe_last_run_ts = 0.0
            s.clog_probe_player_count = 0
            s.clog_probe_players = []
            s.clog_probe_error = ""
            return

        s.clog_probe_status = "pending"
        s.clog_probe_life_index = int(life_index)
        s.clog_probe_scheduled_at = float(now) + max(0.0, float(ClogConfig.TRIGGER_DELAY_SEC))
        s.clog_probe_last_run_ts = 0.0
        s.clog_probe_player_count = 0
        s.clog_probe_players = []
        s.clog_probe_error = ""

    def _maybe_start_clog_probe_worker(self, now: float) -> None:
        """到时后启动一次性 clog 解析后台任务。"""
        if not self._is_clog_probe_enabled():
            return

        life_index = 0
        with self._lock:
            s = self.state
            if s.clog_probe_status != "pending":
                return
            if s.clog_probe_scheduled_at is None:
                return
            if now < s.clog_probe_scheduled_at:
                return
            if not s.current_life:
                s.clog_probe_status = "skip"
                s.clog_probe_scheduled_at = None
                s.clog_probe_error = "no current life"
                return
            if s.phase not in (Phase.ALIVE, Phase.LOSS_PENDING):
                s.clog_probe_status = "skip"
                s.clog_probe_scheduled_at = None
                s.clog_probe_error = "phase not alive"
                return
            if s.current_life.life_index != s.clog_probe_life_index:
                s.clog_probe_status = "skip"
                s.clog_probe_scheduled_at = None
                s.clog_probe_error = "life index changed"
                return
            t = self._clog_probe_thread
            if t is not None and t.is_alive():
                return
            life_index = int(s.current_life.life_index)
            s.clog_probe_status = "running"
            s.clog_probe_last_run_ts = now
            s.clog_probe_error = ""

        t = threading.Thread(
            target=self._run_clog_probe_worker,
            args=(life_index,),
            daemon=True,
            name="bomana-clog-probe",
        )
        self._clog_probe_thread = t
        t.start()

    def _run_clog_probe_worker(self, life_index: int) -> None:
        """后台执行一次 clog 解析，不阻塞 tick。"""
        result = collect_players_one_shot(
            clog_file=(ClogConfig.CLOG_FILE or None),
            clog_dir=(ClogConfig.CLOG_DIR or None),
            key_file=(ClogConfig.KEY_FILE or None),
            max_log_bytes=int(ClogConfig.MAX_LOG_BYTES),
            max_log_lines=int(ClogConfig.MAX_LOG_LINES),
        )

        status = str(result.get("status", "error"))
        error = str(result.get("error", "") or "")
        extract = result.get("extract", {}) if isinstance(result.get("extract"), dict) else {}
        players_raw = extract.get("players", []) if isinstance(extract, dict) else []
        players: List[str] = []
        if isinstance(players_raw, list):
            for item in players_raw:
                if isinstance(item, dict):
                    name = str(item.get("name", "") or "").strip()
                    if name:
                        players.append(name)
                elif isinstance(item, str) and item.strip():
                    players.append(item.strip())
        players = players[: max(1, int(ClogConfig.MAX_DEBUG_NAMES))]

        with self._lock:
            s = self.state
            current_life = s.current_life.life_index if s.current_life else 0
            if current_life != int(life_index):
                return
            if s.clog_probe_life_index != int(life_index):
                return

            s.clog_probe_scheduled_at = None
            s.clog_probe_last_run_ts = time.time()
            scan_stats = extract.get("scan_stats", {}) if isinstance(extract, dict) else {}
            if isinstance(scan_stats, dict):
                s.clog_probe_player_count = int(scan_stats.get("players_detected", len(players_raw)))
            else:
                s.clog_probe_player_count = len(players_raw)
            s.clog_probe_players = players
            s.clog_probe_error = error[:120]

            if not bool(result.get("ok")):
                s.clog_probe_status = "error"
                if not s.clog_probe_error:
                    s.clog_probe_error = "probe failed"
                return

            if status in ("no_clog_dir", "no_clog_file"):
                s.clog_probe_status = "skip"
                return
            if status == "empty":
                s.clog_probe_status = "empty"
                return
            if status == "parsed":
                s.clog_probe_status = "parsed"
                return
            s.clog_probe_status = status or "parsed"

    def tick(self) -> None:
        """主逻辑循环（每250ms执行一次）
        
        流程：
        1. 获取遥测数据
        2. 获取/缓存地图元数据
        3. 获取地图对象
        4. 更新游戏状态（状态机）
        5. 更新导航信息
        """
        now = time.time()
        budget = Budget(NetworkConfig.MAX_TICK_NET_BUDGET)

        # ALIVE 后延迟触发一次性 clog 解析（后台执行）
        self._maybe_start_clog_probe_worker(now)
        
        # 1. 获取遥测数据
        tel = self.tel.fetch(budget)
        raw_tel = tel
        
        # 2. 检查是否需要更新地图元数据（30秒缓存）
        with self._lock:
            map_info = self.state.map_info
            need_map_info = (
                map_info is None or 
                not map_info.valid or 
                (now - map_info.fetch_time) > ZoneConfig.MAP_INFO_CACHE_SEC
            )
        
        if need_map_info and budget.remaining() > 0.05:
            new_map_info = self.map_info_fetcher.fetch(budget)
            if new_map_info:
                with self._lock:
                    self.state.map_info = new_map_info
                    map_info = new_map_info
        
        # 3. 获取地图对象
        mp = self.map.fetch(budget, map_info)
        
        # 4. 记录原始API状态（后续可能在锁内应用短时缓存兜底）
        raw_api_up = bool(tel.ind_ok or tel.state_resp_ok or mp.ok)

        # 5. 更新游戏状态（线程安全）
        with self._lock:
            s = self.state
            prev_tel = s.last_tel
            prev_map = s.last_map

            # 在战斗阶段对瞬时空帧做“上一帧有效数据”兜底，避免UI/状态机被单帧抖动拉偏。
            phase_allows_grace = s.phase in (Phase.ALIVE, Phase.LOSS_PENDING)
            recently_seen = (
                s.last_player_present_ts > 0.0 and
                (now - s.last_player_present_ts) <= GameConfig.PLAYER_PRESENCE_GRACE_SEC
            )
            used_tel_fallback = False
            used_map_fallback = False

            if phase_allows_grace and recently_seen:
                tel_unstable = (not tel.ind_ok) or (not tel.state_resp_ok)
                if tel_unstable and prev_tel and (prev_tel.ind_ok or prev_tel.state_resp_ok):
                    tel = prev_tel
                    used_tel_fallback = True

                map_unstable = (
                    (not mp.ok) or
                    (mp.ok and (mp.obj_count == 0) and (not mp.player_aircraft_present))
                )
                if map_unstable and prev_map and prev_map.ok:
                    mp = prev_map
                    used_map_fallback = True

            api_up = bool(raw_api_up or used_tel_fallback or used_map_fallback)
            s.last_tel = tel
            s.last_map = mp
            self._update_attitude_confidence_locked(raw_tel, now)

            # API状态管理
            if api_up:
                s.api_down = False
                s.api_down_candidate_since = None
            else:
                # API断线确认（5秒）
                if s.api_down_candidate_since is None:
                    s.api_down_candidate_since = now
                if (now - s.api_down_candidate_since) >= GameConfig.API_DOWN_CONFIRM_SEC:
                    s.api_down = True
            
            if s.api_down:
                if s.phase != Phase.HANGAR:
                    s.phase = Phase.IDLE
                return

            # 判断玩家是否存在
            # 地图/对象接口在个别时刻会瞬时抖动（例如游戏内打开/关闭地图），
            # 在 ALIVE/LOSS_PENDING 阶段允许短时兜底，但不能无限延长宽限窗口。
            phase_allows_player_grace = s.phase in (Phase.ALIVE, Phase.LOSS_PENDING)
            player_present = bool(mp.ok and mp.player_aircraft_present)
            # 仅真实 map 帧（非上一帧兜底）可以刷新“最近见到玩家”时间，
            # 否则回机库时可能被兜底数据无限续期。
            if player_present and (not used_map_fallback):
                s.last_player_present_ts = now

            presence_recently_seen = (
                s.last_player_present_ts > 0.0 and
                (now - s.last_player_present_ts) <= GameConfig.PLAYER_PRESENCE_GRACE_SEC
            )

            # 实体特征兜底：仅在“最近确实见过玩家”的短时间窗口内生效，
            # 避免回机库后因遥测仍有残留值而长期保持 ALIVE。
            if (not player_present) and phase_allows_player_grace and tel.entity_like and presence_recently_seen:
                player_present = True

            # 数据短抖动宽限：计分板/地图等场景可能导致8111瞬时空帧，避免ALIVE阶段立即判死。
            if (not player_present) and phase_allows_player_grace:
                data_unstable = (not mp.ok) or (not tel.ind_ok) or (not tel.state_resp_ok)
                if data_unstable and presence_recently_seen:
                    player_present = True
            spawn_candidate = player_present and tel.entity_like

            # 更新导航信息（战区、地速）
            self._update_zone_navigation_locked(mp, tel, now)

            # v6.0.1 优化：弹道计算移至tick线程（每250ms计算一次，而非每50ms）
            self._update_bombing_calculation_locked(tel, now)
            
            # === 状态机逻辑 ===
            
            # 机库检测：无地图数据或对象为空
            hangar_like = (not mp.ok) or (mp.obj_count == 0)
            if hangar_like and (not player_present) and s.phase != Phase.ALIVE:
                if s.hangar_candidate_since is None:
                    s.hangar_candidate_since = now
                elif (now - s.hangar_candidate_since) >= GameConfig.HANGAR_CONFIRM_SEC:
                    s.phase = Phase.HANGAR
                    self._reset_life_state_locked()
            else:
                s.hangar_candidate_since = None

            # 各阶段处理
            if s.phase == Phase.HANGAR:
                # 机库 → 准备出生
                if spawn_candidate:
                    s.phase = Phase.ARMING
                    s.spawn_candidate_since = now
                return

            if s.phase == Phase.IDLE:
                # 空闲 → 准备出生
                if spawn_candidate:
                    s.phase = Phase.ARMING
                    s.spawn_candidate_since = now

            elif s.phase == Phase.ARMING:
                # 准备出生 → 确认出生（1秒）
                if spawn_candidate:
                    if s.spawn_candidate_since is None:
                        s.spawn_candidate_since = now
                    if (now - s.spawn_candidate_since) >= GameConfig.SPAWN_CONFIRM_SEC:
                        self._start_new_life_locked(now)
                        s.phase = Phase.ALIVE
                        self._clear_transient_state_locked()
                else:
                    s.spawn_candidate_since = None
                    s.phase = Phase.IDLE

            elif s.phase == Phase.ALIVE:
                # 存活中：检测补给、着陆、死亡
                
                # v5.8 新增：更新燃油状态
                if tel.state_resp_ok:
                    s.fuel_state.update(
                        fuel_kg=tel.fuel_kg,
                        fuel0_kg=tel.fuel0_kg,
                        altitude_m=tel.altitude_m,
                        ias_kmh=tel.ias_kmh,
                        now=now
                    )
                
                # 补给检测：燃油突增
                if prev_tel and prev_tel.state_resp_ok and tel.state_resp_ok:
                    fuel_jump = tel.fuel_kg - prev_tel.fuel_kg
                    if (fuel_jump >= GameConfig.REFIT_FUEL_JUMP_KG and
                        tel.ias_kmh <= GameConfig.REFIT_SPEED_KMH and
                        abs(tel.vy_ms) <= GameConfig.REFIT_VSPEED_MS and
                        (now - s.last_refit_ts) >= GameConfig.REFIT_MIN_GAP_SEC):
                        s.sortie_id += 1
                        s.last_refit_ts = now
                        s.landing_start_time = None
                        s.landed_flash_until = 0.0

                # 着陆检测
                self._update_landing_locked(tel, now)
                
                # 死亡检测：玩家消失
                if not player_present:
                    s.phase = Phase.LOSS_PENDING
                    s.missing_player_since = now
                    s.spawn_candidate_since = None
                else:
                    s.missing_player_since = None

            elif s.phase == Phase.LOSS_PENDING:
                # 可能死亡 → 确认死亡（1.2秒）
                if player_present:
                    s.phase = Phase.ALIVE
                    s.missing_player_since = None
                else:
                    if s.missing_player_since is None:
                        s.missing_player_since = now
                    if (now - s.missing_player_since) >= GameConfig.DEAD_CONFIRM_SEC:
                        s.phase = Phase.WAIT_NEXT
                        s.spawn_candidate_since = None

            elif s.phase == Phase.WAIT_NEXT:
                # 等待复活 → 下次出生
                if spawn_candidate:
                    if s.spawn_candidate_since is None:
                        s.spawn_candidate_since = now
                    if (now - s.spawn_candidate_since) >= GameConfig.SPAWN_CONFIRM_SEC:
                        self._start_new_life_locked(now)
                        s.phase = Phase.ALIVE
                        self._clear_transient_state_locked()
                else:
                    s.spawn_candidate_since = None

    @staticmethod
    def _angle_delta_deg(current: float, previous: float) -> float:
        """计算两角度差值（映射到 [-180, 180] 后取绝对值）。"""
        return abs(normalize_angle(float(current) - float(previous)))

    @staticmethod
    def _map_axis_scale_m(map_info: Optional[MapInfo]) -> Optional[Tuple[float, float]]:
        """从 map_info 提取归一化坐标在 X/Y 轴对应的米制尺度。"""
        if map_info is None or not getattr(map_info, "valid", False):
            return None
        try:
            min_x, min_y = map_info.map_min
            max_x, max_y = map_info.map_max
            scale_x = abs(float(max_x) - float(min_x))
            scale_y = abs(float(max_y) - float(min_y))
            if scale_x <= 1e-6 or scale_y <= 1e-6:
                return None
            return scale_x, scale_y
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _distance_norm_from_delta(dx: float, dy: float, map_axis_scale_m: Optional[Tuple[float, float]]) -> float:
        """计算兼容旧语义的 distance（实际km / DISTANCE_SCALE）。"""
        dx = float(dx)
        dy = float(dy)
        if map_axis_scale_m is not None:
            moved_m = math.hypot(dx * map_axis_scale_m[0], dy * map_axis_scale_m[1])
            moved_km = moved_m / 1000.0
            return moved_km / ZoneConfig.DISTANCE_SCALE
        return math.hypot(dx, dy)

    @staticmethod
    def _bearing_distance_norm(
        px: float,
        py: float,
        tx: float,
        ty: float,
        map_axis_scale_m: Optional[Tuple[float, float]],
    ) -> Tuple[float, float]:
        """计算目标方位角与兼容距离值。"""
        dx = float(tx) - float(px)
        dy = float(ty) - float(py)
        if map_axis_scale_m is not None:
            dx_m = dx * map_axis_scale_m[0]
            dy_m = dy * map_axis_scale_m[1]
            bearing = (math.degrees(math.atan2(dx_m, -dy_m)) + 360.0) % 360.0
            distance_norm = GameLogic._distance_norm_from_delta(dx, dy, map_axis_scale_m)
            return bearing, distance_norm

        bearing = calculate_bearing(px, py, tx, ty)
        distance_norm = calculate_distance(px, py, tx, ty)
        return bearing, distance_norm

    def _update_attitude_confidence_locked(self, tel: TelemetryData, now: float) -> None:
        """更新姿态可信度（须在锁内调用）。"""
        att = self.state.attitude

        # 抖动分数自然衰减，避免单次异常长期影响。
        if att.last_sample_ts > 0:
            dt = max(0.0, now - att.last_sample_ts)
            if dt > 0:
                att.jitter_score = max(0.0, att.jitter_score - dt * self.ATTITUDE_JITTER_DECAY_PER_SEC)
        else:
            dt = 0.0

        available = bool(
            tel.attitude_available and
            tel.attitude_pitch_present and
            (tel.attitude_roll_present or tel.attitude_bank_present)
        )
        airborne = bool(tel.state_resp_ok and ((tel.ias_kmh > 120.0) or (tel.altitude_m > 150.0)))

        if available:
            pitch = float(tel.attitude_pitch_deg)
            lateral = float(tel.attitude_lateral_deg)

            att.pitch_deg = pitch
            att.roll_deg = lateral
            att.bank_deg = float(tel.attitude_bank_deg)
            att.available = True
            att.missing_since = None

            # 长期恒零检测（仅在空中启用，避免地面状态误判）。
            if airborne and abs(pitch) <= self.ATTITUDE_ZERO_EPS_DEG and abs(lateral) <= self.ATTITUDE_ZERO_EPS_DEG:
                if att.zero_since is None:
                    att.zero_since = now
            else:
                att.zero_since = None

            # 突变抖动检测：按角速度阈值累计分数。
            if dt > 0 and (att.last_pitch_deg is not None) and (att.last_roll_deg is not None):
                pitch_rate = self._angle_delta_deg(pitch, att.last_pitch_deg) / dt
                roll_rate = self._angle_delta_deg(lateral, att.last_roll_deg) / dt
                if pitch_rate >= self.ATTITUDE_JITTER_PITCH_RATE_DEG_S or roll_rate >= self.ATTITUDE_JITTER_ROLL_RATE_DEG_S:
                    att.jitter_score += 1.0

            att.last_pitch_deg = pitch
            att.last_roll_deg = lateral
            att.last_sample_ts = now
        else:
            att.available = False
            if att.missing_since is None:
                att.missing_since = now
            att.zero_since = None
            # 数据缺失时清理历史角速度基线，避免恢复后误判抖动。
            att.last_pitch_deg = None
            att.last_roll_deg = None
            att.last_sample_ts = now

        missing_unreliable = bool(
            (att.missing_since is not None) and
            ((now - att.missing_since) >= self.ATTITUDE_MISSING_CONFIRM_SEC)
        )
        zero_unreliable = bool(
            (att.zero_since is not None) and
            ((now - att.zero_since) >= self.ATTITUDE_ZERO_CONFIRM_SEC)
        )
        jitter_unreliable = bool(att.jitter_score >= self.ATTITUDE_JITTER_TRIGGER_SCORE)

        att.reliable = bool(available and (not zero_unreliable) and (not jitter_unreliable))
        att.fallback = not att.reliable

        if missing_unreliable or (not available):
            att.fallback_reason = "missing"
        elif zero_unreliable:
            att.fallback_reason = "stuck_zero"
        elif jitter_unreliable:
            att.fallback_reason = "jitter"
        else:
            att.fallback_reason = ""

    def _update_zone_navigation_locked(self, mp: MapObjData, tel: TelemetryData, now: float):
        """更新战区导航状态(须在锁内调用)
        
        功能: 计算地速/检测战区摧毁/计算导航信息/选择目标战区
        """
        nav = self.state.zone_nav
        
        if not mp.ok or not mp.player_pos:
            # 无数据时重置
            nav.zones = []
            nav.target_zone = None
            nav.is_deviating = False
            nav.last_pos = None
            nav.ground_speed = 0.0
            return
        
        px, py = mp.player_pos
        map_axis_scale_m = self._map_axis_scale_m(self.state.map_info)
        
        # 计算航向：
        # HUD/导航优先使用机头罗盘（更贴近驾驶视角），
        # 罗盘不可用时再回退到地速向量航向。
        heading = None
        if tel.ind_ok and math.isfinite(float(tel.compass)):
            heading = float(tel.compass) % 360.0
        if heading is None:
            heading = calculate_heading_from_vector(mp.player_dx, mp.player_dy)
        if heading is None:
            fallback_compass = float(tel.compass)
            if math.isfinite(fallback_compass):
                heading = fallback_compass % 360.0
        if heading is None:
            heading = 0.0
        nav.player_heading = heading
        
        # === 地速(SOG)计算 ===
        # 原理：通过位置微分计算真实地速，不受风速影响
        if nav.last_pos and tel.ias_kmh > 40:
            dt = now - nav.last_pos_ts
            
            # 限制计算频率（>0.4s），避免除法震荡
            if dt >= 0.4:
                dx = px - nav.last_pos[0]
                dy = py - nav.last_pos[1]
                dist_moved = self._distance_norm_from_delta(dx, dy, map_axis_scale_m)
                
                if dist_moved > 0:
                    current_speed = dist_moved / dt
                    
                    # 指数平滑滤波（EMA）
                    alpha = 0.2
                    if nav.ground_speed == 0:
                        nav.ground_speed = current_speed
                    else:
                        nav.ground_speed = (nav.ground_speed * (1 - alpha)) + (current_speed * alpha)
                
                nav.last_pos = (px, py)
                nav.last_pos_ts = now
        else:
            # 初始化或低速时
            if not nav.last_pos or (now - nav.last_pos_ts > 2.0):
                nav.last_pos = (px, py)
                nav.last_pos_ts = now
                if tel.ias_kmh <= 40:
                    nav.ground_speed = 0.0

        # === 战区被摧毁检测 ===
        current_zone_ids = {z.id for z in mp.zones}
        if nav.previous_zone_ids and current_zone_ids:
            destroyed_ids = nav.previous_zone_ids - current_zone_ids
            if destroyed_ids:
                # 找到被摧毁的战区
                destroyed = [z for z in nav.zones if z.id in destroyed_ids]
                if destroyed:
                    nav.destroyed_zones = destroyed
                    nav.destroyed_alert_until = now + ZoneConfig.DESTROYED_ALERT_SEC
                    
                    # v5.5: 判断是否有感兴趣的战区被摧毁
                    has_interesting = any(
                        self._is_zone_of_interest(z, nav.target_zone)
                        for z in destroyed
                    )
                    nav.should_play_destroyed_sound = has_interesting
                else:
                    nav.should_play_destroyed_sound = False
            else:
                nav.should_play_destroyed_sound = False
        nav.previous_zone_ids = current_zone_ids
        
        # === 计算所有战区的导航信息 ===
        zones_with_nav = []
        for zone in mp.zones:
            bearing, distance = self._bearing_distance_norm(px, py, zone.x, zone.y, map_axis_scale_m)
            relative = calculate_relative_bearing(heading, bearing)
            zones_with_nav.append(Zone(
                id=zone.id, index=zone.index, x=zone.x, y=zone.y,
                color=zone.color, distance=distance,
                bearing=bearing, relative=relative, is_target=False
            ))
        
        # 按距离排序
        zones_with_nav.sort(key=lambda z: z.distance)
        
        # [目标选择算法]
        # 核心原则:
        # 1. 目标粘性: 锁定后在90°内保持,避免频繁切换
        # 2. 精确对准优先: 持续对准(<5°)3秒后切换
        # 3. 角度优先于距离: ±45°内选角度最小的
        # 
        # 关键配置(ZoneConfig):
        # - HEADING_TOLERANCE=45 (角度门)
        # - TARGET_HOLD_ANGLE=90 (保持角度)
        # - PRECISE_AIM_THRESHOLD=5 (精确对准阈值)
        # - PRECISE_AIM_CONFIRM_SEC=3 (确认时间)
        
        # === 选择目标战区（v5.7改进：目标粘性 + 精确对准切换）===
        # === v5.9改进：角度门内优先选择角度最小的目标 ===
        target = None
        is_airborne = not tel.is_on_ground  # 判断是否在空中
        
        if is_airborne and zones_with_nav:
            # 创建ID到Zone的映射，方便查找
            zone_by_id = {z.id: z for z in zones_with_nav}
            
            # Step 1: 检查当前锁定目标是否仍然有效
            locked_zone = None
            if nav.locked_target_id and nav.locked_target_id in zone_by_id:
                locked_zone = zone_by_id[nav.locked_target_id]
                # 目标仍在前方（<90°）则保持
                if abs(locked_zone.relative) <= ZoneConfig.TARGET_HOLD_ANGLE:
                    target = locked_zone
                else:
                    # 目标超出视野，清除锁定
                    nav.locked_target_id = None
                    locked_zone = None
            else:
                # 目标消失，清除锁定
                nav.locked_target_id = None
            
            # Step 2: 检测精确对准（<5°）的候选目标
            # ⚠️ 从精确对准范围内选择角度最小的目标（不是距离最近的）
            precise_candidates = [z for z in zones_with_nav 
                                  if abs(z.relative) <= ZoneConfig.PRECISE_AIM_THRESHOLD]
            precise_candidate = None
            if precise_candidates:
                # 按角度排序，选择角度最小的
                precise_candidate = min(precise_candidates, key=lambda z: abs(z.relative))
            
            if precise_candidate:
                # 检查是否是新的候选目标
                if nav.precise_aim_candidate_id != precise_candidate.id:
                    # 新候选，重置计时
                    nav.precise_aim_candidate_id = precise_candidate.id
                    nav.precise_aim_since = now
                else:
                    # 相同候选，检查是否超过确认时间
                    aim_duration = now - nav.precise_aim_since
                    if aim_duration >= ZoneConfig.PRECISE_AIM_CONFIRM_SEC:
                        # 确认切换到新目标
                        if nav.locked_target_id != precise_candidate.id:
                            nav.locked_target_id = precise_candidate.id
                            target = precise_candidate
            else:
                # 没有精确对准的目标，清除候选
                nav.precise_aim_candidate_id = None
                nav.precise_aim_since = 0.0
            
            # Step 3: 如果还没有目标，从45°角度门内选择角度最小的
            # ⚠️ 优先角度最小，而不是距离最近
            if target is None:
                candidates_in_gate = [z for z in zones_with_nav 
                                      if abs(z.relative) <= ZoneConfig.HEADING_TOLERANCE]
                if candidates_in_gate:
                    # 按角度排序，选择角度最小的
                    best_candidate = min(candidates_in_gate, key=lambda z: abs(z.relative))
                    target = best_candidate
                    nav.locked_target_id = best_candidate.id
        else:
            # 在地面或无战区时，清除所有锁定状态
            nav.locked_target_id = None
            nav.precise_aim_candidate_id = None
            nav.precise_aim_since = 0.0
        
        # 标记目标
        if target:
            for i, zone in enumerate(zones_with_nav):
                if zone.id == target.id:
                    zones_with_nav[i] = Zone(
                        id=zone.id, index=zone.index, x=zone.x, y=zone.y,
                        color=zone.color, distance=zone.distance,
                        bearing=zone.bearing, relative=zone.relative, is_target=True
                    )
                    target = zones_with_nav[i]
                    break
        
        nav.zones = zones_with_nav
        nav.target_zone = target
        nav.is_deviating = (abs(target.relative) > ZoneConfig.DEVIATION_WARNING) if target else False

    def _is_zone_of_interest(self, zone: Zone, target_zone: Optional[Zone]) -> bool:
        """判断战区是否是玩家感兴趣的（v5.5新增）
        
        判断标准：
        1. 是当前目标战区 → 关注
        2. 后方战区（>90°）→ 不关注
        3. 前方近距离战区：≤75° 且 <35km → 关注
        4. 正前方中距离战区：≤45° 且 <60km → 关注
        
        Args:
            zone: 待判断的战区
            target_zone: 当前目标战区
        
        Returns:
            True 表示该战区是感兴趣的
        """
        # 1. 是当前目标战区
        if target_zone and zone.id == target_zone.id:
            return True
        
        abs_relative = abs(zone.relative)
        
        # 2. 后方战区（>90°）不关注
        if abs_relative > 90:
            return False
        
        # 3. 前方战区需要结合距离判断
        distance_km = zone.distance * ZoneConfig.DISTANCE_SCALE
        
        # 前方近距离：≤75° 且 <35km
        if abs_relative <= 75 and distance_km < 35:
            return True
        
        # 正前方中距离：≤45° 且 <60km
        if abs_relative <= 45 and distance_km < 60:
            return True
        
        # 其他情况（前方远距离或大角度）不关注
        return False

    def manual_reset(self):
        """手动重置计时器

        将当前生命的出生时间设为现在，重启15分钟周期。
        """
        with self._lock:
            if self.state.phase == Phase.ALIVE and self.state.current_life:
                self.state.current_life.spawn_time = time.time()
                self.state.landing_start_time = None
                self.state.landed_flash_until = 0.0

    def save_timer_state(self):
        """保存计时器状态到文件
        
        用于应用退出时保存进度。
        """
        with self._lock:
            if self.state.phase != Phase.ALIVE or not self.state.current_life:
                StateManager.clear()
                return
            now = time.time()
            remaining = self.state.current_life.cycle_remaining(now)
            StateManager.save(remaining, self.state.current_life.life_index, self.state.sortie_id)

    def restore_timer_state(self) -> bool:
        """从文件恢复计时器状态
        
        Returns:
            是否成功恢复
        """
        data = StateManager.load()
        if not data:
            return False
        
        with self._lock:
            self.state.current_life = LifeState(
                spawn_time=data['computed_spawn_time'],
                life_index=data.get('life_index', 1)
            )
            self.state.sortie_id = data.get('sortie_id', 0)
            self.state.phase = Phase.ALIVE
            self.state.last_refit_ts = data['computed_spawn_time']
            self.state.last_player_present_ts = time.time()
            self._schedule_clog_probe_locked(time.time(), self.state.current_life.life_index)
        return True

    def snapshot(self) -> UISnapshot:
        """生成UI快照（线程安全）
        
        将当前游戏状态转换为不可变的UISnapshot对象。
        这是逻辑层与UI层的唯一数据通道。
        
        Returns:
            UISnapshot对象
        """
        now = time.time()
        with self._lock:
            s = self.state
            tel = s.last_tel or TelemetryData()
            mp = s.last_map or MapObjData()
            life = s.current_life
            attitude = s.attitude
            
            # 计算时间相关
            remaining = None
            cycle = None
            progress = 0.0
            life_index = life.life_index if life else None

            if s.phase in (Phase.ALIVE, Phase.LOSS_PENDING) and life:
                remaining = life.cycle_remaining(now)
                cycle = life.current_cycle(now)
                progress = life.cycle_progress(now)

            # 确定主徽章和状态文字
            api_down_pending = False
            if (s.api_down_candidate_since is not None) and (not s.api_down):
                api_down_pending = (
                    (now - s.api_down_candidate_since) >= GameConfig.API_PENDING_HINT_DELAY_SEC
                )

            if s.api_down:
                main_badge = ("❌8111不可用", Theme.TEXT, Theme.RED)
                status_text = "未检测到 8111"
            elif api_down_pending and (s.phase in (Phase.IDLE, Phase.HANGAR, Phase.ARMING) or not life):
                main_badge = ("⏳加入战斗中", Theme.TEXT, Theme.BLUE)
                status_text = "加入战斗中"
            else:
                if s.phase == Phase.ALIVE:
                    main_badge = ("战斗中", Theme.TEXT, Theme.GREEN)
                    status_text = "计时中"
                elif s.phase == Phase.WAIT_NEXT:
                    main_badge = ("等待复活", Theme.TEXT, Theme.YELLOW)
                    status_text = "等待复活"
                elif s.phase == Phase.LOSS_PENDING:
                    main_badge = ("坠毁/弹射", Theme.TEXT, Theme.YELLOW)
                    status_text = "坠毁/弹射"
                elif s.phase == Phase.ARMING:
                    main_badge = ("部署中", Theme.TEXT, Theme.BLUE)
                    status_text = "部署中"
                elif s.phase == Phase.HANGAR:
                    main_badge = ("🏠机库", Theme.TEXT, Theme.GRAYPILL)
                    status_text = "等待游戏开始"
                else:
                    main_badge = ("IDLE", Theme.TEXT, Theme.GRAYPILL)
                    status_text = "等待中"

            # 飞行徽章
            landed_flash = s.landed_flash_until > now
            on_ground = tel.is_on_ground if tel.state_resp_ok else False

            if s.phase not in (Phase.ALIVE, Phase.LOSS_PENDING) or not life:
                flight_badge = ("—", Theme.TEXT_DIM, Theme.GRAYPILL)
            else:
                if landed_flash:
                    flight_badge = ("就绪✓", Theme.TEXT, Theme.GREEN)
                else:
                    flight_badge = ("着陆中", Theme.TEXT_DIM, Theme.GRAYPILL) if on_ground else ("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL)

            # v6.9.0 新增：超速判定（IAS/Mach 双通道）
            overspeed = self.overspeed.evaluate(
                plane_type=tel.type_name,
                ias_kmh=tel.ias_kmh,
                tas_kmh=tel.tas_kmh,
                mach=tel.mach,
                wing_sweep=tel.wing_sweep,
                enabled=(
                    OverspeedConfig.ENABLED and
                    PanelConfig.show_speed and
                    (s.phase in (Phase.ALIVE, Phase.LOSS_PENDING)) and
                    tel.state_resp_ok and
                    (not on_ground)
                ),
            )

            if s.phase == Phase.ALIVE:
                if overspeed.level == "critical":
                    status_text = "超速危险，立即减速"
                elif overspeed.level == "warning":
                    status_text = "接近结构极限"

            # 调试信息
            player_present = bool(mp.ok and mp.player_aircraft_present)
            ratio_dbg = (overspeed.ias_ratio * 100.0) if overspeed.ias_ratio is not None else 0.0
            lim_ias_dbg = overspeed.ias_limit_kmh or 0.0
            lim_mach_dbg = overspeed.mach_limit or 0.0
            clog_status = s.clog_probe_status
            clog_players = s.clog_probe_player_count
            clog_names = ",".join(s.clog_probe_players) if s.clog_probe_players else "-"
            clog_err = s.clog_probe_error[:24] if s.clog_probe_error else "-"
            diag_lines = [
                f"MAP: ok={int(mp.ok)} | objs={mp.obj_count} | player={int(player_present)}",
                f"IND: ok={int(tel.ind_ok)} | valid={int(tel.valid)} | type={'✓' if tel.type_name else '✗'}",
                f"STATE: ok={int(tel.state_resp_ok)} | fuel={tel.fuel_kg:.0f}kg | ias={tel.ias_kmh:.0f}km/h",
                f"SPD: lvl={overspeed.level} | ratio={ratio_dbg:.1f}% | lim={lim_ias_dbg:.0f}km/h M{lim_mach_dbg:.3f}",
                f"ATT: ok={int(attitude.available)} | rel={int(attitude.reliable)} | fb={attitude.fallback_reason or '-'}",
                f"CLOG: st={clog_status} | players={clog_players} | names={clog_names} | err={clog_err}",
            ]
            diag = "\n".join(diag_lines)

            # 战区导航信息
            nav = s.zone_nav
            zone_display_list = []
            gs = nav.ground_speed
            map_axis_scale_m = self._map_axis_scale_m(s.map_info)

            for zone in nav.zones[:ZoneConfig.MAX_DISPLAY_ZONES]:
                # ETE计算（仅目标战区）
                ete_text = ""
                if zone.is_target and gs > 1e-7:
                    seconds_left = zone.distance / gs
                    if seconds_left < 5999:
                        m, s_time = divmod(int(seconds_left), 60)
                        ete_text = f"{m:02d}:{s_time:02d}"
                
                # CDI指示器（仅目标战区显示）
                cdi_str = ""
                cdi_clr = ""
                if zone.is_target:
                    # 转换距离单位为公里
                    dist_km = zone.distance * ZoneConfig.DISTANCE_SCALE
                    # 接收函数返回的两个值：指示器字符串和颜色
                    cdi_str, cdi_clr = generate_cdi_indicator(zone.relative, dist_km)

                # 所有战区都添加到显示列表（CDI仅目标战区有值）
                zone_display_list.append(ZoneDisplayInfo(
                    id=zone.id,
                    distance_km=zone.distance * ZoneConfig.DISTANCE_SCALE,
                    direction=get_direction_text(zone.relative), 
                    relative=zone.relative, is_target=zone.is_target,
                    ete_str=ete_text,
                    cdi_indicator=cdi_str,
                    cdi_color=cdi_clr
                ))
            
            # 机场导航信息
            friendly_airfield_display = None
            enemy_airfields_display: List[AirfieldDisplayInfo] = []
            has_airfield_target = False

            if mp.ok and mp.player_pos and getattr(mp, "airfields", None):
                px, py = mp.player_pos
                heading = nav.player_heading

                friendly_infos: List[Tuple[float, AirfieldDisplayInfo]] = []
                enemy_infos: List[Tuple[float, AirfieldDisplayInfo]] = []

                for af in mp.airfields:
                    if (not math.isfinite(float(af.x))) or (not math.isfinite(float(af.y))):
                        continue

                    bearing, distance = self._bearing_distance_norm(px, py, af.x, af.y, map_axis_scale_m)
                    relative = calculate_relative_bearing(heading, bearing)
                    info = AirfieldDisplayInfo(
                        id=af.id,
                        side="friendly" if af.is_friendly else "enemy",
                        distance_km=distance * ZoneConfig.DISTANCE_SCALE,
                        direction=get_direction_text(relative),
                        relative=relative,
                        is_target=False,
                        ete_str=""
                    )
                    if af.is_friendly:
                        friendly_infos.append((distance, info))
                    else:
                        enemy_infos.append((distance, info))

                # 友方机场：只显示最近的
                if friendly_infos:
                    friendly_infos.sort(key=lambda t: t[0])
                    dist, info = friendly_infos[0]
                    ete_text = ""
                    # 只在航向前方（±90°）显示ETE
                    if abs(info.relative) <= 90 and nav.ground_speed > 1e-7:
                        seconds_left = dist / nav.ground_speed
                        if seconds_left < 3600:
                            mm, ss = divmod(int(seconds_left), 60)
                            ete_text = f"{mm:02d}:{ss:02d}"
                    # CDI指示器（友方机场始终显示）
                    cdi_str, cdi_clr = generate_cdi_indicator(info.relative, info.distance_km)
                    friendly_airfield_display = AirfieldDisplayInfo(
                        id=info.id, side=info.side,
                        distance_km=info.distance_km, direction=info.direction, 
                        relative=info.relative,
                        is_target=True, ete_str=ete_text,
                        cdi_indicator=cdi_str, cdi_color=cdi_clr
                    )

                # 敌方机场：显示部分（上限），但只在朝向时显示ETE（v5.7改进）
                if enemy_infos:
                    enemy_infos.sort(key=lambda t: t[0])
                    max_total = ZoneConfig.MAX_DISPLAY_AIRFIELDS
                    max_enemy = max(0, max_total - (1 if friendly_infos else 0))
                    if max_enemy == 0:
                        enemy_infos = []
                    else:
                        enemy_infos = enemy_infos[:max_enemy]
                    # 查找45°内最近的敌方机场作为目标
                    target_idx = -1  # -1表示没有目标
                    for i, (dist, info) in enumerate(enemy_infos):
                        if abs(info.relative) <= ZoneConfig.ENEMY_AIRFIELD_ETE_ANGLE:
                            target_idx = i
                            break

                    for i, (dist, info) in enumerate(enemy_infos):
                        is_target = (i == target_idx)
                        ete_text = ""
                        cdi_str = ""
                        cdi_clr = ""
                        # 只在目标机场且在航向前方（<45°）时显示ETE和CDI
                        if is_target and abs(info.relative) <= ZoneConfig.ENEMY_AIRFIELD_ETE_ANGLE and nav.ground_speed > 1e-7:
                            seconds_left = dist / nav.ground_speed
                            if seconds_left < 3600:
                                mm, ss = divmod(int(seconds_left), 60)
                                ete_text = f"{mm:02d}:{ss:02d}"
                            cdi_str, cdi_clr = generate_cdi_indicator(info.relative, info.distance_km)
                        enemy_airfields_display.append(AirfieldDisplayInfo(
                            id=info.id, side=info.side,
                            distance_km=info.distance_km, direction=info.direction, 
                            relative=info.relative,
                            is_target=is_target, ete_str=ete_text,
                            cdi_indicator=cdi_str, cdi_color=cdi_clr
                        ))
                    has_airfield_target = (target_idx >= 0)
            
            has_target = nav.target_zone is not None
            deviation_angle = nav.target_zone.relative if nav.target_zone else 0.0
            
            # 战区被摧毁警告
            zone_destroyed_alert = nav.destroyed_alert_until > now
            destroyed_count = len(nav.destroyed_zones) if zone_destroyed_alert else 0
            destroyed_zone_text = ""
            
            # v5.4.2: 实时计算被摧毁战区的位置信息（不显示格子坐标）
            if zone_destroyed_alert and nav.destroyed_zones:
                items = []
                has_pos = mp.player_pos is not None
                if has_pos:
                    px, py = mp.player_pos
                    for dz in nav.destroyed_zones:
                        try:
                            bearing, dist_norm = self._bearing_distance_norm(px, py, dz.x, dz.y, map_axis_scale_m)
                            dist_km = dist_norm * ZoneConfig.DISTANCE_SCALE
                            if nav.player_heading is not None:
                                rel = calculate_relative_bearing(nav.player_heading, bearing)
                                dir_text = get_direction_text(rel)
                                items.append(f"#{dz.index} {dir_text} {dist_km:.1f}km")
                            else:
                                items.append(f"#{dz.index} {dist_km:.1f}km")
                        except Exception:
                            items.append(f"#{dz.index}")
                else:
                    for dz in nav.destroyed_zones:
                        items.append(f"#{dz.index}")
                destroyed_zone_text = "  |  ".join(items)

            # v5.8 新增：燃油管理数据
            fuel = s.fuel_state
            fuel_kg = fuel.current_kg
            fuel_initial_kg = fuel.initial_kg
            fuel_percent = fuel.fuel_percent
            fuel_rate_kg_min = fuel.consumption_rate if fuel.rate_stable else 0.0
            fuel_rate_stable = fuel.rate_stable
            altitude_m = tel.altitude_m
            
            # 剩余飞行时间字符串
            fuel_time_remaining_str = ""
            remaining_min = fuel.remaining_time_min
            if remaining_min is not None:
                if remaining_min > 60:
                    fuel_time_remaining_str = ">60:00"
                else:
                    rm, rs = divmod(int(remaining_min * 60), 60)
                    fuel_time_remaining_str = f"{rm:02d}:{rs:02d}"
            
            # 返航估算
            return_fuel_needed_kg = 0.0
            return_status = "unknown"
            friendly_distance_km = 0.0
            
            if friendly_airfield_display and nav.ground_speed > 0:
                friendly_distance_km = friendly_airfield_display.distance_km
                # 将地速转换为 km/h
                ground_speed_kmh = nav.ground_speed * ZoneConfig.DISTANCE_SCALE * 3600
                return_fuel_needed = fuel.estimate_return_fuel(friendly_distance_km, ground_speed_kmh)
                if return_fuel_needed is not None:
                    return_fuel_needed_kg = return_fuel_needed
                    return_status = fuel.get_return_status(return_fuel_needed)
            
            # v5.9.6 新增：起落架警告判断
            # 判断条件：在空中（速度>80km/h 或 高度>50m）且起落架未收起
            gear_warning = False
            if s.phase == Phase.ALIVE and tel.state_resp_ok:
                is_airborne = (tel.ias_kmh > 80) or (tel.altitude_m > 50)
                # gear_down=True 表示起落架放下（未收起）
                if is_airborne and tel.gear_down:
                    gear_warning = True
            
            # v6.6.0 新增：起落架进度指示器
            # v6.6.1: 添加消抖 - 变化超过2%且持续100ms才更新
            # v6.6.3: 修复方向判断 - 使用前后帧比较而非与初始值比较
            raw_gear_pct = tel.gear_pct
            gear_pct = s.gear_stable_pct if s.gear_stable_pct >= 0 else raw_gear_pct
            gear_retracting = s.gear_stable_direction
            
            # 首次初始化：确保状态变量有正确的起始值
            if s.last_gear_pct < 0:
                s.last_gear_pct = raw_gear_pct
                s.gear_stable_pct = raw_gear_pct
                gear_pct = raw_gear_pct
            
            # 检测变化并消抖
            pct_diff = abs(raw_gear_pct - s.gear_stable_pct)
            if pct_diff > 2.0:  # 变化超过2%
                if s.gear_change_time == 0.0:
                    s.gear_change_time = now
                elif now - s.gear_change_time > 0.1:  # 持续100ms
                    # v6.6.3 修复：使用前后帧比较判断方向
                    # raw_gear_pct 减小 = 收起（从100向0）
                    # raw_gear_pct 增大 = 放下（从0向100）
                    gear_retracting = (raw_gear_pct < s.last_gear_pct)
                    gear_pct = raw_gear_pct
                    s.gear_stable_pct = raw_gear_pct
                    s.gear_stable_direction = gear_retracting
                    s.gear_change_time = 0.0
            else:
                s.gear_change_time = 0.0
                # 小幅度波动时平滑更新
                if pct_diff > 0.5:
                    gear_pct = raw_gear_pct
                    s.gear_stable_pct = raw_gear_pct
            
            delta = raw_gear_pct - s.last_gear_pct
            if abs(delta) >= 0.5:
                gear_retracting = (delta < 0)
                s.gear_stable_direction = gear_retracting
            gear_moving = (0 < raw_gear_pct < 100)
            if not gear_moving:
                gear_retracting = False
            s.last_gear_pct = raw_gear_pct

            # v6.0.1 优化：从缓存读取弹道计算结果（计算已移至tick线程）
            bombing_valid = False
            bomb_name = BombConfig.selected_bomb if ENABLE_CCRP else ""
            bomb_range_m = 0.0
            bomb_flight_time = 0.0
            release_distance_m = 0.0
            time_to_release = 0.0
            release_status = "invalid"
            target_zone_distance_m = 0.0
            ground_speed_kmh_for_bombing = nav.ground_speed * ZoneConfig.DISTANCE_SCALE * 3600
            
            # 从缓存读取弹道计算结果（避免在UI线程重复计算）
            if ENABLE_CCRP and s.bombing_calc_valid:
                bombing_valid = True
                bomb_flight_time = s.cached_bomb_flight_time
                bomb_range_m = s.cached_bomb_range_m
                release_distance_m = s.cached_release_distance_m
                time_to_release = s.cached_time_to_release
                release_status = s.cached_release_status
                target_zone_distance_m = s.cached_target_distance_m

            mach_ratio_dbg = None
            try:
                if (
                    overspeed.mach is not None
                    and overspeed.mach_limit is not None
                    and float(overspeed.mach_limit) > 0.0
                ):
                    mach_ratio_dbg = float(overspeed.mach) / float(overspeed.mach_limit)
            except Exception:
                mach_ratio_dbg = None
            overspeed_display_ratio = max(
                [r for r in (overspeed.ias_ratio, mach_ratio_dbg) if r is not None] or [0.0]
            )

            return UISnapshot(
                phase=s.phase, life_index=life_index, cycle=cycle, 
                remaining_sec=remaining, progress=progress, sortie_id=s.sortie_id, 
                main_badge=main_badge, flight_badge=flight_badge,
                status_text=status_text, diag_text=diag, 
                api_down=s.api_down, api_down_pending=api_down_pending,
                on_ground=on_ground, landed_flash=landed_flash, 
                zones=zone_display_list, 
                friendly_airfield=friendly_airfield_display, 
                enemy_airfields=enemy_airfields_display, 
                has_airfield_target=has_airfield_target, 
                has_target=has_target,
                is_deviating=nav.is_deviating, 
                deviation_angle=deviation_angle, 
                zone_destroyed_alert=zone_destroyed_alert,
                destroyed_zone_count=destroyed_count, 
                destroyed_zone_text=destroyed_zone_text,
                should_play_destroyed_sound=nav.should_play_destroyed_sound,
                player_heading=nav.player_heading,
                # v5.8 新增：燃油管理字段
                fuel_kg=fuel_kg,
                fuel_initial_kg=fuel_initial_kg,
                fuel_percent=fuel_percent,
                fuel_rate_kg_min=fuel_rate_kg_min,
                fuel_rate_stable=fuel_rate_stable,
                fuel_time_remaining_str=fuel_time_remaining_str,
                altitude_m=altitude_m,
                return_fuel_needed_kg=return_fuel_needed_kg,
                return_status=return_status,
                friendly_distance_km=friendly_distance_km,
                # v5.9.6 新增：起落架警告
                gear_warning=gear_warning,
                # v6.6.0 新增：起落架进度指示器
                gear_pct=gear_pct,
                gear_moving=gear_moving,
                gear_retracting=gear_retracting,
                # v6.0 新增：投弹预测
                bombing_valid=bombing_valid,
                bomb_name=bomb_name,
                bomb_range_m=bomb_range_m,
                bomb_flight_time=bomb_flight_time,
                release_distance_m=release_distance_m,
                time_to_release=time_to_release,
                release_status=release_status,
                target_zone_distance_m=target_zone_distance_m,
                ground_speed_kmh=ground_speed_kmh_for_bombing,
                aircraft_type_name=str(tel.type_name or ""),
                attitude_pitch_deg=attitude.pitch_deg,
                attitude_roll_deg=attitude.roll_deg,
                attitude_bank_deg=attitude.bank_deg,
                attitude_reliable=attitude.reliable,
                hud_attitude_fallback=attitude.fallback,
                hud_attitude_fallback_reason=attitude.fallback_reason,
                overspeed_level=overspeed.level,
                overspeed_ratio=float(overspeed.ias_ratio or 0.0),
                overspeed_display_ratio=float(overspeed_display_ratio or 0.0),
                overspeed_current_ias_kmh=float(overspeed.ias_kmh or 0.0),
                overspeed_current_mach=(
                    float(overspeed.mach) if overspeed.mach is not None else None
                ),
                overspeed_limit_kmh=float(overspeed.ias_limit_kmh or 0.0),
                overspeed_limit_mach=float(overspeed.mach_limit or 0.0),
                overspeed_match=bool(overspeed.resolved_fm),
                overspeed_reason=overspeed.reason,
            )

    def _start_new_life_locked(self, now: float):
        """开始新的生命（必须在锁内调用）"""
        s = self.state
        next_index = 1 if not s.current_life else (s.current_life.life_index + 1)
        s.current_life = LifeState(spawn_time=now, life_index=next_index)
        s.sortie_id += 1
        s.last_refit_ts = now
        s.last_player_present_ts = now
        s.attitude = AttitudeConfidenceState()
        self._schedule_clog_probe_locked(now, next_index)

    def _reset_life_state_locked(self):
        """重置生命状态（必须在锁内调用）"""
        s = self.state
        s.current_life = None
        s.sortie_id = 0
        s.last_refit_ts = 0.0
        s.spawn_candidate_since = None
        s.missing_player_since = None
        s.last_player_present_ts = 0.0
        s.landing_start_time = None
        s.landed_flash_until = 0.0
        s.zone_nav = ZoneNavigationState()
        s.attitude = AttitudeConfidenceState()
        s.map_info = None
        s.fuel_state.reset()  # v5.8 新增：重置燃油状态
        if self._is_clog_probe_enabled():
            s.clog_probe_status = "idle"
        else:
            s.clog_probe_status = "disabled"
        s.clog_probe_life_index = 0
        s.clog_probe_scheduled_at = None
        s.clog_probe_last_run_ts = 0.0
        s.clog_probe_player_count = 0
        s.clog_probe_players = []
        s.clog_probe_error = ""

    def _clear_transient_state_locked(self):
        """清除瞬态状态（必须在锁内调用）"""
        s = self.state
        s.spawn_candidate_since = None
        s.missing_player_since = None
        s.landing_start_time = None
        s.landed_flash_until = 0.0

    def _update_landing_locked(self, tel: TelemetryData, now: float):
        """更新着陆状态（必须在锁内调用）
        
        着陆判断：低速3秒 → 触发"就绪"闪烁10秒
        """
        s = self.state
        if not s.current_life:
            return

        # /state 失败时不要用默认零值参与着陆判断，避免误判为“在地面”。
        if not tel.state_resp_ok:
            return
        
        if tel.is_on_ground:
            if s.landing_start_time is None:
                s.landing_start_time = now
            elif (now - s.landing_start_time) >= GameConfig.LAND_CONFIRM_SEC:
                if s.landed_flash_until <= now:
                    s.landed_flash_until = now + GameConfig.LANDED_FLASH_SEC
        else:
            s.landing_start_time = None
    def _update_bombing_calculation_locked(self, tel: TelemetryData, now: float):
        """更新弹道计算缓存（必须在锁内调用）
        
        v6.0.1 优化：将弹道计算从UI线程(50ms)移至tick线程(250ms)
        减少UI线程的计算负载，提高界面流畅度
        """
        s = self.state
        nav = s.zone_nav
        
        # 检查是否需要计算
        if not ENABLE_CCRP:
            s.bombing_calc_valid = False
            return
        
        # 计算频率控制：至少间隔200ms
        if (now - s.last_bombing_calc_time) < 0.2:
            return
        
        s.last_bombing_calc_time = now
        
        # 检查计算条件
        has_target = nav.target_zone is not None
        on_ground = tel.is_on_ground
        altitude_m = tel.altitude_m
        
        if not (has_target and s.phase == Phase.ALIVE and 
                not on_ground and altitude_m > 50 and 
                nav.ground_speed > 0.0002):
            s.bombing_calc_valid = False
            return
        
        # 执行弹道计算
        target_zone = nav.target_zone
        target_distance_m = target_zone.distance * ZoneConfig.DISTANCE_SCALE * 1000
        ground_speed_ms = nav.ground_speed * ZoneConfig.DISTANCE_SCALE * 1000
        
        bomb_params = BombConfig.get_bomb_physics_params()
        
        flight_time, bomb_range_m, _ = calculate_bomb_trajectory(
            release_alt_m=altitude_m,
            release_speed_ms=ground_speed_ms,
            target_alt_m=0.0,
            dive_angle_deg=0.0,
            initial_vz_ms=None,
            bomb_params=bomb_params
        )
        
        if bomb_range_m > 0:
            release_distance_m, time_to_release, release_status = calculate_release_timing(
                current_distance_m=target_distance_m,
                current_alt_m=altitude_m,
                ground_speed_ms=ground_speed_ms,
                target_alt_m=0.0,
                dive_angle_deg=0.0,
                initial_vz_ms=None
            )
            
            # 缓存结果
            s.cached_bomb_flight_time = flight_time
            s.cached_bomb_range_m = bomb_range_m
            s.cached_release_distance_m = release_distance_m
            s.cached_time_to_release = time_to_release
            s.cached_release_status = release_status
            s.cached_target_distance_m = target_distance_m
            s.bombing_calc_valid = True
        else:
            s.bombing_calc_valid = False
