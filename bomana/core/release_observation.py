"""Resolve a common-time bomb release observation from official 8111 fields."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from bomana.core.atmosphere import dagor_speed_of_sound
from bomana.core.offline_ballistics_model import OFFLINE_GRAVITY_MS2
from bomana.core.state import TelemetryData, ZoneNavigationState

MANEUVER_PRECISION_GATE_THRESHOLD: Final = 1.0
LARGE_BANK_ANGLE_DEG: Final = 50.0
LARGE_SIDESLIP_ANGLE_DEG: Final = 12.0
LARGE_BODY_HEADING_RATE_DEG_S: Final = 12.0
LARGE_ROLL_RATE_DEG_S: Final = 60.0
MAX_PROJECTED_ACCELERATION_MS2: Final = 60.0
MAX_ACCELERATION_BLEND_DISAGREEMENT_MS2: Final = 20.0


@dataclass(frozen=True, slots=True)
class ReleaseObservation:
    """One bounded, causal release state aligned to the common solution time."""

    altitude_m: float
    tas_ms: float
    horizontal_air_speed_ms: float
    initial_vz_ms: float | None
    initial_aoa_deg: float | None
    altitude_projection_m: float
    tas_projection_ms: float
    vertical_acceleration_ms2: float | None
    release_state_source: str
    maneuver_score: float
    precision_gate_available: bool
    unresolved_dynamics: bool
    mach_consistency_error: float | None


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _angle_distance_deg(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _load_derived_vertical_acceleration(
    tel: TelemetryData,
    *,
    tas_ms: float,
    vertical_speed_ms: float | None,
) -> float | None:
    """Project aircraft-normal load into world vertical acceleration."""

    ny = _finite(tel.normal_load_factor)
    aoa = _finite(tel.aoa_deg)
    pitch = _finite(tel.attitude_pitch_deg) if tel.attitude_pitch_present else None
    lateral = (
        _finite(tel.attitude_lateral_deg)
        if tel.attitude_roll_present or tel.attitude_bank_present
        else None
    )
    if (
        ny is None
        or aoa is None
        or pitch is None
        or lateral is None
        or vertical_speed_ms is None
        or tas_ms <= 0.0
    ):
        return None

    flight_path_deg = math.degrees(math.asin(_clamp(vertical_speed_ms / tas_ms, -1.0, 1.0)))
    expected_pitch_deg = flight_path_deg + aoa
    # Some 8111 cockpits report aviahorizon_pitch with the opposite sign.
    physical_pitch_deg = min(
        (pitch, -pitch),
        key=lambda candidate: _angle_distance_deg(candidate, expected_pitch_deg),
    )
    vertical_acceleration = (
        OFFLINE_GRAVITY_MS2
        * ny
        * math.cos(math.radians(physical_pitch_deg))
        * math.cos(math.radians(lateral))
        - OFFLINE_GRAVITY_MS2
    )
    return vertical_acceleration if math.isfinite(vertical_acceleration) else None


def _resolved_vertical_acceleration(
    tel: TelemetryData,
    *,
    tas_ms: float,
    vertical_speed_ms: float | None,
) -> float | None:
    direct = _finite(tel.vertical_acceleration_ms2)
    load_derived = _load_derived_vertical_acceleration(
        tel,
        tas_ms=tas_ms,
        vertical_speed_ms=vertical_speed_ms,
    )
    if direct is not None and load_derived is not None:
        if abs(direct - load_derived) <= MAX_ACCELERATION_BLEND_DISAGREEMENT_MS2:
            resolved = 0.5 * (direct + load_derived)
        else:
            # Vy is already in the world vertical frame, so its causal
            # derivative wins when attitude/load conventions disagree.
            resolved = direct
    else:
        resolved = direct if direct is not None else load_derived
    if resolved is None:
        return None
    return _clamp(
        resolved,
        -MAX_PROJECTED_ACCELERATION_MS2,
        MAX_PROJECTED_ACCELERATION_MS2,
    )


def _maneuver_score(
    tel: TelemetryData,
    nav: ZoneNavigationState,
    *,
    aligned_altitude_m: float,
    aligned_tas_ms: float,
    altitude_datum_m: float,
    state_age_s: float,
    vertical_acceleration_ms2: float | None,
) -> tuple[float, bool, float | None]:
    components: list[float] = []

    def add(value: object, limit: float) -> None:
        parsed = _finite(value)
        if parsed is not None:
            components.append(abs(parsed) / limit)

    # CCRP remains available during steep but laterally stable dives and
    # pull-ups. Only strong lateral attitude or turn evidence pauses it.
    if tel.attitude_roll_present or tel.attitude_bank_present:
        add(tel.attitude_lateral_deg, LARGE_BANK_ANGLE_DEG)
    add(tel.aos_deg, LARGE_SIDESLIP_ANGLE_DEG)
    add(tel.angular_velocity_x, LARGE_ROLL_RATE_DEG_S)
    if nav.release_body_heading_rate_available:
        add(nav.release_body_heading_rate_deg_s, LARGE_BODY_HEADING_RATE_DEG_S)

    mach_consistency_error = None
    mach = _finite(tel.mach)
    if mach is not None and mach > 0.05 and aligned_tas_ms > 10.0:
        mach_rate = _finite(tel.mach_rate_per_s) or 0.0
        aligned_mach = mach + _clamp(mach_rate, -0.5, 0.5) * state_age_s
        try:
            expected_mach = aligned_tas_ms / dagor_speed_of_sound(
                aligned_altitude_m + altitude_datum_m
            )
        except ValueError:
            expected_mach = math.nan
        if math.isfinite(expected_mach):
            mach_consistency_error = abs(aligned_mach - expected_mach)

    lateral_dynamics = (
        _finite(tel.aos_deg),
        _finite(tel.angular_velocity_x),
        (
            _finite(tel.attitude_lateral_deg)
            if tel.attitude_roll_present or tel.attitude_bank_present
            else None
        ),
        (
            _finite(nav.release_body_heading_rate_deg_s)
            if nav.release_body_heading_rate_available
            else None
        ),
    )
    precision_gate_available = any(value is not None for value in lateral_dynamics)
    return (
        max(components, default=0.0),
        precision_gate_available,
        mach_consistency_error,
    )


def resolve_release_observation(
    tel: TelemetryData,
    nav: ZoneNavigationState,
    *,
    state_age_s: float,
    altitude_datum_m: float,
) -> ReleaseObservation | None:
    """Align all ballistically relevant 8111 release fields without look-ahead."""

    raw_altitude_m = _finite(tel.altitude_m)
    raw_tas_ms = tas_kmh / 3.6 if (tas_kmh := _finite(tel.tas_kmh)) is not None else None
    vertical_speed_ms = _finite(tel.vy_ms)
    age = _finite(state_age_s)
    datum = _finite(altitude_datum_m)
    if raw_altitude_m is None or raw_tas_ms is None or age is None or datum is None or age < 0.0:
        return None

    vertical_acceleration = _resolved_vertical_acceleration(
        tel,
        tas_ms=raw_tas_ms,
        vertical_speed_ms=vertical_speed_ms,
    )
    # Capture validation rejected first-difference TAS/Vy extrapolation. Keep
    # the rates as maneuver evidence, while retaining the proven H + Vy*dt
    # common-time alignment and zero-order velocity hold.
    altitude_projection_m = (vertical_speed_ms or 0.0) * age
    altitude_m = raw_altitude_m + altitude_projection_m

    tas_projection_ms = 0.0
    aligned_tas_ms = raw_tas_ms
    aligned_vertical_speed = vertical_speed_ms

    vertical_speed_for_magnitude = aligned_vertical_speed or 0.0
    horizontal_air_speed_sq = aligned_tas_ms**2 - vertical_speed_for_magnitude**2
    if (
        not 50.0 < altitude_m <= 30_000.0
        or aligned_tas_ms < 10.0
        or horizontal_air_speed_sq <= 100.0
    ):
        return None

    maneuver_score, gate_available, mach_error = _maneuver_score(
        tel,
        nav,
        aligned_altitude_m=altitude_m,
        aligned_tas_ms=aligned_tas_ms,
        altitude_datum_m=datum,
        state_age_s=age,
        vertical_acceleration_ms2=vertical_acceleration,
    )
    source = "8111_dynamics_gated" if gate_available else "8111_basic_release_state"

    return ReleaseObservation(
        altitude_m=altitude_m,
        tas_ms=aligned_tas_ms,
        horizontal_air_speed_ms=math.sqrt(horizontal_air_speed_sq),
        initial_vz_ms=aligned_vertical_speed,
        initial_aoa_deg=_finite(tel.aoa_deg),
        altitude_projection_m=altitude_projection_m,
        tas_projection_ms=tas_projection_ms,
        vertical_acceleration_ms2=vertical_acceleration,
        release_state_source=source,
        maneuver_score=maneuver_score,
        precision_gate_available=gate_available,
        unresolved_dynamics=(gate_available and maneuver_score > MANEUVER_PRECISION_GATE_THRESHOLD),
        mach_consistency_error=mach_error,
    )


__all__ = [
    "LARGE_BANK_ANGLE_DEG",
    "LARGE_BODY_HEADING_RATE_DEG_S",
    "LARGE_ROLL_RATE_DEG_S",
    "LARGE_SIDESLIP_ANGLE_DEG",
    "MANEUVER_PRECISION_GATE_THRESHOLD",
    "ReleaseObservation",
    "resolve_release_observation",
]
