# enforces: docs/specs/config-variants.md CFG-01..CFG-04 CFG-06..CFG-14

from __future__ import annotations

import importlib.util
from pathlib import Path

import bomana.config.feature_profile as feature_profile
import bomana.config.settings as settings
from bomana import metadata
from bomana.metadata import __version__
from bomana.ui.theme import Theme
from bomana.ui.theme import Theme as RuntimeTheme
from bomana.utils.file_utils import ConfigManager

ROOT = Path(__file__).resolve().parents[2]


def load_tool_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_variant_switch_matrix_matches_spec() -> None:
    build_portable = load_tool_module("build_portable_config_contract", "tools/build_portable.py")

    assert build_portable.VARIANT_SWITCHES == {
        "Enhanced": {
            "ENABLE_CCRP": "True",
            "ENABLE_ZONES": "True",
            "ENABLE_AIRFIELDS": "True",
            "ENABLE_FUEL": "True",
            "ENABLE_CHECKLIST": "True",
            "ENABLE_ADVANCED_SETTINGS": "True",
            "ENABLE_WEB_DASHBOARD": "True",
        },
        "Standard": {
            "ENABLE_CCRP": "False",
            "ENABLE_ZONES": "True",
            "ENABLE_AIRFIELDS": "True",
            "ENABLE_FUEL": "True",
            "ENABLE_CHECKLIST": "True",
            "ENABLE_ADVANCED_SETTINGS": "True",
            "ENABLE_WEB_DASHBOARD": "False",
        },
        "Lite": {
            "ENABLE_CCRP": "False",
            "ENABLE_ZONES": "False",
            "ENABLE_AIRFIELDS": "False",
            "ENABLE_FUEL": "False",
            "ENABLE_CHECKLIST": "False",
            "ENABLE_ADVANCED_SETTINGS": "True",
            "ENABLE_WEB_DASHBOARD": "False",
        },
    }


def test_source_feature_profile_defaults_to_enhanced() -> None:
    assert feature_profile.FEATURE_FLAG_NAMES == (
        "ENABLE_CCRP",
        "ENABLE_ZONES",
        "ENABLE_AIRFIELDS",
        "ENABLE_FUEL",
        "ENABLE_CHECKLIST",
        "ENABLE_ADVANCED_SETTINGS",
        "ENABLE_WEB_DASHBOARD",
    )
    assert all(
        getattr(feature_profile, name) is True for name in feature_profile.FEATURE_FLAG_NAMES
    )


def test_config_package_boundary_uses_explicit_submodules() -> None:
    import bomana.config as config

    assert config.__all__ == ["feature_profile", "settings", "static_data"]
    assert settings.PanelConfig
    assert feature_profile.ENABLE_CCRP is True
    assert not hasattr(config, "PanelConfig")
    assert not hasattr(config, "Theme")
    assert not hasattr(config, "__version__")
    assert __version__ == metadata.__version__
    assert Theme is RuntimeTheme


def test_panel_config_compile_flags_take_precedence(monkeypatch) -> None:
    panel = settings.PanelConfig
    for attr in (
        "show_zones",
        "show_airfields",
        "show_fuel",
        "show_checklist",
        "show_bombing",
        "show_speed",
    ):
        monkeypatch.setattr(panel, attr, True)
    monkeypatch.setattr(panel, "speed_history_mode", False)

    monkeypatch.setattr(settings, "ENABLE_CCRP", False)
    monkeypatch.setattr(settings, "ENABLE_ZONES", False)
    monkeypatch.setattr(settings, "ENABLE_AIRFIELDS", False)
    monkeypatch.setattr(settings, "ENABLE_FUEL", False)
    monkeypatch.setattr(settings, "ENABLE_CHECKLIST", False)

    panel.init_from_compile_switches()

    assert not panel.is_feature_enabled("bombing")
    assert not panel.is_feature_enabled("zones")
    assert not panel.is_feature_enabled("airfields")
    assert not panel.is_feature_enabled("fuel")
    assert not panel.is_feature_enabled("checklist")
    assert panel.is_feature_enabled("speed")
    assert not panel.show_bombing
    assert not panel.show_zones
    assert not panel.show_airfields
    assert not panel.show_fuel
    assert not panel.show_checklist


