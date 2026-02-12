# -*- coding: utf-8 -*-
"""HUD overlay window skeleton."""

import ctypes
import tkinter as tk
from typing import Any, Dict, Optional

from bomana.config import HUDConfig
from bomana.utils.system import Win32


class HUDOverlay:
    """全屏 HUD 叠加层骨架。

    v6.8.0 P1-2:
    - 提供全屏透明置顶 Toplevel
    - 复用 Win32.setup_window 切换点击穿透/锁定
    - 首版仅支持跟随主窗口所在显示器
    """

    def __init__(self, parent_app):
        self.app = parent_app
        self.root = parent_app.root
        self._visible = False
        self._transparent_color = "#010101"

        self.window = tk.Toplevel(self.root)
        self.window.title("HUD Overlay")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=self._transparent_color)
        self.window.withdraw()

        # 优先使用 Tk 的透明色键，失败时仍可使用分层透明度降级运行。
        try:
            self.window.attributes("-transparentcolor", self._transparent_color)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(
            self.window,
            bg=self._transparent_color,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.window.update_idletasks()
        internal_id = self.window.winfo_id()
        self.hwnd = ctypes.windll.user32.GetParent(internal_id) or int(internal_id)

        self.window.bind("<Configure>", self._on_configure)
        self.window.bind("<FocusIn>", self._on_focus_in)

        self.refresh_monitor_geometry()
        self.apply_window_styles(click_through=True, alpha=HUDConfig.alpha)

    def _get_main_window_monitor(self) -> Dict[str, Any]:
        """获取主窗口所在显示器。"""
        try:
            x = int(self.root.winfo_x())
            y = int(self.root.winfo_y())
            w = max(1, int(self.root.winfo_width()))
            h = max(1, int(self.root.winfo_height()))
            center_x = x + w // 2
            center_y = y + h // 2
        except tk.TclError:
            center_x, center_y = 0, 0

        monitor = Win32.get_monitor_at(center_x, center_y)
        if monitor:
            return monitor

        monitors = Win32.get_all_monitors()
        if monitors:
            for mon in monitors:
                if mon.get("is_primary"):
                    return mon
            return monitors[0]

        sw, sh = Win32.screen_size()
        return {"x": 0, "y": 0, "width": sw, "height": sh, "is_primary": True}

    def refresh_monitor_geometry(self) -> None:
        """刷新叠加层几何，默认跟随主窗口所在显示器。"""
        if HUDConfig.follow_main_window_monitor:
            monitor = self._get_main_window_monitor()
        else:
            monitors = Win32.get_all_monitors()
            monitor = next((m for m in monitors if m.get("is_primary")), monitors[0] if monitors else None)
            if not monitor:
                sw, sh = Win32.screen_size()
                monitor = {"x": 0, "y": 0, "width": sw, "height": sh, "is_primary": True}

        x = int(monitor["x"])
        y = int(monitor["y"])
        w = max(1, int(monitor["width"]))
        h = max(1, int(monitor["height"]))
        self.window.geometry(f"{w}x{h}+{x}+{y}")

    def apply_window_styles(self, click_through: bool, alpha: Optional[int] = None) -> None:
        """应用 Win32 窗口样式（穿透、置顶、透明度）。"""
        target_alpha = HUDConfig.alpha if alpha is None else alpha
        target_alpha = max(30, min(255, int(target_alpha)))
        Win32.setup_window(self.hwnd, click_through=bool(click_through), alpha=target_alpha)

    def set_lock_state(self, locked: bool) -> None:
        """同步主窗口锁定态。"""
        self.apply_window_styles(click_through=bool(locked), alpha=HUDConfig.alpha)

    def update_transparency(self) -> None:
        """更新透明度。"""
        locked = bool(getattr(self.app, "_locked", True))
        self.apply_window_styles(click_through=locked, alpha=HUDConfig.alpha)

    def show(self) -> None:
        """显示 HUD 叠加层。"""
        if self._visible:
            return
        self.refresh_monitor_geometry()
        self.window.deiconify()
        self.window.lift()
        self._visible = True
        locked = bool(getattr(self.app, "_locked", True))
        self.apply_window_styles(click_through=locked, alpha=HUDConfig.alpha)
        self._draw_placeholder()

    def hide(self) -> None:
        """隐藏 HUD 叠加层。"""
        if not self._visible:
            return
        self._visible = False
        self.window.withdraw()

    def is_visible(self) -> bool:
        """返回叠加层可见状态。"""
        return self._visible

    def destroy(self) -> None:
        """销毁窗口。"""
        self._visible = False
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def _on_focus_in(self, _event=None) -> None:
        if bool(getattr(self.app, "_locked", True)):
            self.apply_window_styles(click_through=True, alpha=HUDConfig.alpha)

    def _on_configure(self, _event=None) -> None:
        self._draw_placeholder()

    def _draw_placeholder(self) -> None:
        """绘制骨架占位图形，供后续 P1-3 替换为真实 HUD 渲染。"""
        w = max(1, int(self.window.winfo_width()))
        h = max(1, int(self.window.winfo_height()))
        cx, cy = w // 2, h // 2
        radius = max(12, int(min(w, h) * 0.018))
        color = "#5fffa8"

        self.canvas.delete("hud_skeleton")
        self.canvas.create_oval(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            outline=color,
            width=2,
            tags="hud_skeleton",
        )
        self.canvas.create_line(
            cx - radius * 2,
            cy,
            cx + radius * 2,
            cy,
            fill=color,
            width=2,
            tags="hud_skeleton",
        )
        self.canvas.create_line(
            cx,
            cy - radius * 2,
            cx,
            cy + radius * 2,
            fill=color,
            width=2,
            tags="hud_skeleton",
        )
        self.canvas.create_text(
            cx,
            cy + radius + 18,
            text="HUD Overlay Skeleton",
            fill=color,
            font=("Segoe UI", 10, "bold"),
            tags="hud_skeleton",
        )
