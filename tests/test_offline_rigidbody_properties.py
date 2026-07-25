from pathlib import Path

import pytest

from bomana.core.offline_rigidbody_catalog import (
    CATALOG_PROFILE_ID,
    CATALOG_SCHEMA_VERSION,
    load_catalog,
)
from bomana.core.offline_rigidbody_properties import (
    OFFLINE_DEFAULT_AXIAL_COEFFICIENT,
    derive_offline_rigidbody_properties,
)

CATALOG_PATH = Path("bomana/data/offline_rigidbody_catalog.bin")


def test_zb500_record_derives_expected_offline_properties() -> None:
    properties = derive_offline_rigidbody_properties(
        {
            "mass_kg": 374.0,
            "diameter_m": 0.5,
            "length_m": 2.86,
            "lift_area_scale": 1.0,
            "stabilizer_lever_m": 1.2,
            "axial_coefficient": 0.2,
            "normal_coefficient": 2.2,
            "normal_aoa_limit": 1.0,
            "aoa_drag_coefficient": 9.0,
        }
    )

    assert properties.mass_kg == 374.0
    assert properties.diameter_m == 0.5
    assert properties.length_m == 2.86
    assert properties.frontal_area_m2 == pytest.approx(0.19634954084936207)
    assert properties.lateral_area_m2 == pytest.approx(0.429)
    assert properties.stabilizer_lever_m == pytest.approx(1.2)
    assert properties.inertia_x_kg_m2 == pytest.approx(23.375)
    assert properties.inertia_y_kg_m2 == pytest.approx(260.7746333333333)
    assert properties.inertia_z_kg_m2 == properties.inertia_y_kg_m2
    assert properties.axial_coefficient == pytest.approx(0.2)
    assert properties.normal_coefficient == pytest.approx(2.2)
    assert properties.normal_aoa_limit == 1.0
    assert properties.aoa_drag_coefficient == 9.0
    assert properties.rotational_reference_m4 == pytest.approx(1.6060607069159519)


def test_catalog_retains_default_and_explicit_axial_coefficients() -> None:
    payload = load_catalog(CATALOG_PATH)

    assert payload["schema_version"] == CATALOG_SCHEMA_VERSION
    assert payload["profile_id"] == CATALOG_PROFILE_ID
    assert len(payload["records"]) == 437

    zb500 = payload["records"]["su_zb_500"]
    assert zb500["axial_coefficient"] == pytest.approx(
        OFFLINE_DEFAULT_AXIAL_COEFFICIENT
    )

    fab250 = payload["records"]["su_fab_250m_62"]
    assert fab250["axial_coefficient"] == pytest.approx(0.726074)


def test_catalog_alias_preserves_weapon_selector_identity() -> None:
    payload = load_catalog(CATALOG_PATH)

    assert payload["records"]["uk_500lb_mc_mk1_mk4_long_tail"]["aliases"] == [
        "uk_500lb_mc_mk1_mk4_long_tail_bomb"
    ]
