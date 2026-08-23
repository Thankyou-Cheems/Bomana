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


def test_gameparams_linear_tnt_map_is_not_the_hangar_formula() -> None:
    assert mission_hp_from_tnte_kg(1.0, 0.000125) == pytest.approx(8.0)
    assert mission_hp_from_tnte_kg(272.43, 0.000125) == pytest.approx(2_179.44)
    assert required_weapon_count(25_900.0, 2_179.44) == 12


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
    assert result.damage_per_hit_mission_hp == pytest.approx(4_720.376)
    assert result.weapon_count == 6
    assert result.fire_trigger_weapon_count == 5
    assert result.quantity_evidence_kind == "exact_static_splash_curve"
    assert result.quantity_is_exact is True
    assert result.reduced_for_armor is False


def test_helicopter_bombing_point_uses_one_tenth_hp_with_exact_count() -> None:
    result = StrikeDamageCalculator(load_strike_encyclopedia()).calculate(
        room_max_br=8.0,
        target_kind="bombing_point",
        mission_mode="heli",
        weapon_id="us_1000lb_mk_83_ldgp",
    )

    assert result.target_mission_hp == pytest.approx(2_590.0)
    assert result.weapon_count == 1
    assert result.fire_trigger_weapon_count == 1
    assert result.quantity_evidence_kind == "exact_static_splash_curve"


@pytest.mark.parametrize(
    ("module_id", "expected_hp", "expected_count"),
    [
        ("airfield", 280_000.0, 60),
        ("storage", 160_000.0, 34),
        ("parking", 160_000.0, 34),
        ("dwelling", 160_000.0, 34),
    ],
)
def test_airport_modules_use_splash_hp_without_fire_tail(
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
    assert result.quantity_evidence_kind == "exact_static_splash_curve"
    assert result.quantity_is_exact is True


@pytest.mark.parametrize(
    ("weapon_id", "destroy_count", "fire_count"),
    [
        ("us_500lb_mk_82_ldgp", 11, 10),
        ("su_fab_500m_62t", 5, 4),
    ],
)
def test_other_he_bombs_use_the_same_splash_curve(
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
    assert result.quantity_evidence_kind == "exact_static_splash_curve"


def test_air_to_ground_rockets_and_missiles_use_the_splash_curve() -> None:
    calculator = StrikeDamageCalculator(load_strike_encyclopedia())
    hydra = calculator.calculate(
        room_max_br=14.7,
        target_kind="bombing_point",
        mission_mode="planes",
        weapon_id="us_hydra_70_m247",
    )
    maverick = calculator.calculate(
        room_max_br=14.7,
        target_kind="bombing_point",
        mission_mode="planes",
        weapon_id="us_agm_65d",
    )

    assert hydra.quantity_is_exact is True
    assert hydra.reduced_for_armor is True
    assert hydra.weapon_count == 246
    assert maverick.quantity_is_exact is True
    assert maverick.reduced_for_armor is False
    assert maverick.weapon_count == 17


def test_nuclear_yield_destroys_high_tier_base_in_one_hit() -> None:
    result = StrikeDamageCalculator(load_strike_encyclopedia()).calculate(
        room_max_br=14.7,
        target_kind="bombing_point",
        mission_mode="planes",
        weapon_id="us_b61_5kt",
    )

    assert result.weapon_count == 1
    assert result.fire_trigger_weapon_count == 1
    assert result.quantity_is_exact is True
    assert result.quantity_evidence_kind == "exact_static_nuclear_yield"
    assert result.damage_per_hit_mission_hp == pytest.approx(200_000.0)


def test_napalm_uses_splash_and_fire_inputs() -> None:
    result = StrikeDamageCalculator(load_strike_encyclopedia()).calculate(
        room_max_br=14.7,
        target_kind="bombing_point",
        mission_mode="planes",
        weapon_id="us_500lb_mk77_mod4",
    )

    assert result.damage_per_hit_mission_hp == pytest.approx(10_860.0)
    assert result.weapon_count == 3
    assert result.fire_trigger_weapon_count == 3
    assert result.quantity_evidence_kind == "exact_static_napalm_splash_fire"
    assert result.quantity_is_exact is True


def test_airport_repair_formula_reports_hp_per_visit_and_stops_at_both_boundaries() -> None:
    encyclopedia = load_strike_encyclopedia()
    tier = encyclopedia.airport_tiers[-1]

    assert airport_repair_per_visit(tier, dwelling_remaining_hp=0.0) == 0.0
    assert airport_repair_per_visit(tier, dwelling_remaining_hp=160_000.0) == 0.0
    assert airport_repair_per_visit(tier, dwelling_remaining_hp=1.0) == pytest.approx(400.0)
    assert airport_repair_per_visit(tier, dwelling_remaining_hp=79_999.0) == pytest.approx(2_000.0)
    assert airport_repair_per_visit(tier, dwelling_remaining_hp=159_999.0) == pytest.approx(4_000.0)


def test_warheads_without_splash_inputs_stay_native_unknown() -> None:
    result = StrikeDamageCalculator(load_strike_encyclopedia()).calculate(
        room_max_br=14.7,
        target_kind="bombing_point",
        mission_mode="planes",
        weapon_id="jp_ki_148_i_go_1b_event_broken_warhead",
    )

    assert result.weapon_count is None
    assert result.quantity_is_exact is False
    assert result.quantity_evidence_kind == "native_unknown"


def test_unknown_weapon_is_rejected_instead_of_fabricating_damage() -> None:
    calculator = StrikeDamageCalculator(load_strike_encyclopedia())
    with pytest.raises(StrikeDamageCalculatorError, match="unknown_weapon"):
        calculator.calculate(
            room_max_br=14.7,
            target_kind="bombing_point",
            weapon_id="not-a-real-weapon",
        )
