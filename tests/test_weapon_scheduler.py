"""Prepare/compute/apply contract tests for weapon fire control."""

import math
from copy import deepcopy

import pytest

from bomana.config.settings import WeaponBallisticModelConfig
from bomana.core.state import GameState, Phase, TelemetryData, WeaponTarget
from bomana.core.weapon_scheduler import (
    apply_weapon_calculation,
    compute_weapon_calculation,
    prepare_weapon_calculation,
)
from bomana.core.weapon_solver import WeaponSolution


def _powered(weapon_id: str = "agm") -> dict:
    return {
        "id": weapon_id,
        "display_name": "Test AGM",
        "display_name_zh": "测试 AGM",
        "role": "agm",
        "propulsion": "powered",
        "control": "guided",
        "planform": "normal",
        "mass_start_kg": 100.0,
        "mass_end_kg": 90.0,
        "caliber_m": 0.2,
        "cx_k": 0.2,
        "time_life_s": 20.0,
        "start_speed_mps": 0.0,
        "min_distance_m": 100.0,
        "hard_max_distance_m": 10000.0,
        "max_speed_mps": 600.0,
        "motor_stages": [{"duration_s": 3.0, "thrust_n": 5000.0, "mass_end_kg": 90.0}],
    }


def _freefall() -> dict:
    return {
        "id": "su_fab100",
        "display_name": "FAB-100",
        "display_name_zh": "FAB-100",
        "role": "bomb",
        "propulsion": "unpowered",
        "control": "unguided",
        "planform": "normal",
    }


class FakeCatalog:
    def __init__(self):
        self.records = {"agm": _powered(), "su_fab100": _freefall()}
        self.selected_weapon_id = "agm"
        self.selection_source = "manual"

    def get(self, weapon_id):
        value = self.records.get(weapon_id)
        return deepcopy(value) if value else None

    def compatible(self, weapon_id, aircraft):
        return weapon_id in self.records and aircraft == "test_plane"

    def set_selected(self, weapon_id, source="manual"):
        if weapon_id not in self.records:
            return False
        self.selected_weapon_id = weapon_id
        self.selection_source = source
        return True


class FixedSolver:
    def solve(self, _weapon, **inputs):
        return WeaponSolution(
            valid=True,
            status="in_envelope",
            quality="two_dimensional",
            model=WeaponBallisticModelConfig.selected_model,
            reason="test_solution",
            target_kind=inputs["target_kind"],
            target_name=inputs["target_name"],
            target_distance_m=inputs["target_distance_m"],
            min_range_m=100.0,
            max_range_m=5000.0,
            rear_range_m=3000.0,
            head_range_m=8000.0,
            target_aspect_cosine=inputs.get("target_aspect_cosine"),
            time_to_target_s=8.0,
        )


def _alive_state() -> GameState:
    state = GameState(phase=Phase.ALIVE)
    state.zone_nav.ground_speed = 250.0 / (100.0 * 1000.0)
    return state


def _telemetry() -> TelemetryData:
    return TelemetryData(
        ind_ok=True,
        state_resp_ok=True,
        valid=True,
        type_name="test_plane",
        ias_kmh=720.0,
        tas_kmh=900.0,
        altitude_m=2000.0,
        mach=0.82,
    )


def _target(target_id="zone-a", distance=2000.0, relative=2.0) -> WeaponTarget:
    return WeaponTarget(
        id=target_id,
        kind="zone",
        name="Zone A",
        distance_m=distance,
        relative_deg=relative,
    )


def test_prepare_compute_apply_projects_solution_into_state() -> None:
    catalog = FakeCatalog()
    state = _alive_state()
    target = _target()

    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=target,
        catalog=catalog,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=FixedSolver())
    assert apply_weapon_calculation(state, result, catalog=catalog)

    assert state.weapon_id == "agm"
    assert state.weapon_display_name == "测试 AGM"
    assert state.weapon_selection_source == "manual"
    assert state.weapon_selection_compatible
    assert state.weapon_solution_valid
    assert state.weapon_status == "in_envelope"
    assert state.weapon_quality == "two_dimensional"
    assert state.weapon_model == WeaponBallisticModelConfig.DEFAULT_MODEL
    assert state.weapon_target_name == "Zone A"
    assert state.weapon_max_range_m == 5000.0
    assert state.weapon_rear_range_m == 3000.0
    assert state.weapon_head_range_m == 8000.0


def test_prepare_separates_launch_speed_from_aligned_ground_closing_speed() -> None:
    catalog = FakeCatalog()
    state = _alive_state()

    aligned = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=_target(),
        catalog=catalog,
    )
    assert aligned is not None
    assert aligned["launch_speed_mps"] == 250.0
    assert aligned["launch_mach"] == pytest.approx(0.82)
    assert aligned["ground_closing_speed_mps"] == pytest.approx(250.0 * math.cos(math.radians(2.0)))

    off_axis = _target(target_id="zone-b", relative=20.0)
    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.3,
        player_present=True,
        target=off_axis,
        catalog=catalog,
    )
    assert work is not None
    assert work["launch_speed_mps"] == 250.0
    assert work["ground_closing_speed_mps"] is None


