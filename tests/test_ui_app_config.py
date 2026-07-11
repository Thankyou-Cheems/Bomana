import ast
import inspect
import textwrap
from types import SimpleNamespace

from bomana.core.state import Phase, UISnapshot
from bomana.ui import app as app_module
from bomana.ui.app import App, Corner
from bomana.web.control import ValidatedWebCommand, WebCommandEnvelope


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


def _web_envelope(command: ValidatedWebCommand) -> WebCommandEnvelope:
    return WebCommandEnvelope(
        session_token="session-token",
        transport="loopback",
        scope="control",
        authorization_epoch=2,
        command_id="mobile-1",
        command=command,
        submitted_revision=1,
    )


class _FakeLabel:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def config(self, **kwargs) -> None:
        self.options.update(kwargs)

    configure = config


class _FakeWeaponCatalog:
    def __init__(self, selected_weapon_id: str = "su_fab100") -> None:
        self.records = {
            "su_fab100": {"id": "su_fab100", "role": "bomb"},
            "agm_65d": {"id": "agm_65d", "role": "agm"},
            "legacy_bomb_source": {"id": "legacy_bomb_source", "role": "bomb"},
        }
        self.selected_weapon_id = selected_weapon_id
        self.selection_source = "manual"
        self.set_calls: list[tuple[str, str]] = []

    @property
    def selected_weapon(self):
        return self.records.get(self.selected_weapon_id)

    def set_selected(self, weapon_id: str, source: str = "manual") -> bool:
        self.set_calls.append((weapon_id, source))
        if weapon_id not in self.records:
            return False
        self.selected_weapon_id = weapon_id
        self.selection_source = source
        return True


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


def test_content_geometry_sync_expands_when_required_height_grows() -> None:
    calls: list[str] = []
    app = SimpleNamespace(
        root=SimpleNamespace(
            winfo_height=lambda: 320,
            update_idletasks=lambda: None,
        ),
        main_frame=SimpleNamespace(winfo_reqheight=lambda: 420),
        scale=1.0,
        _recalc_size=lambda: calls.append("expand"),
    )

    App._sync_content_geometry(app)

    assert calls == ["expand"]


def test_content_geometry_sync_does_not_loop_when_content_fits() -> None:
    calls: list[str] = []
    app = SimpleNamespace(
        root=SimpleNamespace(
            winfo_height=lambda: 420,
            update_idletasks=lambda: None,
        ),
        main_frame=SimpleNamespace(winfo_reqheight=lambda: 400),
        scale=1.0,
        _recalc_size=lambda: calls.append("expand"),
    )

    App._sync_content_geometry(app)

    assert calls == []


def test_web_command_rechecks_authorization_before_semantic_execution() -> None:
    app = _make_config_only_app()
    reasons: list[str] = []
    app.runtime_services = SimpleNamespace(reauthorize_web_command=lambda _envelope: False)
    app._apply_web_command = lambda _envelope: (_ for _ in ()).throw(
        AssertionError("revoked command must not execute")
    )
    app._complete_web_command = lambda _envelope, reason: reasons.append(reason)

    app._execute_web_command(_web_envelope(ValidatedWebCommand(name="action.cycle_corner")))

    assert reasons == ["authorization_revoked"]


def test_web_access_row_shows_current_pairing_and_every_lan_address(monkeypatch) -> None:
    app = _make_config_only_app()
    app.web_access_row = _FakeNudgeRow("")
    app.web_access_lbl = _FakeLabel()
    app.web_lan_btn = _FakeLabel()
    dashboard = SimpleNamespace(
        is_running=True,
        pairing_code="ABCD-EFGH",
        port=8777,
        lan_addresses=("192.168.31.69", "10.126.126.2"),
        lan_control_enabled=True,
    )
    app.runtime_services = SimpleNamespace(dashboard=dashboard)
    monkeypatch.setattr(app_module, "style_action_button", lambda *_args, **_kwargs: None)

    app._refresh_web_access_row()

    label = str(app.web_access_lbl.options["text"])
    assert "ABCD-EFGH" in label
    assert "192.168.31.69:8777" in label
    assert "10.126.126.2:8777" in label
    assert app.web_lan_btn.options["text"] == "关局域网"
    assert app.web_access_row.manager == "grid"


def test_web_zone_command_rechecks_compile_feature_gate(monkeypatch) -> None:
    app = _make_config_only_app()
    monkeypatch.setattr(app_module, "ENABLE_ZONES", False)
    envelope = _web_envelope(ValidatedWebCommand(name="state.set_zone_sound_enabled", enabled=True))

    assert app._apply_web_command(envelope) == "feature_disabled"


