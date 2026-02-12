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

    # 透视投影参数（v6.8.2: 统一垂直轴 + 2D roll 旋转）
    _MAX_RELATIVE_DEG = 80.0           # tan()安全裁剪上限（避免极端值）
    _MAX_LOOKDOWN_DEG = 78.0
    _PITCH_BLEND_NEAR_KM = 4.0         # 用户反馈近距(3-4km)表现较好，保留全量pitch
    _PITCH_BLEND_FAR_KM = 14.0
    _PITCH_GAIN_NEAR = 1.0
    _PITCH_GAIN_FAR = 0.62
    _DIVE_EXTRA_DAMP_MAX = 0.18        # 俯冲远距额外抑制比例上限

    # 距离 -> 尺寸/亮度映射参数
    _DIST_NEAR_KM = 2.0
    _DIST_FAR_KM = 40.0
    _BASE_RADIUS_PX = 16.0
    _RADIUS_MIN_SCALE = 0.75
    _RADIUS_MAX_SCALE = 1.85
    _BRIGHTNESS_MIN = 0.35
    _BRIGHTNESS_MAX = 1.00
    _MAX_SECONDARY_TARGETS = 6

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
        self._transparent_color_ref = self._hex_to_colorref(self._transparent_color)
        self._transparent_color_supported = False

        self.window = tk.Toplevel(self.root)
        self.window.title("HUD Overlay")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=self._transparent_color)
        self.window.withdraw()

        # 尽量使用透明色键；不支持时降级为普通透明窗口。
        try:
            self.window.attributes("-transparentcolor", self._transparent_color)
            self._transparent_color_supported = True
        except tk.TclError:
            self._transparent_color_supported = False

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
        self._player_altitude_m = 0.0

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
        self._secondary_marker_ids: List[int] = []
        self._secondary_label_ids: List[int] = []
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

    @staticmethod
    def _hex_to_colorref(hex_color: str) -> int:
        """将 '#RRGGBB' 转为 Win32 COLORREF(0x00bbggrr)。"""
        text = str(hex_color or "").strip()
        if text.startswith("#"):
            text = text[1:]
        if len(text) != 6:
            return 0
        try:
            r = int(text[0:2], 16)
            g = int(text[2:4], 16)
            b = int(text[4:6], 16)
        except ValueError:
            return 0
        return (b << 16) | (g << 8) | r

    @classmethod
    def _pitch_gain_for_distance(cls, distance_km: float, pitch_deg: float) -> float:
        """远距降低 pitch 权重，缓解俯冲时的远距离垂直误差放大。"""
        d = max(0.0, float(distance_km))
        if cls._PITCH_BLEND_FAR_KM <= cls._PITCH_BLEND_NEAR_KM:
            gain = cls._PITCH_GAIN_NEAR
        else:
            t = (d - cls._PITCH_BLEND_NEAR_KM) / (cls._PITCH_BLEND_FAR_KM - cls._PITCH_BLEND_NEAR_KM)
            t = max(0.0, min(1.0, t))
            gain = cls._PITCH_GAIN_NEAR + (cls._PITCH_GAIN_FAR - cls._PITCH_GAIN_NEAR) * t

        # 远距俯冲额外抑制，避免目标在屏幕上方过度漂移
        if float(pitch_deg) < 0.0:
            t_dive = (d - cls._PITCH_BLEND_NEAR_KM) / max(1.0, (cls._PITCH_BLEND_FAR_KM - cls._PITCH_BLEND_NEAR_KM))
            t_dive = max(0.0, min(1.0, t_dive))
            gain *= (1.0 - cls._DIVE_EXTRA_DAMP_MAX * t_dive)

        return float(gain)

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
        if self._has_target:
            if self._target_distance_km <= 8.0:
                alpha = max(alpha, 0.78)
            elif self._target_distance_km <= 18.0:
                alpha = max(alpha, 0.62)
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
        """应用 HUD 窗口样式。

        优先使用 Win32 color key 保证背景透明，避免出现整屏黑底/蒙层。
        """
        target_alpha = HUDConfig.alpha if alpha is None else alpha
        target_alpha = max(30, min(255, int(target_alpha)))
        Win32.setup_window(
            self.hwnd,
            click_through=bool(click_through),
            alpha=target_alpha,
            color_key=self._transparent_color_ref,
        )

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
        own_altitude_m: float = 0.0,
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
            own_altitude_m: 自身高度（米，用于近距/越顶几何修正）
            secondary_targets: 次目标列表（每项含 relative/distance）
        """
        self._has_target = bool(has_target)
        self._target_relative_deg = float(relative_deg)
        self._target_distance_km = max(0.0, float(distance_km))
        self._attitude_pitch_deg = float(attitude_pitch_deg)
        self._attitude_roll_deg = float(attitude_roll_deg)
        self._attitude_fallback = bool(attitude_fallback)
        self._heading_deg = float(heading_deg)
        self._player_altitude_m = max(0.0, float(own_altitude_m))
        cleaned_secondary: List[Dict[str, float]] = []
        if secondary_targets:
            for item in secondary_targets:
                if not isinstance(item, dict):
                    continue
                rel = float(item.get("relative", 0.0) or 0.0)
                dist = max(0.0, float(item.get("distance", 0.0) or 0.0))
                label = str(item.get("label", "") or "").strip()
                cleaned_secondary.append({"relative": rel, "distance": dist, "label": label})
                if len(cleaned_secondary) >= self._MAX_SECONDARY_TARGETS:
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
        altitude = float(getattr(snapshot, "altitude_m", 0.0) or 0.0)

        self.update_target(
            has_target=has_target,
            relative_deg=float(target_relative_deg),
            distance_km=float(target_distance_km),
            attitude_pitch_deg=pitch,
            attitude_roll_deg=roll,
            attitude_fallback=fallback,
            heading_deg=heading,
            own_altitude_m=altitude,
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
        self._secondary_marker_ids = []
        self._secondary_label_ids = []
        for _ in range(self._MAX_SECONDARY_TARGETS):
            marker_id = self.canvas.create_oval(
                0, 0, 0, 0,
                outline=color,
                width=2,
                state="hidden",
                tags=("hud_secondary",),
            )
            self._secondary_marker_ids.append(marker_id)
            label_id = self.canvas.create_text(
                0, 0,
                text="",
                fill=color,
                font=("Segoe UI", 8, "bold"),
                state="hidden",
                tags=("hud_secondary",),
            )
            self._secondary_label_ids.append(label_id)
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
        for item_id in self._secondary_marker_ids:
            self.canvas.itemconfig(item_id, state=state)
        for item_id in self._secondary_label_ids:
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

    def _project_point(self, width: int, height: int, relative_deg: float, distance_km: float) -> tuple:
        """根据相对方位 + 姿态 + 几何关系估计目标屏幕位置。

        v6.8.2: 垂直轴 pitch+lookdown 合并为统一 vertical_angle，
        roll 从 Y-only 近似改为完整 2D 旋转矩阵，
        垂直轴也使用 tan() 透视投影保持一致。

        WT pitch 符号约定: aviahorizon_pitch 正值=抬头, 负值=低头。
        """
        cx = width * 0.5
        cy = height * 0.5
        rel = self._clamp(relative_deg, -self._MAX_RELATIVE_DEG, self._MAX_RELATIVE_DEG)

        # === X: tan() 透视投影 ===
        h_fov = HUDConfig.horizontal_fov_deg
        tan_hh = math.tan(math.radians(h_fov * 0.5))
        dx = (math.tan(math.radians(rel)) / tan_hh) * (width * 0.5)

        # === Y: 统一 vertical_angle 计算 ===
        if self._attitude_fallback:
            dy = 0.0
        else:
            v_fov = HUDConfig.vertical_fov_deg
            tan_hv = math.tan(math.radians(v_fov * 0.5))

            # 目标俯角（高度/水平距离）
            horiz_m = max(120.0, float(distance_km) * 1000.0)
            lookdown_deg = math.degrees(math.atan2(
                max(0.0, self._player_altitude_m), horiz_m))
            lookdown_deg = self._clamp(lookdown_deg, 0.0, self._MAX_LOOKDOWN_DEG)

            # 合并: vertical_angle = lookdown + pitch
            # 远距时降低 pitch 贡献，抑制俯冲场景下的纵向误差放大。
            # 正值 = 目标在摄像机中心下方 → 屏幕正Y方向（下移）
            # 抬头(pitch>0) → 地面目标更靠下 ✓
            # 俯冲(pitch<0) → 地面目标更靠上 ✓
            pitch_gain = self._pitch_gain_for_distance(distance_km, self._attitude_pitch_deg)
            effective_pitch_deg = self._attitude_pitch_deg * pitch_gain
            vertical_angle = lookdown_deg + effective_pitch_deg
            vert_clamped = self._clamp(vertical_angle,
                                       -self._MAX_LOOKDOWN_DEG,
                                        self._MAX_LOOKDOWN_DEG)
            dy = (math.tan(math.radians(vert_clamped)) / tan_hv) * (height * 0.5)

        # === Roll: 完整 2D 旋转 ===
        # 飞机右滚(roll>0)时，世界在视野中逆时针旋转
        if not self._attitude_fallback and abs(self._attitude_roll_deg) > 0.5:
            r = math.radians(self._attitude_roll_deg)
            c, s = math.cos(r), math.sin(r)
            dx, dy = dx * c + dy * s, -dx * s + dy * c

        target_x = self._clamp(cx + dx, width * 0.06, width * 0.94)
        target_y = self._clamp(cy + dy, height * 0.08, height * 0.92)

        return target_x, target_y, rel

    def _project_target(self, width: int, height: int) -> tuple:
        return self._project_point(width, height, self._target_relative_deg, self._target_distance_km)

    def _direction_prompt(self, rel: float) -> str:
        """2D 降级时的方向提示文本。"""
        if rel <= -8.0:
            return "←"
        if rel >= 8.0:
            return "→"
        return ""

    def _render_secondary_targets(
        self,
        width: int,
        height: int,
        color: str,
        primary_x: float,
        primary_y: float,
        primary_radius: float,
        force: bool = False,
    ) -> None:
        """渲染次目标图形标记（与主目标同屏显示）。"""
        if not self._secondary_marker_ids:
            return

        candidates = sorted(self._secondary_targets, key=lambda t: abs(float(t.get("relative", 0.0))))
        selected = candidates[:len(self._secondary_marker_ids)]
        if not selected:
            for item_id in self._secondary_marker_ids:
                self.canvas.itemconfig(item_id, state="hidden")
            for item_id in self._secondary_label_ids:
                self.canvas.itemconfig(item_id, text="", state="hidden")
            self._secondary_signature = None
            return

        signature = (
            tuple(
                (
                    round(float(item.get("relative", 0.0)), 1),
                    round(float(item.get("distance", 0.0)), 1),
                    str(item.get("label", "") or ""),
                )
                for item in selected
            ),
            round(self._attitude_pitch_deg, 1),
            round(self._attitude_roll_deg, 1),
            round(self._player_altitude_m, 0),
            int(self._attitude_fallback),
            color,
            width,
            height,
            round(primary_x, 1),
            round(primary_y, 1),
            round(primary_radius, 1),
        )
        if (not force) and signature == self._secondary_signature:
            return
        self._secondary_signature = signature

        secondary_color = self._color_from_brightness(0.62, self._attitude_fallback)
        for idx, item_id in enumerate(self._secondary_marker_ids):
            label_id = self._secondary_label_ids[idx] if idx < len(self._secondary_label_ids) else None
            if idx >= len(selected):
                self.canvas.itemconfig(item_id, state="hidden")
                if label_id is not None:
                    self.canvas.itemconfig(label_id, text="", state="hidden")
                continue
            rel = float(selected[idx].get("relative", 0.0))
            dist = max(0.0, float(selected[idx].get("distance", 0.0)))
            x, y, _ = self._project_point(width, height, rel, dist)

            dx = x - float(primary_x)
            dy = y - float(primary_y)
            distance_to_primary = math.hypot(dx, dy)
            min_gap = max(22.0, float(primary_radius) * 2.1)
            if distance_to_primary < min_gap:
                if distance_to_primary < 1e-3:
                    dx, dy, distance_to_primary = 1.0, 0.0, 1.0
                push = (min_gap - distance_to_primary) + 9.0
                x += (dx / distance_to_primary) * push
                y += (dy / distance_to_primary) * push

            x = self._clamp(x, width * 0.05, width * 0.95)
            y = self._clamp(y, height * 0.08, height * 0.92)
            dist_t = self._normalize_distance(dist)
            marker_r = self._BASE_RADIUS_PX * float(HUDConfig.scale) * self._lerp(1.0, 0.58, dist_t) * 0.52
            marker_r = max(7.0, marker_r)
            self.canvas.coords(item_id, x - marker_r, y - marker_r, x + marker_r, y + marker_r)
            self.canvas.itemconfig(item_id, outline=secondary_color, width=2, state="normal")

            if label_id is not None:
                label = str(selected[idx].get("label", "") or "").strip()
                if label:
                    text = f"{label} {dist:.1f}km"
                else:
                    text = f"{dist:.1f}km"
                self.canvas.coords(label_id, x, y - marker_r - 10.0)
                self.canvas.itemconfig(label_id, text=text, fill=secondary_color, state="normal")

    def _render_compass(self, width: int, height: int, color: str, force: bool = False) -> None:
        """HUD 层不再渲染导航条，避免与主导航系统重复。"""
        self._set_compass_visible(False)

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
        mode_text = self._direction_prompt(rel) if self._attitude_fallback else ""
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
        self._render_secondary_targets(
            width,
            height,
            color=color,
            primary_x=cx,
            primary_y=cy,
            primary_radius=radius,
            force=force,
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

        self.canvas.itemconfig(self._reticle_mode_id, text=mode_text, state="normal" if mode_text else "hidden")
        self.canvas.itemconfig(self._reticle_dist_id, text=dist_text)

        self.canvas.itemconfig(self._reticle_ring_id, outline=color, width=stroke)
        self.canvas.itemconfig(self._reticle_hline_id, fill=color, width=stroke)
        self.canvas.itemconfig(self._reticle_vline_id, fill=color, width=stroke)
        self.canvas.itemconfig(self._reticle_mode_id, fill=color)
        self.canvas.itemconfig(self._reticle_dist_id, fill=color)
