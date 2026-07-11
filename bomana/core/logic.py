"""Game logic core."""

import math
import threading
import time
from typing import Any

import requests

from bomana.config.feature_profile import ENABLE_CCRP
from bomana.config.settings import (
    BombConfig,
    FuelConfig,
    GameConfig,
    NetworkConfig,
    OverspeedConfig,
    PanelConfig,
    ZoneConfig,
)
from bomana.core import ccrp_scheduler, lifecycle, navigation, timing_store, weapon_scheduler
from bomana.core import diagnostics as core_diagnostics
from bomana.core.ballistics import calculate_bomb_trajectory, calculate_release_timing_from_range
from bomana.core.clock import SystemClock, WallClock
from bomana.core.overspeed import OverspeedAnalyzer
from bomana.core.state import (
    AirfieldDisplayInfo,
    BombingTarget,
    GameState,
    InterestPoint,
    LifeState,
    MapObjData,
    NavigationPointDisplayInfo,
    PerfDebugInfo,
    Phase,
    SourceDebugInfo,
    TacticalMapPoint,
    TelemetryData,
    TracebackSite,
    UISnapshot,
    WeaponTarget,
    Zone,
    ZoneDisplayInfo,
)
from bomana.core.telemetry import (
    Budget,
    HttpJson,
    MapInfoFetcher,
    MapObjectsFetcher,
    TelemetryFetcher,
)
from bomana.core.weapon_catalog import WeaponCatalogError, get_weapon_catalog
from bomana.core.weapon_solver import WeaponSolver, uses_existing_ccrp
from bomana.utils.diagnostics import log_event
from bomana.utils.file_utils import StateManager
from bomana.utils.math_utils import (
    calculate_heading_from_vector,
    calculate_relative_bearing,
    generate_cdi_indicator,
    get_direction_text,
)

# ============================================================================
# 游戏逻辑核心
# ============================================================================


