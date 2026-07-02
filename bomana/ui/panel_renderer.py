"""Panel rendering helpers for the main App coordinator."""

import math
import time
import tkinter as tk
from dataclasses import dataclass
from typing import Any

from bomana.config import (
    ENABLE_AIRFIELDS,
    ENABLE_CCRP,
    ENABLE_FUEL,
    ENABLE_ZONES,
    OverspeedConfig,
    PanelConfig,
    Theme,
    ZoneConfig,
)
from bomana.core.state import UISnapshot
from bomana.ui.icon_assets import IconManager
from bomana.ui.navigation_presenter import build_navigation_tape_model
from bomana.ui.panel_presenter import (
    build_bombing_display_model,
    build_fuel_display_model,
    build_speed_strip_model,
    format_aircraft_type_label,
)
from bomana.utils.math_utils import (
    calculate_airfield_status,
    calculate_airfield_turn_indicator,
    calculate_heading_tape_scale,
    calculate_zone_status,
    calculate_zone_turn_indicator,
    format_distance_ete,
    get_cdi_tolerance,
)

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)


@dataclass(frozen=True, slots=True)
class NavListItem:
    """Presentation state for one stable zone/airport list row."""

    icon: str | None = None
    direction: str = ""
    distance: str = ""
    relative: str = ""
    fg: str = Theme.TEXT_MUTED


