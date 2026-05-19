from types import SimpleNamespace

from bomana.ui import app as app_module
from bomana.ui.app import App, Corner


def _make_config_only_app() -> App:
    instance = App.__new__(App)
    instance.root = object()
    instance.chk_items = []
    instance.sound = SimpleNamespace(is_enabled=lambda: False)
    instance._zone_sound_enabled = False
    instance._manual_pos = None
    instance._user_moved = False
    instance._corner = Corner.TOP_RIGHT
    return instance


def test_save_config_returns_failure_without_background_popup(monkeypatch) -> None:
    app = _make_config_only_app()
    monkeypatch.setattr(app_module.ConfigManager, "load", lambda: {})
    monkeypatch.setattr(app_module.ConfigManager, "save", lambda _config: False)

    showerror = SimpleNamespace(calls=0)

    def record_showerror(*_args, **_kwargs) -> None:
        showerror.calls += 1

    monkeypatch.setattr(app_module.messagebox, "showerror", record_showerror)

    assert app._save_config() is False
    assert showerror.calls == 0


def test_save_config_warns_for_explicit_user_save_failure(monkeypatch) -> None:
    app = _make_config_only_app()
    monkeypatch.setattr(app_module.ConfigManager, "load", lambda: {})
    monkeypatch.setattr(app_module.ConfigManager, "save", lambda _config: False)

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        app_module.messagebox,
        "showerror",
        lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )

    assert app._save_config(warn_on_failure=True) is False
    assert len(calls) == 1
    assert calls[0]["args"][:2] == ("保存失败", "配置保存失败，请检查配置文件权限或磁盘状态。")


def test_update_ui_reschedules_after_frame_exception(monkeypatch) -> None:
    app = _make_config_only_app()
    after_calls: list[tuple[int, object]] = []
    app._stop = False
    app._ui_after_id = None
    app._last_ui_gap_ms = 0.0
    app._last_ui_work_ms = 0.0
    app.root = SimpleNamespace(
        after=lambda delay, callback: after_calls.append((delay, callback)) or "after-id"
    )
    monkeypatch.setattr(
        App,
        "_update_ui_frame",
        lambda _self, _loop_start: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    log_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        app_module, "log_exception", lambda *args, **_kwargs: log_calls.append(args)
    )

    app._update_ui()

    assert app._ui_after_id == "after-id"
    assert len(after_calls) == 1
    assert after_calls[0][1] == app._update_ui
    assert log_calls and log_calls[0][0] == "ui_update_failed"


def test_update_ui_cancels_pending_frame_before_manual_refresh(monkeypatch) -> None:
    app = _make_config_only_app()
    after_calls: list[tuple[int, object]] = []
    cancelled: list[str] = []
    app._stop = False
    app._ui_after_id = "pending-frame"
    app._last_ui_gap_ms = 0.0
    app._last_ui_work_ms = 0.0
    app.root = SimpleNamespace(
        after=lambda delay, callback: after_calls.append((delay, callback)) or "next-frame",
        after_cancel=lambda after_id: cancelled.append(after_id),
    )
    monkeypatch.setattr(App, "_update_ui_frame", lambda _self, _loop_start: None)

    app._update_ui()

    assert cancelled == ["pending-frame"]
    assert app._ui_after_id == "next-frame"
    assert len(after_calls) == 1


def test_app_keeps_only_external_callback_wrappers() -> None:
    removed_internal_wrappers = {
        "_toggle_debug_mock_mode",
        "_cycle_debug_scene",
        "_update_debug_controls",
        "_build_debug_snapshot",
        "_build_debug_mock_snapshot",
        "_build_debug_text",
        "_format_aircraft_type_label",
        "_update_speed_strip",
        "_ensure_hud_overlay",
        "_update_hud_overlay",
        "_toggle_hud",
        "_update_mid_panel_layout",
        "_set_zone_panel_visible",
        "_update_tape_info_labels",
        "_set_checklist_visible",
        "_update_zone_display",
        "_reset_navigation_layout_state",
        "_update_fuel_display",
        "_update_bombing_display",
    }

    app_methods = set(App.__dict__)

    assert not (removed_internal_wrappers & app_methods)
    assert "_toggle_debug" in app_methods
    assert "_show_hud_overlay" in app_methods
