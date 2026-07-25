from types import SimpleNamespace

import pytest

from bomana.config.settings import PanelConfig
from bomana.ui.bombing_runtime import AppBombingServices


class FakeBombingWindow:
    def __init__(self) -> None:
        self.visible = False
        self.updates: list[object] = []

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def is_visible(self) -> bool:
        return self.visible

    def update_display(self, snapshot: object) -> None:
        self.updates.append(snapshot)


class FakeNavigationWindow:
    def __init__(self, *, visible: bool) -> None:
        self.visible = visible
        self.bombing_visible = False
        self.updates: list[object] = []

    def is_visible(self) -> bool:
        return self.visible

    def set_bombing_visible(self, visible: bool) -> None:
        self.bombing_visible = visible

    def update_bombing_display(self, snapshot: object) -> None:
        self.updates.append(snapshot)


@pytest.fixture(autouse=True)
def _restore_panel_config():
    previous = (
        PanelConfig.bombing_mode,
        PanelConfig.navigation_mode,
        PanelConfig.show_bombing,
        PanelConfig.speed_history_mode,
    )
    PanelConfig.bombing_mode = "integrated"
    PanelConfig.navigation_mode = "integrated"
    PanelConfig.show_bombing = True
    PanelConfig.speed_history_mode = False
    yield
    (
        PanelConfig.bombing_mode,
        PanelConfig.navigation_mode,
        PanelConfig.show_bombing,
        PanelConfig.speed_history_mode,
    ) = previous


def _service(*, nav_visible: bool = True):
    nav = FakeNavigationWindow(visible=nav_visible)
    app = SimpleNamespace(nav_window=nav)
    service = AppBombingServices(app)
    service.window = FakeBombingWindow()
    return service, nav


def test_standalone_bombing_mounts_below_visible_standalone_navigation() -> None:
    service, nav = _service()
    snapshot = object()
    PanelConfig.bombing_mode = "standalone"
    PanelConfig.navigation_mode = "standalone"

    service.update(snapshot, active=True)

    assert nav.bombing_visible is True
    assert nav.updates == [snapshot]
    assert service.window.visible is False


def test_standalone_bombing_uses_own_window_when_navigation_is_integrated() -> None:
    service, nav = _service()
    snapshot = object()
    PanelConfig.bombing_mode = "standalone"
    PanelConfig.navigation_mode = "integrated"

    service.update(snapshot, active=True)

    assert nav.bombing_visible is False
    assert service.window.visible is True
    assert service.window.updates == [snapshot]


def test_integrated_or_inactive_state_hides_all_external_hosts() -> None:
    service, nav = _service()
    service.window.visible = True
    nav.bombing_visible = True

    service.update(object(), active=False)

    assert service.window.visible is False
    assert nav.bombing_visible is False
