"""Versioned offline ballistic calculations used by CCRP.

This module is deliberately self-contained.  Runtime inputs are ordinary
numbers already obtained from official 8111 endpoints, selected-weapon static
metadata, and an optional local terrain-height callback.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from bomana.config.settings import BallisticPhysicsParams
from bomana.core.atmosphere import (
    DAGOR_STANDARD_DENSITY_KG_M3,
    dagor_speed_of_sound,
)
from bomana.core.offline_ballistics_model import (
    OFFLINE_STEP_SECONDS,
    resolve_offline_ballistics_model,
)
from bomana.core.offline_rigidbody_solver import (
    OfflineRigidbodyEnvironment,
    OfflineRigidbodySolverProperties,
    axial_drag_curve,
    integrate_pitch_projection_to_terrain,
)

TerrainAltitudeAtRange = Callable[[float], float | None]


def offline_speed_of_sound(world_altitude_m: float) -> float:
    """Compatibility name for the centralized complete Dagor atmosphere."""

    return dagor_speed_of_sound(world_altitude_m)


def _positive_finite(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return default
    return parsed if math.isfinite(parsed) and parsed > 0.0 else default


def _finite(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return default
    return parsed if math.isfinite(parsed) else default


def _resolved_sea_level_density(value: float | None) -> float:
    return _positive_finite(value, DAGOR_STANDARD_DENSITY_KG_M3)


def _calculate_rigidbody_projection_trajectory(
    *,
    release_altitude_m: float,
    velocity_x_ms: float,
    velocity_y_ms: float,
    initial_aoa_deg: float,
    fixed_target_altitude_m: float,
    altitude_datum_m: float,
    sea_level_density: float,
    terrain_altitude_at_range: TerrainAltitudeAtRange | None,
    properties: OfflineRigidbodySolverProperties,
) -> tuple[float, float, float]:
    """Project 8111 release observables into the offline rigid-body kernel."""

    body_angle = math.atan2(velocity_y_ms, velocity_x_ms) + math.radians(
        initial_aoa_deg
    )
    def world_terrain_altitude(horizontal_range_m: float) -> float | None:
        if terrain_altitude_at_range is None:
            altitude = fixed_target_altitude_m
        else:
            try:
                raw = terrain_altitude_at_range(horizontal_range_m)
            except (ArithmeticError, TypeError, ValueError):
                return None
            if raw is None:
                return None
            altitude = _finite(raw, default=math.nan)
        return (
            altitude + altitude_datum_m
            if math.isfinite(altitude)
            else None
        )

    impact = integrate_pitch_projection_to_terrain(
        release_world_altitude_m=release_altitude_m + altitude_datum_m,
        velocity_x_ms=velocity_x_ms,
        velocity_y_ms=velocity_y_ms,
        initial_body_angle_rad=body_angle,
        properties=properties,
        terrain_altitude_at_range=world_terrain_altitude,
        environment=OfflineRigidbodyEnvironment(
            sea_level_density_kg_m3=sea_level_density,
        ),
        max_time_seconds=float(BallisticPhysicsParams.MAX_FLIGHT_TIME),
        step_seconds=OFFLINE_STEP_SECONDS,
    )
    if impact is None:
        return 0.0, 0.0, 0.0
    return (
        impact.elapsed_seconds,
        max(0.0, impact.position_world_m.x),
        impact.linear_velocity_world_ms.magnitude(),
    )


def calculate_bomb_trajectory(
    release_alt_m: float,
    release_speed_ms: float,
    bomb_mass_kg: float = 0.0,
    bomb_bc: float = 0.0,
    target_alt_m: float = 0.0,
    dive_angle_deg: float = 0.0,
    initial_vz_ms: float | None = None,
    initial_aoa_deg: float | None = None,
    bomb_params: dict | None = None,
    atmosphere_altitude_datum_m: float = 0.0,
    air_density_sea_level: float | None = None,
    terrain_altitude_at_range: TerrainAltitudeAtRange | None = None,
) -> tuple[float, float, float]:
    """Integrate the offline rigid-body projection to terrain.

    The active reference solver is six-degree-of-freedom.  8111 does not expose
    a released store's quaternion or angular velocity, so every supported
    free-fall store uses the observable along-track plane reconstructed from
    8111 AoA and its own bundled static lift, inertia, stabilizer, and damping
    properties. The force/moment equations are shared with the general
    three-dimensional kernel. The atmosphere, Mach curve, constants, and
    constant-acceleration ``1/48 s`` state step are versioned together.  No
    coefficient is fitted at runtime.
    """

    del bomb_bc
    params = bomb_params if isinstance(bomb_params, dict) else {}
    model = resolve_offline_ballistics_model(params)
    if not model.supported or not model.rigidbody_projection_enabled:
        return 0.0, 0.0, 0.0
    mass = _positive_finite(params.get("mass"), _positive_finite(bomb_mass_kg, 100.0))
    caliber = _positive_finite(params.get("caliber"), 0.2)
    release_altitude = _finite(release_alt_m, default=math.nan)
    horizontal_release_speed = _finite(release_speed_ms, default=math.nan)
    fixed_target_altitude = _finite(target_alt_m, default=math.nan)
    altitude_datum = _finite(atmosphere_altitude_datum_m)
    if not all(
        math.isfinite(value)
        for value in (
            release_altitude,
            horizontal_release_speed,
            fixed_target_altitude,
        )
    ):
        return 0.0, 0.0, 0.0
    if mass <= 0.0 or caliber <= 0.0 or horizontal_release_speed <= 0.0:
        return 0.0, 0.0, 0.0

    dive_radians = math.radians(_finite(dive_angle_deg))
    velocity_x = horizontal_release_speed * math.cos(dive_radians)
    velocity_y = (
        _finite(initial_vz_ms)
        if initial_vz_ms is not None
        else -horizontal_release_speed * math.sin(dive_radians)
    )
    aoa = _finite(initial_aoa_deg, default=math.nan)
    properties = OfflineRigidbodySolverProperties.from_static(params)
    if not math.isfinite(aoa) or properties is None:
        return 0.0, 0.0, 0.0
    return _calculate_rigidbody_projection_trajectory(
        release_altitude_m=release_altitude,
        velocity_x_ms=velocity_x,
        velocity_y_ms=velocity_y,
        initial_aoa_deg=aoa,
        fixed_target_altitude_m=fixed_target_altitude,
        altitude_datum_m=altitude_datum,
        sea_level_density=_resolved_sea_level_density(air_density_sea_level),
        terrain_altitude_at_range=terrain_altitude_at_range,
        properties=properties,
    )


def calculate_release_timing(
    current_distance_m: float,
    current_alt_m: float,
    ground_speed_ms: float,
    bomb_mass_kg: float = 0.0,
    bomb_bc: float = 0.0,
    target_alt_m: float = 0.0,
    dive_angle_deg: float = 0.0,
    initial_vz_ms: float | None = None,
    initial_aoa_deg: float | None = None,
    bomb_params: dict | None = None,
    atmosphere_altitude_datum_m: float = 0.0,
    air_density_sea_level: float | None = None,
) -> tuple[float, float, str]:
    """Compatibility wrapper for callers that already have along-track range."""

    if ground_speed_ms < 10.0 or current_alt_m <= target_alt_m:
        return 0.0, 0.0, "invalid"
    _flight_time, bomb_range_m, _impact_speed = calculate_bomb_trajectory(
        release_alt_m=current_alt_m,
        release_speed_ms=ground_speed_ms,
        bomb_mass_kg=bomb_mass_kg,
        bomb_bc=bomb_bc,
        target_alt_m=target_alt_m,
        dive_angle_deg=dive_angle_deg,
        initial_vz_ms=initial_vz_ms,
        initial_aoa_deg=initial_aoa_deg,
        bomb_params=bomb_params,
        atmosphere_altitude_datum_m=atmosphere_altitude_datum_m,
        air_density_sea_level=air_density_sea_level,
    )
    if bomb_range_m <= 0.0:
        return 0.0, 0.0, "invalid"
    return calculate_release_timing_from_range(
        current_distance_m,
        ground_speed_ms,
        bomb_range_m,
    )


def calculate_release_timing_from_range(
    current_distance_m: float,
    ground_speed_ms: float,
    bomb_range_m: float,
) -> tuple[float, float, str]:
    """Calculate cue timing from an along-track target distance."""

    along_track_distance = _finite(current_distance_m)
    closing_speed = _finite(ground_speed_ms)
    ballistic_range = _finite(bomb_range_m)
    if closing_speed < 10.0 or ballistic_range <= 0.0:
        return 0.0, 0.0, "invalid"

    release_distance_m = along_track_distance - ballistic_range
    if release_distance_m < 0.0:
        return abs(release_distance_m), 0.0, "passed"

    time_to_release = release_distance_m / closing_speed
    if time_to_release <= BallisticPhysicsParams.RELEASE_READY_SEC:
        return release_distance_m, time_to_release, "ready"
    if time_to_release <= BallisticPhysicsParams.RELEASE_WARNING_SEC:
        return release_distance_m, time_to_release, "approaching"
    return release_distance_m, time_to_release, "too_far"


__all__ = [
    "TerrainAltitudeAtRange",
    "calculate_bomb_trajectory",
    "calculate_release_timing",
    "calculate_release_timing_from_range",
    "axial_drag_curve",
    "offline_speed_of_sound",
]
