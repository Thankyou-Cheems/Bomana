from types import SimpleNamespace
from unittest import mock

import pytest

from bomana.config.settings import (
    HotkeyConfig,
    HUDConfig,
)
from bomana.ui import runtime_services
from bomana.ui.dialogs import SettingsDialog
from bomana.ui.runtime_services import AppRuntimeServices
from bomana.utils.hotkey_broker import (
    BrokerStartResult,
    BrokerStartStatus,
    GameIntegrityResult,
    GameIntegrityStatus,
)


@pytest.fixture(autouse=True)
def _default_to_unavailable_broker(monkeypatch):
    class UnavailableBroker:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def start(self) -> BrokerStartResult:
            return BrokerStartResult(BrokerStartStatus.UNAVAILABLE)

        def stop(self) -> None:
            pass

    monkeypatch.setattr(runtime_services, "ElevatedHotkeyBrokerClient", UnavailableBroker)
    monkeypatch.setattr(
        runtime_services,
        "detect_war_thunder_integrity",
        lambda: GameIntegrityResult(GameIntegrityStatus.NOT_RUNNING),
    )


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
        dispatcher=SimpleNamespace(post=lambda _callback, *_args: None),
        _hotkey_broker_action="",
        _manual_reset_hotkey=lambda: None,
        _toggle_lock=lambda: None,
        _next_corner=lambda: None,
        _toggle_beep=lambda: None,
        _toggle_zone_sound=lambda: None,
        _on_hotkey_registration_error=lambda _key_names: None,
        _on_nudge_action=lambda: None,
        _set_hotkey_broker_notice=lambda _message, _action: None,
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


def test_init_global_hotkeys_keeps_manager_when_stop_fails(monkeypatch) -> None:
    class ExistingManager:
        def stop(self) -> None:
            raise RuntimeError("native window owned by another thread")

    services = AppRuntimeServices(_make_hotkey_app())
    existing = ExistingManager()
    services.global_hotkeys = existing
    logged: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(runtime_services.os, "name", "nt")
    monkeypatch.setattr(HotkeyConfig, "GLOBAL_HOTKEYS", True)
    monkeypatch.setattr(
        runtime_services,
        "log_exception",
        lambda *args, **kwargs: logged.append((args, kwargs)),
    )

    services.init_global_hotkeys()

    assert services.global_hotkeys is existing
    assert len(logged) == 1
    assert logged[0][0][0] == "global_hotkeys_stop_failed"


