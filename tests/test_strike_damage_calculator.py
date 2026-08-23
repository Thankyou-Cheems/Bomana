from __future__ import annotations

import pytest

from bomana.core.strike_damage_calculator import (
    StrikeDamageCalculator,
    StrikeDamageCalculatorError,
    airport_repair_per_visit,
    balance_level_from_room_max_br,
    mission_hp_from_tnte_kg,
    required_weapon_count,
    room_max_br_from_balance_level,
    valid_room_max_brs,
)
from bomana.core.strike_encyclopedia import load_strike_encyclopedia


def test_room_max_br_maps_to_exact_internal_max_rank() -> None:
    assert balance_level_from_room_max_br(1.0) == 0
    assert balance_level_from_room_max_br(2.0) == 3
    assert balance_level_from_room_max_br(2.3) == 4
    assert balance_level_from_room_max_br(3.7) == 8
    assert balance_level_from_room_max_br(14.7) == 41
    assert room_max_br_from_balance_level(41) == pytest.approx(14.7)
    assert valid_room_max_brs()[-1] == pytest.approx(14.7)


@pytest.mark.parametrize("room_max_br", [0.9, 14.5, 15.0])
def test_room_max_br_rejects_values_that_are_not_current_valid_ranks(
    room_max_br: float,
) -> None:
    with pytest.raises(StrikeDamageCalculatorError, match="invalid_room_max_br"):
        balance_level_from_room_max_br(room_max_br)


def test_gameparams_maps_one_kilogram_tnt_to_eight_mission_hp() -> None:
    assert mission_hp_from_tnte_kg(1.0, 0.000125) == pytest.approx(8.0)
    assert mission_hp_from_tnte_kg(272.43, 0.000125) == pytest.approx(2_179.44)
    assert required_weapon_count(25_900.0, 2_179.44) == 12
    assert required_weapon_count(23_310.0, 2_179.44) == 11


def test_bombing_point_exposes_exact_hp_and_inferred_fire_tail_separately() -> None:
    result = StrikeDamageCalculator(load_strike_encyclopedia()).calculate(
        room_max_br=14.7,
        target_kind="bombing_point",
        mission_mode="planes",
        weapon_id="us_1000lb_mk_83_ldgp",
    )

    assert result.balance_level == 41
    assert result.balance_level_range == (21, 50)
    assert result.target_mission_hp == pytest.approx(25_900.0)
    assert result.direct_damage_to_fire_reference == pytest.approx(23_310.0)
    assert result.fire_remaining_hp_reference == pytest.approx(2_590.0)
    assert result.fire_tail_evidence_kind == "static_parameter_inference"
    assert result.respawn_seconds == pytest.approx(240.0)
    assert result.target_evidence_kind == "exact_static_hp"
    assert result.damage_per_hit_mission_hp == pytest.approx(2_179.44)
    assert result.weapon_count == 12
    assert result.fire_trigger_weapon_count == 11
    assert result.quantity_evidence_kind == "exact_static_gameparams"
    assert result.quantity_is_exact is True


def test_helicopter_bombing_point_uses_one_tenth_hp_with_exact_count() -> None:
    result = StrikeDamageCalculator(load_strike_encyclopedia()).calculate(
        room_max_br=8.0,
        target_kind="bombing_point",
        mission_mode="heli",
        weapon_id="us_1000lb_mk_83_ldgp",
    )

    assert result.target_mission_hp == pytest.approx(2_590.0)
    assert result.weapon_count == 2
    assert result.fire_trigger_weapon_count == 2
    assert result.quantity_evidence_kind == "exact_static_gameparams"


@pytest.mark.parametrize(
    ("module_id", "expected_hp", "expected_count"),
    [
        ("airfield", 280_000.0, 129),
        ("storage", 160_000.0, 74),
        ("parking", 160_000.0, 74),
        ("dwelling", 160_000.0, 74),
    ],
)
def test_airport_modules_use_exact_tnt_counts_without_fire_tail(
    module_id: str,
    expected_hp: float,
    expected_count: int,
) -> None:
    result = StrikeDamageCalculator(load_strike_encyclopedia()).calculate(
        room_max_br=14.7,
        target_kind="airport_module",
        airport_module=module_id,
        weapon_id="us_1000lb_mk_83_ldgp",
    )

    assert result.target_mission_hp == pytest.approx(expected_hp)
    assert result.direct_damage_to_fire_reference is None
    assert result.fire_tail_evidence_kind is None
    assert result.respawn_seconds is None
    assert result.weapon_count == expected_count
    assert result.fire_trigger_weapon_count is None
    assert result.quantity_evidence_kind == "exact_static_gameparams"
    assert result.quantity_is_exact is True


@pytest.mark.parametrize(
    ("weapon_id", "destroy_count", "fire_count"),
    [
        ("us_500lb_mk_82_ldgp", 28, 25),
        ("su_fab_500m_62t", 10, 9),
    ],
)
def test_other_he_bombs_use_the_same_static_tnt_conversion(
    weapon_id: str,
    destroy_count: int,
    fire_count: int,
) -> None:
    result = StrikeDamageCalculator(load_strike_encyclopedia()).calculate(
        room_max_br=14.7,
        target_kind="bombing_point",
        mission_mode="planes",
        weapon_id=weapon_id,
    )

    assert result.weapon_count == destroy_count
    assert result.fire_trigger_weapon_count == fire_count
    assert result.quantity_is_exact is True


def test_napalm_does_not_use_the_tnt_equivalent_bombing_zone_formula() -> None:
    result = StrikeDamageCalculator(load_strike_encyclopedia()).calculate(
        room_max_br=14.7,
        target_kind="bombing_point",
        mission_mode="planes",
        weapon_id="us_500lb_mk77_mod4",
    )

    assert result.weapon_count is None
    assert result.fire_trigger_weapon_count is None
    assert result.damage_per_hit_mission_hp is None
    assert result.quantity_evidence_kind == "native_unknown"
    assert result.quantity_is_exact is False


def test_airport_repair_formula_reports_hp_per_visit_and_stops_at_both_boundaries() -> None:
    encyclopedia = load_strike_encyclopedia()
    tier = encyclopedia.airport_tiers[-1]

    assert airport_repair_per_visit(tier, dwelling_remaining_hp=0.0) == 0.0
    assert airport_repair_per_visit(tier, dwelling_remaining_hp=160_000.0) == 0.0
    assert airport_repair_per_visit(tier, dwelling_remaining_hp=1.0) == pytest.approx(400.0)
    assert airport_repair_per_visit(tier, dwelling_remaining_hp=79_999.0) == pytest.approx(2_000.0)
    assert airport_repair_per_visit(tier, dwelling_remaining_hp=159_999.0) == pytest.approx(4_000.0)


def test_unknown_weapon_is_rejected_instead_of_fabricating_damage() -> None:
    calculator = StrikeDamageCalculator(load_strike_encyclopedia())
    with pytest.raises(StrikeDamageCalculatorError, match="unknown_weapon"):
        calculator.calculate(
            room_max_br=14.7,
            target_kind="bombing_point",
            weapon_id="not-a-real-weapon",
        )
