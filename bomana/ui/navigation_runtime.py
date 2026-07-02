"""Standalone navigation window runtime ownership."""

from __future__ import annotations

import contextlib
from typing import Any

from bomana.config.feature_profile import ENABLE_ZONES
from bomana.config.settings import PanelConfig
from bomana.ui.nav_window import NavigationWindow
from bomana.utils.diagnostics import log_event


class AppNavigationServices:
    """Own standalone navigation window lifecycle outside the main App body."""

    def __init__(self, app: Any):
        self.app = app
        self.window: NavigationWindow | None = None
        self._history_mode_window_was_visible = False

    def init_window(self) -> None:
        """Create the standalone navigation surface when the feature is compiled in."""
        if not ENABLE_ZONES:
            self.window = None
            return
        self.window = NavigationWindow(self.app)
        if PanelConfig.navigation_mode == "standalone":
            self.window.show()

    def toggle_mode(self) -> None:
        """Switch between integrated and standalone navigation presentation."""
        window = self.window
        if not ENABLE_ZONES or window is None:
            return

        self.app.panel_renderer.reset_navigation_layout_state()
        if PanelConfig.navigation_mode == "integrated":
            PanelConfig.navigation_mode = "standalone"
            window.clear_display()
            window.show()
        else:
            PanelConfig.navigation_mode = "integrated"
            window.hide()

        self.app._update_nav_mode_button()
        self.app._save_config()
        self.app._update_ui()
        self.app._recalc_size(force_shrink=True)
        self.app._refresh_tray()
        log_event("navigation_mode_toggle", mode=PanelConfig.navigation_mode)

    def apply_lock_state(self, *, locked: bool, alpha: int) -> None:
        """Mirror the main-window click-through state onto the standalone nav window."""
        if self.window:
            self.window.apply_window_styles(click_through=locked, alpha=alpha)

    def suspend_for_history_mode(self, *, state_changed: bool) -> None:
        """Hide standalone navigation while the dedicated history layout is active."""
        window = self.window
        if window is None:
            return
        if window.is_visible():
            self._history_mode_window_was_visible = True
            window.hide()
        elif state_changed:
            self._history_mode_window_was_visible = False

    def restore_after_history_mode(self, *, state_changed: bool) -> None:
        """Restore the standalone nav window after leaving the history layout."""
        if not state_changed:
            return
        window = self.window
        if (
            window
            and self._history_mode_window_was_visible
            and ENABLE_ZONES
            and PanelConfig.navigation_mode == "standalone"
        ):
            window.show()
        self._history_mode_window_was_visible = False

    def rebuild_after_display_change(self, *, preserve_text_only_geometry: bool) -> None:
        """Recreate the standalone nav surface after theme/scale/nav-width updates."""
        if not ENABLE_ZONES:
            return

        window = self.window
        nav_was_visible = False
        nav_position: tuple[int, int] | None = None
        if window:
            try:
                nav_was_visible = bool(window.is_visible())
            except Exception:
                nav_was_visible = False
            if preserve_text_only_geometry and nav_was_visible:
                try:
                    nav_position = (
                        window.window.winfo_x(),
                        window.window.winfo_y(),
                    )
                except Exception:
                    nav_position = None
            with contextlib.suppress(Exception):
                window.destroy()

        self.window = NavigationWindow(self.app)
        if PanelConfig.navigation_mode == "standalone" and nav_was_visible:
            self.window.show()
            if preserve_text_only_geometry and nav_position:
                nav_x, nav_y = nav_position
                with contextlib.suppress(Exception):
                    self.window.window.update_idletasks()
                self.window.window.geometry(f"+{nav_x}+{nav_y}")

    def stop(self) -> None:
        """Destroy the owned nav surface during application shutdown."""
        window = self.window
        self.window = None
        if window is None:
            return
        with contextlib.suppress(Exception):
            window.destroy()
