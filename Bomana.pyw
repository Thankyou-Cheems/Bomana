import sys
import time
import ctypes
import threading
import socket
import math
import requests
import tkinter as tk
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple, List, Any

# =================================================================
# 1. 核心配置与主题
# =================================================================
class AppConfig:
    """应用程序静态配置"""
    API_BASE = "http://127.0.0.1:8111"
    LOCK_PORT = 41777
    
    CYCLE_SECONDS = 900
    WARNING_THRESHOLD = 30
    
    POLL_INTERVAL = 0.25
    UI_TICK_MS = 50
    
    # 判定逻辑阈值
    LANDING_SPEED_MAX = 40  # km/h
    LANDING_ALT_MAX = 5    # m
    CONFIRM_DELAY = 1.2    # 状态确认防抖 (秒)

class AppTheme:
    """UI 视觉规范"""
    BG = "#0A0E13"
    BORDER = "#30363D"
    TEXT_MAIN = "#E6EDF3"
    TEXT_DIM = "#8B949E"
    TEXT_MUTED = "#484F58"
    
    STATUS_COLORS = {
        "ACTIVE": "#58A6FF",
        "SUCCESS": "#3FB950",
        "WARNING": "#D29922",
        "DANGER": "#F85149"
    }

# =================================================================
# 2. 系统能力封装 (Win32 & Network)
# =================================================================
class SystemUtils:
    @staticmethod
    def initialize_high_dpi():
        """启用 Windows DPI 感知"""
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass

    @staticmethod
    def get_window_scale(hwnd: int) -> float:
        try:
            dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
            return dpi / 96.0 if dpi else 1.0
        except Exception:
            return 1.0

    @staticmethod
    def configure_overlay(hwnd: int, clickthrough: bool):
        """配置窗口扩展样式"""
        styles = {
            "GWL_EXSTYLE": -20,
            "WS_EX_LAYERED": 0x00080000,
            "WS_EX_TRANSPARENT": 0x00000020,
            "WS_EX_TOPMOST": 0x00000008,
            "WS_EX_TOOLWINDOW": 0x00000080
        }
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, styles["GWL_EXSTYLE"])
        style |= (styles["WS_EX_LAYERED"] | styles["WS_EX_TOPMOST"] | styles["WS_EX_TOOLWINDOW"])
        
        if clickthrough:
            style |= styles["WS_EX_TRANSPARENT"]
        else:
            style &= ~styles["WS_EX_TRANSPARENT"]
            
        user32.SetWindowLongW(hwnd, styles["GWL_EXSTYLE"], style)
        user32.SetLayeredWindowAttributes(hwnd, 0, 245, 0x2)

    @staticmethod
    def play_notification_sound(freq=850, duration=55):
        try:
            ctypes.windll.kernel32.Beep(freq, duration)
        except Exception:
            pass

# =================================================================
# 3. 游戏数据抓取与逻辑处理
# =================================================================
@dataclass
class BattleSnapshot:
    """单次轮询的游戏状态快照"""
    valid: bool = False
    player_present: bool = False
    ias: float = 0.0
    alt: float = 0.0
    fuel: float = 0.0
    aircraft_name: str = ""

