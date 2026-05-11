# -*- coding: utf-8 -*-
"""Core state models and enums."""

from dataclasses import dataclass, field
from collections import deque
from enum import Enum, auto
from typing import Optional, Tuple, Any, List, Dict

from bomana.config import GameConfig, FuelConfig

# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class TelemetryData:
    """遥测数据（来自8111接口）
    
    包含飞机的基本状态信息，用于判断出生/死亡/着陆等状态。
    """
    ind_ok: bool = False          # /indicators 请求成功
    state_resp_ok: bool = False   # /state 请求成功
    valid: bool = False           # 数据有效性标志
    type_name: str = ""           # 飞机型号名称
    ias_kmh: float = 0            # 指示空速 (km/h)
    vy_ms: float = 0              # 垂直速度 (m/s)
    fuel_kg: float = 0            # 燃油量 (kg)
    compass: float = 0            # 罗盘航向 (度)
    
    # v5.8 新增：燃油管理相关字段
    fuel0_kg: float = 0           # 起飞油量 (kg) - 来自 Mfuel0
    altitude_m: float = 0         # 飞行高度 (m)
    tas_kmh: float = 0            # 真空速 (km/h)
    throttle_pct: float = 0       # 油门百分比 (%)
    mach: Optional[float] = None  # 马赫数
    wing_sweep: Optional[float] = None  # 后掠翼位置 (0~1, 可为空)
    
    # v5.9.6 新增：起落架状态
    gear_down: bool = False       # 起落架是否放下 (True=放下, False=收起)
    
    # v6.6.0 新增：起落架百分比（用于进度指示器）
    gear_pct: float = 0.0         # 起落架位置百分比 (0=收起, 100=放下)

    # v6.8.0 新增：HUD姿态字段（来自 aviahorizon_* / bank）
    attitude_pitch_deg: float = 0.0
    attitude_roll_deg: float = 0.0
    attitude_bank_deg: float = 0.0
    attitude_pitch_present: bool = False
    attitude_roll_present: bool = False
    attitude_bank_present: bool = False
    attitude_available: bool = False

    @property
    def entity_like(self) -> bool:
        """判断是否像一个"实体"（有燃油或速度）
        
        用于区分真正的飞机和无效数据。
        """
        if not (self.ind_ok and self.state_resp_ok and self.valid and self.type_name):
            return False
        return (self.fuel_kg > 0.1) or (abs(self.ias_kmh) > 0.1) or (abs(self.vy_ms) > 0.1)

    @property
    def is_on_ground(self) -> bool:
        """判断是否在地面
        
        低速 + 小垂直速度 = 可能着陆
        """
        return (self.ias_kmh < GameConfig.LAND_SPEED_KMH and abs(self.vy_ms) < 2.0)

    @property
    def attitude_lateral_deg(self) -> float:
        """获取横滚轴数据（优先 roll，缺失时回退 bank）。"""
        return self.attitude_roll_deg if self.attitude_roll_present else self.attitude_bank_deg


@dataclass
class Zone:
    """战区数据结构
    
    存储单个战区的位置、导航信息。
    """
    id: str                    # 唯一标识（基于坐标生成）
    index: int                 # 战区编号（1开始）
    x: float                   # X坐标（归一化）
    y: float                   # Y坐标（归一化）
    color: str = ""            # 颜色标识（API返回）
    distance: float = 0.0      # 距离玩家的距离
    bearing: float = 0.0       # 绝对方位角
    relative: float = 0.0      # 相对方位角
    is_target: bool = False    # 是否为当前目标


@dataclass
class Airfield:
    """机场数据结构
    
    存储机场位置、归属、导航信息。
    """
    id: str                    # 唯一标识
    index: int                 # 机场编号
    x: float                   # X坐标（归一化）
    y: float                   # Y坐标（归一化）
    color: str = ""            # 颜色标识
    is_friendly: bool = False  # 是否为友方机场
    distance: float = 0.0      # 距离
    bearing: float = 0.0       # 绝对方位
    relative: float = 0.0      # 相对方位
    is_target: bool = False    # 是否为目标


