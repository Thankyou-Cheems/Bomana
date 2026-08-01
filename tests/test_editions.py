from __future__ import annotations

import pytest

from bomana.editions import (
    CHANNELS,
    LITE_EDITION,
    PUBLIC_CHANNELS,
    STANDARD_EDITION,
    SUBSCRIPTION_CHANNELS,
    SUPER_BOMB_EDITION,
    WEB_COCKPIT_CHANNELS,
    EditionAccess,
    EditionCapability,
    feature_flags_for,
    find_edition,
    require_edition,
    require_public_edition,
    variant_switch_matrix,
)


def test_public_and_subscriber_editions_have_distinct_access() -> None:
    assert CHANNELS == ("Enhanced", "Standard", "Lite")
    assert PUBLIC_CHANNELS == ("Standard", "Lite")
    assert SUBSCRIPTION_CHANNELS == ("Enhanced",)
    assert SUPER_BOMB_EDITION.access is EditionAccess.SUBSCRIPTION
    assert STANDARD_EDITION.access is EditionAccess.PUBLIC
    assert LITE_EDITION.access is EditionAccess.PUBLIC


def test_release_aliases_preserve_enhanced_identity() -> None:
    assert find_edition("Enhanced") is SUPER_BOMB_EDITION
    assert find_edition("enhanced") is SUPER_BOMB_EDITION
    assert find_edition("超级爆弹版") is SUPER_BOMB_EDITION
    assert find_edition("Standard") is STANDARD_EDITION
    assert find_edition("精简版") is LITE_EDITION
    assert find_edition("unknown") is None
    with pytest.raises(ValueError, match="unknown Bomana edition"):
        require_edition("unknown")
    assert require_public_edition("Standard") is STANDARD_EDITION
    with pytest.raises(ValueError, match="private closure"):
        require_public_edition("Enhanced")


def test_capabilities_drive_legacy_flags_and_web_packaging() -> None:
    enhanced = feature_flags_for(SUPER_BOMB_EDITION)
    standard = feature_flags_for(STANDARD_EDITION)
    lite = feature_flags_for(LITE_EDITION)

    assert all(enhanced.values())
    assert standard == {
        "ENABLE_CCRP": False,
        "ENABLE_ZONES": True,
        "ENABLE_AIRFIELDS": True,
        "ENABLE_FUEL": True,
        "ENABLE_CHECKLIST": True,
        "ENABLE_ADVANCED_SETTINGS": True,
        "ENABLE_WEB_DASHBOARD": False,
    }
    assert lite == {
        "ENABLE_CCRP": False,
        "ENABLE_ZONES": False,
        "ENABLE_AIRFIELDS": False,
        "ENABLE_FUEL": False,
        "ENABLE_CHECKLIST": False,
        "ENABLE_ADVANCED_SETTINGS": True,
        "ENABLE_WEB_DASHBOARD": False,
    }
    assert {"Enhanced"} == WEB_COCKPIT_CHANNELS
    assert SUPER_BOMB_EDITION.includes(EditionCapability.STRIKE_PREDICTION)


def test_build_matrix_is_a_projection_of_edition_policy() -> None:
    matrix = variant_switch_matrix()

    assert matrix["Enhanced"]["ENABLE_CCRP"] == "True"
    assert matrix["Standard"]["ENABLE_ZONES"] == "True"
    assert matrix["Standard"]["ENABLE_CCRP"] == "False"
    assert matrix["Lite"]["ENABLE_ADVANCED_SETTINGS"] == "True"
    assert matrix["Lite"]["ENABLE_ZONES"] == "False"
