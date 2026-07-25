"""CCRP scheduling from official 8111 state and an offline terrain pack."""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from typing import Any

from bomana.config.feature_profile import ENABLE_CCRP
from bomana.config.settings import BombConfig
from bomana.core.atmosphere import (
    DAGOR_ATMOSPHERE_MODEL_ID,
    DAGOR_STANDARD_DENSITY_KG_M3,
    estimate_dagor_sea_level_density,
)
from bomana.core.ballistics import calculate_bomb_trajectory, calculate_release_timing_from_range
from bomana.core.offline_ballistics_model import resolve_offline_ballistics_model
from bomana.core.release_observation import resolve_release_observation
from bomana.core.release_state import MAX_CROSS_TRACK_ERROR_M, target_track_geometry
from bomana.core.state import GameState, Phase, TelemetryData

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)
TerrainHeightAtWorld = Callable[[float, float], float | None]
MAX_CCRP_STATE_AGE_SECONDS = 0.15
MAX_CCRP_MAP_AGE_SECONDS = 0.15
MAX_CCRP_ENDPOINT_SKEW_SECONDS = 0.15
MAX_CCRP_FUTURE_TIMESTAMP_SECONDS = 0.005


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except _NUMERIC_PARSE_ERRORS:
        return default
    return result if math.isfinite(result) else default


def optional_finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except _NUMERIC_PARSE_ERRORS:
        return None
    return result if math.isfinite(result) else None


def _invalidate(state: GameState, reason: str) -> None:
    state.bombing_calc_valid = False
    state.cached_bombing_unavailable_reason = reason
    state.cached_bombing_solution_time = 0.0
    state.cached_bombing_state_age_s = 0.0
    state.cached_bombing_map_age_s = 0.0
    state.cached_bombing_endpoint_skew_s = 0.0
    state.cached_bombing_altitude_projection_m = 0.0
    state.cached_bombing_tas_projection_ms = 0.0
    state.cached_bombing_vertical_acceleration_ms2 = 0.0


def _reset_release_diagnostics(state: GameState) -> None:
    state.cached_bombing_release_state_source = ""
    state.cached_bombing_maneuver_score = 0.0
    state.cached_bombing_precision_gate_available = False