@dataclass
class MapObjData:
    """地图对象数据（来自/map_obj.json）
    
    包含玩家、战区、机场的所有信息。
    """
    ok: bool = False                                # 请求成功
    player_aircraft_present: bool = False           # 玩家飞机存在
    player_pos: Optional[Tuple[float, float]] = None  # 玩家位置
    player_dx: float = 0.0                          # 玩家速度向量X
    player_dy: float = 0.0                          # 玩家速度向量Y
    obj_count: int = 0                              # 对象总数
    zones: List[Zone] = field(default_factory=list)           # 战区列表
    airfields: List[Airfield] = field(default_factory=list)   # 机场列表


@dataclass
class MapInfo:
    """地图元数据（来自/map_info.json）
    
    提供地图尺度参数（如 map_min/map_max），缓存30秒避免频繁请求。
    """
    valid: bool = False
    grid_size: List[float] = field(default_factory=lambda: [52719.0, 55385.0])
    grid_steps: List[float] = field(default_factory=lambda: [5500.0, 5500.0])
    grid_zero: List[float] = field(default_factory=lambda: [0.0, 0.0])
    map_min: List[float] = field(default_factory=lambda: [-65536.0, -65536.0])
    map_max: List[float] = field(default_factory=lambda: [65536.0, 65536.0])
    fetch_time: float = 0.0    # 获取时间（用于判断是否过期）


class Phase(Enum):
    """游戏阶段枚举
    
    定义计时器的所有可能状态。
    """
    IDLE = auto()          # 空闲（未开始）
    HANGAR = auto()        # 机库中
    ARMING = auto()        # 准备出生（检测到飞机但未确认）
    ALIVE = auto()         # 存活中（正在计时）
    LOSS_PENDING = auto()  # 可能死亡（玩家消失但未确认）
    WAIT_NEXT = auto()     # 等待下次复活


