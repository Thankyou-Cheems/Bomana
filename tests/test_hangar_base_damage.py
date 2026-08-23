from __future__ import annotations

import pytest

from bomana.core.hangar_base_damage import (
    HangarDamageInputs,
    evaluate_hangar_base_damage,
    hangar_reward_ui_value,
)
from bomana.core.strike_encyclopedia import load_strike_encyclopedia


def _model():
    return load_strike_encyclopedia().bombing_zone_splash


def _damage(**kwargs) -> float:
    breakdown = evaluate_hangar_base_damage(_model(), HangarDamageInputs(**kwargs))
    assert breakdown is not None
    return breakdown.damage


def test_splash_curve_matches_hangar_weapon_damage_for_mk82_mk83_mk84_and_sdb() -> None:
    mk82 = _damage(
        explosive_mass_kg=87.1,
        strength_equivalent=1.35,
        mission_damage_model="splash_tnte_curve",
    )
    mk83 = _damage(
        explosive_mass_kg=201.8,
        strength_equivalent=1.35,
        mission_damage_model="splash_tnte_curve",
    )
    mk84 = _damage(
        explosive_mass_kg=428.6,
        strength_equivalent=1.35,
        mission_damage_model="splash_tnte_curve",
    )
    gbu39 = _damage(
        explosive_mass_kg=16.3293,
        strength_equivalent=1.62,
        mission_damage_model="splash_tnte_curve",
    )

    assert mk82 == pytest.approx(2463.775)
    assert mk83 == pytest.approx(4720.376)
    assert mk84 == pytest.approx(10982.625)
    assert gbu39 == pytest.approx(1138.759, abs=0.01)
    assert round(mk82) == 2464
    assert round(mk83) == 4720
    assert round(mk84) == 10983


def test_underpenetrating_warheads_apply_bombing_zone_restrain() -> None:
    breakdown = evaluate_hangar_base_damage(
        _model(),
        HangarDamageInputs(
            explosive_mass_kg=0.4,
            strength_equivalent=1.0,
            mission_damage_model="splash_tnte_curve",
        ),
    )
    assert breakdown is not None
    assert breakdown.reduced_for_armor is True
    assert breakdown.penetration_mm is not None
    assert breakdown.penetration_mm < 25.0
    assert breakdown.damage == pytest.approx(190.0 * (breakdown.penetration_mm / 25.0) * 0.6)


def test_napalm_uses_splash_block_plus_fire_dot_not_tiny_tnt_strength() -> None:
    damage = _damage(
        explosive_mass_kg=207.3,
        strength_equivalent=0.002,
        splash_damage=14500.0,
        splash_penetration=20.0,
        splash_damage_type="napalm",
        fire_damage=10.0,
        fire_life_time=30.0,
        mission_damage_model="napalm_splash_fire",
    )
    assert damage == pytest.approx(10860.0)


def test_nuclear_yield_uses_yield_table() -> None:
    assert _damage(
        explosive_mass_kg=0.0,
        strength_equivalent=0.0,
        nuclear_yield_kt=5.0,
        mission_damage_model="nuclear_yield",
    ) == pytest.approx(200_000.0)
    assert _damage(
        explosive_mass_kg=0.0,
        strength_equivalent=0.0,
        nuclear_yield_kt=30.0,
        mission_damage_model="nuclear_yield",
    ) == pytest.approx(1_200_000.0)


def test_ten_mk82_crosses_high_tier_fire_but_two_jdam_plus_one_sdb_does_not() -> None:
    mk82 = _damage(
        explosive_mass_kg=87.1,
        strength_equivalent=1.35,
        mission_damage_model="splash_tnte_curve",
    )
    jdam = _damage(
        explosive_mass_kg=428.6,
        strength_equivalent=1.35,
        mission_damage_model="splash_tnte_curve",
    )
    sdb = _damage(
        explosive_mass_kg=16.3293,
        strength_equivalent=1.62,
        mission_damage_model="splash_tnte_curve",
    )
    fire_hp = 25_900.0 * 0.9
    ten_mk82 = 10 * mk82
    two_jdam_one_sdb = 2 * jdam + sdb
    two_jdam_two_sdb = two_jdam_one_sdb + sdb

    assert ten_mk82 == pytest.approx(24_637.75)
    assert pytest.approx(1_175.85) == 10 * 87.1 * 1.35
    assert ten_mk82 >= fire_hp
    assert two_jdam_one_sdb < fire_hp
    assert two_jdam_two_sdb >= fire_hp
    assert two_jdam_one_sdb == pytest.approx(23_104.0, abs=0.05)


def test_reward_ui_caps_at_ten_below_preset_minimum() -> None:
    model = _model()
    assert hangar_reward_ui_value(model, 5_000.0) == pytest.approx(10.0)
    over = hangar_reward_ui_value(model, 24_640.0)
    assert 7.0 < over < 10.0
    fighter = hangar_reward_ui_value(model, 24_640.0, is_fighter=True)
    assert fighter == pytest.approx(over * 0.8)
    assert hangar_reward_ui_value(model, 200_000.0) == pytest.approx(3.0)
