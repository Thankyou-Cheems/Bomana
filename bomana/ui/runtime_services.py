"""Runtime-facing UI services split out of the main App coordinator."""

from __future__ import annotations

import contextlib
import os
import threading
import tkinter as tk
from typing import Any

from bomana.config.feature_profile import (
    ENABLE_ADVANCED_SETTINGS,
    ENABLE_AIRFIELDS,
    ENABLE_CCRP,
    ENABLE_CHECKLIST,
    ENABLE_FUEL,
    ENABLE_WEB_DASHBOARD,
    ENABLE_ZONES,
)
from bomana.config.settings import (
    BombConfig,
    FileConfig,
    GameConfig,
    HotkeyConfig,
    PanelConfig,
)
from bomana.core.state import UISnapshot
from bomana.metadata import __title__
from bomana.ui.runtime import MapIconFontPoller, MapImagePoller, start_daemon_thread
from bomana.ui.theme import Theme
from bomana.ui.tk_style import style_action_button
from bomana.utils.diagnostics import log_event, log_exception
from bomana.utils.file_utils import resource_path
from bomana.utils.hotkey_broker import (
    BrokerBinding,
    BrokerStartStatus,
    ElevatedHotkeyBrokerClient,
)
from bomana.utils.system import GlobalHotkeys

if ENABLE_WEB_DASHBOARD:
    from bomana.web.control import (
        ControlStateProjection,
        DashboardControlStore,
        WebCommandEnvelope,
    )
    from bomana.web.server import DashboardServerError, WebDashboardRuntime
    from bomana.web.snapshot import DashboardSnapshotStore