def _target_radial_aspect_cosine(
    px: float,
    py: float,
    tx: float,
    ty: float,
    target_dx: float | None,
    target_dy: float | None,
    map_axis_scale_m: tuple[float, float] | None,
) -> float | None:
    """Return 2D target heading projected onto shooter-to-target LOS.

    ``+1`` is directly away (tail chase), ``-1`` directly approaching
    (head-on).  The 8111 ``dx``/``dy`` pair is a heading vector, not speed.
    """

    if target_dx is None or target_dy is None:
        return None
    try:
        los_x = float(tx) - float(px)
        los_y = float(ty) - float(py)
        direction_x = float(target_dx)
        direction_y = float(target_dy)
    except TypeError, ValueError:
        return None
    if map_axis_scale_m is not None:
        scale_x, scale_y = map_axis_scale_m
        los_x *= scale_x
        los_y *= scale_y
        direction_x *= scale_x
        direction_y *= scale_y
    los_norm = math.hypot(los_x, los_y)
    direction_norm = math.hypot(direction_x, direction_y)
    if los_norm <= 1e-9 or direction_norm <= 1e-9:
        return None
    value = (los_x * direction_x + los_y * direction_y) / (los_norm * direction_norm)
    return max(-1.0, min(1.0, value))


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

    def __init__(self, *, clock: WallClock | None = None, http: HttpJson | None = None):
        self._lock = threading.Lock()
        self.clock = clock or SystemClock()
        self.session: requests.Session | None = None
        if http is None:
            self.session = requests.Session()
            # 性能优化：禁用代理环境检查，减少每次请求的开销
            self.session.trust_env = False
            self.http = HttpJson(self.session)
        else:
            self.http = http
        self.tel = TelemetryFetcher(self.http)
        self.map_info_fetcher = MapInfoFetcher(self.http, now=self.clock.time)
        self.map = MapObjectsFetcher(self.http)
        self.overspeed = OverspeedAnalyzer()
        self.weapon_catalog = None
        self.weapon_solver = WeaponSolver() if ENABLE_CCRP else None
        if ENABLE_CCRP:
            try:
                self.weapon_catalog = get_weapon_catalog()
            except WeaponCatalogError:
                # A missing/tampered Enhanced-only catalog is surfaced in the snapshot.
                # Standard/Lite never enter this branch and do not load Enhanced assets.
                self.weapon_catalog = None
        self.state = GameState()
        if ENABLE_CCRP and self.weapon_catalog is None:
            self.state.weapon_reason = "catalog_unavailable"
            self.state.weapon_selection_source = "unknown"
        self._endpoint_diag_state: dict[str, int] = {}
        self._pending_timer_restore: dict[str, Any] | None = None
        self.timer_restore_applied = False

    @property
    def is_api_down(self) -> bool:
        """轻量级API状态检查（用于轮询间隔控制）

        避免在_poll_loop中生成完整snapshot只为检查api_down状态。
        """
        with self._lock:
            return self.state.api_down

    def tick(self) -> None:
        """主逻辑循环（每250ms执行一次）

        流程：
        1. 获取遥测数据
        2. 获取/缓存地图元数据
        3. 获取地图对象
        4. 更新游戏状态（状态机）
        5. 更新导航信息
        """
        tick_start = time.monotonic()
        now = self.clock.time()
        budget = Budget(NetworkConfig.MAX_TICK_NET_BUDGET)
        bombing_work: dict[str, Any] | None = None
        bombing_selection_token: tuple[str, str] | None = None
        weapon_work: dict[str, Any] | None = None

        # 1. 获取遥测数据
        tel = self.tel.fetch(budget)
        raw_tel = tel

        # 2. 检查是否需要更新地图元数据（30秒缓存）
        map_info_result = None
        with self._lock:
            map_info = self.state.map_info
            need_map_info = (
                map_info is None
                or not map_info.valid
                or (now - map_info.fetch_time) > ZoneConfig.MAP_INFO_CACHE_SEC
            )

        if need_map_info and budget.remaining() > 0.05:
            new_map_info = self.map_info_fetcher.fetch(budget)
            map_info_result = self.map_info_fetcher.last_result
            if new_map_info:
                with self._lock:
                    self.state.map_info = new_map_info
                    map_info = new_map_info
                    self.state.map_info_error_kind = ""
                    self.state.map_info_elapsed_ms = map_info_result.elapsed_ms
            else:
                with self._lock:
                    self.state.map_info_error_kind = map_info_result.error_kind
                    self.state.map_info_elapsed_ms = map_info_result.elapsed_ms

        # 3. 获取地图对象
        mp = self.map.fetch(budget)
        raw_mp = mp

        # 4. 记录原始API状态（后续可能在锁内应用短时缓存兜底）
        raw_api_up = bool(tel.ind_ok or tel.state_resp_ok or mp.ok)

        # 5. 更新游戏状态（线程安全）
        net_stage_ms = max(0.0, (time.monotonic() - tick_start) * 1000.0)
        lock_wait_start = time.monotonic()
        with self._lock:
            lock_hold_start = time.monotonic()
            try:
                s = self.state
                prev_tel = s.last_tel
                prev_map = s.last_map

                # 在战斗阶段对瞬时空帧做“上一帧有效数据”兜底，避免UI/状态机被单帧抖动拉偏。
                phase_allows_grace = s.phase in (Phase.ALIVE, Phase.LOSS_PENDING)
                recently_seen = (
                    s.last_player_present_ts > 0.0
                    and (now - s.last_player_present_ts) <= GameConfig.PLAYER_PRESENCE_GRACE_SEC
                )
                used_tel_fallback = False
                used_map_fallback = False

                if phase_allows_grace and recently_seen:
                    tel_unstable = (not tel.ind_ok) or (not tel.state_resp_ok)
                    if tel_unstable and prev_tel and (prev_tel.ind_ok or prev_tel.state_resp_ok):
                        tel = prev_tel
                        used_tel_fallback = True

                    map_unstable = (not mp.ok) or (
                        mp.ok and (mp.obj_count == 0) and (not mp.player_aircraft_present)
                    )
                    if map_unstable and prev_map and prev_map.ok:
                        mp = prev_map
                        used_map_fallback = True

                self._update_source_diagnostics_locked(
                    raw_tel=raw_tel,
                    raw_map=raw_mp,
                    map_info_result=map_info_result,
                    used_tel_fallback=used_tel_fallback,
                    used_map_fallback=used_map_fallback,
                )

                api_up = bool(raw_api_up or used_tel_fallback or used_map_fallback)
                s.last_tel = tel
                s.last_map = mp
                self._update_attitude_confidence_locked(raw_tel, now)
                self._update_gear_state_locked(tel, now)

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
                    s.last_player_present_ts > 0.0
                    and (now - s.last_player_present_ts) <= GameConfig.PLAYER_PRESENCE_GRACE_SEC
                )

                # 实体特征兜底：仅在“最近确实见过玩家”的短时间窗口内生效，
                # 避免回机库后因遥测仍有残留值而长期保持 ALIVE。
                if (
                    (not player_present)
                    and phase_allows_player_grace
                    and tel.entity_like
                    and presence_recently_seen
                ):
                    player_present = True

                # 数据短抖动宽限：计分板/地图等场景可能导致8111瞬时空帧，避免ALIVE阶段立即判死。
                if (not player_present) and phase_allows_player_grace:
                    data_unstable = (not mp.ok) or (not tel.ind_ok) or (not tel.state_resp_ok)
                    if data_unstable and presence_recently_seen:
                        player_present = True
                spawn_candidate = player_present and tel.entity_like

                # Trace back observes raw map responses only. Cached fallback data
                # must never extend a player-loss candidate or move its position.
                self._update_traceback_observation_locked(raw_mp, now)

                # 更新导航信息（战区、地速）
                self._update_zone_navigation_locked(mp, tel, now)

                self._resolve_pending_timer_restore_locked(
                    mp=mp,
                    player_present=player_present,
                    spawn_candidate=spawn_candidate,
                    now=now,
                )

                # === 状态机逻辑 ===
                hangar_like = (not mp.ok) or (mp.obj_count == 0)
                if hangar_like and (not player_present) and s.phase != Phase.ALIVE:
                    if s.hangar_candidate_since is None:
                        s.hangar_candidate_since = now
                    elif (now - s.hangar_candidate_since) >= GameConfig.HANGAR_CONFIRM_SEC:
                        s.phase = Phase.HANGAR
                        lifecycle.reset_life_state(s)
                else:
                    s.hangar_candidate_since = None

                if s.phase == Phase.HANGAR:
                    if spawn_candidate:
                        lifecycle.prepare_new_battle_context(s)
                        s.phase = Phase.ARMING
                        s.spawn_candidate_since = now
                    return

                if s.phase == Phase.IDLE:
                    if spawn_candidate:
                        lifecycle.prepare_new_battle_context(s)
                        s.phase = Phase.ARMING
                        s.spawn_candidate_since = now

                elif s.phase == Phase.ARMING:
                    if spawn_candidate:
                        if s.spawn_candidate_since is None:
                            s.spawn_candidate_since = now
                        if (now - s.spawn_candidate_since) >= GameConfig.SPAWN_CONFIRM_SEC:
                            lifecycle.start_new_life(s, now)
                            s.phase = Phase.ALIVE
                            lifecycle.clear_transient_state(s)
                    else:
                        s.spawn_candidate_since = None
                        s.phase = Phase.IDLE

                elif s.phase == Phase.ALIVE:
                    if tel.state_resp_ok:
                        s.fuel_state.update(
                            fuel_kg=tel.fuel_kg,
                            fuel0_kg=tel.fuel0_kg,
                            altitude_m=tel.altitude_m,
                            ias_kmh=tel.ias_kmh,
                            now=now,
                        )

                    if prev_tel and prev_tel.state_resp_ok and tel.state_resp_ok:
                        fuel_jump = tel.fuel_kg - prev_tel.fuel_kg
                        if (
                            fuel_jump >= GameConfig.REFIT_FUEL_JUMP_KG
                            and tel.ias_kmh <= GameConfig.REFIT_SPEED_KMH
                            and abs(tel.vy_ms) <= GameConfig.REFIT_VSPEED_MS
                            and (now - s.last_refit_ts) >= GameConfig.REFIT_MIN_GAP_SEC
                        ):
                            s.sortie_id += 1
                            s.last_refit_ts = now
                            s.landing_start_time = None
                            s.landed_flash_until = 0.0

                    lifecycle.update_landing(s, tel, now)

                    if not player_present:
                        s.phase = Phase.LOSS_PENDING
                        s.missing_player_since = now
                        s.spawn_candidate_since = None
                    else:
                        s.missing_player_since = None

                elif s.phase == Phase.LOSS_PENDING:
                    if player_present:
                        s.phase = Phase.ALIVE
                        s.missing_player_since = None
                    else:
                        if s.missing_player_since is None:
                            s.missing_player_since = now
                        if (now - s.missing_player_since) >= GameConfig.DEAD_CONFIRM_SEC:
                            self._confirm_traceback_loss_locked(now)
                            s.phase = Phase.WAIT_NEXT
                            s.spawn_candidate_since = None

                elif s.phase == Phase.WAIT_NEXT:
                    if spawn_candidate:
                        if s.spawn_candidate_since is None:
                            s.spawn_candidate_since = now
                        if (now - s.spawn_candidate_since) >= GameConfig.SPAWN_CONFIRM_SEC:
                            lifecycle.start_new_life(s, now)
                            s.phase = Phase.ALIVE
                            lifecycle.clear_transient_state(s)
                    else:
                        s.spawn_candidate_since = None

                # v6.14.4: only collect CCRP inputs while holding the state lock.
                # Ballistics integration can be expensive on abnormal settlement frames;
                # keep it outside the lock so UI snapshots do not stall behind it.
                if ENABLE_CCRP and self.weapon_catalog is not None:
                    selection_snapshot = self.weapon_catalog.selection_snapshot()
                    selected_id, _selection_source, selected_weapon = selection_snapshot
                    weapon_target = self._select_weapon_target_locked(selected_weapon, mp)
                    usable_player_frame = player_present and (not used_map_fallback)
                    selected_is_ccrp = uses_existing_ccrp(selected_weapon)
                    ccrp_data = BombConfig.get_bomb_data(selected_id) if selected_is_ccrp else None
                    weapon_work = weapon_scheduler.prepare_weapon_calculation(
                        self.state,
                        tel,
                        now,
                        player_present=usable_player_frame,
                        target=weapon_target,
                        catalog=self.weapon_catalog,
                        selection_snapshot=selection_snapshot,
                        ccrp_supported=not selected_is_ccrp or ccrp_data is not None,
                    )
                    selected_is_compatible = self.weapon_catalog.compatible(
                        selected_id,
                        tel.type_name,
                    )
                    if selected_is_ccrp and selected_is_compatible and ccrp_data is not None:
                        BombConfig.selected_bomb = selected_id
                        bombing_work = ccrp_scheduler.prepare_bombing_calculation(
                            self.state,
                            tel,
                            now,
                            player_present=usable_player_frame,
                            bomb_params=BombConfig.get_bomb_physics_params(selected_id),
                        )
                        bombing_selection_token = selection_snapshot[:2]
                    else:
                        self.state.bombing_calc_valid = False
                elif ENABLE_CCRP:
                    self.state.weapon_solution_valid = False
                    self.state.weapon_status = "unknown_weapon"
                    self.state.weapon_quality = "none"
                    self.state.weapon_reason = "catalog_unavailable"
                    self.state.weapon_selection_source = "unknown"
                    self.state.bombing_calc_valid = False
            finally:
                s = self.state
                s.perf_tick_net_ms = net_stage_ms
                s.perf_tick_lock_wait_ms = max(0.0, (lock_hold_start - lock_wait_start) * 1000.0)
                s.perf_tick_lock_hold_ms = max(0.0, (time.monotonic() - lock_hold_start) * 1000.0)
                s.perf_tick_total_ms = max(0.0, (time.monotonic() - tick_start) * 1000.0)

        if bombing_work is not None:
            bombing_result = ccrp_scheduler.compute_bombing_calculation(
                bombing_work,
                trajectory_func=calculate_bomb_trajectory,
                timing_func=calculate_release_timing_from_range,
            )
            with self._lock:
                current_selection = (
                    self.weapon_catalog.selection_snapshot()[:2]
                    if self.weapon_catalog is not None
                    else None
                )
                if current_selection == bombing_selection_token:
                    ccrp_scheduler.apply_bombing_calculation(self.state, bombing_result)
                else:
                    self.state.bombing_calc_valid = False
                self.state.perf_tick_total_ms = max(0.0, (time.monotonic() - tick_start) * 1000.0)

        if weapon_work is not None:
            weapon_result = weapon_scheduler.compute_weapon_calculation(
                weapon_work,
                solver=self.weapon_solver,
            )
            with self._lock:
                weapon_scheduler.apply_weapon_calculation(
                    self.state,
                    weapon_result,
                    catalog=self.weapon_catalog,
                )
                self.state.perf_tick_total_ms = max(
                    0.0,
                    (time.monotonic() - tick_start) * 1000.0,
                )

    def _resolve_pending_timer_restore_locked(
        self,
        *,
        mp: MapObjData,
        player_present: bool,
        spawn_candidate: bool,
        now: float,
    ) -> None:
        """在识别到战局上下文后决定是否落地旧倒计时。"""
        pending = self._pending_timer_restore
        if not pending or not player_present or not spawn_candidate:
            return

        expected_signature = str(pending.get("battle_signature") or "")
        current_signature = timing_store.build_battle_signature(self.state.map_info, mp)
        if not expected_signature or not current_signature:
            return

        if current_signature != expected_signature:
            self._pending_timer_restore = None
            self.timer_restore_applied = False
            StateManager.clear(report_error=False)
            log_event(
                "timer_restore_discarded",
                reason="battle_signature_mismatch",
            )
            return

        self.state.current_life = LifeState(
            spawn_time=pending["computed_spawn_time"],
            life_index=pending.get("life_index", 1),
        )
        self.state.sortie_id = pending.get("sortie_id", 0)
        self.state.phase = Phase.ALIVE
        self.state.last_refit_ts = pending["computed_spawn_time"]
        self.state.last_player_present_ts = now
        self._pending_timer_restore = None
        self.timer_restore_applied = True
        log_event(
            "timer_restore_applied",
            sortie_id=int(self.state.sortie_id),
            life_index=int(self.state.current_life.life_index),
        )

    def _update_source_diagnostics_locked(
        self,
        raw_tel: TelemetryData,
        raw_map: MapObjData,
        map_info_result: Any | None,
        used_tel_fallback: bool,
        used_map_fallback: bool,
    ) -> None:
        """Record raw 8111 endpoint health before sticky fallbacks are applied."""
        s = self.state
        core_diagnostics.record_endpoint_diagnostic(
            self.state,
            bool(raw_tel.ind_ok),
            "indicators_failure_streak",
            "indicators_failure_count",
        )
        core_diagnostics.record_endpoint_diagnostic(
            self.state,
            bool(raw_tel.state_resp_ok),
            "state_failure_streak",
            "state_failure_count",
        )
        core_diagnostics.record_endpoint_diagnostic(
            self.state,
            bool(raw_map.ok),
            "map_failure_streak",
            "map_failure_count",
        )
        if map_info_result is not None:
            core_diagnostics.record_endpoint_diagnostic(
                self.state,
                bool(map_info_result.ok),
                "map_info_failure_streak",
                "map_info_failure_count",
            )
        core_diagnostics.emit_endpoint_diagnostic(
            self._endpoint_diag_state,
            log_event,
            endpoint="/indicators",
            ok=bool(raw_tel.ind_ok),
            error_kind=str(raw_tel.ind_error_kind or ""),
            elapsed_ms=float(raw_tel.ind_elapsed_ms or 0.0),
            failure_streak=int(s.indicators_failure_streak),
        )
        core_diagnostics.emit_endpoint_diagnostic(
            self._endpoint_diag_state,
            log_event,
            endpoint="/state",
            ok=bool(raw_tel.state_resp_ok),
            error_kind=str(raw_tel.state_error_kind or ""),
            elapsed_ms=float(raw_tel.state_elapsed_ms or 0.0),
            failure_streak=int(s.state_failure_streak),
        )
        core_diagnostics.emit_endpoint_diagnostic(
            self._endpoint_diag_state,
            log_event,
            endpoint="/map_obj.json",
            ok=bool(raw_map.ok),
            error_kind=str(raw_map.error_kind or ""),
            elapsed_ms=float(raw_map.elapsed_ms or 0.0),
            failure_streak=int(s.map_failure_streak),
        )
        if map_info_result is not None:
            core_diagnostics.emit_endpoint_diagnostic(
                self._endpoint_diag_state,
                log_event,
                endpoint="/map_info.json",
                ok=bool(map_info_result.ok),
                error_kind=str(map_info_result.error_kind or ""),
                elapsed_ms=float(map_info_result.elapsed_ms or 0.0),
                failure_streak=int(s.map_info_failure_streak),
                status_code=getattr(map_info_result, "status_code", None),
            )

        s.tel_fallback_active = bool(used_tel_fallback)
        s.map_fallback_active = bool(used_map_fallback)
        if used_tel_fallback:
            s.tel_fallback_count += 1
        if used_map_fallback:
            s.map_fallback_count += 1

    def _update_attitude_confidence_locked(self, tel: TelemetryData, now: float) -> None:
        """更新姿态可信度（须在锁内调用）。"""
        att = self.state.attitude

        # 抖动分数自然衰减，避免单次异常长期影响。
        if att.last_sample_ts > 0:
            dt = max(0.0, now - att.last_sample_ts)
            if dt > 0:
                att.jitter_score = max(
                    0.0, att.jitter_score - dt * self.ATTITUDE_JITTER_DECAY_PER_SEC
                )
        else:
            dt = 0.0

        available = bool(
            tel.attitude_available
            and tel.attitude_pitch_present
            and (tel.attitude_roll_present or tel.attitude_bank_present)
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
            if (
                airborne
                and abs(pitch) <= self.ATTITUDE_ZERO_EPS_DEG
                and abs(lateral) <= self.ATTITUDE_ZERO_EPS_DEG
            ):
                if att.zero_since is None:
                    att.zero_since = now
            else:
                att.zero_since = None

            # 突变抖动检测：按角速度阈值累计分数。
            if dt > 0 and (att.last_pitch_deg is not None) and (att.last_roll_deg is not None):
                pitch_rate = navigation.angle_delta_deg(pitch, att.last_pitch_deg) / dt
                roll_rate = navigation.angle_delta_deg(lateral, att.last_roll_deg) / dt
                if (
                    pitch_rate >= self.ATTITUDE_JITTER_PITCH_RATE_DEG_S
                    or roll_rate >= self.ATTITUDE_JITTER_ROLL_RATE_DEG_S
                ):
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
            (att.missing_since is not None)
            and ((now - att.missing_since) >= self.ATTITUDE_MISSING_CONFIRM_SEC)
        )
        zero_unreliable = bool(
            (att.zero_since is not None)
            and ((now - att.zero_since) >= self.ATTITUDE_ZERO_CONFIRM_SEC)
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

    def _update_gear_state_locked(self, tel: TelemetryData, now: float) -> None:
        """更新起落架显示状态（须在锁内调用）。"""
        s = self.state

        # /state 不可用时保持最近稳定值，避免零值抖动污染状态。
        if not tel.state_resp_ok:
            return

        raw_gear_pct = float(tel.gear_pct or 0.0)

        if s.last_gear_pct < 0:
            s.last_gear_pct = raw_gear_pct
            s.gear_stable_pct = raw_gear_pct
            s.gear_stable_direction = False
            s.gear_change_time = 0.0
            return

        pct_diff = abs(raw_gear_pct - s.gear_stable_pct)
        if pct_diff > 2.0:
            if s.gear_change_time == 0.0:
                s.gear_change_time = now
            elif now - s.gear_change_time > 0.1:
                s.gear_stable_direction = raw_gear_pct < s.last_gear_pct
                s.gear_stable_pct = raw_gear_pct
                s.gear_change_time = 0.0
        else:
            s.gear_change_time = 0.0
            if pct_diff > 0.5:
                s.gear_stable_pct = raw_gear_pct

        delta = raw_gear_pct - s.last_gear_pct
        if abs(delta) >= 0.5:
            s.gear_stable_direction = delta < 0
        s.last_gear_pct = raw_gear_pct

    def _update_traceback_observation_locked(self, raw_mp: MapObjData, now: float) -> None:
        """Observe raw ownship presence while the caller holds the state lock."""
        state = self.state
        traceback = state.traceback
        if state.phase not in (Phase.ALIVE, Phase.LOSS_PENDING):
            return

        if raw_mp.ok and raw_mp.player_aircraft_present and raw_mp.player_pos is not None:
            px, py = raw_mp.player_pos
            if math.isfinite(float(px)) and math.isfinite(float(py)):
                traceback.last_confirmed_pos = (float(px), float(py))
                traceback.last_confirmed_ts = now
                traceback.valid_absence_since = None
                traceback.pending_site = None
                return

        valid_absence = bool(
            raw_mp.ok and raw_mp.obj_count > 0 and not raw_mp.player_aircraft_present
        )
        if not valid_absence:
            traceback.valid_absence_since = None
            traceback.pending_site = None
            return

        if traceback.valid_absence_since is not None:
            return

        traceback.valid_absence_since = now
        if traceback.last_confirmed_pos is None or state.current_life is None:
            traceback.pending_site = None
            return
        px, py = traceback.last_confirmed_pos
        traceback.pending_site = TracebackSite(
            x=px,
            y=py,
            captured_at=traceback.last_confirmed_ts,
            life_index=state.current_life.life_index,
        )

    def _confirm_traceback_loss_locked(self, now: float) -> None:
        """Promote a continuously observed player loss at WAIT_NEXT entry."""
        traceback = self.state.traceback
        if (
            traceback.pending_site is None
            or traceback.valid_absence_since is None
            or (now - traceback.valid_absence_since) < GameConfig.DEAD_CONFIRM_SEC
        ):
            return
        traceback.confirmed_site = traceback.pending_site
        traceback.pending_site = None
        traceback.valid_absence_since = None

    def _update_zone_navigation_locked(self, mp: MapObjData, tel: TelemetryData, now: float):
        """更新战区导航状态(须在锁内调用)

        功能: 计算地速/检测战区摧毁/计算导航信息/选择目标战区
        """
        nav = self.state.zone_nav
        previous_target_id = nav.target_zone.id if nav.target_zone else None

        if not mp.ok or not mp.player_pos:
            # 无数据时重置
            nav.zones = []
            nav.target_zone = None
            nav.bombing_target = None
            nav.is_deviating = False
            nav.last_pos = None
            nav.ground_speed = 0.0
            if previous_target_id is not None:
                log_event(
                    "navigation_target_changed",
                    previous_target_id=previous_target_id,
                    target_id=None,
                    reason="source_unavailable",
                )
            return

        px, py = mp.player_pos
        map_axis_scale_m = navigation.map_axis_scale_m(self.state.map_info)

        # 计算航向：
        # HUD/导航优先使用机头罗盘（更贴近驾驶视角），
        # 罗盘不可用时再回退到地速向量航向。
        heading = None
        if tel.ind_ok and tel.compass_present and math.isfinite(float(tel.compass)):
            heading = float(tel.compass) % 360.0
        if heading is None:
            heading = calculate_heading_from_vector(mp.player_dx, mp.player_dy)
        if heading is None and tel.compass_present:
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
                dist_moved = navigation.distance_norm_from_delta(dx, dy, map_axis_scale_m)

                if dist_moved > 0:
                    current_speed = dist_moved / dt

                    # 指数平滑滤波（EMA）
                    alpha = 0.2
                    if nav.ground_speed == 0:
                        nav.ground_speed = current_speed
                    else:
                        nav.ground_speed = (nav.ground_speed * (1 - alpha)) + (
                            current_speed * alpha
                        )

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
        if nav.previous_zone_ids:
            destroyed_ids = nav.previous_zone_ids - current_zone_ids
            if destroyed_ids:
                # 找到被摧毁的战区
                destroyed = [z for z in nav.zones if z.id in destroyed_ids]
                if destroyed:
                    nav.destroyed_zones = destroyed
                    nav.destroyed_alert_until = now + ZoneConfig.DESTROYED_ALERT_SEC

                    # v5.5: 判断是否有感兴趣的战区被摧毁
                    has_interesting = any(
                        self._is_zone_of_interest(z, nav.target_zone) for z in destroyed
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
            bearing, distance = navigation.bearing_distance_norm(
                px, py, zone.x, zone.y, map_axis_scale_m
            )
            relative = calculate_relative_bearing(heading, bearing)
            zones_with_nav.append(
                Zone(
                    id=zone.id,
                    index=zone.index,
                    x=zone.x,
                    y=zone.y,
                    color=zone.color,
                    distance=distance,
                    bearing=bearing,
                    relative=relative,
                    is_target=False,
                )
            )

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
            precise_candidates = [
                z for z in zones_with_nav if abs(z.relative) <= ZoneConfig.PRECISE_AIM_THRESHOLD
            ]
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
                    if (
                        aim_duration >= ZoneConfig.PRECISE_AIM_CONFIRM_SEC
                        and nav.locked_target_id != precise_candidate.id
                    ):
                        # 确认切换到新目标
                        nav.locked_target_id = precise_candidate.id
                        target = precise_candidate
            else:
                # 没有精确对准的目标，清除候选
                nav.precise_aim_candidate_id = None
                nav.precise_aim_since = 0.0

            # Step 3: 如果还没有目标，从45°角度门内选择角度最小的
            # ⚠️ 优先角度最小，而不是距离最近
            if target is None:
                candidates_in_gate = [
                    z for z in zones_with_nav if abs(z.relative) <= ZoneConfig.HEADING_TOLERANCE
                ]
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
                        id=zone.id,
                        index=zone.index,
                        x=zone.x,
                        y=zone.y,
                        color=zone.color,
                        distance=zone.distance,
                        bearing=zone.bearing,
                        relative=zone.relative,
                        is_target=True,
                    )
                    target = zones_with_nav[i]
                    break

        poi_bombing_target = None
        if is_airborne and getattr(mp, "interest_points", None):
            poi_candidates: list[tuple[float, float, InterestPoint, float]] = []
            for point in mp.interest_points:
                try:
                    point_x = float(point.x)
                    point_y = float(point.y)
                except TypeError, ValueError:
                    continue
                if not (math.isfinite(point_x) and math.isfinite(point_y)):
                    continue

                bearing, distance = navigation.bearing_distance_norm(
                    px, py, point_x, point_y, map_axis_scale_m
                )
                relative = calculate_relative_bearing(heading, bearing)
                if abs(relative) <= ZoneConfig.HEADING_TOLERANCE:
                    poi_candidates.append((abs(relative), distance, point, relative))

            if poi_candidates:
                _, distance, point, relative = min(
                    poi_candidates,
                    key=lambda item: (item[0], item[1]),
                )
                point_name = str(point.name or "").strip() or f"兴趣点 #{point.index}"
                poi_bombing_target = BombingTarget(
                    id=point.id,
                    kind="poi",
                    name=point_name,
                    distance=distance,
                    relative=relative,
                )

        nav.zones = zones_with_nav
        nav.target_zone = target
        if poi_bombing_target is not None:
            nav.bombing_target = poi_bombing_target
        elif target:
            nav.bombing_target = BombingTarget(
                id=target.id,
                kind="zone",
                name=f"战区 #{target.index}",
                distance=target.distance,
                relative=target.relative,
            )
        else:
            nav.bombing_target = None
        nav.is_deviating = (
            (abs(target.relative) > ZoneConfig.DEVIATION_WARNING) if target else False
        )
        target_id = target.id if target else None
        if target_id != previous_target_id:
            log_event(
                "navigation_target_changed",
                previous_target_id=previous_target_id,
                target_id=target_id,
                relative_deg=(float(target.relative) if target else None),
                distance_km=(
                    float(target.distance * ZoneConfig.DISTANCE_SCALE) if target else None
                ),
                airborne=bool(is_airborne),
            )

    def _select_weapon_target_locked(
        self,
        weapon: dict[str, Any] | None,
        mp: MapObjData,
    ) -> WeaponTarget | None:
        """Select one current 2D target without implying a game lock."""

        if not weapon:
            return None
        if weapon.get("role") != "aam":
            bombing_target = self.state.zone_nav.bombing_target
            if bombing_target is None:
                return None
            distance_m = bombing_target.distance * ZoneConfig.DISTANCE_SCALE * 1000
            if not math.isfinite(distance_m) or distance_m <= 0.0:
                return None
            return WeaponTarget(
                id=bombing_target.id,
                kind=bombing_target.kind,
                name=bombing_target.name,
                distance_m=distance_m,
                relative_deg=bombing_target.relative,
                altitude_m=None,
            )

        if not (mp.ok and mp.player_pos and mp.hostile_air_contacts):
            return None
        px, py = mp.player_pos
        map_axis_scale_m = navigation.map_axis_scale_m(self.state.map_info)
        heading = self.state.zone_nav.player_heading
        candidates: list[tuple[float, float, Any, float]] = []
        for contact in mp.hostile_air_contacts:
            try:
                contact_x = float(contact.x)
                contact_y = float(contact.y)
            except TypeError, ValueError:
                continue
            if not (math.isfinite(contact_x) and math.isfinite(contact_y)):
                continue
            bearing, distance = navigation.bearing_distance_norm(
                px,
                py,
                contact_x,
                contact_y,
                map_axis_scale_m,
            )
            relative = calculate_relative_bearing(heading, bearing)
            if abs(relative) <= 60.0:
                candidates.append((abs(relative), distance, contact, relative))
        if not candidates:
            return None

        _angle, distance, contact, relative = min(
            candidates,
            key=lambda item: (item[0], item[1]),
        )
        distance_m = distance * ZoneConfig.DISTANCE_SCALE * 1000
        if not math.isfinite(distance_m) or distance_m <= 0.0:
            return None
        return WeaponTarget(
            id=contact.id,
            kind="aircraft",
            name=str(contact.name or contact.icon or f"敌机 #{contact.index}"),
            distance_m=distance_m,
            relative_deg=relative,
            altitude_m=None,
            aspect_cosine=_target_radial_aspect_cosine(
                px,
                py,
                float(contact.x),
                float(contact.y),
                contact.dx,
                contact.dy,
                map_axis_scale_m,
            ),
        )

    def _is_zone_of_interest(self, zone: Zone, target_zone: Zone | None) -> bool:
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
        return abs_relative <= 45 and distance_km < 60

    def _build_zone_display_list(
        self,
        zones: list[Zone],
        ground_speed: float,
    ) -> list[ZoneDisplayInfo]:
        """根据导航状态构建战区显示列表。"""
        items: list[ZoneDisplayInfo] = []
        for zone in zones[: ZoneConfig.MAX_DISPLAY_ZONES]:
            ete_text = ""
            if zone.is_target and ground_speed > 1e-7:
                seconds_left = zone.distance / ground_speed
                if seconds_left < 5999:
                    m, s_time = divmod(int(seconds_left), 60)
                    ete_text = f"{m:02d}:{s_time:02d}"

            cdi_str = ""
            cdi_clr = ""
            if zone.is_target:
                dist_km = zone.distance * ZoneConfig.DISTANCE_SCALE
                cdi_str, cdi_clr = generate_cdi_indicator(zone.relative, dist_km)

            items.append(
                ZoneDisplayInfo(
                    id=zone.id,
                    distance_km=zone.distance * ZoneConfig.DISTANCE_SCALE,
                    direction=get_direction_text(zone.relative),
                    relative=zone.relative,
                    is_target=zone.is_target,
                    ete_str=ete_text,
                    cdi_indicator=cdi_str,
                    cdi_color=cdi_clr,
                )
            )
        return items

    def _build_airfield_display(
        self,
        mp: MapObjData,
        map_axis_scale_m: tuple[float, float] | None,
        player_heading: float,
        ground_speed: float,
    ) -> tuple[AirfieldDisplayInfo | None, list[AirfieldDisplayInfo], bool]:
        """根据地图对象构建机场显示列表。"""
        if not (mp.ok and mp.player_pos and getattr(mp, "airfields", None)):
            return None, [], False

        px, py = mp.player_pos
        friendly_infos: list[tuple[float, AirfieldDisplayInfo]] = []
        enemy_infos: list[tuple[float, AirfieldDisplayInfo]] = []

        for af in mp.airfields:
            if (not math.isfinite(float(af.x))) or (not math.isfinite(float(af.y))):
                continue

            bearing, distance = navigation.bearing_distance_norm(
                px, py, af.x, af.y, map_axis_scale_m
            )
            relative = calculate_relative_bearing(player_heading, bearing)
            info = AirfieldDisplayInfo(
                id=af.id,
                side="friendly" if af.is_friendly else "enemy",
                distance_km=distance * ZoneConfig.DISTANCE_SCALE,
                direction=get_direction_text(relative),
                relative=relative,
                is_target=False,
            )
            if af.is_friendly:
                friendly_infos.append((distance, info))
            else:
                enemy_infos.append((distance, info))

        friendly_display: AirfieldDisplayInfo | None = None
        if friendly_infos:
            friendly_infos.sort(key=lambda item: item[0])
            dist, info = friendly_infos[0]
            ete_text = ""
            if abs(info.relative) <= 90 and ground_speed > 1e-7:
                seconds_left = dist / ground_speed
                if seconds_left < 3600:
                    mm, ss = divmod(int(seconds_left), 60)
                    ete_text = f"{mm:02d}:{ss:02d}"
            cdi_str, cdi_clr = generate_cdi_indicator(info.relative, info.distance_km)
            friendly_display = AirfieldDisplayInfo(
                id=info.id,
                side=info.side,
                distance_km=info.distance_km,
                direction=info.direction,
                relative=info.relative,
                is_target=True,
                ete_str=ete_text,
                cdi_indicator=cdi_str,
                cdi_color=cdi_clr,
            )

        enemy_display: list[AirfieldDisplayInfo] = []
        has_airfield_target = False
        if enemy_infos:
            enemy_infos.sort(key=lambda item: item[0])
            max_total = ZoneConfig.MAX_DISPLAY_AIRFIELDS
            max_enemy = max(0, max_total - (1 if friendly_infos else 0))
            enemy_infos = enemy_infos[:max_enemy] if max_enemy > 0 else []

            target_idx = -1
            for i, (_, info) in enumerate(enemy_infos):
                if abs(info.relative) <= ZoneConfig.ENEMY_AIRFIELD_ETE_ANGLE:
                    target_idx = i
                    break

            for i, (dist, info) in enumerate(enemy_infos):
                is_target = i == target_idx
                ete_text = ""
                cdi_str = ""
                cdi_clr = ""
                if (
                    is_target
                    and abs(info.relative) <= ZoneConfig.ENEMY_AIRFIELD_ETE_ANGLE
                    and ground_speed > 1e-7
                ):
                    seconds_left = dist / ground_speed
                    if seconds_left < 3600:
                        mm, ss = divmod(int(seconds_left), 60)
                        ete_text = f"{mm:02d}:{ss:02d}"
                    cdi_str, cdi_clr = generate_cdi_indicator(info.relative, info.distance_km)
                enemy_display.append(
                    AirfieldDisplayInfo(
                        id=info.id,
                        side=info.side,
                        distance_km=info.distance_km,
                        direction=info.direction,
                        relative=info.relative,
                        is_target=is_target,
                        ete_str=ete_text,
                        cdi_indicator=cdi_str,
                        cdi_color=cdi_clr,
                    )
                )
            has_airfield_target = target_idx >= 0

        return friendly_display, enemy_display, has_airfield_target

    def _build_interest_point_display(
        self,
        mp: MapObjData,
        map_axis_scale_m: tuple[float, float] | None,
        player_heading: float,
        ground_speed: float,
    ) -> NavigationPointDisplayInfo | None:
        """根据地图对象构建最近兴趣点显示数据。"""
        if not (mp.ok and mp.player_pos and getattr(mp, "interest_points", None)):
            return None

        px, py = mp.player_pos
        candidates: list[tuple[float, InterestPoint, float]] = []
        for point in mp.interest_points:
            if (not math.isfinite(float(point.x))) or (not math.isfinite(float(point.y))):
                continue

            bearing, distance = navigation.bearing_distance_norm(
                px,
                py,
                point.x,
                point.y,
                map_axis_scale_m,
            )
            relative = calculate_relative_bearing(player_heading, bearing)
            candidates.append((distance, point, relative))

        if not candidates:
            return None

        distance, point, relative = min(candidates, key=lambda item: item[0])
        distance_km = distance * ZoneConfig.DISTANCE_SCALE
        ete_text = ""
        if ground_speed > 1e-7:
            seconds_left = distance / ground_speed
            if seconds_left < 5999:
                mm, ss = divmod(int(seconds_left), 60)
                ete_text = f"{mm:02d}:{ss:02d}"

        cdi_str, cdi_clr = generate_cdi_indicator(relative, distance_km)
        return NavigationPointDisplayInfo(
            id=point.id,
            name=point.name or point.id,
            distance_km=distance_km,
            direction=get_direction_text(relative),
            relative=relative,
            is_target=True,
            ete_str=ete_text,
            cdi_indicator=cdi_str,
            cdi_color=cdi_clr,
        )

    def _build_traceback_display(
        self,
        site: TracebackSite | None,
        mp: MapObjData,
        map_axis_scale_m: tuple[float, float] | None,
        player_heading: float,
        ground_speed: float,
    ) -> NavigationPointDisplayInfo | None:
        """Project the confirmed same-battle loss point from current ownship."""
        if site is None or not (mp.ok and mp.player_pos):
            return None
        if not (math.isfinite(site.x) and math.isfinite(site.y)):
            return None

        px, py = mp.player_pos
        bearing, distance = navigation.bearing_distance_norm(
            px,
            py,
            site.x,
            site.y,
            map_axis_scale_m,
        )
        relative = calculate_relative_bearing(player_heading, bearing)
        distance_km = distance * ZoneConfig.DISTANCE_SCALE
        ete_text = ""
        if ground_speed > 1e-7:
            seconds_left = distance / ground_speed
            if seconds_left < 5999:
                mm, ss = divmod(int(seconds_left), 60)
                ete_text = f"{mm:02d}:{ss:02d}"

        cdi_str, cdi_clr = generate_cdi_indicator(relative, distance_km)
        return NavigationPointDisplayInfo(
            id=f"traceback-life-{site.life_index}",
            name="上次坠毁点",
            distance_km=distance_km,
            direction=get_direction_text(relative),
            relative=relative,
            is_target=True,
            ete_str=ete_text,
            cdi_indicator=cdi_str,
            cdi_color=cdi_clr,
        )

    def _build_destroyed_zone_text(
        self,
        destroyed_zones: list[Zone],
        player_pos: tuple[float, float] | None,
        map_axis_scale_m: tuple[float, float] | None,
        player_heading: float,
    ) -> str:
        """构建被摧毁战区的提示文字。"""
        if not destroyed_zones:
            return ""

        if player_pos is None:
            return "  |  ".join(f"#{zone.index}" for zone in destroyed_zones)

        px, py = player_pos
        items: list[str] = []
        for zone in destroyed_zones:
            try:
                bearing, dist_norm = navigation.bearing_distance_norm(
                    px, py, zone.x, zone.y, map_axis_scale_m
                )
                dist_km = dist_norm * ZoneConfig.DISTANCE_SCALE
                rel = calculate_relative_bearing(player_heading, bearing)
                items.append(f"#{zone.index} {get_direction_text(rel)} {dist_km:.1f}km")
            except Exception:
                items.append(f"#{zone.index}")
        return "  |  ".join(items)

    def manual_reset(self):
        """手动重置计时器

        将当前生命的出生时间设为现在，重启15分钟周期。
        """
        with self._lock:
            if self.state.phase == Phase.ALIVE and self.state.current_life:
                self.state.current_life.spawn_time = self.clock.time()
                self.state.landing_start_time = None
                self.state.landed_flash_until = 0.0

    def save_timer_state(self):
        """保存计时器状态到文件

        用于应用退出时保存进度。
        """
        with self._lock:
            if self._pending_timer_restore is not None:
                return
            if self.state.phase != Phase.ALIVE or not self.state.current_life:
                StateManager.clear()
                return
            battle_signature = timing_store.build_battle_signature(
                self.state.map_info,
                self.state.last_map,
            )
            if not battle_signature:
                StateManager.clear()
                log_event("timer_state_not_saved", reason="missing_battle_signature")
                return
            now = self.clock.time()
            remaining = self.state.current_life.cycle_remaining(now)
            StateManager.save(
                remaining,
                self.state.current_life.life_index,
                self.state.sortie_id,
                battle_signature,
            )

    def restore_timer_state(self) -> bool:
        """从文件恢复计时器状态

        Returns:
            是否成功恢复
        """
        data = StateManager.load()
        if not data:
            return False
        if not data.get("battle_signature"):
            StateManager.clear(report_error=False)
            self.timer_restore_applied = False
            log_event("timer_restore_discarded", reason="missing_battle_signature")
            return False

        with self._lock:
            self._pending_timer_restore = data
            self.timer_restore_applied = False
        log_event("timer_restore_pending")
        return True

    def snapshot(self) -> UISnapshot:
        """生成UI快照（线程安全）

        将当前游戏状态转换为不可变的UISnapshot对象。
        这是逻辑层与UI层的唯一数据通道。

        Returns:
            UISnapshot对象
        """
        now = self.clock.time()
        wait_start = time.monotonic()
        with self._lock:
            snapshot_wait_ms = max(0.0, (time.monotonic() - wait_start) * 1000.0)
            s = self.state
            tel = s.last_tel or TelemetryData()
            mp = s.last_map or MapObjData()
            map_info = s.map_info
            phase = s.phase
            life_spawn_time = s.current_life.spawn_time if s.current_life else None
            life_index = s.current_life.life_index if s.current_life else None
            sortie_id = s.sortie_id
            api_down = s.api_down
            api_down_candidate_since = s.api_down_candidate_since
            landed_flash_until = s.landed_flash_until

            nav = s.zone_nav
            nav_zones = list(nav.zones)
            nav_target_zone = nav.target_zone
            nav_bombing_target = nav.bombing_target
            nav_destroyed_zones = list(nav.destroyed_zones)
            nav_destroyed_alert_until = nav.destroyed_alert_until
            nav_is_deviating = nav.is_deviating
            nav_player_heading = nav.player_heading
            nav_ground_speed = nav.ground_speed
            nav_should_play_destroyed_sound = nav.should_play_destroyed_sound
            traceback_site = s.traceback.confirmed_site
            map_player_pos = tuple(mp.player_pos) if mp.player_pos is not None else None
            map_points: list[TacticalMapPoint] = []
            for zone in nav_zones:
                map_points.append(
                    TacticalMapPoint(
                        id=zone.id,
                        kind="zone",
                        x=zone.x,
                        y=zone.y,
                        label=f"战区 #{zone.index}",
                        color="target" if zone.is_target else "zone",
                        is_target=zone.is_target,
                    )
                )
            for airfield in tuple(mp.airfields):
                map_points.append(
                    TacticalMapPoint(
                        id=airfield.id,
                        kind="airfield",
                        x=airfield.x,
                        y=airfield.y,
                        label=(
                            f"友方机场 #{airfield.index}"
                            if airfield.is_friendly
                            else f"敌方机场 #{airfield.index}"
                        ),
                        color="friendly" if airfield.is_friendly else "enemy",
                        is_target=airfield.is_target,
                        is_friendly=airfield.is_friendly,
                    )
                )
            for point in tuple(mp.interest_points):
                point_is_target = bool(
                    nav_bombing_target is not None
                    and nav_bombing_target.kind == "poi"
                    and nav_bombing_target.id == point.id
                )
                map_points.append(
                    TacticalMapPoint(
                        id=point.id,
                        kind="poi",
                        x=point.x,
                        y=point.y,
                        label=point.name or f"兴趣点 #{point.index}",
                        color="poi",
                        is_target=point_is_target,
                    )
                )
            if traceback_site is not None:
                map_points.append(
                    TacticalMapPoint(
                        id=f"traceback-{traceback_site.life_index}",
                        kind="traceback",
                        x=traceback_site.x,
                        y=traceback_site.y,
                        label="上次坠毁点",
                        color="traceback",
                        is_target=True,
                    )
                )

            attitude_pitch_deg = s.attitude.pitch_deg
            attitude_roll_deg = s.attitude.roll_deg
            attitude_bank_deg = s.attitude.bank_deg
            attitude_reliable = s.attitude.reliable
            attitude_fallback = s.attitude.fallback
            attitude_fallback_reason = s.attitude.fallback_reason

            fuel_current_kg = s.fuel_state.current_kg
            fuel_initial_kg = s.fuel_state.initial_kg
            fuel_percent = s.fuel_state.fuel_percent
            fuel_consumption_rate = s.fuel_state.consumption_rate
            fuel_rate_stable = s.fuel_state.rate_stable
            fuel_remaining_time_min = s.fuel_state.remaining_time_min

            gear_stable_pct = s.gear_stable_pct
            gear_stable_direction = s.gear_stable_direction
            map_info_error_kind = s.map_info_error_kind
            map_info_elapsed_ms = s.map_info_elapsed_ms

            bombing_calc_valid = s.bombing_calc_valid
            cached_bomb_flight_time = s.cached_bomb_flight_time
            cached_bomb_range_m = s.cached_bomb_range_m
            cached_release_distance_m = s.cached_release_distance_m
            cached_time_to_release = s.cached_time_to_release
            cached_release_status = s.cached_release_status
            cached_target_distance_m = s.cached_target_distance_m
            cached_bombing_target_kind = s.cached_bombing_target_kind
            cached_bombing_target_name = s.cached_bombing_target_name
            cached_bombing_unavailable_reason = s.cached_bombing_unavailable_reason
            weapon_snapshot = {
                "weapon_id": s.weapon_id,
                "weapon_display_name": s.weapon_display_name,
                "weapon_role": s.weapon_role,
                "weapon_control": s.weapon_control,
                "weapon_planform": s.weapon_planform,
                "weapon_model": s.weapon_model,
                "weapon_selection_source": s.weapon_selection_source,
                "weapon_selection_compatible": s.weapon_selection_compatible,
                "weapon_solution_valid": s.weapon_solution_valid,
                "weapon_status": s.weapon_status,
                "weapon_quality": s.weapon_quality,
                "weapon_reason": s.weapon_reason,
                "weapon_target_kind": s.weapon_target_kind,
                "weapon_target_name": s.weapon_target_name,
                "weapon_target_distance_m": s.weapon_target_distance_m,
                "weapon_min_range_m": s.weapon_min_range_m,
                "weapon_max_range_m": s.weapon_max_range_m,
                "weapon_rear_range_m": s.weapon_rear_range_m,
                "weapon_head_range_m": s.weapon_head_range_m,
                "weapon_target_aspect_cosine": s.weapon_target_aspect_cosine,
                "weapon_time_to_target_s": s.weapon_time_to_target_s,
                "weapon_time_to_window_s": s.weapon_time_to_window_s,
            }

            perf_debug = PerfDebugInfo(
                tick_total_ms=s.perf_tick_total_ms,
                tick_net_ms=s.perf_tick_net_ms,
                tick_lock_wait_ms=s.perf_tick_lock_wait_ms,
                tick_lock_hold_ms=s.perf_tick_lock_hold_ms,
                snapshot_wait_ms=snapshot_wait_ms,
            )
            source_debug = SourceDebugInfo(
                map_ok=bool(mp.ok),
                map_obj_count=int(mp.obj_count),
                player_present=bool(mp.ok and mp.player_aircraft_present),
                indicators_ok=bool(tel.ind_ok),
                indicators_valid=bool(tel.valid),
                has_type_name=bool(tel.type_name),
                state_ok=bool(tel.state_resp_ok),
                indicators_error_kind=str(tel.ind_error_kind or ""),
                state_error_kind=str(tel.state_error_kind or ""),
                map_error_kind=str(mp.error_kind or ""),
                map_info_error_kind=str(map_info_error_kind or ""),
                indicators_elapsed_ms=float(tel.ind_elapsed_ms or 0.0),
                state_elapsed_ms=float(tel.state_elapsed_ms or 0.0),
                map_elapsed_ms=float(mp.elapsed_ms or 0.0),
                map_info_elapsed_ms=float(map_info_elapsed_ms or 0.0),
                indicators_failure_streak=int(s.indicators_failure_streak),
                state_failure_streak=int(s.state_failure_streak),
                map_failure_streak=int(s.map_failure_streak),
                map_info_failure_streak=int(s.map_info_failure_streak),
                indicators_failure_count=int(s.indicators_failure_count),
                state_failure_count=int(s.state_failure_count),
                map_failure_count=int(s.map_failure_count),
                map_info_failure_count=int(s.map_info_failure_count),
                tel_fallback_count=int(s.tel_fallback_count),
                map_fallback_count=int(s.map_fallback_count),
                tel_fallback_active=bool(s.tel_fallback_active),
                map_fallback_active=bool(s.map_fallback_active),
            )

        remaining = None
        cycle = None
        progress = 0.0
        if phase in (Phase.ALIVE, Phase.LOSS_PENDING) and life_spawn_time is not None:
            elapsed = max(0.0, now - life_spawn_time)
            remaining = GameConfig.CYCLE_SECONDS - (elapsed % GameConfig.CYCLE_SECONDS)
            cycle = int(elapsed // GameConfig.CYCLE_SECONDS) + 1
            progress = (elapsed % GameConfig.CYCLE_SECONDS) / GameConfig.CYCLE_SECONDS

        api_down_pending = False
        if (api_down_candidate_since is not None) and (not api_down):
            api_down_pending = (
                now - api_down_candidate_since
            ) >= GameConfig.API_PENDING_HINT_DELAY_SEC

        landed_flash = landed_flash_until > now
        on_ground = tel.is_on_ground if tel.state_resp_ok else False

        overspeed = self.overspeed.evaluate(
            plane_type=tel.type_name,
            ias_kmh=tel.ias_kmh,
            tas_kmh=tel.tas_kmh,
            mach=tel.mach,
            wing_sweep=tel.wing_sweep,
            enabled=(
                OverspeedConfig.ENABLED
                and PanelConfig.is_effectively_enabled("speed")
                and (phase in (Phase.ALIVE, Phase.LOSS_PENDING))
                and tel.state_resp_ok
                and (not on_ground)
            ),
        )
        map_axis_scale_m = navigation.map_axis_scale_m(map_info)
        zone_display_list = self._build_zone_display_list(nav_zones, nav_ground_speed)
        friendly_airfield_display, enemy_airfields_display, has_airfield_target = (
            self._build_airfield_display(
                mp=mp,
                map_axis_scale_m=map_axis_scale_m,
                player_heading=nav_player_heading,
                ground_speed=nav_ground_speed,
            )
        )
        interest_point_display = self._build_interest_point_display(
            mp=mp,
            map_axis_scale_m=map_axis_scale_m,
            player_heading=nav_player_heading,
            ground_speed=nav_ground_speed,
        )
        traceback_point_display = self._build_traceback_display(
            site=traceback_site,
            mp=mp,
            map_axis_scale_m=map_axis_scale_m,
            player_heading=nav_player_heading,
            ground_speed=nav_ground_speed,
        )

        has_target = nav_target_zone is not None
        has_bombing_target = nav_bombing_target is not None
        bombing_target_kind = str(nav_bombing_target.kind) if nav_bombing_target else ""
        bombing_target_name = str(nav_bombing_target.name) if nav_bombing_target else ""
        if (not has_bombing_target) and nav_target_zone is not None:
            has_bombing_target = True
            bombing_target_kind = "zone"
            bombing_target_name = f"战区 #{nav_target_zone.index}"
        deviation_angle = nav_target_zone.relative if nav_target_zone else 0.0
        zone_destroyed_alert = nav_destroyed_alert_until > now
        destroyed_count = len(nav_destroyed_zones) if zone_destroyed_alert else 0
        destroyed_zone_display_list = self._build_zone_display_list(
            nav_destroyed_zones if zone_destroyed_alert else [],
            nav_ground_speed,
        )
        destroyed_zone_text = self._build_destroyed_zone_text(
            destroyed_zones=nav_destroyed_zones if zone_destroyed_alert else [],
            player_pos=mp.player_pos,
            map_axis_scale_m=map_axis_scale_m,
            player_heading=nav_player_heading,
        )

        fuel_rate_kg_min = fuel_consumption_rate if fuel_rate_stable else 0.0

        ground_speed_kmh_for_bombing = nav_ground_speed * ZoneConfig.DISTANCE_SCALE * 3600
        return_fuel_needed_kg = 0.0
        return_status = "unknown"
        friendly_distance_km = (
            friendly_airfield_display.distance_km if friendly_airfield_display else 0.0
        )
        if (
            friendly_airfield_display
            and fuel_rate_stable
            and ground_speed_kmh_for_bombing >= 50
            and friendly_distance_km > 0
        ):
            time_min = (friendly_distance_km / ground_speed_kmh_for_bombing) * 60.0
            return_fuel_needed_kg = (
                fuel_consumption_rate * time_min * FuelConfig.RETURN_SAFETY_FACTOR
            )
            if return_fuel_needed_kg > 0:
                if fuel_current_kg >= return_fuel_needed_kg * FuelConfig.RETURN_WARNING_FACTOR:
                    return_status = "safe"
                elif fuel_current_kg >= return_fuel_needed_kg:
                    return_status = "warning"
                else:
                    return_status = "danger"

        gear_warning = False
        if phase == Phase.ALIVE and tel.state_resp_ok:
            is_airborne = (tel.ias_kmh > 80) or (tel.altitude_m > 50)
            if is_airborne and tel.gear_down:
                gear_warning = True

        raw_gear_pct = float(tel.gear_pct or 0.0)
        gear_pct = gear_stable_pct if gear_stable_pct >= 0 else raw_gear_pct
        gear_moving = 0 < raw_gear_pct < 100
        gear_retracting = gear_stable_direction if gear_moving else False

        bombing_valid = False
        bomb_name = BombConfig.selected_bomb if ENABLE_CCRP else ""
        bomb_range_m = 0.0
        bomb_flight_time = 0.0
        release_distance_m = 0.0
        time_to_release = 0.0
        release_status = "invalid"
        target_zone_distance_m = 0.0
        bombing_unavailable_reason = cached_bombing_unavailable_reason
        if nav_bombing_target is not None:
            target_zone_distance_m = nav_bombing_target.distance * ZoneConfig.DISTANCE_SCALE * 1000
        elif nav_target_zone is not None:
            target_zone_distance_m = nav_target_zone.distance * ZoneConfig.DISTANCE_SCALE * 1000
        if ENABLE_CCRP and bombing_calc_valid:
            bombing_valid = True
            bomb_flight_time = cached_bomb_flight_time
            bomb_range_m = cached_bomb_range_m
            release_distance_m = cached_release_distance_m
            time_to_release = cached_time_to_release
            release_status = cached_release_status
            target_zone_distance_m = cached_target_distance_m
            bombing_target_kind = cached_bombing_target_kind or bombing_target_kind
            bombing_target_name = cached_bombing_target_name or bombing_target_name
            has_bombing_target = bool(bombing_target_kind)
            bombing_unavailable_reason = ""

        return UISnapshot(
            phase=phase,
            life_index=life_index,
            cycle=cycle,
            remaining_sec=remaining,
            progress=progress,
            sortie_id=sortie_id,
            api_down=api_down,
            api_down_pending=api_down_pending,
            on_ground=on_ground,
            landed_flash=landed_flash,
            perf_debug=perf_debug,
            source_debug=source_debug,
            zones=zone_display_list,
            friendly_airfield=friendly_airfield_display,
            enemy_airfields=enemy_airfields_display,
            interest_point=interest_point_display,
            traceback_point=traceback_point_display,
            map_player_x=(float(map_player_pos[0]) if map_player_pos is not None else None),
            map_player_y=(float(map_player_pos[1]) if map_player_pos is not None else None),
            map_points=tuple(map_points),
            has_airfield_target=has_airfield_target,
            has_target=has_target,
            has_bombing_target=has_bombing_target,
            bombing_target_kind=bombing_target_kind,
            bombing_target_name=bombing_target_name,
            is_deviating=nav_is_deviating,
            deviation_angle=deviation_angle,
            zone_destroyed_alert=zone_destroyed_alert,
            destroyed_zone_count=destroyed_count,
            destroyed_zone_text=destroyed_zone_text,
            destroyed_zones=destroyed_zone_display_list,
            should_play_destroyed_sound=nav_should_play_destroyed_sound,
            player_heading=nav_player_heading,
            fuel_kg=fuel_current_kg,
            fuel_initial_kg=fuel_initial_kg,
            fuel_percent=fuel_percent,
            fuel_rate_kg_min=fuel_rate_kg_min,
            fuel_rate_stable=fuel_rate_stable,
            fuel_remaining_time_min=fuel_remaining_time_min,
            altitude_m=tel.altitude_m,
            return_fuel_needed_kg=return_fuel_needed_kg,
            return_status=return_status,
            friendly_distance_km=friendly_distance_km,
            gear_warning=gear_warning,
            gear_pct=gear_pct,
            gear_moving=gear_moving,
            gear_retracting=gear_retracting,
            bombing_valid=bombing_valid,
            bomb_name=bomb_name,
            bomb_range_m=bomb_range_m,
            bomb_flight_time=bomb_flight_time,
            release_distance_m=release_distance_m,
            time_to_release=time_to_release,
            release_status=release_status,
            target_zone_distance_m=target_zone_distance_m,
            bombing_unavailable_reason=bombing_unavailable_reason,
            ground_speed_kmh=ground_speed_kmh_for_bombing,
            aircraft_type_name=str(tel.type_name or ""),
            attitude_pitch_deg=attitude_pitch_deg,
            attitude_roll_deg=attitude_roll_deg,
            attitude_bank_deg=attitude_bank_deg,
            attitude_reliable=attitude_reliable,
            hud_attitude_fallback=attitude_fallback,
            hud_attitude_fallback_reason=attitude_fallback_reason,
            overspeed_level=overspeed.level,
            overspeed_ratio=float(overspeed.ias_ratio or 0.0),
            overspeed_current_ias_kmh=float(overspeed.ias_kmh or 0.0),
            overspeed_current_mach=(float(overspeed.mach) if overspeed.mach is not None else None),
            overspeed_limit_kmh=float(overspeed.ias_limit_kmh or 0.0),
            overspeed_limit_mach=float(overspeed.mach_limit or 0.0),
            overspeed_match=bool(overspeed.resolved_fm),
            overspeed_reason=overspeed.reason,
            **weapon_snapshot,
        )
