#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新增功能：
- 配置持久化：保存用户设置、窗口位置、清单项等
- 右键菜单：更直观的操作方式
- 设置对话框：可调整透明度、缩放、热键等
- 自定义清单：用户可编辑清单项
- 动态透明度/缩放调整：Ctrl+滚轮
- Windows通知：时间到时弹出系统通知
- 改进的并发控制和异常处理

pyinstaller --onefile --noconsole --clean --name WTtimer --add-data "app.png;." --icon app.ico --collect-all pystray --collect-all PIL WTtimer_enhanced.pyw
"""

import os
import sys
import json
import time
import ctypes
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple, Any, List, Dict
from enum import Enum, auto

import tkinter as tk
from tkinter import messagebox, simpledialog
import requests

# Optional dependencies
try:
    from PIL import Image, ImageDraw
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    from win10toast import ToastNotifier
    HAS_TOAST = True
except ImportError:
    HAS_TOAST = False


def resource_path(rel_path: str) -> str:
    """Get absolute path to resource, works for dev and PyInstaller"""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel_path)


class Config:
    """Application configuration with defaults"""
    CYCLE_SECONDS = 15 * 60
    FINAL_WARNING_SEC = 30

    POLL_INTERVAL = 0.25
    UI_REFRESH_MS = 50

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

    API_CONNECT_TIMEOUT = 0.08
    API_READ_TIMEOUT = 0.16
    MAX_TICK_NET_BUDGET = 0.20
    BACKOFF_MAX = 1.25

    API_BASE = "http://127.0.0.1:8111"
    MUTEX_NAME = r"Global\WTtimer_SingleInstance"

    # UI settings (modifiable)
    UI_SCALE_MULT = 0.85
    WINDOW_ALPHA = 210
    GLOBAL_HOTKEYS = True
    
    # User config file
    CONFIG_FILE = Path.home() / ".wttimer_config.json"
    
    # Default checklist items
    DEFAULT_CHECKLIST = [
        "收起落架",
        "开增稳系统", 
        "设定打击目标",
        "取消武器选择模式",
        "火控Y67炸弹自动",
        "调整雷达Y11"
    ]

    @classmethod
    def load_user_config(cls) -> Dict[str, Any]:
        """Load user configuration from file"""
        if cls.CONFIG_FILE.exists():
            try:
                with open(cls.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    @classmethod
    def save_user_config(cls, config: Dict[str, Any]) -> None:
        """Save user configuration to file"""
        try:
            with open(cls.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except IOError:
            pass


class Theme:
    """Color scheme"""
    BG = "#0a0e13"
    BORDER = "#30363d"

    TEXT = "#e6edf3"
    TEXT_DIM = "#8b949e"
    TEXT_MUTED = "#484f58"

    GREEN = "#3fb950"
    YELLOW = "#d29922"
    RED = "#f85149"
    BLUE = "#58a6ff"
    GRAYPILL = "#161b22"


class Win32:
    """Windows API utilities"""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    @classmethod
    def enable_dpi(cls):
        """Enable DPI awareness"""
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
        """Get DPI scale for window"""
        try:
            dpi = cls.user32.GetDpiForWindow(hwnd)
            return (dpi / 96.0) if dpi else 1.0
        except (OSError, AttributeError):
            return 1.0

    @classmethod
    def screen_size(cls) -> Tuple[int, int]:
        """Get screen dimensions"""
        return cls.user32.GetSystemMetrics(0), cls.user32.GetSystemMetrics(1)

    @classmethod
    def setup_window(cls, hwnd: int, click_through: bool, alpha: int = 210):
        """Setup window as layered, topmost, and optionally click-through"""
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
        """Hide console window"""
        try:
            hwnd = cls.kernel32.GetConsoleWindow()
            if hwnd:
                cls.user32.ShowWindow(hwnd, 0)
        except (OSError, AttributeError):
            pass


_MUTEX_HANDLE = None


class GlobalHotkeys:
    """Windows global hotkeys via RegisterHotKey + WM_HOTKEY"""

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    MOD_NOREPEAT = 0x4000

    # Virtual-key codes for function keys
    VK_F7 = 0x76
    VK_F8 = 0x77
    VK_F9 = 0x78
    VK_F10 = 0x79

    def __init__(self, root: tk.Tk, hotkeys: List[Tuple[int, int, callable]]):
        """hotkeys: list of (id, vk, callback)"""
        self.root = root
        self.hotkeys = hotkeys
        self._thread = None
        self._tid = None
        self._stop_event = threading.Event()

    def start(self):
        """Start hotkey listener thread"""
        if not os.name == "nt" or not Config.GLOBAL_HOTKEYS:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop hotkey listener thread"""
        if not os.name == "nt" or not self._tid:
            return
        try:
            self._stop_event.set()
            Win32.user32.PostThreadMessageW(int(self._tid), int(self.WM_QUIT), 0, 0)
        except (OSError, AttributeError):
            pass
        
        # Wait for thread to finish with timeout
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self):
        """Hotkey listener thread main loop"""
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentThreadId.restype = ctypes.c_uint
            self._tid = int(kernel32.GetCurrentThreadId())
        except (OSError, AttributeError):
            self._tid = None
            return

        # Register hotkeys (best-effort)
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
                    break  # WM_QUIT
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

        # Unregister hotkeys
        for hk_id, _vk, _cb in self.hotkeys:
            try:
                Win32.user32.UnregisterHotKey(None, int(hk_id))
            except (OSError, AttributeError):
                pass


