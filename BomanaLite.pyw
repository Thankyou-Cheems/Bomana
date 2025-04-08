#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
BomanaLite - 战雷全真模式计时器（精简版）
===============================================================================

精简版特性：
- 仅保留核心15分钟自动计时功能
- 自动检测出生/死亡/着陆状态
- 透明悬浮窗口，可拖动
- 最小化资源占用

使用方法：
- 启动游戏后运行此程序
- 计时器会自动检测并开始计时
- 右键退出，拖动移动位置
===============================================================================
"""

import os
import sys
import json
import time
import ctypes
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple, Any
from enum import Enum, auto

import tkinter as tk
import requests
# 可选依赖：系统托盘支持
try:
    from PIL import Image
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False
# 可选依赖：用于打开网页
import webbrowser


# ============================================================================
# 配置类
# ============================================================================

class GameConfig:
    """游戏逻辑配置"""
    CYCLE_SECONDS = 15 * 60
    FINAL_WARNING_SEC = 30
    LAND_SPEED_KMH = 40
    LAND_CONFIRM_SEC = 3.0
    SPAWN_CONFIRM_SEC = 1.0
    DEAD_CONFIRM_SEC = 1.2
    HANGAR_CONFIRM_SEC = 1.2
    API_DOWN_CONFIRM_SEC = 5.0


class NetworkConfig:
    """网络配置"""
    API_BASE = "http://127.0.0.1:8111"
    API_CONNECT_TIMEOUT = 0.08
    API_READ_TIMEOUT = 0.16
    MAX_TICK_NET_BUDGET = 0.30
    BACKOFF_MAX = 1.25
    POLL_INTERVAL = 0.25


class UIConfig:
    """UI配置"""
    WINDOW_ALPHA = 210
    UI_SCALE_MULT = 1.0
    UI_REFRESH_MS = 50
    WINDOW_MARGIN = 20
    WINDOW_PADDING = 6
class SoundConfig:
    """声音配置"""
    BEEP_TICK = (784, 28)
    BEEP_WARNING_1 = (784, 35)
    BEEP_WARNING_2 = (988, 35)
    BEEP_MANUAL_RESET = (1000, 80)
    BEEP_ON_1 = (988, 40)
    BEEP_ON_2 = (1319, 70)
    WARNING_GAP_MS = 20
    ON_GAP_MS = 25
    WARNING_SECONDS = [30, 20, 10, 5, 4, 3, 2, 1]
    MAJOR_WARNINGS = [30, 20, 10]


class FileConfig:
    """文件配置"""
    CONFIG_FILE = Path.home() / ".bomanalite_config.json"
    STATE_FILE = Path.home() / ".bomanalite_state.json"
    ICON_FILE = "app.png"
class AboutConfig:
    """关于对话框配置"""
    # 软件信息
    APP_NAME = "BomanaLite"
    APP_NAME_CN = "战雷全真模式计时器（精简版）"
    VERSION = "1.0.0"
    AUTHOR = "猹Cheems"
    
    # 链接配置
    GITHUB_URL = "https://github.com/Thankyou-Cheems/Bomana"
    
    # 赞助链接配置
    SPONSOR_LINKS = [
        # ("显示名称", "链接URL", "图片文件名"),
        ("微信赞赏", "", "sponsor_wechat.png"),  # 空链接表示只显示图片
    ]
    
    # 赞助图片尺寸
    SPONSOR_IMAGE_WIDTH = 400


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
    GRAYPILL = "#161b22"


# ============================================================================
# 数据结构
# ============================================================================

class Phase(Enum):
    """游戏阶段"""
    IDLE = auto()
    HANGAR = auto()
    ARMING = auto()
    ALIVE = auto()
    LOSS_PENDING = auto()
    WAIT_NEXT = auto()


@dataclass
class TelemetryData:
    """遥测数据"""
    ind_ok: bool = False
    state_resp_ok: bool = False
    valid: bool = False
    type_name: str = ""
    ias_kmh: float = 0
    vy_ms: float = 0
    fuel_kg: float = 0

    @property
    def entity_like(self) -> bool:
        if not (self.ind_ok and self.state_resp_ok and self.valid and self.type_name):
            return False
        return (self.fuel_kg > 0.1) or (abs(self.ias_kmh) > 0.1)

    @property
    def is_on_ground(self) -> bool:
        return self.ias_kmh < GameConfig.LAND_SPEED_KMH and abs(self.vy_ms) < 2.0


@dataclass
class MapObjData:
    """地图对象数据"""
    ok: bool = False
    player_aircraft_present: bool = False
    obj_count: int = 0


@dataclass
class LifeState:
    """生命状态"""
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


# ============================================================================
# 工具函数
# ============================================================================

def fmt_time(sec: Optional[float]) -> str:
    if sec is None:
        return "--:--"
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"
def resource_path(rel_path: str) -> str:
    """获取资源文件路径（支持PyInstaller打包）"""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel_path)


# ============================================================================
# 配置和状态管理
# ============================================================================

class ConfigManager:
    """配置文件管理"""
    @staticmethod
    def load() -> dict:
        if FileConfig.CONFIG_FILE.exists():
            try:
                with open(FileConfig.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    @staticmethod
    def save(config: dict):
        try:
            with open(FileConfig.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except:
            pass


class StateManager:
    """计时状态管理（支持重启恢复）"""
    @staticmethod
    def save(remaining_sec: float, life_index: int):
        try:
            with open(FileConfig.STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    'remaining_sec': remaining_sec,
                    'save_timestamp': time.time(),
                    'life_index': life_index
                }, f)
        except:
            pass

    @staticmethod
    def load() -> Optional[dict]:
        if not FileConfig.STATE_FILE.exists():
            return None
        try:
            with open(FileConfig.STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            saved_remaining = data.get('remaining_sec', 0)
            save_time = data.get('save_timestamp', 0)
            elapsed = time.time() - save_time
            new_remaining = saved_remaining - elapsed
            if new_remaining < -GameConfig.CYCLE_SECONDS:
                StateManager.clear()
                return None
            if new_remaining < 0:
                new_remaining = GameConfig.CYCLE_SECONDS - abs(new_remaining)
            data['computed_remaining'] = new_remaining
            data['computed_spawn_time'] = time.time() - (GameConfig.CYCLE_SECONDS - new_remaining)
            return data
        except:
            StateManager.clear()
            return None

    @staticmethod
    def clear():
        try:
            if FileConfig.STATE_FILE.exists():
                FileConfig.STATE_FILE.unlink()
        except:
            pass


# ============================================================================
# 声音管理
# ============================================================================

class SoundManager:
    """声音管理器（Windows Beep API）"""
    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = False

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def play(self, pattern: str = "tick", freq: int = None, duration: int = None):
        if not self._enabled and pattern != "on":
            return
        if not self._lock.acquire(blocking=False):
            return
        try:
            if freq is not None and duration is not None:
                def _play():
                    try:
                        ctypes.windll.kernel32.Beep(int(freq), int(duration))
                    except:
                        pass
                    finally:
                        self._lock.release()
                threading.Thread(target=_play, daemon=True).start()
                return
            seq = self._get_sequence(pattern)
            def _play_seq():
                try:
                    for (f, ms, gap) in seq:
                        try:
                            ctypes.windll.kernel32.Beep(int(f), int(ms))
                        except:
                            pass
                        if gap:
                            time.sleep(gap / 1000.0)
                finally:
                    self._lock.release()
            threading.Thread(target=_play_seq, daemon=True).start()
        except:
            self._lock.release()

    @staticmethod
    def _get_sequence(pattern: str):
        if pattern == "on":
            return [(*SoundConfig.BEEP_ON_1, SoundConfig.ON_GAP_MS), (*SoundConfig.BEEP_ON_2, 0)]
        elif pattern == "warning":
            return [(*SoundConfig.BEEP_WARNING_1, SoundConfig.WARNING_GAP_MS), (*SoundConfig.BEEP_WARNING_2, 0)]
        else:
            return [(*SoundConfig.BEEP_TICK, 0)]


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
        except:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except:
                pass

    @classmethod
    def get_dpi_scale(cls, hwnd: int) -> float:
        try:
            dpi = cls.user32.GetDpiForWindow(hwnd)
            return (dpi / 96.0) if dpi else 1.0
        except:
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
        except:
            pass

    @classmethod
    def hide_console(cls):
        try:
            hwnd = cls.kernel32.GetConsoleWindow()
            if hwnd:
                cls.user32.ShowWindow(hwnd, 0)
        except:
            pass


# ============================================================================
# 单实例管理
# ============================================================================

_MUTEX_HANDLE = None

class SingleInstance:
    MUTEX_NAME = r"Global\BomanaLite_SingleInstance"

    @staticmethod
    def check():
        global _MUTEX_HANDLE
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            h = kernel32.CreateMutexW(None, True, SingleInstance.MUTEX_NAME)
            err = kernel32.GetLastError()
            _MUTEX_HANDLE = h
            if not h or err == 183:
                r = tk.Tk()
                r.withdraw()
                tk.messagebox.showinfo("BomanaLite", "程序已在运行")
                r.destroy()
                sys.exit(0)
        except:
            pass

    @staticmethod
    def release():
        global _MUTEX_HANDLE
        if _MUTEX_HANDLE:
            try:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_MUTEX_HANDLE))
            except:
                pass


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
        except:
            return False, None


# ============================================================================
# 游戏逻辑
# ============================================================================

class GameLogic:
    def __init__(self):
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.http = HttpJson(self.session)
        
        self.phase = Phase.IDLE
        self.current_life: Optional[LifeState] = None
        self.api_down = False
        
        self._spawn_candidate_since: Optional[float] = None
        self._missing_player_since: Optional[float] = None
        self._hangar_candidate_since: Optional[float] = None
        self._api_down_candidate_since: Optional[float] = None
        self._last_tel: Optional[TelemetryData] = None

    def _fetch_telemetry(self, budget: Budget) -> TelemetryData:
        data = TelemetryData()
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/indicators", budget)
        data.ind_ok = ok
        if ok and isinstance(j, dict):
            data.valid = bool(j.get("valid", False))
            data.type_name = str(j.get("type", "") or "").strip()
        if not data.ind_ok:
            return data
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/state", budget)
        data.state_resp_ok = ok
        if ok and isinstance(j, dict):
            data.ias_kmh = float(j.get("IAS, km/h", 0) or 0)
            data.vy_ms = float(j.get("Vy, m/s", 0) or 0)
            data.fuel_kg = float(j.get("Mfuel, kg", 0) or 0)
        return data

    def _fetch_map(self, budget: Budget) -> MapObjData:
        out = MapObjData()
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/map_obj.json", budget)
        if not ok:
            return out
        out.ok = True
        objs = j if isinstance(j, list) else j.get("objects", []) if isinstance(j, dict) else []
        out.obj_count = len(objs)
        for o in objs:
            if isinstance(o, dict) and o.get("type") == "aircraft" and o.get("icon") == "Player":
                out.player_aircraft_present = True
                break
        return out

    def tick(self):
        now = time.time()
        budget = Budget(NetworkConfig.MAX_TICK_NET_BUDGET)
        tel = self._fetch_telemetry(budget)
        mp = self._fetch_map(budget)
        api_up = bool(tel.ind_ok or tel.state_resp_ok or mp.ok)

        with self._lock:
            self._last_tel = tel
            
            # API状态
            if api_up:
                self.api_down = False
                self._api_down_candidate_since = None
            else:
                if self._api_down_candidate_since is None:
                    self._api_down_candidate_since = now
                if (now - self._api_down_candidate_since) >= GameConfig.API_DOWN_CONFIRM_SEC:
                    self.api_down = True

            if self.api_down:
                if self.phase != Phase.HANGAR:
                    self.phase = Phase.IDLE
                return

            player_present = mp.ok and mp.player_aircraft_present
            spawn_candidate = player_present and tel.entity_like

            # 机库检测
            hangar_like = (not mp.ok) or (mp.obj_count == 0)
            if hangar_like and (not player_present) and self.phase != Phase.ALIVE:
                if self._hangar_candidate_since is None:
                    self._hangar_candidate_since = now
                elif (now - self._hangar_candidate_since) >= GameConfig.HANGAR_CONFIRM_SEC:
                    self.phase = Phase.HANGAR
                    self.current_life = None
            else:
                self._hangar_candidate_since = None

            # 状态机
            if self.phase == Phase.HANGAR:
                if spawn_candidate:
                    self.phase = Phase.ARMING
                    self._spawn_candidate_since = now
                return

            if self.phase == Phase.IDLE:
                if spawn_candidate:
                    self.phase = Phase.ARMING
                    self._spawn_candidate_since = now

            elif self.phase == Phase.ARMING:
                if spawn_candidate:
                    if self._spawn_candidate_since is None:
                        self._spawn_candidate_since = now
                    if (now - self._spawn_candidate_since) >= GameConfig.SPAWN_CONFIRM_SEC:
                        next_idx = 1 if not self.current_life else (self.current_life.life_index + 1)
                        self.current_life = LifeState(spawn_time=now, life_index=next_idx)
                        self.phase = Phase.ALIVE
                        self._spawn_candidate_since = None
                        self._missing_player_since = None
                else:
                    self._spawn_candidate_since = None
                    self.phase = Phase.IDLE

            elif self.phase == Phase.ALIVE:
                if not player_present:
                    self.phase = Phase.LOSS_PENDING
                    self._missing_player_since = now
                else:
                    self._missing_player_since = None

            elif self.phase == Phase.LOSS_PENDING:
                if player_present:
                    self.phase = Phase.ALIVE
                    self._missing_player_since = None
                else:
                    if self._missing_player_since is None:
                        self._missing_player_since = now
                    if (now - self._missing_player_since) >= GameConfig.DEAD_CONFIRM_SEC:
                        self.phase = Phase.WAIT_NEXT
                        self._spawn_candidate_since = None

            elif self.phase == Phase.WAIT_NEXT:
                if spawn_candidate:
                    if self._spawn_candidate_since is None:
                        self._spawn_candidate_since = now
                    if (now - self._spawn_candidate_since) >= GameConfig.SPAWN_CONFIRM_SEC:
                        next_idx = 1 if not self.current_life else (self.current_life.life_index + 1)
                        self.current_life = LifeState(spawn_time=now, life_index=next_idx)
                        self.phase = Phase.ALIVE
                        self._spawn_candidate_since = None
                        self._missing_player_since = None
                else:
                    self._spawn_candidate_since = None

    def get_state(self):
        now = time.time()
        with self._lock:
            return {
                'phase': self.phase,
                'api_down': self.api_down,
                'life_index': self.current_life.life_index if self.current_life else None,
                'cycle': self.current_life.current_cycle(now) if self.current_life else None,
                'remaining': self.current_life.cycle_remaining(now) if self.current_life and self.phase == Phase.ALIVE else None,
                'progress': self.current_life.cycle_progress(now) if self.current_life and self.phase == Phase.ALIVE else 0.0,
            }

    def manual_reset(self):
        with self._lock:
            if self.phase == Phase.ALIVE and self.current_life:
                self.current_life.spawn_time = time.time()

    def save_state(self):
        with self._lock:
            if self.phase != Phase.ALIVE or not self.current_life:
                StateManager.clear()
                return
            remaining = self.current_life.cycle_remaining(time.time())
            StateManager.save(remaining, self.current_life.life_index)

    def restore_state(self) -> bool:
        data = StateManager.load()
        if not data:
            return False
        with self._lock:
            self.current_life = LifeState(
                spawn_time=data['computed_spawn_time'],
                life_index=data.get('life_index', 1)
            )
            self.phase = Phase.ALIVE
        return True


# ============================================================================
# 设置对话框
# ============================================================================

class SettingsDialog(tk.Toplevel):
    """设置对话框"""
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("⚙️ 设置")
        self.resizable(False, False)
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        
        self._build_ui()
        self._center()
    
    def _build_ui(self):
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=20, pady=15, fill="both", expand=True)
        
        # 透明度
        tk.Label(main, text="窗口透明度:", bg=Theme.BG, fg=Theme.TEXT,
                font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", pady=8)
        
        self.alpha_var = tk.IntVar(value=UIConfig.WINDOW_ALPHA)
        self.alpha_scale = tk.Scale(
            main, from_=80, to=255, orient="horizontal", length=200,
            variable=self.alpha_var, bg=Theme.BG, fg=Theme.TEXT,
            highlightthickness=0, troughcolor=Theme.BORDER,
            activebackground=Theme.BLUE, command=self._on_alpha_change
        )
        self.alpha_scale.grid(row=0, column=1, padx=(10, 0), pady=8)
        
        self.alpha_lbl = tk.Label(main, text=f"{UIConfig.WINDOW_ALPHA}", 
                                  bg=Theme.BG, fg=Theme.TEXT_DIM, width=4,
                                  font=("Segoe UI", 10))
        self.alpha_lbl.grid(row=0, column=2, padx=(5, 0))
        
        # 缩放
        tk.Label(main, text="UI缩放:", bg=Theme.BG, fg=Theme.TEXT,
                font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=8)
        
        self.scale_var = tk.DoubleVar(value=UIConfig.UI_SCALE_MULT)
        self.scale_scale = tk.Scale(
            main, from_=0.6, to=1.5, resolution=0.05, orient="horizontal", length=200,
            variable=self.scale_var, bg=Theme.BG, fg=Theme.TEXT,
            highlightthickness=0, troughcolor=Theme.BORDER,
            activebackground=Theme.BLUE, command=self._on_scale_change
        )
        self.scale_scale.grid(row=1, column=1, padx=(10, 0), pady=8)
        
        self.scale_lbl = tk.Label(main, text=f"{UIConfig.UI_SCALE_MULT:.2f}x", 
                                  bg=Theme.BG, fg=Theme.TEXT_DIM, width=5,
                                  font=("Segoe UI", 10))
        self.scale_lbl.grid(row=1, column=2, padx=(5, 0))
        
        # 缩放提示
        tk.Label(main, text="* 缩放修改需要重启生效", bg=Theme.BG, fg=Theme.TEXT_MUTED,
                font=("Segoe UI", 8)).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 10))
        
        # 按钮
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.grid(row=3, column=0, columnspan=3, pady=(10, 0))
        
        tk.Button(btn_frame, text="保存", command=self._save,
                 bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=25, pady=6,
                 font=("Segoe UI", 10)).pack(side="left", padx=5)
        
        tk.Button(btn_frame, text="取消", command=self.destroy,
                 bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=25, pady=6,
                 font=("Segoe UI", 10)).pack(side="left", padx=5)
    
    def _on_alpha_change(self, val):
        """透明度实时预览"""
        alpha = int(float(val))
        self.alpha_lbl.config(text=f"{alpha}")
        Win32.setup_window(self.app.hwnd, click_through=self.app._locked, alpha=alpha)
    
    def _on_scale_change(self, val):
        """缩放值显示"""
        self.scale_lbl.config(text=f"{float(val):.2f}x")
    
    def _save(self):
        """保存设置"""
        UIConfig.WINDOW_ALPHA = self.alpha_var.get()
        UIConfig.UI_SCALE_MULT = self.scale_var.get()
        Win32.setup_window(self.app.hwnd, click_through=self.app._locked, alpha=UIConfig.WINDOW_ALPHA)
        self.app._save_config()
        self.destroy()
    
    def _center(self):
        """居中显示"""
        self.update_idletasks()
        x = self.master.winfo_x() + (self.master.winfo_width() - self.winfo_width()) // 2
        y = self.master.winfo_y() + (self.master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
class AboutDialog(tk.Toplevel):
    """关于对话框"""
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("关于 BomanaLite")
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._images = []
        
        self._build_ui()
        
        # 让窗口自适应内容大小
        self.update_idletasks()
        
        # 获取内容实际需要的尺寸
        req_width = self.winfo_reqwidth()
        req_height = self.winfo_reqheight()
        
        # 设置最小尺寸
        min_width = max(500, req_width)
        min_height = max(600, req_height)
        
        # 限制最大尺寸不超过屏幕
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        final_width = min(min_width, screen_w - 100)
        final_height = min(min_height, screen_h - 100)
        
        self.geometry(f"{final_width}x{final_height}")
        self.minsize(400, 500)
        self.resizable(True, True)
        
        self._center_on_parent(parent)
    
    def _build_ui(self):
        # 创建可滚动的画布
        canvas = tk.Canvas(self, bg=Theme.BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        
        main = tk.Frame(canvas, bg=Theme.BG)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        canvas_frame = canvas.create_window((0, 0), window=main, anchor="nw")
        
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_frame, width=event.width)
        
        def configure_canvas(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        canvas.bind("<Configure>", configure_scroll)
        main.bind("<Configure>", configure_canvas)
        
        # 鼠标滚轮支持
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # 内容区域
        content = tk.Frame(main, bg=Theme.BG)
        content.pack(fill="both", expand=True, padx=30, pady=25)
        
        # === 软件标题 ===
        title_frame = tk.Frame(content, bg=Theme.BG)
        title_frame.pack(fill="x", pady=(0, 15))
        
        try:
            icon_path = resource_path(FileConfig.ICON_FILE)
            if HAS_TRAY:
                from PIL import Image, ImageTk
                img = Image.open(icon_path).convert("RGBA")
                img = img.resize((64, 64), Image.Resampling.LANCZOS)
                self._app_icon = ImageTk.PhotoImage(img)
                icon_lbl = tk.Label(title_frame, image=self._app_icon, bg=Theme.BG)
                icon_lbl.pack(side="left", padx=(0, 15))
        except Exception:
            pass
        
        title_text_frame = tk.Frame(title_frame, bg=Theme.BG)
        title_text_frame.pack(side="left", fill="both", expand=True)
        
        tk.Label(
            title_text_frame,
            text=f"{AboutConfig.APP_NAME} v{AboutConfig.VERSION}",
            font=("Segoe UI", 18, "bold"),
            fg=Theme.TEXT, bg=Theme.BG, anchor="w"
        ).pack(anchor="w")
        
        tk.Label(
            title_text_frame,
            text=AboutConfig.APP_NAME_CN,
            font=("Segoe UI", 11),
            fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="w"
        ).pack(anchor="w", pady=(5, 0))
        
        # === 分隔线 ===
        tk.Frame(content, bg=Theme.BORDER, height=1).pack(fill="x", pady=15)
        
        # === 项目说明 ===
        description = """本软件是战雷全真模式计时器的精简版本，
