# -*- coding: utf-8 -*-
"""Panel rendering helpers for the main App coordinator."""

import time
import tkinter as tk
from typing import Any

from bomana.config import (
    ENABLE_AIRFIELDS,
    ENABLE_CCRP,
    ENABLE_FUEL,
    ENABLE_ZONES,
    BombConfig,
    FuelConfig,
    OverspeedConfig,
    PanelConfig,
    Theme,
    ZoneConfig,
)
from bomana.core.state import UISnapshot
from bomana.ui.navigation_presenter import build_navigation_tape_model
from bomana.utils.math_utils import (
    calculate_airfield_status,
    calculate_airfield_turn_indicator,
    calculate_heading_tape_scale,
    calculate_zone_status,
    calculate_zone_turn_indicator,
    format_distance_ete,
    get_cdi_tolerance,
)


class AppPanelRenderer:
    """Encapsulate large panel rendering sections for App."""

    def __init__(self, app: Any):
        self.app = app

    @staticmethod
    def _normalize_geom_value(value: Any) -> str:
        """Normalize geometry-manager values for stable comparisons."""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (tuple, list)):
            return " ".join(str(v) for v in value)
        return str(value)

    def _grid_if_needed(self, widget: tk.Widget, **kwargs: Any) -> bool:
        """Only call grid() when placement actually changes."""
        if widget.winfo_manager() == "grid":
            info = widget.grid_info()
            unchanged = True
            for key, value in kwargs.items():
                if self._normalize_geom_value(info.get(key, "")) != self._normalize_geom_value(
                    value
                ):
                    unchanged = False
                    break
            if unchanged:
                return False
            widget.grid_configure(**kwargs)
            return True
        widget.grid(**kwargs)
        return True

    @staticmethod
    def _grid_remove_if_needed(widget: tk.Widget) -> bool:
        """Only remove grid-managed widgets when visible."""
        if widget.winfo_manager() == "grid" and widget.winfo_ismapped():
            widget.grid_remove()
            return True
        return False

    def _pack_if_needed(self, widget: tk.Widget, **kwargs: Any) -> bool:
        """Only call pack() when placement actually changes."""
        if widget.winfo_manager() == "pack":
            info = widget.pack_info()
            unchanged = True
            for key, value in kwargs.items():
                if self._normalize_geom_value(info.get(key, "")) != self._normalize_geom_value(
                    value
                ):
                    unchanged = False
                    break
            if unchanged:
                return False
            widget.pack_configure(**kwargs)
            return True
        widget.pack(**kwargs)
        return True

    @staticmethod
    def _pack_forget_if_needed(widget: tk.Widget) -> bool:
        """Only forget packed widgets when they are currently packed."""
        if widget.winfo_manager() == "pack" and widget.winfo_ismapped():
            widget.pack_forget()
            return True
        return False

    def update_mid_panel_layout(self) -> None:
        """更新中间面板布局（战区/检查清单）。"""
        app = self.app
        layout_changed = False
        if app._zone_panel_visible and app._checklist_panel_visible:
            layout_changed |= self._grid_if_needed(
                app.mid_frame, row=1, column=0, sticky="ew", pady=(0, int(4 * app.scale))
            )
            layout_changed |= self._grid_if_needed(
                app.zone_frame, row=0, column=0, sticky="new", padx=(0, int(2 * app.scale))
            )
            layout_changed |= self._grid_if_needed(
                app.chk_frame, row=0, column=1, sticky="new", padx=(int(2 * app.scale), 0)
            )
            layout_changed |= self._pack_if_needed(
                app.chk_border_frame,
                side="left",
                fill="y",
                padx=(0, 2),
                before=app.chk_content_frame,
            )
            if layout_changed:
                app._recalc_size()
        elif app._zone_panel_visible:
            layout_changed |= self._grid_if_needed(
                app.mid_frame, row=1, column=0, sticky="ew", pady=(0, int(4 * app.scale))
            )
            layout_changed |= self._grid_if_needed(
                app.zone_frame, row=0, column=0, columnspan=2, sticky="new"
            )
            layout_changed |= self._grid_remove_if_needed(app.chk_frame)
            if layout_changed:
                app._recalc_size()
        elif app._checklist_panel_visible:
            layout_changed |= self._grid_if_needed(
                app.mid_frame, row=1, column=0, sticky="ew", pady=(0, int(4 * app.scale))
            )
            layout_changed |= self._grid_remove_if_needed(app.zone_frame)
            layout_changed |= self._grid_if_needed(
                app.chk_frame, row=0, column=0, columnspan=2, sticky="new"
            )
            layout_changed |= self._pack_forget_if_needed(app.chk_border_frame)
            if layout_changed:
                app._recalc_size()
        else:
            layout_changed |= self._grid_remove_if_needed(app.zone_frame)
            layout_changed |= self._grid_remove_if_needed(app.chk_frame)
            layout_changed |= self._grid_remove_if_needed(app.mid_frame)
            if layout_changed:
                app._recalc_size(force_shrink=True)

    def reset_navigation_layout_state(self) -> None:
        """Clear both integrated and compact nav layouts before a mode switch."""
        app = self.app
        for rows in (
            getattr(app, "_zone_row_pool", []),
            getattr(app, "_compact_zone_row_pool", []),
            getattr(app, "_airport_row_pool", []),
            getattr(app, "_compact_airport_row_pool", []),
        ):
            self._clear_nav_rows(rows)
            self._sync_nav_row_visibility(rows, 0)

        for widget_name in (
            "compact_nav_frame",
            "zone_list_frame",
            "zone_list_header_frame",
            "airport_header_frame",
            "airport_list_frame",
            "heading_tape_frame",
        ):
            widget = getattr(app, widget_name, None)
            if widget is not None:
                self._grid_remove_if_needed(widget)

        if getattr(app, "heading_tape", None) is not None:
            app.heading_tape.clear()
        if getattr(app, "zone_alert_lbl", None) is not None:
            app.zone_alert_lbl.config(text="")

        app._zone_layout_mode = None
        app._airport_layout_mode = None
        app._last_layout_signature = None

    def set_zone_panel_visible(self, visible: bool) -> None:
        """设置战区面板可见性。"""
        app = self.app
        if app._zone_panel_visible != visible:
            app._zone_panel_visible = visible
            self.update_mid_panel_layout()

    def update_tape_info_labels(self, targets_info: list, primary_zone) -> None:
        """更新航向带下方的状态提示（战区+友方机场）。"""
        app = self.app
        zone_info = next((t for t in targets_info if t["type"] == "zone"), None)
        if primary_zone and app.tape_turn_lbl and app.tape_deviation_lbl and app.tape_tolerance_lbl:
            tolerance = get_cdi_tolerance(primary_zone.distance_km)
            scale = calculate_heading_tape_scale(primary_zone.distance_km)
            rel = primary_zone.relative
            abs_rel = abs(rel)

            turn_text, turn_color = calculate_zone_turn_indicator(rel, tolerance)
            dev_text, dev_color = calculate_zone_status(abs_rel, tolerance)
            ete_str = zone_info.get("ete_str") if zone_info else None
            info_text = format_distance_ete(primary_zone.distance_km, ete_str)
            tol_text = f"±{tolerance:.1f}° {scale:.1f}x"

            app.tape_turn_lbl.config(text=turn_text, fg=turn_color)
            app.tape_deviation_lbl.config(text=dev_text, fg=dev_color)
            if hasattr(app, "tape_zone_info") and app.tape_zone_info:
                app.tape_zone_info.config(text=info_text, fg=Theme.RED)
            if hasattr(app, "tape_tolerance_legend") and app.tape_tolerance_legend:
                app.tape_tolerance_legend.config(text=tol_text)
            app.tape_tolerance_lbl.config(text="")
        elif app.tape_turn_lbl and app.tape_deviation_lbl and app.tape_tolerance_lbl:
            app.tape_turn_lbl.config(text="", fg=Theme.TEXT_MUTED)
            app.tape_deviation_lbl.config(text="无目标", fg=Theme.TEXT_MUTED)
            if hasattr(app, "tape_zone_info") and app.tape_zone_info:
                app.tape_zone_info.config(text="")
            if hasattr(app, "tape_tolerance_legend") and app.tape_tolerance_legend:
                app.tape_tolerance_legend.config(text="")
            app.tape_tolerance_lbl.config(text="")

        friendly_info = next((t for t in targets_info if t["type"] == "friendly"), None)
        if friendly_info and app.tape_friendly_turn and app.tape_friendly_info:
            rel = friendly_info["relative"]
            abs_rel = abs(rel)
            dist = friendly_info["distance_km"]

            turn_text, turn_color = calculate_airfield_turn_indicator(rel)
            status_text, status_color = calculate_airfield_status(abs_rel)
            info_text = format_distance_ete(dist, friendly_info.get("ete_str"))

            app.tape_friendly_turn.config(text=turn_text, fg=turn_color)
            if hasattr(app, "tape_friendly_status") and app.tape_friendly_status:
                app.tape_friendly_status.config(text=status_text, fg=status_color)
            app.tape_friendly_info.config(text=info_text, fg=Theme.BLUE)
        elif app.tape_friendly_turn and app.tape_friendly_info:
            app.tape_friendly_turn.config(text="", fg=Theme.TEXT_MUTED)
            if hasattr(app, "tape_friendly_status") and app.tape_friendly_status:
                app.tape_friendly_status.config(text="", fg=Theme.TEXT_MUTED)
            app.tape_friendly_info.config(text="", fg=Theme.TEXT_MUTED)

    def set_checklist_visible(self, visible: bool) -> None:
        """设置检查清单可见性。"""
        app = self.app
        if app._checklist_panel_visible != visible:
            app._checklist_panel_visible = visible
            self.update_mid_panel_layout()

    @staticmethod
    def _set_nav_row(
        row: Any,
        *,
        icon: str = "",
        direction: str = "",
        distance: str = "",
        relative: str = "",
        fg: str = Theme.TEXT_MUTED,
    ) -> None:
        """Update one prebuilt zone/airport row without changing geometry."""
        row.icon_lbl.config(text=icon, fg=fg)
        row.direction_lbl.config(text=direction, fg=fg)
        row.distance_lbl.config(text=distance, fg=fg)
        if getattr(row, "relative_lbl", None) is not None:
            row.relative_lbl.config(text=relative, fg=fg)

    def _clear_nav_rows(self, rows: list[Any], start: int = 0) -> None:
        """Blank remaining prebuilt rows."""
        for row in rows[start:]:
            self._set_nav_row(row)

    def _sync_nav_row_visibility(self, rows: list[Any], visible_count: int) -> None:
        """Show only the visible prefix of prebuilt rows."""
        for idx, row in enumerate(rows):
            widgets = [row.icon_lbl, row.direction_lbl, row.distance_lbl]
            if getattr(row, "relative_lbl", None) is not None:
                widgets.append(row.relative_lbl)
            if idx < visible_count:
                for widget in widgets:
                    if widget.winfo_manager() != "grid" or not widget.winfo_ismapped():
                        widget.grid()
            else:
                for widget in widgets:
                    self._grid_remove_if_needed(widget)

    def _build_heading_targets(
        self, snap: UISnapshot
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Any]:
        """Build integrated heading-tape targets and status items."""
        app = self.app
        destroyed_zones = (
            app.game.state.zone_nav.destroyed_zones
            if snap.zone_destroyed_alert and hasattr(app.game.state.zone_nav, "destroyed_zones")
            else None
        )
        model = build_navigation_tape_model(snap, destroyed_zones=destroyed_zones)
        return model.targets, model.active_targets_info, model.primary_zone

    def update_zone_display(self, snap: UISnapshot):
        """更新战区显示，并返回是否需要重算布局尺寸。"""
        app = self.app
        s = app.scale
        pad_x = int(8 * s)

        raw_heading = float(getattr(snap, "player_heading", 0.0) or 0.0)
        heading_deg = raw_heading % 360.0
        heading_available = (snap.phase in app._alive_phases) and (not snap.api_down)

        if heading_available:
            app.heading_lbl.config(text=f"航向: {int(heading_deg):03d}°")
        else:
            app.heading_lbl.config(text="航向: ---°")

        zones_enabled = ENABLE_ZONES and PanelConfig.is_effectively_enabled("zones")
        airfields_enabled = ENABLE_AIRFIELDS and PanelConfig.is_effectively_enabled("airfields")
        fuel_enabled = ENABLE_FUEL and PanelConfig.is_effectively_enabled("fuel")
        bombing_enabled = ENABLE_CCRP and PanelConfig.is_effectively_enabled("bombing")

        if zones_enabled:
            self._grid_if_needed(
                app.zone_header_frame,
                row=0,
                column=0,
                sticky="ew",
                padx=pad_x,
                pady=(int(6 * s), int(2 * s)),
            )
            self._grid_remove_if_needed(app.compact_nav_frame)
            if hasattr(app, "nav_window") and app.nav_window and app.nav_window.is_visible():
                app.nav_window.update_display(snap)

            nav_in_main = PanelConfig.navigation_mode == "integrated"
            if app.heading_tape is not None:
                if nav_in_main and heading_available:
                    targets, active_targets_info, target_zone = self._build_heading_targets(snap)
                    primary_dist = target_zone.distance_km if target_zone else 10.0
                    app.heading_tape.update_tape_multi(heading_deg, targets, primary_dist)
                    self.update_tape_info_labels(active_targets_info, target_zone)
                    self._grid_if_needed(
                        app.heading_tape_frame,
                        row=1,
                        column=0,
                        sticky="ew",
                        padx=pad_x,
                        pady=(int(2 * s), int(4 * s)),
                    )
                elif nav_in_main:
                    app.heading_tape.clear()
                    self.update_tape_info_labels([], None)
                    self._grid_if_needed(
                        app.heading_tape_frame,
                        row=1,
                        column=0,
                        sticky="ew",
                        padx=pad_x,
                        pady=(int(2 * s), int(4 * s)),
                    )
                else:
                    app.heading_tape.clear()
                    self.update_tape_info_labels([], None)
                    self._grid_remove_if_needed(app.heading_tape_frame)

            if snap.zone_destroyed_alert:
                alert_text = "💥 战区被摧毁："
                if getattr(snap, "destroyed_zone_text", ""):
                    alert_text += snap.destroyed_zone_text
                else:
                    alert_text = "💥 战区已摧毁!"
                wrap = max(int(220 * s), app.zone_frame.winfo_width() - int(16 * s))
                app.zone_alert_lbl.config(text=alert_text, wraplength=wrap, justify="left")
                if (
                    snap.should_play_destroyed_sound
                    and not app._last_zone_destroyed_alert
                    and app._zone_sound_enabled
                ):
                    app.sound.play(pattern="zone_destroyed")
                app._last_zone_destroyed_alert = True
            else:
                app.zone_alert_lbl.config(text="")
                app._last_zone_destroyed_alert = False

            zone_layout_mode = "full" if nav_in_main else "hidden"
            if app._zone_layout_mode != zone_layout_mode:
                self._clear_nav_rows(app._zone_row_pool)
                self._clear_nav_rows(app._compact_zone_row_pool)
                app._zone_layout_mode = zone_layout_mode

            if nav_in_main:
                self._grid_if_needed(
                    app.zone_list_header_frame,
                    row=3,
                    column=0,
                    sticky="ew",
                    padx=pad_x,
                    pady=(0, int(2 * s)),
                )
                self._grid_if_needed(
                    app.zone_list_frame,
                    row=4,
                    column=0,
                    sticky="ew",
                    padx=pad_x,
                    pady=(0, int(10 * s)),
                )
            else:
                self._grid_remove_if_needed(app.zone_list_header_frame)
                self._grid_remove_if_needed(app.zone_list_frame)

            if nav_in_main:
                row_pool = app._zone_row_pool
            else:
                row_pool = app._compact_zone_row_pool

            idx = 0
            if not snap.zones:
                self._set_nav_row(row_pool[idx], direction="无战区")
                idx += 1
            else:
                for zone in snap.zones[: ZoneConfig.MAX_DISPLAY_ZONES]:
                    marker = "➤" if zone.is_target else "○"
                    dist_text = (
                        f"{zone.distance_km:.1f}km"
                        if zone.distance_km < 10
                        else f"{int(zone.distance_km)}km"
                    )
                    rel_sign = "+" if zone.relative > 0 else ""
                    rel_text = (
                        f"{rel_sign}{zone.relative:.2f}°"
                        if zone.is_target
                        else f"{rel_sign}{int(zone.relative)}°"
                    )
                    relative_text = rel_text if nav_in_main else ""
                    fg = (
                        Theme.GREEN
                        if zone.is_target and not snap.is_deviating
                        else Theme.ORANGE
                        if zone.is_target
                        else Theme.TEXT_DIM
                    )
                    self._set_nav_row(
                        row_pool[idx],
                        icon=marker,
                        direction=zone.direction,
                        distance=dist_text,
                        relative=relative_text,
                        fg=fg,
                    )
                    idx += 1
            self._clear_nav_rows(row_pool, start=idx)
            self._sync_nav_row_visibility(app._zone_row_pool, idx if nav_in_main else 0)
            self._sync_nav_row_visibility(app._compact_zone_row_pool, 0)
        else:
            self._grid_remove_if_needed(app.zone_header_frame)
            self._grid_remove_if_needed(app.zone_list_header_frame)
            self._grid_remove_if_needed(app.zone_list_frame)
            self._grid_remove_if_needed(app.compact_nav_frame)
            app.zone_alert_lbl.config(text="")
            self._clear_nav_rows(app._zone_row_pool)
            self._clear_nav_rows(app._compact_zone_row_pool)
            self._sync_nav_row_visibility(app._zone_row_pool, 0)
            self._sync_nav_row_visibility(app._compact_zone_row_pool, 0)
            app._zone_layout_mode = None

        if airfields_enabled:
            nav_in_main = PanelConfig.navigation_mode == "integrated"
            airport_layout_mode = "full" if nav_in_main else "hidden"
            if app._airport_layout_mode != airport_layout_mode:
                self._clear_nav_rows(app._airport_row_pool)
                self._clear_nav_rows(app._compact_airport_row_pool)
                app._airport_layout_mode = airport_layout_mode

            if nav_in_main:
                self._grid_if_needed(
                    app.airport_header_frame,
                    row=5,
                    column=0,
                    sticky="ew",
                    padx=pad_x,
                    pady=(0, int(2 * s)),
                )
                self._grid_if_needed(
                    app.airport_list_frame,
                    row=6,
                    column=0,
                    sticky="ew",
                    padx=pad_x,
                    pady=(0, int(10 * s)),
                )
                row_pool = app._airport_row_pool
            else:
                self._grid_remove_if_needed(app.airport_header_frame)
                self._grid_remove_if_needed(app.airport_list_frame)
                row_pool = app._compact_airport_row_pool

            ap_idx = 0
            if snap.friendly_airfield:
                af = snap.friendly_airfield
                dist_text = (
                    f"{af.distance_km:.1f}km" if af.distance_km < 10 else f"{int(af.distance_km)}km"
                )
                rel_sign = "+" if af.relative > 0 else ""
                rel_text = f"{rel_sign}{int(af.relative)}°"
                relative_text = rel_text if nav_in_main else ""
                self._set_nav_row(
                    row_pool[ap_idx],
                    icon="🟢➤",
                    direction=af.direction,
                    distance=dist_text,
                    relative=relative_text,
                    fg=Theme.GREEN,
                )
                ap_idx += 1

            if snap.enemy_airfields:
                for af in snap.enemy_airfields[: max(0, ZoneConfig.MAX_DISPLAY_AIRFIELDS - ap_idx)]:
                    marker = "➤" if af.is_target else "○"
                    dist_text = (
                        f"{af.distance_km:.1f}km"
                        if af.distance_km < 10
                        else f"{int(af.distance_km)}km"
                    )
                    rel_sign = "+" if af.relative > 0 else ""
                    rel_text = f"{rel_sign}{int(af.relative)}°"
                    relative_text = rel_text if nav_in_main else ""
                    fg = Theme.ORANGE if af.is_target else Theme.TEXT_DIM
                    self._set_nav_row(
                        row_pool[ap_idx],
                        icon=f"🔴{marker}",
                        direction=af.direction,
                        distance=dist_text,
                        relative=relative_text,
                        fg=fg,
                    )
                    ap_idx += 1

            if ap_idx == 0:
                self._set_nav_row(row_pool[0], direction="无数据")
                ap_idx = 1
            self._clear_nav_rows(row_pool, start=ap_idx)
            self._sync_nav_row_visibility(app._airport_row_pool, ap_idx if nav_in_main else 0)
            self._sync_nav_row_visibility(app._compact_airport_row_pool, 0)
        else:
            self._grid_remove_if_needed(app.airport_header_frame)
            if app.airport_tape_frame:
                self._grid_remove_if_needed(app.airport_tape_frame)
            self._grid_remove_if_needed(app.airport_list_frame)
            self._clear_nav_rows(app._airport_row_pool)
            self._clear_nav_rows(app._compact_airport_row_pool)
            self._sync_nav_row_visibility(app._airport_row_pool, 0)
            self._sync_nav_row_visibility(app._compact_airport_row_pool, 0)
            app._airport_layout_mode = None

        if fuel_enabled:
            self._grid_if_needed(
                app.fuel_header_frame,
                row=7,
                column=0,
                sticky="ew",
                padx=pad_x,
                pady=(0, int(2 * s)),
            )
            self._grid_if_needed(
                app.fuel_info_frame, row=8, column=0, sticky="ew", padx=pad_x, pady=(0, int(6 * s))
            )
            self.update_fuel_display(snap)
        else:
            self._grid_remove_if_needed(app.fuel_header_frame)
            self._grid_remove_if_needed(app.fuel_info_frame)

        if ENABLE_CCRP:
            if bombing_enabled:
                self._grid_if_needed(
                    app.bombing_header_frame,
                    row=9,
                    column=0,
                    sticky="ew",
                    padx=pad_x,
                    pady=(0, int(2 * s)),
                )
                self._grid_if_needed(
                    app.bombing_info_frame,
                    row=10,
                    column=0,
                    sticky="ew",
                    padx=pad_x,
                    pady=(0, int(6 * s)),
                )
                self.update_bombing_display(snap)
            else:
                self._grid_remove_if_needed(app.bombing_header_frame)
                self._grid_remove_if_needed(app.bombing_info_frame)

        layout_signature = (
            PanelConfig.navigation_mode,
            bool(zones_enabled),
            bool(airfields_enabled),
            bool(fuel_enabled),
            bool(bombing_enabled),
            bool(app.heading_tape is not None and PanelConfig.navigation_mode == "integrated"),
        )
        if layout_signature != app._last_layout_signature:
            app._last_layout_signature = layout_signature
            return True
        return False

    def update_fuel_display(self, snap: UISnapshot) -> None:
        """更新燃油信息显示。"""
        app = self.app
        if snap.fuel_kg > 0:
            fuel_text = f"{int(snap.fuel_kg)}kg ({snap.fuel_percent:.0f}%)"

            if snap.fuel_percent <= FuelConfig.DANGER_PERCENT:
                fuel_color = Theme.RED
            elif snap.fuel_percent <= FuelConfig.WARNING_PERCENT:
                fuel_color = Theme.YELLOW
            else:
                fuel_color = Theme.TEXT

            app.fuel_main_lbl.config(text=fuel_text, fg=fuel_color)
        else:
            app.fuel_main_lbl.config(text="-- kg (--%)", fg=Theme.TEXT_MUTED)

        if snap.fuel_time_remaining_str:
            app.fuel_time_lbl.config(text=f"⏱️ {snap.fuel_time_remaining_str}", fg=Theme.TEXT)
        else:
            app.fuel_time_lbl.config(text="⏱️ 计算中...", fg=Theme.TEXT_MUTED)

        if snap.fuel_rate_stable and snap.fuel_rate_kg_min > 0:
            rate_text = f"油耗 {snap.fuel_rate_kg_min:.0f}kg/min"
        else:
            rate_text = "油耗 --"

        alt_text = f"高度 {int(snap.altitude_m)}m" if snap.altitude_m > 0 else "高度 --"
        detail_suffix = "返航 --"

        if snap.return_status != "unknown" and snap.return_fuel_needed_kg > 0:
            needed_text = f"需~{int(snap.return_fuel_needed_kg)}kg"
            if snap.fuel_initial_kg > 0:
                return_percent = (snap.return_fuel_needed_kg / snap.fuel_initial_kg) * 100
                needed_text += f" ({return_percent:.0f}%)"

            if snap.return_status == "safe":
                status_icon = "✅ 充足"
                return_color = Theme.GREEN
            elif snap.return_status == "warning":
                status_icon = "⚠️ 注意"
                return_color = Theme.YELLOW
            else:
                status_icon = "🔴 不足!"
                return_color = Theme.RED

            app.fuel_return_lbl.config(text=status_icon, fg=return_color)
            detail_suffix = f"返航 {needed_text}"
        elif snap.friendly_distance_km > 0:
            app.fuel_return_lbl.config(text="↻ 估算中", fg=Theme.TEXT_MUTED)
            detail_suffix = f"返航距离 {snap.friendly_distance_km:.0f}km"
        else:
            app.fuel_return_lbl.config(text="无机场", fg=Theme.TEXT_MUTED)
            detail_suffix = "返航无机场数据"

        app.fuel_detail_lbl.config(text=f"{rate_text} │ {alt_text} │ {detail_suffix}")

    def update_bombing_display(self, snap: UISnapshot) -> None:
        """更新投弹预测信息显示。"""
        app = self.app
        app.bomb_select_lbl.config(
            text=f"炸弹: {BombConfig.format_bomb_name(snap.bomb_name)} (点击更换)"
        )

        if snap.bombing_valid:
            bomb_range_km = snap.bomb_range_m / 1000.0
            trajectory_text = f"弹道: {bomb_range_km:.2f}km │ 飞行: {snap.bomb_flight_time:.1f}s"
            app.bomb_trajectory_lbl.config(text=trajectory_text, fg=Theme.TEXT_DIM)

            status = snap.release_status
            dist_m = snap.release_distance_m
            if dist_m > 1000:
                dist_str = f"{dist_m / 1000:.2f}km"
            elif dist_m > 100:
                dist_str = f"{int(dist_m)}m"
            else:
                dist_str = f"{dist_m:.0f}m"

            if status == "ready":
                time_str = f"{snap.time_to_release:.2f}s"
                release_text = f"💣 投弹 {time_str} │ {dist_str}"
                release_color = Theme.GREEN
            elif status == "approaching":
                time_str = f"{snap.time_to_release:.1f}s"
                release_text = f"⏱️ {time_str} │ {dist_str}"
                release_color = Theme.YELLOW
            elif status == "passed":
                release_text = f"❌ 已飞过 {dist_str}"
                release_color = Theme.RED
            elif status == "too_far":
                time_str = f"{snap.time_to_release:.0f}s"
                release_text = f"🎯 {dist_str} │ {time_str}"
                release_color = Theme.TEXT_DIM
            else:
                release_text = "⏳ 计算中"
                release_color = Theme.TEXT_MUTED

            app.bomb_release_lbl.config(text=release_text, fg=release_color)
        else:
            app.bomb_trajectory_lbl.config(text="弹道: -- km │ 飞行: -- s", fg=Theme.TEXT_MUTED)

            if snap.on_ground:
                release_text = "🛫 请起飞"
            elif snap.altitude_m <= 50:
                release_text = "📈 请爬升"
            elif not snap.has_target:
                release_text = "🎯 无目标战区"
            else:
                release_text = "↻ 请对准目标"

            app.bomb_release_lbl.config(text=release_text, fg=Theme.TEXT_MUTED)

    @staticmethod
    def format_aircraft_type_label(raw: str) -> str:
        text = str(raw or "").strip().replace("_", " ")
        text = " ".join(text.split())
        if not text:
            return "机型未识别"
        if len(text) > 28:
            return text[:25] + "..."
        return text

    def update_speed_strip(self, snap: UISnapshot, debug_mock_mode: bool) -> str:
        """更新紧凑速度指示条，并返回当前超速等级。"""
        app = self.app
        speed_level = str(getattr(snap, "overspeed_level", "unknown") or "unknown")
        speed_ratio = float(getattr(snap, "overspeed_ratio", 0.0) or 0.0)
        display_ratio = float(getattr(snap, "overspeed_display_ratio", speed_ratio) or 0.0)
        current_ias = float(getattr(snap, "overspeed_current_ias_kmh", 0.0) or 0.0)
        current_mach = getattr(snap, "overspeed_current_mach", None)
        limit_ias = float(getattr(snap, "overspeed_limit_kmh", 0.0) or 0.0)
        limit_mach = float(getattr(snap, "overspeed_limit_mach", 0.0) or 0.0)
        matched = bool(getattr(snap, "overspeed_match", False))
        reason = str(getattr(snap, "overspeed_reason", "") or "")
        aircraft_type_name = self.format_aircraft_type_label(
            str(getattr(snap, "aircraft_type_name", "") or "")
        )

        if speed_level == "critical":
            state_text = "超速危险"
            state_fg = Theme.RED
            fill_color = Theme.RED
        elif speed_level == "warning":
            state_text = "接近极限"
            state_fg = Theme.YELLOW
            fill_color = Theme.YELLOW
        elif speed_level == "caution":
            state_text = "高速预警"
            state_fg = Theme.ORANGE
            fill_color = Theme.ORANGE
        elif reason == "limit_missing":
            state_text = "阈值缺失"
            state_fg = Theme.TEXT_MUTED
            fill_color = Theme.TEXT_MUTED
        elif matched:
            state_text = "速度安全"
            state_fg = Theme.GREEN
            fill_color = Theme.GREEN
        else:
            state_text = "速度监视"
            state_fg = Theme.TEXT_MUTED
            fill_color = Theme.TEXT_MUTED

        if matched:
            if limit_ias > 0.0:
                value_text = f"IAS {current_ias:.0f}/{limit_ias:.0f}"
            elif current_ias > 0.0:
                value_text = f"IAS {current_ias:.0f}"
            else:
                value_text = "IAS --"
        else:
            value_text = f"IAS {current_ias:.0f}" if current_ias > 0.0 else "IAS --"

        model_parts = [aircraft_type_name]
        if current_mach is not None and limit_mach > 0.0:
            model_parts.append(f"M{float(current_mach):.2f}/{limit_mach:.2f}")
        elif reason == "limit_missing":
            model_parts.append("阈值缺失")
        elif not matched:
            model_parts.append("阈值未匹配")
        model_text = "  |  ".join(part for part in model_parts if part)

        app.speed_state_lbl.config(text=state_text, fg=state_fg)
        app.speed_model_lbl.config(
            text=model_text,
            fg=(Theme.TEXT if speed_level in ("warning", "critical") else Theme.TEXT_DIM),
        )
        app.speed_value_lbl.config(
            text=value_text,
            fg=state_fg if speed_level in ("caution", "warning", "critical") else Theme.TEXT_DIM,
        )
        app.speed_bar_fill.config(bg=fill_color if matched else Theme.TEXT_MUTED)
        app.speed_bar_fill.place(relwidth=max(0.0, min(1.0, display_ratio if matched else 0.0)))

        if speed_level != app._last_overspeed_level:
            app._last_overspeed_level = speed_level
            app._last_overspeed_sound_ts = 0.0

        if not debug_mock_mode:
            now_sound = time.monotonic()
            if speed_level == "critical":
                if (
                    now_sound - app._last_overspeed_sound_ts
                ) >= OverspeedConfig.CRITICAL_SOUND_INTERVAL_SEC:
                    app.sound.play(pattern="overspeed_critical")
                    app._last_overspeed_sound_ts = now_sound
            elif speed_level == "warning":
                if (
                    now_sound - app._last_overspeed_sound_ts
                ) >= OverspeedConfig.WARNING_SOUND_INTERVAL_SEC:
                    app.sound.play(pattern="overspeed_warning")
                    app._last_overspeed_sound_ts = now_sound
            else:
                app._last_overspeed_sound_ts = 0.0
        elif speed_level not in ("critical", "warning"):
            app._last_overspeed_sound_ts = 0.0

        return speed_level
