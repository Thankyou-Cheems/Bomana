from types import SimpleNamespace

from bomana.core.state import Phase, UISnapshot
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
    instance._locked = True
    instance._manual_reset_confirm_until = 0.0
    instance._nudge_visible = False
    instance._hotkey_broker_notice = ""
    instance._hotkey_broker_action = ""
    return instance


class _FakeLabel:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def config(self, **kwargs) -> None:
        self.options.update(kwargs)


class _FakeNudgeRow:
    def __init__(self, manager: str) -> None:
        self.manager = manager
        self.grid_calls = 0
        self.grid_remove_calls = 0

    def winfo_manager(self) -> str:
        return self.manager

    def grid(self, **_kwargs) -> None:
        self.manager = "grid"
        self.grid_calls += 1

    def grid_remove(self) -> None:
        self.manager = ""
        self.grid_remove_calls += 1


def _make_hint_app_with_nudge(*, visible: bool, manager: str):
    app = _make_config_only_app()
    app._nudge_visible = visible
    app._manual_reset_confirm_until = 0.0
    app._hint_width_cache = {"text": "old"}
    app._hint_text = lambda: "hint"
    app._nudge_text = lambda: "nudge"
    app._update_lock_badge = lambda: None
    recalc_calls: list[dict[str, object]] = []
    app._recalc_size = lambda **kwargs: recalc_calls.append(kwargs)
    app.main_frame = object()
    app.hint_lbl = _FakeLabel()
    app.nudge_lbl = _FakeLabel()
    app.star_lbl = _FakeLabel()
    app.nudge_row = _FakeNudgeRow(manager)
    return app, recalc_calls


def test_init_ui_syncs_hint_after_build(monkeypatch) -> None:
    app = _make_config_only_app()
    calls: list[str] = []

    class FakeBuilder:
        def __init__(self, built_app) -> None:
            assert built_app is app

        def build(self) -> None:
            calls.append("build")

    monkeypatch.setattr(app_module, "MainWindowBuilder", FakeBuilder)
    app._update_hint = lambda: calls.append("hint")

    app._init_ui()

    assert calls == ["build", "hint"]


def test_update_hint_removes_hidden_star_nudge_row() -> None:
    app, recalc_calls = _make_hint_app_with_nudge(visible=False, manager="grid")

    app._update_hint()

    assert app.nudge_lbl.options["text"] == ""
    assert app.star_lbl.options["text"] == ""
    assert app.star_lbl.options["cursor"] == "arrow"
    assert app.nudge_row.manager == ""
    assert app.nudge_row.grid_remove_calls == 1
    assert recalc_calls == [{"force_shrink": True}]


def test_update_hint_restores_visible_star_nudge_row() -> None:
    app, recalc_calls = _make_hint_app_with_nudge(visible=True, manager="")

    app._update_hint()

    assert app.nudge_lbl.options["text"] == "nudge"
    assert app.star_lbl.options["text"] == "GitHub Star"
    assert app.star_lbl.options["cursor"] == "hand2"
    assert app.nudge_row.manager == "grid"
    assert app.nudge_row.grid_calls == 1
    assert recalc_calls == [{"force_shrink": False}]


def test_hotkey_broker_notice_uses_existing_nudge_row_with_elevation_action() -> None:
    app, recalc_calls = _make_hint_app_with_nudge(visible=False, manager="")
    app._hotkey_broker_notice = "游戏前台热键需要单独授权。"
    app._hotkey_broker_action = "elevate"
    app._nudge_text = App._nudge_text.__get__(app, App)

    app._update_hint()

    assert app.nudge_lbl.options["text"] == "游戏前台热键需要单独授权。"
    assert app.star_lbl.options["text"] == "授权管理员热键"
    assert app.star_lbl.options["cursor"] == "hand2"
    assert app.nudge_row.manager == "grid"
    assert recalc_calls == [{"force_shrink": False}]


