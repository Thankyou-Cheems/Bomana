import time
import threading
import ctypes
import math
import requests
import tkinter as tk
from typing import Tuple, Optional

# =================================================================
# 1. 基础配置与视觉规范
# =================================================================
CONFIG = {
    "GAME_API_BASE": "http://127.0.0.1:8111",
    "POLL_INTERVAL": 0.5,
    "UI_UPDATE_MS": 50,
    "CYCLE_DURATION": 900,  # 15分钟收益周期
    "WARNING_LEAD_TIME": 30,
    "THEME": {
        "BG_DARK": "#0F141A",
        "BG_LIGHT": "#101823",
        "TEXT_MAIN": "#EDEDED",
        "TEXT_DIM": "#A8B0B8",
        "ACCENT": "#EDEDED",
        "BAR_BG": "#1E2A36",
        "STROKE": "#263242"
    }
}

# =================================================================
# 2. Win32 系统交互工具
# =================================================================
class Win32Utils:
    @staticmethod
    def set_overlay_style(hwnd: int, clickthrough: bool, alpha: int = 235):
        """配置窗口扩展样式：点击穿透、置顶、透明度"""
        gwl_exstyle = -20
        ws_ex_layered = 0x00080000
        ws_ex_transparent = 0x00000020
        ws_ex_topmost = 0x00000008
        lwa_alpha = 0x00000002

        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, gwl_exstyle)
        
        # 始终保持 Layered 和 Topmost 样式
        style |= (ws_ex_layered | ws_ex_topmost)
        
        if clickthrough:
            style |= ws_ex_transparent
        else:
            style &= ~ws_ex_transparent
            
        user32.SetWindowLongW(hwnd, gwl_exstyle, style)
        user32.SetLayeredWindowAttributes(hwnd, 0, alpha, lwa_alpha)

    @staticmethod
    def get_screen_size() -> Tuple[int, int]:
        return (ctypes.windll.user32.GetSystemMetrics(0), 
                ctypes.windll.user32.GetSystemMetrics(1))

    @staticmethod
    def hide_console():
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)

