#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.3.1 更新说明:
- 修复：战区列表底部显示不全的问题
- 修复：检查清单文字被截断的问题（减小wraplength）
- 优化：增加两栏模式最小宽度到480*scale
- 优化：窗口高度只在需要时收缩，避免频繁抖动

v5.3 更新说明:
- 修复：切换地图后UI不回缩的问题（mid_frame正确隐藏）
- 修复：起飞检查单显示不全的问题（改用单列布局+文字换行）
- 修复：战区列表显示不全的问题（移除expand=True）
- 优化：窗口尺寸重计算逻辑更可靠

v5.2 更新说明:
- 新增：地速(SOG)计算与预计抵达时间(ETE)显示
- 修复：UI在内容减少时无法自动回缩高度的Bug
- 优化：地速计算采用坐标微分，不受风速影响
"""

import os
import sys
import json
import time
import math
import ctypes
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Tuple, Any, List, Dict
from enum import Enum, auto

import tkinter as tk
from tkinter import messagebox
import requests

# Optional dependencies
try:
    from PIL import Image
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False


# ============================================================================
# 配置类
# ============================================================================

class GameConfig:
    """游戏逻辑相关配置"""
    CYCLE_SECONDS = 15 * 60
    FINAL_WARNING_SEC = 30
    
    LAND_SPEED_KMH = 40
    LAND_CONFIRM_SEC = 3.0
    LANDED_FLASH_SEC = 10.0
    
    SPAWN_CONFIRM_SEC = 1.0
    DEAD_CONFIRM_SEC = 1.2
    HANGAR_CONFIRM_SEC = 1.2
    API_DOWN_CONFIRM_SEC = 5.0
    
    REFIT_FUEL_JUMP_KG = 50.0
    REFIT_MIN_GAP_SEC = 8.0
    REFIT_SPEED_KMH = 12.0
    REFIT_VSPEED_MS = 1.2


class ZoneConfig:
    """战区导航相关配置"""
    HEADING_TOLERANCE = 45
    DEVIATION_WARNING = 60
    DESTROYED_ALERT_SEC = 5.0
    MAX_DISPLAY_ZONES = 6
    DISTANCE_SCALE = 100.0
    MAP_INFO_CACHE_SEC = 30.0


class NetworkConfig:
    """网络请求相关配置"""
    API_BASE = "http://127.0.0.1:8111"
    API_CONNECT_TIMEOUT = 0.08
    API_READ_TIMEOUT = 0.16
    MAX_TICK_NET_BUDGET = 0.30
    BACKOFF_MAX = 1.25
    POLL_INTERVAL = 0.25


class UIConfig:
    """UI界面相关配置"""
    UI_SCALE_MULT = 0.85
    WINDOW_ALPHA = 210
    UI_REFRESH_MS = 50
    
    FONT_TIMER = ("Segoe UI", 44, "bold")
    FONT_LIFE = ("Segoe UI", 13, "bold")
    FONT_CYCLE = ("Segoe UI", 12)
    FONT_PILL = ("Segoe UI", 10, "bold")
    FONT_STATUS = ("Segoe UI", 11)
    FONT_CHECKLIST_TITLE = ("Segoe UI", 9, "bold")
    FONT_CHECKLIST_ITEM = ("Segoe UI", 8)
    FONT_ZONE_TITLE = ("Segoe UI", 9, "bold")
    FONT_ZONE_ITEM = ("Segoe UI", 8)
    FONT_DEBUG = ("Consolas", 9)
    FONT_HINT = ("Segoe UI", 8)
    
    PADDING_MAIN = (14, 10)
    PADDING_ROW2 = (8, 4)
    PADDING_PROGRESS = (4, 6)
    SPACING_BADGE = 6
    SPACING_DEBUG = 8
    
    WINDOW_MARGIN = 20
    WINDOW_PADDING = 6
    PROGRESS_BAR_HEIGHT = 6
    PROGRESS_BAR_THICKNESS = 3
    
    DEBUG_WRAP_LENGTH = 600


class HotkeyConfig:
    """热键配置"""
    VK_F7 = 0x76
    VK_F8 = 0x77
    VK_F9 = 0x78
    VK_F10 = 0x79
    VK_F11 = 0x7A
    
    HK_ID_RESET = 7007
    HK_ID_LOCK = 7008
    HK_ID_CORNER = 7009
    HK_ID_BEEP = 7010
    HK_ID_ZONES = 7011
    
    GLOBAL_HOTKEYS = True


class SoundConfig:
    """声音配置"""
    BEEP_TICK = (784, 28)
    BEEP_WARNING_1 = (784, 35)
    BEEP_WARNING_2 = (988, 35)
    BEEP_MANUAL_RESET = (1000, 80)
    BEEP_ON_1 = (988, 40)
    BEEP_ON_2 = (1319, 70)
    BEEP_ZONE_DESTROYED = (440, 100)
    
    WARNING_GAP_MS = 20
    ON_GAP_MS = 25
    
    WARNING_SECONDS = [30, 20, 10, 5, 4, 3, 2, 1]
    MAJOR_WARNINGS = [30, 20, 10]


class FileConfig:
    """文件路径配置"""
    CONFIG_FILE = Path.home() / ".wttimer_config.json"
    STATE_FILE = Path.home() / ".wttimer_state.json"
    ICON_FILE = "app.png"
    MUTEX_NAME = r"Global\WTtimer_SingleInstance"


class ChecklistConfig:
    """检查清单配置"""
    MAX_ITEMS = 8
    DEFAULT_ITEMS = [
        "收起落架",
        "开增稳系统", 
        "设定打击目标",
        "取消武器选择模式",
        "火控Y67炸弹自动",
        "调整雷达Y11"
    ]


class Theme:
    """颜色主题"""
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


# ============================================================================
# 工具函数和辅助类
# ============================================================================

def resource_path(rel_path: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel_path)


def fmt_time(sec: Optional[float]) -> str:
    if sec is None:
        return "--:--"
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"


class ConfigManager:
    @staticmethod
    def load() -> Dict[str, Any]:
        if FileConfig.CONFIG_FILE.exists():
            try:
                with open(FileConfig.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}
    
    @staticmethod
    def save(config: Dict[str, Any]) -> None:
        try:
            with open(FileConfig.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except IOError:
            pass


class StateManager:
    @staticmethod
    def save(remaining_sec: float, life_index: int, sortie_id: int) -> None:
        state_data = {
            'remaining_sec': remaining_sec,
            'save_timestamp': time.time(),
            'life_index': life_index,
            'sortie_id': sortie_id
        }
        try:
            with open(FileConfig.STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, indent=2)
        except (IOError, OSError):
            pass
    
    @staticmethod
    def load() -> Optional[Dict[str, Any]]:
        if not FileConfig.STATE_FILE.exists():
            return None
        try:
            with open(FileConfig.STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            saved_remaining = data.get('remaining_sec', 0)
            save_time = data.get('save_timestamp', 0)
            
            now = time.time()
            elapsed_since_save = now - save_time
            new_remaining = saved_remaining - elapsed_since_save
            
            if new_remaining < -GameConfig.CYCLE_SECONDS:
                StateManager.clear()
                return None
            
            if new_remaining < 0:
                overshoot = abs(new_remaining)
                new_remaining = GameConfig.CYCLE_SECONDS - overshoot
            
            data['computed_remaining'] = new_remaining
            data['computed_spawn_time'] = now - (GameConfig.CYCLE_SECONDS - new_remaining)
            
            return data
        except (json.JSONDecodeError, IOError, KeyError, OSError):
            StateManager.clear()
            return None
    
    @staticmethod
    def clear() -> None:
        try:
            if FileConfig.STATE_FILE.exists():
                FileConfig.STATE_FILE.unlink()
        except (IOError, OSError):
            pass


# ============================================================================
# Windows API
# ============================================================================

class Win32:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    @classmethod
    def enable_dpi(cls):
        try:
            cls.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (OSError, AttributeError):
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except (OSError, AttributeError):
                try:
                    cls.user32.SetProcessDPIAware()
                except (OSError, AttributeError):
                    pass

    @classmethod
    def get_dpi_scale(cls, hwnd: int) -> float:
        try:
            dpi = cls.user32.GetDpiForWindow(hwnd)
            return (dpi / 96.0) if dpi else 1.0
        except (OSError, AttributeError):
            return 1.0

    @classmethod
    def screen_size(cls) -> Tuple[int, int]:
        return cls.user32.GetSystemMetrics(0), cls.user32.GetSystemMetrics(1)

    @classmethod
    def setup_window(cls, hwnd: int, click_through: bool, alpha: int = 210):
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        LWA_ALPHA = 0x2

        try:
            style = cls.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= (WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)

            if click_through:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT

            cls.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            cls.user32.SetLayeredWindowAttributes(hwnd, 0, int(alpha), LWA_ALPHA)
        except (OSError, AttributeError):
            pass

    @classmethod
    def hide_console(cls):
        try:
            hwnd = cls.kernel32.GetConsoleWindow()
            if hwnd:
                cls.user32.ShowWindow(hwnd, 0)
        except (OSError, AttributeError):
            pass


_MUTEX_HANDLE = None


class SingleInstanceManager:
    @staticmethod
    def ensure_single_instance_or_exit():
        global _MUTEX_HANDLE
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            kernel32.GetLastError.restype = ctypes.c_uint

            h = kernel32.CreateMutexW(None, True, FileConfig.MUTEX_NAME)
            err = kernel32.GetLastError()
            _MUTEX_HANDLE = h

            ERROR_ALREADY_EXISTS = 183
            if not h or err == ERROR_ALREADY_EXISTS:
                try:
                    r = tk.Tk()
                    r.withdraw()
                    messagebox.showinfo("WT Timer", "WT Timer 已在运行（仅允许一个实例）。")
                    r.destroy()
                except tk.TclError:
                    pass
                sys.exit(0)
        except (OSError, AttributeError):
            pass
    
    @staticmethod
    def release():
        global _MUTEX_HANDLE
        if _MUTEX_HANDLE:
            try:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_MUTEX_HANDLE))
            except (OSError, AttributeError):
                pass
            _MUTEX_HANDLE = None


class GlobalHotkeys:
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    MOD_NOREPEAT = 0x4000

    def __init__(self, root: tk.Tk, hotkeys: List[Tuple[int, int, callable]]):
        self.root = root
        self.hotkeys = hotkeys
        self._thread = None
        self._tid = None
        self._stop_event = threading.Event()

    def start(self):
        if not os.name == "nt" or not HotkeyConfig.GLOBAL_HOTKEYS:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if not os.name == "nt" or not self._tid:
            return
        try:
            self._stop_event.set()
            Win32.user32.PostThreadMessageW(int(self._tid), int(self.WM_QUIT), 0, 0)
        except (OSError, AttributeError):
            pass
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self):
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentThreadId.restype = ctypes.c_uint
            self._tid = int(kernel32.GetCurrentThreadId())
        except (OSError, AttributeError):
            self._tid = None
            return

        for hk_id, vk, _cb in self.hotkeys:
            try:
                Win32.user32.RegisterHotKey(None, int(hk_id), int(self.MOD_NOREPEAT), int(vk))
            except (OSError, AttributeError):
                pass

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", ctypes.c_void_p),
                ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_size_t),
                ("time", ctypes.c_uint),
                ("pt", POINT),
            ]

        msg = MSG()
        getmsg = Win32.user32.GetMessageW
        getmsg.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        getmsg.restype = ctypes.c_int

        while not self._stop_event.is_set():
            try:
                r = getmsg(ctypes.byref(msg), None, 0, 0)
                if r == 0:
                    break
                if msg.message == self.WM_HOTKEY:
                    hk_id = int(msg.wParam)
                    for _id, _vk, cb in self.hotkeys:
                        if _id == hk_id:
                            try:
                                self.root.after(0, cb)
                            except tk.TclError:
                                pass
                            break
            except (OSError, AttributeError):
                break

        for hk_id, _vk, _cb in self.hotkeys:
            try:
                Win32.user32.UnregisterHotKey(None, int(hk_id))
            except (OSError, AttributeError):
                pass


# ============================================================================
# 导航数学
# ============================================================================

def calculate_heading_from_vector(dx: float, dy: float) -> Optional[float]:
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    angle = math.degrees(math.atan2(dx, dy))
    return (angle + 360) % 360

def calculate_bearing(x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    angle = math.degrees(math.atan2(dx, dy))
    return (angle + 360) % 360

def calculate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

def normalize_angle(angle: float) -> float:
    while angle > 180:
        angle -= 360
    while angle < -180:
        angle += 360
    return angle

def calculate_relative_bearing(player_heading: float, target_bearing: float) -> float:
    relative = target_bearing - player_heading
    return normalize_angle(relative)

def get_direction_text(relative: float) -> str:
    abs_rel = abs(relative)
    if abs_rel <= 30:
        return "前"
    elif abs_rel >= 150:
        return "后"
    elif relative > 0:
        return "右"
    else:
        return "左"

def normalized_to_grid(x: float, y: float, map_info: Optional[Dict]) -> str:
    if not map_info or not map_info.get('valid'):
        return "?"
    
    try:
        map_min = map_info.get('map_min', [-65536.0, -65536.0])
        map_max = map_info.get('map_max', [65536.0, 65536.0])
        grid_zero = map_info.get('grid_zero', [0.0, 0.0])
        grid_steps = map_info.get('grid_steps', [5500.0, 5500.0])
        grid_size = map_info.get('grid_size', [52719.0, 55385.0])
        
        world_x = map_min[0] + x * (map_max[0] - map_min[0])
        world_y = map_min[1] + y * (map_max[1] - map_min[1])
        
        grid_col = int((world_x - grid_zero[0]) / grid_steps[0])
        grid_row = int((world_y - grid_zero[1]) / grid_steps[1])
        
        num_rows = max(1, int(grid_size[1] / grid_steps[1]))
        
        col_num = grid_col + 1
        row_letter_idx = num_rows - 1 - grid_row
        
        col_num = max(1, col_num)
        row_letter_idx = max(0, row_letter_idx)
        
        row_letter = chr(ord('A') + row_letter_idx)
        
        return f"{row_letter}{col_num}"
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return "?"


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class TelemetryData:
    ind_ok: bool = False
    state_resp_ok: bool = False
    valid: bool = False
    type_name: str = ""
    ias_kmh: float = 0
    vy_ms: float = 0
    fuel_kg: float = 0
    compass: float = 0

    @property
    def entity_like(self) -> bool:
        if not (self.ind_ok and self.state_resp_ok and self.valid and self.type_name):
            return False
        return (self.fuel_kg > 0.1) or (abs(self.ias_kmh) > 0.1) or (abs(self.vy_ms) > 0.1)

    @property
    def is_on_ground(self) -> bool:
        return (self.ias_kmh < GameConfig.LAND_SPEED_KMH and abs(self.vy_ms) < 2.0)


@dataclass
class Zone:
    id: str
    index: int
    x: float
    y: float
    grid: str = "?"
    color: str = ""
    distance: float = 0.0
    bearing: float = 0.0
    relative: float = 0.0
    is_target: bool = False


@dataclass
class MapObjData:
    ok: bool = False
    player_aircraft_present: bool = False
    player_pos: Optional[Tuple[float, float]] = None
    player_dx: float = 0.0
    player_dy: float = 0.0
    obj_count: int = 0
    zones: List[Zone] = field(default_factory=list)


@dataclass
class MapInfo:
    valid: bool = False
    grid_size: List[float] = field(default_factory=lambda: [52719.0, 55385.0])
    grid_steps: List[float] = field(default_factory=lambda: [5500.0, 5500.0])
    grid_zero: List[float] = field(default_factory=lambda: [0.0, 0.0])
    map_min: List[float] = field(default_factory=lambda: [-65536.0, -65536.0])
    map_max: List[float] = field(default_factory=lambda: [65536.0, 65536.0])
    fetch_time: float = 0.0


class Phase(Enum):
    IDLE = auto()
    HANGAR = auto()
    ARMING = auto()
    ALIVE = auto()
    LOSS_PENDING = auto()
    WAIT_NEXT = auto()


@dataclass
class LifeState:
    spawn_time: float
    life_index: int

    def elapsed_seconds(self, now: float) -> float:
        return now - self.spawn_time

    def current_cycle(self, now: float) -> int:
        return int(self.elapsed_seconds(now) // GameConfig.CYCLE_SECONDS) + 1

    def cycle_remaining(self, now: float) -> float:
        elapsed = self.elapsed_seconds(now)
        return GameConfig.CYCLE_SECONDS - (elapsed % GameConfig.CYCLE_SECONDS)

    def cycle_progress(self, now: float) -> float:
        elapsed = self.elapsed_seconds(now)
        return (elapsed % GameConfig.CYCLE_SECONDS) / GameConfig.CYCLE_SECONDS


@dataclass
class ZoneNavigationState:
    zones: List[Zone] = field(default_factory=list)
    target_zone: Optional[Zone] = None
    previous_zone_ids: set = field(default_factory=set)
    destroyed_zones: List[Zone] = field(default_factory=list)
    destroyed_alert_until: float = 0.0
    is_deviating: bool = False
    player_heading: float = 0.0
    # --- V5.2 新增字段 ---
    last_pos: Optional[Tuple[float, float]] = None
    last_pos_ts: float = 0.0
    ground_speed: float = 0.0  # 地速（地图单位/秒）


@dataclass
class GameState:
    phase: Phase = Phase.IDLE
    current_life: Optional[LifeState] = None
    sortie_id: int = 0
    last_refit_ts: float = 0.0
    spawn_candidate_since: Optional[float] = None
    missing_player_since: Optional[float] = None
    landing_start_time: Optional[float] = None
    landed_flash_until: float = 0.0
    hangar_candidate_since: Optional[float] = None
    api_down: bool = False
    api_down_candidate_since: Optional[float] = None
    last_tel: Optional[TelemetryData] = None
    last_map: Optional[MapObjData] = None
    map_info: Optional[MapInfo] = None
    zone_nav: ZoneNavigationState = field(default_factory=ZoneNavigationState)


@dataclass(frozen=True)
class ZoneDisplayInfo:
    id: str
    grid: str
    distance_km: float
    direction: str
    relative: float
    is_target: bool
    ete_str: str = ""  # --- V5.2 新增 ---


@dataclass(frozen=True)
class UISnapshot:
    phase: Phase
    life_index: Optional[int]
    cycle: Optional[int]
    remaining_sec: Optional[float]
    progress: float
    sortie_id: int
    main_badge: Tuple[str, str, str]
    flight_badge: Tuple[str, str, str]
    status_text: str
    diag_text: str
    api_down: bool
    api_down_pending: bool
    on_ground: bool
    landed_flash: bool
    zones: List[ZoneDisplayInfo] = field(default_factory=list)
    has_target: bool = False
    is_deviating: bool = False
    deviation_angle: float = 0.0
    zone_destroyed_alert: bool = False
    destroyed_zone_count: int = 0
    player_heading: float = 0.0


# ============================================================================
# 网络请求
# ============================================================================

class Budget:
    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + max(0.0, seconds)
    def remaining(self) -> float:
        return self.deadline - time.monotonic()


class HttpJson:
    def __init__(self, session: requests.Session):
        self.session = session
    def get_json(self, url: str, budget: Budget) -> Tuple[bool, Optional[Any]]:
        rem = budget.remaining()
        if rem <= 0.0:
            return False, None
        connect_t = min(NetworkConfig.API_CONNECT_TIMEOUT, max(0.01, rem))
        read_t = min(NetworkConfig.API_READ_TIMEOUT, max(0.01, rem))
        try:
            r = self.session.get(url, timeout=(connect_t, read_t))
            if not r.ok:
                return False, None
            return True, r.json()
        except (requests.RequestException, ValueError):
            return False, None


class TelemetryFetcher:
    def __init__(self, http: HttpJson):
        self.http = http
    def fetch(self, budget: Budget) -> TelemetryData:
        data = TelemetryData()
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/indicators", budget)
        data.ind_ok = ok
        if ok and isinstance(j, dict):
            data.valid = bool(j.get("valid", False))
            data.type_name = str(j.get("type", "") or "").strip()
            data.compass = float(j.get("compass1") or j.get("compass") or 0)
        if not data.ind_ok:
            return data
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/state", budget)
        data.state_resp_ok = ok
        if ok and isinstance(j, dict):
            data.ias_kmh = float(j.get("IAS, km/h", 0) or 0)
            data.vy_ms = float(j.get("Vy, m/s", 0) or 0)
            data.fuel_kg = float(j.get("Mfuel, kg", 0) or 0)
        return data


class MapInfoFetcher:
    def __init__(self, http: HttpJson):
        self.http = http
    def fetch(self, budget: Budget) -> Optional[MapInfo]:
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/map_info.json", budget)
        if not ok or not isinstance(j, dict) or not j.get("valid", False):
            return None
        return MapInfo(
            valid=True,
            grid_size=j.get("grid_size", [52719.0, 55385.0]),
            grid_steps=j.get("grid_steps", [5500.0, 5500.0]),
            grid_zero=j.get("grid_zero", [0.0, 0.0]),
            map_min=j.get("map_min", [-65536.0, -65536.0]),
            map_max=j.get("map_max", [65536.0, 65536.0]),
            fetch_time=time.time()
        )


class MapObjectsFetcher:
    def __init__(self, http: HttpJson):
        self.http = http
    def fetch(self, budget: Budget, map_info: Optional[MapInfo] = None) -> MapObjData:
        out = MapObjData()
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/map_obj.json", budget)
        if not ok: return out
        out.ok = True
        objs = j if isinstance(j, list) else j.get("objects", []) if isinstance(j, dict) else []
        out.obj_count = len(objs)
        map_info_dict = None
        if map_info and map_info.valid:
            map_info_dict = {
                'valid': True,
                'grid_size': map_info.grid_size,
                'grid_steps': map_info.grid_steps,
                'grid_zero': map_info.grid_zero,
                'map_min': map_info.map_min,
                'map_max': map_info.map_max
            }
        zone_index = 1
        for o in objs:
            if not isinstance(o, dict): continue
            obj_type = o.get("type", "")
            icon = o.get("icon", "")
            if obj_type == "aircraft" and icon == "Player":
                out.player_aircraft_present = True
                out.player_pos = (o.get("x", 0), o.get("y", 0))
                out.player_dx = float(o.get("dx", 0) or 0)
                out.player_dy = float(o.get("dy", 0) or 0)
            elif obj_type == "bombing_point":
                zone_x = o.get("x", 0)
                zone_y = o.get("y", 0)
                out.zones.append(Zone(
                    id=f"zone_{zone_x:.4f}_{zone_y:.4f}",
                    index=zone_index,
                    x=zone_x, y=zone_y,
                    grid=normalized_to_grid(zone_x, zone_y, map_info_dict),
                    color=o.get("color", "")
                ))
                zone_index += 1
        return out


# ============================================================================
# 游戏逻辑核心
# ============================================================================

class GameLogic:
    def __init__(self):
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.http = HttpJson(self.session)
        self.tel = TelemetryFetcher(self.http)
        self.map_info_fetcher = MapInfoFetcher(self.http)
        self.map = MapObjectsFetcher(self.http)
        self.state = GameState()

    def tick(self) -> None:
        now = time.time()
        budget = Budget(NetworkConfig.MAX_TICK_NET_BUDGET)
        tel = self.tel.fetch(budget)
        
        with self._lock:
            map_info = self.state.map_info
            need_map_info = (map_info is None or not map_info.valid or (now - map_info.fetch_time) > ZoneConfig.MAP_INFO_CACHE_SEC)
        
        if need_map_info and budget.remaining() > 0.05:
            new_map_info = self.map_info_fetcher.fetch(budget)
            if new_map_info:
                with self._lock:
                    self.state.map_info = new_map_info
                    map_info = new_map_info
        
        mp = self.map.fetch(budget, map_info)
        api_up = bool(tel.ind_ok or tel.state_resp_ok or mp.ok)

        with self._lock:
            s = self.state
            prev_tel = s.last_tel
            s.last_tel = tel
            s.last_map = mp

            if api_up:
                s.api_down = False
                s.api_down_candidate_since = None
            else:
                if s.api_down_candidate_since is None:
                    s.api_down_candidate_since = now
                if (now - s.api_down_candidate_since) >= GameConfig.API_DOWN_CONFIRM_SEC:
                    s.api_down = True
            if s.api_down:
                if s.phase != Phase.HANGAR:
                    s.phase = Phase.IDLE
                return

            player_present = bool(mp.ok and mp.player_aircraft_present)
            spawn_candidate = player_present and tel.entity_like

            self._update_zone_navigation_locked(mp, tel, now)

            hangar_like = (not mp.ok) or (mp.obj_count == 0)
            if hangar_like and (not player_present) and s.phase != Phase.ALIVE:
                if s.hangar_candidate_since is None:
                    s.hangar_candidate_since = now
                elif (now - s.hangar_candidate_since) >= GameConfig.HANGAR_CONFIRM_SEC:
                    s.phase = Phase.HANGAR
                    self._reset_life_state_locked()
            else:
                s.hangar_candidate_since = None

            if s.phase == Phase.HANGAR:
                if spawn_candidate:
                    s.phase = Phase.ARMING
                    s.spawn_candidate_since = now
                return

            if s.phase == Phase.IDLE:
                if spawn_candidate:
                    s.phase = Phase.ARMING
                    s.spawn_candidate_since = now

            elif s.phase == Phase.ARMING:
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

                self._update_landing_locked(tel, now)
                
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
                        s.phase = Phase.WAIT_NEXT
                        s.spawn_candidate_since = None

            elif s.phase == Phase.WAIT_NEXT:
                if spawn_candidate:
                    if s.spawn_candidate_since is None:
                        s.spawn_candidate_since = now
                    if (now - s.spawn_candidate_since) >= GameConfig.SPAWN_CONFIRM_SEC:
                        self._start_new_life_locked(now)
                        s.phase = Phase.ALIVE
                        self._clear_transient_state_locked()
                else:
                    s.spawn_candidate_since = None

    def _update_zone_navigation_locked(self, mp: MapObjData, tel: TelemetryData, now: float):
        """核心导航逻辑：更新战区列表与计算地速"""
        nav = self.state.zone_nav
        if not mp.ok or not mp.player_pos:
            nav.zones = []
            nav.target_zone = None
            nav.is_deviating = False
            nav.last_pos = None # Reset
            nav.ground_speed = 0.0
            return
        
        px, py = mp.player_pos
        heading = calculate_heading_from_vector(mp.player_dx, mp.player_dy)
        if heading is None: heading = tel.compass
        nav.player_heading = heading
        
        # === V5.2 新增：地速(SOG) 计算 ===
        # 仅当 IAS > 40km/h 时计算，避免地面静止/滑行时数值乱跳
        if nav.last_pos and tel.ias_kmh > 40:
            dt = now - nav.last_pos_ts
            # 限制计算频率 > 0.4s，防止 dt 过小导致除法震荡
            if dt >= 0.4:
                dx = px - nav.last_pos[0]
                dy = py - nav.last_pos[1]
                # 计算位移（地图坐标单位）
                dist_moved = math.sqrt(dx*dx + dy*dy)
                
                if dist_moved > 0:
                    current_speed = dist_moved / dt
                    
                    # 简单的指数平滑 (EMA) 过滤抖动
                    alpha = 0.2
                    if nav.ground_speed == 0:
                        nav.ground_speed = current_speed
                    else:
                        nav.ground_speed = (nav.ground_speed * (1 - alpha)) + (current_speed * alpha)
                
                nav.last_pos = (px, py)
                nav.last_pos_ts = now
        else:
            # 初始化或速度过低时重置状态
            if not nav.last_pos or (now - nav.last_pos_ts > 2.0):
                nav.last_pos = (px, py)
                nav.last_pos_ts = now
                # 处于地面或极低速，强制归零地速
                if tel.ias_kmh <= 40:
                    nav.ground_speed = 0.0

        # === 战区状态追踪 ===
        current_zone_ids = {z.id for z in mp.zones}
        if nav.previous_zone_ids and current_zone_ids:
            destroyed_ids = nav.previous_zone_ids - current_zone_ids
            if destroyed_ids:
                destroyed = [z for z in nav.zones if z.id in destroyed_ids]
                if destroyed:
                    nav.destroyed_zones = destroyed
                    nav.destroyed_alert_until = now + ZoneConfig.DESTROYED_ALERT_SEC
        nav.previous_zone_ids = current_zone_ids
        
        zones_with_nav = []
        for zone in mp.zones:
            bearing = calculate_bearing(px, py, zone.x, zone.y)
            relative = calculate_relative_bearing(heading, bearing)
            distance = calculate_distance(px, py, zone.x, zone.y)
            zones_with_nav.append(Zone(
                id=zone.id, index=zone.index, x=zone.x, y=zone.y,
                grid=zone.grid, color=zone.color, distance=distance,
                bearing=bearing, relative=relative, is_target=False
            ))
        zones_with_nav.sort(key=lambda z: z.distance)
        
        target = None
        for zone in zones_with_nav:
            if abs(zone.relative) <= ZoneConfig.HEADING_TOLERANCE:
                target = zone
                break
        if not target and zones_with_nav: target = zones_with_nav[0]
        
        if target:
            for i, zone in enumerate(zones_with_nav):
                if zone.id == target.id:
                    zones_with_nav[i] = Zone(
                        id=zone.id, index=zone.index, x=zone.x, y=zone.y,
                        grid=zone.grid, color=zone.color, distance=zone.distance,
                        bearing=zone.bearing, relative=zone.relative, is_target=True
                    )
                    target = zones_with_nav[i]
                    break
        
        nav.zones = zones_with_nav
        nav.target_zone = target
        nav.is_deviating = (abs(target.relative) > ZoneConfig.DEVIATION_WARNING) if target else False

    def manual_reset(self):
        with self._lock:
            if self.state.phase == Phase.ALIVE and self.state.current_life:
                self.state.current_life.spawn_time = time.time()
                self.state.landing_start_time = None
                self.state.landed_flash_until = 0.0

    def save_timer_state(self):
        with self._lock:
            if self.state.phase != Phase.ALIVE or not self.state.current_life:
                StateManager.clear()
                return
            now = time.time()
            remaining = self.state.current_life.cycle_remaining(now)
            StateManager.save(remaining, self.state.current_life.life_index, self.state.sortie_id)

    def restore_timer_state(self) -> bool:
        data = StateManager.load()
        if not data: return False
        with self._lock:
            self.state.current_life = LifeState(
                spawn_time=data['computed_spawn_time'],
                life_index=data.get('life_index', 1)
            )
            self.state.sortie_id = data.get('sortie_id', 0)
            self.state.phase = Phase.ALIVE
            self.state.last_refit_ts = data['computed_spawn_time']
        return True

    def snapshot(self) -> UISnapshot:
        now = time.time()
        with self._lock:
            s = self.state
            tel = s.last_tel or TelemetryData()
            mp = s.last_map or MapObjData()
            life = s.current_life
            remaining = None
            cycle = None
            progress = 0.0
            life_index = life.life_index if life else None

            if s.phase == Phase.ALIVE and life:
                remaining = life.cycle_remaining(now)
                cycle = life.current_cycle(now)
                progress = life.cycle_progress(now)

            api_down_pending = (s.api_down_candidate_since is not None) and (not s.api_down)

            if s.api_down:
                main_badge = ("❌8111不可用", Theme.TEXT, Theme.RED)
                status_text = "未检测到 8111"
            elif api_down_pending:
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

            landed_flash = s.landed_flash_until > now
            on_ground = tel.is_on_ground

            if s.phase != Phase.ALIVE or not life:
                flight_badge = ("—", Theme.TEXT_DIM, Theme.GRAYPILL)
            else:
                if landed_flash:
                    flight_badge = ("就绪✓", Theme.TEXT, Theme.GREEN)
                else:
                    flight_badge = ("着陆中", Theme.TEXT_DIM, Theme.GRAYPILL) if on_ground else ("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL)

            player_present = bool(mp.ok and mp.player_aircraft_present)
            diag_lines = [
                f"MAP: ok={int(mp.ok)} | objs={mp.obj_count} | player={int(player_present)}",
                f"IND: ok={int(tel.ind_ok)} | valid={int(tel.valid)} | type={'✓' if tel.type_name else '✗'}",
                f"STATE: ok={int(tel.state_resp_ok)} | fuel={tel.fuel_kg:.0f}kg | ias={tel.ias_kmh:.0f}km/h"
            ]
            diag = "\n".join(diag_lines)

            nav = s.zone_nav
            zone_display_list = []
            gs = nav.ground_speed

            for zone in nav.zones[:ZoneConfig.MAX_DISPLAY_ZONES]:
                # === V5.2 新增：ETE 计算 ===
                ete_text = ""
                # 只有当它是目标，且地速有效(>微小值)，且距离不是太远时显示
                if zone.is_target and gs > 1e-7:
                    # 时间 = 距离 / 速度 (单位一致，直接除)
                    seconds_left = zone.distance / gs
                    # 上限保护，超过 99 分钟就不显示了
                    if seconds_left < 5999:
                        m, s_time = divmod(int(seconds_left), 60)
                        ete_text = f"{m:02d}:{s_time:02d}"

                zone_display_list.append(ZoneDisplayInfo(
                    id=zone.id, grid=zone.grid, distance_km=zone.distance * ZoneConfig.DISTANCE_SCALE,
                    direction=get_direction_text(zone.relative), relative=zone.relative, is_target=zone.is_target,
                    ete_str=ete_text # 传递 ETE 字符串
                ))
            
            has_target = nav.target_zone is not None
            deviation_angle = nav.target_zone.relative if nav.target_zone else 0.0
            zone_destroyed_alert = nav.destroyed_alert_until > now
            destroyed_count = len(nav.destroyed_zones) if zone_destroyed_alert else 0

            return UISnapshot(
                phase=s.phase, life_index=life_index, cycle=cycle, remaining_sec=remaining,
                progress=progress, sortie_id=s.sortie_id, main_badge=main_badge, flight_badge=flight_badge,
                status_text=status_text, diag_text=diag, api_down=s.api_down, api_down_pending=api_down_pending,
                on_ground=on_ground, landed_flash=landed_flash, zones=zone_display_list, has_target=has_target,
                is_deviating=nav.is_deviating, deviation_angle=deviation_angle, zone_destroyed_alert=zone_destroyed_alert,
                destroyed_zone_count=destroyed_count, player_heading=nav.player_heading,
            )

    def _start_new_life_locked(self, now: float):
        s = self.state
        next_index = 1 if not s.current_life else (s.current_life.life_index + 1)
        s.current_life = LifeState(spawn_time=now, life_index=next_index)
        s.sortie_id += 1
        s.last_refit_ts = now

    def _reset_life_state_locked(self):
        s = self.state
        s.current_life = None
        s.sortie_id = 0
        s.last_refit_ts = 0.0
        s.spawn_candidate_since = None
        s.missing_player_since = None
        s.landing_start_time = None
        s.landed_flash_until = 0.0
        s.zone_nav = ZoneNavigationState()
        s.map_info = None

    def _clear_transient_state_locked(self):
        s = self.state
        s.spawn_candidate_since = None
        s.missing_player_since = None
        s.landing_start_time = None
        s.landed_flash_until = 0.0

    def _update_landing_locked(self, tel: TelemetryData, now: float):
        s = self.state
        if not s.current_life: return
        if tel.is_on_ground:
            if s.landing_start_time is None:
                s.landing_start_time = now
            elif (now - s.landing_start_time) >= GameConfig.LAND_CONFIRM_SEC:
                if s.landed_flash_until <= now:
                    s.landed_flash_until = now + GameConfig.LANDED_FLASH_SEC
        else:
            s.landing_start_time = None


# ============================================================================
# UI组件
# ============================================================================

class Corner(Enum):
    TOP_RIGHT = 0
    TOP_LEFT = 1
    BOTTOM_RIGHT = 2
    BOTTOM_LEFT = 3


class Pill(tk.Label):
    def __init__(self, parent, text="", fg=Theme.TEXT, bg=Theme.GRAYPILL, font=None):
        super().__init__(parent, text=text, fg=fg, bg=bg, bd=0, highlightthickness=0)
        if font: self.configure(font=font)
        self._apply_padding(text)
    def _apply_padding(self, text: str):
        self.configure(text=f"  {text}  ")
    def set(self, text: str, fg: str, bg: str):
        self.configure(fg=fg, bg=bg)
        self._apply_padding(text)


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("设置")
        self.resizable(False, False)
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._center_on_parent(parent)
    def _build_ui(self):
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=20, pady=15)
        tk.Label(main, text="窗口透明度:", bg=Theme.BG, fg=Theme.TEXT).grid(row=0, column=0, sticky="w", pady=5)
        self.alpha_var = tk.IntVar(value=UIConfig.WINDOW_ALPHA)
        tk.Scale(main, from_=100, to=255, orient="horizontal", variable=self.alpha_var, length=200, bg=Theme.BG, fg=Theme.TEXT, highlightthickness=0, troughcolor=Theme.BORDER, activebackground=Theme.BLUE).grid(row=0, column=1, padx=10, pady=5)
        tk.Label(main, text="UI缩放:", bg=Theme.BG, fg=Theme.TEXT).grid(row=1, column=0, sticky="w", pady=5)
        self.scale_var = tk.DoubleVar(value=UIConfig.UI_SCALE_MULT)
        tk.Scale(main, from_=0.6, to=1.2, resolution=0.05, orient="horizontal", variable=self.scale_var, length=200, bg=Theme.BG, fg=Theme.TEXT, highlightthickness=0, troughcolor=Theme.BORDER, activebackground=Theme.BLUE).grid(row=1, column=1, padx=10, pady=5)
        tk.Label(main, text="全局热键:", bg=Theme.BG, fg=Theme.TEXT).grid(row=2, column=0, sticky="w", pady=5)
        self.hotkeys_var = tk.BooleanVar(value=HotkeyConfig.GLOBAL_HOTKEYS)
        tk.Checkbutton(main, text="启用", variable=self.hotkeys_var, bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL, activebackground=Theme.BG, activeforeground=Theme.TEXT, highlightthickness=0).grid(row=2, column=1, sticky="w", padx=10, pady=5)
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(15, 0))
        tk.Button(btn_frame, text="保存", command=self._save, bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=self.destroy, bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
    def _center_on_parent(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    def _save(self):
        UIConfig.WINDOW_ALPHA = self.alpha_var.get()
        UIConfig.UI_SCALE_MULT = self.scale_var.get()
        old_hotkeys = HotkeyConfig.GLOBAL_HOTKEYS
        HotkeyConfig.GLOBAL_HOTKEYS = self.hotkeys_var.get()
        config = ConfigManager.load()
        config['alpha'] = UIConfig.WINDOW_ALPHA
        config['scale'] = UIConfig.UI_SCALE_MULT
        config['global_hotkeys'] = HotkeyConfig.GLOBAL_HOTKEYS
        ConfigManager.save(config)
        Win32.setup_window(self.app.hwnd, self.app._locked, UIConfig.WINDOW_ALPHA)
        if old_hotkeys != HotkeyConfig.GLOBAL_HOTKEYS:
            if hasattr(self.app, '_ghk') and self.app._ghk: self.app._ghk.stop()
            if HotkeyConfig.GLOBAL_HOTKEYS:
                self.app._init_global_hotkeys()
                if hasattr(self.app, '_ghk') and self.app._ghk: self.app._ghk.start()
        messagebox.showinfo("设置", "设置已保存\n部分更改需要重启生效", parent=self)
        self.destroy()


class ChecklistEditor(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("编辑检查清单")
        self.resizable(False, False)
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._center_on_parent(parent)
    def _build_ui(self):
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=20, pady=15, fill="both", expand=True)
        tk.Label(main, text=f"每行一个检查项（最多{ChecklistConfig.MAX_ITEMS}项）:", bg=Theme.BG, fg=Theme.TEXT, anchor="w").pack(fill="x", pady=(0, 5))
        self.text = tk.Text(main, width=40, height=10, bg=Theme.GRAYPILL, fg=Theme.TEXT, insertbackground=Theme.TEXT, bd=0, highlightthickness=1, highlightbackground=Theme.BORDER)
        self.text.pack(fill="both", expand=True)
        current_items = "\n".join(self.app.chk_items)
        self.text.insert("1.0", current_items)
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(pady=(10, 0))
        tk.Button(btn_frame, text="保存", command=self._save, bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
        tk.Button(btn_frame, text="恢复默认", command=self._restore_default, bg=Theme.YELLOW, fg=Theme.TEXT, bd=0, padx=15, pady=5).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=self.destroy, bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
    def _center_on_parent(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    def _save(self):
        content = self.text.get("1.0", "end-1c")
        items = [line.strip() for line in content.split("\n") if line.strip()]
        if not items:
            messagebox.showwarning("警告", "检查清单不能为空", parent=self)
            return
        if len(items) > ChecklistConfig.MAX_ITEMS:
            messagebox.showwarning("警告", f"检查项数量不能超过{ChecklistConfig.MAX_ITEMS}个", parent=self)
            return
        config = ConfigManager.load()
        config['checklist_items'] = items
        ConfigManager.save(config)
        self.app.chk_items = items
        self.app._rebuild_checklist()
        messagebox.showinfo("成功", "检查清单已保存", parent=self)
        self.destroy()
    def _restore_default(self):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(ChecklistConfig.DEFAULT_ITEMS))


# ============================================================================
# 音效管理
# ============================================================================

class SoundManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = False
    def set_enabled(self, enabled: bool):
        self._enabled = enabled
    def is_enabled(self) -> bool:
        return self._enabled
    def play(self, pattern: str = "tick", freq: int = None, duration: int = None):
        if not self._enabled and pattern != "on": return
        if not self._lock.acquire(blocking=False): return
        try:
            if freq is not None and duration is not None:
                def _play_single():
                    try: ctypes.windll.kernel32.Beep(int(freq), int(duration))
                    except: pass
                    finally: self._lock.release()
                threading.Thread(target=_play_single, daemon=True).start()
                return
            seq = self._get_pattern_sequence(pattern)
            def _play():
                try:
                    for (f, ms, gap) in seq:
                        try: ctypes.windll.kernel32.Beep(int(f), int(ms))
                        except: pass
                        if gap: time.sleep(gap / 1000.0)
                finally: self._lock.release()
            threading.Thread(target=_play, daemon=True).start()
        except Exception:
            self._lock.release()
            raise
    @staticmethod
    def _get_pattern_sequence(pattern: str) -> List[Tuple[int, int, int]]:
        if pattern == "on": return [(*SoundConfig.BEEP_ON_1, SoundConfig.ON_GAP_MS), (*SoundConfig.BEEP_ON_2, 0)]
        elif pattern == "warning": return [(*SoundConfig.BEEP_WARNING_1, SoundConfig.WARNING_GAP_MS), (*SoundConfig.BEEP_WARNING_2, 0)]
        elif pattern == "zone_destroyed": return [(*SoundConfig.BEEP_ZONE_DESTROYED, 50), (*SoundConfig.BEEP_ZONE_DESTROYED, 0)]
        else: return [(*SoundConfig.BEEP_TICK, 0)]


# ============================================================================
# 主应用
# ============================================================================

class App:
    """主应用程序"""
    def __init__(self, root: tk.Tk):
        self.root = root
        self.game = GameLogic()
        self.sound = SoundManager()
        self._stop = False
        self._corner = Corner.TOP_RIGHT
        self._locked = True
        self._debug = False
        self._last_beep_sec = -1
        self._zone_sound_enabled = True

        self._user_moved = False
        self._manual_pos = None
        self._last_sortie_id = -1
        self._restored_state = False
        self._last_zone_destroyed_alert = False
        
        # 布局可见性状态
        self._zone_panel_visible = False
        self._checklist_panel_visible = False

        self._load_config()

        self._init_window_base()
        self._init_ui()
        self._finalize_window_geometry_and_styles()
        self._init_bindings()
        self._init_global_hotkeys()

        self._restored_state = self.game.restore_timer_state()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._update_ui()

        if HAS_TRAY: self._init_tray()

    def _load_config(self):
        config = ConfigManager.load()
        UIConfig.WINDOW_ALPHA = config.get('alpha', UIConfig.WINDOW_ALPHA)
        UIConfig.UI_SCALE_MULT = config.get('scale', UIConfig.UI_SCALE_MULT)
        HotkeyConfig.GLOBAL_HOTKEYS = config.get('global_hotkeys', HotkeyConfig.GLOBAL_HOTKEYS)
        self.chk_items = config.get('checklist_items', ChecklistConfig.DEFAULT_ITEMS.copy())
        self._zone_sound_enabled = config.get('zone_sound_enabled', True)
        saved_pos = config.get('window_position')
        if saved_pos and isinstance(saved_pos, dict):
            corner_name = saved_pos.get('corner')
            if corner_name:
                try: self._corner = Corner[corner_name]
                except KeyError: pass
            manual_pos = saved_pos.get('manual_pos')
            if manual_pos and isinstance(manual_pos, list) and len(manual_pos) == 2:
                self._manual_pos = tuple(manual_pos)
                self._user_moved = saved_pos.get('user_moved', False)
        beep_enabled = config.get('beep_enabled', False)
        self.sound.set_enabled(beep_enabled)

    def _save_config(self):
        config = ConfigManager.load()
        config['alpha'] = UIConfig.WINDOW_ALPHA
        config['scale'] = UIConfig.UI_SCALE_MULT
        config['global_hotkeys'] = HotkeyConfig.GLOBAL_HOTKEYS
        config['checklist_items'] = self.chk_items
        config['beep_enabled'] = self.sound.is_enabled()
        config['zone_sound_enabled'] = self._zone_sound_enabled
        config['window_position'] = {
            'corner': self._corner.name,
            'manual_pos': list(self._manual_pos) if self._manual_pos else None,
            'user_moved': self._user_moved
        }
        ConfigManager.save(config)

    def _init_window_base(self):
        self.root.title("WT Timer")
        try:
            p = resource_path(FileConfig.ICON_FILE)
            self._tk_icon = tk.PhotoImage(file=p)
            self.root.iconphoto(True, self._tk_icon)
        except (tk.TclError, FileNotFoundError): pass
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=Theme.BG)
        self.root.geometry("10x10+0+0")
        self.root.update_idletasks()
        self.hwnd = int(self.root.winfo_id())
        self.scale = Win32.get_dpi_scale(self.hwnd) * float(UIConfig.UI_SCALE_MULT)
        try: self.root.tk.call("tk", "scaling", float(self.scale))
        except tk.TclError: pass

    def _finalize_window_geometry_and_styles(self):
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        pad = int(UIConfig.WINDOW_PADDING * self.scale)
        self.W = req_w + pad
        self.H = req_h + pad
        self._position()
        self.root.update_idletasks()
        Win32.setup_window(self.hwnd, click_through=True, alpha=UIConfig.WINDOW_ALPHA)

    def _init_ui(self):
        s = self.scale
        self.main_frame = tk.Frame(self.root, bg=Theme.BG)
        pad_x, pad_y = UIConfig.PADDING_MAIN
        self.main_frame.pack(fill="both", expand=True, padx=int(pad_x*s), pady=int(pad_y*s))

        # === 底部区域 (Hint/Debug) ===
        bottom_frame = tk.Frame(self.main_frame, bg=Theme.BG)
        bottom_frame.pack(side="bottom", fill="x")

        font_hint = (UIConfig.FONT_HINT[0], int(UIConfig.FONT_HINT[1]*s))
        self.hint_lbl = tk.Label(
            bottom_frame, text=self._hint_text(),
            font=font_hint, fg=Theme.TEXT_MUTED, bg=Theme.BG
        )
        self.hint_lbl.pack(side="bottom", fill="x")

        font_debug = (UIConfig.FONT_DEBUG[0], int(UIConfig.FONT_DEBUG[1]*s))
        self.diag_lbl = tk.Label(
            bottom_frame, text="",
            font=font_debug, fg=Theme.TEXT_MUTED, bg=Theme.BG, 
            anchor="w", justify="left",
            wraplength=int(UIConfig.DEBUG_WRAP_LENGTH*s)
        )

        # === 顶部区域 (Timer, Badges, Progress) ===
        self.top_frame = tk.Frame(self.main_frame, bg=Theme.BG)
        self.top_frame.pack(side="top", fill="x")

        # 第一行：计时器
        row1 = tk.Frame(self.top_frame, bg=Theme.BG)
        row1.pack(fill="x")
        font_timer = (UIConfig.FONT_TIMER[0], int(UIConfig.FONT_TIMER[1]*s), UIConfig.FONT_TIMER[2])
        self.timer_lbl = tk.Label(row1, text="--:--", font=font_timer, fg=Theme.TEXT_MUTED, bg=Theme.BG, anchor="w")
        self.timer_lbl.pack(side="left")
        
        right = tk.Frame(row1, bg=Theme.BG)
        right.pack(side="right", padx=(int(14*s), 0))
        font_life = (UIConfig.FONT_LIFE[0], int(UIConfig.FONT_LIFE[1]*s), UIConfig.FONT_LIFE[2])
        self.life_lbl = tk.Label(right, text="未复活", font=font_life, fg=Theme.BLUE, bg=Theme.BG, anchor="e")
        self.life_lbl.pack(anchor="e")
        font_cycle = (UIConfig.FONT_CYCLE[0], int(UIConfig.FONT_CYCLE[1]*s))
        self.cycle_lbl = tk.Label(right, text="未开始", font=font_cycle, fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="e")
        self.cycle_lbl.pack(anchor="e", pady=(int(2*s), 0))

        # 第二行：徽章
        row2 = tk.Frame(self.top_frame, bg=Theme.BG)
        pad_top, pad_bot = UIConfig.PADDING_ROW2
        row2.pack(fill="x", pady=(int(pad_top*s), int(pad_bot*s)))
        pill_font = (UIConfig.FONT_PILL[0], int(UIConfig.FONT_PILL[1]*s), UIConfig.FONT_PILL[2])
        self.badge_main = Pill(row2, text="IDLE", fg=Theme.TEXT, bg=Theme.GRAYPILL, font=pill_font)
        self.badge_main.pack(side="left")
        self.badge_flight = Pill(row2, text="—", fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, font=pill_font)
        self.badge_flight.pack(side="left", padx=(int(UIConfig.SPACING_BADGE*s), 0))
        font_status = (UIConfig.FONT_STATUS[0], int(UIConfig.FONT_STATUS[1]*s))
        self.status_txt = tk.Label(row2, text="等待中", font=font_status, fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="e")
        self.status_txt.pack(side="right")

        # 进度条
        bar_height = int(UIConfig.PROGRESS_BAR_HEIGHT * s)
        bar_frame = tk.Frame(self.top_frame, bg=Theme.BG, height=bar_height)
        pad_top, pad_bot = UIConfig.PADDING_PROGRESS
        bar_frame.pack(fill="x", pady=(int(pad_top*s), int(pad_bot*s)))
        bar_frame.pack_propagate(False)
        bar_thickness = int(UIConfig.PROGRESS_BAR_THICKNESS * s)
        self.bar_bg = tk.Frame(bar_frame, bg=Theme.BORDER, height=bar_thickness)
        self.bar_bg.place(relx=0, rely=0.5, relwidth=1, anchor="w")
        self.bar_fill = tk.Frame(self.bar_bg, bg=Theme.BLUE, height=bar_thickness)
        self.bar_fill.place(relx=0, rely=0, relwidth=0, relheight=1)

        # === 中间内容区域 ===
        self.mid_frame = tk.Frame(self.main_frame, bg=Theme.BG)
        # 注意：不使用 expand=True，让内容决定高度，这样隐藏面板时UI能正确收缩
        self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*s)))
        self.mid_frame.columnconfigure(0, weight=1)
        self.mid_frame.columnconfigure(1, weight=1)

        # 战区导航框架
        self.zone_frame = tk.Frame(self.mid_frame, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        self._init_zone_ui()

        # 检查清单框架
        self.chk_frame = tk.Frame(self.mid_frame, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        self.chk_border_frame = tk.Frame(self.chk_frame, bg=Theme.SEPARATOR, width=1)
        self.chk_content_frame = tk.Frame(self.chk_frame, bg=Theme.GRAYPILL)
        
        self.chk_vars: List[tk.BooleanVar] = []
        self._rebuild_checklist()

    def _init_zone_ui(self):
        s = self.scale
        title_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        title_frame.pack(fill="x", padx=int(8*s), pady=(int(6*s), int(2*s)))
        
        font_title = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2])
        self.zone_title = tk.Label(title_frame, text="🎯 战区导航", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.zone_title.pack(side="left")
        
        font_heading = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        self.heading_lbl = tk.Label(title_frame, text="HDG: ---", font=font_heading, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="e")
        self.heading_lbl.pack(side="right")
        
        font_alert = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2])
        self.zone_alert_lbl = tk.Label(self.zone_frame, text="", font=font_alert, fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w")
        
        # 不使用 expand=True，让内容决定高度，避免显示不全
        self.zone_list_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.zone_list_frame.pack(fill="x", padx=int(8*s), pady=(0, int(10*s)))  # 增加底部padding
        self.zone_labels: List[tk.Label] = []

    def _rebuild_checklist(self):
        for widget in self.chk_content_frame.winfo_children(): widget.destroy()
        self.chk_vars.clear()
        s = self.scale
        
        self.chk_border_frame.pack(side="left", fill="y", padx=(0, 2))
        self.chk_content_frame.pack(side="left", fill="both", expand=True)

        font_title = (UIConfig.FONT_CHECKLIST_TITLE[0], int(UIConfig.FONT_CHECKLIST_TITLE[1]*s), UIConfig.FONT_CHECKLIST_TITLE[2])
        self.chk_title = tk.Label(self.chk_content_frame, text="✅ 出击检查", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.chk_title.pack(fill="x", padx=int(6*s), pady=(int(6*s), int(2*s)))

        font_item = (UIConfig.FONT_CHECKLIST_ITEM[0], int(UIConfig.FONT_CHECKLIST_ITEM[1]*s))
        pad_x = int(6*s)
        # 使用 pack 单列布局，确保所有项目都能显示
        # wraplength 设为较小值，确保在两栏模式下也能正确换行
        wrap_width = int(140*s)
        for i, item in enumerate(self.chk_items):
            var = tk.BooleanVar(value=False)
            self.chk_vars.append(var)
            cb = tk.Checkbutton(
                self.chk_content_frame, text=item, variable=var, onvalue=True, offvalue=False,
                font=font_item, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, activebackground=Theme.GRAYPILL,
                activeforeground=Theme.TEXT, selectcolor=Theme.BG, anchor="w", bd=0, highlightthickness=0,
                padx=0, pady=1, wraplength=wrap_width
            )
            cb.pack(fill="x", padx=(pad_x, pad_x), pady=0, anchor="w")

    def _init_bindings(self):
        self.root.bind("<Escape>", lambda e: self._quit())
        self.root.bind("<F7>", lambda e: self._manual_reset())
        self.root.bind("<F8>", lambda e: self._toggle_lock())
        self.root.bind("<F9>", lambda e: self._next_corner())
        self.root.bind("<F10>", lambda e: self._toggle_beep())
        self.root.bind("<F11>", lambda e: self._toggle_zone_sound())
        self.root.bind("<Control-MouseWheel>", self._adjust_alpha)
        self._drag = {"x": 0, "y": 0}
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)
        self.root.bind("<Button-3>", self._show_context_menu)
        self.context_menu = tk.Menu(self.root, tearoff=0, bg=Theme.GRAYPILL, fg=Theme.TEXT)
        self.context_menu.add_command(label="🔄 重置计时器 (F7)", command=self._manual_reset)
        self.context_menu.add_command(label="🔓 锁定/解锁 (F8)", command=self._toggle_lock)
        self.context_menu.add_command(label="📍 切换角落 (F9)", command=self._next_corner)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🔔 战区提示音 (F11)", command=self._toggle_zone_sound)
        self.context_menu.add_command(label="📝 编辑检查清单", command=self._edit_checklist)
        self.context_menu.add_command(label="⚙️ 设置", command=self._show_settings)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❌ 退出", command=self._quit)

    def _init_global_hotkeys(self):
        self._ghk = None
        if not os.name == "nt" or not HotkeyConfig.GLOBAL_HOTKEYS: return
        hotkeys = [
            (HotkeyConfig.HK_ID_RESET, HotkeyConfig.VK_F7, self._manual_reset),
            (HotkeyConfig.HK_ID_LOCK, HotkeyConfig.VK_F8, self._toggle_lock),
            (HotkeyConfig.HK_ID_CORNER, HotkeyConfig.VK_F9, self._next_corner),
            (HotkeyConfig.HK_ID_BEEP, HotkeyConfig.VK_F10, self._toggle_beep),
            (HotkeyConfig.HK_ID_ZONES, HotkeyConfig.VK_F11, self._toggle_zone_sound),
        ]
        self._ghk = GlobalHotkeys(self.root, hotkeys)
        self._ghk.start()

    def _init_tray(self):
        def icon():
            try: return Image.open(resource_path(FileConfig.ICON_FILE)).convert("RGBA")
            except: return Image.new('RGBA', (64, 64), Theme.BLUE)
        def toggle_debug(icon, item): self.root.after(0, self._toggle_debug)
        def is_debug_checked(item): return self._debug
        menu = pystray.Menu(
            pystray.MenuItem("Debug模式", toggle_debug, checked=is_debug_checked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("显示", lambda: self.root.after(0, self._show)),
            pystray.MenuItem("退出", lambda: self.root.after(0, self._quit)),
        )
        self.tray = pystray.Icon("WTTimer", icon(), "WT Timer", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _toggle_debug(self):
        self._debug = not self._debug
        if self._debug:
            self.diag_lbl.pack(side="bottom", fill="x", pady=(0, int(UIConfig.SPACING_DEBUG*self.scale)), before=self.hint_lbl)
        else:
            self.diag_lbl.pack_forget()
        self._recalc_size()

    def _toggle_zone_sound(self):
        self._zone_sound_enabled = not self._zone_sound_enabled
        self._update_hint()
        self._save_config()
        if self._zone_sound_enabled: self.sound.play(pattern="on")

    def _recalc_size(self, keep_pos: bool = True, force_shrink: bool = False):
        """修复版：正确计算窗口尺寸，确保内容完全显示"""
        try:
            old_x = self.root.winfo_x()
            old_y = self.root.winfo_y()
            old_w = self.root.winfo_width()
            old_h = self.root.winfo_height()
        except tk.TclError:
            old_x, old_y, old_w, old_h = 0, 0, 0, 0
        
        # 1. 强制刷新布局，确保所有组件都正确计算尺寸
        self.root.update_idletasks()
        
        # 2. 读取内部容器的请求尺寸（这是组件需要的实际尺寸）
        req_w = self.main_frame.winfo_reqwidth()
        req_h = self.main_frame.winfo_reqheight()
        
        pad = int(UIConfig.WINDOW_PADDING * self.scale)
        
        # 3. 根据面板可见性设置最小宽度
        if self._zone_panel_visible and self._checklist_panel_visible:
            min_width = int(480 * self.scale)  # 两栏并排时需要更大宽度
        else:
            min_width = int(280 * self.scale)
        
        new_w = max(min_width, req_w + pad)
        new_h = req_h + pad + int(8 * self.scale)  # 额外padding防止底部裁剪
        
        # 4. 高度策略：
        # - 如果新高度 > 旧高度：总是扩展（确保内容显示完全）
        # - 如果新高度 < 旧高度：只有当面板隐藏(force_shrink)或差距很大(>30)时才收缩
        if new_h < old_h:
            if not force_shrink and (old_h - new_h) < 30:
                new_h = old_h  # 保持原有高度
        
        if new_w == old_w and new_h == old_h:
            return  # 尺寸完全相同，无需更新
        
        self.W = new_w
        self.H = new_h

        if keep_pos:
            if self._user_moved and self._manual_pos:
                x, y = self._manual_pos
            elif (old_x, old_y) != (0, 0):
                x, y = old_x, old_y
            else:
                self._position()
                return
            self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        else:
            self._position()

    def _show(self):
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError: pass

    def _position(self):
        sw, sh = Win32.screen_size()
        m = int(UIConfig.WINDOW_MARGIN * self.scale)
        pos = {
            Corner.TOP_RIGHT: (sw - self.W - m, m),
            Corner.TOP_LEFT: (m, m),
            Corner.BOTTOM_RIGHT: (sw - self.W - m, sh - self.H - m),
            Corner.BOTTOM_LEFT: (m, sh - self.H - m),
        }
        if self._user_moved and self._manual_pos: x, y = self._manual_pos
        else: x, y = pos[self._corner]
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _toggle_lock(self):
        self._locked = not self._locked
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=UIConfig.WINDOW_ALPHA)
        self._update_hint()

    def _hint_text(self) -> str:
        sound = "🔊开" if self.sound.is_enabled() else "🔇关"
        zone_sound = "🔔开" if self._zone_sound_enabled else "🔕关"
        if self._locked: return f"F7重置 │ F8解锁 │ F9角落 │ F10声音({sound}) │ F11战区({zone_sound})"
        else: return f"拖动移动 │ F8锁定 │ F10声音({sound}) │ F11战区({zone_sound}) │ 右键菜单"

    def _update_hint(self) -> None:
        if hasattr(self, "hint_lbl") and self.hint_lbl: self.hint_lbl.config(text=self._hint_text())

    def _next_corner(self):
        corners = list(Corner)
        i = (corners.index(self._corner) + 1) % len(corners)
        self._corner = corners[i]
        self._user_moved = False
        self._manual_pos = None
        self._position()
        self._save_config()

    def _toggle_beep(self):
        enabled = not self.sound.is_enabled()
        self.sound.set_enabled(enabled)
        self._update_hint()
        self._save_config()
        if enabled: self.sound.play(pattern="on")

    def _manual_reset(self):
        self.game.manual_reset()
        self.sound.play(*SoundConfig.BEEP_MANUAL_RESET)

    def _show_settings(self):
        if not self._locked: SettingsDialog(self.root, self)

    def _edit_checklist(self):
        if not self._locked: ChecklistEditor(self.root, self)

    def _show_context_menu(self, event):
        if not self._locked:
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

    def _adjust_alpha(self, event):
        if not self._locked:
            delta = 10 if event.delta > 0 else -10
            UIConfig.WINDOW_ALPHA = max(100, min(255, UIConfig.WINDOW_ALPHA + delta))
            Win32.setup_window(self.hwnd, click_through=False, alpha=UIConfig.WINDOW_ALPHA)
            self._save_config()

    def _quit(self):
        self._stop = True
        self.game.save_timer_state()
        self._save_config()
        try:
            if getattr(self, "_ghk", None): self._ghk.stop()
        except: pass
        if HAS_TRAY and hasattr(self, "tray"):
            try: self.tray.stop()
            except: pass
        SingleInstanceManager.release()
        self.root.destroy()

    def _start_drag(self, e):
        if self._locked: return
        self._drag["x"] = e.x
        self._drag["y"] = e.y

    def _do_drag(self, e):
        if self._locked: return
        x = self.root.winfo_pointerx() - self._drag["x"]
        y = self.root.winfo_pointery() - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, e=None):
        if self._locked: return
        try:
            self._manual_pos = (int(self.root.winfo_x()), int(self.root.winfo_y()))
            self._user_moved = True
            self._save_config()
        except tk.TclError: pass

    def _poll_loop(self):
        while not self._stop:
            loop_start = time.monotonic()
            self.game.tick()
            snap = self.game.snapshot()
            interval = NetworkConfig.BACKOFF_MAX if snap.api_down else NetworkConfig.POLL_INTERVAL
            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.0, interval - elapsed))

    def _reset_checklist(self):
        for v in self.chk_vars: v.set(False)

    def _update_mid_panel_layout(self):
        self.zone_frame.grid_forget()
        self.chk_frame.grid_forget()
        
        # 配置 mid_frame 的行列权重，让内容能正确扩展
        self.mid_frame.rowconfigure(0, weight=1)
        
        if self._zone_panel_visible and self._checklist_panel_visible:
            # 确保 mid_frame 可见
            if not self.mid_frame.winfo_ismapped():
                self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*self.scale)), after=self.top_frame)
            # 使用 sticky="new" 让内容从顶部开始，宽度填满，高度由内容决定
            self.zone_frame.grid(row=0, column=0, sticky="new", padx=(0, int(2*self.scale)))
            self.chk_frame.grid(row=0, column=1, sticky="new", padx=(int(2*self.scale), 0))
            if not self.chk_border_frame.winfo_ismapped():
                self.chk_border_frame.pack(side="left", fill="y", padx=(0, 2), before=self.chk_content_frame)
            self._recalc_size()
        elif self._zone_panel_visible:
            # 确保 mid_frame 可见
            if not self.mid_frame.winfo_ismapped():
                self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*self.scale)), after=self.top_frame)
            self.zone_frame.grid(row=0, column=0, columnspan=2, sticky="new")
            self._recalc_size()
        elif self._checklist_panel_visible:
            # 确保 mid_frame 可见
            if not self.mid_frame.winfo_ismapped():
                self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*self.scale)), after=self.top_frame)
            self.chk_frame.grid(row=0, column=0, columnspan=2, sticky="new")
            self.chk_border_frame.pack_forget()
            self._recalc_size()
        else:
            # 两个面板都不可见时，隐藏 mid_frame 让UI正确收缩
            self.mid_frame.pack_forget()
            self._recalc_size(force_shrink=True)  # 强制收缩

    def _set_zone_panel_visible(self, visible: bool):
        if self._zone_panel_visible != visible:
            self._zone_panel_visible = visible
            self._update_mid_panel_layout()

    def _set_checklist_visible(self, visible: bool):
        if self._checklist_panel_visible != visible:
            self._checklist_panel_visible = visible
            self._update_mid_panel_layout()

    def _update_zone_display(self, snap: UISnapshot):
        s = self.scale
        if snap.player_heading > 0: self.heading_lbl.config(text=f"HDG: {int(snap.player_heading):03d}°")
        else: self.heading_lbl.config(text="HDG: ---")
        
        if snap.zone_destroyed_alert:
            self.zone_alert_lbl.config(text="💥 战区已摧毁!")
            if not self.zone_alert_lbl.winfo_ismapped():
                self.zone_alert_lbl.pack(fill="x", padx=int(8*s), pady=(0, int(4*s)), after=self.zone_title.master)
            if not self._last_zone_destroyed_alert and self._zone_sound_enabled:
                self.sound.play(pattern="zone_destroyed")
            self._last_zone_destroyed_alert = True
        else:
            if self.zone_alert_lbl.winfo_ismapped(): self.zone_alert_lbl.pack_forget()
            self._last_zone_destroyed_alert = False
        
        for lbl in self.zone_labels: lbl.destroy()
        self.zone_labels.clear()
        
        if not snap.zones:
            font_item = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
            empty_lbl = tk.Label(self.zone_list_frame, text="无战区", font=font_item, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w")
            empty_lbl.pack(fill="x")
            self.zone_labels.append(empty_lbl)
            return
        
        font_item = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        for zone in snap.zones:
            marker = "➤" if zone.is_target else "○"
            dist_text = f"{zone.distance_km:.1f}km" if zone.distance_km < 10 else f"{int(zone.distance_km)}km"
            rel_sign = "+" if zone.relative > 0 else ""
            rel_text = f"{rel_sign}{int(zone.relative)}°"
            
            text = f"{marker} {zone.direction} {dist_text}  ({rel_text})"
            
            # === V5.2 新增：显示 ETE ===
            if zone.ete_str:
                text += f"   ⏱️{zone.ete_str}"
            
            fg = Theme.GREEN if zone.is_target and not snap.is_deviating else Theme.ORANGE if zone.is_target else Theme.TEXT_DIM
            
            lbl = tk.Label(self.zone_list_frame, text=text, font=font_item, fg=fg, bg=Theme.GRAYPILL, anchor="w")
            lbl.pack(fill="x")
            self.zone_labels.append(lbl)
        
        if snap.is_deviating and snap.has_target:
            warn_text = f"⚠️ 偏航 ({int(snap.deviation_angle):+d}°)"
            warn_lbl = tk.Label(self.zone_list_frame, text=warn_text, font=font_item, fg=Theme.ORANGE, bg=Theme.GRAYPILL, anchor="w")
            warn_lbl.pack(fill="x", pady=(int(4*s), 0))
            self.zone_labels.append(warn_lbl)

    def _update_ui(self):
        if self._stop: return
        snap = self.game.snapshot()

        show_zones = (snap.phase == Phase.ALIVE) and (not snap.api_down) and len(snap.zones) > 0
        self._set_zone_panel_visible(show_zones)
        if show_zones: 
            self._update_zone_display(snap)
            # 战区内容更新后重新计算尺寸
            self._recalc_size()

        show_chk = (snap.phase == Phase.ALIVE) and (snap.on_ground or snap.landed_flash) and (not snap.api_down)
        self._set_checklist_visible(show_chk)

        if snap.sortie_id != self._last_sortie_id:
            self._last_sortie_id = snap.sortie_id
            if snap.sortie_id > 0: self._reset_checklist()

        self.timer_lbl.config(text=fmt_time(snap.remaining_sec))
        if snap.remaining_sec is None:
            self.timer_lbl.config(fg=Theme.TEXT_MUTED)
            self.bar_fill.place(relwidth=0)
            self.bar_fill.config(bg=Theme.BLUE)
        else:
            remain = snap.remaining_sec
            color = Theme.RED if remain <= 10 else Theme.YELLOW if remain <= GameConfig.FINAL_WARNING_SEC else Theme.TEXT
            bar = Theme.RED if remain <= 10 else Theme.YELLOW if remain <= GameConfig.FINAL_WARNING_SEC else Theme.BLUE
            self.timer_lbl.config(fg=color)
            self.bar_fill.place(relwidth=snap.progress)
            self.bar_fill.config(bg=bar)
            remain_int = int(remain)
            if remain <= GameConfig.FINAL_WARNING_SEC:
                if remain_int in SoundConfig.WARNING_SECONDS and remain_int != self._last_beep_sec:
                    pattern = "warning" if remain_int in SoundConfig.MAJOR_WARNINGS else "tick"
                    self.sound.play(pattern=pattern)
                    self._last_beep_sec = remain_int
            else: self._last_beep_sec = -1

        self.life_lbl.config(text=(f"第{snap.life_index}次复活" if snap.life_index is not None else "未复活"))
        self.cycle_lbl.config(text=(f"第{snap.cycle}轮" if snap.cycle is not None else "未开始"))
        self.badge_main.set(*snap.main_badge)
        self.badge_flight.set(*snap.flight_badge)
        self.status_txt.config(text=snap.status_text, fg=(Theme.YELLOW if snap.api_down else Theme.TEXT_DIM))

        if self._debug:
            debug_text = snap.diag_text
            if self._restored_state and snap.phase == Phase.ALIVE: debug_text += "\n🔄 已从保存状态恢复计时"
            debug_text += f"\n战区: {len(snap.zones)}个"
            if snap.has_target: debug_text += f" | 目标偏离: {int(snap.deviation_angle)}°"
            self.diag_lbl.config(text=debug_text)

        self.root.after(UIConfig.UI_REFRESH_MS, self._update_ui)


def main():
    SingleInstanceManager.ensure_single_instance_or_exit()
    Win32.enable_dpi()
    Win32.hide_console()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