def ensure_single_instance_or_exit():
    """Ensure only one instance of the app is running"""
    global _MUTEX_HANDLE
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.GetLastError.restype = ctypes.c_uint

        h = kernel32.CreateMutexW(None, True, Config.MUTEX_NAME)
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
        pass  # Non-Windows or API not available


def release_single_instance_mutex():
    """Release the single instance mutex"""
    global _MUTEX_HANDLE
    if _MUTEX_HANDLE:
        try:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_MUTEX_HANDLE))
        except (OSError, AttributeError):
            pass
        _MUTEX_HANDLE = None


@dataclass
class TelemetryData:
    """Aircraft telemetry data"""
    ind_ok: bool = False
    state_resp_ok: bool = False

    valid: bool = False
    type_name: str = ""

    ias_kmh: float = 0
    vy_ms: float = 0
    fuel_kg: float = 0

    @property
    def entity_like(self) -> bool:
        """Check if telemetry indicates an active entity"""
        if not (self.ind_ok and self.state_resp_ok and self.valid and self.type_name):
            return False
        return (self.fuel_kg > 0.1) or (abs(self.ias_kmh) > 0.1) or (abs(self.vy_ms) > 0.1)

    @property
    def is_on_ground(self) -> bool:
        """Check if aircraft is on ground"""
        return (self.ias_kmh < Config.LAND_SPEED_KMH and abs(self.vy_ms) < 2.0)


@dataclass
class MapObjData:
    """Map objects data"""
    ok: bool = False
    player_aircraft_present: bool = False
    obj_count: int = 0


class Budget:
    """Time budget for network operations"""
    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + max(0.0, seconds)

    def remaining(self) -> float:
        return self.deadline - time.monotonic()


class HttpJson:
    """HTTP JSON fetcher"""
    def __init__(self, session: requests.Session):
        self.session = session

    def get_json(self, url: str, budget: Budget) -> Tuple[bool, Optional[Any]]:
        """Fetch JSON from URL within time budget"""
        rem = budget.remaining()
        if rem <= 0.0:
            return False, None

        connect_t = min(Config.API_CONNECT_TIMEOUT, max(0.01, rem))
        read_t = min(Config.API_READ_TIMEOUT, max(0.01, rem))

        try:
            r = self.session.get(url, timeout=(connect_t, read_t))
            if not r.ok:
                return False, None
            return True, r.json()
        except (requests.RequestException, ValueError):
            return False, None


class TelemetryFetcher:
    """Fetch telemetry data from War Thunder API"""
    def __init__(self, http: HttpJson):
        self.http = http

    def fetch(self, budget: Budget) -> TelemetryData:
        """Fetch telemetry data"""
        data = TelemetryData()

        ok, j = self.http.get_json(f"{Config.API_BASE}/indicators", budget)
        data.ind_ok = ok
        if ok and isinstance(j, dict):
            data.valid = bool(j.get("valid", False))
            data.type_name = str(j.get("type", "") or "").strip()

        if not data.ind_ok:
            return data

        ok, j = self.http.get_json(f"{Config.API_BASE}/state", budget)
        data.state_resp_ok = ok
        if ok and isinstance(j, dict):
            data.ias_kmh = float(j.get("IAS, km/h", 0) or 0)
            data.vy_ms = float(j.get("Vy, m/s", 0) or 0)
            data.fuel_kg = float(j.get("Mfuel, kg", 0) or 0)

        return data


class MapObjectsFetcher:
    """Fetch map objects from War Thunder API"""
    def __init__(self, http: HttpJson):
        self.http = http

    def fetch(self, budget: Budget) -> MapObjData:
        """Fetch map objects data"""
        out = MapObjData()
        ok, j = self.http.get_json(f"{Config.API_BASE}/map_obj.json", budget)
        if not ok:
            return out

        out.ok = True

        objs: List[Any]
        if isinstance(j, list):
            objs = j
        elif isinstance(j, dict):
            if isinstance(j.get("objects"), list):
                objs = j["objects"]
            elif isinstance(j.get("map_objects"), list):
                objs = j["map_objects"]
            else:
                objs = []
        else:
            objs = []

        out.obj_count = len(objs)

        for o in objs:
            if not isinstance(o, dict):
                continue
            if o.get("type") == "aircraft" and o.get("icon") == "Player":
                out.player_aircraft_present = True
                break

        return out


class Phase(Enum):
    """Game phase states"""
    IDLE = auto()
    HANGAR = auto()
    ARMING = auto()
    ALIVE = auto()
    LOSS_PENDING = auto()
    WAIT_NEXT = auto()


