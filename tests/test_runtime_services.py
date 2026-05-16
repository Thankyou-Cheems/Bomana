from types import SimpleNamespace
from unittest import mock

from bomana.config import HUDConfig
from bomana.ui import runtime_services
from bomana.ui.runtime_services import AppRuntimeServices


class FakeSound:
    def __init__(self) -> None:
        self.patterns: list[str] = []

    def play(self, *, pattern: str) -> None:
        self.patterns.append(pattern)


def test_hud_overlay_init_failure_disables_without_leaking_exception() -> None:
    calls: list[str] = []
    app = SimpleNamespace(
        _locked=True,
        sound=FakeSound(),
        _update_hint=lambda: calls.append("hint"),
        _save_config=lambda: calls.append("save"),
    )
    services = AppRuntimeServices(app)
    original_enabled = HUDConfig.enabled
    HUDConfig.enabled = False

    class FailingHUDOverlay:
        def __init__(self, _app) -> None:
            raise RuntimeError("transparent overlay unavailable")

    try:
        with (
            mock.patch.object(runtime_services, "HUDOverlay", FailingHUDOverlay),
            mock.patch.object(runtime_services, "log_exception") as log_exception,
            mock.patch.object(AppRuntimeServices, "refresh_tray") as refresh_tray,
        ):
            assert services.ensure_hud_overlay() is False
            assert services.hud_overlay is None
            assert services.show_hud_overlay() is False

            services.toggle_hud()

            assert HUDConfig.enabled is False
            assert services.hud_overlay is None
            assert calls == ["hint", "save"]
            refresh_tray.assert_called_once()
            assert log_exception.call_count >= 2
    finally:
        HUDConfig.enabled = original_enabled
