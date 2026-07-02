"""Reusable UI widgets."""

import tkinter as tk
import tkinter.font as tkfont
from typing import Any

from bomana.config import Theme, UIConfig, ZoneConfig
from bomana.utils.math_utils import (
    calculate_heading_tape_scale,
    format_distance_dynamic,
    get_cdi_tolerance,
    get_deviation_color,
)
from bomana.utils.system import resolve_tk_font_tuple


class Pill(tk.Label):
    """徽章组件（圆角矩形标签）

    用于显示状态徽章，如"战斗中"、"就绪✓"等。
    """

    def __init__(self, parent, text="", fg=Theme.TEXT, bg=Theme.GRAYPILL, font=None):
        super().__init__(
            parent,
            text=text,
            fg=fg,
            bg=bg,
            bd=0,
            relief="flat",
            padx=8,
            pady=1,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            highlightcolor=Theme.SEPARATOR,
        )
        if font:
            self.configure(font=font)
        self._apply_padding(text)

    def _apply_padding(self, text: str):
        """更新标签文本。"""
        self.configure(text=text)

    def set(self, text: str, fg: str, bg: str):
        """更新徽章内容和颜色"""
        self.configure(fg=fg, bg=bg)
        self._apply_padding(text)


class HeadingTape(tk.Canvas):
    """统一航向带指示器 (Heading Tape)

    v6.2重构: 合并战区/机场到同一航向带，支持多目标显示

    目标类型及标记:
    - zone: 战区目标 - 红色标靶 ⊚
    - friendly: 友方机场 - 蓝色飞机 ✈
    - enemy: 敌方机场 - 橙色飞机 ✈
    - destroyed: 被摧毁战区 - 灰色X ✕

    特性:
    - 同时显示多个不同类型的目标
    - 主目标（战区）有偏航提示
    - 被摧毁的战区用特殊标记显示
    """

    def __init__(
        self, parent, width: int = 280, height: int = 36, text_scale: float = 1.0, **kwargs
    ):
        """初始化航向带

        Args:
            parent: 父容器
            width: 宽度(像素)
            height: 高度(像素)
        """
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=Theme.BG,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            highlightcolor=Theme.SEPARATOR,
            **kwargs,
        )
        self.text_scale = UIConfig.clamp_text_scale(text_scale)
        self.tape_width = width
        self._font_object_cache: dict[str, tkfont.Font] = {}
        self._font_metric_cache: dict[tuple[str, str], int] = {}
        self._measure_cache: dict[tuple[str, str], int] = {}
        self._layout_cache_key: tuple[float, int] | None = None
        self._layout_cache: dict[str, Any] | None = None
        self.tape_height = max(height, self._required_tape_height())
        if self.tape_height != height:
            self.configure(height=self.tape_height)
        self.pixels_per_degree = ZoneConfig.HEADING_TAPE_PIXELS_PER_DEG
        self._current_hdg = 0.0
        self._primary_target = None
        self._last_render_signature = None
        self._last_targets = []
        self._last_primary_distance_km = 0.0
        self.bind("<Configure>", self._on_configure, add="+")

        # 目标类型颜色配置
        self._target_colors = {
            "zone": Theme.RED,
            "poi": Theme.YELLOW,
            "friendly": Theme.BLUE,
            "enemy": Theme.ORANGE,
            "destroyed": Theme.TEXT_MUTED,
        }

    def _scaled_text_size(self, base_size: float, *, min_size: int = 1) -> int:
        return max(int(min_size), int(float(base_size) * float(self.text_scale)))

    def _font(self, size: int, *, weight: str | None = None, family: str = "Consolas"):
        font = (family, size, weight) if weight else (family, size)
        resolved = resolve_tk_font_tuple(self, font)
        return resolved if isinstance(resolved, tuple) else font

    def _font_object(self, font) -> tkfont.Font:
        key = repr(font)
        cached = self._font_object_cache.get(key)
        if cached is None:
            cached = tkfont.Font(master=self, font=font)
            self._font_object_cache[key] = cached
        return cached

    def _font_linespace(self, font) -> int:
        key = ("linespace", repr(font))
        cached = self._font_metric_cache.get(key)
        if cached is None:
            cached = int(self._font_object(font).metrics("linespace"))
            self._font_metric_cache[key] = cached
        return cached

    def _measure_text(self, text: str, font) -> int:
        key = (repr(font), text)
        cached = self._measure_cache.get(key)
        if cached is None:
            if len(self._measure_cache) > 512:
                self._measure_cache.clear()
            cached = int(self._font_object(font).measure(text))
            self._measure_cache[key] = cached
        return cached

    def _layout_metrics(self) -> dict[str, Any]:
        cache_key = (float(self.text_scale), int(self.tape_height))
        if self._layout_cache_key == cache_key and self._layout_cache is not None:
            return self._layout_cache

        scale = float(self.text_scale)
        degree_font_size = self._scaled_text_size(8, min_size=7)
        distance_font_size = self._scaled_text_size(9, min_size=7)
        distance_small_font_size = self._scaled_text_size(7, min_size=6)
        overflow_font_size = self._scaled_text_size(7, min_size=6)
        arrow_font_size = self._scaled_text_size(10, min_size=8)

        degree_font = self._font(degree_font_size)
        distance_font = self._font(distance_font_size)
        distance_bold_font = self._font(distance_font_size, weight="bold")
        distance_small_font = self._font(distance_small_font_size)
        overflow_font = self._font(overflow_font_size, weight="bold")
        arrow_font = self._font(arrow_font_size, weight="bold", family="Arial")

        distance_linespace = max(
            self._font_linespace(distance_font),
            self._font_linespace(distance_bold_font),
            self._font_linespace(distance_small_font),
        )

        top_pad = max(2, int(2 * scale))
        bottom_pad = max(2, int(2 * scale))
        row_gap = max(2, int(2 * scale))
        marker_scale = max(0.85, scale)
        marker_half = max(8, int(9 * marker_scale))
        tick_major = max(12, int(12 * scale))
        tick_mid = max(8, int(tick_major * 0.65))
        tick_small = max(5, int(tick_major * 0.45))

        tick_top = top_pad
        tick_major_bottom = tick_top + tick_major
        degree_text_y = tick_major_bottom + row_gap
        distance_y = self.tape_height - bottom_pad
        distance_top = distance_y - distance_linespace
        marker_top_limit = top_pad + marker_half
        marker_bottom_limit = distance_top - row_gap - marker_half
        if marker_bottom_limit >= marker_top_limit:
            marker_center_y = int((marker_top_limit + marker_bottom_limit) / 2)
        else:
            marker_center_y = int(marker_top_limit)

        metrics: dict[str, Any] = {
            "top_pad": top_pad,
            "bottom_pad": bottom_pad,
            "row_gap": row_gap,
            "tick_top": tick_top,
            "tick_major_bottom": tick_major_bottom,
            "tick_mid_bottom": tick_top + tick_mid,
            "tick_small_bottom": tick_top + tick_small,
            "degree_text_y": degree_text_y,
            "degree_font": degree_font,
            "distance_y": distance_y,
            "distance_linespace": distance_linespace,
            "distance_font": distance_font,
            "distance_bold_font": distance_bold_font,
            "distance_small_font": distance_small_font,
            "overflow_font": overflow_font,
            "arrow_font": arrow_font,
            "marker_scale": marker_scale,
            "marker_center_y": marker_center_y,
            "marker_half": marker_half,
        }
        self._layout_cache_key = cache_key
        self._layout_cache = metrics
        return metrics

    def _required_tape_height(self) -> int:
        degree_font_size = self._scaled_text_size(8, min_size=7)
        distance_font_size = self._scaled_text_size(9, min_size=7)
        scale = float(self.text_scale)
        top_pad = max(2, int(2 * scale))
        bottom_pad = max(2, int(2 * scale))
        row_gap = max(2, int(2 * scale))
        tick_major = max(12, int(12 * scale))
        marker_half = max(8, int(9 * max(0.85, scale)))
        degree_linespace = self._font_linespace(self._font(degree_font_size))
        distance_linespace = self._font_linespace(self._font(distance_font_size))
        top_band_height = max(
            tick_major + row_gap + degree_linespace,
            marker_half * 2,
        )
        return top_pad + top_band_height + row_gap + distance_linespace + bottom_pad

    def update_tape_multi(
        self, current_hdg: float, targets: list | None = None, primary_distance_km: float = 0.0
    ):
        """更新航向带显示（多目标版本）

        Args:
            current_hdg: 当前航向(0-360°)
            targets: 目标列表，每个目标为dict:
                {
                    'type': 'zone'/'poi'/'friendly'/'enemy'/'destroyed',
                    'relative': 相对角度(-180~180),
                    'distance_km': 距离(公里),
                    'is_primary': 是否主目标(用于偏航提示),
                    'name': 目标名称(可选)
                }
            primary_distance_km: 主目标距离(用于计算缩放)
        """
        if targets is None:
            targets = []
        self._last_targets = [dict(t) for t in targets]
        self._last_primary_distance_km = float(primary_distance_km or 0.0)

        # 高频刷新场景下跳过等效帧重绘，降低Canvas CPU/GDI开销
        render_signature = (
            round(float(current_hdg) * 5),  # 0.2°精度
            round(float(primary_distance_km) * 10),  # 0.1km精度
            tuple(
                (
                    t.get("type", "zone"),
                    round(float(t.get("relative", 0.0)) * 5),
                    round(float(t.get("distance_km", 0.0)) * 10),
                    bool(t.get("is_primary", False)),
                    bool(t.get("is_target", True)),
                )
                for t in targets
            ),
        )
        if render_signature == self._last_render_signature:
            return
        self._last_render_signature = render_signature

        required_height = self._required_tape_height()
        if self.tape_height < required_height:
            self.tape_height = required_height
            self.configure(height=required_height)

        layout = self._layout_metrics()
        self.delete("all")
        self._current_hdg = current_hdg
        self.create_rectangle(
            0,
            0,
            self.tape_width - 1,
            self.tape_height - 1,
            outline=Theme.SEPARATOR,
            width=1,
        )

        # 找出主目标（用于偏航提示和缩放计算）
        primary = next((t for t in targets if t.get("is_primary")), None)
        self._primary_target = primary

        # 1. 动态计算缩放系数（基于主目标距离）
        dist_for_scale = (
            primary_distance_km
            if primary_distance_km > 0
            else (primary["distance_km"] if primary else 10.0)
        )
        scale_factor = calculate_heading_tape_scale(dist_for_scale)
        ppd = self.pixels_per_degree * scale_factor

        center_x = self.tape_width / 2

        # 2. 检查主目标是否在视野外（用于偏航提示）
        primary_diff = 0.0
        primary_in_view = True
        if primary:
            primary_diff = primary["relative"]
            primary_x = center_x + primary_diff * ppd
            primary_in_view = 0 <= primary_x <= self.tape_width

            # 主目标在视野外时，绘制偏航背景
            if not primary_in_view:
                if primary_diff < 0:
                    self.create_rectangle(
                        0, 0, 50, self.tape_height, fill=Theme.RED, stipple="gray50", outline=""
                    )
                else:
                    self.create_rectangle(
                        self.tape_width - 50,
                        0,
                        self.tape_width,
                        self.tape_height,
                        fill=Theme.RED,
                        stipple="gray50",
                        outline="",
                    )

        # 3. 绘制背景分割线
        self.create_line(
            0,
            self.tape_height - 1,
            self.tape_width,
            self.tape_height - 1,
            fill=Theme.BORDER,
            width=1,
        )

        # 4. 绘制刻度
        visible_degrees = self.tape_width / ppd
        start_deg = current_hdg - visible_degrees / 2 - 5
        end_deg = current_hdg + visible_degrees / 2 + 5

        for d in range(int(start_deg) - 1, int(end_deg) + 2):
            display_d = d % 360
            if display_d < 0:
                display_d += 360

            diff = d - current_hdg
            while diff > 180:
                diff -= 360
            while diff < -180:
                diff += 360

            x = center_x + diff * ppd

            if x < -20 or x > self.tape_width + 20:
                continue

            if display_d % 10 == 0:
                self.create_line(
                    x,
                    layout["tick_top"],
                    x,
                    layout["tick_major_bottom"],
                    fill=Theme.TEXT,
                    width=2,
                )
                self.create_text(
                    x,
                    layout["degree_text_y"],
                    text=f"{display_d:03d}",
                    fill=Theme.TEXT,
                    font=layout["degree_font"],
                    anchor="n",
                )
            elif display_d % 5 == 0:
                self.create_line(
                    x,
                    layout["tick_top"] + 2,
                    x,
                    layout["tick_mid_bottom"],
                    fill=Theme.TEXT_DIM,
                    width=1,
                )
            elif scale_factor >= 2.0:
                self.create_line(
                    x,
                    layout["tick_top"] + 4,
                    x,
                    layout["tick_small_bottom"],
                    fill=Theme.TEXT_MUTED,
                    width=1,
                )

        # 5. 绘制所有目标标记（按优先级：destroyed < enemy < friendly < zone < poi）
        sorted_targets = sorted(
            targets,
            key=lambda t: {"destroyed": 0, "enemy": 1, "friendly": 2, "zone": 3, "poi": 4}.get(
                t.get("type", "zone"), 2
            ),
        )

        for target in sorted_targets:
            t_type = target.get("type", "zone")
            t_rel = target.get("relative", 0)
            t_is_primary = target.get("is_primary", False)
            t_is_target = target.get("is_target", True)  # v6.3: 是否为活动目标
            t_distance = target.get("distance_km", 0)  # v6.4.1: 获取目标自身距离

            t_x = center_x + t_rel * ppd
            in_view = 0 <= t_x <= self.tape_width

            if in_view:
                self._draw_target_marker(
                    t_x,
                    t_type,
                    t_is_primary,
                    t_rel,
                    primary["distance_km"] if primary else 10.0,
                    is_target=t_is_target,
                    show_distance=t_distance,
                    layout=layout,
                )
            else:
                # 视野外目标显示小箭头（只显示活动目标）
                if t_is_target:
                    self._draw_overflow_indicator(t_rel, t_type, t_distance, layout=layout)

        # 6. 主目标在视野外时的大箭头提示
        if primary and not primary_in_view:
            self._draw_primary_overflow(primary_diff, layout=layout)

        # 7. 绘制中心基准线（机头指向）
        self.create_line(
            center_x, 0, center_x, self.tape_height, fill=Theme.GREEN, width=2, dash=(3, 2)
        )
        tri_size = 5
        self.create_polygon(
            center_x,
            0,
            center_x - tri_size,
            tri_size + 2,
            center_x + tri_size,
            tri_size + 2,
            fill=Theme.GREEN,
            outline="",
        )

    def _on_configure(self, event) -> None:
        """Redraw when the widget gets resized by layout."""
        new_width = max(1, int(getattr(event, "width", self.tape_width)))
        min_height = self._required_tape_height()
        event_height = int(getattr(event, "height", self.tape_height))
        new_height = max(min_height, event_height)
        if event_height < min_height:
            self.configure(height=min_height)
        if new_width == self.tape_width and new_height == self.tape_height:
            return
        self.tape_width = new_width
        self.tape_height = new_height
        self._last_render_signature = None
        self.update_tape_multi(
            self._current_hdg, self._last_targets, self._last_primary_distance_km
        )

    def _draw_target_marker(
        self,
        x: float,
        t_type: str,
        is_primary: bool,
        relative: float,
        distance_km: float,
        is_target: bool = True,
        show_distance: float = 0,
        layout: dict[str, Any] | None = None,
    ):
        """绘制目标标记

        Args:
            x: X坐标
            t_type: 目标类型
            is_primary: 是否主目标
            relative: 相对角度
            distance_km: 距离（用于颜色计算）
            is_target: 是否为活动目标（v6.3新增）
            show_distance: 显示的距离值（v6.4.1新增，0表示不显示）
        """
        # v6.3: 根据是否为目标调整颜色和透明度
        # v6.6.1: 提亮非目标颜色，增强可见度
        base_color = self._target_colors.get(t_type, Theme.TEXT)

        if not is_target:
            # 非目标：使用中等亮度颜色（比之前更亮）
            color_map = {
                Theme.RED: "#CC6666",  # 中红（更亮）
                Theme.BLUE: "#6688BB",  # 中蓝（更亮）
                Theme.ORANGE: "#CC9966",  # 中橙（更亮）
            }
            color = color_map.get(base_color, Theme.TEXT_DIM)
        else:
            color = base_color
        layout = layout or self._layout_metrics()
        icon_scale = float(layout["marker_scale"])
        y_center = int(layout["marker_center_y"])

        # v6.6.1: 为所有目标显示距离标签（非目标使用弱化样式）
        if show_distance > 0:
            self._draw_distance_label(
                x,
                show_distance,
                t_type,
                is_primary,
                icon_scale,
                y_center,
                relative,
                is_target,
                layout=layout,
            )

        if t_type == "zone":
            # v6.3: 战区标靶 - 区分目标和非目标
            # v6.5.2: 调小尺寸，给距离标签腾空间
            if is_primary:
                size = int(8 * icon_scale)
                # 主目标根据精度调整颜色
                tolerance = get_cdi_tolerance(distance_km)
                abs_rel = abs(relative)
                if abs_rel < 0.2:
                    color = "#FF4444"  # 亮红
                elif abs_rel < tolerance * 0.5:
                    color = Theme.RED
                elif abs_rel < tolerance:
                    color = "#CC3333"  # 暗红
                else:
                    color = Theme.ORANGE  # 偏航时变橙
                # 绘制实心标靶（外圈+内圈）
                self.create_oval(
                    x - size,
                    y_center - size,
                    x + size,
                    y_center + size,
                    outline=color,
                    width=2,
                    fill="",
                )
                inner_size = size * 0.5
                self.create_oval(
                    x - inner_size,
                    y_center - inner_size,
                    x + inner_size,
                    y_center + inner_size,
                    fill=color,
                    outline="",
                )
            elif is_target:
                # 活动目标但非主目标：中等大小，实心
                size = int(6 * icon_scale)
                self.create_oval(
                    x - size,
                    y_center - size,
                    x + size,
                    y_center + size,
                    outline=color,
                    width=2,
                    fill="",
                )
                inner_size = size * 0.5
                self.create_oval(
                    x - inner_size,
                    y_center - inner_size,
                    x + inner_size,
                    y_center + inner_size,
                    fill=color,
                    outline="",
                )
            else:
                # v6.6.1: 非目标战区：实心小圈（更明显）
                size = int(5 * icon_scale)
                # 使用实心圆点代替虚线圈
                self.create_oval(
                    x - size,
                    y_center - size,
                    x + size,
                    y_center + size,
                    outline=color,
                    width=1,
                    fill="",
                )
                # 更大的中心点
                dot_size = 3
                self.create_oval(
                    x - dot_size,
                    y_center - dot_size,
                    x + dot_size,
                    y_center + dot_size,
                    fill=color,
                    outline="",
                )

        elif t_type == "poi":
            size = int((8 if is_primary else 6) * icon_scale)
            width = 2 if is_target else 1
            self.create_polygon(
                x,
                y_center - size,
                x + size,
                y_center,
                x,
                y_center + size,
                x - size,
                y_center,
                outline=color,
                fill="" if is_primary else color,
                width=width,
            )
            if is_primary:
                dot_size = max(2, int(2 * icon_scale))
                self.create_oval(
                    x - dot_size,
                    y_center - dot_size,
                    x + dot_size,
                    y_center + dot_size,
                    fill=color,
                    outline="",
                )

        elif t_type == "friendly":
            # v6.3: 友方机场 - 根据是否为目标调整大小
            # v6.5.2: 调小尺寸
            size = int((7 if is_target else 5) * icon_scale)
            width = 2 if is_target else 1
            self._draw_aircraft_icon(x, y_center, color, size=size, width=width)

        elif t_type == "enemy":
            # v6.3: 敌方机场 - 根据是否为目标调整大小
            # v6.5.2: 调小尺寸
            size = int((7 if is_target else 5) * icon_scale)
            width = 2 if is_target else 1
            self._draw_aircraft_icon(x, y_center, color, size=size, width=width)

        elif t_type == "destroyed":
            # 被摧毁：灰色X标记（v6.4: 更大更粗更易识别）
            size = int(6 * icon_scale)
            line_width = 2
            self.create_line(
                x - size, y_center - size, x + size, y_center + size, fill=color, width=line_width
            )
            self.create_line(
                x - size, y_center + size, x + size, y_center - size, fill=color, width=line_width
            )

    def _draw_aircraft_icon(self, x: float, y: float, color: str, size: int = 7, width: int = 2):
        """绘制飞机图标（v6.4: 更粗更易识别）"""
        base_width = max(2, width)
        # 机身（垂直线，加粗）
        self.create_line(x, y - size, x, y + size * 0.7, fill=color, width=base_width + 1)
        # 主翼（水平线，加粗）
        wing_y = y - size * 0.15
        self.create_line(
            x - size * 1.1, wing_y, x + size * 1.1, wing_y, fill=color, width=base_width
        )
        # 尾翼
        tail_y = y + size * 0.55
        self.create_line(
            x - size * 0.55, tail_y, x + size * 0.55, tail_y, fill=color, width=base_width
        )
        # 机头标记（小三角形）
        head_size = size * 0.25
        self.create_polygon(
            x,
            y - size - head_size,
            x - head_size,
            y - size + head_size * 0.5,
            x + head_size,
            y - size + head_size * 0.5,
            fill=color,
            outline="",
        )

    def _draw_distance_label(
        self,
        x: float,
        distance: float,
        t_type: str,
        is_primary: bool,
        icon_scale: float,
        y_center: int,
        relative_angle: float = 0.0,
        is_target: bool = True,
        layout: dict[str, Any] | None = None,
    ):
        """v6.6.0 重构：绘制距离标签（图标下方，继承偏差颜色）

        根据目标类型和距离显示不同样式的标签：
        - 位置：图标下方（航向带底部）
        - 颜色：继承当前航道偏差颜色
        - 精度：动态精度（>20km整数，5-20km一位小数，<5km一位小数或米）
        - v6.6.1: 非目标使用弱化样式

        Args:
            x: X坐标
            distance: 距离（公里）
            t_type: 目标类型
            is_primary: 是否主目标
            icon_scale: 图标缩放系数
            y_center: 图标中心Y坐标
            relative_angle: 相对角度（用于计算偏差颜色）
            is_target: 是否为活动目标（v6.6.1新增）
        """
        # v6.6.0: 距离标签放在图标下方（航向带底部）
        layout = layout or self._layout_metrics()
        dist_y = int(layout["distance_y"])

        # v6.6.0: 使用动态精度格式化距离
        dist_text = format_distance_dynamic(distance)

        # v6.6.0: 获取基于偏差的语义颜色
        deviation_color = get_deviation_color(relative_angle, distance)

        text_font = layout["distance_font"] if is_target else layout["distance_small_font"]
        bold_font = layout["distance_bold_font"] if is_target else layout["distance_small_font"]

        if t_type == "zone":
            # v6.6.0: 战区距离标签 - 使用偏差颜色
            if is_primary:
                # 主目标：带底色的标签，底色基于偏差颜色
                # 计算底色（偏差颜色的暗化版本）
                bg_color = self._darken_color(deviation_color, 0.4)
                text_color = "#FFFFFF"

                # 绘制带底色的标签
                text_width = self._measure_text(dist_text, bold_font)
                pad = 2
                self.create_rectangle(
                    x - text_width / 2 - pad,
                    dist_y - int(layout["distance_linespace"]),
                    x + text_width / 2 + pad,
                    dist_y + pad,
                    fill=bg_color,
                    outline="",
                )
                self.create_text(
                    x,
                    dist_y,
                    text=dist_text,
                    fill=text_color,
                    font=bold_font,
                    anchor="s",
                )
            elif is_target:
                # 非主目标但是活动目标：直接使用偏差颜色
                self.create_text(
                    x,
                    dist_y,
                    text=dist_text,
                    fill=deviation_color,
                    font=text_font,
                    anchor="s",
                )
            else:
                # v6.6.1: 非目标战区：使用弱化的灰色
                self.create_text(
                    x,
                    dist_y,
                    text=dist_text,
                    fill=Theme.TEXT_MUTED,
                    font=text_font,
                    anchor="s",
                )

        elif t_type == "poi":
            label_text = f"◇{dist_text}"
            if is_primary:
                bg_color = self._darken_color(Theme.YELLOW, 0.45)
                text_width = self._measure_text(label_text, bold_font)
                pad = 2
                self.create_rectangle(
                    x - text_width / 2 - pad,
                    dist_y - int(layout["distance_linespace"]),
                    x + text_width / 2 + pad,
                    dist_y + pad,
                    fill=bg_color,
                    outline="",
                )
                self.create_text(
                    x,
                    dist_y,
                    text=label_text,
                    fill="#FFFFFF",
                    font=bold_font,
                    anchor="s",
                )
            else:
                self.create_text(
                    x,
                    dist_y,
                    text=label_text,
                    fill=Theme.YELLOW if is_target else Theme.TEXT_MUTED,
                    font=text_font,
                    anchor="s",
                )

        elif t_type == "friendly":
            if is_target:
                # 友方机场：蓝色系 + ⌂ 标记
                bg_color = self._get_urgency_blue(distance)
                text_color = "#FFFFFF"

                # 友方机场添加"⌂"标记
                label_text = f"⌂{dist_text}"
                text_width = self._measure_text(label_text, bold_font)
                pad = 2
                self.create_rectangle(
                    x - text_width / 2 - pad,
                    dist_y - int(layout["distance_linespace"]),
                    x + text_width / 2 + pad,
                    dist_y + pad,
                    fill=bg_color,
                    outline="",
                )
                self.create_text(
                    x,
                    dist_y,
                    text=label_text,
                    fill=text_color,
                    font=bold_font,
                    anchor="s",
                )
            else:
                # v6.6.1: 非活动友方机场：弱化蓝色
                label_text = f"⌂{dist_text}"
                self.create_text(
                    x,
                    dist_y,
                    text=label_text,
                    fill="#5577AA",
                    font=text_font,
                    anchor="s",
                )

        elif t_type == "enemy":
            if is_target:
                # 敌方机场：橙色系，带"✖"标记
                urgency_color = self._get_urgency_orange(distance)
                label_text = f"✖{dist_text}"
                self.create_text(
                    x,
                    dist_y,
                    text=label_text,
                    fill=urgency_color,
                    font=text_font,
                    anchor="s",
                )
            else:
                # v6.6.1: 非活动敌方机场：弱化橙色
                label_text = f"✖{dist_text}"
                self.create_text(
                    x,
                    dist_y,
                    text=label_text,
                    fill="#997755",
                    font=text_font,
                    anchor="s",
                )

        else:
            # 其他类型：普通显示
            self.create_text(
                x,
                dist_y,
                text=dist_text,
                fill=Theme.TEXT_DIM,
                font=text_font,
                anchor="s",
            )

    def _darken_color(self, hex_color: str, factor: float) -> str:
        """v6.6.0: 暗化颜色

        Args:
            hex_color: 十六进制颜色 (如 "#FF0000")
            factor: 暗化系数 (0-1, 越小越暗)

        Returns:
            暗化后的颜色
        """
        try:
            hex_color = hex_color.lstrip("#")
            r = int(int(hex_color[0:2], 16) * factor)
            g = int(int(hex_color[2:4], 16) * factor)
            b = int(int(hex_color[4:6], 16) * factor)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#333333"

    def _get_urgency_blue(self, distance: float) -> str:
        """v6.6.0: 根据距离获取蓝色系紧急程度颜色"""
        if distance < 5:
            return "#3399FF"  # 亮蓝
        elif distance < 15:
            return "#2277CC"  # 蓝
        elif distance < 30:
            return "#225599"  # 暗蓝
        else:
            return "#224466"  # 很暗蓝

    def _get_urgency_orange(self, distance: float) -> str:
        """v6.6.0: 根据距离获取橙色系紧急程度颜色"""
        if distance < 5:
            return Theme.ORANGE
        elif distance < 15:
            return "#CC8844"
        elif distance < 30:
            return "#996633"
        else:
            return "#664422"

    def _draw_overflow_indicator(
        self,
        relative: float,
        t_type: str,
        distance: float = 0,
        *,
        layout: dict[str, Any] | None = None,
    ):
        """绘制视野外目标的小指示器（v6.5优化：增强区分度）

        Args:
            relative: 相对角度
            t_type: 目标类型
            distance: 目标距离（公里）
        """
        color = self._target_colors.get(t_type, Theme.TEXT_DIM)
        layout = layout or self._layout_metrics()
        icon_scale = float(layout["marker_scale"])
        y = int(layout["marker_center_y"])
        tri_size = int(6 * icon_scale)

        # v6.5: 根据类型添加前缀标记
        prefix = ""
        if t_type == "friendly":
            prefix = "⌂"
        elif t_type == "enemy":
            prefix = "✖"
        elif t_type == "zone":
            prefix = "●"
        elif t_type == "poi":
            prefix = "◇"

        # v6.5: 格式化距离文本
        dist_text = ""
        if distance > 0:
            dist_text = f"{prefix}{distance:.1f}" if distance < 10 else f"{prefix}{int(distance)}"
        elif prefix:
            dist_text = prefix

        overflow_font = layout["overflow_font"]

        if relative < 0:
            # 左侧小三角
            self.create_polygon(
                2,
                y,
                2 + tri_size,
                y - tri_size * 0.7,
                2 + tri_size,
                y + tri_size * 0.7,
                fill=color,
                outline="",
            )
            # v6.5: 显示带前缀的距离
            if dist_text:
                self.create_text(
                    2 + tri_size + 2,
                    y,
                    text=dist_text,
                    fill=color,
                    font=overflow_font,
                    anchor="w",
                )
        else:
            # 右侧小三角
            self.create_polygon(
                self.tape_width - 2,
                y,
                self.tape_width - 2 - tri_size,
                y - tri_size * 0.7,
                self.tape_width - 2 - tri_size,
                y + tri_size * 0.7,
                fill=color,
                outline="",
            )
            # v6.5: 显示带前缀的距离
            if dist_text:
                self.create_text(
                    self.tape_width - 2 - tri_size - 2,
                    y,
                    text=dist_text,
                    fill=color,
                    font=overflow_font,
                    anchor="e",
                )

    def _draw_primary_overflow(self, diff: float, *, layout: dict[str, Any] | None = None):
        """绘制主目标的大偏航箭头"""
        layout = layout or self._layout_metrics()
        y = int(layout["marker_center_y"])
        arrow_half = max(10, int(10 * float(layout["marker_scale"])))
        arrow_font = layout["arrow_font"]

        if diff < 0:
            # 左侧大箭头
            arrow_points = [5, y, 25, y - arrow_half, 20, y, 25, y + arrow_half]
            self.create_polygon(arrow_points, fill=Theme.RED, outline=Theme.BG)
            self.create_text(
                40,
                y,
                text=f"◀ {abs(int(diff))}°",
                fill=Theme.RED,
                font=arrow_font,
                anchor="w",
            )
        else:
            # 右侧大箭头
            arrow_points = [
                self.tape_width - 5,
                y,
                self.tape_width - 25,
                y - arrow_half,
                self.tape_width - 20,
                y,
                self.tape_width - 25,
                y + arrow_half,
            ]
            self.create_polygon(arrow_points, fill=Theme.RED, outline=Theme.BG)
            self.create_text(
                self.tape_width - 40,
                y,
                text=f"{abs(int(diff))}° ▶",
                fill=Theme.RED,
                font=arrow_font,
                anchor="e",
            )

    def update_tape(
        self,
        current_hdg: float,
        target_hdg: float | None = None,
        distance_km: float = 0.0,
        tolerance: float = 5.0,
        target_name: str = "",
    ):
        """兼容旧接口：单目标更新"""
        if target_hdg is None:
            self.update_tape_multi(current_hdg, [], distance_km)
        else:
            rel = target_hdg - current_hdg
            while rel > 180:
                rel -= 360
            while rel < -180:
                rel += 360
            targets = [
                {"type": "zone", "relative": rel, "distance_km": distance_km, "is_primary": True}
            ]
            self.update_tape_multi(current_hdg, targets, distance_km)

    def clear(self):
        """清除航向带"""
        self.delete("all")
        self._primary_target = None
        self._last_render_signature = None