def test_speed_history_mode_suppresses_extended_panels_but_not_speed(monkeypatch) -> None:
    panel = settings.PanelConfig
    for flag_name in (
        "ENABLE_CCRP",
        "ENABLE_ZONES",
        "ENABLE_AIRFIELDS",
        "ENABLE_FUEL",
        "ENABLE_CHECKLIST",
    ):
        monkeypatch.setattr(settings, flag_name, True)
    for attr in (
        "show_zones",
        "show_airfields",
        "show_fuel",
        "show_checklist",
        "show_bombing",
        "show_speed",
    ):
        monkeypatch.setattr(panel, attr, True)
    monkeypatch.setattr(panel, "speed_history_mode", True)

    assert panel.is_effectively_enabled("speed")
    for feature in ("zones", "airfields", "fuel", "checklist", "bombing"):
        assert not panel.is_effectively_enabled(feature)


def test_compile_switches_persist_all_feature_flags() -> None:
    assert tuple(ConfigManager._current_compile_switches()) == feature_profile.FEATURE_FLAG_NAMES


def test_portable_build_patches_feature_profile_not_config_facade() -> None:
    source = (ROOT / "tools/build_portable.py").read_text(encoding="utf-8")

    assert '"config" / "feature_profile.py"' in source
    assert 'root / "bomana" / "config.py"' not in source
    assert "original_feature_profile = feature_profile_path.read_text" in source
    assert "feature_profile_path.write_text(original_feature_profile" in source


def test_variants_share_one_config_file() -> None:
    settings_source = (ROOT / "bomana/config/settings.py").read_text(encoding="utf-8")
    build_source = (ROOT / "tools/build_portable.py").read_text(encoding="utf-8")

    assert 'CONFIG_FILE = Path.home() / ".wttimer_config.json"' in settings_source
    assert "CONFIG_FILE" not in build_source


def test_disabled_zones_force_integrated_navigation_mode() -> None:
    source = (ROOT / "bomana/ui/app.py").read_text(encoding="utf-8")

    assert "if ENABLE_ZONES:" in source
    assert 'PanelConfig.navigation_mode = config.get("navigation_mode", "integrated")' in source
    assert 'PanelConfig.navigation_mode = "integrated"' in source


def test_weapon_solution_uses_legacy_bombing_gate_and_enhanced_packaging() -> None:
    # enforces: docs/specs/config-variants.md CFG-02, CFG-03, CFG-09
    portable = (ROOT / "tools/build_portable.py").read_text(encoding="utf-8")
    batch = (ROOT / "tools/scripts/build.bat").read_text(encoding="utf-8")
    shell = (ROOT / "tools/scripts/build.sh").read_text(encoding="utf-8")

    assert "weapon_catalog_rel" in portable
    assert "weapon_schema_rel" in portable
    assert 'variant != "Enhanced"' in portable
    assert "WEAPON_DATA_ARG" in batch
    assert "WEAPON_SCHEMA_ARG" in batch
    assert "weapon_fire_control.json" in batch
    assert 'if [ "$VARIANT" = "Enhanced" ]' in shell
    assert "weapon_fire_control.json" in shell


def test_launcher_web_preferences_are_an_exact_three_boolean_allowlist() -> None:
    launcher = (ROOT / "launcher.pyw").read_text(encoding="utf-8")
    bootstrap = (ROOT / "launcher/bootstrap.py").read_text(encoding="utf-8")
    combined = "\n".join((launcher, bootstrap))

    assert "web_dashboard_autostart" in launcher
    assert "web_dashboard_auto_open" in launcher
    assert "web_dashboard_autostart" in bootstrap
    assert "web_dashboard_auto_open" in bootstrap
    assert "web_dashboard_lan_enabled" in launcher
    assert "web_dashboard_lan_enabled" in bootstrap
    for forbidden in (
        "web_dashboard_host",
        "web_dashboard_port",
        "web_dashboard_pairing",
        "web_dashboard_lan_control",
        "web_dashboard_session",
        "web_dashboard_csrf",
        "web_dashboard_authorization_epoch",
    ):
        assert forbidden not in combined

    quickstart = (ROOT / "docs/QUICKSTART.md").read_text(encoding="utf-8")
    assert "Launcher persists only Web autostart" in quickstart
    assert "LAN access/control startup (off)" in quickstart
    assert "persist only loopback Web autostart" not in quickstart

    assert "DEFAULT_WEB_DASHBOARD_LAN_ENABLED = False" in launcher
    assert "BOMANA_WEB_DASHBOARD_LAN_ENABLED" in bootstrap
