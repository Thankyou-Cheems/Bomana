"""Runtime-facing UI services split out of the main App coordinator."""

from __future__ import annotations

import contextlib
import os
import time
import tkinter as tk
from typing import Any

from bomana.config.feature_profile import (
    ENABLE_ADVANCED_SETTINGS,
    ENABLE_AIRFIELDS,
    ENABLE_CCRP,
    ENABLE_CHECKLIST,
    ENABLE_FUEL,
    ENABLE_ZONES,
)
from bomana.config.settings import (
    FileConfig,
    HotkeyConfig,
    HUDConfig,
    PanelConfig,
    ZoneConfig,
)
from bomana.core.state import Phase, UISnapshot
from bomana.metadata import __title__
from bomana.ui.hud_overlay import HUDOverlay
from bomana.ui.hud_presenter import build_hud_target_model
from bomana.ui.runtime import start_daemon_thread
from bomana.ui.theme import Theme
from bomana.utils.diagnostics import log_event, log_exception
from bomana.utils.file_utils import resource_path
from bomana.utils.hotkey_broker import (
    BrokerBinding,
    BrokerStartStatus,
    ElevatedHotkeyBrokerClient,
    GameIntegrityStatus,
    detect_war_thunder_integrity,
)
from bomana.utils.system import GlobalHotkeys

try:
    import pystray
    from PIL import Image

    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False


