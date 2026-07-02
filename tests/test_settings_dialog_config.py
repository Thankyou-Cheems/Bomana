from types import SimpleNamespace

from bomana.config.settings import (
    HotkeyConfig,
    UIConfig,
)
from bomana.ui import dialogs
from bomana.ui.dialogs import OverspeedAircraftOverrideDialog, SettingsDialog


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class FakeSound:
    def __init__(self) -> None:
        self.enabled = False

    def is_enabled(self) -> bool:
        return self.enabled

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled


class InvalidNumberVar:
    def get(self):
        raise dialogs.tk.TclError('expected floating-point number but got "bad"')


def _dialog_for_save() -> SettingsDialog:
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.alpha_var = FakeVar(210)
    dialog.nav_width_var = FakeVar(1.35)
    dialog.scale_var = FakeVar(UIConfig.DEFAULT_UI_SCALE_MULT)
    dialog.text_scale_var = FakeVar(1.0)
    dialog.theme_var = FakeVar("fluent_dark")
    dialog.hud_enabled_var = FakeVar(False)
    dialog.hud_alpha_var = FakeVar(255)
    dialog.hud_scale_var = FakeVar(1.0)
    dialog.hud_smoothing_var = FakeVar(0.35)
    dialog.hud_follow_main_monitor_var = FakeVar(True)
    dialog.hud_color_style_var = FakeVar("auto")
    dialog.hotkeys_enabled_var = FakeVar(HotkeyConfig.GLOBAL_HOTKEYS)
    dialog.hotkey_vars = {
        "reset": FakeVar("F7"),
        "lock": FakeVar("F8"),
        "corner": FakeVar("F9"),
        "beep": FakeVar("F10"),
        "zones": FakeVar("F11"),
    }
    dialog.panel_vars = {"show_zones": FakeVar(False)}
    dialog.snap_var = FakeVar(True)
    dialog.snap_dist_var = FakeVar(20)
    dialog.sound_enabled_var = FakeVar(False)
    dialog.zone_sound_enabled_var = FakeVar(True)
    dialog.sound_file_overrides = {}
    dialog.overspeed_vars = {}
    dialog.overspeed_override_map = {}
    dialog._persist_sound_overrides = lambda: ({}, [], [])
    dialog._refresh_runtime_hud_after_settings = lambda _previous: None
    dialog.destroy = lambda: None
    runtime_services = SimpleNamespace(refresh_local_hotkey_bindings=lambda: None)
    dialog.app = SimpleNamespace(
        sound=FakeSound(),
        _zone_sound_enabled=True,
        _refresh_tray=lambda: None,
        _update_hint=lambda: None,
        nav_window=None,
        hwnd=0,
        _locked=False,
        apply_display_settings_runtime=lambda **_kwargs: None,
        runtime_services=runtime_services,
    )
    return dialog


def test_reset_defaults_uses_current_ui_scale_default(monkeypatch) -> None:
    dialog = _dialog_for_save()
    monkeypatch.setattr(dialogs.messagebox, "askyesno", lambda *_args, **_kwargs: True)

    dialog._reset_defaults()

    assert dialog.scale_var.get() == UIConfig.DEFAULT_UI_SCALE_MULT


def test_settings_save_persists_nav_width_and_merges_panels(monkeypatch) -> None:
    dialog = _dialog_for_save()
    saved: dict[str, object] = {}

    monkeypatch.setattr(
        dialogs.ConfigManager,
        "load",
        lambda: {"panels": {"show_bombing": False, "show_zones": True}},
    )

    def save_config(config: dict[str, object]) -> bool:
        saved.update(config)
        return True

    monkeypatch.setattr(dialogs.ConfigManager, "save", save_config)
    monkeypatch.setattr(dialogs.Win32, "setup_window", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(dialogs.Theme, "apply", lambda _theme: None)
    monkeypatch.setattr(dialogs.messagebox, "showinfo", lambda *_args, **_kwargs: None)

    dialog._save()

    assert saved["navigation_bar_width"] == 1.35
    assert saved["panels"] == {"show_bombing": False, "show_zones": False}


def test_settings_save_validates_overspeed_before_sound_persistence(monkeypatch) -> None:
    dialog = _dialog_for_save()
    warnings = []
    dialog.overspeed_vars = {"caution_ratio": InvalidNumberVar()}

    monkeypatch.setattr(dialogs.ConfigManager, "load", lambda: {})
    monkeypatch.setattr(
        dialogs.ConfigManager,
        "save",
        lambda _config: (_ for _ in ()).throw(AssertionError("save should not run")),
    )
    dialog._persist_sound_overrides = lambda: (_ for _ in ()).throw(
        AssertionError("sound persistence should not run")
    )
    monkeypatch.setattr(
        dialogs.messagebox,
        "showwarning",
        lambda title, message, **_kwargs: warnings.append((title, message)),
    )

    dialog._save()

    assert warnings == [("数值无效", "IAS 提示线 必须输入有效数字。")]


def test_settings_save_validates_ccrp_before_sound_persistence(monkeypatch) -> None:
    dialog = _dialog_for_save()
    warnings = []
    dialog.ccrp_range_mult_var = InvalidNumberVar()
    dialog.ccrp_time_mult_var = FakeVar(1.0)

    monkeypatch.setattr(dialogs, "ENABLE_CCRP", True)
    monkeypatch.setattr(dialogs.ConfigManager, "load", lambda: {})
    monkeypatch.setattr(
        dialogs.ConfigManager,
        "save",
        lambda _config: (_ for _ in ()).throw(AssertionError("save should not run")),
    )
    dialog._persist_sound_overrides = lambda: (_ for _ in ()).throw(
        AssertionError("sound persistence should not run")
    )
    monkeypatch.setattr(
        dialogs.messagebox,
        "showwarning",
        lambda title, message, **_kwargs: warnings.append((title, message)),
    )

    dialog._save()

    assert warnings == [("数值无效", "CCRP 距离修正倍率 必须输入有效数字。")]


def test_aircraft_overspeed_override_invalid_number_warns_without_mutating(
    monkeypatch,
) -> None:
    dialog = OverspeedAircraftOverrideDialog.__new__(OverspeedAircraftOverrideDialog)
    existing_override = {"caution_ratio": 0.91}
    dialog.selected_aircraft_key = "test_aircraft"
    dialog.override_map = {"existing_aircraft": dict(existing_override)}
    dialog.editor_vars = {"caution_ratio": InvalidNumberVar()}
    dialog.aircraft_mode_var = FakeVar("状态：继承全局")
    dialog._effective_search_query = lambda: ""
    dialog._populate_list = lambda _query: (_ for _ in ()).throw(
        AssertionError("list refresh should not run")
    )
    warnings = []

    monkeypatch.setattr(
        dialogs.messagebox,
        "showwarning",
        lambda title, message, **_kwargs: warnings.append((title, message)),
    )

    dialog._apply_override()

    assert warnings == [("数值无效", "IAS 提示线 必须输入有效数字。")]
    assert dialog.override_map == {"existing_aircraft": existing_override}
    assert dialog.aircraft_mode_var.get() == "状态：继承全局"
