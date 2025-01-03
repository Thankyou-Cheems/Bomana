import time
import threading
import ctypes
import math
import random
import requests
import tkinter as tk
from typing import Optional, Tuple, List

# ==========================================
# 核心配置与主题定义
# ==========================================
CONFIG = {
    "GAME_API_BASE": "http://127.0.0.1:8111",
    "POLL_INTERVAL": 0.5,
    "UI_REFRESH_MS": 50,
    "CYCLE_SECONDS": 900,
    "WARNING_THRESHOLD": 30,
    "PULSE_SPEED": 2.2,
    "SCALE": {"MIN": 0.8, "MAX": 1.6, "BASE_RES": (1920, 1080)},
    "THEME": {
        "TEXT": "#EDEDED",
        "TEXT_DIM": "#A8B0B8",
        "CARD_BG": "#0F141A",
        "CARD_BG_ALT": "#101823",
        "STROKE": "#263242",
        "BAR_BG": "#1E2A36",
        "BAR_FILL": "#EDEDED"
    }
}

# ==========================================
# 系统工具 (Win32 & 辅助函数)
# ==========================================
class SystemUtils:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    @classmethod
    def hide_console(cls):
        hwnd = cls.kernel32.GetConsoleWindow()
        if hwnd:
            cls.user32.ShowWindow(hwnd, 0)

    @classmethod
    def set_clickthrough(cls, hwnd: int, enable: bool, alpha: int = 235):
        # Win32 样式常量
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOPMOST = 0x00000008
        LWA_ALPHA = 0x00000002

        ex_style = cls.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enable:
            ex_style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST)
        else:
            ex_style |= (WS_EX_LAYERED | WS_EX_TOPMOST)
            ex_style &= ~WS_EX_TRANSPARENT
        
        cls.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
        cls.user32.SetLayeredWindowAttributes(hwnd, 0, max(0, min(255, alpha)), LWA_ALPHA)

    @staticmethod
    def get_screen_size():
        return SystemUtils.user32.GetSystemMetrics(0), SystemUtils.user32.GetSystemMetrics(1)

def format_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