class AppRuntimeServices:
    """Own optional runtime integrations kept out of the main App body."""

    def __init__(self, app: Any):
        self.app = app
        self.global_hotkeys: GlobalHotkeys | None = None
        self.hotkey_broker: ElevatedHotkeyBrokerClient | None = None
        self.tray: Any | None = None
        self.hud_overlay: HUDOverlay | None = None
        self.local_hotkey_sequences: list[str] = []
        self._hud_monitor_refresh_ts = 0.0
        self._hud_last_target: dict[str, Any] | None = None
        self._hud_target_hold_sec = 1.2
        self._hud_render_error_count = 0

    def init_global_hotkeys(self) -> None:
        """Initialize runtime-configurable Windows global hotkeys."""
        if not self.stop_global_hotkeys():
            return
        if os.name != "nt" or not HotkeyConfig.GLOBAL_HOTKEYS:
            self._set_hotkey_broker_notice("", "")
            return

        hotkeys = self._configured_hotkeys()
        self._start_local_hotkeys(hotkeys)
        integrity = detect_war_thunder_integrity()
        log_event(
            "war_thunder_integrity_probe",
            status=integrity.status.value,
            process_id=integrity.process_id,
            image_name=integrity.image_name,
        )
        if integrity.status is GameIntegrityStatus.ORDINARY:
            self._set_hotkey_broker_notice("", "")
        elif integrity.status is GameIntegrityStatus.ELEVATED:
            self._set_hotkey_broker_notice(
                "检测到 War Thunder 以管理员权限运行；普通热键可能在游戏前台失效。",
                "elevate",
            )
        elif integrity.status is GameIntegrityStatus.NOT_RUNNING:
            self._set_hotkey_broker_notice(
                "尚未检测到 War Thunder；普通热键已启用，如游戏以管理员运行可手动授权。",
                "elevate",
            )
        elif integrity.status is GameIntegrityStatus.UNKNOWN:
            self._set_hotkey_broker_notice(
                "无法判断 War Thunder 权限；普通热键已启用，需要时可手动授权。",
                "elevate",
            )
        else:
            self._set_hotkey_broker_notice("", "")

    def enable_elevated_hotkeys(self) -> None:
        """Request the optional broker only after explicit user confirmation."""

        if os.name != "nt" or not HotkeyConfig.GLOBAL_HOTKEYS:
            return
        hotkeys = self._configured_hotkeys()
        if not self._stop_local_global_hotkeys():
            return
        broker = ElevatedHotkeyBrokerClient(
            self.app.dispatcher.post,
            [
                BrokerBinding(action, key_name, callback)
                for action, _hotkey_id, key_name, callback in hotkeys
            ],
            ready_cb=self._on_hotkey_broker_ready,
            failure_cb=self._on_hotkey_broker_failure,
        )
        result = broker.start()
        if result.status is BrokerStartStatus.STARTED:
            self.hotkey_broker = broker
            self._set_hotkey_broker_notice("正在连接管理员热键组件…", "")
            return

        broker.stop()
        self._start_local_hotkeys(hotkeys)
        if result.status in (BrokerStartStatus.UNAVAILABLE, BrokerStartStatus.UNTRUSTED):
            self._set_hotkey_broker_notice(
                f"{result.message or '当前 App 包的热键组件不可用。'} 普通热键已恢复。",
                "",
            )
        elif result.status in (BrokerStartStatus.CANCELLED, BrokerStartStatus.FAILED):
            message = "未启用管理员热键；普通热键已恢复，游戏以前台高权限运行时可能失效。"
            self._set_hotkey_broker_notice(message, "elevate")
        else:
            self._set_hotkey_broker_notice("", "")

    def _configured_hotkeys(self) -> list[tuple[str, int, str, Any]]:
        hotkeys = [
            (
                "reset",
                HotkeyConfig.HK_ID_RESET,
                HotkeyConfig.KEY_RESET,
                self.app._manual_reset_hotkey,
            ),
            ("lock", HotkeyConfig.HK_ID_LOCK, HotkeyConfig.KEY_LOCK, self.app._toggle_lock),
            (
                "corner",
                HotkeyConfig.HK_ID_CORNER,
                HotkeyConfig.KEY_CORNER,
                self.app._next_corner,
            ),
            ("beep", HotkeyConfig.HK_ID_BEEP, HotkeyConfig.KEY_BEEP, self.app._toggle_beep),
        ]
        if ENABLE_ZONES:
            hotkeys.append(
                (
                    "zones",
                    HotkeyConfig.HK_ID_ZONES,
                    HotkeyConfig.KEY_ZONES,
                    self.app._toggle_zone_sound,
                )
            )
        return hotkeys

    def _start_local_hotkeys(self, hotkeys: list[tuple[str, int, str, Any]]) -> None:
        self.global_hotkeys = GlobalHotkeys(
            self.app.dispatcher.post,
            [(hotkey_id, key_name, callback) for _action, hotkey_id, key_name, callback in hotkeys],
            error_cb=self.app._on_hotkey_registration_error,
        )
        self.global_hotkeys.start()

    def _on_hotkey_broker_ready(self, failed_keys: tuple[str, ...]) -> None:
        if failed_keys:
            joined = "、".join(failed_keys)
            self._set_hotkey_broker_notice(
                f"游戏内热键 {joined} 注册失败；请检查按键冲突后重试。",
                "elevate",
            )
            self.app._on_hotkey_registration_error(failed_keys)
            return
        self._set_hotkey_broker_notice("", "")

    def _on_hotkey_broker_failure(self, message: str) -> None:
        broker = self.hotkey_broker
        self.hotkey_broker = None
        if broker is not None:
            broker.stop()
        if HotkeyConfig.GLOBAL_HOTKEYS and self.global_hotkeys is None:
            self._start_local_hotkeys(self._configured_hotkeys())
        self._set_hotkey_broker_notice(
            (
                f"{message} 游戏以前台高权限运行时，F7-F11 可能失效；"
                "窗口按钮、托盘与 8111 功能不受影响。"
            ),
            "elevate",
        )

    def _set_hotkey_broker_notice(self, message: str, action: str) -> None:
        callback = getattr(self.app, "_set_hotkey_broker_notice", None)
        if callable(callback):
            callback(message, action)

    def retry_hotkey_broker(self) -> None:
        """Retry one explicit UAC broker request from the App notice action."""
        self.enable_elevated_hotkeys()

    def _stop_local_global_hotkeys(self) -> bool:
        manager = self.global_hotkeys
        if manager is None:
            return True
        try:
            manager.stop()
        except Exception as exc:
            log_exception("global_hotkeys_stop_failed", exc)
            return False
        self.global_hotkeys = None
        return True

    def stop_global_hotkeys(self) -> bool:
        stopped = True
        broker = self.hotkey_broker
        self.hotkey_broker = None
        if broker is not None:
            try:
                broker.stop()
            except Exception as exc:
                log_exception("hotkey_broker_stop_failed", exc)
                stopped = False
        return self._stop_local_global_hotkeys() and stopped

    def refresh_local_hotkey_bindings(self) -> None:
        """Refresh Tk-local hotkeys after settings mutate HotkeyConfig."""
        for sequence in self.local_hotkey_sequences:
            with contextlib.suppress(tk.TclError):
                self.app.root.unbind(sequence)

        bindings = [
            (HotkeyConfig.KEY_LOCK, self.app._toggle_lock),
            (HotkeyConfig.KEY_CORNER, self.app._next_corner),
            (HotkeyConfig.KEY_BEEP, self.app._toggle_beep),
        ]
        if ENABLE_ZONES:
            bindings.append((HotkeyConfig.KEY_ZONES, self.app._toggle_zone_sound))

        self.local_hotkey_sequences = []
        for key_name, callback in bindings:
            normalized_key = HotkeyConfig.normalize_key(key_name)
            if normalized_key is None:
                continue
            sequence = f"<{normalized_key}>"
            try:
                self.app.root.bind(sequence, lambda _event, cb=callback: cb())
            except tk.TclError:
                continue
            self.local_hotkey_sequences.append(sequence)

    def refresh_tray(self) -> None:
        """Refresh the system tray menu if it exists."""
        tray = self.tray
        if not HAS_TRAY or tray is None:
            return
        with contextlib.suppress(Exception):
            tray.update_menu()

    def init_tray(self) -> None:
        """Create and start the optional system tray integration."""
        if not HAS_TRAY:
            return

        app = self.app

        def icon():
            try:
                p = resource_path(FileConfig.ICON_FILE)
                if os.path.exists(p):
                    return Image.open(p).convert("RGBA")
            except Exception:
                pass
            return Image.new("RGBA", (64, 64), Theme.BLUE)

        def do_reset(icon, item):
            app.dispatcher.post(app._manual_reset)

        def do_lock(icon, item):
            app.dispatcher.post(app._toggle_lock)

        def do_corner(icon, item):
            app.dispatcher.post(app._next_corner)

        def do_beep(icon, item):
            app.dispatcher.post(app._toggle_beep)

        def do_zone_sound(icon, item):
            app.dispatcher.post(app._toggle_zone_sound)

        def do_speed_history(icon, item):
            app.dispatcher.post(app._toggle_speed_history_mode)

        def do_edit_checklist(icon, item):
            app.dispatcher.post(app._edit_checklist)

        def do_settings(icon, item):
            app.dispatcher.post(app._show_settings)

        def do_debug(icon, item):
            app.dispatcher.post(app._toggle_debug)

        def do_quit(icon, item):
            app.dispatcher.post(app._quit)

        def do_about(icon, item):
            app.dispatcher.post(app._show_about)

        def do_star(icon, item):
            app.dispatcher.post(app._open_star_url)

        def is_locked(item):
            return app._locked

        def is_beep_on(item):
            return app.sound.is_enabled()

        def is_zone_sound_on(item):
            return app._zone_sound_enabled

        def is_debug_on(item):
            return app._debug

        def is_speed_history_mode(item):
            return PanelConfig.speed_history_mode

        menu_items = [
            pystray.MenuItem("立即重置计时器", do_reset),
            pystray.MenuItem(f"锁定/解锁 ({HotkeyConfig.KEY_LOCK})", do_lock, checked=is_locked),
            pystray.MenuItem(f"切换角落 ({HotkeyConfig.KEY_CORNER})", do_corner),
            pystray.MenuItem("空历速度模式", do_speed_history, checked=is_speed_history_mode),
            pystray.Menu.SEPARATOR,
        ]

        if ENABLE_ADVANCED_SETTINGS:

            def toggle_zone(icon, item):
                app.dispatcher.post(app._toggle_panel, "show_zones")

            def toggle_airfield(icon, item):
                app.dispatcher.post(app._toggle_panel, "show_airfields")

            def toggle_fuel(icon, item):
                app.dispatcher.post(app._toggle_panel, "show_fuel")

            def toggle_speed(icon, item):
                app.dispatcher.post(app._toggle_panel, "show_speed")

            def toggle_checklist(icon, item):
                app.dispatcher.post(app._toggle_panel, "show_checklist")

            def toggle_bombing(icon, item):
                app.dispatcher.post(app._toggle_panel, "show_bombing")

            def is_zone_panel(item):
                return PanelConfig.is_effectively_enabled("zones")

            def is_airfield_panel(item):
                return PanelConfig.is_effectively_enabled("airfields")

            def is_fuel_panel(item):
                return PanelConfig.is_effectively_enabled("fuel")

            def is_speed_panel(item):
                return PanelConfig.is_effectively_enabled("speed")

            def is_checklist_panel(item):
                return PanelConfig.is_effectively_enabled("checklist")

            def is_bombing_panel(item):
                return PanelConfig.is_effectively_enabled("bombing")

            panel_items = []
            if ENABLE_ZONES:
                panel_items.append(pystray.MenuItem("战区导航", toggle_zone, checked=is_zone_panel))
            if ENABLE_AIRFIELDS:
                panel_items.append(
                    pystray.MenuItem("机场导航", toggle_airfield, checked=is_airfield_panel)
                )
            if ENABLE_FUEL:
                panel_items.append(pystray.MenuItem("燃油管理", toggle_fuel, checked=is_fuel_panel))
            panel_items.append(pystray.MenuItem("速度监视", toggle_speed, checked=is_speed_panel))
            if ENABLE_CCRP:
                panel_items.append(
                    pystray.MenuItem("投弹预测", toggle_bombing, checked=is_bombing_panel)
                )
            if ENABLE_CHECKLIST:
                panel_items.append(
                    pystray.MenuItem("出击检查", toggle_checklist, checked=is_checklist_panel)
                )

            if panel_items:
                menu_items.append(pystray.MenuItem("显示面板", pystray.Menu(*panel_items)))

            if ENABLE_ZONES:

                def toggle_nav_mode(icon, item):
                    app.dispatcher.post(app._toggle_navigation_mode)

                def is_standalone_nav(item):
                    return PanelConfig.navigation_mode == "standalone"

                menu_items.append(
                    pystray.MenuItem("独立导航窗口", toggle_nav_mode, checked=is_standalone_nav)
                )

            menu_items.append(pystray.Menu.SEPARATOR)

        menu_items.append(
            pystray.MenuItem(f"声音 ({HotkeyConfig.KEY_BEEP})", do_beep, checked=is_beep_on)
        )

        if ENABLE_ZONES:
            menu_items.append(
                pystray.MenuItem(
                    f"战区提示音 ({HotkeyConfig.KEY_ZONES})",
                    do_zone_sound,
                    checked=is_zone_sound_on,
                )
            )

        if ENABLE_CHECKLIST:
            menu_items.append(pystray.MenuItem("编辑检查清单", do_edit_checklist))

        if ENABLE_ADVANCED_SETTINGS:
            menu_items.append(pystray.MenuItem("设置", do_settings))

        menu_items.append(pystray.Menu.SEPARATOR)
        menu_items.append(pystray.MenuItem("给作者点个Star", do_star))
        menu_items.append(pystray.MenuItem("Debug模式", do_debug, checked=is_debug_on))
        menu_items.append(pystray.MenuItem("关于", do_about))
        menu_items.append(pystray.MenuItem("退出", do_quit))

        self.tray = pystray.Icon(__title__, icon(), __title__, pystray.Menu(*menu_items))
        start_daemon_thread("BomanaTray", self.tray.run)

    def stop_tray(self) -> None:
        tray = self.tray
        self.tray = None
        if tray is None:
            return
        with contextlib.suppress(Exception):
            tray.stop()

    def ensure_hud_overlay(self) -> bool:
        """Ensure a HUD overlay exists and is ready for updates."""
        if self.hud_overlay:
            return True
        try:
            self.hud_overlay = HUDOverlay(self.app)
            self.hud_overlay.set_lock_state(self.app._locked)
            self._hud_monitor_refresh_ts = 0.0
            log_event("hud_overlay_created", locked=self.app._locked)
            return True
        except Exception as exc:
            self.hud_overlay = None
            log_exception("hud_overlay_init_failed", exc)
            return False

    def show_hud_overlay(self) -> bool:
        """Show the HUD overlay if it can be created."""
        if not self.ensure_hud_overlay():
            return False
        try:
            self.hud_overlay.show()
            self.hud_overlay.set_lock_state(self.app._locked)
            self._hud_monitor_refresh_ts = 0.0
            return True
        except Exception as exc:
            log_exception("hud_overlay_show_failed", exc)
            return False

    def update_hud_overlay(self, snap: UISnapshot) -> None:
        """Update the HUD overlay from the current UI snapshot."""
        overlay = self.hud_overlay
        if not HUDConfig.enabled:
            if overlay and overlay.is_visible():
                overlay.hide()
            self._hud_last_target = None
            return

        if not self.show_hud_overlay():
            HUDConfig.enabled = False
            self.app._update_hint()
            self.app._save_config()
            self.refresh_tray()
            self._hud_last_target = None
            return

        overlay = self.hud_overlay
        if not overlay:
            return

        try:
            now = time.monotonic()
            if (now - self._hud_monitor_refresh_ts) >= 0.35:
                self._hud_monitor_refresh_ts = now
                overlay.refresh_monitor_geometry()

            secondary_limit = max(2, int(getattr(ZoneConfig, "MAX_DISPLAY_ZONES", 6)))
            model = build_hud_target_model(snap, secondary_limit=secondary_limit)

            if model.has_target:
                self._hud_last_target = {
                    "ts": now,
                    "relative": model.relative,
                    "distance": model.distance,
                    "pitch": model.pitch,
                    "roll": model.roll,
                    "fallback": model.fallback,
                    "heading": model.heading,
                    "altitude": model.altitude,
                    "secondary_targets": list(model.secondary_targets),
                }
                overlay.clear_standby()
                overlay.update_target(
                    has_target=True,
                    relative_deg=model.relative,
                    distance_km=model.distance,
                    attitude_pitch_deg=model.pitch,
                    attitude_roll_deg=model.roll,
                    attitude_fallback=model.fallback,
                    heading_deg=model.heading,
                    own_altitude_m=model.altitude,
                    secondary_targets=list(model.secondary_targets),
                )
            else:
                can_hold = False
                if (
                    self._hud_last_target
                    and snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING)
                    and not snap.api_down
                ):
                    age = now - float(self._hud_last_target.get("ts", 0.0))
                    can_hold = age <= self._hud_target_hold_sec

                if can_hold:
                    cached = self._hud_last_target
                    heading = float(
                        getattr(snap, "player_heading", cached.get("heading", 0.0)) or 0.0
                    )
                    altitude = float(
                        getattr(snap, "altitude_m", cached.get("altitude", 0.0)) or 0.0
                    )
                    pitch = float(
                        getattr(snap, "attitude_pitch_deg", cached.get("pitch", 0.0)) or 0.0
                    )
                    roll = float(getattr(snap, "attitude_roll_deg", cached.get("roll", 0.0)) or 0.0)
                    fallback = bool(
                        getattr(snap, "hud_attitude_fallback", cached.get("fallback", True))
                    )
                    cached["heading"] = heading
                    cached["altitude"] = altitude
                    cached["pitch"] = pitch
                    cached["roll"] = roll
                    cached["fallback"] = fallback
                    overlay.clear_standby()
                    overlay.update_target(
                        has_target=True,
                        relative_deg=float(cached["relative"]),
                        distance_km=float(cached["distance"]),
                        attitude_pitch_deg=pitch,
                        attitude_roll_deg=roll,
                        attitude_fallback=fallback,
                        heading_deg=heading,
                        own_altitude_m=altitude,
                        secondary_targets=list(cached.get("secondary_targets", [])),
                    )
                else:
                    overlay.clear_target()
                    overlay.show_standby(model.standby_text)

            if self._hud_render_error_count > 0:
                self._hud_render_error_count = 0
                overlay.update_transparency()
        except Exception as exc:
            self._hud_render_error_count += 1
            if self._hud_render_error_count in (1, 10, 30):
                log_exception(
                    "hud_render_degraded",
                    exc,
                    error_count=self._hud_render_error_count,
                )
            degraded_alpha = max(60, int(HUDConfig.alpha * 0.55))
            try:
                overlay.apply_window_styles(click_through=self.app._locked, alpha=degraded_alpha)
                overlay.show_standby("HUD DEGRADED")
            except Exception:
                pass

    def toggle_hud(self) -> None:
        """Toggle HUD availability while keeping config persistence in App."""
        requested_enabled = not HUDConfig.enabled
        HUDConfig.enabled = not HUDConfig.enabled
        if HUDConfig.enabled:
            if not self.show_hud_overlay():
                HUDConfig.enabled = False
            else:
                self._hud_render_error_count = 0
        else:
            if self.hud_overlay:
                self.hud_overlay.hide()
            self._hud_last_target = None

        self.app._update_hint()
        self.app._save_config()
        self.refresh_tray()
        if HUDConfig.enabled:
            self.app.sound.play(pattern="on")
        log_event(
            "hud_toggle",
            requested_enabled=requested_enabled,
            enabled=HUDConfig.enabled,
            has_overlay=bool(self.hud_overlay),
        )

    def apply_hud_lock_state(self, locked: bool) -> None:
        overlay = self.hud_overlay
        if overlay:
            overlay.set_lock_state(locked)

    def refresh_hud_after_display_change(
        self,
        *,
        ui_scale_changed: bool,
        text_scale_changed: bool,
        locked: bool,
    ) -> None:
        overlay = self.hud_overlay
        if not overlay:
            return
        if (ui_scale_changed or text_scale_changed) and hasattr(overlay, "refresh_text_scale"):
            overlay.refresh_text_scale()
        overlay.set_lock_state(locked)
        overlay.update_transparency()

    def destroy_hud_overlay(self) -> None:
        overlay = self.hud_overlay
        self.hud_overlay = None
        self._hud_last_target = None
        if not overlay:
            return
        with contextlib.suppress(Exception):
            overlay.destroy()

    def stop(self) -> None:
        """Stop all optional runtime services during app shutdown."""
        self.stop_global_hotkeys()
        self.stop_tray()
        self.destroy_hud_overlay()