# =================================================================
# 3. UI 核心类
# =================================================================
class IncomeTimerOverlay:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._setup_window()
        self._init_state()
        self._build_interface()
        
        # 启动后台轮询
        self.session = requests.Session()
        threading.Thread(target=self._data_polling_worker, daemon=True).start()
        self._ui_tick()

    def _setup_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # 设置绿色为透明穿透色
        self.trans_key = "#00FF00"
        self.root.configure(bg=self.trans_key)
        self.root.wm_attributes("-transparentcolor", self.trans_key)

        sw, sh = Win32Utils.get_screen_size()
        # 针对不同分辨率计算缩放因子 (1080p 为基准)
        self.scale = max(0.8, min(1.6, ((sw/1920) + (sh/1080)) / 2.0))
        
        self.w, self.h = int(340 * self.scale), int(160 * self.scale)
        self._apply_layout(corner=1) # 默认右上角

    def _init_state(self):
        self.in_battle = False
        self.battle_start_time = None
        self.is_clickthrough = True
        self.alerts_on = True

    def _build_interface(self):
        self.canvas = tk.Canvas(
            self.root, width=self.w, height=self.h,
            highlightthickness=0, bd=0, bg=self.trans_key
        )
        self.canvas.pack()
        
        # 静态背景绘制 (基于比例计算)
        s = self.scale
        colors = CONFIG["THEME"]
        pad, gap = int(12 * s), int(10 * s)
        lw = int(self.w * 0.58)
        th = int(self.h * 0.58)

        # 区域定义: [x1, y1, x2, y2]
        self.rect_timer = (pad, pad, pad + lw, pad + th)
        self.rect_bar   = (pad, pad + th + gap, pad + lw, self.h - pad)
        self.rect_info  = (pad + lw + gap, pad, self.w - pad, self.h - pad)

        self._draw_base_cards()
        
        # 初始化动态元素
        self.ui_time = self.canvas.create_text(
            pad+int(14*s), pad+int(10*s), anchor="nw", 
            text="--:--", fill=colors["TEXT_MAIN"], font=("Segoe UI", int(34*s), "bold")
        )
        
        self.ui_hint = self.canvas.create_text(
            pad+int(14*s), pad+int(60*s), anchor="nw",
            text="IDLE", fill=colors["TEXT_DIM"], font=("Segoe UI", int(10*s))
        )

        # 进度条
        bx1, by1, bx2, by2 = self.rect_bar
        bar_x, bar_y = bx1 + int(14*s), by1 + int(34*s)
        self.bar_w = (bx2 - bx1) - int(28*s)
        
        self.canvas.create_rectangle(
            bar_x, bar_y, bar_x + self.bar_w, bar_y + int(10*s),
            fill=colors["BAR_BG"], outline=""
        )
        self.ui_progress = self.canvas.create_rectangle(
            bar_x, bar_y, bar_x, bar_y + int(10*s),
            fill=colors["ACCENT"], outline=""
        )

        # 热键绑定
        self.root.bind("<F8>", self._toggle_lock)
        self.root.bind("<F9>", self._cycle_position)

    def _draw_base_cards(self):
        """绘制圆角背景层"""
        colors = CONFIG["THEME"]
        radius = int(18 * self.scale)
        for rect, color in [(self.rect_timer, colors["BG_DARK"]), 
                            (self.rect_bar, colors["BG_LIGHT"]), 
                            (self.rect_info, colors["BG_DARK"])]:
            self._create_rounded_rect(rect, radius, fill=color, outline=colors["STROKE"])

    def _create_rounded_rect(self, coords, r, **kwargs):
        x1, y1, x2, y2 = coords
        points = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def _data_polling_worker(self):
        """独立线程轮询游戏数据"""
        while True:
            try:
                # 检查 indicators 接口判断是否在局内
                resp = self.session.get(f"{CONFIG['GAME_API_BASE']}/indicators", timeout=0.4).json()
                active = resp.get("valid", False)
                
                if active and not self.in_battle:
                    self.battle_start_time = time.time()
                elif not active:
                    self.battle_start_time = None
                
                self.in_battle = active
            except Exception:
                self.in_battle = False
            time.sleep(CONFIG["POLL_INTERVAL"])

    def _ui_tick(self):
        """UI 刷新逻辑"""
        if self.in_battle and self.battle_start_time:
            elapsed = time.time() - self.battle_start_time
            remaining = CONFIG["CYCLE_DURATION"] - (elapsed % CONFIG["CYCLE_DURATION"])
            progress = (elapsed % CONFIG["CYCLE_DURATION"]) / CONFIG["CYCLE_DURATION"]
            
            # 更新倒计时
            m, s = divmod(int(remaining), 60)
            self.canvas.itemconfig(self.ui_time, text=f"{m:02d}:{s:02d}")
            self.canvas.itemconfig(self.ui_hint, text="SB CYCLE ACTIVE")
            
            # 更新进度条
            bar_x = self.canvas.coords(self.ui_progress)[0]
            self.canvas.coords(self.ui_progress, bar_x, self.canvas.coords(self.ui_progress)[1], 
                               bar_x + (self.bar_w * progress), self.canvas.coords(self.ui_progress)[3])
            
            # 临界预警 (呼吸效果)
            if remaining <= CONFIG["WARNING_LEAD_TIME"]:
                alpha = abs(math.sin(time.time() * 3))
                self.canvas.itemconfig(self.ui_time, fill="#FF6B6B" if alpha > 0.5 else "#EDEDED")
            else:
                self.canvas.itemconfig(self.ui_time, fill=CONFIG["THEME"]["TEXT_MAIN"])
        else:
            self.canvas.itemconfig(self.ui_time, text="--:--")
            self.canvas.itemconfig(self.ui_hint, text="WAITING FOR MISSION")

        self.root.after(CONFIG["UI_UPDATE_MS"], self._ui_tick)

    def _apply_layout(self, corner: int):
        sw, sh = Win32Utils.get_screen_size()
        off = 22
        # 0: LT, 1: RT, 2: LB, 3: RB
        pos = [
            (off, off), (sw - self.w - off, off),
            (off, sh - self.h - off), (sw - self.w - off, sh - self.h - off)
        ]
        x, y = pos[corner]
        self.root.geometry(f"{self.w}x{self.h}+{x}+{y}")
        self.current_corner = corner

    def _toggle_lock(self, event=None):
        self.is_clickthrough = not self.is_clickthrough
        Win32Utils.set_overlay_style(self.root.winfo_id(), self.is_clickthrough)

    def _cycle_position(self, event=None):
        self._apply_layout((self.current_corner + 1) % 4)

if __name__ == "__main__":
    Win32Utils.hide_console()
    root = tk.Tk()
    app = IncomeTimerOverlay(root)
    # 延迟执行以确保句柄有效
    root.after(100, lambda: Win32Utils.set_overlay_style(root.winfo_id(), True))
    root.mainloop()
