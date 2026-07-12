"""Standalone navigation window."""

from __future__ import annotations

import contextlib
import ctypes
import math
import tkinter as tk
from typing import TYPE_CHECKING, Any

from bomana.config.settings import (
    HotkeyConfig,
    PanelConfig,
    UIConfig,
    ZoneConfig,
)
from bomana.ui.navigation_presenter import build_navigation_tape_model
from bomana.ui.theme import Theme
from bomana.ui.tk_style import style_clickable_surface
from bomana.ui.widgets import HeadingTape
from bomana.utils.math_utils import (
    calculate_airfield_status,
    calculate_airfield_turn_indicator,
    calculate_heading_tape_scale,
    calculate_zone_status,
    calculate_zone_turn_indicator,
    format_distance_ete,
    get_cdi_tolerance,
)
from bomana.utils.system import Win32

_WIN32_ACCESS_ERRORS = (OSError, AttributeError)
_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)
_RESTORE_VISIBLE_WIDTH = 100
_RESTORE_VISIBLE_HEIGHT = 50

if TYPE_CHECKING:
    from bomana.core.state import UISnapshot

# ============================================================================
# 独立导航窗口
# ============================================================================


class NavigationWindow:
    """独立导航条窗口

    v6.2.1新增：可拖动的独立导航窗口，方便放置在屏幕任意位置

    特性:
    - 无边框透明窗口
    - 支持拖动
    - 关闭时隐藏而非退出
    - 位置自动保存
    - 与主窗口数据同步
    """

    def __init__(self, parent_app):
        """初始化独立导航窗口

        Args:
            parent_app: 主App实例，用于访问游戏数据和配置
        """
        self.app = parent_app
        self.root = parent_app.root
        self.scale = parent_app.scale * PanelConfig.clamp_navigation_scale(
            PanelConfig.navigation_bar_scale
        )
        self._visible = False
        self._drag_data = {"x": 0, "y": 0}

        # 创建顶层窗口
        # 定义透明键颜色（用于背景透明，内容不透明）
        self._transparent_color = "#010101"  # 接近黑色但不影响正常UI

        self.window = tk.Toplevel(self.root)
        self.window.title("导航条")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        # 窗口背景设置为透明键颜色
        self.window.configure(bg=self._transparent_color)

        # 初始隐藏
        self.window.withdraw()

        # 获取窗口句柄
        self.window.update_idletasks()  # 确保窗口已创建
        # v6.6.3: 兼容 overrideredirect 的真实句柄获取
        internal_id = self.window.winfo_id()
        try:
            self.hwnd = ctypes.windll.user32.GetParent(internal_id) or int(internal_id)
        except _WIN32_ACCESS_ERRORS:
            self.hwnd = int(internal_id)

        # 使用Win32 API设置分层窗口：背景透明，内容保持不透明 + 点击穿透
        self.apply_window_styles(click_through=self.app._locked, alpha=UIConfig.WINDOW_ALPHA)

        # 初始化UI
        self._init_ui()

        # 绑定事件
        self._init_bindings()

        # 恢复位置
        self._restore_position()

    def apply_window_styles(self, click_through: bool, alpha: int):
        """设置分层窗口属性 + 点击穿透

        使用透明键颜色实现背景透明、内容不透明的效果，
        同时根据锁定状态启用点击穿透。
        """
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        LWA_COLORKEY = 0x1
        LWA_ALPHA = 0x2

        try:
            user32 = ctypes.windll.user32
            # 获取当前样式并添加分层窗口样式
            style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
            if click_through:
                style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            else:
                style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)

            # 将透明键颜色转换为COLORREF (BGR格式)
            color_hex = self._transparent_color.lstrip("#")
            r, g, b = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)
            colorref = r | (g << 8) | (b << 16)

            # 同时应用透明键和整体透明度
            alpha = int(alpha)
            user32.SetLayeredWindowAttributes(self.hwnd, colorref, alpha, LWA_COLORKEY | LWA_ALPHA)
        except _WIN32_ACCESS_ERRORS:
            # 降级：使用Tkinter的alpha属性
            self.window.attributes("-alpha", alpha / 255.0)

    def update_transparency(self):
        """更新窗口透明度（响应透明度配置变化）"""
        self.apply_window_styles(click_through=self.app._locked, alpha=UIConfig.WINDOW_ALPHA)

    @staticmethod
    def _configure_status_row(
        row: tk.Frame,
        *,
        turn_label: tk.Label,
        status_label: tk.Label,
        info_label: tk.Label,
    ) -> None:
        """Use elastic columns for standalone navigation status rows."""
        row.grid_columnconfigure(0, weight=0)
        row.grid_columnconfigure(1, weight=1, uniform="standalone_status")
        row.grid_columnconfigure(2, weight=1, uniform="standalone_status")
        row.grid_columnconfigure(3, weight=2)

        def update_wrap(event=None) -> None:
            width = int(getattr(event, "width", 0) or row.winfo_width() or 0)
            if width <= 1:
                return
            turn_label.configure(wraplength=max(42, int(width * 0.22)))
            status_label.configure(wraplength=max(42, int(width * 0.22)))
            info_label.configure(wraplength=max(72, int(width * 0.34)))

        row.bind("<Configure>", update_wrap, add="+")

    def _init_ui(self):
        """初始化独立导航窗 UI（简洁版：标题 + 航向带 + 两条状态）。"""
        s = self.scale
        pad = int(4 * s)

        self.main_frame = tk.Frame(self.window, bg=Theme.BORDER, bd=0, highlightthickness=0)
        self.main_frame.pack(fill="both", expand=True, padx=2, pady=2)

        self.content_frame = tk.Frame(
            self.main_frame, bg=Theme.GRAYPILL, bd=0, highlightthickness=0
        )
        self.content_frame.pack(fill="both", expand=True, padx=1, pady=1)

        nav_scale = PanelConfig.clamp_navigation_scale(PanelConfig.navigation_bar_scale)
        title_font = self.app._scaled_font(
            UIConfig.FONT_ZONE_TITLE, size_mult=0.9 * nav_scale, min_size=8
        )
        item_font = self.app._scaled_font(
            UIConfig.FONT_ZONE_ITEM, size_mult=0.92 * nav_scale, min_size=7
        )
        hint_font = self.app._scaled_font(
            UIConfig.FONT_HINT, size_mult=0.75 * nav_scale, min_size=7
        )

        self.title_bar = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.title_bar.pack(fill="x", padx=pad, pady=(pad, 0))
        self.title_lbl = tk.Label(
            self.title_bar,
            text="独立导航",
            font=title_font,
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.title_lbl.pack(side="left")

        self.hint_lbl = tk.Label(
            self.title_bar,
            text=f"[{HotkeyConfig.KEY_LOCK}] 解锁后拖动",
            font=hint_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.hint_lbl.pack(side="left", padx=(int(10 * s), 0))

        self.tolerance_lbl = tk.Label(
            self.title_bar,
            text="",
            font=hint_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        self.tolerance_lbl.pack(side="right", padx=(0, int(6 * s)))

        self.close_btn = tk.Label(
            self.title_bar,
            text="✕",
            font=title_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.BG,
            cursor="hand2",
            padx=int(5 * s),
            pady=max(1, int(1 * s)),
        )
        self.close_btn.pack(side="right")
        style_clickable_surface(self.close_btn)
        self.close_btn.bind("<Button-1>", self._on_close_requested)
        self.close_btn.bind(
            "<Enter>", lambda e: self.close_btn.config(fg=Theme.RED, bg=Theme.BORDER)
        )
        self.close_btn.bind(
            "<Leave>", lambda e: self.close_btn.config(fg=Theme.TEXT_MUTED, bg=Theme.BG)
        )

        self.heading_lbl = tk.Label(
            self.title_bar,
            text="航向 ---°",
            font=item_font,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        self.heading_lbl.pack(side="right", padx=(0, int(4 * s)))

        width_mult = PanelConfig.navigation_bar_width
        tape_width = int(ZoneConfig.HEADING_TAPE_WIDTH * s * 1.2 * width_mult)
        tape_height = int(ZoneConfig.HEADING_TAPE_HEIGHT * s)
        self.tape_frame = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.tape_frame.pack(fill="x", padx=pad, pady=(int(2 * s), 0))
        self.heading_tape = HeadingTape(
            self.tape_frame,
            width=tape_width,
            height=tape_height,
            text_scale=UIConfig.TEXT_SCALE_MULT * nav_scale,
        )
        self.heading_tape.pack(fill="x", expand=True)

        status_font = self.app._scaled_font(
            UIConfig.FONT_ZONE_ITEM, size_mult=0.9 * nav_scale, min_size=7
        )
        self.zone_row = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.zone_row.pack(fill="x", padx=pad, pady=(int(2 * s), 0))
        self.zone_label = tk.Label(
            self.zone_row,
            text="⊚战区",
            font=status_font,
            fg=Theme.RED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.zone_label.grid(row=0, column=0, sticky="w")
        self.zone_turn = tk.Label(
            self.zone_row,
            text="",
            font=status_font,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        self.zone_turn.grid(row=0, column=1, sticky="ew", padx=(int(6 * s), 0))
        self.zone_status = tk.Label(
            self.zone_row,
            text="",
            font=status_font,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        self.zone_status.grid(row=0, column=2, sticky="ew", padx=(int(8 * s), 0))
        self.zone_info = tk.Label(
            self.zone_row,
            text="",
            font=status_font,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="e",
            justify="right",
        )
        self.zone_info.grid(row=0, column=3, sticky="ew", padx=(int(8 * s), 0))
        self._configure_status_row(
            self.zone_row,
            turn_label=self.zone_turn,
            status_label=self.zone_status,
            info_label=self.zone_info,
        )

        self.friendly_row = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.friendly_row.pack(fill="x", padx=pad, pady=(int(1 * s), int(4 * s)))
        self.friendly_label = tk.Label(
            self.friendly_row,
            text="✈友方",
            font=status_font,
            fg=Theme.BLUE,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.friendly_label.grid(row=0, column=0, sticky="w")
        self.friendly_turn = tk.Label(
            self.friendly_row,
            text="",
            font=status_font,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        self.friendly_turn.grid(row=0, column=1, sticky="ew", padx=(int(6 * s), 0))
        self.friendly_status = tk.Label(
            self.friendly_row,
            text="",
            font=status_font,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        self.friendly_status.grid(row=0, column=2, sticky="ew", padx=(int(8 * s), 0))
        self.friendly_info = tk.Label(
            self.friendly_row,
            text="",
            font=status_font,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="e",
            justify="right",
        )
        self.friendly_info.grid(row=0, column=3, sticky="ew", padx=(int(8 * s), 0))
        self._configure_status_row(
            self.friendly_row,
            turn_label=self.friendly_turn,
            status_label=self.friendly_status,
            info_label=self.friendly_info,
        )

    def _init_bindings(self):
        """初始化事件绑定"""
        # 全窗口拖动
        self._bind_drag_recursive(self.window)

        # 右键菜单
        self.window.bind("<Button-3>", self._show_context_menu)

        # 窗口关闭事件（点X或Alt+F4）
        self.window.protocol("WM_DELETE_WINDOW", self._on_close_requested)
        self.window.bind("<FocusIn>", self._on_focus_in)

    def _bind_drag_recursive(self, widget):
        widget.bind("<Button-1>", self._on_drag_start, add="+")
        widget.bind("<B1-Motion>", self._on_drag_motion, add="+")
        for child in widget.winfo_children():
            self._bind_drag_recursive(child)

    def _on_drag_start(self, event):
        """开始拖动（仅在主窗口解锁时允许）"""
        if self.app._locked:
            return
        self._drag_data["x"] = event.x_root
        self._drag_data["y"] = event.y_root
        self._drag_data["win_x"] = self.window.winfo_x()
        self._drag_data["win_y"] = self.window.winfo_y()

    def _on_drag_motion(self, event):
        """拖动中（仅在主窗口解锁时允许）"""
        if self.app._locked:
            return
        dx = event.x_root - self._drag_data["x"]
        dy = event.y_root - self._drag_data["y"]
        x = self._drag_data["win_x"] + dx
        y = self._drag_data["win_y"] + dy
        self.window.geometry(f"+{x}+{y}")
        # 保存位置
        PanelConfig.navigation_window_pos = (x, y)

    def _show_context_menu(self, event):
        """显示右键菜单"""
        menu = tk.Menu(self.window, tearoff=0)
        menu.add_command(label="切换到集成模式", command=self._switch_to_integrated)
        menu.add_separator()
        menu.add_command(label="重置位置", command=self._reset_position)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _switch_to_integrated(self):
        """切换到集成模式"""
        self.app.navigation_services.switch_to_integrated()

    def _on_close_requested(self, _event=None):
        """Treat window-manager close as a presentation-mode change."""
        self._switch_to_integrated()
        return "break"

    def _reset_position(self):
        """重置窗口位置到屏幕中央"""
        self.window.update_idletasks()
        sw, _ = Win32.screen_size()
        w = self.window.winfo_width()
        x = (sw - w) // 2
        y = 50  # 靠近顶部
        self.window.geometry(f"+{x}+{y}")
        PanelConfig.navigation_window_pos = (x, y)

    @staticmethod
    def _monitor_rect(monitor: dict[str, Any]) -> tuple[int, int, int, int] | None:
        try:
            x = int(monitor["x"])
            y = int(monitor["y"])
            width = int(monitor["width"])
            height = int(monitor["height"])
        except KeyError, TypeError, ValueError:
            return None
        if width <= 0 or height <= 0:
            return None
        return x, y, width, height

    @classmethod
    def _pick_restore_monitor(
        cls,
        x: int,
        y: int,
        monitors: list[dict[str, Any]],
    ) -> tuple[int, int, int, int] | None:
        """Find the monitor that still contains the saved standalone nav position."""
        restore_right = x + _RESTORE_VISIBLE_WIDTH
        restore_bottom = y + _RESTORE_VISIBLE_HEIGHT
        best_rect = None
        best_area = 0
        primary_rect = None

        for monitor in monitors:
            rect = cls._monitor_rect(monitor)
            if rect is None:
                continue
            mon_x, mon_y, mon_w, mon_h = rect
            if monitor.get("is_primary") and primary_rect is None:
                primary_rect = rect

            overlap_w = max(0, min(restore_right, mon_x + mon_w) - max(x, mon_x))
            overlap_h = max(0, min(restore_bottom, mon_y + mon_h) - max(y, mon_y))
            area = overlap_w * overlap_h
            if area > best_area:
                best_area = area
                best_rect = rect

        if best_rect is not None:
            return best_rect
        if primary_rect is not None:
            return primary_rect
        for monitor in monitors:
            rect = cls._monitor_rect(monitor)
            if rect is not None:
                return rect
        return None

    @classmethod
    def _clamp_restore_position(cls, x: int, y: int) -> tuple[int, int]:
        """Clamp restored position to the current monitor layout, including negative origins."""
        monitor = cls._pick_restore_monitor(x, y, Win32.get_all_monitors())
        if monitor is None:
            sw, sh = Win32.screen_size()
            monitor = (0, 0, sw, sh)

        mon_x, mon_y, mon_w, mon_h = monitor
        max_x = mon_x + max(0, mon_w - _RESTORE_VISIBLE_WIDTH)
        max_y = mon_y + max(0, mon_h - _RESTORE_VISIBLE_HEIGHT)
        return max(mon_x, min(x, max_x)), max(mon_y, min(y, max_y))

    def _restore_position(self):
        """恢复保存的窗口位置"""
        if PanelConfig.navigation_window_pos:
            x, y = PanelConfig.navigation_window_pos
            x, y = self._clamp_restore_position(int(x), int(y))
            self.window.geometry(f"+{x}+{y}")
        else:
            self._reset_position()

    def show(self):
        """显示窗口"""
        if not self._visible:
            self._visible = True
            self.window.deiconify()
            self.window.lift()
            alpha = (
                UIConfig.WINDOW_ALPHA if self.app._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
            )
            self.apply_window_styles(click_through=self.app._locked, alpha=alpha)

    def hide(self):
        """隐藏窗口"""
        if self._visible:
            self.clear_display()
            self._visible = False
            self.window.withdraw()

    def clear_display(self):
        """Clear rendered nav content before hiding or mode switching."""
        self.heading_lbl.config(text="航向 ---°")
        self.tolerance_lbl.config(text="")
        self.heading_tape.clear()
        self.zone_label.config(text="⊚战区", fg=Theme.RED)
        self.zone_turn.config(text="", fg=Theme.TEXT_DIM)
        self.zone_status.config(text="", fg=Theme.TEXT_DIM)
        self.zone_info.config(text="", fg=Theme.TEXT_DIM)
        self.friendly_turn.config(text="", fg=Theme.TEXT_DIM)
        self.friendly_status.config(text="", fg=Theme.TEXT_DIM)
        self.friendly_info.config(text="", fg=Theme.TEXT_DIM)

    def is_visible(self):
        """返回窗口是否可见"""
        return self._visible

    def update_hint_text(self):
        """更新提示文本（当热键配置变更时调用）"""
        if hasattr(self, "hint_lbl") and self.hint_lbl:
            self.hint_lbl.config(text=f"[{HotkeyConfig.KEY_LOCK}] 解锁后拖动")

    def destroy(self):
        """销毁窗口实例（用于主题/缩放热重载）"""
        self._visible = False
        with contextlib.suppress(tk.TclError):
            self.window.destroy()

    def _on_focus_in(self, event=None):
        """Focus guard to keep click-through when locked."""
        if self.app._locked:
            with contextlib.suppress(Exception):
                self.apply_window_styles(click_through=True, alpha=UIConfig.WINDOW_ALPHA)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except _NUMERIC_PARSE_ERRORS:
            return default
        return number if math.isfinite(number) else default

    @classmethod
    def _format_active_info_text(cls, info: dict[str, Any]) -> str:
        distance = cls._safe_float(info.get("distance_km", 0.0))
        return format_distance_ete(distance, info.get("ete_str"))

    def update_display(self, snap: UISnapshot):
        """更新独立导航窗显示（简洁航向带版）。"""
        if not self._visible:
            return

        raw_heading = float(getattr(snap, "player_heading", 0.0) or 0.0)
        heading_deg = raw_heading % 360.0
        phase_name = str(getattr(getattr(snap, "phase", None), "name", "") or "")
        heading_available = (phase_name in {"ALIVE", "LOSS_PENDING"}) and (
            not bool(getattr(snap, "api_down", False))
        )

        # 更新航向
        if heading_available:
            self.heading_lbl.config(text=f"航向 {int(heading_deg):03d}°")
        else:
            self.heading_lbl.config(text="航向 ---°")
        if not heading_available:
            self.heading_tape.clear()
            self.tolerance_lbl.config(text="")
            self.zone_label.config(text="⊚战区", fg=Theme.RED)
            self.zone_turn.config(text="", fg=Theme.TEXT_DIM)
            self.zone_status.config(text="无目标", fg=Theme.TEXT_MUTED)
            self.zone_info.config(text="", fg=Theme.TEXT_DIM)
            self.friendly_turn.config(text="", fg=Theme.TEXT_DIM)
            self.friendly_status.config(text="", fg=Theme.TEXT_DIM)
            self.friendly_info.config(text="", fg=Theme.TEXT_DIM)
            return

        destroyed_zones = (
            getattr(snap, "destroyed_zones", [])
            if getattr(snap, "zone_destroyed_alert", False)
            else None
        )
        model = build_navigation_tape_model(snap, destroyed_zones=destroyed_zones)
        targets = model.targets
        primary_info = model.primary_target_info

        primary_dist = self._safe_float(primary_info.get("distance_km")) if primary_info else 10.0
        self.heading_tape.update_tape_multi(heading_deg, targets, primary_dist)

        if primary_info:
            rel = self._safe_float(primary_info.get("relative", 0.0))
            distance = self._safe_float(primary_info.get("distance_km", 0.0))
            info_text = self._format_active_info_text(primary_info)
            self.zone_label.config(text="⊚战区", fg=Theme.RED)
            tolerance = get_cdi_tolerance(distance)
            scale = calculate_heading_tape_scale(distance)
            turn_text, turn_color = calculate_zone_turn_indicator(rel, tolerance)
            status_text, status_color = calculate_zone_status(abs(rel), tolerance)
            self.tolerance_lbl.config(text=f"±{tolerance:.1f}° {scale:.1f}x")
            info_color = Theme.RED
            self.zone_turn.config(text=turn_text, fg=turn_color)
            self.zone_status.config(text=status_text, fg=status_color)
            self.zone_info.config(text=info_text, fg=info_color)
        else:
            self.zone_label.config(text="⊚战区", fg=Theme.RED)
            self.tolerance_lbl.config(text="")
            self.zone_turn.config(text="", fg=Theme.TEXT_DIM)
            self.zone_status.config(text="无目标", fg=Theme.TEXT_MUTED)
            self.zone_info.config(text="", fg=Theme.TEXT_DIM)

        friendly = getattr(snap, "friendly_airfield", None)
        if friendly:
            friendly_rel = self._safe_float(getattr(friendly, "relative", 0.0))
            friendly_distance = self._safe_float(getattr(friendly, "distance_km", 0.0))
            turn_text, turn_color = calculate_airfield_turn_indicator(friendly_rel)
            status_text, status_color = calculate_airfield_status(abs(friendly_rel))
            info_text = format_distance_ete(friendly_distance, getattr(friendly, "ete_str", ""))
            self.friendly_turn.config(text=turn_text, fg=turn_color)
            self.friendly_status.config(text=status_text, fg=status_color)
            self.friendly_info.config(text=info_text, fg=Theme.BLUE)
        else:
            self.friendly_turn.config(text="", fg=Theme.TEXT_DIM)
            self.friendly_status.config(text="", fg=Theme.TEXT_DIM)
            self.friendly_info.config(text="", fg=Theme.TEXT_DIM)
