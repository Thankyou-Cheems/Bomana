# -*- coding: utf-8 -*-
"""
配置与元数据集中管理。
"""

from pathlib import Path
import json

# =============================================================================
# 标准元数据 (Standard Metadata)
# =============================================================================
__title__ = "Bomana"
__version__ = "6.7.4"
__author__ = "Thankyou-Cheems"
__license__ = "MIT"
__copyright__ = "Copyright 2024-2026 Thankyou-Cheems"
__repository__ = "https://github.com/Thankyou-Cheems/Bomana"

# ============================================================================
# 编译开关 - 功能模块启用控制
# ============================================================================
# 本地源码直接运行（python Bomana.pyw）默认全功能，提升测试体验。
# 构建脚本 tools/build_portable.py 会按变体临时覆盖这些值，并在结束后恢复。
# 因此此处默认值不会改变 Enhanced/Standard/Lite 的打包结果。

ENABLE_CCRP = True
ENABLE_ZONES = True
ENABLE_AIRFIELDS = True
ENABLE_FUEL = True
ENABLE_CHECKLIST = True
ENABLE_ADVANCED_SETTINGS = True


# ============================================================================
# 配置类 - 所有可调参数集中管理
# ============================================================================

class GameConfig:
    """游戏逻辑相关配置

    这些参数直接影响游戏状态判断的准确性，修改时需谨慎测试。
    """
    # 复活周期：15分钟（战雷SB标准）
    CYCLE_SECONDS = 15 * 60

    # 最后警告时间：30秒（进入黄色/红色警告区）
    FINAL_WARNING_SEC = 30

    # 着陆判断参数
    LAND_SPEED_KMH = 40          # 低于此速度视为可能着陆
    LAND_CONFIRM_SEC = 3.0       # 持续低速3秒确认着陆
    LANDED_FLASH_SEC = 10.0      # 着陆后"就绪"状态闪烁10秒

    # 状态确认时间（防止误判）
    SPAWN_CONFIRM_SEC = 1.0      # 出生确认：连续1秒有实体数据
    DEAD_CONFIRM_SEC = 1.2       # 死亡确认：连续1.2秒无玩家
    HANGAR_CONFIRM_SEC = 1.2     # 机库确认：连续1.2秒无地图数据
    API_DOWN_CONFIRM_SEC = 5.0   # API断线确认：连续5秒无响应
    PLAYER_PRESENCE_GRACE_SEC = 1.2   # ALIVE阶段短时数据抖动宽限（按计分板/地图常见）
    API_PENDING_HINT_DELAY_SEC = 0.35 # 断线候选需持续到该时长才显示“加入战斗中”

    # 补给判断参数（检测地面补给站）
    REFIT_FUEL_JUMP_KG = 50.0    # 油量突增50kg以上
    REFIT_MIN_GAP_SEC = 8.0      # 两次补给最小间隔
    REFIT_SPEED_KMH = 12.0       # 补给时速度很低
    REFIT_VSPEED_MS = 1.2        # 补给时垂直速度很小