@dataclass
class LifeState:
    """Current life state"""
    spawn_time: float
    life_index: int

    def elapsed_seconds(self, now: float) -> float:
        return now - self.spawn_time

    def current_cycle(self, now: float) -> int:
        return int(self.elapsed_seconds(now) // Config.CYCLE_SECONDS) + 1

    def cycle_remaining(self, now: float) -> float:
        elapsed = self.elapsed_seconds(now)
        return Config.CYCLE_SECONDS - (elapsed % Config.CYCLE_SECONDS)

    def cycle_progress(self, now: float) -> float:
        elapsed = self.elapsed_seconds(now)
        return (elapsed % Config.CYCLE_SECONDS) / Config.CYCLE_SECONDS


@dataclass
class GameState:
    """Complete game state"""
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


@dataclass(frozen=True)
class UISnapshot:
    """Immutable snapshot of UI state"""
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


class GameLogic:
    """Core game logic and state management"""
    def __init__(self):
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.http = HttpJson(self.session)
        self.tel = TelemetryFetcher(self.http)
        self.map = MapObjectsFetcher(self.http)
        self.state = GameState()

    def tick(self) -> None:
        """Update game state based on API data"""
        now = time.time()
        budget = Budget(Config.MAX_TICK_NET_BUDGET)

        tel = self.tel.fetch(budget)
        mp = self.map.fetch(budget)

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
                if (now - s.api_down_candidate_since) >= Config.API_DOWN_CONFIRM_SEC:
                    s.api_down = True

            if s.api_down:
                if s.phase != Phase.HANGAR:
                    s.phase = Phase.IDLE
                return

            player_present = bool(mp.ok and mp.player_aircraft_present)
            spawn_candidate = player_present and tel.entity_like

            hangar_like = (not mp.ok) or (mp.obj_count == 0)
            if hangar_like and (not player_present) and s.phase != Phase.ALIVE:
                if s.hangar_candidate_since is None:
                    s.hangar_candidate_since = now
                elif (now - s.hangar_candidate_since) >= Config.HANGAR_CONFIRM_SEC:
                    s.phase = Phase.HANGAR
                    s.current_life = None
                    s.sortie_id = 0
                    s.last_refit_ts = 0.0
                    s.spawn_candidate_since = None
                    s.missing_player_since = None
                    s.landing_start_time = None
                    s.landed_flash_until = 0.0
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
                    if (now - s.spawn_candidate_since) >= Config.SPAWN_CONFIRM_SEC:
                        self._start_new_life_locked(now)
                        s.phase = Phase.ALIVE
                        s.spawn_candidate_since = None
                        s.missing_player_since = None
                        s.landing_start_time = None
                        s.landed_flash_until = 0.0
                else:
                    s.spawn_candidate_since = None
                    s.phase = Phase.IDLE

            elif s.phase == Phase.ALIVE:
                # Refit refresh
                if prev_tel and prev_tel.state_resp_ok and tel.state_resp_ok:
                    fuel_jump = tel.fuel_kg - prev_tel.fuel_kg
                    if (fuel_jump >= Config.REFIT_FUEL_JUMP_KG and
                        tel.ias_kmh <= Config.REFIT_SPEED_KMH and
                        abs(tel.vy_ms) <= Config.REFIT_VSPEED_MS and
                        (now - s.last_refit_ts) >= Config.REFIT_MIN_GAP_SEC):
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
                    if (now - s.missing_player_since) >= Config.DEAD_CONFIRM_SEC:
                        s.phase = Phase.WAIT_NEXT
                        s.spawn_candidate_since = None

            elif s.phase == Phase.WAIT_NEXT:
                if spawn_candidate:
                    if s.spawn_candidate_since is None:
                        s.spawn_candidate_since = now
                    if (now - s.spawn_candidate_since) >= Config.SPAWN_CONFIRM_SEC:
                        self._start_new_life_locked(now)
                        s.phase = Phase.ALIVE
                        s.spawn_candidate_since = None
                        s.missing_player_since = None
                        s.landing_start_time = None
                        s.landed_flash_until = 0.0
                else:
                    s.spawn_candidate_since = None

    def manual_reset(self):
        """Manually reset timer"""
        with self._lock:
            if self.state.phase == Phase.ALIVE and self.state.current_life:
                self.state.current_life.spawn_time = time.time()
                self.state.landing_start_time = None
                self.state.landed_flash_until = 0.0

    def snapshot(self) -> UISnapshot:
        """Get immutable snapshot of current state"""
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
                status_text = "未检测到 8111（请启动游戏）"
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
                    status_text = "机库 / 等待游戏开始"
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
            diag = (
                f"map_ok={int(mp.ok)} objs={mp.obj_count} player={int(player_present)} | "
                f"ind_ok={int(tel.ind_ok)} ind_valid={int(tel.valid)} type={1 if bool(tel.type_name) else 0} | "
                f"state_ok={int(tel.state_resp_ok)} fuel={tel.fuel_kg:.0f}"
            )

            return UISnapshot(
                phase=s.phase,
                life_index=life_index,
                cycle=cycle,
                remaining_sec=remaining,
                progress=progress,
                sortie_id=s.sortie_id,
                main_badge=main_badge,
                flight_badge=flight_badge,
                status_text=status_text,
                diag_text=diag,
                api_down=s.api_down,
                api_down_pending=api_down_pending,
                on_ground=on_ground,
                landed_flash=landed_flash,
            )

    def _start_new_life_locked(self, now: float):
        """Start a new life (must be called with lock held)"""
        s = self.state
        next_index = 1 if not s.current_life else (s.current_life.life_index + 1)
        s.current_life = LifeState(spawn_time=now, life_index=next_index)
        s.sortie_id += 1
        s.last_refit_ts = now

    def _update_landing_locked(self, tel: TelemetryData, now: float):
        """Update landing state (must be called with lock held)"""
        s = self.state
        if not s.current_life:
            return

        if tel.is_on_ground:
            if s.landing_start_time is None:
                s.landing_start_time = now
            elif (now - s.landing_start_time) >= Config.LAND_CONFIRM_SEC:
                if s.landed_flash_until <= now:
                    s.landed_flash_until = now + Config.LANDED_FLASH_SEC
        else:
            s.landing_start_time = None


def fmt_time(sec: Optional[float]) -> str:
    """Format seconds as MM:SS"""
    if sec is None:
        return "--:--"
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"


class Corner(Enum):
    """Window corner positions"""
    TOP_RIGHT = 0
    TOP_LEFT = 1
    BOTTOM_RIGHT = 2
    BOTTOM_LEFT = 3


class Pill(tk.Label):
    """Styled pill-shaped label"""
    def __init__(self, parent, text="", fg=Theme.TEXT, bg=Theme.GRAYPILL, font=None):
        super().__init__(parent, text=text, fg=fg, bg=bg, bd=0, highlightthickness=0)
        if font:
            self.configure(font=font)
        self._apply_padding(text)

    def _apply_padding(self, text: str):
        self.configure(text=f"  {text}  ")

    def set(self, text: str, fg: str, bg: str):
        self.configure(fg=fg, bg=bg)
        self._apply_padding(text)


class SettingsDialog(tk.Toplevel):
    """Settings dialog window"""
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("设置")
        self.resizable(False, False)
        self.configure(bg=Theme.BG)
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._build_ui()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        """Build settings UI"""
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=20, pady=15)
        
        # Transparency
        tk.Label(main, text="窗口透明度:", bg=Theme.BG, fg=Theme.TEXT).grid(row=0, column=0, sticky="w", pady=5)
        self.alpha_var = tk.IntVar(value=Config.WINDOW_ALPHA)
        alpha_scale = tk.Scale(
            main, from_=100, to=255, orient="horizontal",
            variable=self.alpha_var, length=200,
            bg=Theme.BG, fg=Theme.TEXT, highlightthickness=0,
            troughcolor=Theme.BORDER, activebackground=Theme.BLUE
        )
        alpha_scale.grid(row=0, column=1, padx=10, pady=5)
        
        # Scale
        tk.Label(main, text="UI缩放:", bg=Theme.BG, fg=Theme.TEXT).grid(row=1, column=0, sticky="w", pady=5)
        self.scale_var = tk.DoubleVar(value=Config.UI_SCALE_MULT)
        scale_scale = tk.Scale(
            main, from_=0.6, to=1.2, resolution=0.05, orient="horizontal",
            variable=self.scale_var, length=200,
            bg=Theme.BG, fg=Theme.TEXT, highlightthickness=0,
            troughcolor=Theme.BORDER, activebackground=Theme.BLUE
        )
        scale_scale.grid(row=1, column=1, padx=10, pady=5)
        
        # Global hotkeys
        tk.Label(main, text="全局热键:", bg=Theme.BG, fg=Theme.TEXT).grid(row=2, column=0, sticky="w", pady=5)
        self.hotkeys_var = tk.BooleanVar(value=Config.GLOBAL_HOTKEYS)
        tk.Checkbutton(
            main, text="启用", variable=self.hotkeys_var,
            bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL,
            activebackground=Theme.BG, activeforeground=Theme.TEXT,
            highlightthickness=0
        ).grid(row=2, column=1, sticky="w", padx=10, pady=5)
        
        # Buttons
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(15, 0))
        
        tk.Button(
            btn_frame, text="保存", command=self._save,
            bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5,
            activebackground=Theme.BORDER
        ).pack(side="left", padx=5)
        
        tk.Button(
            btn_frame, text="取消", command=self.destroy,
            bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5,
            activebackground=Theme.BORDER
        ).pack(side="left", padx=5)

    def _save(self):
        """Save settings"""
        Config.WINDOW_ALPHA = self.alpha_var.get()
        Config.UI_SCALE_MULT = self.scale_var.get()
        
        old_hotkeys = Config.GLOBAL_HOTKEYS
        Config.GLOBAL_HOTKEYS = self.hotkeys_var.get()
        
        # Save to config file
        config = Config.load_user_config()
        config['alpha'] = Config.WINDOW_ALPHA
        config['scale'] = Config.UI_SCALE_MULT
        config['global_hotkeys'] = Config.GLOBAL_HOTKEYS
        Config.save_user_config(config)
        
        # Apply changes
        Win32.setup_window(self.app.hwnd, self.app._locked, Config.WINDOW_ALPHA)
        
        # Restart hotkeys if changed
        if old_hotkeys != Config.GLOBAL_HOTKEYS:
            if hasattr(self.app, '_ghk') and self.app._ghk:
                self.app._ghk.stop()
            if Config.GLOBAL_HOTKEYS:
                self.app._init_global_hotkeys()
                if hasattr(self.app, '_ghk') and self.app._ghk:
                    self.app._ghk.start()
        
        messagebox.showinfo("设置", "设置已保存\n部分更改需要重启生效", parent=self)
        self.destroy()