def test_web_control_projection_respects_compile_feature_authority(monkeypatch) -> None:
    app = _make_config_only_app()
    app.game = SimpleNamespace(snapshot=lambda: SimpleNamespace(phase=Phase.IDLE, on_ground=True))
    for name in (
        "ENABLE_CCRP",
        "ENABLE_ZONES",
        "ENABLE_AIRFIELDS",
        "ENABLE_FUEL",
        "ENABLE_CHECKLIST",
    ):
        monkeypatch.setattr(app_module, name, False)
    monkeypatch.setattr(app_module.PanelConfig, "show_zones", True)
    monkeypatch.setattr(app_module.PanelConfig, "show_airfields", True)
    monkeypatch.setattr(app_module.PanelConfig, "show_fuel", True)
    monkeypatch.setattr(app_module.PanelConfig, "show_checklist", True)
    monkeypatch.setattr(app_module.PanelConfig, "show_bombing", True)

    projection = app._build_web_control_projection(revision=1)

    assert projection.commands == (
        "action.reset_timer",
        "action.cycle_corner",
        "state.set_locked",
        "state.set_beep_enabled",
        "config.set_panel_visibility",
        "config.set_timer_cycle_minutes",
    )
    assert projection.panel_targets == ("speed",)
    assert projection.weapons == ()
    assert projection.state.zone_sound_enabled is False
    assert projection.state.timer_cycle_minutes == 15
    assert projection.state.panel_visibility.zones is False
    assert projection.state.panel_visibility.weapon_solution is False


def test_web_weapon_choices_are_cached_between_unchanged_ui_frames(monkeypatch) -> None:
    app = _make_config_only_app()
    searches: list[str] = []

    class Catalog:
        selected_weapon_id = "agm_65d"

        def search(self, query: str):
            searches.append(query)
            return [
                {
                    "id": "agm_65d",
                    "display_name": "AGM-65D",
                    "role": "agm",
                }
            ]

        def for_aircraft(self, _aircraft: str):
            return []

        def compatible(self, _weapon_id: str, _aircraft: str) -> bool:
            return True

    catalog = Catalog()
    snap = SimpleNamespace(
        phase=Phase.IDLE,
        on_ground=True,
        aircraft_type_name="f_16c_block_50",
    )
    app.game = SimpleNamespace(snapshot=lambda: snap)
    app._get_weapon_catalog = lambda: catalog
    monkeypatch.setattr(app_module, "ENABLE_CCRP", True)

    first = app._build_web_control_projection(revision=1, snapshot=snap)
    second = app._build_web_control_projection(revision=1, snapshot=snap)

    assert first.weapons == second.weapons
    assert searches == [""]


def test_web_weapon_choices_disable_unverified_airborne_compatibility(monkeypatch) -> None:
    app = _make_config_only_app()

    class Catalog:
        selected_weapon_id = "agm_65d"

        @staticmethod
        def search(_query: str):
            return [{"id": "agm_65d", "display_name": "AGM-65D", "role": "agm"}]

        @staticmethod
        def for_aircraft(_aircraft: str):
            return []

        @staticmethod
        def compatible(_weapon_id: str, _aircraft: str) -> bool:
            return False

    snap = SimpleNamespace(phase=Phase.ALIVE, on_ground=False, aircraft_type_name="")
    app.game = SimpleNamespace(snapshot=lambda: snap)
    app._get_weapon_catalog = lambda: Catalog()
    monkeypatch.setattr(app_module, "ENABLE_CCRP", True)

    projection = app._build_web_control_projection(revision=1, snapshot=snap)

    assert len(projection.weapons) == 1
    assert projection.weapons[0].compatible is False


def test_web_weapon_select_rejects_unverified_airborne_compatibility(monkeypatch) -> None:
    app = _make_config_only_app()
    persisted: list[str] = []

    class Catalog:
        @staticmethod
        def get(weapon_id: str):
            return {"id": weapon_id, "role": "agm"}

        @staticmethod
        def compatible(_weapon_id: str, _aircraft: str) -> bool:
            return False

    app.game = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(
            phase=Phase.ALIVE,
            on_ground=False,
            aircraft_type_name="unknown_aircraft",
        )
    )
    app._get_weapon_catalog = lambda: Catalog()
    monkeypatch.setattr(app_module, "ENABLE_CCRP", True)
    monkeypatch.setattr(
        app_module,
        "persist_weapon_selection",
        lambda _catalog, weapon_id, _model: persisted.append(weapon_id) or True,
    )

    reason = app._apply_web_command(
        _web_envelope(ValidatedWebCommand(name="weapon.select", weapon_id="agm_65d"))
    )

    assert reason == "weapon_incompatible"
    assert persisted == []