class ZoneConfig:
    """战区导航相关配置"""

    # CDI(航道偏差指示器)配置
    CDI_WIDTH = 31  # 指示器宽度(字符数,奇数确保中心点) - v6. v6.1提升精度

    # 动态容差: (距离上限km, 容差角度°) - 距离越近要求越精确
    # v6.1优化: 针对高空投弹场景，在12km处就开始收紧阈值
    CDI_TOLERANCE_THRESHOLDS = [
        (2.0, 0.5),     # <2km: ±0.5° 极限精准（投弹瞬间）
        (5.0, 1.0),     # <5km: ±1.0° 投弹窗口
        (8.0, 2.0),     # <8km: ±2.0° 精确瞄准
        (12.0, 3.0),    # <12km: ±3.0° 投弹准备（高空投弹关键区间）
        (20.0, 5.0),    # <20km: ±5.0° 接近目标
        (35.0, 8.0),    # <35km: ±8.0° 中距离
        (float('inf'), 12.0)  # >35km: ±12.0° 远距离巡航
    ]

    # v6.1新增: 航向带(Heading Tape)配置
    HEADING_TAPE_ENABLED = True           # 是否启用航向带
    HEADING_TAPE_WIDTH = 280              # 航向带宽度(像素)
    HEADING_TAPE_HEIGHT = 32              # 航向带高度(像素)
    HEADING_TAPE_PIXELS_PER_DEG = 8       # 基础缩放: 每度8像素
    HEADING_TAPE_MAX_SCALE = 4.0          # 最大缩放倍数(近距离时)
    HEADING_TAPE_SCALE_START_KM = 15.0    # 开始缩放的距离(km)
    HEADING_TAPE_SCALE_END_KM = 3.0       # 达到最大缩放的距离(km)

    # CDI符号定义
    CDI_CENTER = "●"      # 中心指示点
    CDI_TRACK = "━"       # 轨道线
    CDI_LEFT = "◁"        # 左边界
    CDI_RIGHT = "▷"       # 右边界
    CDI_OVERFLOW_LEFT = "◀◀"   # 严重偏左指示
    CDI_OVERFLOW_RIGHT = "▶▶"  # 严重偏右指示

    # 航向容差：±45°内视为正对目标
    HEADING_TOLERANCE = 45

    # 偏航警告：超过±60°显示偏航提示
    DEVIATION_WARNING = 60

    # 战区被摧毁警告持续时间：30秒
    DESTROYED_ALERT_SEC = 30.0

    # 最多显示战区数量：6个（避免UI过长）
    MAX_DISPLAY_ZONES = 6

    # 最多显示机场数量（友方+敌方合计）
    MAX_DISPLAY_AIRFIELDS = 6

    # 距离缩放系数：归一化距离 × 100 = km
    # （战雷地图归一化为0-1，实际约100km）
    DISTANCE_SCALE = 100.0

    # 地图信息缓存时间：30秒（减少API请求）
    MAP_INFO_CACHE_SEC = 30.0

    # v5.7: 目标锁定相关配置
    # 精确对准角度阈值：<5°视为精确对准
    PRECISE_AIM_THRESHOLD = 5

    # 精确对准确认时间：持续3秒后切换目标
    PRECISE_AIM_CONFIRM_SEC = 3.0

    # 目标保持角度：超过90°视为目标丢失
    TARGET_HOLD_ANGLE = 90

    # 敌方机场ETE显示角度：只在<45°时显示ETE
    ENEMY_AIRFIELD_ETE_ANGLE = 45


class FuelConfig:
    """燃油管理相关配置

    燃油采样、警告阈值、返航估算参数。
    """
    # 采样参数
    SAMPLE_INTERVAL_SEC = 1.0        # 采样间隔缩短至1秒，使燃油流速计算更灵敏
    SAMPLE_WINDOW_SEC = 60.0         # 历史窗口（秒）
    MIN_STABLE_SAMPLES = 5           # 最少稳定样本数

    # 补给检测（油量突增）
    REFUEL_JUMP_KG = 30.0            # 油量增加超过此值视为补给

    # 警告阈值（基于百分比）
    WARNING_PERCENT = 30             # 黄色警告阈值
    DANGER_PERCENT = 15              # 红色警告阈值

    # 返航安全系数
    RETURN_SAFETY_FACTOR = 1.3       # 返航油量估算的安全系数（30%余量）
    RETURN_WARNING_FACTOR = 1.5      # 低于此倍数时提醒返航

    # 显示开关
    SHOW_FUEL_PANEL = True           # 是否显示燃油面板
    SHOW_CONSUMPTION_RATE = True     # 是否显示油耗率
    SHOW_ALTITUDE = True             # 是否显示高度

    # 最小飞行速度（低于此速度不计算油耗率）
    MIN_FLIGHT_SPEED_KMH = 50.0


class NetworkConfig:
    """网络请求相关配置

    8111接口的超时和轮询参数，影响响应速度和资源占用。
    """
    # 8111接口基础URL（本地回环地址）
    API_BASE = "http://127.0.0.1:8111"

    # 连接超时：50ms（保留快速失败，同时降低打包环境偶发超时抖动）
    API_CONNECT_TIMEOUT = 0.05

    # 读取超时：80ms（计分板/地图切换时8111短卡顿更稳）
    API_READ_TIMEOUT = 0.08

    # 单次tick最大网络耗时：300ms
    MAX_TICK_NET_BUDGET = 0.30

    # API断线时的轮询间隔：1.25秒（降低CPU占用）
    BACKOFF_MAX = 1.25

    # 正常轮询间隔：50ms（20次/秒，与UI刷新频率一致，大幅提升仪表平滑度）
    POLL_INTERVAL = 0.05