def test_apply_rejects_selection_changed_while_compute_was_outside_lock() -> None:
    catalog = FakeCatalog()
    state = _alive_state()
    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=_target(),
        catalog=catalog,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=FixedSolver())
    catalog.set_selected("su_fab100")

    assert not apply_weapon_calculation(state, result, catalog=catalog)
    assert state.weapon_id == ""


def test_apply_rejects_ballistic_model_changed_while_compute_was_outside_lock(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        WeaponBallisticModelConfig,
        "selected_model",
        WeaponBallisticModelConfig.FOXTHREE_COMPATIBLE,
    )
    catalog = FakeCatalog()
    state = _alive_state()
    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=_target(),
        catalog=catalog,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=FixedSolver())
    WeaponBallisticModelConfig.set_selected(WeaponBallisticModelConfig.STRICT_OFFICIAL)

    assert not apply_weapon_calculation(state, result, catalog=catalog)
    assert state.weapon_id == ""


def test_apply_rejects_solution_computed_under_a_different_model(monkeypatch) -> None:
    monkeypatch.setattr(
        WeaponBallisticModelConfig,
        "selected_model",
        WeaponBallisticModelConfig.FOXTHREE_COMPATIBLE,
    )
    catalog = FakeCatalog()
    state = _alive_state()
    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=_target(),
        catalog=catalog,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=FixedSolver())
    result["solution"] = WeaponSolution(
        valid=True,
        status="in_envelope",
        quality="two_dimensional",
        model=WeaponBallisticModelConfig.STRICT_OFFICIAL,
    )

    assert not apply_weapon_calculation(state, result, catalog=catalog)
    assert state.weapon_id == ""


def test_apply_rejects_target_changed_while_compute_was_outside_lock() -> None:
    catalog = FakeCatalog()
    state = _alive_state()
    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=_target(),
        catalog=catalog,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=FixedSolver())
    state.weapon_target = _target(target_id="zone-b", distance=2500.0)

    assert not apply_weapon_calculation(state, result, catalog=catalog)
    assert state.weapon_id == ""


def test_apply_rejects_air_target_aspect_changed_while_compute_was_outside_lock() -> None:
    catalog = FakeCatalog()
    catalog.records["agm"] = dict(catalog.records["agm"], role="aam")
    state = _alive_state()
    target = WeaponTarget(
        id="hostile-1",
        kind="aircraft",
        name="Hostile",
        distance_m=20_000.0,
        aspect_cosine=-1.0,
    )
    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=target,
        catalog=catalog,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=FixedSolver())
    state.weapon_target = WeaponTarget(
        id="hostile-1",
        kind="aircraft",
        name="Hostile",
        distance_m=20_000.0,
        aspect_cosine=1.0,
    )

    assert not apply_weapon_calculation(state, result, catalog=catalog)
    assert state.weapon_id == ""


def test_disappeared_air_contact_bypasses_throttle_and_clears_valid_cue() -> None:
    catalog = FakeCatalog()
    catalog.records["agm"] = dict(catalog.records["agm"], role="aam")
    state = _alive_state()
    state.last_weapon_calc_time = 10.0
    state.weapon_target = WeaponTarget(
        id="hostile-1",
        kind="aircraft",
        name="Hostile",
        distance_m=2000.0,
    )
    state.weapon_solution_valid = True
    state.weapon_status = "in_envelope"

    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        10.05,
        player_present=True,
        target=None,
        catalog=catalog,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=FixedSolver())
    assert apply_weapon_calculation(state, result, catalog=catalog)

    assert state.weapon_target is None
    assert state.weapon_status == "no_target"
    assert not state.weapon_solution_valid


def test_missing_ccrp_physics_fails_closed_in_weapon_status() -> None:
    catalog = FakeCatalog()
    catalog.set_selected("su_fab100")
    state = _alive_state()

    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=_target(),
        catalog=catalog,
        ccrp_supported=False,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=FixedSolver())
    assert apply_weapon_calculation(state, result, catalog=catalog)

    assert state.weapon_status == "insufficient_data"
    assert state.weapon_reason == "ccrp_physics_unavailable"
    assert not state.weapon_solution_valid


def test_missing_target_fails_closed_without_invoking_solver() -> None:
    class MustNotRun:
        def solve(self, *_args, **_kwargs):
            raise AssertionError("no-target work must not enter the numerical solver")

    catalog = FakeCatalog()
    state = _alive_state()
    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=None,
        catalog=catalog,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=MustNotRun())

    assert apply_weapon_calculation(state, result, catalog=catalog)
    assert state.weapon_status == "no_target"
    assert not state.weapon_solution_valid


def test_freefall_routes_to_ccrp_without_invoking_weapon_solver() -> None:
    class MustNotRun:
        def solve(self, *_args, **_kwargs):
            raise AssertionError("free-fall bombs stay on CCRP")

    catalog = FakeCatalog()
    catalog.set_selected("su_fab100")
    state = _alive_state()
    work = prepare_weapon_calculation(
        state,
        _telemetry(),
        1.0,
        player_present=True,
        target=_target(),
        catalog=catalog,
    )
    assert work is not None
    result = compute_weapon_calculation(work, solver=MustNotRun())

    assert apply_weapon_calculation(state, result, catalog=catalog)
    assert state.weapon_status == "ccrp"
    assert not state.weapon_solution_valid
