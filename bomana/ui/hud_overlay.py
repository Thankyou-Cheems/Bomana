# -*- coding: utf-8 -*-
"""HUD overlay with reticle projection."""

import ctypes
import math
import tkinter as tk
from typing import Any, Dict, Optional

from bomana.config import HUDConfig
from bomana.utils.system import Win32


class HUDOverlay:
    """全屏 HUD 叠加层。

    v6.8.0 P1-3:
    - 靶子(reticle)渲染与 2.5D 估计投影
    - X: 相对方位投影
    - Y: 姿态俯仰 + 横滚补偿
    - 距离驱动尺寸和亮度（作为透明度近似）
    - 姿态不可信时自动降级到 2D 方向提示

    注意：
    - 所有 canvas 图元仅初始化一次，后续逐帧只更新坐标/样式；
      不使用每帧 delete/create。
    """

    # 2.5D 投影参数（首版估计）
    _MAX_RELATIVE_DEG = 90.0
    _HORIZONTAL_COVER_RATIO = 0.42
    _VERTICAL_COVER_RATIO = 0.36
    _ROLL_COUPLING_RATIO = 0.14
    _VERTICAL_FOV_DEG = 55.0

    # 距离 -> 尺寸/亮度映射参数
    _DIST_NEAR_KM = 2.0
    _DIST_FAR_KM = 40.0
    _BASE_RADIUS_PX = 16.0
    _RADIUS_MIN_SCALE = 0.75
    _RADIUS_MAX_SCALE = 1.85
    _BRIGHTNESS_MIN = 0.35
    _BRIGHTNESS_MAX = 1.00

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

        # 尽量使用透明色键；不支持时降级为普通透明窗口。
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

        # 渲染状态（由外部更新）
        self._has_target = False
        self._target_relative_deg = 0.0
        self._target_distance_km = 0.0
        self._attitude_pitch_deg = 0.0
        self._attitude_roll_deg = 0.0
        self._attitude_fallback = True

        # 轻量平滑缓存
        self._smoothed_x: Optional[float] = None
        self._smoothed_y: Optional[float] = None
        self._smoothed_radius: Optional[float] = None
        self._last_signature: Optional[tuple] = None

        # 图元初始化：仅创建一次，后续只更新
        self._reticle_ring_id: Optional[int] = None
        self._reticle_hline_id: Optional[int] = None
        self._reticle_vline_id: Optional[int] = None
        self._reticle_mode_id: Optional[int] = None
        self._reticle_dist_id: Optional[int] = None
        self._init_reticle_items()

        self.window.bind("<Configure>", self._on_configure)
        self.window.bind("<FocusIn>", self._on_focus_in)

        self.refresh_monitor_geometry()
        self.apply_window_styles(click_through=True, alpha=HUDConfig.alpha)
        self._set_reticle_visible(False)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return float(a) + (float(b) - float(a)) * float(t)

    @classmethod
    def _normalize_distance(cls, distance_km: float) -> float:
        if cls._DIST_FAR_KM <= cls._DIST_NEAR_KM:
            return 1.0
        t = (float(distance_km) - cls._DIST_NEAR_KM) / (cls._DIST_FAR_KM - cls._DIST_NEAR_KM)
        return cls._clamp(t, 0.0, 1.0)

    @classmethod
    def _color_from_brightness(cls, brightness: float, fallback: bool) -> str:
        brightness = cls._clamp(brightness, cls._BRIGHTNESS_MIN, cls._BRIGHTNESS_MAX)
        base = (255, 196, 96) if fallback else (95, 255, 168)
        r = int(base[0] * brightness)
        g = int(base[1] * brightness)
        b = int(base[2] * brightness)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _smooth(self, current: Optional[float], target: float) -> float:
        if current is None:
            return float(target)
        alpha = self._clamp(getattr(HUDConfig, "smoothing", 0.35), 0.05, 1.0)
        return current + (float(target) - current) * alpha

    def _get_main_window_monitor(self) -> Dict[str, Any]:
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
        target_alpha = HUDConfig.alpha if alpha is None else alpha
        target_alpha = max(30, min(255, int(target_alpha)))
        Win32.setup_window(self.hwnd, click_through=bool(click_through), alpha=target_alpha)

    def set_lock_state(self, locked: bool) -> None:
        self.apply_window_styles(click_through=bool(locked), alpha=HUDConfig.alpha)

    def update_transparency(self) -> None:
        locked = bool(getattr(self.app, "_locked", True))
        self.apply_window_styles(click_through=locked, alpha=HUDConfig.alpha)

    def show(self) -> None:
        if self._visible:
            return
        self.refresh_monitor_geometry()
        self.window.deiconify()
        self.window.lift()
        self._visible = True
        locked = bool(getattr(self.app, "_locked", True))
        self.apply_window_styles(click_through=locked, alpha=HUDConfig.alpha)
        self._render_reticle(force=True)

    def hide(self) -> None:
        if not self._visible:
            return
        self._visible = False
        self.window.withdraw()

    def is_visible(self) -> bool:
        return self._visible

    def destroy(self) -> None:
        self._visible = False
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def clear_target(self) -> None:
        """清空目标并隐藏靶子。"""
        self._has_target = False
        self._render_reticle(force=True)

    def update_target(
        self,
        has_target: bool,
        relative_deg: float = 0.0,
        distance_km: float = 0.0,
        attitude_pitch_deg: float = 0.0,
        attitude_roll_deg: float = 0.0,
        attitude_fallback: bool = True,
    ) -> None:
        """更新目标渲染输入。

        Args:
            has_target: 是否存在主目标
            relative_deg: 目标相对方位（左负右正）
            distance_km: 目标距离（公里）
            attitude_pitch_deg: 姿态俯仰角（度）
            attitude_roll_deg: 姿态横滚角（度）
            attitude_fallback: 姿态不可信时为 True，自动降级 2D
        """
        self._has_target = bool(has_target)
        self._target_relative_deg = float(relative_deg)
        self._target_distance_km = max(0.0, float(distance_km))
        self._attitude_pitch_deg = float(attitude_pitch_deg)
        self._attitude_roll_deg = float(attitude_roll_deg)
        self._attitude_fallback = bool(attitude_fallback)
        self._render_reticle()

    def update_from_snapshot(
        self,
        snapshot: Any,
        target_relative_deg: Optional[float],
        target_distance_km: Optional[float],
    ) -> None:
        """从 UISnapshot 风格对象更新 HUD。

        该方法用于后续 App 生命周期接入时直接复用，当前任务只实现渲染端。
        """
        if snapshot is None or target_relative_deg is None or target_distance_km is None:
            self.clear_target()
            return

        has_target = bool(getattr(snapshot, "has_target", True))
        pitch = float(getattr(snapshot, "attitude_pitch_deg", 0.0) or 0.0)
        roll = float(getattr(snapshot, "attitude_roll_deg", 0.0) or 0.0)
        fallback = bool(getattr(snapshot, "hud_attitude_fallback", True))

        self.update_target(
            has_target=has_target,
            relative_deg=float(target_relative_deg),
            distance_km=float(target_distance_km),
            attitude_pitch_deg=pitch,
            attitude_roll_deg=roll,
            attitude_fallback=fallback,
        )

    def _on_focus_in(self, _event=None) -> None:
        if bool(getattr(self.app, "_locked", True)):
            self.apply_window_styles(click_through=True, alpha=HUDConfig.alpha)

    def _on_configure(self, _event=None) -> None:
        self._render_reticle(force=True)

    def _init_reticle_items(self) -> None:
        """初始化靶子图元（仅执行一次）。"""
        color = "#5fffa8"
        self._reticle_ring_id = self.canvas.create_oval(
            0, 0, 0, 0,
            outline=color,
            width=2,
            state="hidden",
            tags=("hud_reticle",),
        )
        self._reticle_hline_id = self.canvas.create_line(
            0, 0, 0, 0,
            fill=color,
            width=2,
            state="hidden",
            tags=("hud_reticle",),
        )
        self._reticle_vline_id = self.canvas.create_line(
            0, 0, 0, 0,
            fill=color,
            width=2,
            state="hidden",
            tags=("hud_reticle",),
        )
        self._reticle_mode_id = self.canvas.create_text(
            0, 0,
            text="",
            fill=color,
            font=("Segoe UI", 10, "bold"),
            state="hidden",
            tags=("hud_reticle",),
        )
        self._reticle_dist_id = self.canvas.create_text(
            0, 0,
            text="",
            fill=color,
            font=("Segoe UI", 9),
            state="hidden",
            tags=("hud_reticle",),
        )

    def _set_reticle_visible(self, visible: bool) -> None:
        state = "normal" if visible else "hidden"
        for item_id in (
            self._reticle_ring_id,
            self._reticle_hline_id,
            self._reticle_vline_id,
            self._reticle_mode_id,
            self._reticle_dist_id,
        ):
            if item_id is not None:
                self.canvas.itemconfig(item_id, state=state)
        if not visible:
            self._last_signature = None

    def _project_target(self, width: int, height: int) -> tuple:
        """根据相对方位 + 姿态估计目标屏幕位置。"""
        cx = width * 0.5
        cy = height * 0.5
        rel = self._clamp(self._target_relative_deg, -self._MAX_RELATIVE_DEG, self._MAX_RELATIVE_DEG)
        rel_norm = rel / self._MAX_RELATIVE_DEG

        # X: 方位投影
        target_x = cx + rel_norm * (width * self._HORIZONTAL_COVER_RATIO)

        # Y: 2.5D 俯仰 + 横滚耦合补偿（姿态可靠时）
        if self._attitude_fallback:
            target_y = cy
        else:
            pixels_per_deg = (height * self._VERTICAL_COVER_RATIO) / max(10.0, self._VERTICAL_FOV_DEG * 0.5)
            pitch_offset = -self._attitude_pitch_deg * pixels_per_deg
            roll_offset = math.sin(math.radians(self._attitude_roll_deg)) * (rel_norm * height * self._ROLL_COUPLING_RATIO)
            target_y = cy + pitch_offset + roll_offset

        min_x, max_x = width * 0.06, width * 0.94
        min_y, max_y = height * 0.08, height * 0.92
        target_x = self._clamp(target_x, min_x, max_x)
        target_y = self._clamp(target_y, min_y, max_y)

        return target_x, target_y, rel

    def _direction_prompt(self, rel: float) -> str:
        """2D 降级时的方向提示文本。"""
        if rel <= -8.0:
            return "<- 2D"
        if rel >= 8.0:
            return "2D ->"
        return "2D"

    def _render_reticle(self, force: bool = False) -> None:
        if not self._visible:
            return

        if not self._has_target:
            self._set_reticle_visible(False)
            return

        width = max(1, int(self.window.winfo_width()))
        height = max(1, int(self.window.winfo_height()))
        target_x, target_y, rel = self._project_target(width, height)

        dist_t = self._normalize_distance(self._target_distance_km)
        radius_scale = self._lerp(self._RADIUS_MAX_SCALE, self._RADIUS_MIN_SCALE, dist_t)
        brightness = self._lerp(self._BRIGHTNESS_MAX, self._BRIGHTNESS_MIN, dist_t)
        radius_target = self._BASE_RADIUS_PX * float(HUDConfig.scale) * radius_scale

        self._smoothed_x = self._smooth(self._smoothed_x, target_x)
        self._smoothed_y = self._smooth(self._smoothed_y, target_y)
        self._smoothed_radius = self._smooth(self._smoothed_radius, radius_target)

        cx = float(self._smoothed_x)
        cy = float(self._smoothed_y)
        radius = max(8.0, float(self._smoothed_radius))
        line_len = radius * 2.3

        color = self._color_from_brightness(brightness, self._attitude_fallback)
        mode_text = self._direction_prompt(rel) if self._attitude_fallback else "2.5D"
        dist_text = f"{self._target_distance_km:.1f}km"
        stroke = 2 if self._attitude_fallback else 3

        signature = (
            round(cx, 1),
            round(cy, 1),
            round(radius, 1),
            round(self._target_distance_km, 1),
            mode_text,
            color,
            stroke,
        )
        if (not force) and signature == self._last_signature:
            return
        self._last_signature = signature

        self._set_reticle_visible(True)
        self.canvas.coords(self._reticle_ring_id, cx - radius, cy - radius, cx + radius, cy + radius)
        self.canvas.coords(self._reticle_hline_id, cx - line_len, cy, cx + line_len, cy)
        self.canvas.coords(self._reticle_vline_id, cx, cy - line_len, cx, cy + line_len)
        self.canvas.coords(self._reticle_mode_id, cx, cy + radius + 16)
        self.canvas.coords(self._reticle_dist_id, cx, cy + radius + 32)

        self.canvas.itemconfig(self._reticle_mode_id, text=mode_text)
        self.canvas.itemconfig(self._reticle_dist_id, text=dist_text)

        self.canvas.itemconfig(self._reticle_ring_id, outline=color, width=stroke)
        self.canvas.itemconfig(self._reticle_hline_id, fill=color, width=stroke)
        self.canvas.itemconfig(self._reticle_vline_id, fill=color, width=stroke)
        self.canvas.itemconfig(self._reticle_mode_id, fill=color)
        self.canvas.itemconfig(self._reticle_dist_id, fill=color)