else:
    # Standard/Lite packages omit bomana/web; keep inert stubs for shared call sites.

    class DashboardServerError(RuntimeError):
        """Raised when a Web cockpit start is requested without the feature."""

    class _NullDashboardStore:
        def publish(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def publish_map_image(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def publish_map_icon_font(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def read_map_icon_font(self) -> None:
            return None

    class DashboardSnapshotStore(_NullDashboardStore):
        pass

    class DashboardControlStore(_NullDashboardStore):
        pass

    class ControlStateProjection:
        pass

    class WebCommandEnvelope:
        pass

    class WebDashboardRuntime:
        pass


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
        self._web_command_dispatcher = getattr(app, "dispatcher", None)
        self._web_command_callback = getattr(app, "_execute_web_command", None)
        self._web_command_queue_open = threading.Event()
        self._web_command_queue_open.set()
        self.global_hotkeys: GlobalHotkeys | None = None
        self.hotkey_broker: ElevatedHotkeyBrokerClient | None = None
        self.tray: Any | None = None
        self.local_hotkey_sequences: list[str] = []
        self.dashboard_store = DashboardSnapshotStore()
        game = getattr(app, "game", None)
        self.map_image_poller = MapImagePoller(
            self.dashboard_store,
            on_image=getattr(game, "update_terrain_map_image", None),
        )
        self.map_icon_font_poller = MapIconFontPoller(self.dashboard_store)
        self.dashboard_control_store = DashboardControlStore()
        self.dashboard: WebDashboardRuntime | None = None
        self.dashboard_error = ""

    @staticmethod
    def _launcher_web_preference(name: str, *, default: bool) -> bool:
        value = os.environ.get(name)
        if value == "1":
            return True
        if value == "0":
            return False
        return default

    def dashboard_autostart_enabled(self) -> bool:
        if not ENABLE_WEB_DASHBOARD:
            return False
        return self._launcher_web_preference(
            "BOMANA_WEB_DASHBOARD_AUTOSTART",
            default=True,
        )

    def dashboard_auto_open_enabled(self) -> bool:
        if not ENABLE_WEB_DASHBOARD:
            return False
        return self._launcher_web_preference(
            "BOMANA_WEB_DASHBOARD_AUTO_OPEN",
            default=False,
        )

    def web_dashboard_lan_enabled(self) -> bool:
        if not ENABLE_WEB_DASHBOARD:
            return False
        return self._launcher_web_preference(
            "BOMANA_WEB_DASHBOARD_LAN_ENABLED",
            default=False,
        )

    def dashboard_lan_autostart_enabled(self) -> bool:
        return self.web_dashboard_lan_enabled()

    def _queue_web_command(self, envelope: WebCommandEnvelope) -> bool:
        dispatcher = self._web_command_dispatcher
        callback = self._web_command_callback
        if not self._web_command_queue_open.is_set() or dispatcher is None or callback is None:
            return False
        try:
            dispatcher.post(callback, envelope)
        except Exception as exc:
            log_exception("web_dashboard_command_queue_failed", exc)
            return False
        return True

    def init_dashboard(self) -> bool:
        """Start the extension-free loopback Web Cockpit."""
        if not ENABLE_WEB_DASHBOARD:
            self.dashboard = None
            self.dashboard_error = "当前通道未包含网页驾驶舱（仅超级爆弹版提供）。"
            return False
        if self.dashboard is not None and self.dashboard.is_running:
            return True
        dashboard: WebDashboardRuntime | None = None
        try:
            dashboard = WebDashboardRuntime(
                self.dashboard_store,
                control_store=self.dashboard_control_store,
                command_sink=self._queue_web_command,
            )
            dashboard.start()
            self.map_image_poller.start()
            self.map_icon_font_poller.start()
        except Exception as exc:
            if not self._terrain_map_tracking_required():
                with contextlib.suppress(Exception):
                    self.map_image_poller.stop()
            with contextlib.suppress(Exception):
                self.map_icon_font_poller.stop()
            if dashboard is not None:
                with contextlib.suppress(Exception):
                    dashboard.stop()
            self.dashboard = None
            self.dashboard_error = str(exc)
            log_exception("web_dashboard_start_failed", exc)
            return False
        self.dashboard = dashboard
        self.dashboard_error = ""
        log_event("web_dashboard_started", port=dashboard.port, scope="loopback")
        return True

    def start_terrain_map_tracking(self) -> bool:
        """Start active-map identification when a local terrain pack exists."""
        if not self._terrain_map_tracking_required():
            return False
        self.map_image_poller.start()
        return True

    def _terrain_map_tracking_required(self) -> bool:
        game = getattr(self.app, "game", None)
        return bool(game is not None and getattr(game, "terrain_pack_available", False))

    def publish_dashboard(self, snapshot: UISnapshot, checklist_items: list[str]) -> None:
        """Publish immutable presentation state; HTTP threads never read Tk/App."""
        self.dashboard_store.publish(snapshot, checklist_items)

    def publish_dashboard_control(self, projection: ControlStateProjection) -> None:
        """Publish immutable Tk-owned semantic state for paired Web sessions."""
        self.dashboard_control_store.publish(projection)

    def reauthorize_web_command(self, envelope: WebCommandEnvelope) -> bool:
        """Recheck the session authorization_epoch and current-run control scope."""
        dashboard = self.dashboard
        return bool(
            dashboard is not None
            and dashboard.is_running
            and dashboard.reauthorize_command(envelope)
        )

    def complete_web_command(
        self,
        envelope: WebCommandEnvelope,
        *,
        status: str,
        reason: str,
        resulting_revision: int,
    ) -> bool:
        """Publish one session-owned recent_commands result after its resulting_revision."""
        dashboard = self.dashboard
        if dashboard is None or not dashboard.is_running:
            return False
        return dashboard.publish_command_completion(
            envelope,
            status=status,
            reason=reason,
            resulting_revision=resulting_revision,
        )

    def enable_dashboard_lan(self) -> str:
        dashboard = self.dashboard
        if dashboard is None or not dashboard.is_running:
            if not self.init_dashboard():
                raise DashboardServerError(self.dashboard_error or "网页驾驶舱启动失败")
            dashboard = self.dashboard
        if dashboard is None:
            raise DashboardServerError("网页驾驶舱启动失败")
        address = dashboard.enable_lan()
        log_event("web_dashboard_lan_enabled", port=dashboard.port)
        return address

    def disable_dashboard_lan(self) -> None:
        dashboard = self.dashboard
        if dashboard is None or not dashboard.lan_enabled:
            return
        dashboard.disable_lan()
        log_event("web_dashboard_lan_disabled")

    def _dashboard_lan_share_available(self, _item: Any | None = None) -> bool:
        dashboard = self.dashboard
        return bool(dashboard is not None and dashboard.is_running and dashboard.lan_enabled)

    def stop_dashboard(self) -> None:
        dashboard = self.dashboard
        self.dashboard = None
        if not self._terrain_map_tracking_required():
            self.map_image_poller.stop()
        self.map_icon_font_poller.stop()
        if dashboard is None:
            return
        with contextlib.suppress(Exception):
            dashboard.stop()

    def init_global_hotkeys(self) -> None:
        """Initialize runtime-configurable Windows global hotkeys."""
        if not self.stop_global_hotkeys():
            return
        if os.name != "nt" or not HotkeyConfig.GLOBAL_HOTKEYS:
            self._set_hotkey_broker_notice("", "")
            return

        hotkeys = self._configured_hotkeys()
        self._start_local_hotkeys(hotkeys)
        # Deliberately do not enumerate or open the game process. RegisterHotKey
        # is system-owned and the production runtime remains on the 8111 boundary.
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
        if ENABLE_CCRP:
            hotkeys.insert(
                0,
                (
                    "bomb_target",
                    HotkeyConfig.HK_ID_BOMB_TARGET,
                    HotkeyConfig.KEY_BOMB_TARGET,
                    self.app._toggle_bomb_target_mode,
                ),
            )
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
                f"{message} 游戏以前台高权限运行时，F6-F11 可能失效；"
                "窗口按钮、托盘与 8111 功能不受影响。"
            ),
            "elevate",
        )

    def _set_hotkey_broker_notice(self, message: str, action: str) -> None:
        callback = getattr(self.app, "_set_hotkey_broker_notice", None)
        if callable(callback):
            callback(message, action)
        button = getattr(self.app, "star_lbl", None)
        if button is not None:
            with contextlib.suppress(tk.TclError, AttributeError):
                style_action_button(button, "warning" if action == "elevate" else "secondary")
        self.refresh_tray()

    def _tray_hotkey_action_visible(self, _item=None) -> bool:
        """Expose the tray escape hatch exactly while a broker action is available."""
        return getattr(self.app, "_hotkey_broker_action", "") == "elevate"

    def _request_hotkey_broker_from_tray(self, _icon=None, _item=None) -> None:
        """Cross from the tray worker to the existing Tk-owned consent action."""
        if not self._tray_hotkey_action_visible():
            return
        callback = getattr(self.app, "_on_nudge_action", None)
        if callable(callback):
            self.app.dispatcher.post(callback)

    def _build_hotkey_broker_tray_item(self):
        return pystray.MenuItem(
            "启用游戏内热键…",
            self._request_hotkey_broker_from_tray,
            visible=self._tray_hotkey_action_visible,
        )

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
        if ENABLE_CCRP:
            bindings.insert(0, (HotkeyConfig.KEY_BOMB_TARGET, self.app._toggle_bomb_target_mode))
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

        def do_timer_target(minutes: int):
            def apply_target(icon, item):
                app.dispatcher.post(app._set_timer_cycle_minutes, minutes)

            return apply_target

        def do_custom_timer(icon, item):
            app.dispatcher.post(app._prompt_timer_cycle_minutes)

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

        def do_open_dashboard(icon, item):
            app.dispatcher.post(app._open_web_dashboard)

        def do_toggle_dashboard_lan(icon, item):
            app.dispatcher.post(app._toggle_web_dashboard_lan)

        def do_copy_dashboard_link(icon, item):
            app.dispatcher.post(app._copy_web_dashboard_link)

        def do_copy_dashboard_code(icon, item):
            app.dispatcher.post(app._copy_web_dashboard_pairing_code)

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

        timer_menu_items = [
            pystray.MenuItem(
                f"{minutes} 分钟",
                do_timer_target(minutes),
                checked=lambda _item, target=minutes: GameConfig.cycle_minutes() == target,
            )
            for minutes in (15, 30, 45, 60)
        ]
        timer_menu_items.extend(
            (pystray.Menu.SEPARATOR, pystray.MenuItem("自定义…", do_custom_timer))
        )
        timer_menu = pystray.Menu(*timer_menu_items)

        menu_items = [
            pystray.MenuItem("立即重置计时器", do_reset),
            pystray.MenuItem(
                lambda _item: f"计时周期 · {GameConfig.cycle_minutes()} 分钟",
                timer_menu,
            ),
            pystray.MenuItem(f"锁定/解锁 ({HotkeyConfig.KEY_LOCK})", do_lock, checked=is_locked),
            self._build_hotkey_broker_tray_item(),
            pystray.MenuItem(f"切换角落 ({HotkeyConfig.KEY_CORNER})", do_corner),
            pystray.MenuItem("空历速度模式", do_speed_history, checked=is_speed_history_mode),
            pystray.Menu.SEPARATOR,
        ]

        if ENABLE_WEB_DASHBOARD:

            def dashboard_pairing_text(_item):
                active = self.dashboard
                code = (
                    active.pairing_code if active is not None and active.is_running else "---- ----"
                )
                return f"复制配对码：{code}"

            def dashboard_title(_item):
                active = self.dashboard
                return (
                    "网页驾驶舱"
                    if active is not None and active.is_running
                    else "网页驾驶舱（按需启动）"
                )

            def dashboard_is_ready(_item):
                active = self.dashboard
                return bool(active is not None and active.is_running)

            dashboard_menu = pystray.Menu(
                pystray.MenuItem("打开本机页面", do_open_dashboard),
                pystray.MenuItem(
                    "开启局域网访问与控制（本次运行）",
                    do_toggle_dashboard_lan,
                    checked=lambda _item: bool(
                        self.dashboard is not None and self.dashboard.lan_enabled
                    ),
                    enabled=dashboard_is_ready,
                ),
                pystray.MenuItem(
                    "复制手机访问链接",
                    do_copy_dashboard_link,
                    enabled=self._dashboard_lan_share_available,
                ),
                pystray.MenuItem(
                    dashboard_pairing_text,
                    do_copy_dashboard_code,
                    enabled=dashboard_is_ready,
                ),
            )
            menu_items.append(
                pystray.MenuItem(
                    dashboard_title,
                    dashboard_menu,
                )
            )
            menu_items.append(pystray.Menu.SEPARATOR)

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
                    pystray.MenuItem("CCRP", toggle_bombing, checked=is_bombing_panel)
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

            if ENABLE_CCRP:

                def toggle_bombing_mode(icon, item):
                    app.dispatcher.post(app._toggle_bombing_mode)

                def is_standalone_bombing(item):
                    return PanelConfig.bombing_mode == "standalone"

                def toggle_bomb_target(icon, item):
                    app.dispatcher.post(app._toggle_bomb_target_mode)

                def bomb_target_label(item):
                    label = "战区" if BombConfig.target_mode == "zone" else "兴趣点"
                    return f"CCRP 目标：{label} ({HotkeyConfig.KEY_BOMB_TARGET})"

                menu_items.append(
                    pystray.MenuItem(
                        "独立 CCRP",
                        toggle_bombing_mode,
                        checked=is_standalone_bombing,
                    )
                )
                menu_items.append(pystray.MenuItem(bomb_target_label, toggle_bomb_target))

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

    def stop(self) -> None:
        """Stop all optional runtime services during app shutdown."""
        self._web_command_queue_open.clear()
        self.stop_dashboard()
        self.map_image_poller.stop()
        self.stop_global_hotkeys()
        self.stop_tray()
