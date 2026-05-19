import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bomana.config import PanelConfig
from bomana.ui.navigation_runtime import AppNavigationServices


class FakeGeometryWindow:
    def __init__(self) -> None:
        self.geometry_calls = []
        self.update_idletasks_calls = 0

    def winfo_x(self) -> int:
        return 11

    def winfo_y(self) -> int:
        return 22

    def winfo_width(self) -> int:
        return 333

    def winfo_height(self) -> int:
        return 44

    def update_idletasks(self) -> None:
        self.update_idletasks_calls += 1

    def geometry(self, value: str) -> None:
        self.geometry_calls.append(value)


class FakeNavigationWindow:
    def __init__(self, app) -> None:
        self.app = app
        self.window = FakeGeometryWindow()
        self.visible = False
        self.clear_calls = 0
        self.destroy_calls = 0
        self.style_calls = []

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def is_visible(self) -> bool:
        return self.visible

    def clear_display(self) -> None:
        self.clear_calls += 1

    def destroy(self) -> None:
        self.destroy_calls += 1

    def apply_window_styles(self, *, click_through: bool, alpha: int) -> None:
        self.style_calls.append((click_through, alpha))


class FakeApp:
    def __init__(self) -> None:
        self.reset_calls = 0
        self.nav_button_calls = 0
        self.save_calls = 0
        self.update_calls = 0
        self.recalc_calls = []
        self.tray_calls = 0
        self.panel_renderer = SimpleNamespace(
            reset_navigation_layout_state=lambda: self._record_reset()
        )

    def _record_reset(self) -> None:
        self.reset_calls += 1

    def _update_nav_mode_button(self) -> None:
        self.nav_button_calls += 1

    def _save_config(self) -> None:
        self.save_calls += 1

    def _update_ui(self) -> None:
        self.update_calls += 1

    def _recalc_size(self, *, force_shrink: bool) -> None:
        self.recalc_calls.append(force_shrink)

    def _refresh_tray(self) -> None:
        self.tray_calls += 1


class NavigationRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_mode = PanelConfig.navigation_mode

    def tearDown(self) -> None:
        PanelConfig.navigation_mode = self._old_mode

    @patch("bomana.ui.navigation_runtime.log_event")
    def test_toggle_mode_moves_window_to_standalone(self, log_event) -> None:
        app = FakeApp()
        services = AppNavigationServices(app)
        services.window = FakeNavigationWindow(app)
        PanelConfig.navigation_mode = "integrated"

        services.toggle_mode()

        self.assertEqual(PanelConfig.navigation_mode, "standalone")
        self.assertTrue(services.window.visible)
        self.assertEqual(services.window.clear_calls, 1)
        self.assertEqual(app.reset_calls, 1)
        self.assertEqual(app.recalc_calls, [True])
        log_event.assert_called_once_with("navigation_mode_toggle", mode="standalone")

    def test_history_mode_suspends_and_restores_visible_window(self) -> None:
        app = FakeApp()
        services = AppNavigationServices(app)
        services.window = FakeNavigationWindow(app)
        services.window.show()
        PanelConfig.navigation_mode = "standalone"

        services.suspend_for_history_mode(state_changed=True)
        self.assertFalse(services.window.visible)

        services.restore_after_history_mode(state_changed=True)
        self.assertTrue(services.window.visible)

    @patch("bomana.ui.navigation_runtime.NavigationWindow", FakeNavigationWindow)
    def test_rebuild_preserves_position_but_reflows_size_for_text_only_change(self) -> None:
        app = FakeApp()
        services = AppNavigationServices(app)
        services.window = FakeNavigationWindow(app)
        services.window.show()
        old_window = services.window
        PanelConfig.navigation_mode = "standalone"

        services.rebuild_after_display_change(preserve_text_only_geometry=True)

        self.assertEqual(old_window.destroy_calls, 1)
        self.assertIsNot(services.window, old_window)
        self.assertTrue(services.window.visible)
        self.assertEqual(services.window.window.update_idletasks_calls, 1)
        self.assertEqual(services.window.window.geometry_calls, ["+11+22"])

    def test_apply_lock_state_updates_owned_window(self) -> None:
        app = FakeApp()
        services = AppNavigationServices(app)
        services.window = FakeNavigationWindow(app)

        services.apply_lock_state(locked=True, alpha=210)

        self.assertEqual(services.window.style_calls, [(True, 210)])


if __name__ == "__main__":
    unittest.main()