class ChecklistEditor(tk.Toplevel):
    """Checklist editor dialog"""
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("编辑检查清单")
        self.resizable(False, False)
        self.configure(bg=Theme.BG)
        
        self.transient(parent)
        self.grab_set()
        
        self._build_ui()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        """Build editor UI"""
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=20, pady=15, fill="both", expand=True)
        
        tk.Label(
            main, text="每行一个检查项（最多8项）:",
            bg=Theme.BG, fg=Theme.TEXT, anchor="w"
        ).pack(fill="x", pady=(0, 5))
        
        self.text = tk.Text(
            main, width=40, height=10,
            bg=Theme.GRAYPILL, fg=Theme.TEXT,
            insertbackground=Theme.TEXT,
            bd=0, highlightthickness=1, highlightbackground=Theme.BORDER
        )
        self.text.pack(fill="both", expand=True)
        
        # Load current items
        current_items = "\n".join(self.app.chk_items)
        self.text.insert("1.0", current_items)
        
        # Buttons
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(pady=(10, 0))
        
        tk.Button(
            btn_frame, text="保存", command=self._save,
            bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5
        ).pack(side="left", padx=5)
        
        tk.Button(
            btn_frame, text="恢复默认", command=self._restore_default,
            bg=Theme.YELLOW, fg=Theme.TEXT, bd=0, padx=15, pady=5
        ).pack(side="left", padx=5)
        
        tk.Button(
            btn_frame, text="取消", command=self.destroy,
            bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5
        ).pack(side="left", padx=5)

    def _save(self):
        """Save checklist items"""
        content = self.text.get("1.0", "end-1c")
        items = [line.strip() for line in content.split("\n") if line.strip()]
        
        if not items:
            messagebox.showwarning("警告", "检查清单不能为空", parent=self)
            return
        
        if len(items) > 8:
            messagebox.showwarning("警告", "检查项数量不能超过8个", parent=self)
            return
        
        # Save to config
        config = Config.load_user_config()
        config['checklist_items'] = items
        Config.save_user_config(config)
        
        # Update app
        self.app.chk_items = items
        self.app._rebuild_checklist()
        
        messagebox.showinfo("成功", "检查清单已保存", parent=self)
        self.destroy()

    def _restore_default(self):
        """Restore default checklist"""
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(Config.DEFAULT_CHECKLIST))