def test_web_timer_command_rechecks_exact_target_and_persistence(monkeypatch) -> None:
    app = _make_config_only_app()
    targets: list[int] = []
    app._set_timer_cycle_minutes = lambda minutes: targets.append(minutes) or True

    reason = app._apply_web_command(
        _web_envelope(
            ValidatedWebCommand(
                name="config.set_timer_cycle_minutes",
                minutes=60,
            )
        )
    )

    assert reason == "ok"
    assert targets == [60]


def test_explicit_beep_target_rolls_back_when_persistence_fails() -> None:
    app = _make_config_only_app()
    current = {"enabled": False}
    app.sound = SimpleNamespace(
        is_enabled=lambda: current["enabled"],
        set_enabled=lambda value: current.update(enabled=value),
    )
    app._save_config = lambda **_kwargs: False

    assert app._set_beep_enabled(True) is False
    assert current["enabled"] is False


def test_same_locked_target_is_successful_noop_without_persistence() -> None:
    app = _make_config_only_app()
    app._locked = True
    app._save_config = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("same target must not persist")
    )

    assert app._set_locked_state(True) is True


def test_same_beep_target_is_successful_noop_without_persistence_or_sound() -> None:
    app = _make_config_only_app()
    app.sound = SimpleNamespace(
        is_enabled=lambda: False,
        set_enabled=lambda _value: (_ for _ in ()).throw(
            AssertionError("same target must not mutate sound")
        ),
        play=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("same target must not play sound")
        ),
    )
    app._save_config = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("same target must not persist")
    )

    assert app._set_beep_enabled(False) is True


def test_explicit_panel_target_rolls_back_when_persistence_fails(monkeypatch) -> None:
    app = _make_config_only_app()
    monkeypatch.setattr(app_module.PanelConfig, "show_speed", True)
    app._save_config = lambda **_kwargs: False

    assert app._set_panel_visibility("speed", False) is False
    assert app_module.PanelConfig.show_speed is True


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

    assert app.nudge_lbl.options["text"] == (
        f"游戏前台热键需要单独授权。 先按 [{app_module.HotkeyConfig.KEY_LOCK}] 解锁 Bomana。"
    )
    assert app.star_lbl.options["text"] == "启用热键"
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
    catalog = _FakeWeaponCatalog()
    monkeypatch.setattr(app_module, "get_weapon_catalog", lambda: catalog)
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
    catalog = _FakeWeaponCatalog()
    monkeypatch.setattr(app_module, "get_weapon_catalog", lambda: catalog)
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


def test_load_config_migrates_missing_selected_weapon_from_selected_bomb(monkeypatch) -> None:
    app = _make_config_only_app()
    app.sound = SimpleNamespace(set_enabled=lambda _enabled: None, is_enabled=lambda: False)
    catalog = _FakeWeaponCatalog(selected_weapon_id="agm_65d")
    monkeypatch.setattr(app_module, "get_weapon_catalog", lambda: catalog)
    monkeypatch.setattr(
        app_module.ConfigManager,
        "load",
        lambda: {
            "scale": 1.0,
            "selected_bomb": "su_fab100",
            "panels": {},
        },
    )
    monkeypatch.setattr(app_module.BombConfig, "get_bomb_data", lambda _value: {})

    app._load_config()

    assert catalog.set_calls == [("su_fab100", "manual")]
    assert catalog.selected_weapon_id == "su_fab100"
    assert catalog.selection_source == "manual"


def test_load_config_restores_ballistic_model_and_rejects_unknown(monkeypatch) -> None:
    app = _make_config_only_app()
    app.sound = SimpleNamespace(set_enabled=lambda _enabled: None, is_enabled=lambda: False)
    catalog = _FakeWeaponCatalog()
    monkeypatch.setattr(app_module, "get_weapon_catalog", lambda: catalog)
    monkeypatch.setattr(app_module.BombConfig, "get_bomb_data", lambda _value: {})
    monkeypatch.setattr(
        app_module.ConfigManager,
        "load",
        lambda: {
            "scale": 1.0,
            "panels": {},
            "weapon_ballistic_model": "strict_official",
        },
    )

    app._load_config()

    assert app_module.WeaponBallisticModelConfig.selected_model == "strict_official"

    monkeypatch.setattr(
        app_module.ConfigManager,
        "load",
        lambda: {
            "scale": 1.0,
            "panels": {},
            "weapon_ballistic_model": "made_up_model",
        },
    )
    app._load_config()

    assert (
        app_module.WeaponBallisticModelConfig.selected_model
        == app_module.WeaponBallisticModelConfig.DEFAULT_MODEL
    )