def prepare_bombing_calculation(
    state: GameState,
    tel: TelemetryData,
    now: float,
    *,
    player_present: bool,
    bomb_params: dict[str, Any] | None = None,
    target_alt_m: float | None = None,
    atmosphere_altitude_datum_m: float | None = None,
    terrain_height_at_world: TerrainHeightAtWorld | None = None,
) -> dict[str, Any] | None:
    """Collect one strict 8111-plus-heightmap release solution under lock."""

    _reset_release_diagnostics(state)
    if not ENABLE_CCRP:
        _invalidate(state, "feature_disabled")
        return None
    state.last_bombing_calc_time = now
    state.cached_bombing_unavailable_reason = ""

    nav = state.zone_nav
    target = nav.bombing_target
    if target is None:
        state.cached_target_altitude_m = 0.0
        state.cached_target_altitude_source = ""
        _invalidate(state, "no_target")
        return None
    resolved_target_altitude = optional_finite_float(target_alt_m)
    resolved_altitude_datum = optional_finite_float(atmosphere_altitude_datum_m)
    if resolved_target_altitude is not None:
        state.cached_target_altitude_m = resolved_target_altitude
        state.cached_target_altitude_source = "terrain"
    else:
        state.cached_target_altitude_m = 0.0
        state.cached_target_altitude_source = ""

    raw_altitude_m = optional_finite_float(tel.altitude_m)
    if not (
        player_present
        and state.phase == Phase.ALIVE
        and tel.state_resp_ok
        and not tel.is_on_ground
        and raw_altitude_m is not None
        and 50.0 < raw_altitude_m <= 30_000.0
    ):
        _invalidate(state, "release_state_unavailable")
        return None

    params = dict(bomb_params) if bomb_params is not None else BombConfig.get_bomb_physics_params()
    model = resolve_offline_ballistics_model(params)
    if not params.get("prediction_supported", True):
        _invalidate(
            state,
            str(params.get("prediction_note") or params.get("prediction_kind") or "unsupported"),
        )
        return None
    if not model.supported:
        _invalidate(state, model.unavailable_reason or "offline_rigidbody_model_unavailable")
        return None

    if (
        resolved_target_altitude is None
        or resolved_altitude_datum is None
        or terrain_height_at_world is None
    ):
        _invalidate(state, "terrain_unavailable")
        return None

    state_sample_time = optional_finite_float(tel.state_sample_time)
    if state_sample_time is None or state_sample_time <= 0.0:
        state_sample_time = now
    map_sample_time = optional_finite_float(nav.release_track_sample_time)
    if map_sample_time is None or map_sample_time <= 0.0:
        map_sample_time = now
    state_age_s = now - state_sample_time
    map_age_s = now - map_sample_time
    endpoint_skew_s = abs(state_sample_time - map_sample_time)
    if (
        state_age_s < -MAX_CCRP_FUTURE_TIMESTAMP_SECONDS
        or map_age_s < -MAX_CCRP_FUTURE_TIMESTAMP_SECONDS
        or state_age_s > MAX_CCRP_STATE_AGE_SECONDS
        or map_age_s > MAX_CCRP_MAP_AGE_SECONDS
        or endpoint_skew_s > MAX_CCRP_ENDPOINT_SKEW_SECONDS
    ):
        _invalidate(state, "time_alignment_unavailable")
        return None
    state_age_s = max(0.0, state_age_s)
    map_age_s = max(0.0, map_age_s)

    observation = resolve_release_observation(
        tel,
        nav,
        state_age_s=state_age_s,
        altitude_datum_m=resolved_altitude_datum,
    )
    if observation is None:
        _invalidate(state, "release_state_unavailable")
        return None
    if model.rigidbody_projection_enabled and observation.initial_aoa_deg is None:
        _invalidate(state, "release_attitude_unavailable")
        return None
    state.cached_bombing_release_state_source = observation.release_state_source
    state.cached_bombing_maneuver_score = observation.maneuver_score
    state.cached_bombing_precision_gate_available = observation.precision_gate_available
    if observation.unresolved_dynamics:
        _invalidate(state, "release_dynamics_unresolved")
        state.cached_bombing_release_state_source = observation.release_state_source
        state.cached_bombing_maneuver_score = observation.maneuver_score
        state.cached_bombing_precision_gate_available = observation.precision_gate_available
        state.cached_bombing_altitude_projection_m = observation.altitude_projection_m
        state.cached_bombing_tas_projection_ms = observation.tas_projection_ms
        state.cached_bombing_vertical_acceleration_ms2 = (
            observation.vertical_acceleration_ms2 or 0.0
        )
        return None

    # IAS/TAS are one synchronized observation of local density. Infer rho0 at
    # that observation altitude; use the projected state only for release.
    density_sample = estimate_dagor_sea_level_density(
        ias_kmh=tel.ias_kmh,
        tas_kmh=tel.tas_kmh,
        world_altitude_m=raw_altitude_m + resolved_altitude_datum,
    )
    if density_sample is not None:
        state.atmosphere_density_samples.append(density_sample)
    if state.atmosphere_density_samples:
        sea_level_density = statistics.median(state.atmosphere_density_samples)
        air_density_source = (
            "8111_ias_tas_filtered" if density_sample is not None else "8111_ias_tas_cached"
        )
    else:
        sea_level_density = DAGOR_STANDARD_DENSITY_KG_M3
        air_density_source = "standard_fallback"

    target_x = optional_finite_float(getattr(target, "x", None))
    target_y = optional_finite_float(getattr(target, "y", None))
    if target_x is None or target_y is None:
        _invalidate(state, "target_coordinates_unavailable")
        return None
    geometry = target_track_geometry(
        nav,
        target_x=target_x,
        target_y=target_y,
        map_info=state.map_info,
    )
    if geometry is None:
        _invalidate(state, "release_state_unavailable")
        return None
    if abs(geometry.cross_track_m) > MAX_CROSS_TRACK_ERROR_M:
        _invalidate(state, "off_axis")
        return None

    ground_speed_ms = finite_float(nav.release_ground_speed_ms)
    if not 10.0 <= ground_speed_ms <= 2_500.0:
        _invalidate(state, "release_state_unavailable")
        return None

    target_kind = str(getattr(target, "kind", "") or "zone")
    target_name = str(
        getattr(target, "name", "")
        or (f"战区 #{getattr(target, 'index', '')}" if target_kind == "zone" else "")
    )
    return {
        "altitude_m": observation.altitude_m,
        "horizontal_air_speed_ms": observation.horizontal_air_speed_ms,
        "ground_speed_ms": ground_speed_ms,
        "initial_vz_ms": observation.initial_vz_ms,
        "initial_aoa_deg": observation.initial_aoa_deg,
        "target_distance_m": geometry.distance_m,
        "target_along_track_m": geometry.along_track_m,
        "target_cross_track_m": geometry.cross_track_m,
        "target_kind": target_kind,
        "target_name": target_name,
        "target_alt_m": resolved_target_altitude,
        "target_altitude_source": "terrain",
        "atmosphere_altitude_datum_m": resolved_altitude_datum,
        "altitude_datum_source": "terrain_pack",
        "air_density_sea_level": sea_level_density,
        "air_density_source": air_density_source,
        "atmosphere_model_id": DAGOR_ATMOSPHERE_MODEL_ID,
        "state_age_s": state_age_s,
        "map_age_s": map_age_s,
        "endpoint_skew_s": endpoint_skew_s,
        "altitude_projection_m": observation.altitude_projection_m,
        "tas_projection_ms": observation.tas_projection_ms,
        "vertical_acceleration_ms2": observation.vertical_acceleration_ms2,
        "release_state_source": observation.release_state_source,
        "maneuver_score": observation.maneuver_score,
        "precision_gate_available": observation.precision_gate_available,
        "release_world_x_m": nav.release_world_x_m,
        "release_world_z_m": nav.release_world_z_m,
        "release_direction_x": geometry.direction_x,
        "release_direction_z": geometry.direction_z,
        "terrain_height_at_world": terrain_height_at_world,
        "bomb_params": params,
        "trajectory_model_id": model.model_id,
        "trajectory_model_category": model.category,
        "trajectory_model_quality": model.quality,
        "solution_time": now,
    }