def test_elevation_action_requires_bomana_confirmation_before_uac(monkeypatch) -> None:
    app = _make_config_only_app()
    app._hotkey_broker_action = "elevate"
    calls: list[str] = []
    app.runtime_services = SimpleNamespace(
        retry_hotkey_broker=lambda: calls.append("uac"),
    )

    monkeypatch.setattr(app_module.messagebox, "askokcancel", lambda *_args, **_kwargs: False)
    app._on_nudge_action()
    assert calls == []

    prompts: list[str] = []

    def approve(_title, message, **_kwargs) -> bool:
        prompts.append(message)
        return True

    monkeypatch.setattr(app_module.messagebox, "askokcancel", approve)
    app._on_nudge_action()

    assert calls == ["uac"]
    assert "未知" in prompts[0]
    assert "不会安装额外程序" in prompts[0]


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
        "_capture_snap_anchor",
        "_apply_snap_anchor",
        "refresh_local_hotkey_bindings",
    }

    app_methods = set(App.__dict__)

    assert not (removed_internal_wrappers & app_methods)
    assert "_toggle_debug" in app_methods
    assert "_show_hud_overlay" in app_methods


def test_hotkey_config_rejects_invalid_saved_bindings() -> None:
    original = app_module.HotkeyConfig.get_bindings()
    try:
        app_module.HotkeyConfig.set_bindings(
            {
                "reset": "f1",
                "lock": "BAD KEY",
                "corner": " F2 ",
                "beep": "",
                "zones": "F12",
            }
        )

        assert app_module.HotkeyConfig.get_bindings() == {
            "reset": "F1",
            "lock": app_module.HotkeyConfig.DEFAULT_BINDINGS["lock"],
            "corner": "F2",
            "beep": app_module.HotkeyConfig.DEFAULT_BINDINGS["beep"],
            "zones": "F12",
        }
    finally:
        app_module.HotkeyConfig.set_bindings(original)


def test_update_ui_frame_refreshes_visible_standalone_navigation_when_phase_exits(
    monkeypatch,
) -> None:
    app = _make_config_only_app()
    snap = UISnapshot(
        phase=Phase.IDLE,
        life_index=None,
        cycle=None,
        remaining_sec=None,
        progress=0.0,
        sortie_id=1,
        api_down=False,
        api_down_pending=False,
        on_ground=False,
        landed_flash=False,
    )
    nav_updates: list[UISnapshot] = []
    nav_window = SimpleNamespace(
        is_visible=lambda: True,
        update_display=lambda current_snap: nav_updates.append(current_snap),
    )
    app.navigation_services = SimpleNamespace(window=nav_window)
    app.game = SimpleNamespace(snapshot=lambda: snap, timer_restore_applied=False)
    app._last_ui_frame_ts = 0.0
    app._debug = False
    app._debug_effective_mock = False
    app._debug_live_available = False
    app._restored_state = False
    app._nudge_sortie_seen = 1
    app._nudge_airborne_seen = False
    app._nudge_visible = False
    app._nudge_sortie_id = 0
    app._last_landed_flash = False
    app._manual_reset_confirm_until = 0.0
    app._last_zone_recalc_ts = 0.0
    app._last_beep_sec = -1
    app.scale = 1.0
    app.panel_renderer = SimpleNamespace(
        set_zone_panel_visible=lambda _visible: None,
        update_zone_display=lambda _snap: (_ for _ in ()).throw(
            AssertionError("hidden zone panel should not render")
        ),
        set_checklist_visible=lambda _visible: None,
    )
    app._apply_speed_history_layout = lambda _active: None
    app._refresh_speed_history_ui = lambda _snap, _speed_level: None
    app.bar_fill = SimpleNamespace(place=lambda **_kwargs: None, config=lambda **_kwargs: None)
    app.timer_lbl = SimpleNamespace(config=lambda **_kwargs: None)
    app.life_lbl = SimpleNamespace(config=lambda **_kwargs: None)
    app.cycle_lbl = SimpleNamespace(config=lambda **_kwargs: None)
    app.badge_main = SimpleNamespace(set=lambda *_args: None)
    app.badge_flight = SimpleNamespace(set=lambda *_args: None)
    app.badge_gear = SimpleNamespace(
        winfo_ismapped=lambda: False,
        set=lambda *_args: None,
        pack=lambda **_kwargs: None,
        pack_forget=lambda: None,
    )
    app.speed_row = SimpleNamespace(
        winfo_manager=lambda: "",
        grid=lambda **_kwargs: None,
        grid_remove=lambda: None,
    )
    app.status_txt = SimpleNamespace(config=lambda **_kwargs: None)
    app.runtime_services = SimpleNamespace(update_hud_overlay=lambda _snap: None)
    monkeypatch.setattr(app_module.PanelConfig, "is_effectively_enabled", lambda _feature: False)
    monkeypatch.setattr(app_module.PanelConfig, "speed_history_mode", False)

    app._update_ui_frame(100.0)

    assert nav_updates == [snap]