class GameStateEngine:
    """处理核心状态机逻辑"""
    class Phase(Enum):
        IDLE = auto()       # 未在战斗或未生成
        ARMING = auto()     # 检测到实体，等待确认
        ALIVE = auto()      # 战斗存活中
        WAIT_NEXT = auto()  # 击落或跳伞，等待下次生成

    def __init__(self):
        self.session = requests.Session()
        self.phase = self.Phase.IDLE
        self.current_life_start = 0.0
        self.life_count = 0
        self.landed_confirmed = False
        self._last_snapshot = BattleSnapshot()

    def update(self) -> "GameStateEngine":
        snapshot = self._fetch_snapshot()
        self._last_snapshot = snapshot
        now = time.time()

        # 核心逻辑：基于实体存在判断生命周期
        if self.phase == self.Phase.IDLE:
            if snapshot.player_present:
                self.phase = self.Phase.ARMING
                self._state_timer = now
        
        elif self.phase == self.Phase.ARMING:
            if snapshot.player_present and (now - self._state_timer >= AppConfig.CONFIRM_DELAY):
                self._start_new_life(now)
            elif not snapshot.player_present:
                self.phase = self.Phase.IDLE

        elif self.phase == self.Phase.ALIVE:
            if not snapshot.player_present:
                self.phase = self.Phase.WAIT_NEXT
                self._state_timer = now
            else:
                self._check_landing_status(snapshot, now)

        elif self.phase == self.Phase.WAIT_NEXT:
            if snapshot.player_present:
                self._start_new_life(now)
        
        return self

    def _fetch_snapshot(self) -> BattleSnapshot:
        shot = BattleSnapshot()
        try:
            # 1. 检查物理实体
            map_data = self.session.get(f"{AppConfig.API_BASE}/map_obj.json", timeout=0.3).json()
            objs = map_data if isinstance(map_data, list) else map_data.get("objects", [])
            shot.player_present = any(o.get("icon") == "Player" for o in objs)
            
            # 2. 检查遥测数据
            ind = self.session.get(f"{AppConfig.API_BASE}/indicators", timeout=0.3).json()
            if ind.get("valid"):
                shot.valid = True
                shot.aircraft_name = ind.get("type", "Unknown")
                
            state = self.session.get(f"{AppConfig.API_BASE}/state", timeout=0.3).json()
            shot.ias = state.get("IAS, km/h", 0)
            shot.alt = state.get("H, m", 0)
            shot.fuel = state.get("Mfuel, kg", 0)
        except Exception:
            shot.valid = False
        return shot

    def _start_new_life(self, now: float):
        self.phase = self.Phase.ALIVE
        self.current_life_start = now
        self.life_count += 1
        self.landed_confirmed = False

    def _check_landing_status(self, shot: BattleSnapshot, now: float):
        if shot.ias < AppConfig.LANDING_SPEED_MAX and shot.alt < AppConfig.LANDING_ALT_MAX:
            self.landed_confirmed = True

    def get_timer_info(self, now: float):
        if self.phase != self.Phase.ALIVE: return 0, 0, 0.0
        elapsed = now - self.current_life_start
        remaining = AppConfig.CYCLE_SECONDS - (elapsed % AppConfig.CYCLE_SECONDS)
        cycle_num = int(elapsed // AppConfig.CYCLE_SECONDS) + 1
        progress = (elapsed % AppConfig.CYCLE_SECONDS) / AppConfig.CYCLE_SECONDS
        return int(remaining), cycle_num, progress

# =================================================================
# 4. UI 表现层
# =================================================================
class TimerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.engine = GameStateEngine()
        self.is_locked = True
        self.enable_sound = False
        self._last_beep_time = 0

        self._init_window()
        self._build_ui()
        self._bind_controls()
        
        threading.Thread(target=self._logic_loop, daemon=True).start()
        self._ui_tick()

    def _init_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=AppTheme.BG)
        
        SystemUtils.initialize_high_dpi()
        self.scale = SystemUtils.get_window_scale(self.root.winfo_id())
        
        # 初始布局位置
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"+{sw - 400}+{100}")

    def _build_ui(self):
        s = self.scale
        container = tk.Frame(self.root, bg=AppTheme.BG, padx=int(18*s), pady=int(12*s))
        container.pack()

        # 头部：时间与周期
        header = tk.Frame(container, bg=AppTheme.BG)
        header.pack(fill="x")
        
        self.ui_timer = tk.Label(header, text="--:--", font=("Segoe UI", int(38*s), "bold"),
                                 fg=AppTheme.TEXT_MUTED, bg=AppTheme.BG)
        self.ui_timer.pack(side="left")
        
        self.ui_cycle = tk.Label(header, text="", font=("Segoe UI", int(12*s)),
                                 fg=AppTheme.STATUS_COLORS["ACTIVE"], bg=AppTheme.BG)
        self.ui_cycle.pack(side="right", pady=(int(10*s), 0))

        # 进度条
        bar_container = tk.Frame(container, bg=AppTheme.BORDER, height=int(4*s))
        bar_container.pack(fill="x", pady=int(10*s))
        bar_container.pack_propagate(False)
        self.ui_progress = tk.Frame(bar_container, bg=AppTheme.STATUS_COLORS["ACTIVE"], width=0)
        self.ui_progress.place(relx=0, rely=0, relheight=1)

        # 状态栏
        footer = tk.Frame(container, bg=AppTheme.BG)
        footer.pack(fill="x")
        self.ui_status = tk.Label(footer, text="WAITING", font=("Segoe UI", int(11*s)),
                                  fg=AppTheme.TEXT_MUTED, bg=AppTheme.BG)
        self.ui_status.pack(side="left")

        self.ui_landing_dot = tk.Label(footer, text="● LANDED", font=("Segoe UI", int(10*s)),
                                       fg=AppTheme.TEXT_MUTED, bg=AppTheme.BG)
        self.ui_landing_dot.pack(side="right")

    def _logic_loop(self):
        while True:
            self.engine.update()
            time.sleep(AppConfig.POLL_INTERVAL)

    def _ui_tick(self):
        now = time.time()
        rem, cycle, prog = self.engine.get_timer_info(now)
        
        if self.engine.phase == GameStateEngine.Phase.ALIVE:
            # 更新时间文本
            m, s = divmod(rem, 60)
            self.ui_timer.config(text=f"{m:02d}:{s:02d}", 
                                 fg=AppTheme.STATUS_COLORS["DANGER"] if rem < 10 else 
                                    AppTheme.STATUS_COLORS["WARNING"] if rem < AppConfig.WARNING_THRESHOLD else 
                                    AppTheme.TEXT_MAIN)
            
            # 更新进度条与状态
            self.ui_progress.place(relwidth=prog)
            self.ui_cycle.config(text=f"CYCLE {cycle}")
            self.ui_status.config(text=f"LIFE {self.engine.life_count}", fg=AppTheme.TEXT_MAIN)
            self.ui_landing_dot.config(fg=AppTheme.STATUS_COLORS["SUCCESS"] if self.engine.landed_confirmed else AppTheme.TEXT_MUTED)
            
            # 声音提醒逻辑
            if self.enable_sound and rem in [30, 10, 5, 3, 2, 1] and rem != self._last_beep_time:
                SystemUtils.play_notification_sound()
                self._last_beep_time = rem
        else:
            self._reset_ui_display()

        self.root.after(AppConfig.UI_TICK_MS, self._ui_tick)

    def _reset_ui_display(self):
        self.ui_timer.config(text="--:--", fg=AppTheme.TEXT_MUTED)
        self.ui_progress.place(relwidth=0)
        self.ui_status.config(text=self.engine.phase.name)
        self.ui_landing_dot.config(fg=AppTheme.TEXT_MUTED)

    def _bind_controls(self):
        self.root.bind("<F8>", self._toggle_lock)
        self.root.bind("<F10>", self._toggle_sound)
        # 点击穿透初始化
        self.root.after(100, lambda: SystemUtils.configure_overlay(self.root.winfo_id(), True))

    def _toggle_lock(self, e=None):
        self.is_locked = not self.is_locked
        SystemUtils.configure_overlay(self.root.winfo_id(), self.is_locked)

    def _toggle_sound(self, e=None):
        self.enable_sound = not self.enable_sound
        SystemUtils.play_notification_sound(freq=1000 if self.enable_sound else 600)

if __name__ == "__main__":
    # 单实例检测逻辑
    try:
        lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_sock.bind(("127.0.0.1", AppConfig.LOCK_PORT))
    except socket.error:
        sys.exit(0)

    root = tk.Tk()
    app = TimerApp(root)
    root.mainloop()