def compute_bombing_calculation(
    work: dict[str, Any],
    *,
    trajectory_func=calculate_bomb_trajectory,
    timing_func=calculate_release_timing_from_range,
) -> dict[str, float | str | bool] | None:
    """Integrate the offline model outside the shared state lock."""

    altitude_m = finite_float(work.get("altitude_m"))
    horizontal_air_speed_ms = finite_float(work.get("horizontal_air_speed_ms"))
    ground_speed_ms = finite_float(work.get("ground_speed_ms"))
    target_distance_m = finite_float(work.get("target_distance_m"))
    target_along_track_m = finite_float(work.get("target_along_track_m"))
    target_cross_track_m = finite_float(work.get("target_cross_track_m"))
    target_alt_m = finite_float(work.get("target_alt_m"))
    altitude_datum_m = finite_float(work.get("atmosphere_altitude_datum_m"))
    sea_level_density = finite_float(
        work.get("air_density_sea_level"),
        default=DAGOR_STANDARD_DENSITY_KG_M3,
    )
    if sea_level_density <= 0.0:
        sea_level_density = DAGOR_STANDARD_DENSITY_KG_M3
    initial_vz_ms = optional_finite_float(work.get("initial_vz_ms"))
    initial_aoa_deg = optional_finite_float(work.get("initial_aoa_deg"))

    origin_x = finite_float(work.get("release_world_x_m"))
    origin_z = finite_float(work.get("release_world_z_m"))
    direction_x = finite_float(work.get("release_direction_x"))
    direction_z = finite_float(work.get("release_direction_z"))
    terrain_height_at_world = work.get("terrain_height_at_world")
    terrain_altitude_at_range = None
    if callable(terrain_height_at_world):

        def terrain_altitude_at_range(horizontal_range_m: float) -> float | None:
            return terrain_height_at_world(
                origin_x + direction_x * horizontal_range_m,
                origin_z + direction_z * horizontal_range_m,
            )

    try:
        flight_time, bomb_range_m, _impact_speed = trajectory_func(
            release_alt_m=altitude_m,
            release_speed_ms=horizontal_air_speed_ms,
            target_alt_m=target_alt_m,
            dive_angle_deg=0.0,
            initial_vz_ms=initial_vz_ms,
            initial_aoa_deg=initial_aoa_deg,
            bomb_params=work.get("bomb_params"),
            atmosphere_altitude_datum_m=altitude_datum_m,
            air_density_sea_level=sea_level_density,
            terrain_altitude_at_range=terrain_altitude_at_range,
        )
    except Exception:
        return None

    if not (
        math.isfinite(flight_time)
        and math.isfinite(bomb_range_m)
        and flight_time > 0.0
        and bomb_range_m > 0.0
    ):
        return None

    release_distance_m, time_to_release, release_status = timing_func(
        current_distance_m=target_along_track_m,
        ground_speed_ms=ground_speed_ms,
        bomb_range_m=bomb_range_m,
    )
    if not (math.isfinite(release_distance_m) and math.isfinite(time_to_release)):
        return None

    return {
        "flight_time": flight_time,
        "bomb_range_m": bomb_range_m,
        "release_distance_m": release_distance_m,
        "time_to_release": time_to_release,
        "release_status": release_status,
        "target_distance_m": target_distance_m,
        "target_along_track_m": target_along_track_m,
        "target_cross_track_m": target_cross_track_m,
        "target_kind": str(work.get("target_kind") or ""),
        "target_name": str(work.get("target_name") or ""),
        "target_alt_m": target_alt_m,
        "target_altitude_source": "terrain",
        "atmosphere_altitude_datum_m": altitude_datum_m,
        "altitude_datum_source": "terrain_pack",
        "air_density_sea_level": sea_level_density,
        "air_density_source": str(work.get("air_density_source") or ""),
        "atmosphere_model_id": str(work.get("atmosphere_model_id") or ""),
        "state_age_s": finite_float(work.get("state_age_s")),
        "map_age_s": finite_float(work.get("map_age_s")),
        "endpoint_skew_s": finite_float(work.get("endpoint_skew_s")),
        "altitude_projection_m": finite_float(work.get("altitude_projection_m")),
        "tas_projection_ms": finite_float(work.get("tas_projection_ms")),
        "vertical_acceleration_ms2": finite_float(work.get("vertical_acceleration_ms2")),
        "release_state_source": str(work.get("release_state_source") or ""),
        "maneuver_score": finite_float(work.get("maneuver_score")),
        "precision_gate_available": bool(work.get("precision_gate_available")),
        "trajectory_model_id": str(work.get("trajectory_model_id") or ""),
        "trajectory_model_category": str(work.get("trajectory_model_category") or ""),
        "trajectory_model_quality": str(work.get("trajectory_model_quality") or ""),
        "solution_time": finite_float(work.get("solution_time")),
    }


