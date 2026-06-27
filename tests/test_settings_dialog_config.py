from types import SimpleNamespace

from bomana.config import HotkeyConfig, UIConfig
from bomana.ui import dialogs
from bomana.ui.dialogs import SettingsDialog


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
    dialog.app = SimpleNamespace(
        sound=FakeSound(),
        _zone_sound_enabled=True,
        _refresh_tray=lambda: None,
        _update_hint=lambda: None,
        nav_window=None,
        hwnd=0,
        _locked=False,
        apply_display_settings_runtime=lambda **_kwargs: None,
        refresh_local_hotkey_bindings=lambda: None,
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