# ==========================================
# 视觉特效引擎
# ==========================================
def render_visual_assets(w: int, h: int, scale: float):
    """
    尝试使用 PIL 渲染极光渐变和噪点层。
    若 PIL 不可用，则返回 (None, None) 进行静默降级。
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageTk
    except ImportError:
        return None, None

    # 1. 极光渐变层
    aurora = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(aurora)
    
    # 模拟极光色带
    blobs = [
        ((int(w*0.15), int(h*0.30)), int(220*scale), (90, 255, 200, 70)),
        ((int(w*0.55), int(h*0.20)), int(260*scale), (130, 190, 255, 60)),
        ((int(w*0.70), int(h*0.55)), int(240*scale), (180, 140, 255, 55)),
        ((int(w*0.35), int(h*0.70)), int(280*scale), (80, 220, 255, 45)),
    ]
    for (cx, cy), rad, col in blobs:
        draw.ellipse((cx-rad, cy-rad, cx+rad, cy+rad), fill=col)

    aurora = aurora.filter(ImageFilter.GaussianBlur(radius=24))

    # 2. 噪点层
    nw, nh = max(160, int(220*scale)), max(120, int(180*scale))
    noise_img = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    px = noise_img.load()
    for y in range(nh):
        for x in range(nw):
            v = random.randint(0, 25)
            a = random.randint(10, 22)
            px[x, y] = (255, 255, 255, a) if v > 18 else (0, 0, 0, a)
    
    noise_img = noise_img.filter(ImageFilter.GaussianBlur(radius=0.6))

    return ImageTk.PhotoImage(aurora), ImageTk.PhotoImage(noise_img)

# ==========================================
# 核心 UI 与 逻辑
# ==========================================
class OverlayApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._init_window_settings()
        self._init_state()
        
        # 布局参数与资源
        self._calculate_scaling()
        self.aurora_img, self.noise_img = render_visual_assets(self.width, self.height, self.scale)
        
        self._setup_ui()
        self._bind_events()
        
        # 启动后台轮询
        self.session = requests.Session()
        threading.Thread(target=self._data_polling_loop, daemon=True).start()
        self.update_ui()

    def _init_window_settings(self):
        self.root.title("WT SB Timer")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.transparent_color = "#00ff00"
        self.root.configure(bg=self.transparent_color)
        self.root.wm_attributes("-transparentcolor", self.transparent_color)

    def _init_state(self):
        self.in_battle = False
        self.join_time = None
        self.last_cycle_idx = None
        self.is_clickthrough = True
        self.current_corner = 1
        self.alert_enabled = True
        self.beep_enabled = False

    def _calculate_scaling(self):
        sw, sh = SystemUtils.get_screen_size()
        bw, bh = CONFIG["SCALE"]["BASE_RES"]
        self.scale = max(CONFIG["SCALE"]["MIN"], min(CONFIG["SCALE"]["MAX"], ((sw/bw) + (sh/bh))/2.0))
        self.width = int(340 * self.scale)
        self.height = int(160 * self.scale)
        self.radius = int(18 * self.scale)

    def _setup_ui(self):
        self.canvas = tk.Canvas(self.root, width=self.width, height=self.height, 
                                highlightthickness=0, bd=0, bg=self.transparent_color)
        self.canvas.pack()
        
        # 1. 绘制背景特效
        if self.aurora_img:
            self.canvas.create_image(0, 0, anchor="nw", image=self.aurora_img)
        if self.noise_img:
            tw, th = self.noise_img.width(), self.noise_img.height()
            for y in range(0, self.height, th):
                for x in range(0, self.width, tw):
                    self.canvas.create_image(x, y, anchor="nw", image=self.noise_img)

        # 2. Bento 布局网格计算
        s = self.scale
        theme = CONFIG["THEME"]
        pad, gap = int(12*s), int(10*s)
        left_w = int(self.width * 0.58)
        top_h = int(self.height * 0.58)
        right_w = self.width - pad*2 - gap - left_w
        bot_h = self.height - pad*2 - gap - top_h

        # 卡片定义
        self.layout = {
            "timer": (pad, pad, pad + left_w, pad + top_h),
            "bar": (pad, pad + top_h + gap, pad + left_w, pad + top_h + gap + bot_h),
            "info": (pad + left_w + gap, pad, pad + left_w + gap + right_w, self.height - pad)
        }

        # 3. 绘制卡片
        for key, rect in self.layout.items():
            color = theme["CARD_BG"] if key != "bar" else theme["CARD_BG_ALT"]
            self._draw_rounded_rect(*rect, self.radius, fill=color, outline=theme["STROKE"])

        # 4. 初始化动态文本
        tx, ty = self.layout["timer"][0] + int(14*s), self.layout["timer"][1] + int(10*s)
        self.ui_timer = self.canvas.create_text(tx, ty, anchor="nw", text="--:--", 
                                                fill=theme["TEXT"], font=("Segoe UI", int(34*s), "bold"))
        self.ui_subtitle = self.canvas.create_text(tx, ty + int(52*s), anchor="nw", text="WAITING FOR BATTLE", 
                                                   fill=theme["TEXT_DIM"], font=("Segoe UI", int(10*s)))

        # 5. 进度条组件
        bx1, by1, bx2, by2 = self.layout["bar"]
        self.canvas.create_text(bx1+int(14*s), by1+int(10*s), anchor="nw", text="Cycle Progress", 
                                fill=theme["TEXT_DIM"], font=("Segoe UI", int(10*s)))
        
        self.bar_coords = (bx1+int(14*s), by1+int(34*s), bx2-int(14*s), by1+int(44*s))
        self._draw_rounded_rect(*self.bar_coords, int(8*s), fill=theme["BAR_BG"], outline="")
        self.ui_bar_fill = self._draw_rounded_rect(self.bar_coords[0], self.bar_coords[1], self.bar_coords[0], self.bar_coords[3], 
                                                   int(8*s), fill=theme["BAR_FILL"], outline="")

        # 6. 信息栏
        ix, iy = self.layout["info"][0] + int(14*s), self.layout["info"][1] + int(14*s)
        self._create_info_item("Elapsed", ix, iy, "ui_elapsed")
        self._create_info_item("Cycle", ix, iy + int(42*s), "ui_cycle")
        self._create_info_item("Alerts", ix, iy + int(84*s), "ui_alerts")

        # 初始化位置
        self.dock_to_corner(self.current_corner)
        SystemUtils.set_clickthrough(self.root.winfo_id(), True)

    def _create_info_item(self, label, x, y, attr_name):
        s = self.scale
        theme = CONFIG["THEME"]
        self.canvas.create_text(x, y, anchor="nw", text=label, fill=theme["TEXT_DIM"], font=("Segoe UI", int(10*s)))
        setattr(self, attr_name, self.canvas.create_text(x, y + int(16*s), anchor="nw", text="--", 
                                                         fill=theme["TEXT"], font=("Segoe UI", int(11*s), "bold")))

    def _draw_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        points = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def _data_polling_loop(self):
        while True:
            try:
                # 检查进入战斗状态
                ind = self.session.get(f"{CONFIG['GAME_API_BASE']}/indicators", timeout=0.4).json()
                active = ind.get("valid", False)
                if active:
                    mission = self.session.get(f"{CONFIG['GAME_API_BASE']}/mission.json", timeout=0.4).json()
                    active = mission.get("status") == "running"
                
                if not self.in_battle and active:
                    self.join_time = time.time()
                elif self.in_battle and not active:
                    self.join_time = None
                    self.last_cycle_idx = None
                
                self.in_battle = active
            except Exception:
                self.in_battle = False
            time.sleep(CONFIG["POLL_INTERVAL"])

    def update_ui(self):
        now = time.time()
        theme = CONFIG["THEME"]
        
        if self.in_battle and self.join_time:
            elapsed = int(now - self.join_time)
            rem = CONFIG["CYCLE_SECONDS"] - (elapsed % CONFIG["CYCLE_SECONDS"])
            cycle_idx = (elapsed // CONFIG["CYCLE_SECONDS"]) + 1
            progress = (elapsed % CONFIG["CYCLE_SECONDS"]) / CONFIG["CYCLE_SECONDS"]

            # 更新文本
            self.canvas.itemconfig(self.ui_timer, text=format_hms(rem))
            self.canvas.itemconfig(self.ui_elapsed, text=format_hms(elapsed))
            self.canvas.itemconfig(self.ui_cycle, text=str(cycle_idx))
            self.canvas.itemconfig(self.ui_alerts, text="ON" if self.alert_enabled else "OFF")

            # 进度条呼吸效果与告警
            in_final = rem <= CONFIG["WARNING_THRESHOLD"]
            pulse = (0.5 + 0.5 * math.sin(now * CONFIG["PULSE_SPEED"] * 2 * math.pi)) if in_final else 0.0
            
            # 更新进度条
            bx1, by1, bx2, by2 = self.bar_coords
            fill_w = int((bx2 - bx1) * progress)
            mod = int(2 * self.scale * pulse)
            self.canvas.delete(self.ui_bar_fill)
            self.ui_bar_fill = self._draw_rounded_rect(bx1, by1, bx1 + fill_w + mod, by2, int(8*self.scale), 
                                                       fill="#FFFFFF" if pulse > 0.6 else theme["BAR_FILL"], outline="")

            # 告警提醒
            if in_final:
                self.canvas.itemconfig(self.ui_subtitle, text="FINAL 30S • STAY ALIVE")
                if rem in (30, 20, 10, 5, 4, 3, 2, 1) and self.beep_enabled:
                    SystemUtils.kernel32.Beep(900, 60)
            else:
                self.canvas.itemconfig(self.ui_subtitle, text="SB INCOME TIMER • 15M CYCLE")

            # 周期变更提醒
            if self.last_cycle_idx is not None and cycle_idx != self.last_cycle_idx:
                if self.beep_enabled: SystemUtils.kernel32.Beep(1000, 100)
            self.last_cycle_idx = cycle_idx

        else:
            self.canvas.itemconfig(self.ui_timer, text="--:--")
            self.canvas.itemconfig(self.ui_subtitle, text="AWAITING GAME CONNECTION (8111)")
            self.canvas.itemconfig(self.ui_elapsed, text="--")
            self.canvas.itemconfig(self.ui_cycle, text="--")

        self.root.after(CONFIG["UI_REFRESH_MS"], self.update_ui)

    def dock_to_corner(self, corner_idx):
        sw, sh = SystemUtils.get_screen_size()
        p = 22
        positions = [
            (p, p), (sw - self.width - p, p),
            (p, sh - self.height - p), (sw - self.width - p, sh - self.height - p)
        ]
        x, y = positions[corner_idx]
        self.root.geometry(f"{self.width}x{self.height}+{max(0, x)}+{max(0, y)}")

    def _bind_events(self):
        self.root.bind("<F8>", self.toggle_clickthrough)
        self.root.bind("<F9>", self.next_corner)
        self.root.bind("<F10>", lambda e: setattr(self, "alert_enabled", not self.alert_enabled))
        self.root.bind("<F11>", lambda e: setattr(self, "beep_enabled", not self.beep_enabled))
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def toggle_clickthrough(self, event=None):
        self.is_clickthrough = not self.is_clickthrough
        SystemUtils.set_clickthrough(self.root.winfo_id(), self.is_clickthrough)

    def next_corner(self, event=None):
        self.current_corner = (self.current_corner + 1) % 4
        self.dock_to_corner(self.current_corner)

if __name__ == "__main__":
    SystemUtils.hide_console()
    root = tk.Tk()
    app = OverlayApp(root)
    root.mainloop()
