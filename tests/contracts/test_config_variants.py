from __future__ import annotations

import importlib.util
from pathlib import Path

from bomana import config
from bomana.config import feature_profile, settings
from bomana.utils.file_utils import ConfigManager

# enforces: docs/specs/config-variants.md CFG-01..CFG-08

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
        },
        "Standard": {
            "ENABLE_CCRP": "False",
            "ENABLE_ZONES": "True",
            "ENABLE_AIRFIELDS": "True",
            "ENABLE_FUEL": "True",
            "ENABLE_CHECKLIST": "True",
            "ENABLE_ADVANCED_SETTINGS": "True",
        },
        "Lite": {
            "ENABLE_CCRP": "False",
            "ENABLE_ZONES": "False",
            "ENABLE_AIRFIELDS": "False",
            "ENABLE_FUEL": "False",
            "ENABLE_CHECKLIST": "False",
            "ENABLE_ADVANCED_SETTINGS": "True",
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
    )
    assert all(
        getattr(feature_profile, name) is True for name in feature_profile.FEATURE_FLAG_NAMES
    )


def test_config_package_facade_preserves_public_reexports() -> None:
    assert config.PanelConfig is settings.PanelConfig
    assert config.Theme is not None
    assert config.__version__
    assert config.ENABLE_CCRP is feature_profile.ENABLE_CCRP
    assert hasattr(config, "GameConfig")
    assert hasattr(config, "BombConfig")


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
