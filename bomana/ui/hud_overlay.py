# -*- coding: utf-8 -*-
"""HUD overlay with reticle projection."""

import ctypes
import math
import tkinter as tk
from typing import Any, Dict, List, Optional

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

    # 顶部简化罗盘条参数（v6.8.x 可选增强）
    _COMPASS_TOP_RATIO = 0.075
    _COMPASS_WIDTH_RATIO = 0.34
    _COMPASS_BAR_HEIGHT_PX = 24.0
    _COMPASS_VISIBLE_HALF_DEG = 60.0
    _COMPASS_TICK_STEP_DEG = 10.0
    _COMPASS_MAJOR_STEP_DEG = 30.0
    _COMPASS_TARGET_MARKER_W = 7.0
    _COMPASS_TARGET_MARKER_H = 9.0

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
        self._heading_deg = 0.0

        # 轻量平滑缓存
        self._smoothed_x: Optional[float] = None
        self._smoothed_y: Optional[float] = None
        self._smoothed_radius: Optional[float] = None
        self._last_signature: Optional[tuple] = None
        self._compass_signature: Optional[tuple] = None
        self._secondary_signature: Optional[tuple] = None
        self._standby_visible = False
        self._standby_text = "HUD STANDBY"
        self._secondary_targets: List[Dict[str, float]] = []
        self._compass_offsets: List[float] = [
            float(v)
            for v in range(
                int(-self._COMPASS_VISIBLE_HALF_DEG),
                int(self._COMPASS_VISIBLE_HALF_DEG) + 1,
                int(self._COMPASS_TICK_STEP_DEG),
            )
        ]

        # 图元初始化：仅创建一次，后续只更新
        self._reticle_ring_id: Optional[int] = None
        self._reticle_hline_id: Optional[int] = None
        self._reticle_vline_id: Optional[int] = None
        self._reticle_mode_id: Optional[int] = None
        self._reticle_dist_id: Optional[int] = None
        self._secondary_text_ids: List[int] = []
        self._compass_bg_id: Optional[int] = None
        self._compass_axis_id: Optional[int] = None
        self._compass_center_id: Optional[int] = None
        self._compass_heading_id: Optional[int] = None
        self._compass_target_id: Optional[int] = None
        self._compass_tick_ids: List[int] = []
        self._compass_label_ids: List[int] = []
        self._standby_id: Optional[int] = None
        self._init_reticle_items()
        self._init_compass_items()

        self.window.bind("<Configure>", self._on_configure)
        self.window.bind("<FocusIn>", self._on_focus_in)

        self.refresh_monitor_geometry()
        self.apply_window_styles(click_through=True, alpha=HUDConfig.alpha)
        self._set_reticle_visible(False)
        self._set_compass_visible(False)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return float(a) + (float(b) - float(a)) * float(t)

    @staticmethod
    def _normalize_heading_deg(deg: float) -> float:
        return float(deg) % 360.0

    @classmethod
    def _compass_label(cls, heading_deg: float) -> str:
        value = int(round(cls._normalize_heading_deg(heading_deg))) % 360
        cards = {0: "N", 90: "E", 180: "S", 270: "W"}
        return cards.get(value, f"{value:03d}")

    @classmethod
    def _normalize_distance(cls, distance_km: float) -> float:
        if cls._DIST_FAR_KM <= cls._DIST_NEAR_KM:
            return 1.0
        t = (float(distance_km) - cls._DIST_NEAR_KM) / (cls._DIST_FAR_KM - cls._DIST_NEAR_KM)
        return cls._clamp(t, 0.0, 1.0)

    @classmethod
    def _color_from_brightness(cls, brightness: float, fallback: bool) -> str:
        brightness = cls._clamp(brightness, cls._BRIGHTNESS_MIN, cls._BRIGHTNESS_MAX)
        style = str(getattr(HUDConfig, "color_style", "auto") or "auto").strip().lower()
        if style == "green":
            base = (95, 255, 168)
        elif style == "amber":
            base = (255, 196, 96)
        elif style == "cyan":
            base = (112, 224, 255)
        elif style == "white":
            base = (240, 240, 240)
        else:
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
        """刷新叠加层几何，支持跟随主窗口或鼠标所在显示器。"""
        if HUDConfig.follow_main_window_monitor:
            monitor = self._get_main_window_monitor()
        else:
            monitor = None
            try:
                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                pt = POINT()
                if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                    monitor = Win32.get_monitor_at(int(pt.x), int(pt.y))
            except Exception:
                monitor = None
            if not monitor:
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
        self._secondary_targets = []
        self._render_reticle(force=True)

    def show_standby(self, text: str = "HUD STANDBY") -> None:
        """显示 HUD 待机文案。"""
        self._standby_text = str(text or "HUD STANDBY")
        self._set_standby_visible(True)

    def clear_standby(self) -> None:
        """隐藏 HUD 待机文案。"""
        self._set_standby_visible(False)

    def update_target(
        self,
        has_target: bool,
        relative_deg: float = 0.0,
        distance_km: float = 0.0,
        attitude_pitch_deg: float = 0.0,
        attitude_roll_deg: float = 0.0,
        attitude_fallback: bool = True,
        heading_deg: float = 0.0,
        secondary_targets: Optional[List[Dict[str, float]]] = None,
    ) -> None:
        """更新目标渲染输入。

        Args:
            has_target: 是否存在主目标
            relative_deg: 目标相对方位（左负右正）
            distance_km: 目标距离（公里）
            attitude_pitch_deg: 姿态俯仰角（度）
            attitude_roll_deg: 姿态横滚角（度）
            attitude_fallback: 姿态不可信时为 True，自动降级 2D
            heading_deg: 当前航向角（度）
            secondary_targets: 次目标列表（每项含 relative/distance）
        """
        self._has_target = bool(has_target)
        self._target_relative_deg = float(relative_deg)
        self._target_distance_km = max(0.0, float(distance_km))
        self._attitude_pitch_deg = float(attitude_pitch_deg)
        self._attitude_roll_deg = float(attitude_roll_deg)
        self._attitude_fallback = bool(attitude_fallback)
        self._heading_deg = float(heading_deg)
        cleaned_secondary: List[Dict[str, float]] = []
        if secondary_targets:
            for item in secondary_targets:
                if not isinstance(item, dict):
                    continue
                rel = float(item.get("relative", 0.0) or 0.0)
                dist = max(0.0, float(item.get("distance", 0.0) or 0.0))
                cleaned_secondary.append({"relative": rel, "distance": dist})
                if len(cleaned_secondary) >= 2:
                    break
        self._secondary_targets = cleaned_secondary
        self.clear_standby()
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
        heading = float(getattr(snapshot, "player_heading", 0.0) or 0.0)

        self.update_target(
            has_target=has_target,
            relative_deg=float(target_relative_deg),
            distance_km=float(target_distance_km),
            attitude_pitch_deg=pitch,
            attitude_roll_deg=roll,
            attitude_fallback=fallback,
            heading_deg=heading,
            secondary_targets=None,
        )

    def _on_focus_in(self, _event=None) -> None:
        if bool(getattr(self.app, "_locked", True)):
            self.apply_window_styles(click_through=True, alpha=HUDConfig.alpha)

    def _on_configure(self, _event=None) -> None:
        if self._standby_visible:
            self._position_standby()
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
        self._secondary_text_ids = [
            self.canvas.create_text(
                0, 0,
                text="",
                fill=color,
                font=("Segoe UI", 9, "bold"),
                state="hidden",
                tags=("hud_secondary",),
            ),
            self.canvas.create_text(
                0, 0,
                text="",
                fill=color,
                font=("Segoe UI", 9, "bold"),
                state="hidden",
                tags=("hud_secondary",),
            ),
        ]
        self._standby_id = self.canvas.create_text(
            0, 0,
            text="HUD STANDBY",
            fill="#8fb5a0",
            font=("Segoe UI", 12, "bold"),
            state="hidden",
            tags=("hud_standby",),
        )

    def _init_compass_items(self) -> None:
        """初始化顶部简化罗盘图元（仅执行一次）。"""
        color = "#5fffa8"
        self._compass_bg_id = self.canvas.create_rectangle(
            0, 0, 0, 0,
            outline="#2f5742",
            fill="#11261b",
            width=1,
            state="hidden",
            tags=("hud_compass",),
        )
        self._compass_axis_id = self.canvas.create_line(
            0, 0, 0, 0,
            fill=color,
            width=2,
            state="hidden",
            tags=("hud_compass",),
        )
        self._compass_center_id = self.canvas.create_line(
            0, 0, 0, 0,
            fill="#f8ffdc",
            width=2,
            state="hidden",
            tags=("hud_compass",),
        )
        for _ in self._compass_offsets:
            tick_id = self.canvas.create_line(
                0, 0, 0, 0,
                fill=color,
                width=1,
                state="hidden",
                tags=("hud_compass",),
            )
            label_id = self.canvas.create_text(
                0, 0,
                text="",
                fill=color,
                font=("Segoe UI", 8, "bold"),
                state="hidden",
                tags=("hud_compass",),
            )
            self._compass_tick_ids.append(tick_id)
            self._compass_label_ids.append(label_id)
        self._compass_heading_id = self.canvas.create_text(
            0, 0,
            text="",
            fill=color,
            font=("Segoe UI", 9, "bold"),
            state="hidden",
            tags=("hud_compass",),
        )
        self._compass_target_id = self.canvas.create_polygon(
            0, 0, 0, 0, 0, 0,
            outline="",
            fill=color,
            state="hidden",
            tags=("hud_compass",),
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
        for item_id in self._secondary_text_ids:
            self.canvas.itemconfig(item_id, state=state)
        if not visible:
            self._last_signature = None
            self._secondary_signature = None

    def _set_compass_visible(self, visible: bool) -> None:
        state = "normal" if visible else "hidden"
        for item_id in (
            self._compass_bg_id,
            self._compass_axis_id,
            self._compass_center_id,
            self._compass_heading_id,
            self._compass_target_id,
        ):
            if item_id is not None:
                self.canvas.itemconfig(item_id, state=state)
        for tick_id in self._compass_tick_ids:
            self.canvas.itemconfig(tick_id, state=state)
        for label_id in self._compass_label_ids:
            self.canvas.itemconfig(label_id, state=state)
        if not visible:
            self._compass_signature = None

    def _position_standby(self) -> None:
        w = max(1, int(self.window.winfo_width()))
        h = max(1, int(self.window.winfo_height()))
        cx = w * 0.5
        cy = h * 0.5
        if self._standby_id is not None:
            self.canvas.coords(self._standby_id, cx, cy)

    def _set_standby_visible(self, visible: bool) -> None:
        self._standby_visible = bool(visible)
        if self._standby_id is None:
            return
        if self._standby_visible:
            self._set_reticle_visible(False)
            self._set_compass_visible(False)
            self._position_standby()
            self.canvas.itemconfig(self._standby_id, text=self._standby_text, state="normal")
        else:
            self.canvas.itemconfig(self._standby_id, state="hidden")

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

    def _render_secondary_targets(self, width: int, height: int, color: str, force: bool = False) -> None:
        """渲染次目标文字（双侧布局，避免占用中心视野）。"""
        if not self._secondary_text_ids:
            return

        if not self._secondary_targets:
            for item_id in self._secondary_text_ids:
                self.canvas.itemconfig(item_id, state="hidden")
            self._secondary_signature = None
            return

        candidates = sorted(self._secondary_targets, key=lambda t: abs(float(t.get("relative", 0.0))))
        selected: List[Dict[str, float]] = []
        left_first = next((t for t in candidates if float(t.get("relative", 0.0)) < 0.0), None)
        right_first = next((t for t in candidates if float(t.get("relative", 0.0)) >= 0.0), None)
        if left_first is not None:
            selected.append(left_first)
        if right_first is not None and right_first is not left_first and len(selected) < 2:
            selected.append(right_first)
        if len(selected) < 2:
            for item in candidates:
                if item in selected:
                    continue
                selected.append(item)
                if len(selected) >= 2:
                    break

        signature = (
            tuple(
                (round(float(item.get("relative", 0.0)), 1), round(float(item.get("distance", 0.0)), 1))
                for item in selected
            ),
            color,
            width,
            height,
        )
        if (not force) and signature == self._secondary_signature:
            return
        self._secondary_signature = signature

        left_rows = 0
        right_rows = 0
        base_y = max(40.0, float(height) * 0.18)

        for idx, item_id in enumerate(self._secondary_text_ids):
            if idx >= len(selected):
                self.canvas.itemconfig(item_id, text="", state="hidden")
                continue

            rel = float(selected[idx].get("relative", 0.0))
            dist = max(0.0, float(selected[idx].get("distance", 0.0)))
            abs_rel = abs(rel)

            if rel < 0.0:
                row = left_rows
                left_rows += 1
                x = float(width) * 0.08
                y = base_y + (row * 18.0)
                text = f"< {abs_rel:.0f}°  {dist:.1f}km"
                anchor = "w"
            else:
                row = right_rows
                right_rows += 1
                x = float(width) * 0.92
                y = base_y + (row * 18.0)
                text = f"{dist:.1f}km  {abs_rel:.0f}° >"
                anchor = "e"

            self.canvas.coords(item_id, x, y)
            self.canvas.itemconfig(item_id, text=text, fill=color, anchor=anchor, state="normal")

    def _render_compass(self, width: int, height: int, color: str, force: bool = False) -> None:
        """渲染顶部简化罗盘条（与主靶子同步更新）。"""
        if not bool(getattr(HUDConfig, "compass_enabled", True)):
            self._set_compass_visible(False)
            return

        bar_w = max(180.0, float(width) * self._COMPASS_WIDTH_RATIO)
        bar_h = self._COMPASS_BAR_HEIGHT_PX
        half_w = bar_w * 0.5
        cx = float(width) * 0.5
        top = max(10.0, float(height) * self._COMPASS_TOP_RATIO)
        left = cx - half_w
        right = cx + half_w
        bottom = top + bar_h
        axis_y = top + (bar_h * 0.5)

        clamped_rel = self._clamp(
            self._target_relative_deg,
            -self._COMPASS_VISIBLE_HALF_DEG,
            self._COMPASS_VISIBLE_HALF_DEG,
        )
        target_x = cx + (clamped_rel / self._COMPASS_VISIBLE_HALF_DEG) * half_w

        signature = (
            round(cx, 1),
            round(top, 1),
            round(bar_w, 1),
            round(self._normalize_heading_deg(self._heading_deg), 1),
            round(clamped_rel, 1),
            color,
            int(self._attitude_fallback),
        )
        if (not force) and signature == self._compass_signature:
            return
        self._compass_signature = signature

        self._set_compass_visible(True)

        bg_fill = "#2a1f12" if self._attitude_fallback else "#11261b"
        bg_outline = "#6f5738" if self._attitude_fallback else "#2f5742"
        self.canvas.coords(self._compass_bg_id, left, top, right, bottom)
        self.canvas.itemconfig(self._compass_bg_id, fill=bg_fill, outline=bg_outline)

        self.canvas.coords(self._compass_axis_id, left + 8.0, axis_y, right - 8.0, axis_y)
        self.canvas.itemconfig(self._compass_axis_id, fill=color)

        self.canvas.coords(self._compass_center_id, cx, top + 2.0, cx, bottom - 2.0)

        for idx, offset_deg in enumerate(self._compass_offsets):
            x = cx + (offset_deg / self._COMPASS_VISIBLE_HALF_DEG) * half_w
            major = int(abs(offset_deg)) % int(self._COMPASS_MAJOR_STEP_DEG) == 0
            tick_half = 7.0 if major else 4.0

            tick_id = self._compass_tick_ids[idx]
            self.canvas.coords(tick_id, x, axis_y - tick_half, x, axis_y + tick_half)
            self.canvas.itemconfig(tick_id, fill=color, width=2 if major else 1)

            label_id = self._compass_label_ids[idx]
            if major:
                tick_heading = self._normalize_heading_deg(self._heading_deg + offset_deg)
                tick_text = self._compass_label(tick_heading)
                self.canvas.coords(label_id, x, bottom + 8.0)
                self.canvas.itemconfig(label_id, text=tick_text, fill=color, state="normal")
            else:
                self.canvas.itemconfig(label_id, text="", state="hidden")

        hdg_value = int(round(self._normalize_heading_deg(self._heading_deg))) % 360
        self.canvas.coords(self._compass_heading_id, cx, top - 8.0)
        self.canvas.itemconfig(self._compass_heading_id, text=f"HDG {hdg_value:03d}", fill=color)

        marker_top = bottom + 2.0
        marker_w = self._COMPASS_TARGET_MARKER_W
        marker_h = self._COMPASS_TARGET_MARKER_H
        self.canvas.coords(
            self._compass_target_id,
            target_x, marker_top + marker_h,
            target_x - marker_w, marker_top,
            target_x + marker_w, marker_top,
        )
        self.canvas.itemconfig(self._compass_target_id, fill=color)

    def _render_reticle(self, force: bool = False) -> None:
        if not self._visible:
            return

        if not self._has_target:
            self._set_reticle_visible(False)
            self._set_compass_visible(False)
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
        self._render_compass(width, height, color=color, force=force)
        self._render_secondary_targets(width, height, color=color, force=force)
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
