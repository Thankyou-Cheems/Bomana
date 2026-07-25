"""Bombing-bar presentation ownership across integrated and standalone hosts."""

from __future__ import annotations

import contextlib
from typing import Any

from bomana.config.feature_profile import ENABLE_CCRP
from bomana.config.settings import PanelConfig
from bomana.ui.bombing_bar import BombingWindow
from bomana.utils.diagnostics import log_event


class AppBombingServices:
    """Route one bombing presentation to the main panel, nav host, or own window."""

    def __init__(self, app: Any):
        self.app = app
        self.window: BombingWindow | None = None

    def init_window(self) -> None:
        if not ENABLE_CCRP:
            self.window = None
            return
        self.window = BombingWindow(self.app)

    def toggle_mode(self) -> None:
        target = "standalone" if PanelConfig.bombing_mode == "integrated" else "integrated"
        self.set_mode(target)

    def set_mode(self, mode: str) -> bool:
        if mode not in {"integrated", "standalone"} or not ENABLE_CCRP:
            return False
        if PanelConfig.bombing_mode == mode:
            return False
        previous = PanelConfig.bombing_mode
        PanelConfig.bombing_mode = mode
        if not self.app._save_config(warn_on_failure=True):
            PanelConfig.bombing_mode = previous
            return False
        self._hide_external_hosts()
        integrated = getattr(self.app, "bombing_bar", None)
        if integrated is not None:
            integrated.refresh_mode()
        self.app._update_ui()
        self.app._recalc_size(force_shrink=True)
        self.app._refresh_tray()
        log_event("bombing_mode_toggle", mode=mode)
        return True

    def _hide_external_hosts(self) -> None:
        if self.window is not None:
            self.window.hide()
        nav_window = getattr(self.app, "nav_window", None)
        if nav_window is not None:
            nav_window.set_bombing_visible(False)

    def update(self, snapshot: Any, *, active: bool) -> None:
        """Render the standalone host, or hide it while the integrated host owns output."""
        if (
            not ENABLE_CCRP
            or not active
            or not PanelConfig.is_effectively_enabled("bombing")
            or PanelConfig.bombing_mode != "standalone"
        ):
            self._hide_external_hosts()
            return

        nav_window = getattr(self.app, "nav_window", None)
        mount_below_navigation = bool(
            PanelConfig.navigation_mode == "standalone"
            and nav_window is not None
            and nav_window.is_visible()
        )
        if mount_below_navigation:
            if self.window is not None:
                self.window.hide()
            nav_window.set_bombing_visible(True)
            nav_window.update_bombing_display(snapshot)
            return

        if nav_window is not None:
            nav_window.set_bombing_visible(False)
        if self.window is not None:
            self.window.show()
            self.window.update_display(snapshot)

    def refresh_host(self) -> None:
        """Clear the old external host immediately after a navigation mode transition."""
        self._hide_external_hosts()

    def apply_lock_state(self, *, locked: bool, alpha: int) -> None:
        if self.window is not None:
            self.window.apply_window_styles(click_through=locked, alpha=alpha)

    def rebuild_after_display_change(self) -> None:
        if not ENABLE_CCRP:
            return
        was_visible = bool(self.window is not None and self.window.is_visible())
        position = PanelConfig.bombing_window_pos
        if self.window is not None:
            with contextlib.suppress(Exception):
                self.window.destroy()
        PanelConfig.bombing_window_pos = position
        self.window = BombingWindow(self.app)
        if was_visible and PanelConfig.bombing_mode == "standalone":
            self.window.show()

    def stop(self) -> None:
        window = self.window
        self.window = None
        if window is not None:
            with contextlib.suppress(Exception):
                window.destroy()


__all__ = ["AppBombingServices"]