def test_init_global_hotkeys_omits_zones_when_feature_is_disabled(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeGlobalHotkeys:
        def __init__(self, dispatch, hotkeys, **_kwargs) -> None:
            captured["dispatch"] = dispatch
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
    assert captured["dispatch"] == services.app.dispatcher.post
    assert captured["started"] is True


def test_init_global_hotkeys_uses_local_backend_without_automatic_uac(monkeypatch) -> None:
    calls: list[str] = []
    notices: list[tuple[str, str]] = []

    class LocalHotkeys:
        def __init__(self, _dispatch, hotkeys, **_kwargs) -> None:
            calls.append(f"local-create:{len(hotkeys)}")

        def start(self) -> None:
            calls.append("local-start")

        def stop(self) -> None:
            calls.append("local-stop")

    class UnexpectedBroker:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("startup must not create or elevate the broker")

    app = _make_hotkey_app()
    app._set_hotkey_broker_notice = lambda message, action: notices.append((message, action))
    services = AppRuntimeServices(app)
    monkeypatch.setattr(runtime_services.os, "name", "nt")
    monkeypatch.setattr(runtime_services, "ElevatedHotkeyBrokerClient", UnexpectedBroker)
    monkeypatch.setattr(runtime_services, "GlobalHotkeys", LocalHotkeys)
    monkeypatch.setattr(
        runtime_services,
        "detect_war_thunder_integrity",
        lambda: GameIntegrityResult(GameIntegrityStatus.ORDINARY, 42, "aces.exe"),
    )
    monkeypatch.setattr(HotkeyConfig, "GLOBAL_HOTKEYS", True)

    services.init_global_hotkeys()

    assert calls == ["local-create:5", "local-start"]
    assert services.hotkey_broker is None
    assert services.global_hotkeys is not None
    assert notices[-1][1] == ""
    assert notices[-1][0] == ""


def test_elevated_game_keeps_local_hotkeys_and_offers_manual_uac(monkeypatch) -> None:
    calls: list[str] = []
    notices: list[tuple[str, str]] = []

    class LocalHotkeys:
        def __init__(self, _dispatch, _hotkeys, **_kwargs) -> None:
            calls.append("local-create")

        def start(self) -> None:
            calls.append("local-start")

        def stop(self) -> None:
            calls.append("local-stop")

    app = _make_hotkey_app()
    app._set_hotkey_broker_notice = lambda message, action: notices.append((message, action))
    services = AppRuntimeServices(app)
    monkeypatch.setattr(runtime_services.os, "name", "nt")
    monkeypatch.setattr(runtime_services, "GlobalHotkeys", LocalHotkeys)
    monkeypatch.setattr(
        runtime_services,
        "detect_war_thunder_integrity",
        lambda: GameIntegrityResult(GameIntegrityStatus.ELEVATED, 42, "aces.exe"),
    )
    monkeypatch.setattr(HotkeyConfig, "GLOBAL_HOTKEYS", True)

    services.init_global_hotkeys()

    assert calls == ["local-create", "local-start"]
    assert notices[-1][1] == "elevate"
    assert notices[-1][0] == ("检测到 War Thunder 以管理员权限运行；普通热键可能在游戏前台失效。")


def test_tray_hotkey_action_is_dynamic_and_dispatches_to_tk() -> None:
    consent_calls: list[str] = []
    dispatched: list[tuple[object, tuple[object, ...]]] = []
    app = _make_hotkey_app()
    app._on_nudge_action = lambda: consent_calls.append("consent")
    app.dispatcher = SimpleNamespace(
        post=lambda callback, *args: dispatched.append((callback, args))
    )
    services = AppRuntimeServices(app)
    item = services._build_hotkey_broker_tray_item()

    assert item.text == "启用游戏内热键…"
    assert item.visible is False

    app._hotkey_broker_action = "elevate"
    assert item.visible is True
    item(None)

    assert consent_calls == []
    assert dispatched == [(app._on_nudge_action, ())]
    dispatched[0][0](*dispatched[0][1])
    assert consent_calls == ["consent"]


def test_cancelled_explicit_uac_restores_local_hotkeys(monkeypatch) -> None:
    calls: list[str] = []
    notices: list[tuple[str, str]] = []

    class CancelledBroker:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def start(self) -> BrokerStartResult:
            calls.append("broker-start")
            return BrokerStartResult(BrokerStartStatus.CANCELLED)

        def stop(self) -> None:
            calls.append("broker-stop")

    class LocalHotkeys:
        def __init__(self, _dispatch, hotkeys, **_kwargs) -> None:
            calls.append(f"local-create:{len(hotkeys)}")

        def start(self) -> None:
            calls.append("local-start")

        def stop(self) -> None:
            calls.append("local-stop")

    app = _make_hotkey_app()
    app._set_hotkey_broker_notice = lambda message, action: notices.append((message, action))
    services = AppRuntimeServices(app)
    monkeypatch.setattr(runtime_services.os, "name", "nt")
    monkeypatch.setattr(runtime_services, "ElevatedHotkeyBrokerClient", CancelledBroker)
    monkeypatch.setattr(runtime_services, "GlobalHotkeys", LocalHotkeys)
    monkeypatch.setattr(HotkeyConfig, "GLOBAL_HOTKEYS", True)

    services._start_local_hotkeys(services._configured_hotkeys())
    services.enable_elevated_hotkeys()

    assert calls == [
        "local-create:5",
        "local-start",
        "local-stop",
        "broker-start",
        "broker-stop",
        "local-create:5",
        "local-start",
    ]
    assert services.hotkey_broker is None
    assert services.global_hotkeys is not None
    assert notices[-1][1] == "elevate"
    assert "普通热键已恢复" in notices[-1][0]


def test_broker_registration_failure_keeps_persistent_retry_notice() -> None:
    notices: list[tuple[str, str]] = []
    errors: list[tuple[str, ...]] = []
    app = _make_hotkey_app()
    app._set_hotkey_broker_notice = lambda message, action: notices.append((message, action))
    app._on_hotkey_registration_error = errors.append
    services = AppRuntimeServices(app)

    services._on_hotkey_broker_ready(("F8", "F11"))

    assert errors == [("F8", "F11")]
    assert notices[-1][1] == "elevate"
    assert "F8、F11" in notices[-1][0]


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