def test_load_config_migrates_legacy_ccrp_key_to_datamine_source_id(monkeypatch) -> None:
    app = _make_config_only_app()
    app.sound = SimpleNamespace(set_enabled=lambda _enabled: None, is_enabled=lambda: False)
    catalog = _FakeWeaponCatalog(selected_weapon_id="agm_65d")
    monkeypatch.setattr(app_module, "get_weapon_catalog", lambda: catalog)
    monkeypatch.setattr(
        app_module.ConfigManager,
        "load",
        lambda: {
            "scale": 1.0,
            "selected_bomb": "legacy_ccrp_key",
            "panels": {},
        },
    )
    monkeypatch.setattr(
        app_module.BombConfig,
        "get_bomb_data",
        lambda value: {"mass": 100.0} if value == "legacy_ccrp_key" else None,
    )
    monkeypatch.setattr(
        app_module.BombConfig,
        "get_bomb_source_id",
        lambda value: "legacy_bomb_source" if value == "legacy_ccrp_key" else "",
    )

    app._load_config()

    assert catalog.selected_weapon_id == "legacy_bomb_source"
    assert catalog.selection_source == "manual"


def test_save_config_writes_weapon_and_ccrp_bomb_selection_together(monkeypatch) -> None:
    app = _make_config_only_app()
    catalog = _FakeWeaponCatalog(selected_weapon_id="agm_65d")
    saved = {}
    monkeypatch.setattr(app_module, "get_weapon_catalog", lambda: catalog)
    monkeypatch.setattr(app_module.ConfigManager, "load", lambda: {})
    monkeypatch.setattr(
        app_module.ConfigManager, "save", lambda config: saved.update(config) or True
    )
    monkeypatch.setattr(app_module.BombConfig, "selected_bomb", "su_fab100")
    monkeypatch.setattr(
        app_module.WeaponBallisticModelConfig,
        "selected_model",
        "strict_official",
    )

    assert app._save_config() is True
    assert saved["selected_weapon"] == "agm_65d"
    assert saved["selected_bomb"] == "su_fab100"
    assert saved["weapon_ballistic_model"] == "strict_official"


def test_main_card_selector_filters_with_current_aircraft_only_in_flight(monkeypatch) -> None:
    app = _make_config_only_app()
    catalog = _FakeWeaponCatalog(selected_weapon_id="agm_65d")
    calls = []
    app.game = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(
            phase=Phase.ALIVE,
            on_ground=False,
            aircraft_type_name="f_16c_block_50",
        )
    )
    monkeypatch.setattr(app_module, "get_weapon_catalog", lambda: catalog)
    monkeypatch.setattr(
        app_module,
        "WeaponSelectorDialog",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    app._show_bomb_selector()

    assert len(calls) == 1
    assert calls[0][1] == {
        "catalog": catalog,
        "initial_weapon": "agm_65d",
        "aircraft_type_name": "f_16c_block_50",
        "airborne": True,
    }


def test_weapon_catalog_failure_reuses_core_fallback_and_disables_selector(monkeypatch) -> None:
    app = _make_config_only_app()
    app.game = SimpleNamespace(weapon_catalog=None)
    warnings = []
    monkeypatch.setattr(
        app_module,
        "get_weapon_catalog",
        lambda: (_ for _ in ()).throw(AssertionError("must not reload catalog")),
    )
    monkeypatch.setattr(
        app_module.messagebox,
        "showwarning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    app._show_bomb_selector()

    assert len(warnings) == 1
    assert warnings[0][0][:2] == (
        "武器目录不可用",
        "武器目录缺失或校验失败，已停用武器选择与解算。",
    )


def test_tray_initialization_remains_in_app_startup_flow() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(App)))
    methods = {node.name: node for node in tree.body[0].body if isinstance(node, ast.FunctionDef)}

    def calls_init_tray(method: ast.FunctionDef) -> bool:
        return any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_init_tray"
            for node in ast.walk(method)
        )

    assert calls_init_tray(methods["__init__"])
    assert not calls_init_tray(methods["_get_weapon_catalog"])


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
    app.banana_progress = SimpleNamespace(
        set_progress=lambda _value: None,
        set_color=lambda _value: None,
    )
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
    app.runtime_services = SimpleNamespace(
        publish_dashboard=lambda _snap, _items: None,
        update_hud_overlay=lambda _snap: None,
    )
    monkeypatch.setattr(app_module.PanelConfig, "is_effectively_enabled", lambda _feature: False)
    monkeypatch.setattr(app_module.PanelConfig, "speed_history_mode", False)

    app._update_ui_frame(100.0)

    assert nav_updates == [snap]