仅保留核心15分钟自动计时功能。

精简版特性：
• 自动检测出生/死亡/着陆状态
• 透明悬浮窗口，可拖动
• 最小化资源占用
• 支持状态保存和恢复

本软件完全开源免费，欢迎贡献代码！"""
        
        tk.Label(
            content, text=description,
            font=("Segoe UI", 10),
            fg=Theme.TEXT_DIM, bg=Theme.BG,
            justify="left", anchor="w"
        ).pack(anchor="w")
        
        # === GitHub 链接 ===
        if AboutConfig.GITHUB_URL:
            link_frame = tk.Frame(content, bg=Theme.BG)
            link_frame.pack(fill="x", pady=(15, 0))
            
            tk.Label(
                link_frame, text="📦 项目主页：",
                font=("Segoe UI", 10),
                fg=Theme.TEXT_DIM, bg=Theme.BG
            ).pack(side="left")
            
            github_btn = tk.Label(
                link_frame, text=AboutConfig.GITHUB_URL,
                font=("Segoe UI", 10, "underline"),
                fg=Theme.BLUE, bg=Theme.BG, cursor="hand2"
            )
            github_btn.pack(side="left")
            github_btn.bind("<Button-1>", lambda e: self._open_url(AboutConfig.GITHUB_URL))
        
        # === 分隔线 ===
        tk.Frame(content, bg=Theme.BORDER, height=1).pack(fill="x", pady=15)
        
        # === 赞助区域 ===
        tk.Label(
            content, text="❤️ 支持作者",
            font=("Segoe UI", 13, "bold"),
            fg=Theme.TEXT, bg=Theme.BG, anchor="w"
        ).pack(anchor="w", pady=(0, 10))
        
        tk.Label(
            content, text="如果这个工具对你有帮助，欢迎请作者喝杯咖啡~",
            font=("Segoe UI", 10),
            fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="w"
        ).pack(anchor="w", pady=(0, 15))
        
        # 赞助图片/链接区域
        sponsor_frame = tk.Frame(content, bg=Theme.BG)
        sponsor_frame.pack(fill="x", pady=(0, 15))
        
        for name, url, img_file in AboutConfig.SPONSOR_LINKS:
            self._add_sponsor_item(sponsor_frame, name, url, img_file)
        
        # === 分隔线 ===
        tk.Frame(content, bg=Theme.BORDER, height=1).pack(fill="x", pady=15)
        
        # === 版权声明 ===
        copyright_text = f"""作者：{AboutConfig.AUTHOR}