class UIConfig:
    """UI显示相关配置

    [UI缩放机制]
    - 基础缩放: UI_SCALE_MULT (默认1.0)
    - DPI缩放: 自动根据系统DPI调整
    - 智能缩放: 首次启动时根据屏幕分辨率自动调整
      * 1080p及以下: 1.5x
      * 1440p: 1.2x
      * 4K及以上: 0.9x
    - 用户可调范围: 0.6-1.5

    最终缩放 = DPI缩放 × UI_SCALE_MULT
    """
    # UI缩放倍数：1.0（相对于系统DPI的额外缩放）
    # v5.9.3: 从0.85提升到1.0，让界面在1080p/2k下更清晰
    # 注意：此值可能被智能缩放逻辑覆盖（首次启动时）
    UI_SCALE_MULT = 1.0

    # 窗口不透明度：210/255（约82%）
    WINDOW_ALPHA = 210

    # UI刷新频率：50ms（20fps，流畅且省资源）
    UI_REFRESH_MS = 50

    # 字体定义（字体名, 大小, 样式）
    FONT_TIMER = ("Segoe UI", 44, "bold")           # 主计时器
    FONT_LIFE = ("Segoe UI", 13, "bold")            # 复活次数
    FONT_CYCLE = ("Segoe UI", 12)                   # 当前轮次
    FONT_PILL = ("Segoe UI", 10, "bold")            # 状态徽章
    FONT_STATUS = ("Segoe UI", 11)                  # 状态文本
    FONT_CHECKLIST_TITLE = ("Segoe UI", 9, "bold")  # 检查清单标题
    FONT_CHECKLIST_ITEM = ("Segoe UI", 8)           # 检查清单项目
    FONT_ZONE_TITLE = ("Segoe UI", 9, "bold")       # 战区标题
    FONT_ZONE_ITEM = ("Segoe UI", 8)                # 战区项目
    FONT_DEBUG = ("Consolas", 9)                    # 调试信息
    FONT_HINT = ("Segoe UI", 8)                     # 底部提示

    # 内边距定义（水平, 垂直）
    PADDING_MAIN = (14, 10)      # 主容器
    PADDING_ROW2 = (8, 4)        # 第二行（徽章行）
    PADDING_PROGRESS = (4, 6)    # 进度条

    # 间距定义
    SPACING_BADGE = 6            # 徽章间距
    SPACING_DEBUG = 8            # 调试信息间距

    # 窗口定位参数
    WINDOW_MARGIN = 20           # 屏幕边缘留白
    WINDOW_PADDING = 6           # 窗口内部留白

    # 进度条样式
    PROGRESS_BAR_HEIGHT = 6      # 进度条容器高度
    PROGRESS_BAR_THICKNESS = 3   # 进度条实际粗细

    # 调试文本换行宽度
    DEBUG_WRAP_LENGTH = 600


