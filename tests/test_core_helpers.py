"""Behavioral coverage for the extracted core helper modules."""

import time

from bomana.core import ccrp_scheduler, diagnostics, lifecycle, navigation, timing_store
from bomana.core.state import Airfield, GameState, MapInfo, MapObjData, Phase, TelemetryData, Zone


def _valid_map_info() -> MapInfo:
    return MapInfo(
        valid=True,
        map_min=[0.0, 0.0],
        map_max=[2000.0, 1000.0],
        grid_size=[1.0, 1.0],
        grid_steps=[1.0, 1.0],
        grid_zero=[0.0, 0.0],
        fetch_time=time.time(),
    )


def test_navigation_helpers_preserve_scaled_distance_contract() -> None:
    scale = navigation.map_axis_scale_m(_valid_map_info())

    assert scale == (2000.0, 1000.0)
    bearing, distance_norm = navigation.bearing_distance_norm(0.0, 0.0, 0.5, -0.5, scale)

    assert round(bearing, 1) == 63.4
    assert round(distance_norm, 4) == 0.0112
    assert navigation.angle_delta_deg(350.0, 10.0) == 20.0


def test_timing_store_signature_is_stable_for_same_battle_context() -> None:
    mp = MapObjData(
        ok=True,
        zones=[Zone(id="zone-a", index=1, x=0.25, y=0.5, color="red")],
        airfields=[Airfield(id="af-a", index=1, x=0.1, y=0.2, color="blue", is_friendly=True)],
    )

    first = timing_store.build_battle_signature(_valid_map_info(), mp)
    second = timing_store.build_battle_signature(_valid_map_info(), mp)

    assert first is not None
    assert first == second
    assert timing_store.build_battle_signature(None, mp) is None


def test_lifecycle_helpers_update_life_and_landing_state() -> None:
    state = GameState()

    lifecycle.start_new_life(state, 100.0)
    assert state.current_life is not None
    assert state.current_life.life_index == 1
    assert state.sortie_id == 1
    assert state.last_player_present_ts == 100.0

    lifecycle.update_landing(
        state,
        TelemetryData(state_resp_ok=True, ias_kmh=0.0, vy_ms=0.0),
        101.0,
    )
    assert state.landing_start_time == 101.0
    lifecycle.clear_transient_state(state)
    assert state.landing_start_time is None

    lifecycle.reset_life_state(state)
    assert state.current_life is None
    assert state.sortie_id == 0
    assert state.map_info is None


def test_ccrp_scheduler_applies_and_rejects_results() -> None:
    state = GameState(phase=Phase.ALIVE)

    ccrp_scheduler.apply_bombing_calculation(
        state,
        {
            "flight_time": 3.2,
            "bomb_range_m": 450.0,
            "release_distance_m": 120.0,
            "time_to_release": 0.8,
            "release_status": "ready",
            "target_distance_m": 570.0,
        },
    )

    assert state.bombing_calc_valid is True
    assert state.cached_bomb_flight_time == 3.2
    assert state.cached_release_status == "ready"

    state.cached_bombing_unavailable_reason = ""
    ccrp_scheduler.apply_bombing_calculation(state, None)

    assert state.bombing_calc_valid is False
    assert state.cached_bombing_unavailable_reason == "calc_failed"
    assert (
        ccrp_scheduler.estimate_release_mach(TelemetryData(mach=None, tas_kmh=1225.0), 0.0) == 1.0
    )


def test_diagnostics_helpers_count_and_throttle_endpoint_events() -> None:
    state = GameState()
    events: list[tuple[str, dict]] = []

    diagnostics.record_endpoint_diagnostic(
        state,
        False,
        "map_failure_streak",
        "map_failure_count",
    )
    assert state.map_failure_streak == 1
    assert state.map_failure_count == 1

    endpoint_state: dict[str, int] = {}

    def log(name: str, **payload) -> None:
        events.append((name, payload))

    diagnostics.emit_endpoint_diagnostic(
        endpoint_state,
        log,
        endpoint="/map_obj.json",
        ok=False,
        error_kind="timeout",
        elapsed_ms=12.0,
        failure_streak=1,
    )
    diagnostics.emit_endpoint_diagnostic(
        endpoint_state,
        log,
        endpoint="/map_obj.json",
        ok=True,
        error_kind="",
        elapsed_ms=2.0,
        failure_streak=0,
    )

    assert events[0][0] == "endpoint_failed"
    assert events[0][1]["error_kind"] == "timeout"
    assert events[1][0] == "endpoint_recovered"
    assert events[1][1]["previous_failure_streak"] == 1