class App:
    """Main application"""
    def __init__(self, root: tk.Tk):
        self.root = root
        self.game = GameLogic()
        self._stop = False
        self._corner = Corner.TOP_RIGHT
        self._locked = True
        self._beep = False
        self._debug = False
        self._last_beep_sec = -1
        self._last_warning_sec = -1  # For notifications

        self._user_moved = False
        self._manual_pos = None
        self._last_sortie_id = -1

        self._beep_lock = threading.Lock()
        self._beep_playing = False

        # Load user config
        self._load_config()

        self._init_window_base()
        self._init_ui()
        self._finalize_window_geometry_and_styles()
        self._init_bindings()
        self._init_global_hotkeys()

        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._update_ui()

        if HAS_TRAY:
            self._init_tray()

    def _load_config(self):
        """Load user configuration"""
        config = Config.load_user_config()
        
        # Apply settings
        Config.WINDOW_ALPHA = config.get('alpha', Config.WINDOW_ALPHA)
        Config.UI_SCALE_MULT = config.get('scale', Config.UI_SCALE_MULT)
        Config.GLOBAL_HOTKEYS = config.get('global_hotkeys', Config.GLOBAL_HOTKEYS)
        
        # Load checklist
        self.chk_items = config.get('checklist_items', Config.DEFAULT_CHECKLIST.copy())
        
        # Load window position
        saved_pos = config.get('window_position')
        if saved_pos and isinstance(saved_pos, dict):
            corner_name = saved_pos.get('corner')
            if corner_name:
                try:
                    self._corner = Corner[corner_name]
                except KeyError:
                    pass
            
            manual_pos = saved_pos.get('manual_pos')
            if manual_pos and isinstance(manual_pos, list) and len(manual_pos) == 2:
                self._manual_pos = tuple(manual_pos)
                self._user_moved = saved_pos.get('user_moved', False)
        
        # Load other preferences
        self._beep = config.get('beep_enabled', False)

    def _save_config(self):
        """Save current configuration"""
        config = Config.load_user_config()
        
        config['alpha'] = Config.WINDOW_ALPHA
        config['scale'] = Config.UI_SCALE_MULT
        config['global_hotkeys'] = Config.GLOBAL_HOTKEYS
        config['checklist_items'] = self.chk_items
        config['beep_enabled'] = self._beep
        
        # Save window position
        config['window_position'] = {
            'corner': self._corner.name,
            'manual_pos': list(self._manual_pos) if self._manual_pos else None,
            'user_moved': self._user_moved
        }
        
        Config.save_user_config(config)

    def _init_window_base(self):
        """Initialize window basics"""
        self.root.title("WT Timer")
        try:
            p = resource_path("app.png")
            self._tk_icon = tk.PhotoImage(file=p)
            self.root.iconphoto(True, self._tk_icon)
        except (tk.TclError, FileNotFoundError):
            pass
        
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=Theme.BG)

        self.root.geometry("10x10+0+0")
        self.root.update_idletasks()

        self.hwnd = int(self.root.winfo_id())
        self.scale = Win32.get_dpi_scale(self.hwnd) * float(Config.UI_SCALE_MULT)

        try:
            self.root.tk.call("tk", "scaling", float(self.scale))
        except tk.TclError:
            pass

    def _finalize_window_geometry_and_styles(self):
        """Finalize window geometry and apply styles"""
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        pad = int(6 * self.scale)
        self.W = req_w + pad
        self.H = req_h + pad
        self._position()
        self.root.update_idletasks()
        Win32.setup_window(self.hwnd, click_through=True, alpha=Config.WINDOW_ALPHA)

    def _init_ui(self):
        """Initialize UI components"""
        s = self.scale
        main = tk.Frame(self.root, bg=Theme.BG)
        main.pack(fill="both", expand=True, padx=int(18*s), pady=int(14*s))

        # Row 1: Timer and life info
        row1 = tk.Frame(main, bg=Theme.BG)
        row1.pack(fill="x")

        self.timer_lbl = tk.Label(
            row1, text="--:--",
            font=("Segoe UI", int(44*s), "bold"),
            fg=Theme.TEXT_MUTED, bg=Theme.BG, anchor="w"
        )
        self.timer_lbl.pack(side="left")

        right = tk.Frame(row1, bg=Theme.BG)
        right.pack(side="right", padx=(int(14*s), 0))

        self.life_lbl = tk.Label(
            right, text="未复活",
            font=("Segoe UI", int(13*s), "bold"),
            fg=Theme.BLUE, bg=Theme.BG, anchor="e"
        )
        self.life_lbl.pack(anchor="e")

        self.cycle_lbl = tk.Label(
            right, text="未开始",
            font=("Segoe UI", int(12*s)),
            fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="e"
        )
        self.cycle_lbl.pack(anchor="e", pady=(int(2*s), 0))

        # Row 2: Badges and status
        row2 = tk.Frame(main, bg=Theme.BG)
        row2.pack(fill="x", pady=(int(10*s), int(6*s)))

        pill_font = ("Segoe UI", int(10*s), "bold")
        self.badge_main = Pill(row2, text="IDLE", fg=Theme.TEXT, bg=Theme.GRAYPILL, font=pill_font)
        self.badge_main.pack(side="left")

        self.badge_flight = Pill(row2, text="—", fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, font=pill_font)
        self.badge_flight.pack(side="left", padx=(int(8*s), 0))

        self.status_txt = tk.Label(
            row2, text="等待中",
            font=("Segoe UI", int(11*s)),
            fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="e"
        )
        self.status_txt.pack(side="right")

        # Progress bar
        bar_frame = tk.Frame(main, bg=Theme.BG, height=int(8*s))
        bar_frame.pack(fill="x", pady=(int(6*s), int(8*s)))
        bar_frame.pack_propagate(False)

        self.bar_bg = tk.Frame(bar_frame, bg=Theme.BORDER, height=int(4*s))
        self.bar_bg.place(relx=0, rely=0.5, relwidth=1, anchor="w")
        self.bar_fill = tk.Frame(self.bar_bg, bg=Theme.BLUE, height=int(4*s))
        self.bar_fill.place(relx=0, rely=0, relwidth=0, relheight=1)

        # Checklist frame (will be populated by _rebuild_checklist)
        self.chk_frame = tk.Frame(main, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        self.chk_vars: List[tk.BooleanVar] = []
        self._rebuild_checklist()

        # Debug line
        self.diag_lbl = tk.Label(
            main, text="",
            font=("Consolas", int(9*s)),
            fg=Theme.TEXT_MUTED, bg=Theme.BG, anchor="w"
        )

        # Hint line
        self.hint_lbl = tk.Label(
            main, text=self._hint_text(),
            font=("Segoe UI", int(9*s)),
            fg=Theme.TEXT_MUTED, bg=Theme.BG
        )
        self.hint_lbl.pack(fill="x")

    def _rebuild_checklist(self):
        """Rebuild checklist UI with current items"""
        # Clear existing widgets
        for widget in self.chk_frame.winfo_children():
            widget.destroy()
        self.chk_vars.clear()

        s = self.scale
        
        # Title
        self.chk_title = tk.Label(
            self.chk_frame, text="✅ 出击检查",
            font=("Segoe UI", int(9*s), "bold"),
            fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w"
        )
        self.chk_title.grid(row=0, column=0, columnspan=2, sticky="w", padx=int(8*s), pady=(int(6*s), int(2*s)))

        # Items in two columns
        item_font = ("Segoe UI", int(8*s))
        pad_x = int(8*s)
        for i, item in enumerate(self.chk_items):
            var = tk.BooleanVar(value=False)
            self.chk_vars.append(var)
            r = 1 + (i // 2)
            c = i % 2
            cb = tk.Checkbutton(
                self.chk_frame,
                text=item,
                variable=var,
                onvalue=True, offvalue=False,
                font=item_font,
                fg=Theme.TEXT_DIM,
                bg=Theme.GRAYPILL,
                activebackground=Theme.GRAYPILL,
                activeforeground=Theme.TEXT,
                selectcolor=Theme.BG,
                anchor="w",
                bd=0,
                highlightthickness=0,
                padx=0, pady=0
            )
            cb.grid(row=r, column=c, sticky="w", padx=(pad_x, 0), pady=0)

    def _init_bindings(self):
        """Initialize keyboard and mouse bindings"""
        self.root.bind("<Escape>", lambda e: self._quit())
        self.root.bind("<F7>", lambda e: self._manual_reset())
        self.root.bind("<F8>", lambda e: self._toggle_lock())
        self.root.bind("<F9>", lambda e: self._next_corner())
        self.root.bind("<F10>", lambda e: self._toggle_beep())

        # Mouse wheel for transparency (Ctrl+Wheel)
        self.root.bind("<Control-MouseWheel>", self._adjust_alpha)

        # Drag to move
        self._drag = {"x": 0, "y": 0}
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)

        # Right-click menu
        self.root.bind("<Button-3>", self._show_context_menu)

        # Create context menu
        self.context_menu = tk.Menu(self.root, tearoff=0, bg=Theme.GRAYPILL, fg=Theme.TEXT)
        self.context_menu.add_command(label="🔄 重置计时器 (F7)", command=self._manual_reset)
        self.context_menu.add_command(label="🔓 锁定/解锁 (F8)", command=self._toggle_lock)
        self.context_menu.add_command(label="📍 切换角落 (F9)", command=self._next_corner)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📝 编辑检查清单", command=self._edit_checklist)
        self.context_menu.add_command(label="⚙️ 设置", command=self._show_settings)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❌ 退出", command=self._quit)

    def _init_global_hotkeys(self):
        """Initialize global hotkeys"""
        self._ghk = None
        if not os.name == "nt" or not Config.GLOBAL_HOTKEYS:
            return

        hotkeys = [
            (7007, GlobalHotkeys.VK_F7, self._manual_reset),
            (7008, GlobalHotkeys.VK_F8, self._toggle_lock),
            (7009, GlobalHotkeys.VK_F9, self._next_corner),
            (7010, GlobalHotkeys.VK_F10, self._toggle_beep),
        ]
        self._ghk = GlobalHotkeys(self.root, hotkeys)
        self._ghk.start()

    def _init_tray(self):
        """Initialize system tray icon"""
        def icon():
            try:
                path = resource_path("app.png")
                return Image.open(path).convert("RGBA")
            except (FileNotFoundError, IOError):
                # Create a simple colored icon if file not found
                img = Image.new('RGBA', (64, 64), Theme.BLUE)
                return img

        def toggle_debug(icon, item):
            self.root.after(0, self._toggle_debug)

        def is_debug_checked(item):
            return self._debug

        menu = pystray.Menu(
            pystray.MenuItem("Debug模式", toggle_debug, checked=is_debug_checked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("显示", lambda: self.root.after(0, self._show)),
            pystray.MenuItem("退出", lambda: self.root.after(0, self._quit)),
        )
        self.tray = pystray.Icon("WTTimer", icon(), "WT Timer", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _toggle_debug(self):
        """Toggle debug mode"""
        self._debug = not self._debug
        if self._debug:
            self.diag_lbl.pack(fill="x", pady=(0, int(10*self.scale)), before=self.hint_lbl)
        else:
            self.diag_lbl.pack_forget()
        self._recalc_size()

    def _recalc_size(self, keep_pos: bool = True):
        """Recalculate window size"""
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        pad = int(6 * self.scale)
        self.W = req_w + pad
        self.H = req_h + pad

        if keep_pos:
            try:
                x = int(self.root.winfo_x())
                y = int(self.root.winfo_y())
                if self._user_moved and self._manual_pos:
                    x, y = self._manual_pos
                if (x, y) != (0, 0):
                    self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
                    return
            except tk.TclError:
                pass

        self._position()

    def _show(self):
        """Show window"""
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass

    def _position(self):
        """Position window at current corner"""
        sw, sh = Win32.screen_size()
        m = int(20 * self.scale)
        pos = {
            Corner.TOP_RIGHT: (sw - self.W - m, m),
            Corner.TOP_LEFT: (m, m),
            Corner.BOTTOM_RIGHT: (sw - self.W - m, sh - self.H - m),
            Corner.BOTTOM_LEFT: (m, sh - self.H - m),
        }
        
        # Use manual position if user has moved the window
        if self._user_moved and self._manual_pos:
            x, y = self._manual_pos
        else:
            x, y = pos[self._corner]
        
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _toggle_lock(self):
        """Toggle window lock (click-through)"""
        self._locked = not self._locked
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=Config.WINDOW_ALPHA)
        self._update_hint()

    def _hint_text(self) -> str:
        """Get hint text based on current state"""
        sound = "🔊开" if self._beep else "🔇关"
        if self._locked:
            return f"F7重置 │ F8移动 │ F9角落 │ F10声音({sound}) │ 右键菜单 │ Esc退出"
        else:
            return f"拖动移动窗口 │ F8锁定 │ F10声音({sound}) │ 右键菜单 │ Esc退出"

    def _update_hint(self) -> None:
        """Update hint label"""
        if hasattr(self, "hint_lbl") and self.hint_lbl:
            self.hint_lbl.config(text=self._hint_text())

    def _next_corner(self):
        """Move window to next corner"""
        corners = list(Corner)
        i = (corners.index(self._corner) + 1) % len(corners)
        self._corner = corners[i]
        self._user_moved = False
        self._manual_pos = None
        self._position()
        self._save_config()

    def _toggle_beep(self):
        """Toggle beep sound"""
        self._beep = not self._beep
        self._update_hint()
        self._save_config()
        if self._beep:
            self._do_beep(pattern="on")

    def _manual_reset(self):
        """Manually reset timer"""
        self.game.manual_reset()
        self._do_beep(1000, 80)

    def _show_settings(self):
        """Show settings dialog"""
        if not self._locked:
            SettingsDialog(self.root, self)

    def _edit_checklist(self):
        """Show checklist editor"""
        if not self._locked:
            ChecklistEditor(self.root, self)

    def _show_context_menu(self, event):
        """Show context menu on right-click"""
        if not self._locked:
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

    def _adjust_alpha(self, event):
        """Adjust window transparency with Ctrl+MouseWheel"""
        if not self._locked:
            delta = 10 if event.delta > 0 else -10
            Config.WINDOW_ALPHA = max(100, min(255, Config.WINDOW_ALPHA + delta))
            Win32.setup_window(self.hwnd, click_through=False, alpha=Config.WINDOW_ALPHA)
            self._save_config()

    def _quit(self):
        """Quit application"""
        self._stop = True
        self._save_config()
        
        try:
            if getattr(self, "_ghk", None):
                self._ghk.stop()
        except (AttributeError, tk.TclError):
            pass
        
        if HAS_TRAY and hasattr(self, "tray"):
            try:
                self.tray.stop()
            except Exception:
                pass
        
        release_single_instance_mutex()
        self.root.destroy()

    def _start_drag(self, e):
        """Start window drag"""
        if self._locked:
            return
        self._drag["x"] = e.x
        self._drag["y"] = e.y

    def _do_drag(self, e):
        """Handle window drag"""
        if self._locked:
            return
        x = self.root.winfo_pointerx() - self._drag["x"]
        y = self.root.winfo_pointery() - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, e=None):
        """End window drag and save position"""
        if self._locked:
            return
        try:
            self._manual_pos = (int(self.root.winfo_x()), int(self.root.winfo_y()))
            self._user_moved = True
            self._save_config()
        except tk.TclError:
            pass

    def _do_beep(self, pattern: str = "tick", freq: int = None, duration: int = None):
        """Play beep sound"""
        if not self._beep and pattern != "on":
            return

        # Thread-safe beep control
        if not self._beep_lock.acquire(blocking=False):
            return

        try:
            # Single beep (for manual reset)
            if freq is not None and duration is not None:
                def _play_single():
                    try:
                        ctypes.windll.kernel32.Beep(int(freq), int(duration))
                    except (OSError, AttributeError):
                        pass
                    finally:
                        self._beep_lock.release()
                threading.Thread(target=_play_single, daemon=True).start()
                return

            # Pattern-based beep
            if pattern == "on":
                seq = [
                    (988, 40, 25),   # B5
                    (1319, 70, 0),   # E6
                ]
            elif pattern == "warning":
                seq = [
                    (784, 35, 20),   # G5
                    (988, 35, 0),    # B5
                ]
            else:  # "tick"
                seq = [
                    (784, 28, 0),    # G5
                ]

            def _play():
                try:
                    for (f, ms, gap) in seq:
                        try:
                            ctypes.windll.kernel32.Beep(int(f), int(ms))
                        except (OSError, AttributeError):
                            pass
                        if gap:
                            time.sleep(gap / 1000.0)
                finally:
                    self._beep_lock.release()

            threading.Thread(target=_play, daemon=True).start()
        except Exception:
            self._beep_lock.release()
            raise

    def _send_notification(self, title: str, message: str):
        """Send Windows notification"""
        if HAS_TOAST:
            try:
                toaster = ToastNotifier()
                threading.Thread(
                    target=lambda: toaster.show_toast(title, message, duration=5, threaded=True),
                    daemon=True
                ).start()
            except Exception:
                pass

    def _poll_loop(self):
        """Game state polling loop"""
        while not self._stop:
            loop_start = time.monotonic()
            self.game.tick()
            snap = self.game.snapshot()
            interval = Config.BACKOFF_MAX if snap.api_down else Config.POLL_INTERVAL
            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.0, interval - elapsed))

    def _reset_checklist(self):
        """Reset all checklist items"""
        for v in self.chk_vars:
            v.set(False)

    def _set_checklist_visible(self, visible: bool):
        """Show or hide checklist"""
        if visible:
            if not self.chk_frame.winfo_ismapped():
                before_widget = self.diag_lbl if self._debug else self.hint_lbl
                self.chk_frame.pack(fill="x", pady=(0, int(8*self.scale)), before=before_widget)
                self._recalc_size()
        else:
            if self.chk_frame.winfo_ismapped():
                self.chk_frame.pack_forget()
                self._recalc_size()

    def _update_ui(self):
        """Update UI based on game state"""
        if self._stop:
            return

        snap = self.game.snapshot()

        # Checklist visibility
        show_chk = (snap.phase == Phase.ALIVE) and (snap.on_ground or snap.landed_flash) and (not snap.api_down)
        self._set_checklist_visible(show_chk)

        # Reset checklist on sortie change
        if snap.sortie_id != self._last_sortie_id:
            self._last_sortie_id = snap.sortie_id
            if snap.sortie_id > 0:
                self._reset_checklist()

        # Timer and progress
        self.timer_lbl.config(text=fmt_time(snap.remaining_sec))
        if snap.remaining_sec is None:
            self.timer_lbl.config(fg=Theme.TEXT_MUTED)
            self.bar_fill.place(relwidth=0)
            self.bar_fill.config(bg=Theme.BLUE)
        else:
            remain = snap.remaining_sec
            if remain <= 10:
                color = Theme.RED
                bar = Theme.RED
            elif remain <= Config.FINAL_WARNING_SEC:
                color = Theme.YELLOW
                bar = Theme.YELLOW
            else:
                color = Theme.TEXT
                bar = Theme.BLUE

            self.timer_lbl.config(fg=color)
            self.bar_fill.place(relwidth=snap.progress)
            self.bar_fill.config(bg=bar)

            remain_int = int(remain)
            
            # Beep warnings
            if remain <= Config.FINAL_WARNING_SEC:
                if remain_int in (30, 20, 10, 5, 4, 3, 2, 1):
                    if remain_int != self._last_beep_sec:
                        self._do_beep(pattern=("warning" if remain_int in (30, 20, 10) else "tick"))
                        self._last_beep_sec = remain_int
            else:
                self._last_beep_sec = -1

            # Windows notifications
            if remain_int in (60, 30, 10) and remain_int != self._last_warning_sec:
                self._send_notification(
                    "WT Timer 提醒",
                    f"还剩 {remain_int} 秒！"
                )
                self._last_warning_sec = remain_int
            elif remain_int > 60:
                self._last_warning_sec = -1

        # Life and cycle info
        self.life_lbl.config(text=(f"第{snap.life_index}次复活" if snap.life_index is not None else "未复活"))
        self.cycle_lbl.config(text=(f"第{snap.cycle - 1}轮" if snap.cycle is not None else "未开始"))

        # Badges and status
        self.badge_main.set(*snap.main_badge)
        self.badge_flight.set(*snap.flight_badge)
        self.status_txt.config(text=snap.status_text, fg=(Theme.YELLOW if snap.api_down else Theme.TEXT_DIM))

        # Debug info
        if self._debug:
            self.diag_lbl.config(text=snap.diag_text)

        self.root.after(Config.UI_REFRESH_MS, self._update_ui)


def main():
    """Application entry point"""
    ensure_single_instance_or_exit()
    Win32.enable_dpi()
    Win32.hide_console()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