class HotkeyConfig:
    """热键配置

    [快捷键自定义]
    - 支持功能键: F1-F12
    - 默认绑定: F7=重置, F8=锁定, F9=角落, F10=声音, F11=战区
    - 可在设置对话框中自定义
    - 注意: 避免与游戏快捷键冲突(F1-F4通常被游戏占用)
    """
    # 功能键VK码映射表
    VK_CODES = {
        "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
        "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
        "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    }

    # 可用功能键列表（供UI选择）
    AVAILABLE_KEYS = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"]

    # 当前绑定（可运行时修改）
    KEY_RESET = "F7"     # 重置计时器
    KEY_LOCK = "F8"      # 锁定/解锁
    KEY_CORNER = "F9"    # 切换角落
    KEY_BEEP = "F10"     # 声音开关
    KEY_ZONES = "F11"    # 战区提示音

    # 热键ID（用于注册/注销）
    HK_ID_RESET = 7007
    HK_ID_LOCK = 7008
    HK_ID_CORNER = 7009
    HK_ID_BEEP = 7010
    HK_ID_ZONES = 7011

    # 全局热键开关（用户可配置）
    GLOBAL_HOTKEYS = True

    @classmethod
    def get_vk(cls, key_name: str) -> int:
        """获取功能键的VK码"""
        return cls.VK_CODES.get(key_name, 0)

    @classmethod
    def get_bindings(cls) -> dict:
        """获取当前所有绑定"""
        return {
            "reset": cls.KEY_RESET,
            "lock": cls.KEY_LOCK,
            "corner": cls.KEY_CORNER,
            "beep": cls.KEY_BEEP,
            "zones": cls.KEY_ZONES,
        }

    @classmethod
    def set_bindings(cls, bindings: dict) -> None:
        """设置绑定"""
        if "reset" in bindings:
            cls.KEY_RESET = bindings["reset"]
        if "lock" in bindings:
            cls.KEY_LOCK = bindings["lock"]
        if "corner" in bindings:
            cls.KEY_CORNER = bindings["corner"]
        if "beep" in bindings:
            cls.KEY_BEEP = bindings["beep"]
        if "zones" in bindings:
            cls.KEY_ZONES = bindings["zones"]


class SoundConfig:
    """声音配置

    使用Windows Beep API，频率和持续时间定义音效。
    """
    # 音效定义：(频率Hz, 持续时间ms)
    BEEP_TICK = (784, 28)              # 常规提示音
    BEEP_WARNING_1 = (784, 35)         # 警告音1
    BEEP_WARNING_2 = (988, 35)         # 警告音2
    BEEP_MANUAL_RESET = (1000, 80)     # 手动重置
    BEEP_ON_1 = (988, 40)              # 功能开启1
    BEEP_ON_2 = (1319, 70)             # 功能开启2
    BEEP_ZONE_DESTROYED = (440, 100)   # 战区被摧毁

    # 音效间隔
    WARNING_GAP_MS = 20   # 警告双音间隔
    ON_GAP_MS = 25        # 开启双音间隔

    # 警告触发时间点（秒）
    WARNING_SECONDS = [30, 20, 10, 5, 4, 3, 2, 1]
    MAJOR_WARNINGS = [30, 20, 10]  # 重要警告点（双音）


class FileConfig:
    """文件路径配置

    所有配置文件都存储在用户主目录下。
    """
    # 配置文件（JSON格式）
    CONFIG_FILE = Path.home() / ".wttimer_config.json"

    # 状态文件（保存当前计时状态）
    STATE_FILE = Path.home() / ".wttimer_state.json"

    # 图标文件（用于托盘和窗口）
    ICON_FILE = "app.ico"

    # 互斥锁名称（防止多开）
    MUTEX_NAME = r"Global\WTtimer_SingleInstance"

    # 配置文件版本（用于迁移旧配置）
    # v3: 添加编译开关状态记录，解决精简版/完整版配置冲突
    CONFIG_VERSION = 3


# ============================================================================
# 弹道物理计算参数（用于公式校准）
# ============================================================================

class BallisticPhysicsParams:
    """弹道物理计算参数 (CCRP v3.0)

    基于War Thunder大气模型:
    - 空气密度: rho(h) = 1.225 * exp(-h/14426) kg/m^3
    - 标高H = 14426m (源自Wiki "10km约一半密度")
    - 支持地图温度修正(冷图+12%, 热图-6%)
    """

    # ==================== 基础物理常量 ====================
    GRAVITY = 9.8
    AIR_DENSITY_SEA = 1.225
    AIR_DENSITY_SCALE_HEIGHT = 14426.0

    # ==================== 地图温度修正 ====================
    TEMP_REFERENCE_K = 288.15
    MAP_TEMPERATURE_K = 288.0
    USE_TEMPERATURE_CORRECTION = True

    # ==================== 阻力模型配置 ====================
    DRAG_MODEL = "advanced"
    DRAG_COEFFICIENT_MULT = 0.5
    DRAG_REFERENCE_AREA_MULT = 0.8

    # ==================== 减速伞参数 ====================
    BRAKE_DRAG_MULT = 1.0
    BRAKE_DEPLOY_DELAY = 0.5

    # ==================== 数值计算精度 ====================
    TIME_STEP = 0.005
    MAX_FLIGHT_TIME = 120.0
    GROUND_MARGIN = 1.0

    # ==================== 校准修正参数 ====================
    RANGE_CORRECTION_MULT = 1.0
    TIME_CORRECTION_MULT = 1.0
    ALTITUDE_CORRECTION_OFFSET = 0.0

    # ==================== 飞机状态参数 ====================
    USE_AIRCRAFT_VY = True
    DEFAULT_TARGET_ALT = 0.0

    # ==================== 投弹提示配置 ====================
    RELEASE_WARNING_SEC = 5.0
    RELEASE_READY_SEC = 0.5

    # ==================== 用户可调参数（全局） ====================
    _DEFAULT_TUNING = {
        "range_correction_mult": 1.0,
        "time_correction_mult": 1.0,
    }
    _TUNING_LIMITS = {
        "range_correction_mult": (0.6, 1.6),
        "time_correction_mult": (0.6, 1.6),
    }

    @classmethod
    def apply_user_tuning(cls, tuning: dict) -> None:
        """应用用户全局调参（来自配置文件/UI）"""
        if not isinstance(tuning, dict):
            return

        def _clamp(name: str, value: float) -> float:
            low, high = cls._TUNING_LIMITS[name]
            return max(low, min(high, float(value)))

        if "range_correction_mult" in tuning and isinstance(tuning["range_correction_mult"], (int, float)):
            cls.RANGE_CORRECTION_MULT = _clamp("range_correction_mult", tuning["range_correction_mult"])

        if "time_correction_mult" in tuning and isinstance(tuning["time_correction_mult"], (int, float)):
            cls.TIME_CORRECTION_MULT = _clamp("time_correction_mult", tuning["time_correction_mult"])

    @classmethod
    def get_user_tuning(cls) -> dict:
        """获取当前用户调参（用于保存）"""
        return {
            "range_correction_mult": float(cls.RANGE_CORRECTION_MULT),
            "time_correction_mult": float(cls.TIME_CORRECTION_MULT),
        }

    @classmethod
    def get_default_tuning(cls) -> dict:
        """获取默认调参（用于重置）"""
        return dict(cls._DEFAULT_TUNING)


class AboutConfig:
    """关于对话框配置

    注意: APP_NAME, VERSION, AUTHOR, GITHUB_URL 引用自文件头的标准元数据，
    修改版本号请更新 __version__ 变量，无需在此处重复修改。
    """
    # 软件信息 (引用标准元数据，保持单一数据源)
    APP_NAME = __title__
    APP_NAME_CN = "战雷全真模式收益计时器"
    VERSION = __version__
    AUTHOR = __author__
    # 链接配置 (引用标准元数据)
    GITHUB_URL = __repository__

    # 赞助链接配置（可以添加多个）
    SPONSOR_LINKS = [
        # ("显示名称", "链接URL", "图片文件名"),
        ("微信赞赏", "", "sponsor_wechat.png"),  # 空链接表示只显示图片
    ]

    # 赞助图片尺寸
    SPONSOR_IMAGE_WIDTH = 400


class ChecklistConfig:
    """检查清单配置

    用户可以自定义起飞前的检查项目。
    """
    # 最多允许的检查项数量
    MAX_ITEMS = 8

    # 默认检查清单
    DEFAULT_ITEMS = [
        "按I启动发动机",
        "等待发动机转速稳定",
        "收起落架",
        "开增稳系统",
        "Y66或地图设定打击目标",
        "取消武器选择模式",
        "火控系统Y67调节炸弹自动",
        "降落后Y65关闭座舱盖防噪音"
    ]


class BombConfig:
    """投弹预测配置（CCRP v2.0 - 外部参数加载版）

    ╔══════════════════════════════════════════════════════════════════════════╗
    ║ 投弹系统说明 (CCRP v2.0)                                                   ║
    ╠══════════════════════════════════════════════════════════════════════════╣
    ║ 炸弹参数从外部ccrp_bomb_params.json模块加载                                   ║
    ║ 弹道计算参数集中到BallisticPhysicsParams配置块                              ║
    ║ 支持动态切换阻力模型（none/simple/advanced）                                ║
    ╚══════════════════════════════════════════════════════════════════════════╝
    """

    selected_bomb = "su_fab100sv"
    BOMB_DATABASE = {}
    _database_loaded = False

    @classmethod
    def _ensure_database_loaded(cls):
        """确保炸弹数据库已加载"""
        if cls._database_loaded:
            return

        try:
            external_params = None
            json_path = Path(__file__).resolve().parent.parent / "ccrp_bomb_params.json"
            if json_path.exists():
                data = json.loads(json_path.read_text(encoding="utf-8"))
                external_params = data.get("ballistic_params", {})
            else:
                from ccrp_bomb_params import BALLISTIC_PARAMS as external_params

            for bomb_id, params in external_params.items():
                cls.BOMB_DATABASE[bomb_id] = {
                    'mass': params.get('mass', 100.0),
                    'drag_cx': params.get('dragCx', 0.04),
                    'caliber': params.get('caliber', 0.2),
                    'distFromCmToStab': params.get('distFromCmToStab', 0.5),
                    'brakeTime': params.get('brakeTime', [0.0, 0.0]),
                    'brakeCxK': params.get('brakeCxK', 0.0),
                    'brakeArm': params.get('brakeArm', 0.0),
                    'stab_enabled': params.get('stab_enabled', False),
                    'category': cls._infer_category(bomb_id),
                }

            cls._database_loaded = True
            source = "ccrp_bomb_params.json" if json_path.exists() else "ccrp_bomb_params.json"
            print(f"[BombConfig] 已从{source}加载 {len(cls.BOMB_DATABASE)} 种炸弹参数")

        except ImportError as e:
            print(f"[BombConfig] 警告: 无法加载ccrp_bomb_params模块: {e}")
            cls._database_loaded = True
        except Exception as e:
            print(f"[BombConfig] 加载炸弹参数时出错: {e}")
            cls._database_loaded = True

    @classmethod
    def _infer_category(cls, bomb_id: str) -> str:
        """根据炸弹ID推断国家/分类"""
        bomb_id_lower = bomb_id.lower()

        category_prefixes = {
            'us_': '美国', 'su_': '苏联', 'uk_': '英国', 'de_': '德国',
            'jp_': '日本', 'it_': '意大利', 'fr_': '法国', 'cn_': '中国',
            'swd_': '瑞典', 'sws_': '瑞典', 'il_': '以色列',
        }

        for prefix, category in category_prefixes.items():
            if bomb_id_lower.startswith(prefix):
                return category

        if 'fab' in bomb_id_lower or 'ofab' in bomb_id_lower:
            return '苏联'
        if 'mk_' in bomb_id_lower or 'gbu' in bomb_id_lower:
            return '美国'

        return '通用'

    @classmethod
    def get_categories(cls) -> list:
        """获取所有炸弹分类"""
        cls._ensure_database_loaded()
        categories = set(bomb.get("category", "通用") for bomb in cls.BOMB_DATABASE.values())
        priority = ['苏联', '美国', '德国', '英国', '日本', '中国']
        result = [p for p in priority if p in categories]
        result.extend(sorted(categories - set(priority)))
        return result

    @classmethod
    def get_bombs_by_category(cls, category: str) -> list:
        """获取指定分类的所有炸弹"""
        cls._ensure_database_loaded()
        bombs = [name for name, data in cls.BOMB_DATABASE.items() if data.get("category") == category]
        return sorted(bombs, key=lambda x: cls.BOMB_DATABASE[x].get('mass', 0))

    @classmethod
    def get_all_bomb_names(cls) -> list:
        """获取所有炸弹名称"""
        cls._ensure_database_loaded()
        return sorted(list(cls.BOMB_DATABASE.keys()))

    @classmethod
    def get_bomb_data(cls, name: str):
        """获取指定炸弹的数据"""
        cls._ensure_database_loaded()
        return cls.BOMB_DATABASE.get(name)

    @classmethod
    def get_selected_bomb_data(cls) -> dict:
        """获取当前选中炸弹的数据"""
        cls._ensure_database_loaded()
        data = cls.BOMB_DATABASE.get(cls.selected_bomb)
        return data if data else {"mass": 100.0, "drag_cx": 0.04, "caliber": 0.2, "category": "苏联"}

    @classmethod
    def search_bombs(cls, query: str, limit: int = 100) -> list:
        """搜索炸弹"""
        cls._ensure_database_loaded()
        if not query:
            return list(cls.BOMB_DATABASE.keys())[:limit]

        def normalize(s):
            return s.lower().replace('_', '').replace('-', '').replace(' ', '')

        query_norm = normalize(query)
        results = []

        for bomb_id, data in cls.BOMB_DATABASE.items():
            keywords = bomb_id + ' ' + data.get('category', '') + ' ' + str(int(data.get('mass', 0)))
            if query_norm in normalize(keywords) or query.lower() in keywords.lower():
                results.append(bomb_id)
                if len(results) >= limit:
                    break
        return results

    @classmethod
    def format_bomb_name(cls, bomb_id: str) -> str:
        """格式化炸弹名称用于显示"""
        cls._ensure_database_loaded()
        data = cls.get_bomb_data(bomb_id)
        if data is None:
            return bomb_id
        mass = data.get('mass', 0)
        mass_str = f"{mass/1000:.1f}t" if mass >= 1000 else f"{int(mass)}kg"
        name = bomb_id.replace('_', ' ').replace(' default', '')
        return f"{name} ({mass_str})"

    @classmethod
    def get_bomb_physics_params(cls, name: str = None) -> dict:
        """获取炸弹的完整物理参数"""
        cls._ensure_database_loaded()
        data = cls.get_selected_bomb_data() if name is None else (cls.get_bomb_data(name) or {})
        return {
            'mass': data.get('mass', 100.0),
            'caliber': data.get('caliber', 0.2),
            'drag_cx': data.get('drag_cx', 0.04),
            'distFromCmToStab': data.get('distFromCmToStab', 0.5),
            'brakeTime': data.get('brakeTime', [0.0, 0.0]),
            'brakeCxK': data.get('brakeCxK', 0.0),
            'brakeArm': data.get('brakeArm', 0.0),
            'stab_enabled': data.get('stab_enabled', False),
            'reference_area': 3.14159 * (data.get('caliber', 0.2) / 2) ** 2,
        }


class Theme:
    """颜色主题配置

    预设主题: Dark(默认), Light, HighContrast, LunarNewYear

    添加新主题:
    1. 在THEMES字典中添加定义
    2. 确保包含所有必要颜色键
    3. 调用Theme.apply(name)应用

    注意: 主题切换需重启应用生效(tkinter限制)
    """
    # 当前活动主题名称
    _current = "dark"

    # 预设主题定义
    THEMES = {
        "dark": {
            "name": "暗色 (Dark)",
            "BG": "#0a0e13",
            "BORDER": "#30363d",
            "TEXT": "#e6edf3",
            "TEXT_DIM": "#8b949e",
            "TEXT_MUTED": "#484f58",
            "GREEN": "#3fb950",
            "YELLOW": "#d29922",
            "RED": "#f85149",
            "BLUE": "#58a6ff",
            "ORANGE": "#f0883e",
            "GRAYPILL": "#161b22",
            "SEPARATOR": "#21262d",
        },
        "light": {
            "name": "亮色 (Light)",
            "BG": "#ffffff",
            "BORDER": "#d0d7de",
            "TEXT": "#1f2328",
            "TEXT_DIM": "#656d76",
            "TEXT_MUTED": "#8c959f",
            "GREEN": "#1a7f37",
            "YELLOW": "#9a6700",
            "RED": "#cf222e",
            "BLUE": "#0969da",
            "ORANGE": "#bc4c00",
            "GRAYPILL": "#f6f8fa",
            "SEPARATOR": "#d8dee4",
        },
        "high_contrast": {
            "name": "高对比度",
            "BG": "#000000",
            "BORDER": "#ffffff",
            "TEXT": "#ffffff",
            "TEXT_DIM": "#ffff00",
            "TEXT_MUTED": "#808080",
            "GREEN": "#00ff00",
            "YELLOW": "#ffff00",
            "RED": "#ff0000",
            "BLUE": "#00ffff",
            "ORANGE": "#ffa500",
            "GRAYPILL": "#1a1a1a",
            "SEPARATOR": "#404040",
        },
        "lunar_new_year": {
            "name": "农历新年 (Lunar New Year)",
            "BG": "#2a0d0d",
            "BORDER": "#9c4e1d",
            "TEXT": "#fbe7b2",
            "TEXT_DIM": "#e8c47a",
            "TEXT_MUTED": "#a8835c",
            "GREEN": "#8fbf6b",
            "YELLOW": "#e7b75b",
            "RED": "#e14c3a",
            "BLUE": "#5e8f8a",
            "ORANGE": "#c97a33",
            "GRAYPILL": "#4a1a14",
            "SEPARATOR": "#6a2b1a",
        },
    }

    # 默认颜色值（使用暗色主题）
    BG = "#0a0e13"
    BORDER = "#30363d"
    TEXT = "#e6edf3"
    TEXT_DIM = "#8b949e"
    TEXT_MUTED = "#484f58"
    GREEN = "#3fb950"
    YELLOW = "#d29922"
    RED = "#f85149"
    BLUE = "#58a6ff"
    ORANGE = "#f0883e"
    GRAYPILL = "#161b22"
    SEPARATOR = "#21262d"

    @classmethod
    def apply(cls, theme_name: str) -> bool:
        """应用指定主题

        Args:
            theme_name: 主题名称 ("dark", "light", "high_contrast")

        Returns:
            是否成功应用
        """
        if theme_name not in cls.THEMES:
            return False

        theme = cls.THEMES[theme_name]
        cls._current = theme_name

        # 更新类属性
        cls.BG = theme["BG"]
        cls.BORDER = theme["BORDER"]
        cls.TEXT = theme["TEXT"]
        cls.TEXT_DIM = theme["TEXT_DIM"]
        cls.TEXT_MUTED = theme["TEXT_MUTED"]
        cls.GREEN = theme["GREEN"]
        cls.YELLOW = theme["YELLOW"]
        cls.RED = theme["RED"]
        cls.BLUE = theme["BLUE"]
        cls.ORANGE = theme["ORANGE"]
        cls.GRAYPILL = theme["GRAYPILL"]
        cls.SEPARATOR = theme["SEPARATOR"]

        return True

    @classmethod
    def get_current(cls) -> str:
        """获取当前主题名称"""
        return cls._current

    @classmethod
    def get_theme_names(cls) -> list:
        """获取所有主题名称列表"""
        return list(cls.THEMES.keys())

    @classmethod
    def get_theme_display_name(cls, theme_name: str) -> str:
        """获取主题的显示名称"""
        if theme_name in cls.THEMES:
            return cls.THEMES[theme_name]["name"]
        return theme_name


class PanelConfig:
    """面板显示配置

    控制各个信息面板的显示/隐藏状态。
    受编译开关控制：如果编译开关禁用某功能，则对应面板强制隐藏。
    """
    # 默认全部显示
    show_zones = True        # 战区导航
    show_airfields = True    # 机场导航
    show_fuel = True         # 燃油管理
    show_checklist = True    # 检查清单
    show_bombing = True      # v6.0新增：投弹预测（受ENABLE_CCRP开关控制）
    # v6.2.1: 导航条模式 - "integrated"(集成) / "standalone"(独立窗口)
    navigation_mode = "integrated"
    navigation_window_pos = None  # 独立窗口位置 (x, y)
    navigation_bar_width = 1.0    # 独立导航栏宽度倍率（0.5-2.0）

    @classmethod
    def init_from_compile_switches(cls):
        """根据编译开关初始化面板状态

        编译开关优先级高于用户配置：
        如果编译开关禁用某功能，则该面板强制隐藏且用户无法开启
        """
        if not ENABLE_CCRP:
            cls.show_bombing = False
        if not ENABLE_ZONES:
            cls.show_zones = False
        if not ENABLE_AIRFIELDS:
            cls.show_airfields = False
        if not ENABLE_FUEL:
            cls.show_fuel = False
        if not ENABLE_CHECKLIST:
            cls.show_checklist = False

    @classmethod
    def is_feature_enabled(cls, feature: str) -> bool:
        """检查某功能是否被编译开关启用

        用于UI判断是否显示相关设置选项
        """
        feature_map = {
            'zones': ENABLE_ZONES,
            'airfields': ENABLE_AIRFIELDS,
            'fuel': ENABLE_FUEL,
            'checklist': ENABLE_CHECKLIST,
            'bombing': ENABLE_CCRP,
        }
        return feature_map.get(feature, True)


class SnapConfig:
    """窗口吸附配置"""
    # 吸附距离（像素）：窗口边缘距离屏幕边缘小于此值时自动吸附
    SNAP_DISTANCE = 20
    # 是否启用吸附
    enabled = True