MIT License
Copyright © 2024-2026 {AboutConfig.AUTHOR}

Gaijin Entertainment AG及其子公司拥有《战争雷霆》及相关商标的所有权
本软件与Gaijin Entertainment AG无任何关联
注意！滥用本软件可能违反Gaijin用户守则
使用本软件的风险由用户自行承担"""
        
        tk.Label(
            content, text=copyright_text,
            font=("Segoe UI", 9),
            fg=Theme.TEXT_MUTED, bg=Theme.BG,
            justify="left", anchor="w"
        ).pack(anchor="w", pady=(0, 15))
        
        # === 关闭按钮 ===
        tk.Button(
            content, text="关闭", command=self._close,
            font=("Segoe UI", 10),
            bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=40, pady=8
        ).pack(pady=(10, 0))
    
    def _add_sponsor_item(self, parent, name: str, url: str, img_file: str):
        item_frame = tk.Frame(parent, bg=Theme.BG)
        item_frame.pack(side="left", padx=(0, 20), pady=10)
        
        img_loaded = False
        if img_file and HAS_TRAY:
            try:
                from PIL import Image, ImageTk
                img_path = resource_path(img_file)
                img = Image.open(img_path).convert("RGBA")
                
                target_width = AboutConfig.SPONSOR_IMAGE_WIDTH
                ratio = target_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._images.append(photo)
                
                img_lbl = tk.Label(item_frame, image=photo, bg=Theme.BG, cursor="hand2" if url else "")
                img_lbl.pack()
                if url:
                    img_lbl.bind("<Button-1>", lambda e, u=url: self._open_url(u))
                
                tk.Label(
                    item_frame, text=name,
                    font=("Segoe UI", 9),
                    fg=Theme.TEXT_DIM, bg=Theme.BG
                ).pack(pady=(5, 0))
                img_loaded = True
            except Exception:
                pass
        
        if not img_loaded:
            btn = tk.Button(
                item_frame, text=f"💝 {name}",
                font=("Segoe UI", 10),
                bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=10,
                cursor="hand2" if url else ""
            )
            btn.pack()
            if url:
                btn.config(command=lambda u=url: self._open_url(u))
    
    def _open_url(self, url: str):
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass
    
    def _close(self):
        try:
            self.unbind_all("<MouseWheel>")
        except:
            pass
        self.destroy()
    
    def _center_on_parent(self, parent):
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        x = max(0, x)
        y = max(0, y)
        self.geometry(f"+{x}+{y}")

# ============================================================================
# 主应用
# ============================================================================

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.game = GameLogic()
        self.sound = SoundManager()
        self._stop = False
        self._locked = True
        self._drag = {"x": 0, "y": 0}
        self._last_beep_sec = -1
        self._manual_pos = None

        self._load_config()
        self._init_window()
        self._init_ui()
        self._init_bindings()
        self._finalize()

        # 恢复状态
        self._restored = self.game.restore_state()

        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._update_ui()

        if HAS_TRAY:
            self._init_tray()

    def _load_config(self):
        config = ConfigManager.load()
        self.sound.set_enabled(config.get('beep_enabled', False))
        UIConfig.WINDOW_ALPHA = config.get('alpha', 210)
        UIConfig.UI_SCALE_MULT = config.get('scale', 1.0)
        pos = config.get('window_pos')
        if pos and isinstance(pos, list) and len(pos) == 2:
            self._manual_pos = tuple(pos)

    def _save_config(self):
        config = {
            'beep_enabled': self.sound.is_enabled(),
            'alpha': UIConfig.WINDOW_ALPHA,
            'scale': UIConfig.UI_SCALE_MULT,
            'window_pos': list(self._manual_pos) if self._manual_pos else None
        }
        ConfigManager.save(config)

    def _init_window(self):
        self.root.title("BomanaLite")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=Theme.BG)
        self.root.geometry("10x10+0+0")
        self.root.update_idletasks()
        self.hwnd = int(self.root.winfo_id())
        self.scale = Win32.get_dpi_scale(self.hwnd) * UIConfig.UI_SCALE_MULT

    def _init_ui(self):
        s = self.scale
        self.main = tk.Frame(self.root, bg=Theme.BG)
        self.main.pack(fill="both", expand=True, padx=int(14*s), pady=int(10*s))

        # 计时器
        font_timer = ("Segoe UI", int(44*s), "bold")
        self.timer_lbl = tk.Label(self.main, text="--:--", font=font_timer, fg=Theme.TEXT_MUTED, bg=Theme.BG)
        self.timer_lbl.pack(anchor="w")

        # 信息行
        row = tk.Frame(self.main, bg=Theme.BG)
        row.pack(fill="x", pady=(int(4*s), int(6*s)))
        
        font_pill = ("Segoe UI", int(10*s), "bold")
        self.badge = tk.Label(row, text="  IDLE  ", font=font_pill, fg=Theme.TEXT, bg=Theme.GRAYPILL)
        self.badge.pack(side="left")
        
        font_info = ("Segoe UI", int(11*s))
        self.info_lbl = tk.Label(row, text="等待中", font=font_info, fg=Theme.TEXT_DIM, bg=Theme.BG)
        self.info_lbl.pack(side="right")

        # 进度条
        bar_frame = tk.Frame(self.main, bg=Theme.BG, height=int(6*s))
        bar_frame.pack(fill="x", pady=(0, int(6*s)))
        bar_frame.pack_propagate(False)
        self.bar_bg = tk.Frame(bar_frame, bg=Theme.BORDER, height=int(3*s))
        self.bar_bg.place(relx=0, rely=0.5, relwidth=1, anchor="w")
        self.bar_fill = tk.Frame(self.bar_bg, bg=Theme.BLUE, height=int(3*s))
        self.bar_fill.place(relx=0, rely=0, relwidth=0, relheight=1)

        # 提示
        font_hint = ("Segoe UI", int(8*s))
        sound = "🔊开" if self.sound.is_enabled() else "🔇关"
        hint_text = f"F7重置 │ F8解锁 │ F10声音({sound}) │ 托盘退出"
        self.hint_lbl = tk.Label(self.main, text=hint_text, font=font_hint, fg=Theme.TEXT_MUTED, bg=Theme.BG)
        self.hint_lbl.pack(fill="x")

    def _init_bindings(self):
        self.root.bind("<F7>", lambda e: self._manual_reset())
        self.root.bind("<F8>", lambda e: self._toggle_lock())
        self.root.bind("<F10>", lambda e: self._toggle_beep())
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)
        self.root.bind("<Control-MouseWheel>", self._adjust_alpha)
        self.root.bind("<Shift-MouseWheel>", self._adjust_scale)

    def _init_tray(self):
        """初始化系统托盘"""
        app = self

        def get_icon():
            try:
                return Image.open(resource_path(FileConfig.ICON_FILE)).convert("RGBA")
            except:
                return Image.new('RGBA', (64, 64), Theme.BLUE)

        def do_reset(icon, item):
            app.root.after(0, app._manual_reset)

        def do_lock(icon, item):
            app.root.after(0, app._toggle_lock)

        def do_beep(icon, item):
            app.root.after(0, app._toggle_beep)

        def do_settings(icon, item):
            app.root.after(0, app._show_settings)

        def do_quit(icon, item):
            app.root.after(0, app._quit)

        def is_locked(item):
            return app._locked

        def is_beep_on(item):
            return app.sound.is_enabled()

        def do_about(icon, item):
            app.root.after(0, app._show_about)

        menu = pystray.Menu(
            pystray.MenuItem("🔄 重置计时器 (F7)", do_reset),
            pystray.MenuItem("🔓 锁定/解锁 (F8)", do_lock, checked=is_locked),
            pystray.MenuItem("🔊 声音 (F10)", do_beep, checked=is_beep_on),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙️ 设置", do_settings),
            pystray.MenuItem("ℹ️ 关于", do_about),
            pystray.MenuItem("❌ 退出", do_quit),
        )

        self.tray = pystray.Icon("BomanaLite", get_icon(), "BomanaLite", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _show_settings(self):
        """显示设置对话框"""
        SettingsDialog(self.root, self)
    def _show_about(self):
        """显示关于对话框"""
        AboutDialog(self.root, self)

    def _toggle_lock(self):
        self._locked = not self._locked
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=UIConfig.WINDOW_ALPHA)
        self._update_hint()

    def _toggle_beep(self):
        enabled = not self.sound.is_enabled()
        self.sound.set_enabled(enabled)
        self._update_hint()
        self._save_config()
        if enabled:
            self.sound.play(pattern="on")

    def _manual_reset(self):
        self.game.manual_reset()
        self.sound.play(*SoundConfig.BEEP_MANUAL_RESET)

    def _update_hint(self):
        sound = "🔊开" if self.sound.is_enabled() else "🔇关"
        if self._locked:
            text = f"F7重置 │ F8解锁 │ F10声音({sound}) │ 托盘退出"
        else:
            text = f"拖动移动 │ F8锁定 │ F10声音({sound}) │ Ctrl/Shift+滚轮调节"
        self.hint_lbl.config(text=text)
    def _adjust_alpha(self, event):
        """Ctrl+滚轮调整透明度"""
        if self._locked:
            return
        delta = 15 if event.delta > 0 else -15
        UIConfig.WINDOW_ALPHA = max(80, min(255, UIConfig.WINDOW_ALPHA + delta))
        Win32.setup_window(self.hwnd, click_through=False, alpha=UIConfig.WINDOW_ALPHA)
        self.hint_lbl.config(text=f"透明度: {UIConfig.WINDOW_ALPHA}")
        self._save_config()
        self.root.after(1500, self._update_hint)

    def _adjust_scale(self, event):
        """Shift+滚轮调整缩放"""
        if self._locked:
            return
        delta = 0.1 if event.delta > 0 else -0.1
        UIConfig.UI_SCALE_MULT = max(0.6, min(1.5, UIConfig.UI_SCALE_MULT + delta))
        self._save_config()
        self.hint_lbl.config(text=f"缩放: {UIConfig.UI_SCALE_MULT:.1f}x (重启生效)")
        self.root.after(1500, self._update_hint)

    def _finalize(self):
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        pad = int(UIConfig.WINDOW_PADDING * self.scale)
        self.W = req_w + pad
        self.H = req_h + pad
        sw, sh = Win32.screen_size()
        m = int(UIConfig.WINDOW_MARGIN * self.scale)
        if self._manual_pos:
            x, y = self._manual_pos
        else:
            x = sw - self.W - m
            y = m
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.root.update_idletasks()
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=UIConfig.WINDOW_ALPHA)

    def _start_drag(self, e):
        if self._locked:
            return
        self._drag["x"] = e.x
        self._drag["y"] = e.y

    def _do_drag(self, e):
        if self._locked:
            return
        x = self.root.winfo_pointerx() - self._drag["x"]
        y = self.root.winfo_pointery() - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, e=None):
        if self._locked:
            return
        try:
            x = int(self.root.winfo_x())
            y = int(self.root.winfo_y())
            self._manual_pos = (x, y)
            self._save_config()
        except:
            pass

    def _quit(self):
        self._stop = True
        self.game.save_state()
        self._save_config()
        if HAS_TRAY and hasattr(self, 'tray'):
            try:
                self.tray.stop()
            except:
                pass
        SingleInstance.release()
        self.root.destroy()

    def _poll_loop(self):
        while not self._stop:
            start = time.monotonic()
            self.game.tick()
            state = self.game.get_state()
            interval = NetworkConfig.BACKOFF_MAX if state['api_down'] else NetworkConfig.POLL_INTERVAL
            elapsed = time.monotonic() - start
            time.sleep(max(0.0, interval - elapsed))

    def _update_ui(self):
        if self._stop:
            return

        state = self.game.get_state()

        # 计时器
        self.timer_lbl.config(text=fmt_time(state['remaining']))
        if state['remaining'] is None:
            self.timer_lbl.config(fg=Theme.TEXT_MUTED)
            self.bar_fill.place(relwidth=0)
        else:
            r = state['remaining']
            color = Theme.RED if r <= 10 else Theme.YELLOW if r <= GameConfig.FINAL_WARNING_SEC else Theme.TEXT
            bar_c = Theme.RED if r <= 10 else Theme.YELLOW if r <= GameConfig.FINAL_WARNING_SEC else Theme.BLUE
            self.timer_lbl.config(fg=color)
            self.bar_fill.place(relwidth=state['progress'])
            self.bar_fill.config(bg=bar_c)

        # 徽章和信息
        phase = state['phase']
        if state['api_down']:
            badge_text, badge_bg, info = "❌8111", Theme.RED, "未检测到8111"
        elif phase == Phase.ALIVE:
            badge_text, badge_bg = "战斗中", Theme.GREEN
            info = f"第{state['life_index']}次复活 · 第{state['cycle']}轮"
        elif phase == Phase.WAIT_NEXT:
            badge_text, badge_bg, info = "等待复活", Theme.YELLOW, "等待下次复活"
        elif phase == Phase.HANGAR:
            badge_text, badge_bg, info = "🏠机库", Theme.GRAYPILL, "等待游戏开始"
        elif phase == Phase.ARMING:
            badge_text, badge_bg, info = "部署中", Theme.BLUE, "正在部署..."
        else:
            badge_text, badge_bg, info = "IDLE", Theme.GRAYPILL, "等待中"

        self.badge.config(text=f"  {badge_text}  ", bg=badge_bg)
        self.info_lbl.config(text=info)

        # 警告音
        if state['remaining'] is not None:
            remain_int = int(state['remaining'])
            if state['remaining'] <= GameConfig.FINAL_WARNING_SEC:
                if remain_int in SoundConfig.WARNING_SECONDS and remain_int != self._last_beep_sec:
                    pattern = "warning" if remain_int in SoundConfig.MAJOR_WARNINGS else "tick"
                    self.sound.play(pattern=pattern)
                    self._last_beep_sec = remain_int
            else:
                self._last_beep_sec = -1

        self.root.after(UIConfig.UI_REFRESH_MS, self._update_ui)


def main():
    SingleInstance.check()
    Win32.enable_dpi()
    Win32.hide_console()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