def apply_bombing_calculation(
    state: GameState,
    result: dict[str, float | str | bool] | None,
) -> None:
    """Store one completed offline CCRP result."""

    if result is None:
        state.bombing_calc_valid = False
        state.cached_bombing_solution_time = 0.0
        state.cached_bombing_model_id = ""
        state.cached_bombing_model_category = ""
        state.cached_bombing_model_quality = ""
        # Target elevation is an independently validated offline-terrain summary.
        # ``prepare_bombing_calculation`` refreshes or clears it every tick, so a
        # later trajectory failure must not erase a still-valid target height.
        state.cached_atmosphere_model_id = ""
        state.cached_atmosphere_altitude_datum_m = 0.0
        state.cached_altitude_datum_source = ""
        state.cached_air_density_sea_level = 0.0
        state.cached_air_density_source = ""
        state.cached_bombing_state_age_s = 0.0
        state.cached_bombing_map_age_s = 0.0
        state.cached_bombing_endpoint_skew_s = 0.0
        state.cached_bombing_altitude_projection_m = 0.0
        state.cached_bombing_tas_projection_ms = 0.0
        state.cached_bombing_vertical_acceleration_ms2 = 0.0
        if not state.cached_bombing_unavailable_reason:
            state.cached_bombing_unavailable_reason = "calc_failed"
        return

    state.cached_bomb_flight_time = float(result["flight_time"])
    state.cached_bomb_range_m = float(result["bomb_range_m"])
    state.cached_release_distance_m = float(result["release_distance_m"])
    state.cached_time_to_release = float(result["time_to_release"])
    state.cached_release_status = str(result["release_status"])
    state.cached_target_distance_m = float(result["target_distance_m"])
    state.cached_bombing_target_kind = str(result.get("target_kind") or "")
    state.cached_bombing_target_name = str(result.get("target_name") or "")
    state.cached_bombing_model_id = str(result.get("trajectory_model_id") or "")
    state.cached_bombing_model_category = str(result.get("trajectory_model_category") or "")
    state.cached_bombing_model_quality = str(result.get("trajectory_model_quality") or "")
    state.cached_target_altitude_m = float(result.get("target_alt_m") or 0.0)
    state.cached_target_altitude_source = "terrain"
    state.cached_atmosphere_model_id = str(result.get("atmosphere_model_id") or "")
    state.cached_atmosphere_altitude_datum_m = float(
        result.get("atmosphere_altitude_datum_m") or 0.0
    )
    state.cached_altitude_datum_source = "terrain_pack"
    state.cached_air_density_sea_level = float(result.get("air_density_sea_level") or 0.0)
    state.cached_air_density_source = str(result.get("air_density_source") or "")
    state.cached_bombing_state_age_s = float(result.get("state_age_s") or 0.0)
    state.cached_bombing_map_age_s = float(result.get("map_age_s") or 0.0)
    state.cached_bombing_endpoint_skew_s = float(result.get("endpoint_skew_s") or 0.0)
    state.cached_bombing_altitude_projection_m = float(result.get("altitude_projection_m") or 0.0)
    state.cached_bombing_tas_projection_ms = float(result.get("tas_projection_ms") or 0.0)
    state.cached_bombing_vertical_acceleration_ms2 = float(
        result.get("vertical_acceleration_ms2") or 0.0
    )
    state.cached_bombing_release_state_source = str(result.get("release_state_source") or "")
    state.cached_bombing_maneuver_score = float(result.get("maneuver_score") or 0.0)
    state.cached_bombing_precision_gate_available = bool(result.get("precision_gate_available"))
    state.cached_bombing_unavailable_reason = ""
    state.cached_bombing_solution_time = float(result.get("solution_time") or 0.0)
    state.bombing_calc_valid = state.phase == Phase.ALIVE


__all__ = [
    "apply_bombing_calculation",
    "compute_bombing_calculation",
    "finite_float",
    "optional_finite_float",
    "prepare_bombing_calculation",
]