@dataclass
class LifeState:
    """单次生命状态
    
    记录一次出生的时间和编号，用于计算当前周期。
    """
    spawn_time: float      # 出生时间戳（秒）
    life_index: int        # 复活次数（1开始）

    def elapsed_seconds(self, now: float) -> float:
        """计算已存活秒数"""
        return now - self.spawn_time

    def current_cycle(self, now: float) -> int:
        """计算当前是第几轮（1开始）"""
        return int(self.elapsed_seconds(now) // GameConfig.CYCLE_SECONDS) + 1

    def cycle_remaining(self, now: float) -> float:
        """计算当前周期剩余秒数"""
        elapsed = self.elapsed_seconds(now)
        return GameConfig.CYCLE_SECONDS - (elapsed % GameConfig.CYCLE_SECONDS)

    def cycle_progress(self, now: float) -> float:
        """计算当前周期进度（0.0-1.0）"""
        elapsed = self.elapsed_seconds(now)
        return (elapsed % GameConfig.CYCLE_SECONDS) / GameConfig.CYCLE_SECONDS


@dataclass
class FuelSample:
    """燃油采样点
    
    记录某一时刻的燃油量，用于计算油耗率。
    """
    timestamp: float    # 时间戳
    fuel_kg: float      # 油量
    altitude_m: float   # 高度（用于分析，可选）


@dataclass
class FuelState:
    """燃油状态管理
    
    采样燃油变化,计算油耗率,估算剩余飞行时间和返航油量。
    
    性能优化: 使用deque管理采样数据
    - deque.popleft()是O(1), list.pop(0)是O(n)
    - maxlen自动限制大小(60秒窗口/2秒间隔=30样本)
    """
    current_kg: float = 0.0           # 当前油量
    initial_kg: float = 0.0           # 起飞油量（来自Mfuel0）
    
    # 采样缓冲（使用deque，maxlen=30对应60秒窗口/2秒间隔）
    samples: deque = field(default_factory=lambda: deque(maxlen=30))
    last_sample_time: float = 0.0     # 上次采样时间
    
    # 计算结果
    consumption_rate: float = 0.0     # 油耗率 (kg/min)
    rate_stable: bool = False         # 油耗率是否稳定
    
    def update(self, fuel_kg: float, fuel0_kg: float, altitude_m: float, 
               ias_kmh: float, now: float) -> None:
        """更新燃油状态
        
        Args:
            fuel_kg: 当前油量
            fuel0_kg: 起飞油量（API提供）
            altitude_m: 当前高度
            ias_kmh: 指示空速
            now: 当前时间戳
        """
        self.current_kg = fuel_kg
        
        # 更新起飞油量（只在有效时更新）
        if fuel0_kg > 0:
            self.initial_kg = fuel0_kg
        
        # 检测补给（油量突增）→ 清空历史
        if self.samples and fuel_kg > self.samples[-1].fuel_kg + FuelConfig.REFUEL_JUMP_KG:
            self.samples.clear()
            self.rate_stable = False
            self.consumption_rate = 0.0
            # 补给后更新起飞油量
            if fuel0_kg > 0:
                self.initial_kg = fuel0_kg
            self.last_sample_time = now
            return
        
        # 低速时不采样（地面或悬停）
        if ias_kmh < FuelConfig.MIN_FLIGHT_SPEED_KMH:
            return
        
        # 控制采样频率
        if (now - self.last_sample_time) < FuelConfig.SAMPLE_INTERVAL_SEC:
            return
        
        # 添加新样本（deque自动丢弃超出maxlen的旧样本）
        self.samples.append(FuelSample(now, fuel_kg, altitude_m))
        self.last_sample_time = now
        
        # 清理过期样本（补充清理，处理时间间隔不均匀的情况）
        cutoff = now - FuelConfig.SAMPLE_WINDOW_SEC
        while self.samples and self.samples[0].timestamp < cutoff:
            self.samples.popleft()  # O(1) 操作
        
        # 计算油耗率
        self._calculate_consumption_rate()
    
    def _calculate_consumption_rate(self) -> None:
        """计算油耗率（kg/min）"""
        if len(self.samples) < FuelConfig.MIN_STABLE_SAMPLES:
            self.rate_stable = False
            return
        
        oldest = self.samples[0]
        newest = self.samples[-1]
        dt_min = (newest.timestamp - oldest.timestamp) / 60.0
        
        if dt_min < 0.1:  # 至少6秒数据
            self.rate_stable = False
            return
        
        fuel_used = oldest.fuel_kg - newest.fuel_kg
        if fuel_used < 0:
            # 油量增加了（可能是数据抖动），忽略
            self.rate_stable = False
            return
        
        self.consumption_rate = fuel_used / dt_min
        self.rate_stable = True
    
    def reset(self) -> None:
        """重置燃油状态"""
        self.current_kg = 0.0
        self.initial_kg = 0.0
        self.samples.clear()
        self.last_sample_time = 0.0
        self.consumption_rate = 0.0
        self.rate_stable = False
    
    @property
    def fuel_percent(self) -> float:
        """剩余油量百分比"""
        if self.initial_kg <= 0:
            return 0.0
        return min(100.0, (self.current_kg / self.initial_kg) * 100)
    
    @property
    def remaining_time_min(self) -> Optional[float]:
        """剩余飞行时间（分钟）"""
        if not self.rate_stable or self.consumption_rate <= 0:
            return None
        return self.current_kg / self.consumption_rate
    
    def estimate_return_fuel(self, distance_km: float, ground_speed_kmh: float) -> Optional[float]:
        """估算返航所需油量（kg）
        
        Args:
            distance_km: 到友方机场距离（km）
            ground_speed_kmh: 地速（km/h）
        
        Returns:
            返航所需油量（kg），无法估算时返回None
        """
        if not self.rate_stable or ground_speed_kmh < 50 or distance_km <= 0:
            return None
        
        time_hours = distance_km / ground_speed_kmh
        time_min = time_hours * 60
        return self.consumption_rate * time_min * FuelConfig.RETURN_SAFETY_FACTOR
    
    def get_return_status(self, return_fuel_needed: Optional[float]) -> str:
        """获取返航状态
        
        Args:
            return_fuel_needed: 返航所需油量
        
        Returns:
            "safe" / "warning" / "danger" / "unknown"
        """
        if return_fuel_needed is None or return_fuel_needed <= 0:
            return "unknown"
        
        if self.current_kg >= return_fuel_needed * FuelConfig.RETURN_WARNING_FACTOR:
            return "safe"
        elif self.current_kg >= return_fuel_needed:
            return "warning"
        else:
            return "danger"


@dataclass
class ZoneNavigationState:
    """战区导航状态
    
    管理战区列表、目标选择、被摧毁战区追踪、地速计算。
    """
    zones: List[Zone] = field(default_factory=list)              # 当前战区列表
    target_zone: Optional[Zone] = None                           # 当前目标战区
    previous_zone_ids: set = field(default_factory=set)          # 上一帧战区ID集合
    destroyed_zones: List[Zone] = field(default_factory=list)    # 被摧毁的战区
    destroyed_alert_until: float = 0.0                           # 摧毁警告持续到的时间戳
    is_deviating: bool = False                                   # 是否偏航
    player_heading: float = 0.0                                  # 玩家航向
    should_play_destroyed_sound: bool = False                    # 是否应该播放摧毁音效（v5.5新增）
    
    # 地速计算相关（v5.2新增）
    last_pos: Optional[Tuple[float, float]] = None  # 上次位置
    last_pos_ts: float = 0.0                        # 上次位置时间戳
    ground_speed: float = 0.0                       # 地速（归一化单位/秒）
    
    # v5.7: 目标锁定相关（智能目标切换）
    locked_target_id: Optional[str] = None          # 当前锁定的目标ID（粘性）
    precise_aim_candidate_id: Optional[str] = None  # 精确对准候选目标ID
    precise_aim_since: float = 0.0                  # 开始精确对准的时间戳


@dataclass
class AttitudeConfidenceState:
    """HUD姿态可信度状态。"""
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    bank_deg: float = 0.0
    available: bool = False
    reliable: bool = False
    fallback: bool = True
    fallback_reason: str = "missing"
    missing_since: Optional[float] = None
    zero_since: Optional[float] = None
    jitter_score: float = 0.0
    last_pitch_deg: Optional[float] = None
    last_roll_deg: Optional[float] = None
    last_sample_ts: float = 0.0


@dataclass
class GameState:
    """游戏总体状态
    
    所有游戏逻辑状态的集合，由GameLogic类管理。
    """
    phase: Phase = Phase.IDLE                                    # 当前阶段
    # v6.0.1 新增：弹道计算缓存（在tick线程计算，减少UI线程负载）
    cached_bomb_flight_time: float = 0.0
    cached_bomb_range_m: float = 0.0
    cached_release_distance_m: float = 0.0
    cached_time_to_release: float = 0.0
    cached_release_status: str = "invalid"
    cached_target_distance_m: float = 0.0
    bombing_calc_valid: bool = False
    last_bombing_calc_time: float = 0.0
    current_life: Optional[LifeState] = None                     # 当前生命
    sortie_id: int = 0                                           # 出击计数（补给时递增）
    last_refit_ts: float = 0.0                                   # 上次补给时间
    
    # 状态确认相关（防止误判）
    spawn_candidate_since: Optional[float] = None                # 出生候选开始时间
    missing_player_since: Optional[float] = None                 # 玩家消失开始时间
    last_player_present_ts: float = 0.0                          # 最近一次确认玩家存在（用于短时抖动宽限）
    landing_start_time: Optional[float] = None                   # 着陆开始时间
    landed_flash_until: float = 0.0                              # 着陆闪烁持续到
    hangar_candidate_since: Optional[float] = None               # 机库候选开始时间
    
    # API状态
    api_down: bool = False                                       # API是否断线
    api_down_candidate_since: Optional[float] = None             # API断线候选时间
    
    # 缓存的数据
    last_tel: Optional[TelemetryData] = None                     # 上一帧遥测数据
    last_map: Optional[MapObjData] = None                        # 上一帧地图数据
    map_info: Optional[MapInfo] = None                           # 地图元数据（缓存）
    
    # 导航状态
    zone_nav: ZoneNavigationState = field(default_factory=ZoneNavigationState)

    # v6.8.0 新增：姿态可信度（HUD 2.5D/2D 降级决策）
    attitude: AttitudeConfidenceState = field(default_factory=AttitudeConfidenceState)
    
    # v5.8 新增：燃油状态
    fuel_state: FuelState = field(default_factory=FuelState)
    
    # v6.6.0 新增：起落架进度追踪
    last_gear_pct: float = -1.0                                  # 上一帧起落架百分比（-1=未初始化）
    # v6.6.1 新增：起落架消抖
    gear_stable_pct: float = -1.0                                # 稳定后的起落架百分比（-1=未初始化）
    gear_stable_direction: bool = False                          # 稳定后的方向（True=收起）
    gear_change_time: float = 0.0                                # 上次变化时间

    # 轻量性能诊断（用于排查 UI/锁/8111 卡顿来源）
    perf_tick_total_ms: float = 0.0
    perf_tick_net_ms: float = 0.0
    perf_tick_lock_wait_ms: float = 0.0
    perf_tick_lock_hold_ms: float = 0.0


@dataclass(frozen=True)
class ZoneDisplayInfo:
    """战区显示信息（UI层数据）
    
    不可变数据类，用于快照传递给UI。
    """
    id: str
    distance_km: float
    direction: str
    relative: float
    is_target: bool
    ete_str: str = ""      # 预计抵达时间字符串
    cdi_indicator: str = ""  # 航道偏差指示器字符串
    cdi_color: str = ""      # 指示器颜色


@dataclass(frozen=True)
class AirfieldDisplayInfo:
    """机场显示信息（UI层数据）"""
    id: str
    side: str              # "friendly" 或 "enemy"
    distance_km: float
    direction: str
    relative: float
    is_target: bool
    ete_str: str = ""
    cdi_indicator: str = ""  # 航道偏差指示器字符串
    cdi_color: str = ""      # 指示器颜色


@dataclass(frozen=True)
class PerfDebugInfo:
    """性能诊断信息。"""
    tick_total_ms: float = 0.0
    tick_net_ms: float = 0.0
    tick_lock_wait_ms: float = 0.0
    tick_lock_hold_ms: float = 0.0
    snapshot_wait_ms: float = 0.0


@dataclass(frozen=True)
class SourceDebugInfo:
    """8111 数据源诊断信息。"""
    map_ok: bool = False
    map_obj_count: int = 0
    player_present: bool = False
    indicators_ok: bool = False
    indicators_valid: bool = False
    has_type_name: bool = False
    state_ok: bool = False


@dataclass(frozen=True)
class UISnapshot:
    """UI快照（逻辑层 → UI层的数据传递）
    
    不可变快照，包含UI渲染所需的所有信息。
    每帧生成一次，避免线程安全问题。
    """
    phase: Phase
    life_index: Optional[int]
    cycle: Optional[int]
    remaining_sec: Optional[float]
    progress: float
    sortie_id: int
    main_badge: Tuple[str, str, str]      # (文本, 前景色, 背景色)
    flight_badge: Tuple[str, str, str]
    status_text: str
    api_down: bool
    api_down_pending: bool
    on_ground: bool
    landed_flash: bool
    perf_debug: PerfDebugInfo = field(default_factory=PerfDebugInfo)
    source_debug: SourceDebugInfo = field(default_factory=SourceDebugInfo)
    
    # 导航相关
    zones: List[ZoneDisplayInfo] = field(default_factory=list)
    friendly_airfield: Optional[AirfieldDisplayInfo] = None
    enemy_airfields: List[AirfieldDisplayInfo] = field(default_factory=list)
    has_airfield_target: bool = False
    has_target: bool = False
    is_deviating: bool = False
    deviation_angle: float = 0.0
    
    # 战区被摧毁警告
    zone_destroyed_alert: bool = False
    destroyed_zone_count: int = 0
    destroyed_zone_text: str = ""
    should_play_destroyed_sound: bool = False  # v5.5新增：是否应该播放摧毁音效
    
    player_heading: float = 0.0
    
    # v5.8 新增：燃油管理
    fuel_kg: float = 0.0                       # 当前油量
    fuel_initial_kg: float = 0.0               # 起飞油量
    fuel_percent: float = 0.0                  # 油量百分比
    fuel_rate_kg_min: float = 0.0              # 油耗率 (kg/min)
    fuel_rate_stable: bool = False             # 油耗率是否稳定
    fuel_time_remaining_str: str = ""          # 剩余飞行时间字符串
    altitude_m: float = 0.0                    # 高度
    
    # 返航估算
    return_fuel_needed_kg: float = 0.0         # 返航所需油量
    return_status: str = "unknown"             # "safe"/"warning"/"danger"/"unknown"
    friendly_distance_km: float = 0.0          # 到友方机场距离
    
    # v5.9.6 新增：起落架警告
    gear_warning: bool = False                 # 起落架未收起警告
    
    # v6.6.0 新增：起落架进度指示器
    gear_pct: float = 0.0                      # 起落架位置百分比 (0-100)
    gear_moving: bool = False                  # 起落架是否正在移动
    gear_retracting: bool = False              # 是否正在收起（True=收起/蓝色，False=放下/黄色）
    
    # v6.0 新增：投弹预测
    bombing_valid: bool = False                # 投弹预测是否有效
    bomb_name: str = ""                        # 当前炸弹名称
    bomb_range_m: float = 0.0                  # 炸弹水平飞行距离 (米)
    bomb_flight_time: float = 0.0              # 炸弹飞行时间 (秒)
    release_distance_m: float = 0.0            # 投弹距离 (米)
    time_to_release: float = 0.0               # 到投弹点时间 (秒)
    release_status: str = "invalid"            # ready/approaching/too_far/passed/invalid
    target_zone_distance_m: float = 0.0        # 目标战区距离 (米)
    ground_speed_kmh: float = 0.0              # 地速 (km/h)
    aircraft_type_name: str = ""               # 当前机型标识（来自 /indicators.type）

    # v6.8.0 新增：HUD姿态链路输出
    attitude_pitch_deg: float = 0.0
    attitude_roll_deg: float = 0.0
    attitude_bank_deg: float = 0.0
    attitude_reliable: bool = False
    hud_attitude_fallback: bool = True
    hud_attitude_fallback_reason: str = "missing"

    # v6.9.0 新增：超速提醒链路
    overspeed_level: str = "unknown"        # unknown/safe/caution/warning/critical
    overspeed_ratio: float = 0.0            # IAS占限速百分比（0~1）
    overspeed_display_ratio: float = 0.0    # UI显示比例（IAS/Mach中更危险的一侧）
    overspeed_current_ias_kmh: float = 0.0  # 当前IAS
    overspeed_current_mach: Optional[float] = None  # 当前马赫
    overspeed_limit_kmh: float = 0.0        # 机型IAS限速
    overspeed_limit_mach: float = 0.0       # 机型马赫限速
    overspeed_match: bool = False           # 是否成功匹配机型限速
    overspeed_reason: str = ""              # 判定来源（ias/mach/ias+mach/safe/unknown）
