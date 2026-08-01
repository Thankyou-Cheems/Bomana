from __future__ import annotations

import pytest

from bomana.config.settings import UIConfig
from bomana.ui import settings_form


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class InvalidNumberVar:
    def get(self):
        raise ValueError("bad number")


def make_payload_kwargs(**overrides):
    kwargs = {
        "alpha_var": FakeVar(210),
        "nav_width_var": FakeVar(1.35),
        "nav_scale_var": FakeVar(1.2),
        "scale_var": FakeVar(UIConfig.DEFAULT_UI_SCALE_MULT),
        "text_scale_var": FakeVar(1.0),
        "theme_var": FakeVar("fluent_dark"),
        "hotkeys_enabled_var": FakeVar(True),
        "hotkey_bindings": {"reset": "F7"},
        "panel_vars": {"show_zones": FakeVar(False)},
        "snap_var": FakeVar(True),
        "snap_dist_var": FakeVar(20),
        "sound_enabled_var": FakeVar(False),
        "zone_sound_enabled_var": FakeVar(True),
        "overspeed_vars": {},
        "overspeed_override_map": {},
        "existing_config": {"panels": {"show_bombing": False, "show_zones": True}},
        "enable_ccrp": False,
    }
    kwargs.update(overrides)
    return kwargs


def test_collect_hotkey_bindings_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="检测到重复快捷键绑定"):
        settings_form.collect_hotkey_bindings(
            {
                "reset": FakeVar("F7"),
                "lock": FakeVar("F7"),
            }
        )


def test_build_settings_save_payload_clamps_navigation_scale_and_merges_panels() -> None:
    payload = settings_form.build_settings_save_payload(
        **make_payload_kwargs(nav_scale_var=FakeVar(9.0))
    )

    assert payload.panel_config == {"show_bombing": False, "show_zones": False}
    assert payload.nav_scale == 2.0


def test_build_settings_save_payload_validates_overspeed_before_config_mutation() -> None:
    with pytest.raises(ValueError, match="IAS 提示线 必须输入有效数字"):
        settings_form.build_settings_save_payload(
            **make_payload_kwargs(overspeed_vars={"caution_ratio": InvalidNumberVar()})
        )


def test_apply_settings_payload_to_config_writes_expected_sections() -> None:
    payload = settings_form.build_settings_save_payload(
        **make_payload_kwargs(
            enable_ccrp=True,
            selected_bomb_id="fab_500",
        )
    )
    config: dict[str, object] = {
        "ccrp_tuning": {"range_correction_mult": 1.1, "time_correction_mult": 0.9},
        "hud_enabled": True,
        "hud": {"alpha": 220},
    }

    settings_form.apply_settings_payload_to_config(
        config,
        payload,
        sound_settings={"alert": "custom.wav"},
    )

    assert config["navigation_bar_width"] == 1.35
    assert config["navigation_bar_scale"] == 1.2
    assert config["sound_settings"] == {"alert": "custom.wav"}
    assert "ccrp_tuning" not in config
    assert "hud_enabled" not in config
    assert "hud" not in config
    assert config["selected_bomb"] == "fab_500"