class AppPanelRenderer:
    """Encapsulate large panel rendering sections for App."""

    _NAV_TARGET_ICON = "target"

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
        if widget.winfo_manager() == "grid":
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
        if widget.winfo_manager() == "pack":
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
            app.icons.configure_label(app.zone_alert_lbl, icon=None, text="")

        app._zone_layout_mode = None
        app._airport_layout_mode = None
        app._last_layout_signature = None

    def set_zone_panel_visible(self, visible: bool) -> None:
        """设置战区面板可见性。"""
        app = self.app
        if app._zone_panel_visible != visible:
            app._zone_panel_visible = visible
            self.update_mid_panel_layout()

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

    @classmethod
    def _target_info_from_legacy_zone(cls, zone: Any) -> dict[str, Any] | None:
        if zone is None:
            return None
        return {
            "type": "zone",
            "name": "战区",
            "icon": "⊚",
            "relative": getattr(zone, "relative", 0.0),
            "distance_km": getattr(zone, "distance_km", 0.0),
            "ete_str": getattr(zone, "ete_str", ""),
            "color": Theme.RED,
        }

    @classmethod
    def _primary_target_info(
        cls, targets_info: list[dict[str, Any]], primary_target_info: Any = None
    ) -> dict[str, Any] | None:
        if isinstance(primary_target_info, dict):
            return primary_target_info
        if primary_target_info is not None:
            return cls._target_info_from_legacy_zone(primary_target_info)
        return next(
            (info for info in targets_info if info.get("type") == "zone"),
            None,
        )

    def update_tape_info_labels(
        self, targets_info: list[dict[str, Any]], primary_target_info: Any = None
    ) -> None:
        """更新航向带下方的主导航目标和友方机场状态提示。"""
        app = self.app
        target_info = self._primary_target_info(targets_info, primary_target_info)
        has_primary_labels = app.tape_turn_lbl and app.tape_deviation_lbl and app.tape_tolerance_lbl
        if target_info and has_primary_labels:
            rel = self._safe_float(target_info.get("relative", 0.0))
            distance = self._safe_float(target_info.get("distance_km", 0.0))
            info_text = self._format_active_info_text(target_info)

            tolerance = get_cdi_tolerance(distance)
            scale = calculate_heading_tape_scale(distance)
            turn_text, turn_color = calculate_zone_turn_indicator(rel, tolerance)
            dev_text, dev_color = calculate_zone_status(abs(rel), tolerance)
            label_text = "⊚战区:"
            label_color = Theme.RED
            tol_text = f"±{tolerance:.1f}° {scale:.1f}x"

            if hasattr(app, "tape_zone_label") and app.tape_zone_label:
                app.tape_zone_label.config(text=label_text, fg=label_color)
            app.tape_turn_lbl.config(text=turn_text, fg=turn_color)
            app.tape_deviation_lbl.config(text=dev_text, fg=dev_color)
            if hasattr(app, "tape_zone_info") and app.tape_zone_info:
                app.tape_zone_info.config(text=info_text, fg=label_color)
            if hasattr(app, "tape_tolerance_legend") and app.tape_tolerance_legend:
                app.tape_tolerance_legend.config(text=tol_text)
            app.tape_tolerance_lbl.config(text="")
        elif has_primary_labels:
            if hasattr(app, "tape_zone_label") and app.tape_zone_label:
                app.tape_zone_label.config(text="⊚战区:", fg=Theme.RED)
            app.tape_turn_lbl.config(text="", fg=Theme.TEXT_MUTED)
            app.tape_deviation_lbl.config(text="无目标", fg=Theme.TEXT_MUTED)
            if hasattr(app, "tape_zone_info") and app.tape_zone_info:
                app.tape_zone_info.config(text="")
            if hasattr(app, "tape_tolerance_legend") and app.tape_tolerance_legend:
                app.tape_tolerance_legend.config(text="")
            app.tape_tolerance_lbl.config(text="")

        friendly_info = next((t for t in targets_info if t.get("type") == "friendly"), None)
        if friendly_info and app.tape_friendly_turn and app.tape_friendly_info:
            rel = self._safe_float(friendly_info.get("relative", 0.0))
            abs_rel = abs(rel)
            dist = self._safe_float(friendly_info.get("distance_km", 0.0))

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

    @classmethod
    def _nav_list_icon(cls, base_icon: str, selected: bool) -> str:
        """Return the replacement icon for selected rows."""
        return cls._NAV_TARGET_ICON if selected else base_icon

    @staticmethod
    def _format_nav_distance(distance_km: float) -> str:
        return f"{distance_km:.1f}km" if distance_km < 10 else f"{int(distance_km)}km"

    @staticmethod
    def _format_nav_relative(relative: float, *, precise: bool = False) -> str:
        rel_sign = "+" if relative > 0 else ""
        if precise:
            return f"{rel_sign}{relative:.2f}°"
        return f"{rel_sign}{int(relative)}°"

    @classmethod
    def _build_nav_list_item(
        cls,
        *,
        base_icon: str,
        selected: bool,
        direction: Any,
        distance_km: Any,
        relative: Any,
        fg: str,
        precise_relative: bool = False,
    ) -> NavListItem:
        """Build one dense navigation row without dropping core row fields."""
        distance = cls._safe_float(distance_km)
        rel = cls._safe_float(relative)
        return NavListItem(
            icon=cls._nav_list_icon(base_icon, selected),
            direction=str(direction or ""),
            distance=cls._format_nav_distance(distance),
            relative=cls._format_nav_relative(rel, precise=precise_relative),
            fg=fg,
        )

    def _icon_size(self, base_size: int = 18, *, min_size: int = 16, max_size: int = 64) -> int:
        scale = float(getattr(self.app, "scale", 1.0) or 1.0)
        return IconManager.scaled_size(base_size, scale, min_size=min_size, max_size=max_size)

    def _set_nav_row(self, row: Any, item: NavListItem | None = None) -> None:
        """Update one prebuilt zone/airport row without changing geometry."""
        item = item or NavListItem()
        if getattr(self.app, "icons", None) is not None:
            self.app.icons.configure_label(
                row.icon_lbl,
                icon=item.icon,
                text="",
                size=self._icon_size(18),
                fg=item.fg,
                padx=0,
            )
        else:
            row.icon_lbl.config(text=item.icon or "", image="", fg=item.fg)
        row.direction_lbl.config(text=item.direction, fg=item.fg)
        row.distance_lbl.config(text=item.distance, fg=item.fg)
        if getattr(row, "relative_lbl", None) is not None:
            row.relative_lbl.config(text=item.relative, fg=item.fg)

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
        destroyed_zones = (
            getattr(snap, "destroyed_zones", [])
            if getattr(snap, "zone_destroyed_alert", False)
            else None
        )
        model = build_navigation_tape_model(snap, destroyed_zones=destroyed_zones)
        return model.targets, model.active_targets_info, model.primary_target_info

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

        if (
            (zones_enabled or airfields_enabled)
            and hasattr(app, "nav_window")
            and app.nav_window
            and app.nav_window.is_visible()
        ):
            app.nav_window.update_display(snap)

        if zones_enabled:
            self._grid_if_needed(
                app.zone_header_frame,
                row=0,
                column=0,
                sticky="ew",
                padx=pad_x,
                pady=(int(2 * s), int(1 * s)),
            )
            self._grid_remove_if_needed(app.compact_nav_frame)

            nav_in_main = PanelConfig.navigation_mode == "integrated"
            if app.heading_tape is not None:
                if nav_in_main and heading_available:
                    targets, active_targets_info, primary_info = self._build_heading_targets(snap)
                    primary_dist = (
                        self._safe_float(primary_info.get("distance_km")) if primary_info else 10.0
                    )
                    app.heading_tape.update_tape_multi(heading_deg, targets, primary_dist)
                    self.update_tape_info_labels(active_targets_info, primary_info)
                    self._grid_if_needed(
                        app.heading_tape_frame,
                        row=1,
                        column=0,
                        sticky="ew",
                        padx=pad_x,
                        pady=(int(1 * s), int(3 * s)),
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
                        pady=(int(1 * s), int(3 * s)),
                    )
                else:
                    app.heading_tape.clear()
                    self.update_tape_info_labels([], None)
                    self._grid_remove_if_needed(app.heading_tape_frame)

            if snap.zone_destroyed_alert:
                alert_text = "战区被摧毁："
                if getattr(snap, "destroyed_zone_text", ""):
                    alert_text += snap.destroyed_zone_text
                else:
                    alert_text = "战区已摧毁!"
                wrap = max(int(220 * s), app.zone_frame.winfo_width() - int(16 * s))
                app.icons.configure_label(
                    app.zone_alert_lbl,
                    icon="explosion",
                    text=alert_text,
                    size=self._icon_size(18),
                    wraplength=wrap,
                    justify="left",
                )
                if (
                    snap.should_play_destroyed_sound
                    and not app._last_zone_destroyed_alert
                    and app._zone_sound_enabled
                ):
                    app.sound.play(pattern="zone_destroyed")
                app._last_zone_destroyed_alert = True
            else:
                app.icons.configure_label(app.zone_alert_lbl, icon=None, text="")
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
                    pady=(0, int(1 * s)),
                )
                self._grid_if_needed(
                    app.zone_list_frame,
                    row=4,
                    column=0,
                    sticky="ew",
                    padx=pad_x,
                    pady=(0, int(3 * s)),
                )
            else:
                self._grid_remove_if_needed(app.zone_list_header_frame)
                self._grid_remove_if_needed(app.zone_list_frame)

            row_pool = app._zone_row_pool if nav_in_main else app._compact_zone_row_pool

            idx = 0
            if not snap.zones:
                self._set_nav_row(row_pool[idx], NavListItem(direction="无战区"))
                idx += 1
            else:
                for zone in snap.zones[: ZoneConfig.MAX_DISPLAY_ZONES]:
                    zone_is_target = bool(getattr(zone, "is_target", False))
                    fg = (
                        Theme.GREEN
                        if zone_is_target and not getattr(snap, "is_deviating", False)
                        else Theme.ORANGE
                        if zone_is_target
                        else Theme.TEXT_DIM
                    )
                    self._set_nav_row(
                        row_pool[idx],
                        self._build_nav_list_item(
                            base_icon="zone",
                            selected=zone_is_target,
                            direction=getattr(zone, "direction", ""),
                            distance_km=getattr(zone, "distance_km", 0.0),
                            relative=getattr(zone, "relative", 0.0),
                            fg=fg,
                            precise_relative=zone_is_target,
                        ),
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
            app.icons.configure_label(app.zone_alert_lbl, icon=None, text="")
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
                    pady=(0, int(1 * s)),
                )
                self._grid_if_needed(
                    app.airport_list_frame,
                    row=6,
                    column=0,
                    sticky="ew",
                    padx=pad_x,
                    pady=(0, int(3 * s)),
                )
                row_pool = app._airport_row_pool
            else:
                self._grid_remove_if_needed(app.airport_header_frame)
                self._grid_remove_if_needed(app.airport_list_frame)
                row_pool = app._compact_airport_row_pool

            ap_idx = 0
            if snap.friendly_airfield:
                af = snap.friendly_airfield
                self._set_nav_row(
                    row_pool[ap_idx],
                    self._build_nav_list_item(
                        base_icon="airfield_friendly",
                        selected=True,
                        direction=getattr(af, "direction", ""),
                        distance_km=getattr(af, "distance_km", 0.0),
                        relative=getattr(af, "relative", 0.0),
                        fg=Theme.GREEN,
                    ),
                )
                ap_idx += 1

            if snap.enemy_airfields:
                for af in snap.enemy_airfields[: max(0, ZoneConfig.MAX_DISPLAY_AIRFIELDS - ap_idx)]:
                    af_is_target = bool(getattr(af, "is_target", False))
                    fg = Theme.ORANGE if af_is_target else Theme.TEXT_DIM
                    self._set_nav_row(
                        row_pool[ap_idx],
                        self._build_nav_list_item(
                            base_icon="airfield_enemy",
                            selected=af_is_target,
                            direction=getattr(af, "direction", ""),
                            distance_km=getattr(af, "distance_km", 0.0),
                            relative=getattr(af, "relative", 0.0),
                            fg=fg,
                        ),
                    )
                    ap_idx += 1

            if ap_idx == 0:
                self._set_nav_row(row_pool[0], NavListItem(direction="无数据"))
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
        model = build_fuel_display_model(snap)
        app.fuel_main_lbl.config(text=model.main_text, fg=model.main_fg)
        app.icons.configure_label(
            app.fuel_time_lbl,
            icon=model.time.icon,
            text=model.time.text,
            size=self._icon_size(18),
            fg=model.time.fg,
        )
        app.icons.configure_label(
            app.fuel_return_lbl,
            icon=model.return_status.icon,
            text=model.return_status.text,
            size=self._icon_size(18),
            fg=model.return_status.fg,
        )
        app.fuel_detail_lbl.config(text=model.detail_text)
        if hasattr(app, "fuel_alt_lbl"):
            app.fuel_alt_lbl.config(text=model.altitude_text)
        if hasattr(app, "fuel_return_detail_lbl"):
            app.fuel_return_detail_lbl.config(text=model.return_detail_text)

    def update_bombing_display(self, snap: UISnapshot) -> None:
        """更新投弹预测信息显示。"""
        app = self.app
        model = build_bombing_display_model(snap)
        app.bomb_select_lbl.config(text=model.bomb_label_text)
        app.bomb_trajectory_lbl.config(text=model.trajectory_text, fg=model.trajectory_fg)
        if hasattr(app, "bomb_flight_lbl"):
            app.bomb_flight_lbl.config(text=model.flight_text, fg=model.flight_fg)
        app.icons.configure_label(
            app.bomb_release_lbl,
            icon=model.release.icon,
            text=model.release.text,
            size=self._icon_size(18),
            fg=model.release.fg,
        )
        if hasattr(app, "bomb_release_detail_lbl"):
            app.bomb_release_detail_lbl.config(
                text=model.release_detail_text,
                fg=model.release.fg,
            )

    @staticmethod
    def format_aircraft_type_label(raw: str) -> str:
        return format_aircraft_type_label(raw)

    def update_speed_strip(self, snap: UISnapshot, debug_mock_mode: bool) -> str:
        """更新紧凑速度指示条，并返回当前超速等级。"""
        app = self.app
        model = build_speed_strip_model(snap)
        app.speed_state_lbl.config(text=model.state_text, fg=model.state_fg)
        app.speed_model_lbl.config(text=model.model_text, fg=model.model_fg)
        app.speed_value_lbl.config(text=model.value_text, fg=model.value_fg)
        app.speed_bar_fill.config(bg=model.fill_color)
        app.speed_bar_fill.place(relwidth=model.fill_ratio)

        if model.level != app._last_overspeed_level:
            app._last_overspeed_level = model.level
            app._last_overspeed_sound_ts = 0.0

        if not debug_mock_mode:
            now_sound = time.monotonic()
            if model.level == "critical":
                if (
                    now_sound - app._last_overspeed_sound_ts
                ) >= OverspeedConfig.CRITICAL_SOUND_INTERVAL_SEC:
                    app.sound.play(pattern="overspeed_critical")
                    app._last_overspeed_sound_ts = now_sound
            elif model.level == "warning":
                if (
                    now_sound - app._last_overspeed_sound_ts
                ) >= OverspeedConfig.WARNING_SOUND_INTERVAL_SEC:
                    app.sound.play(pattern="overspeed_warning")
                    app._last_overspeed_sound_ts = now_sound
            else:
                app._last_overspeed_sound_ts = 0.0
        elif model.level not in ("critical", "warning"):
            app._last_overspeed_sound_ts = 0.0

        return model.level
