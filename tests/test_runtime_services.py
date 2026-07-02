from types import SimpleNamespace
from unittest import mock

from bomana.config.settings import (
    HotkeyConfig,
    HUDConfig,
)
from bomana.ui import runtime_services
from bomana.ui.dialogs import SettingsDialog
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


def _make_hotkey_app() -> SimpleNamespace:
    return SimpleNamespace(
        root=object(),
        _manual_reset_hotkey=lambda: None,
        _toggle_lock=lambda: None,
        _next_corner=lambda: None,
        _toggle_beep=lambda: None,
        _toggle_zone_sound=lambda: None,
        _on_hotkey_registration_error=lambda _key_names: None,
    )


def test_init_global_hotkeys_stops_existing_manager_before_reinit(monkeypatch) -> None:
    calls: list[str] = []

    class ExistingManager:
        def stop(self) -> None:
            calls.append("old-stop")

    class FakeGlobalHotkeys:
        def __init__(self, *_args, **_kwargs) -> None:
            calls.append("create")

        def start(self) -> None:
            calls.append("start")

    services = AppRuntimeServices(_make_hotkey_app())
    services.global_hotkeys = ExistingManager()

    monkeypatch.setattr(runtime_services.os, "name", "nt")
    monkeypatch.setattr(runtime_services, "GlobalHotkeys", FakeGlobalHotkeys)
    monkeypatch.setattr(HotkeyConfig, "GLOBAL_HOTKEYS", True)

    services.init_global_hotkeys()

    assert calls == ["old-stop", "create", "start"]
    assert isinstance(services.global_hotkeys, FakeGlobalHotkeys)


def test_init_global_hotkeys_stops_existing_manager_when_disabled(monkeypatch) -> None:
    calls: list[str] = []

    class ExistingManager:
        def stop(self) -> None:
            calls.append("old-stop")

    services = AppRuntimeServices(_make_hotkey_app())
    services.global_hotkeys = ExistingManager()

    monkeypatch.setattr(runtime_services.os, "name", "nt")
    monkeypatch.setattr(HotkeyConfig, "GLOBAL_HOTKEYS", False)

    services.init_global_hotkeys()

    assert calls == ["old-stop"]
    assert services.global_hotkeys is None


def test_init_global_hotkeys_omits_zones_when_feature_is_disabled(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeGlobalHotkeys:
        def __init__(self, _root, hotkeys, **_kwargs) -> None:
            captured["hotkeys"] = hotkeys

        def start(self) -> None:
            captured["started"] = True

    services = AppRuntimeServices(_make_hotkey_app())

    monkeypatch.setattr(runtime_services.os, "name", "nt")
    monkeypatch.setattr(runtime_services, "ENABLE_ZONES", False)
    monkeypatch.setattr(runtime_services, "GlobalHotkeys", FakeGlobalHotkeys)
    monkeypatch.setattr(HotkeyConfig, "GLOBAL_HOTKEYS", True)

    services.init_global_hotkeys()

    hotkey_ids = [item[0] for item in captured["hotkeys"]]
    assert HotkeyConfig.HK_ID_ZONES not in hotkey_ids
    assert captured["started"] is True


def test_refresh_local_hotkey_bindings_unbinds_old_sequences(monkeypatch) -> None:
    bound: list[str] = []
    unbound: list[str] = []
    app = _make_hotkey_app()
    app.root = SimpleNamespace(
        bind=lambda sequence, _callback: bound.append(sequence),
        unbind=lambda sequence: unbound.append(sequence),
    )
    services = AppRuntimeServices(app)
    services.local_hotkey_sequences = ["<F8>", "<F9>"]
    monkeypatch.setattr(HotkeyConfig, "KEY_LOCK", "F1")
    monkeypatch.setattr(HotkeyConfig, "KEY_CORNER", "F2")
    monkeypatch.setattr(HotkeyConfig, "KEY_BEEP", "F3")
    monkeypatch.setattr(HotkeyConfig, "KEY_ZONES", "F4")
    monkeypatch.setattr(runtime_services, "ENABLE_ZONES", True)

    services.refresh_local_hotkey_bindings()

    assert unbound == ["<F8>", "<F9>"]
    assert bound == ["<F1>", "<F2>", "<F3>", "<F4>"]
    assert services.local_hotkey_sequences == ["<F1>", "<F2>", "<F3>", "<F4>"]


def test_refresh_local_hotkey_bindings_omits_zones_when_disabled(monkeypatch) -> None:
    bound: list[str] = []
    app = _make_hotkey_app()
    app.root = SimpleNamespace(
        bind=lambda sequence, _callback: bound.append(sequence),
        unbind=lambda _sequence: None,
    )
    services = AppRuntimeServices(app)
    monkeypatch.setattr(HotkeyConfig, "KEY_LOCK", "F1")
    monkeypatch.setattr(HotkeyConfig, "KEY_CORNER", "F2")
    monkeypatch.setattr(HotkeyConfig, "KEY_BEEP", "F3")
    monkeypatch.setattr(HotkeyConfig, "KEY_ZONES", "F4")
    monkeypatch.setattr(runtime_services, "ENABLE_ZONES", False)

    services.refresh_local_hotkey_bindings()

    assert bound == ["<F1>", "<F2>", "<F3>"]


def test_refresh_local_hotkey_bindings_skips_invalid_runtime_key(monkeypatch) -> None:
    bound: list[str] = []
    app = _make_hotkey_app()

    def bind(sequence, _callback):
        if sequence == "<BAD KEY>":
            raise runtime_services.tk.TclError("bad event type")
        bound.append(sequence)

    app.root = SimpleNamespace(bind=bind, unbind=lambda _sequence: None)
    services = AppRuntimeServices(app)
    monkeypatch.setattr(HotkeyConfig, "KEY_LOCK", "BAD KEY")
    monkeypatch.setattr(HotkeyConfig, "KEY_CORNER", "F2")
    monkeypatch.setattr(HotkeyConfig, "KEY_BEEP", "F3")
    monkeypatch.setattr(HotkeyConfig, "KEY_ZONES", "F4")
    monkeypatch.setattr(runtime_services, "ENABLE_ZONES", True)

    services.refresh_local_hotkey_bindings()

    assert bound == ["<F2>", "<F3>", "<F4>"]
    assert services.local_hotkey_sequences == ["<F2>", "<F3>", "<F4>"]


def test_settings_hotkey_restart_uses_runtime_services(monkeypatch) -> None:
    calls: list[str] = []

    class RuntimeServices:
        def stop_global_hotkeys(self) -> None:
            calls.append("stop")

        def init_global_hotkeys(self) -> None:
            calls.append("init")

    class LegacyManager:
        def stop(self) -> None:
            raise AssertionError("legacy _ghk should not be stopped directly")

    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.app = SimpleNamespace(
        runtime_services=RuntimeServices(),
        _ghk=LegacyManager(),
        _init_global_hotkeys=lambda: calls.append("legacy-init"),
    )
    monkeypatch.setattr(HotkeyConfig, "GLOBAL_HOTKEYS", True)

    dialog._restart_global_hotkeys_after_save()

    assert calls == ["stop", "init"]
