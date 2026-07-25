import math

import pytest

from bomana.core.release_observation import (
    MANEUVER_PRECISION_GATE_THRESHOLD,
    resolve_release_observation,
)
from bomana.core.state import TelemetryData, ZoneNavigationState


def _telemetry(**overrides) -> TelemetryData:
    values = {
        "altitude_m": 1200.0,
        "tas_kmh": 720.0,
        "vy_ms": 10.0,
        "mach": 0.60,
    }
    values.update(overrides)
    return TelemetryData(**values)


def test_missing_optional_dynamics_preserves_axial_fallback() -> None:
    observation = resolve_release_observation(
        _telemetry(),
        ZoneNavigationState(),
        state_age_s=0.10,
        altitude_datum_m=60.0,
    )

    assert observation is not None
    assert observation.altitude_m == pytest.approx(1201.0)
    assert observation.initial_vz_ms == pytest.approx(10.0)
    assert observation.initial_aoa_deg is None
    assert observation.tas_ms == pytest.approx(200.0)
    assert observation.horizontal_air_speed_ms == pytest.approx(math.sqrt(200.0**2 - 10.0**2))
    assert observation.release_state_source == "8111_basic_release_state"
    assert not observation.precision_gate_available
    assert not observation.unresolved_dynamics


def test_causal_rates_gate_but_do_not_extrapolate_release_velocity() -> None:
    observation = resolve_release_observation(
        _telemetry(
            tas_acceleration_ms2=4.0,
            vertical_acceleration_ms2=2.0,
            aoa_deg=3.0,
            aos_deg=0.0,
            normal_load_factor=1.0,
            angular_velocity_x=0.0,
        ),
        ZoneNavigationState(),
        state_age_s=0.10,
        altitude_datum_m=60.0,
    )

    assert observation is not None
    assert observation.altitude_projection_m == pytest.approx(1.0)
    assert observation.altitude_m == pytest.approx(1201.0)
    assert observation.tas_projection_ms == pytest.approx(0.0)
    assert observation.tas_ms == pytest.approx(200.0)
    assert observation.initial_vz_ms == pytest.approx(10.0)
    assert observation.initial_aoa_deg == pytest.approx(3.0)
    assert observation.vertical_acceleration_ms2 == pytest.approx(2.0)
    assert observation.release_state_source == "8111_dynamics_gated"
    assert observation.precision_gate_available


def test_ny_and_attitude_supply_bounded_vertical_acceleration() -> None:
    observation = resolve_release_observation(
        _telemetry(
            aoa_deg=2.9,
            aos_deg=0.0,
            normal_load_factor=1.2,
            angular_velocity_x=0.0,
            attitude_pitch_deg=-5.8,
            attitude_pitch_present=True,
            attitude_roll_deg=0.0,
            attitude_roll_present=True,
        ),
        ZoneNavigationState(),
        state_age_s=0.10,
        altitude_datum_m=60.0,
    )

    assert observation is not None
    assert observation.vertical_acceleration_ms2 is not None
    assert 1.0 < observation.vertical_acceleration_ms2 < 2.0
    assert observation.initial_vz_ms == pytest.approx(10.0)
    assert observation.release_state_source == "8111_dynamics_gated"


def test_complete_high_dynamics_state_fails_precision_gate() -> None:
    nav = ZoneNavigationState(
        release_body_heading_rate_deg_s=30.0,
        release_body_heading_rate_available=True,
    )
    observation = resolve_release_observation(
        _telemetry(
            aoa_deg=4.0,
            aos_deg=8.0,
            normal_load_factor=1.1,
            angular_velocity_x=5.0,
        ),
        nav,
        state_age_s=0.0,
        altitude_datum_m=60.0,
    )

    assert observation is not None
    assert observation.maneuver_score > MANEUVER_PRECISION_GATE_THRESHOLD
    assert observation.precision_gate_available
    assert observation.unresolved_dynamics


@pytest.mark.parametrize(
    ("pitch_deg", "aoa_deg", "load_factor", "elevator_pct", "vy_ms"),
    (
        (-62.0, 24.0, 0.35, -100.0, -120.0),
        (38.0, 18.0, 4.5, 100.0, 80.0),
    ),
)
def test_longitudinal_dive_or_pull_up_does_not_trip_lateral_gate(
    pitch_deg: float,
    aoa_deg: float,
    load_factor: float,
    elevator_pct: float,
    vy_ms: float,
) -> None:
    observation = resolve_release_observation(
        _telemetry(
            vy_ms=vy_ms,
            aoa_deg=aoa_deg,
            aos_deg=0.2,
            normal_load_factor=load_factor,
            angular_velocity_x=2.0,
            attitude_pitch_deg=pitch_deg,
            attitude_pitch_present=True,
            attitude_roll_deg=3.0,
            attitude_roll_present=True,
            elevator_pct=elevator_pct,
            vertical_acceleration_ms2=35.0,
        ),
        ZoneNavigationState(),
        state_age_s=0.0,
        altitude_datum_m=60.0,
    )

    assert observation is not None
    assert observation.precision_gate_available
    assert not observation.unresolved_dynamics
    assert observation.maneuver_score < MANEUVER_PRECISION_GATE_THRESHOLD
