"""CCRP calculation scheduling helpers extracted from GameLogic."""

import math
from typing import Any

from bomana.config.feature_profile import ENABLE_CCRP
from bomana.config.settings import (
    BombConfig,
    ZoneConfig,
)
from bomana.core.ballistics import calculate_bomb_trajectory, calculate_release_timing_from_range
from bomana.core.state import GameState, Phase, TelemetryData

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except _NUMERIC_PARSE_ERRORS:
        return default
    return result if math.isfinite(result) else default


def estimate_release_mach(tel: TelemetryData, ground_speed_ms: float) -> float | None:
    """Prefer 8111 Mach; fall back to TAS or map-derived ground speed."""
    if tel.mach is not None:
        mach = finite_float(tel.mach, default=0.0)
        if mach > 0.0:
            return mach

    tas_kmh = finite_float(tel.tas_kmh, default=0.0)
    if tas_kmh > 0.0:
        return tas_kmh / 1225.0

    if ground_speed_ms > 0.0:
        return ground_speed_ms / 340.3
    return None


def prepare_bombing_calculation(
    state: GameState,
    tel: TelemetryData,
    now: float,
    *,
    player_present: bool,
) -> dict[str, Any] | None:
    """Collect CCRP inputs under lock; expensive integration runs outside it."""
    nav = state.zone_nav

    if not ENABLE_CCRP:
        state.bombing_calc_valid = False
        return None

    if (now - state.last_bombing_calc_time) < 0.2:
        return None

    state.last_bombing_calc_time = now
    state.cached_bombing_unavailable_reason = ""

    target_zone = nav.target_zone
    altitude_m = finite_float(tel.altitude_m)
    ground_speed_ms = finite_float(nav.ground_speed) * ZoneConfig.DISTANCE_SCALE * 1000
    target_distance_m = (
        finite_float(target_zone.distance) * ZoneConfig.DISTANCE_SCALE * 1000
        if target_zone is not None
        else 0.0
    )

    if not (
        player_present
        and target_zone is not None
        and state.phase == Phase.ALIVE
        and tel.state_resp_ok
        and not tel.is_on_ground
        and altitude_m > 50
        and altitude_m <= 30000
        and 10.0 <= ground_speed_ms <= 2500.0
        and 0.0 < target_distance_m <= 500000.0
    ):
        state.bombing_calc_valid = False
        return None

    bomb_params = BombConfig.get_bomb_physics_params()
    if not bomb_params.get("prediction_supported", True):
        state.bombing_calc_valid = False
        state.cached_bombing_unavailable_reason = str(
            bomb_params.get("prediction_kind") or "unsupported"
        )
        return None

    release_mach_max = bomb_params.get("release_mach_max")
    if release_mach_max is not None:
        max_mach = finite_float(release_mach_max, default=0.0)
        release_mach = estimate_release_mach(tel, ground_speed_ms)
        if max_mach > 0.0 and release_mach is not None and release_mach >= max_mach:
            state.bombing_calc_valid = False
            state.cached_bombing_unavailable_reason = "release_mach_limit"
            return None

    return {
        "altitude_m": altitude_m,
        "ground_speed_ms": ground_speed_ms,
        "target_distance_m": target_distance_m,
        "bomb_params": bomb_params,
    }


def compute_bombing_calculation(
    work: dict[str, Any],
    *,
    trajectory_func=calculate_bomb_trajectory,
    timing_func=calculate_release_timing_from_range,
) -> dict[str, float | str] | None:
    """Run CCRP ballistics without holding the game state lock."""
    altitude_m = finite_float(work.get("altitude_m"))
    ground_speed_ms = finite_float(work.get("ground_speed_ms"))
    target_distance_m = finite_float(work.get("target_distance_m"))

    try:
        flight_time, bomb_range_m, _ = trajectory_func(
            release_alt_m=altitude_m,
            release_speed_ms=ground_speed_ms,
            target_alt_m=0.0,
            dive_angle_deg=0.0,
            initial_vz_ms=None,
            bomb_params=work.get("bomb_params"),
        )
    except Exception:
        return None

    if not (
        math.isfinite(flight_time)
        and math.isfinite(bomb_range_m)
        and flight_time > 0
        and bomb_range_m > 0
    ):
        return None

    release_distance_m, time_to_release, release_status = timing_func(
        current_distance_m=target_distance_m,
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
    }


def apply_bombing_calculation(
    state: GameState,
    result: dict[str, float | str] | None,
) -> None:
    """Store CCRP result after out-of-lock calculation."""
    if result is None:
        state.bombing_calc_valid = False
        if not state.cached_bombing_unavailable_reason:
            state.cached_bombing_unavailable_reason = "calc_failed"
        return

    state.cached_bomb_flight_time = float(result["flight_time"])
    state.cached_bomb_range_m = float(result["bomb_range_m"])
    state.cached_release_distance_m = float(result["release_distance_m"])
    state.cached_time_to_release = float(result["time_to_release"])
    state.cached_release_status = str(result["release_status"])
    state.cached_target_distance_m = float(result["target_distance_m"])
    state.cached_bombing_unavailable_reason = ""
    state.bombing_calc_valid = state.phase == Phase.ALIVE
