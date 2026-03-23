# -*- coding: utf-8 -*-
"""Debug support helpers for the main App coordinator."""

from dataclasses import replace
from typing import Any

from bomana.config import BombConfig, Theme, UIConfig
from bomana.core.state import UISnapshot, Phase, ZoneDisplayInfo, AirfieldDisplayInfo


class AppDebugSupport:
    """Encapsulate debug-only UI and mock snapshot helpers."""

    def __init__(self, app: Any):
        self.app = app

    def toggle_debug(self) -> None:
        """切换调试模式（支持离线模拟场景）。"""
        app = self.app
        app._debug = not app._debug
        if app._debug:
            app._debug_force_mock = True
            app._debug_effective_mock = True
            self.show_debug_ui()
            if app._nudge_visible:
                app._nudge_visible = False
                app._update_hint()
        else:
            self.hide_debug_ui()
        app._recalc_size()
        app._refresh_tray()

    def show_debug_ui(self) -> None:
        """显示 Debug 控制区和诊断区。"""
        app = self.app
        self.update_debug_controls()
        if hasattr(app, "debug_ctrl_row") and app.debug_ctrl_row and app.debug_ctrl_row.winfo_manager() != "grid":
            app.debug_ctrl_row.grid(
                row=2,
                column=0,
                sticky="ew",
                padx=int(6 * app.scale),
                pady=(0, int(4 * app.scale)),
            )
        if hasattr(app, "diag_lbl") and app.diag_lbl and app.diag_lbl.winfo_manager() != "grid":
            app.diag_lbl.grid(
                row=3,
                column=0,
                sticky="ew",
                padx=int(6 * app.scale),
                pady=(0, int(UIConfig.SPACING_DEBUG * app.scale)),
            )

    def hide_debug_ui(self) -> None:
        """隐藏 Debug 控制区和诊断区。"""
        app = self.app
        if hasattr(app, "debug_ctrl_row") and app.debug_ctrl_row and app.debug_ctrl_row.winfo_manager() == "grid":
            app.debug_ctrl_row.grid_remove()
        if hasattr(app, "diag_lbl") and app.diag_lbl and app.diag_lbl.winfo_manager() == "grid":
            app.diag_lbl.grid_remove()

    def toggle_debug_mock_mode(self) -> None:
        """切换 Debug 数据源（模拟/实时）。"""
        self.app._debug_force_mock = not self.app._debug_force_mock
        self.update_debug_controls()

    def cycle_debug_scene(self, delta: int) -> None:
        """切换 Debug 场景。"""
        app = self.app
        total = max(1, len(app._debug_scene_names))
        app._debug_scene_index = (app._debug_scene_index + int(delta)) % total
        self.update_debug_controls()

    def update_debug_controls(self) -> None:
        """刷新 Debug 控制栏文案。"""
        app = self.app
        if not hasattr(app, "debug_scene_lbl"):
            return
        total = max(1, len(app._debug_scene_names))
        idx = app._debug_scene_index % total
        scene_name = app._debug_scene_names[idx]
        app.debug_scene_lbl.config(text=f"场景 {idx + 1}/{total}: {scene_name}")

        live_online = bool(app._debug_live_available)
        if app._debug_force_mock:
            source_text = "数据源: 模拟(强制)"
            source_fg = Theme.GREEN
        elif live_online:
            source_text = "数据源: 实时"
            source_fg = Theme.BLUE
        else:
            source_text = "数据源: 自动模拟"
            source_fg = Theme.YELLOW
        app.debug_source_btn.config(text=source_text, fg=source_fg, bg=Theme.BG)

    @staticmethod
    def debug_direction(relative_deg: float) -> str:
        """将相对角转换为简短方向文案。"""
        rel = float(relative_deg)
        abs_rel = abs(rel)
        if abs_rel < 8:
            return "正前"
        if abs_rel < 28:
            return "前左" if rel < 0 else "前右"
        if abs_rel < 65:
            return "左侧" if rel < 0 else "右侧"
        return "后左" if rel < 0 else "后右"

    @staticmethod
    def debug_live_snapshot_available(snap: UISnapshot) -> bool:
        """判断实时快照是否可用于完整UI测试。"""
        return (not snap.api_down) and (snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING))

    def build_debug_snapshot(self, base_snap: UISnapshot) -> UISnapshot:
        """按 Debug 状态构建渲染快照（实时或模拟）。"""
        app = self.app
        app._debug_frame_counter += 1
        app._debug_live_available = self.debug_live_snapshot_available(base_snap)
        app._debug_effective_mock = bool(app._debug_force_mock or (not app._debug_live_available))
        self.update_debug_controls()
        if not app._debug_effective_mock:
            return base_snap
        return self.build_debug_mock_snapshot(base_snap)

    def build_debug_mock_snapshot(self, base_snap: UISnapshot) -> UISnapshot:
        """构建离线可视化调试快照。"""
        app = self.app
        idx = app._debug_scene_index % max(1, len(app._debug_scene_names))
        heading = (app._debug_frame_counter * 1.8) % 360.0
        overspeed_defaults = {
            "aircraft_type_name": "mig-21_bison",
            "overspeed_level": "safe",
            "overspeed_ratio": 0.0,
            "overspeed_display_ratio": 0.0,
            "overspeed_current_ias_kmh": 0.0,
            "overspeed_current_mach": None,
            "overspeed_limit_kmh": 0.0,
            "overspeed_limit_mach": 0.0,
            "overspeed_match": False,
            "overspeed_reason": "safe",
        }

        if idx == 0:
            zones = [
                ZoneDisplayInfo("dbg-z1", 8.6, self.debug_direction(-2.4), -2.4, True, "00:42"),
                ZoneDisplayInfo("dbg-z2", 22.3, self.debug_direction(21.0), 21.0, False, ""),
                ZoneDisplayInfo("dbg-z3", 31.2, self.debug_direction(-56.0), -56.0, False, ""),
            ]
            friendly = AirfieldDisplayInfo("dbg-af-f", "friendly", 14.2, self.debug_direction(-18.0), -18.0, True, "01:18")
            enemies = [
                AirfieldDisplayInfo("dbg-af-e1", "enemy", 19.0, self.debug_direction(35.0), 35.0, True, "01:02"),
                AirfieldDisplayInfo("dbg-af-e2", "enemy", 28.8, self.debug_direction(-74.0), -74.0, False, ""),
            ]
            return replace(
                base_snap,
                phase=Phase.ALIVE,
                life_index=3,
                cycle=2,
                remaining_sec=470.0,
                progress=0.48,
                sortie_id=903,
                main_badge=("DEBUG模拟", Theme.TEXT, Theme.BLUE),
                flight_badge=("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL),
                status_text="模拟: 巡航导航",
                api_down=False,
                api_down_pending=False,
                on_ground=False,
                landed_flash=False,
                zones=zones,
                friendly_airfield=friendly,
                enemy_airfields=enemies,
                has_airfield_target=True,
                has_target=True,
                is_deviating=False,
                deviation_angle=-2.4,
                zone_destroyed_alert=False,
                destroyed_zone_count=0,
                destroyed_zone_text="",
                should_play_destroyed_sound=False,
                player_heading=heading,
                fuel_kg=1860.0,
                fuel_initial_kg=2600.0,
                fuel_percent=71.5,
                fuel_rate_kg_min=430.0,
                fuel_rate_stable=True,
                fuel_time_remaining_str="04:19",
                altitude_m=3250.0,
                return_fuel_needed_kg=580.0,
                return_status="safe",
                friendly_distance_km=14.2,
                gear_warning=False,
                gear_pct=0.0,
                gear_moving=False,
                gear_retracting=False,
                bombing_valid=False,
                bomb_name=BombConfig.selected_bomb,
                ground_speed_kmh=392.0,
                attitude_pitch_deg=3.5,
                attitude_roll_deg=-1.1,
                attitude_bank_deg=-1.1,
                attitude_reliable=True,
                hud_attitude_fallback=False,
                hud_attitude_fallback_reason="",
                **overspeed_defaults,
            )

        if idx == 1:
            rel = 37.0
            zones = [
                ZoneDisplayInfo("dbg-z1", 10.4, self.debug_direction(rel), rel, True, "00:55"),
                ZoneDisplayInfo("dbg-z2", 15.6, self.debug_direction(-14.0), -14.0, False, ""),
            ]
            friendly = AirfieldDisplayInfo("dbg-af-f", "friendly", 9.8, self.debug_direction(-10.0), -10.0, True, "00:50")
            return replace(
                base_snap,
                phase=Phase.ALIVE,
                life_index=5,
                cycle=1,
                remaining_sec=121.0,
                progress=0.87,
                sortie_id=1201,
                main_badge=("DEBUG模拟", Theme.TEXT, Theme.BLUE),
                flight_badge=("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL),
                status_text="模拟: 偏航修正中",
                api_down=False,
                api_down_pending=False,
                on_ground=False,
                landed_flash=False,
                zones=zones,
                friendly_airfield=friendly,
                enemy_airfields=[],
                has_airfield_target=True,
                has_target=True,
                is_deviating=True,
                deviation_angle=rel,
                zone_destroyed_alert=True,
                destroyed_zone_count=1,
                destroyed_zone_text="#2 右侧 6.4km",
                should_play_destroyed_sound=False,
                player_heading=heading,
                fuel_kg=1200.0,
                fuel_initial_kg=2200.0,
                fuel_percent=54.5,
                fuel_rate_kg_min=520.0,
                fuel_rate_stable=True,
                fuel_time_remaining_str="02:18",
                altitude_m=2780.0,
                return_fuel_needed_kg=410.0,
                return_status="warning",
                friendly_distance_km=9.8,
                gear_warning=False,
                gear_pct=0.0,
                gear_moving=False,
                gear_retracting=False,
                bombing_valid=False,
                bomb_name=BombConfig.selected_bomb,
                ground_speed_kmh=455.0,
                attitude_pitch_deg=1.8,
                attitude_roll_deg=6.4,
                attitude_bank_deg=6.4,
                attitude_reliable=True,
                hud_attitude_fallback=False,
                hud_attitude_fallback_reason="",
                **overspeed_defaults,
            )

        if idx == 2:
            zones = [
                ZoneDisplayInfo("dbg-z1", 18.2, self.debug_direction(-6.0), -6.0, True, "02:36"),
                ZoneDisplayInfo("dbg-z2", 30.1, self.debug_direction(42.0), 42.0, False, ""),
            ]
            friendly = AirfieldDisplayInfo("dbg-af-f", "friendly", 7.4, self.debug_direction(-3.0), -3.0, True, "01:06")
            return replace(
                base_snap,
                phase=Phase.ALIVE,
                life_index=7,
                cycle=3,
                remaining_sec=42.0,
                progress=0.95,
                sortie_id=1540,
                main_badge=("DEBUG模拟", Theme.TEXT, Theme.BLUE),
                flight_badge=("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL),
                status_text="模拟: 低油返航",
                api_down=False,
                api_down_pending=False,
                on_ground=False,
                landed_flash=False,
                zones=zones,
                friendly_airfield=friendly,
                enemy_airfields=[],
                has_airfield_target=True,
                has_target=True,
                is_deviating=False,
                deviation_angle=-6.0,
                zone_destroyed_alert=False,
                destroyed_zone_count=0,
                destroyed_zone_text="",
                should_play_destroyed_sound=False,
                player_heading=heading,
                fuel_kg=250.0,
                fuel_initial_kg=2600.0,
                fuel_percent=9.6,
                fuel_rate_kg_min=460.0,
                fuel_rate_stable=True,
                fuel_time_remaining_str="00:33",
                altitude_m=1680.0,
                return_fuel_needed_kg=340.0,
                return_status="danger",
                friendly_distance_km=7.4,
                gear_warning=False,
                gear_pct=0.0,
                gear_moving=False,
                gear_retracting=False,
                bombing_valid=False,
                bomb_name=BombConfig.selected_bomb,
                ground_speed_kmh=405.0,
                attitude_pitch_deg=-2.0,
                attitude_roll_deg=1.0,
                attitude_bank_deg=1.0,
                attitude_reliable=True,
                hud_attitude_fallback=False,
                hud_attitude_fallback_reason="",
                **overspeed_defaults,
            )

        if idx == 3:
            phase_slot = app._debug_frame_counter % 80
            if phase_slot < 18:
                release_status = "too_far"
                time_to_release = float(46 - phase_slot)
                release_distance = float(3100 - phase_slot * 40)
            elif phase_slot < 42:
                release_status = "approaching"
                time_to_release = max(0.1, float(12 - (phase_slot - 18) * 0.45))
                release_distance = max(120.0, float(980 - (phase_slot - 18) * 34))
            elif phase_slot < 52:
                release_status = "ready"
                time_to_release = max(0.01, float(0.8 - (phase_slot - 42) * 0.07))
                release_distance = max(30.0, float(95 - (phase_slot - 42) * 6.0))
            else:
                release_status = "passed"
                time_to_release = float(-(phase_slot - 52) * 0.35)
                release_distance = float(220 + (phase_slot - 52) * 18)

            zones = [
                ZoneDisplayInfo("dbg-z1", 5.6, self.debug_direction(0.7), 0.7, True, "00:28"),
                ZoneDisplayInfo("dbg-z2", 17.9, self.debug_direction(-25.0), -25.0, False, ""),
            ]
            return replace(
                base_snap,
                phase=Phase.ALIVE,
                life_index=2,
                cycle=1,
                remaining_sec=301.0,
                progress=0.66,
                sortie_id=640,
                main_badge=("DEBUG模拟", Theme.TEXT, Theme.BLUE),
                flight_badge=("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL),
                status_text="模拟: 投弹窗口测试",
                api_down=False,
                api_down_pending=False,
                on_ground=False,
                landed_flash=False,
                zones=zones,
                friendly_airfield=AirfieldDisplayInfo("dbg-af-f", "friendly", 13.0, self.debug_direction(-20.0), -20.0, True, "01:20"),
                enemy_airfields=[
                    AirfieldDisplayInfo("dbg-af-e1", "enemy", 11.2, self.debug_direction(26.0), 26.0, True, "00:52"),
                ],
                has_airfield_target=True,
                has_target=True,
                is_deviating=False,
                deviation_angle=0.7,
                zone_destroyed_alert=False,
                destroyed_zone_count=0,
                destroyed_zone_text="",
                should_play_destroyed_sound=False,
                player_heading=heading,
                fuel_kg=920.0,
                fuel_initial_kg=1800.0,
                fuel_percent=51.1,
                fuel_rate_kg_min=390.0,
                fuel_rate_stable=True,
                fuel_time_remaining_str="02:21",
                altitude_m=4120.0,
                return_fuel_needed_kg=370.0,
                return_status="safe",
                friendly_distance_km=13.0,
                gear_warning=False,
                gear_pct=0.0,
                gear_moving=False,
                gear_retracting=False,
                bombing_valid=True,
                bomb_name=BombConfig.selected_bomb,
                bomb_range_m=3200.0,
                bomb_flight_time=15.2,
                release_distance_m=release_distance,
                time_to_release=time_to_release,
                release_status=release_status,
                target_zone_distance_m=release_distance,
                ground_speed_kmh=420.0,
                attitude_pitch_deg=-0.8,
                attitude_roll_deg=0.6,
                attitude_bank_deg=0.6,
                attitude_reliable=True,
                hud_attitude_fallback=False,
                hud_attitude_fallback_reason="",
                **overspeed_defaults,
            )

        if idx == 4:
            zones = [
                ZoneDisplayInfo("dbg-z1", 0.0, "正前", 0.0, False, ""),
            ]
            return replace(
                base_snap,
                phase=Phase.ALIVE,
                life_index=1,
                cycle=1,
                remaining_sec=890.0,
                progress=0.02,
                sortie_id=100,
                main_badge=("DEBUG模拟", Theme.TEXT, Theme.BLUE),
                flight_badge=("就绪✓", Theme.TEXT, Theme.GREEN),
                status_text="模拟: 地面检查",
                api_down=False,
                api_down_pending=False,
                on_ground=True,
                landed_flash=True,
                zones=zones,
                friendly_airfield=AirfieldDisplayInfo("dbg-af-f", "friendly", 2.1, "正前", 0.0, True, ""),
                enemy_airfields=[],
                has_airfield_target=True,
                has_target=False,
                is_deviating=False,
                deviation_angle=0.0,
                zone_destroyed_alert=False,
                destroyed_zone_count=0,
                destroyed_zone_text="",
                should_play_destroyed_sound=False,
                player_heading=heading,
                fuel_kg=1540.0,
                fuel_initial_kg=1600.0,
                fuel_percent=96.0,
                fuel_rate_kg_min=0.0,
                fuel_rate_stable=False,
                fuel_time_remaining_str="",
                altitude_m=8.0,
                return_fuel_needed_kg=0.0,
                return_status="unknown",
                friendly_distance_km=2.1,
                gear_warning=False,
                gear_pct=100.0,
                gear_moving=False,
                gear_retracting=False,
                bombing_valid=False,
                bomb_name=BombConfig.selected_bomb,
                ground_speed_kmh=0.0,
                attitude_pitch_deg=0.0,
                attitude_roll_deg=0.0,
                attitude_bank_deg=0.0,
                attitude_reliable=True,
                hud_attitude_fallback=False,
                hud_attitude_fallback_reason="",
                **overspeed_defaults,
            )

        phase_slot = app._debug_frame_counter % 90
        if phase_slot < 30:
            os_level = "caution"
            os_ratio = 0.955
            os_reason = "ias"
            os_status = "模拟: 超速压测 (提前提示)"
        elif phase_slot < 60:
            os_level = "warning"
            os_ratio = 0.978
            os_reason = "ias+mach"
            os_status = "模拟: 超速压测 (接近极限)"
        else:
            os_level = "critical"
            os_ratio = 1.005
            os_reason = "ias+mach"
            os_status = "模拟: 超速压测 (危险)"

        return replace(
            base_snap,
            phase=Phase.ALIVE,
            life_index=4,
            cycle=2,
            remaining_sec=188.0,
            progress=0.79,
            sortie_id=1120,
            main_badge=("DEBUG模拟", Theme.TEXT, Theme.BLUE),
            flight_badge=("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL),
            status_text=os_status,
            api_down=False,
            api_down_pending=False,
            on_ground=False,
            landed_flash=False,
            zones=[
                ZoneDisplayInfo("dbg-z1", 11.6, self.debug_direction(-1.2), -1.2, True, "01:12"),
                ZoneDisplayInfo("dbg-z2", 23.1, self.debug_direction(18.0), 18.0, False, ""),
            ],
            friendly_airfield=AirfieldDisplayInfo("dbg-af-f", "friendly", 10.2, self.debug_direction(-8.0), -8.0, True, "01:02"),
            enemy_airfields=[],
            has_airfield_target=True,
            has_target=True,
            is_deviating=False,
            deviation_angle=-1.2,
            zone_destroyed_alert=False,
            destroyed_zone_count=0,
            destroyed_zone_text="",
            should_play_destroyed_sound=False,
            player_heading=heading,
            fuel_kg=980.0,
            fuel_initial_kg=1800.0,
            fuel_percent=54.4,
            fuel_rate_kg_min=470.0,
            fuel_rate_stable=True,
            fuel_time_remaining_str="02:05",
            altitude_m=4680.0,
            return_fuel_needed_kg=390.0,
            return_status="safe",
            friendly_distance_km=10.2,
            gear_warning=False,
            gear_pct=0.0,
            gear_moving=False,
            gear_retracting=False,
            bombing_valid=False,
            bomb_name=BombConfig.selected_bomb,
            ground_speed_kmh=980.0,
            attitude_pitch_deg=-12.0,
            attitude_roll_deg=2.8,
            attitude_bank_deg=2.8,
            attitude_reliable=True,
            hud_attitude_fallback=False,
            hud_attitude_fallback_reason="",
            overspeed_level=os_level,
            overspeed_ratio=os_ratio,
            overspeed_display_ratio=max(os_ratio, (0.86 / 0.88)),
            overspeed_current_ias_kmh=980.0 * os_ratio,
            overspeed_current_mach=0.86,
            overspeed_limit_kmh=980.0,
            overspeed_limit_mach=0.88,
            overspeed_match=True,
            overspeed_reason=os_reason,
        )

    def build_debug_text(self, live_snap: UISnapshot, render_snap: UISnapshot) -> str:
        """生成 Debug 面板文本。"""
        app = self.app
        scene_name = app._debug_scene_names[app._debug_scene_index % len(app._debug_scene_names)]
        source_text = "模拟" if app._debug_effective_mock else "实时"
        perf = live_snap.perf_debug
        source_dbg = live_snap.source_debug
        clog_dbg = live_snap.clog_debug
        lines = [
            f"[Debug] 数据源={source_text} | 场景={scene_name}",
            "操作: 点击[数据源]切实时/模拟，点击[◀/▶]切换场景",
            (
                f"Live: phase={live_snap.phase.name} api_down={int(live_snap.api_down)} "
                f"zones={len(live_snap.zones)} target={int(live_snap.has_target)}"
            ),
            (
                f"SRC: map={int(source_dbg.map_ok)} objs={source_dbg.map_obj_count} "
                f"player={int(source_dbg.player_present)} ind={int(source_dbg.indicators_ok)} "
                f"valid={int(source_dbg.indicators_valid)} state={int(source_dbg.state_ok)} "
                f"type={int(source_dbg.has_type_name)}"
            ),
            (
                f"PERF: tick={perf.tick_total_ms:.1f}ms net={perf.tick_net_ms:.1f}ms "
                f"lock_wait={perf.tick_lock_wait_ms:.1f}ms lock_hold={perf.tick_lock_hold_ms:.1f}ms "
                f"snap_wait={perf.snapshot_wait_ms:.1f}ms"
            ),
            f"UI: gap={app._last_ui_gap_ms:.1f}ms work={app._last_ui_work_ms:.1f}ms",
            (
                f"CLOG: st={clog_dbg.status} players={clog_dbg.player_count} "
                f"names={clog_dbg.player_names} err={clog_dbg.error}"
            ),
            (
                f"Render: phase={render_snap.phase.name} on_ground={int(render_snap.on_ground)} "
                f"fuel={render_snap.fuel_kg:.0f}kg ({render_snap.fuel_percent:.0f}%) "
                f"bombing={int(render_snap.bombing_valid)}"
            ),
            (
                f"Overspeed: match={int(render_snap.overspeed_match)} "
                f"level={render_snap.overspeed_level} ratio={render_snap.overspeed_ratio*100:.1f}% "
                f"limit={render_snap.overspeed_limit_kmh:.0f}km/h M{render_snap.overspeed_limit_mach:.3f}"
            ),
        ]
        if app._restored_state and (not app._debug_effective_mock) and render_snap.phase == Phase.ALIVE:
            lines.append("状态恢复: 已从保存状态恢复计时")
        return "\n".join(lines)
