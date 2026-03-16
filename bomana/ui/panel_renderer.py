# -*- coding: utf-8 -*-
"""Panel rendering helpers for the main App coordinator."""

import time
import tkinter as tk
from typing import Any

from bomana.config import (
    ENABLE_CCRP,
    ENABLE_ZONES,
    ENABLE_AIRFIELDS,
    ENABLE_FUEL,
    PanelConfig,
    ZoneConfig,
    BombConfig,
    FuelConfig,
    OverspeedConfig,
    Theme,
)
from bomana.core.state import UISnapshot
from bomana.utils.math_utils import (
    calculate_heading_tape_scale,
    get_cdi_tolerance,
    calculate_zone_turn_indicator,
    calculate_zone_status,
    calculate_airfield_turn_indicator,
    calculate_airfield_status,
    format_distance_ete,
)


class AppPanelRenderer:
    """Encapsulate large panel rendering sections for App."""

    def __init__(self, app: Any):
        self.app = app

    def update_mid_panel_layout(self) -> None:
        """更新中间面板布局（战区/检查清单）。"""
        app = self.app
        app.zone_frame.grid_forget()
        app.chk_frame.grid_forget()

        app.mid_frame.rowconfigure(0, weight=1)

        if app._zone_panel_visible and app._checklist_panel_visible:
            if not app.mid_frame.winfo_ismapped():
                app.mid_frame.pack(side="top", fill="x", pady=(0, int(8 * app.scale)), after=app.top_frame)
            app.zone_frame.grid(row=0, column=0, sticky="new", padx=(0, int(2 * app.scale)))
            app.chk_frame.grid(row=0, column=1, sticky="new", padx=(int(2 * app.scale), 0))
            if not app.chk_border_frame.winfo_ismapped():
                app.chk_border_frame.pack(side="left", fill="y", padx=(0, 2), before=app.chk_content_frame)
            app._recalc_size()
        elif app._zone_panel_visible:
            if not app.mid_frame.winfo_ismapped():
                app.mid_frame.pack(side="top", fill="x", pady=(0, int(8 * app.scale)), after=app.top_frame)
            app.zone_frame.grid(row=0, column=0, columnspan=2, sticky="new")
            app._recalc_size()
        elif app._checklist_panel_visible:
            if not app.mid_frame.winfo_ismapped():
                app.mid_frame.pack(side="top", fill="x", pady=(0, int(8 * app.scale)), after=app.top_frame)
            app.chk_frame.grid(row=0, column=0, columnspan=2, sticky="new")
            app.chk_border_frame.pack_forget()
            app._recalc_size()
        else:
            app.mid_frame.pack_forget()
            app._recalc_size(force_shrink=True)

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

            if app.tape_zone_row:
                app.tape_zone_row.pack(fill="x", pady=(int(2 * app.scale), 0))
        elif app.tape_turn_lbl and app.tape_deviation_lbl and app.tape_tolerance_lbl:
            app.tape_turn_lbl.config(text="", fg=Theme.TEXT_MUTED)
            app.tape_deviation_lbl.config(text="无目标", fg=Theme.TEXT_MUTED)
            if hasattr(app, "tape_zone_info") and app.tape_zone_info:
                app.tape_zone_info.config(text="")
            app.tape_tolerance_lbl.config(text="")
            if app.tape_zone_row:
                app.tape_zone_row.pack_forget()

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

            if app.tape_friendly_row:
                app.tape_friendly_row.pack(fill="x", pady=(int(1 * app.scale), 0))
        elif app.tape_friendly_row:
            app.tape_friendly_row.pack_forget()

    def set_checklist_visible(self, visible: bool) -> None:
        """设置检查清单可见性。"""
        app = self.app
        if app._checklist_panel_visible != visible:
            app._checklist_panel_visible = visible
            self.update_mid_panel_layout()

    def update_zone_display(self, snap: UISnapshot):
        """更新战区显示，并返回是否需要重算布局尺寸。"""
        app = self.app
        s = app.scale
        font_item = app._get_font("zone_item")
        pad_x = int(8 * s)

        raw_heading = float(getattr(snap, "player_heading", 0.0) or 0.0)
        heading_deg = raw_heading % 360.0
        heading_available = (snap.phase in app._alive_phases) and (not snap.api_down)

        if heading_available:
            app.heading_lbl.config(text=f"航向: {int(heading_deg):03d}°")
        else:
            app.heading_lbl.config(text="航向: ---°")

        zone_count = 0
        airport_count = 0
        zones_enabled = ENABLE_ZONES and PanelConfig.is_effectively_enabled("zones")
        airfields_enabled = ENABLE_AIRFIELDS and PanelConfig.is_effectively_enabled("airfields")
        fuel_enabled = ENABLE_FUEL and PanelConfig.is_effectively_enabled("fuel")
        bombing_enabled = ENABLE_CCRP and PanelConfig.is_effectively_enabled("bombing")

        if zones_enabled:
            app.zone_header_frame.grid(row=0, column=0, sticky="ew", padx=pad_x, pady=(int(6 * s), int(2 * s)))
            app.zone_list_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10 * s)))

            if app.heading_tape is not None and heading_available:
                targets = []
                active_targets_info = []
                target_zone = next((z for z in snap.zones if z.is_target), None)
                for zone in snap.zones:
                    is_target = zone.is_target
                    targets.append({
                        "type": "zone",
                        "relative": zone.relative,
                        "distance_km": zone.distance_km,
                        "is_primary": is_target,
                        "is_target": is_target,
                    })
                    if is_target:
                        active_targets_info.append({
                            "type": "zone",
                            "name": "战区",
                            "icon": "⊚",
                            "relative": zone.relative,
                            "distance_km": zone.distance_km,
                            "ete_str": zone.ete_str if hasattr(zone, "ete_str") else "",
                            "color": Theme.RED,
                        })

                if snap.zone_destroyed_alert and hasattr(app.game.state.zone_nav, "destroyed_zones"):
                    for dz in app.game.state.zone_nav.destroyed_zones:
                        if hasattr(dz, "relative"):
                            targets.append({
                                "type": "destroyed",
                                "relative": dz.relative,
                                "distance_km": dz.distance * ZoneConfig.DISTANCE_SCALE,
                                "is_primary": False,
                            })

                if snap.friendly_airfield:
                    af = snap.friendly_airfield
                    is_in_front = abs(af.relative) <= 90
                    targets.append({
                        "type": "friendly",
                        "relative": af.relative,
                        "distance_km": af.distance_km,
                        "is_primary": False,
                        "is_target": is_in_front,
                    })
                    if is_in_front:
                        active_targets_info.append({
                            "type": "friendly",
                            "name": "友方",
                            "icon": "✈",
                            "relative": af.relative,
                            "distance_km": af.distance_km,
                            "ete_str": af.ete_str,
                            "color": Theme.BLUE,
                        })

                if snap.enemy_airfields:
                    for af in snap.enemy_airfields:
                        is_in_front = abs(af.relative) <= 90
                        targets.append({
                            "type": "enemy",
                            "relative": af.relative,
                            "distance_km": af.distance_km,
                            "is_primary": False,
                            "is_target": is_in_front,
                        })
                        if af.is_target and is_in_front:
                            active_targets_info.append({
                                "type": "enemy",
                                "name": "敌方",
                                "icon": "✈",
                                "relative": af.relative,
                                "distance_km": af.distance_km,
                                "ete_str": af.ete_str,
                                "color": Theme.ORANGE,
                            })

                primary_dist = target_zone.distance_km if target_zone else 10.0
                app.heading_tape.update_tape_multi(heading_deg, targets, primary_dist)
                self.update_tape_info_labels(active_targets_info, target_zone)

                if PanelConfig.navigation_mode == "integrated":
                    app.heading_tape_frame.grid(row=1, column=0, sticky="ew", padx=pad_x, pady=(int(2 * s), int(4 * s)))
                else:
                    app.heading_tape_frame.grid_remove()

                if hasattr(app, "nav_window") and app.nav_window and app.nav_window.is_visible():
                    app.nav_window.update_display(snap, targets, active_targets_info, target_zone)
            elif app.heading_tape is not None:
                app.heading_tape.clear()
                if app.tape_info_container:
                    for lbl in app._tape_info_labels:
                        lbl.pack_forget()
                if PanelConfig.navigation_mode == "integrated":
                    app.heading_tape_frame.grid(row=1, column=0, sticky="ew", padx=pad_x, pady=(int(2 * s), int(4 * s)))
                if hasattr(app, "nav_window") and app.nav_window and app.nav_window.is_visible():
                    app.nav_window.update_display(snap, [], [], None)

            if snap.zone_destroyed_alert:
                alert_text = "💥 战区被摧毁："
                if getattr(snap, "destroyed_zone_text", ""):
                    alert_text += snap.destroyed_zone_text
                else:
                    alert_text = "💥 战区已摧毁!"
                wrap = max(int(220 * s), app.zone_frame.winfo_width() - int(16 * s))
                app.zone_alert_lbl.config(text=alert_text, wraplength=wrap, justify="left")
                app.zone_alert_lbl.grid(row=2, column=0, sticky="ew", padx=pad_x, pady=(0, int(4 * s)))
                if snap.should_play_destroyed_sound and not app._last_zone_destroyed_alert and app._zone_sound_enabled:
                    app.sound.play(pattern="zone_destroyed")
                app._last_zone_destroyed_alert = True
            else:
                app.zone_alert_lbl.grid_remove()
                app._last_zone_destroyed_alert = False

            is_compact = (PanelConfig.navigation_mode == "standalone")
            zone_layout_mode = "compact" if is_compact else "full"
            if app._zone_layout_mode != zone_layout_mode:
                app._hide_label_pool(app._zone_label_pool)
                app._hide_label_pool(app._compact_zone_label_pool)
                app._zone_layout_mode = zone_layout_mode

            if is_compact:
                app.compact_nav_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10 * s)))
                app.zone_list_frame.grid_remove()
                if airfields_enabled:
                    app.compact_airport_frame.grid(row=0, column=1, sticky="nsew", padx=(int(4 * s), 0))
                    app.compact_zone_frame.grid(row=0, column=0, columnspan=1, sticky="nsew", padx=(0, int(4 * s)))
                else:
                    app.compact_airport_frame.grid_remove()
                    app.compact_zone_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=(0, 0))
            else:
                app.compact_nav_frame.grid_remove()
                app.zone_list_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10 * s)))

            zone_count = len(snap.zones) if snap.zones else 1
            if is_compact:
                target_frame = app.compact_zone_list
                label_pool = app._compact_zone_label_pool
            else:
                target_frame = app.zone_list_frame
                label_pool = app._zone_label_pool

            while len(label_pool) < zone_count:
                lbl = tk.Label(target_frame, text="", font=font_item, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w")
                label_pool.append(lbl)

            idx = 0
            if not snap.zones:
                lbl = label_pool[idx]
                lbl.config(text="无战区", fg=Theme.TEXT_MUTED)
                if not lbl.winfo_ismapped():
                    lbl.pack(fill="x")
                idx += 1
            else:
                for zone in snap.zones:
                    marker = "➤" if zone.is_target else "○"
                    dist_text = f"{zone.distance_km:.1f}km" if zone.distance_km < 10 else f"{int(zone.distance_km)}km"
                    if is_compact:
                        text = f"{marker} {zone.direction} {dist_text}"
                    else:
                        rel_sign = "+" if zone.relative > 0 else ""
                        rel_text = f"{rel_sign}{zone.relative:.2f}°" if zone.is_target else f"{rel_sign}{int(zone.relative)}°"
                        text = f"{marker} {zone.direction} {dist_text}  ({rel_text})"
                    fg = Theme.GREEN if zone.is_target and not snap.is_deviating else Theme.ORANGE if zone.is_target else Theme.TEXT_DIM
                    lbl = label_pool[idx]
                    lbl.config(text=text, fg=fg)
                    if not lbl.winfo_ismapped():
                        lbl.pack(fill="x")
                    idx += 1
            app._hide_label_pool(label_pool, idx)
        else:
            app.zone_header_frame.grid_remove()
            app.zone_list_frame.grid_remove()
            app.compact_nav_frame.grid_remove()
            app.zone_alert_lbl.grid_remove()
            app._hide_label_pool(app._zone_label_pool)
            app._hide_label_pool(app._compact_zone_label_pool)
            app._zone_layout_mode = None

        if airfields_enabled:
            is_compact = (PanelConfig.navigation_mode == "standalone")
            airport_layout_mode = "compact" if is_compact else "full"
            if app._airport_layout_mode != airport_layout_mode:
                app._hide_label_pool(app._airport_label_pool)
                app._hide_label_pool(app._compact_airport_label_pool)
                app._airport_layout_mode = airport_layout_mode

            if is_compact:
                app.compact_nav_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10 * s)))
                app.airport_title_lbl.grid_remove()
                app.airport_list_frame.grid_remove()
                target_frame = app.compact_airport_list
                label_pool = app._compact_airport_label_pool
            else:
                app.airport_title_lbl.grid(row=4, column=0, sticky="ew", padx=pad_x, pady=(0, int(2 * s)))
                app.airport_list_frame.grid(row=6, column=0, sticky="ew", padx=pad_x, pady=(0, int(10 * s)))
                target_frame = app.airport_list_frame
                label_pool = app._airport_label_pool

            airport_count = 0
            if snap.friendly_airfield:
                airport_count += 1
            if snap.enemy_airfields:
                airport_count += len(snap.enemy_airfields)
            if airport_count == 0:
                airport_count = 1

            while len(label_pool) < airport_count:
                lbl = tk.Label(target_frame, text="", font=font_item, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w")
                label_pool.append(lbl)

            ap_idx = 0
            if snap.friendly_airfield:
                af = snap.friendly_airfield
                dist_text = f"{af.distance_km:.1f}km" if af.distance_km < 10 else f"{int(af.distance_km)}km"
                if is_compact:
                    text = f"🟢 {af.direction} {dist_text}"
                else:
                    rel_sign = "+" if af.relative > 0 else ""
                    rel_text = f"{rel_sign}{int(af.relative)}°"
                    text = f"🟢 ➤ {af.direction} {dist_text}  ({rel_text})"
                lbl = label_pool[ap_idx]
                lbl.config(text=text, fg=Theme.GREEN)
                if not lbl.winfo_ismapped():
                    lbl.pack(fill="x")
                ap_idx += 1

            if snap.enemy_airfields:
                for af in snap.enemy_airfields:
                    marker = "➤" if af.is_target else "○"
                    dist_text = f"{af.distance_km:.1f}km" if af.distance_km < 10 else f"{int(af.distance_km)}km"
                    if is_compact:
                        text = f"🔴 {af.direction} {dist_text}"
                    else:
                        rel_sign = "+" if af.relative > 0 else ""
                        rel_text = f"{rel_sign}{int(af.relative)}°"
                        text = f"🔴 {marker} {af.direction} {dist_text}  ({rel_text})"
                    fg = Theme.ORANGE if af.is_target else Theme.TEXT_DIM
                    lbl = label_pool[ap_idx]
                    lbl.config(text=text, fg=fg)
                    if not lbl.winfo_ismapped():
                        lbl.pack(fill="x")
                    ap_idx += 1

            if ap_idx == 0:
                lbl = label_pool[0]
                lbl.config(text="无数据", fg=Theme.TEXT_MUTED)
                if not lbl.winfo_ismapped():
                    lbl.pack(fill="x")
                ap_idx = 1
            app._hide_label_pool(label_pool, ap_idx)
        else:
            app.airport_title_lbl.grid_remove()
            if app.airport_tape_frame:
                app.airport_tape_frame.grid_remove()
            app.airport_list_frame.grid_remove()
            app._hide_label_pool(app._airport_label_pool)
            app._hide_label_pool(app._compact_airport_label_pool)
            app._airport_layout_mode = None

        if fuel_enabled:
            app.fuel_title_lbl.grid(row=7, column=0, sticky="ew", padx=pad_x, pady=(0, int(2 * s)))
            app.fuel_info_frame.grid(row=8, column=0, sticky="ew", padx=pad_x, pady=(0, int(6 * s)))
            self.update_fuel_display(snap)
        else:
            app.fuel_title_lbl.grid_remove()
            app.fuel_info_frame.grid_remove()

        if ENABLE_CCRP:
            if bombing_enabled:
                app.bombing_title_lbl.grid(row=9, column=0, sticky="ew", padx=pad_x, pady=(0, int(2 * s)))
                app.bombing_info_frame.grid(row=10, column=0, sticky="ew", padx=pad_x, pady=(0, int(6 * s)))
                self.update_bombing_display(snap)
            else:
                app.bombing_title_lbl.grid_remove()
                app.bombing_info_frame.grid_remove()

        layout_signature = (
            PanelConfig.navigation_mode,
            bool(zones_enabled),
            bool(airfields_enabled),
            bool(fuel_enabled),
            bool(bombing_enabled),
            bool(snap.zone_destroyed_alert),
            int(zone_count),
            int(airport_count),
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
            if snap.fuel_time_remaining_str:
                fuel_text += f"  ⏱️ {snap.fuel_time_remaining_str}"
            else:
                fuel_text += "  ⏱️ 计算中..."

            if snap.fuel_percent <= FuelConfig.DANGER_PERCENT:
                fuel_color = Theme.RED
            elif snap.fuel_percent <= FuelConfig.WARNING_PERCENT:
                fuel_color = Theme.YELLOW
            else:
                fuel_color = Theme.TEXT

            app.fuel_main_lbl.config(text=fuel_text, fg=fuel_color)
        else:
            app.fuel_main_lbl.config(text="-- kg (--%)", fg=Theme.TEXT_MUTED)

        if snap.fuel_rate_stable and snap.fuel_rate_kg_min > 0:
            rate_text = f"油耗 {snap.fuel_rate_kg_min:.0f}kg/min"
        else:
            rate_text = "油耗 --"

        alt_text = f"高度 {int(snap.altitude_m)}m" if snap.altitude_m > 0 else "高度 --"
        app.fuel_detail_lbl.config(text=f"{rate_text} │ {alt_text}")

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

            app.fuel_return_lbl.config(text=f"🏠 返航: {needed_text}  {status_icon}", fg=return_color)
        elif snap.friendly_distance_km > 0:
            app.fuel_return_lbl.config(
                text=f"🏠 返航: 距离{snap.friendly_distance_km:.0f}km (估算中...)",
                fg=Theme.TEXT_MUTED,
            )
        else:
            app.fuel_return_lbl.config(text="🏠 返航: 无机场数据", fg=Theme.TEXT_MUTED)

    def update_bombing_display(self, snap: UISnapshot) -> None:
        """更新投弹预测信息显示。"""
        app = self.app
        app.bomb_select_lbl.config(text=f"炸弹: {BombConfig.format_bomb_name(snap.bomb_name)} (点击更换)")

        if snap.bombing_valid:
            bomb_range_km = snap.bomb_range_m / 1000.0
            trajectory_text = f"弹道: {bomb_range_km:.2f}km │ 飞行: {snap.bomb_flight_time:.1f}s"
            app.bomb_trajectory_lbl.config(text=trajectory_text, fg=Theme.TEXT_DIM)

            status = snap.release_status
            dist_m = snap.release_distance_m
            if dist_m > 1000:
                dist_str = f"{dist_m/1000:.2f}km"
            elif dist_m > 100:
                dist_str = f"{int(dist_m)}m"
            else:
                dist_str = f"{dist_m:.0f}m"

            if status == "ready":
                time_str = f"{snap.time_to_release:.2f}s"
                release_text = f"💣 投弹! {time_str} ({dist_str})"
                release_color = Theme.GREEN
            elif status == "approaching":
                time_str = f"{snap.time_to_release:.1f}s"
                release_text = f"⏱️ {time_str} ({dist_str})"
                release_color = Theme.YELLOW
            elif status == "passed":
                release_text = f"❌ 已飞过 {dist_str}"
                release_color = Theme.RED
            elif status == "too_far":
                time_str = f"{snap.time_to_release:.0f}s"
                release_text = f"🎯 {dist_str} ({time_str})"
                release_color = Theme.TEXT_DIM
            else:
                release_text = "⏳ 计算中..."
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
        aircraft_type_name = self.format_aircraft_type_label(str(getattr(snap, "aircraft_type_name", "") or ""))

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
                if (now_sound - app._last_overspeed_sound_ts) >= OverspeedConfig.CRITICAL_SOUND_INTERVAL_SEC:
                    app.sound.play(pattern="overspeed_critical")
                    app._last_overspeed_sound_ts = now_sound
            elif speed_level == "warning":
                if (now_sound - app._last_overspeed_sound_ts) >= OverspeedConfig.WARNING_SOUND_INTERVAL_SEC:
                    app.sound.play(pattern="overspeed_warning")
                    app._last_overspeed_sound_ts = now_sound
            else:
                app._last_overspeed_sound_ts = 0.0
        elif speed_level not in ("critical", "warning"):
            app._last_overspeed_sound_ts = 0.0

        return speed_level
