"""Qualified two-dimensional weapon engagement-envelope estimates."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from bomana.config.settings import WeaponBallisticModelConfig
from bomana.core.ballistics import calculate_bomb_trajectory
from bomana.core.visible_trajectory_reference import (
    VisibleTrajectoryReference,
    find_visible_trajectory_reference,
)
from bomana.core.weapon_envelope import (
    FIELD_RANGE_MAX_M,
    FIELD_RANGE_MIN_M,
    REASON_ENDPOINT_UNAVAILABLE,
    REASON_UNAVAILABLE_CELL,
    interpolate_aspect,
    interpolate_aspect_endpoints,
)

QUALITY_NONE = "none"
QUALITY_TWO_DIMENSIONAL = "two_dimensional"
QUALITY_CONSERVATIVE = "conservative"
QUALITY_EXPERIMENTAL = "experimental"

REASON_PLAYER_VISIBLE_TRAJECTORY_REFERENCE = "player_visible_trajectory_reference"
REASON_GUIDED_BALLISTIC_UNCALIBRATED = "guided_ballistic_uncalibrated"

STATUS_CCRP = "ccrp"
STATUS_UNKNOWN_WEAPON = "unknown_weapon"
STATUS_INCOMPATIBLE = "incompatible"
STATUS_NO_TARGET = "no_target"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_TOO_CLOSE = "too_close"
STATUS_OUT_OF_RANGE = "out_of_range"
STATUS_ALIGN = "align"
STATUS_IN_ENVELOPE = "in_envelope"
STATUS_WITHIN_BALLISTIC_REFERENCE = "within_ballistic_reference"
STATUS_BEYOND_BALLISTIC_REFERENCE = "beyond_ballistic_reference"
STATUS_WITHIN_2D_MAX_ONLY = "within_2d_max_only"
STATUS_WITHIN_ALL_ASPECT_REFERENCE = "within_all_aspect_reference"
STATUS_WITHIN_ASPECT_REFERENCE = "within_aspect_reference"
STATUS_HEAD_ON_ONLY_REFERENCE = "head_on_only_reference"
STATUS_BEYOND_ENVELOPE_REFERENCE = "beyond_envelope_reference"
STATUS_WITHIN_EXPERIMENTAL_REFERENCE = "within_experimental_reference"
STATUS_BEYOND_EXPERIMENTAL_REFERENCE = "beyond_experimental_reference"
STATUS_SOLVER_ERROR = "solver_error"

VALID_STATUSES = frozenset(
    {
        STATUS_CCRP,
        STATUS_UNKNOWN_WEAPON,
        STATUS_INCOMPATIBLE,
        STATUS_NO_TARGET,
        STATUS_INSUFFICIENT_DATA,
        STATUS_TOO_CLOSE,
        STATUS_OUT_OF_RANGE,
        STATUS_ALIGN,
        STATUS_IN_ENVELOPE,
        STATUS_WITHIN_BALLISTIC_REFERENCE,
        STATUS_BEYOND_BALLISTIC_REFERENCE,
        STATUS_WITHIN_2D_MAX_ONLY,
        STATUS_WITHIN_ALL_ASPECT_REFERENCE,
        STATUS_WITHIN_ASPECT_REFERENCE,
        STATUS_HEAD_ON_ONLY_REFERENCE,
        STATUS_BEYOND_ENVELOPE_REFERENCE,
        STATUS_WITHIN_EXPERIMENTAL_REFERENCE,
        STATUS_BEYOND_EXPERIMENTAL_REFERENCE,
        STATUS_SOLVER_ERROR,
    }
)
VALID_QUALITIES = frozenset(
    {QUALITY_NONE, QUALITY_TWO_DIMENSIONAL, QUALITY_CONSERVATIVE, QUALITY_EXPERIMENTAL}
)

# Explicit conservative model constants. They are not weapon performance data.
POWERED_TIME_STEP_S = 0.02
AGM_POST_BURN_SPEED_FLOOR_MPS = 90.0
AAM_POST_BURN_SPEED_FLOOR_MPS = 220.0
ALIGN_TOLERANCE_DEG = 10.0
GUIDED_NORMAL_RANGE_FACTOR = 0.85
GUIDANCE_CONTROL_BASE_FACTOR = 0.75
GUIDANCE_KNOWN_BONUS = 0.10
CONTROL_SURFACE_BONUS_MAX = 0.15
GRAVITY_MPS2 = 9.80665

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)


@dataclass(frozen=True)
class WeaponSolution:
    """Machine-readable result consumed by the scheduler and UI snapshot."""

    valid: bool = False
    status: str = STATUS_INSUFFICIENT_DATA
    quality: str = QUALITY_NONE
    model: str = ""
    reason: str = ""
    target_kind: str = ""
    target_name: str = ""
    target_distance_m: float = 0.0
    min_range_m: float = 0.0
    max_range_m: float = 0.0
    rear_range_m: float = 0.0
    head_range_m: float = 0.0
    target_aspect_cosine: float | None = None
    time_to_target_s: float = 0.0
    time_to_window_s: float = 0.0

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"unsupported weapon solution status: {self.status}")
        if self.quality not in VALID_QUALITIES:
            raise ValueError(f"unsupported weapon solution quality: {self.quality}")
        if self.model and self.model not in WeaponBallisticModelConfig.VALID_MODELS:
            raise ValueError(f"unsupported weapon ballistic model: {self.model}")


@dataclass(frozen=True)
class _EnvelopeEstimate:
    range_m: float
    duration_s: float
    time_to_target_s: float
    hard_limited: bool = False


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except _NUMERIC_PARSE_ERRORS:
        return default
    return result if math.isfinite(result) else default


def isa_air_density(altitude_m: float) -> float:
    """Return dry-air density from the ISA troposphere/lower stratosphere."""

    altitude = max(0.0, min(32000.0, _finite_float(altitude_m)))
    gas_constant = 287.05287
    if altitude <= 11000.0:
        temperature = 288.15 - 0.0065 * altitude
        pressure = 101325.0 * (temperature / 288.15) ** 5.2558797
    else:
        temperature = 216.65
        pressure_11km = 22632.06
        pressure = pressure_11km * math.exp(
            -GRAVITY_MPS2 * (altitude - 11000.0) / (gas_constant * temperature)
        )
    return pressure / (gas_constant * temperature)


def _mach_from_launch_state(altitude_m: float, speed_mps: float, mach: float | None) -> float:
    supplied = _finite_float(mach, default=-1.0)
    if supplied > 0.0:
        return supplied
    altitude = max(0.0, min(32000.0, _finite_float(altitude_m)))
    temperature = 288.15 - 0.0065 * altitude if altitude <= 11000.0 else 216.65
    speed_of_sound = math.sqrt(1.4 * 287.05287 * temperature)
    return max(0.0, _finite_float(speed_mps) / speed_of_sound)


def _guidance_envelope_solution(
    weapon: Mapping[str, Any],
    *,
    ballistic_model: str,
    launch_altitude_m: float,
    launch_mach: float,
    target_distance_m: float,
    target_relative_deg: float,
    target_kind: str,
    target_name: str,
    target_aspect_cosine: float | None,
    ground_closing_speed_mps: float | None,
) -> WeaponSolution | None:
    """Prefer Datamine's condition table over Bomana's flat propulsion model."""

    envelope = weapon.get("guidance_envelope")
    if not isinstance(envelope, Mapping):
        return None

    endpoints = interpolate_aspect_endpoints(
        envelope,
        field=FIELD_RANGE_MAX_M,
        altitude_m=launch_altitude_m,
        fighter_mach=launch_mach,
    )
    if not endpoints.available:
        # A zero rangeMax cell is how current Datamine tables mark launch
        # conditions with no table solution (for example high-altitude
        # AGM-65/RB75 tail-chase endpoints).  That condition makes the table
        # unusable, not the independent powered-weapon model invalid.
        if endpoints.reason in {REASON_ENDPOINT_UNAVAILABLE, REASON_UNAVAILABLE_CELL}:
            return None
        return WeaponSolution(
            status=STATUS_INSUFFICIENT_DATA,
            quality=QUALITY_NONE,
            model=ballistic_model,
            reason=f"guidance_envelope_{endpoints.reason}",
            target_kind=target_kind,
            target_name=target_name,
            target_distance_m=target_distance_m,
        )

    tail_range_m = max(0.0, _finite_float(endpoints.tail_chase.value))
    head_range_m = max(0.0, _finite_float(endpoints.head_on.value))
    if tail_range_m <= 0.0 or head_range_m <= 0.0:
        return WeaponSolution(
            status=STATUS_INSUFFICIENT_DATA,
            quality=QUALITY_NONE,
            model=ballistic_model,
            reason="guidance_envelope_unavailable_cell",
            target_kind=target_kind,
            target_name=target_name,
            target_distance_m=target_distance_m,
        )

    role = str(weapon.get("role") or "")
    aspect: float | None = None
    if target_aspect_cosine is not None:
        parsed_aspect = _finite_float(target_aspect_cosine, default=math.nan)
        if math.isfinite(parsed_aspect):
            aspect = max(-1.0, min(1.0, parsed_aspect))
    # Static ground points have zero radial target motion.  For AAMs, retain
    # unknown aspect when 8111 did not provide a current heading vector.
    interpolation_aspect = aspect if role == "aam" else 0.0
    current_value = (
        interpolate_aspect(
            envelope,
            field=FIELD_RANGE_MAX_M,
            altitude_m=launch_altitude_m,
            fighter_mach=launch_mach,
            aspect_cosine=interpolation_aspect,
        )
        if interpolation_aspect is not None
        else None
    )
    current_range_m = (
        max(0.0, _finite_float(current_value.value))
        if current_value is not None and current_value.available
        else max(tail_range_m, head_range_m)
    )
    if current_range_m <= 0.0:
        return WeaponSolution(
            status=STATUS_INSUFFICIENT_DATA,
            quality=QUALITY_NONE,
            model=ballistic_model,
            reason="guidance_envelope_unavailable_cell",
            target_kind=target_kind,
            target_name=target_name,
            target_distance_m=target_distance_m,
        )

    min_value = (
        interpolate_aspect(
            envelope,
            field=FIELD_RANGE_MIN_M,
            altitude_m=launch_altitude_m,
            fighter_mach=launch_mach,
            aspect_cosine=interpolation_aspect,
        )
        if interpolation_aspect is not None
        else None
    )
    min_range_m = (
        max(0.0, _finite_float(min_value.value))
        if min_value is not None and min_value.available
        else (0.0 if role == "aam" else max(0.0, _finite_float(weapon.get("min_distance_m"))))
    )
    base = {
        "valid": True,
        "quality": QUALITY_TWO_DIMENSIONAL,
        "model": ballistic_model,
        "target_kind": target_kind,
        "target_name": target_name,
        "target_distance_m": target_distance_m,
        "min_range_m": min_range_m,
        "max_range_m": current_range_m,
        "rear_range_m": tail_range_m,
        "head_range_m": head_range_m,
        "target_aspect_cosine": aspect,
    }

    if role == "aam":
        if target_distance_m < min_range_m:
            return WeaponSolution(
                **base,
                status=STATUS_TOO_CLOSE,
                reason="datamine_guidance_envelope",
            )
        all_aspect_range_m = min(tail_range_m, head_range_m)
        best_aspect_range_m = max(tail_range_m, head_range_m)
        if target_distance_m <= all_aspect_range_m:
            status = STATUS_WITHIN_ALL_ASPECT_REFERENCE
        elif aspect is not None and target_distance_m <= current_range_m:
            status = STATUS_WITHIN_ASPECT_REFERENCE
        elif target_distance_m <= best_aspect_range_m:
            status = STATUS_HEAD_ON_ONLY_REFERENCE
        else:
            status = STATUS_BEYOND_ENVELOPE_REFERENCE
        return WeaponSolution(**base, status=status, reason="datamine_guidance_envelope")

    if abs(target_relative_deg) > ALIGN_TOLERANCE_DEG:
        return WeaponSolution(**base, status=STATUS_ALIGN, reason="target_off_axis")
    if target_distance_m < min_range_m:
        return WeaponSolution(**base, status=STATUS_TOO_CLOSE, reason="below_min_distance")
    if target_distance_m > current_range_m:
        closing_speed_mps = _finite_float(ground_closing_speed_mps)
        if closing_speed_mps > 0.0:
            base["time_to_window_s"] = (target_distance_m - current_range_m) / closing_speed_mps
        return WeaponSolution(
            **base,
            status=STATUS_OUT_OF_RANGE,
            reason="datamine_guidance_envelope",
        )
    return WeaponSolution(
        **base,
        status=STATUS_IN_ENVELOPE,
        reason="datamine_guidance_envelope",
    )


def uses_existing_ccrp(weapon: Mapping[str, Any] | None) -> bool:
    """Whether this store stays on the existing free-fall/high-drag CCRP path."""

    return bool(
        weapon
        and weapon.get("role") == "bomb"
        and weapon.get("propulsion") == "unpowered"
        and weapon.get("control") == "unguided"
        and weapon.get("planform") in {"normal", "high_drag"}
    )


def _motor_schedule(
    weapon: Mapping[str, Any],
) -> tuple[list[tuple[float, float, float, float]], float]:
    """Return (start, end, thrust, mass_end) stages and total burn time."""

    schedule: list[tuple[float, float, float, float]] = []
    cursor = 0.0
    for raw_stage in weapon.get("motor_stages", []):
        if not isinstance(raw_stage, Mapping):
            continue
        duration = _finite_float(raw_stage.get("duration_s"))
        thrust = _finite_float(raw_stage.get("thrust_n"), default=-1.0)
        mass_end = _finite_float(raw_stage.get("mass_end_kg"))
        if duration <= 0.0 or thrust < 0.0 or mass_end <= 0.0:
            raise ValueError("invalid Datamine motor stage")
        schedule.append((cursor, cursor + duration, thrust, mass_end))
        cursor += duration
    return schedule, cursor


def _powered_envelope(
    weapon: Mapping[str, Any],
    *,
    launch_altitude_m: float,
    launch_speed_mps: float,
    target_distance_m: float,
) -> _EnvelopeEstimate:
    lifetime = _finite_float(weapon.get("time_life_s"))
    mass_start = _finite_float(weapon.get("mass_start_kg"))
    caliber = _finite_float(weapon.get("caliber_m"))
    cx_k = _finite_float(weapon.get("cx_k"), default=-1.0)
    if lifetime <= 0.0 or mass_start <= 0.0 or caliber <= 0.0 or cx_k < 0.0:
        raise ValueError("powered weapon is missing required physical values")

    schedule, burn_end_s = _motor_schedule(weapon)
    if not schedule:
        raise ValueError("powered weapon has no motor stages")

    rho = isa_air_density(launch_altitude_m)
    area_m2 = math.pi * (caliber * 0.5) ** 2
    max_speed_mps = _finite_float(weapon.get("max_speed_mps"))
    hard_max_distance_m = _finite_float(weapon.get("hard_max_distance_m"))
    hard_limit = hard_max_distance_m if hard_max_distance_m > 0.0 else math.inf
    speed_floor = (
        AAM_POST_BURN_SPEED_FLOOR_MPS
        if weapon.get("role") == "aam"
        else AGM_POST_BURN_SPEED_FLOOR_MPS
    )

    datamine_start_speed_mps = max(0.0, _finite_float(weapon.get("start_speed_mps")))
    velocity = datamine_start_speed_mps if datamine_start_speed_mps > 0.0 else launch_speed_mps
    velocity = max(0.0, velocity)
    if max_speed_mps > 0.0:
        velocity = min(velocity, max_speed_mps)
    distance = 0.0
    elapsed = 0.0
    time_to_target = 0.0
    stage_index = 0
    stage_mass_start = mass_start
    hard_limited = False

    while elapsed < lifetime and distance < hard_limit:
        while stage_index < len(schedule) and elapsed >= schedule[stage_index][1] - 1e-10:
            stage_mass_start = schedule[stage_index][3]
            stage_index += 1

        thrust_n = 0.0
        mass_kg = stage_mass_start
        next_boundary = lifetime
        if stage_index < len(schedule):
            stage_start, stage_end, thrust_n, stage_mass_end = schedule[stage_index]
            next_boundary = min(next_boundary, stage_end)
            ratio = min(1.0, max(0.0, (elapsed - stage_start) / (stage_end - stage_start)))
            mass_kg = stage_mass_start + (stage_mass_end - stage_mass_start) * ratio

        step = min(POWERED_TIME_STEP_S, lifetime - elapsed, next_boundary - elapsed)
        if step <= 1e-10:
            elapsed = next_boundary
            continue

        drag_n = 0.5 * rho * cx_k * area_m2 * velocity * velocity
        acceleration = (thrust_n - drag_n) / max(0.001, mass_kg)
        next_velocity = max(0.0, velocity + acceleration * step)
        if max_speed_mps > 0.0:
            next_velocity = min(next_velocity, max_speed_mps)
        next_distance = distance + (velocity + next_velocity) * 0.5 * step

        if time_to_target <= 0.0 and target_distance_m > 0.0 and next_distance >= target_distance_m:
            segment = next_distance - distance
            fraction = (target_distance_m - distance) / segment if segment > 1e-9 else 0.0
            time_to_target = elapsed + step * max(0.0, min(1.0, fraction))

        if next_distance >= hard_limit:
            segment = next_distance - distance
            fraction = (hard_limit - distance) / segment if segment > 1e-9 else 0.0
            elapsed += step * max(0.0, min(1.0, fraction))
            distance = hard_limit
            hard_limited = True
            break

        elapsed += step
        distance = next_distance
        velocity = next_velocity
        if elapsed >= burn_end_s and velocity < speed_floor:
            break

    return _EnvelopeEstimate(
        range_m=max(0.0, distance),
        duration_s=max(0.0, elapsed),
        time_to_target_s=max(0.0, time_to_target),
        hard_limited=hard_limited,
    )


def _guidance_control_factor(weapon: Mapping[str, Any]) -> float:
    """Apply a bounded conservative penalty from normalized Datamine fields."""

    fins_horiz = max(0.0, _finite_float(weapon.get("fins_aoa_horiz")))
    fins_vert = max(0.0, _finite_float(weapon.get("fins_aoa_vert")))
    surface_bonus = min(
        CONTROL_SURFACE_BONUS_MAX,
        ((fins_horiz + fins_vert) / 60.0) * CONTROL_SURFACE_BONUS_MAX,
    )
    guidance = weapon.get("guidance")
    guidance_values = [str(weapon.get("guidance_kind") or "").casefold()]
    if isinstance(guidance, Mapping):
        guidance_values.extend(
            [
                str(guidance.get("type") or "").casefold(),
                str(guidance.get("seeker") or "").casefold(),
            ]
        )
    guidance_known = any(value not in {"", "none", "unknown"} for value in guidance_values)
    guidance_bonus = GUIDANCE_KNOWN_BONUS if guidance_known else 0.0
    return min(1.0, GUIDANCE_CONTROL_BASE_FACTOR + guidance_bonus + surface_bonus)


def _guided_normal_envelope(
    weapon: Mapping[str, Any],
    *,
    launch_altitude_m: float,
    launch_speed_mps: float,
    target_altitude_m: float | None,
    target_distance_m: float,
    trajectory_func: Callable[..., tuple[Any, Any, Any]],
) -> _EnvelopeEstimate:
    mass_kg = _finite_float(weapon.get("mass_start_kg"))
    caliber_m = _finite_float(weapon.get("caliber_m"))
    drag_cx = _finite_float(weapon.get("drag_cx"), default=-1.0)
    if mass_kg <= 0.0 or caliber_m <= 0.0 or drag_cx < 0.0:
        raise ValueError("guided weapon is missing required ballistic values")

    assumed_target_altitude = (
        _finite_float(target_altitude_m) if target_altitude_m is not None else 0.0
    )
    flight_time, raw_range_m, _impact_speed = trajectory_func(
        release_alt_m=launch_altitude_m,
        release_speed_ms=launch_speed_mps,
        target_alt_m=assumed_target_altitude,
        dive_angle_deg=0.0,
        initial_vz_ms=None,
        bomb_params={
            "mass": mass_kg,
            "drag_cx": drag_cx,
            "caliber": caliber_m,
        },
    )
    flight_time = _finite_float(flight_time)
    raw_range_m = _finite_float(raw_range_m)
    if flight_time <= 0.0 or raw_range_m <= 0.0:
        raise ValueError("guided ballistic integration returned no trajectory")

    effective_time = flight_time
    lifetime = _finite_float(weapon.get("time_life_s"))
    if lifetime > 0.0:
        effective_time = min(effective_time, lifetime)
    life_fraction = min(1.0, effective_time / flight_time)
    range_m = (
        raw_range_m * life_fraction * GUIDED_NORMAL_RANGE_FACTOR * _guidance_control_factor(weapon)
    )
    hard_limit = _finite_float(weapon.get("hard_max_distance_m"))
    hard_limited = hard_limit > 0.0 and range_m >= hard_limit
    if hard_limit > 0.0:
        range_m = min(range_m, hard_limit)
    time_to_target = (
        effective_time * (target_distance_m / range_m)
        if 0.0 < target_distance_m <= range_m
        else 0.0
    )
    return _EnvelopeEstimate(range_m, effective_time, time_to_target, hard_limited)


def _visible_trajectory_reference_envelope(
    reference: VisibleTrajectoryReference,
    *,
    target_distance_m: float,
) -> _EnvelopeEstimate:
    """Project one source-backed visible curve without calling it a maximum."""

    verified_reach_m = max(0.0, reference.verified_reach_m)
    time_to_target_s = (
        reference.time_at_horizontal_distance(target_distance_m)
        if 0.0 < target_distance_m <= verified_reach_m
        else 0.0
    )
    return _EnvelopeEstimate(
        range_m=verified_reach_m,
        duration_s=reference.duration_s,
        time_to_target_s=time_to_target_s,
    )


def _foxthree_compatible_glide_envelope(
    weapon: Mapping[str, Any],
    *,
    launch_altitude_m: float,
    launch_speed_mps: float,
    target_altitude_m: float | None,
    target_distance_m: float,
) -> _EnvelopeEstimate:
    """Clean-room compatibility estimate for glide stores without an official table."""

    if "wing_area_mult" not in weapon:
        raise ValueError("glide weapon is missing wing-area multiplier")
    wing_area_mult = max(0.0, _finite_float(weapon.get("wing_area_mult")))
    lift_drag_ratio = max(1.5, min(12.0, 2.4 * wing_area_mult))
    target_altitude = _finite_float(target_altitude_m) if target_altitude_m is not None else 0.0
    height_available_m = max(0.0, launch_altitude_m - target_altitude)
    energy_height_m = height_available_m + launch_speed_mps**2 / (2.0 * GRAVITY_MPS2)
    raw_range_m = 0.8 * lift_drag_ratio * energy_height_m
    if raw_range_m <= 0.0:
        raise ValueError("glide compatibility model returned no range")

    range_m = raw_range_m
    lifetime_s = _finite_float(weapon.get("time_life_s"))
    if lifetime_s > 0.0:
        range_m = min(range_m, launch_speed_mps * lifetime_s)
    hard_limit_m = _finite_float(weapon.get("hard_max_distance_m"))
    hard_limited = hard_limit_m > 0.0 and hard_limit_m <= range_m
    if hard_limit_m > 0.0:
        range_m = min(range_m, hard_limit_m)
    if range_m <= 0.0:
        raise ValueError("glide compatibility caps removed the estimated range")

    duration_s = range_m / launch_speed_mps
    if lifetime_s > 0.0:
        duration_s = min(duration_s, lifetime_s)
    time_to_target_s = (
        target_distance_m / launch_speed_mps if 0.0 < target_distance_m <= range_m else 0.0
    )
    return _EnvelopeEstimate(range_m, duration_s, time_to_target_s, hard_limited)


def _solution_from_envelope(
    estimate: _EnvelopeEstimate,
    *,
    weapon: Mapping[str, Any],
    ground_closing_speed_mps: float | None,
    target_distance_m: float,
    target_relative_deg: float,
    target_kind: str,
    target_name: str,
    ballistic_model: str,
    quality: str,
    model_reason: str,
    within_status: str = STATUS_IN_ENVELOPE,
    beyond_status: str = STATUS_OUT_OF_RANGE,
) -> WeaponSolution:
    is_aam = weapon.get("role") == "aam"
    min_range_m = 0.0 if is_aam else max(0.0, _finite_float(weapon.get("min_distance_m")))
    max_range_m = max(0.0, estimate.range_m)
    base = {
        "valid": max_range_m > 0.0,
        "quality": quality,
        "model": ballistic_model,
        "target_kind": target_kind,
        "target_name": target_name,
        "target_distance_m": target_distance_m,
        "min_range_m": min_range_m,
        "max_range_m": max_range_m,
        "time_to_target_s": 0.0 if is_aam else estimate.time_to_target_s,
        "time_to_window_s": 0.0,
    }
    if max_range_m <= 0.0:
        return WeaponSolution(
            **base,
            status=STATUS_SOLVER_ERROR,
            reason="empty_estimated_envelope",
        )
    if abs(target_relative_deg) > ALIGN_TOLERANCE_DEG:
        return WeaponSolution(**base, status=STATUS_ALIGN, reason="target_off_axis")
    if target_distance_m < min_range_m:
        return WeaponSolution(**base, status=STATUS_TOO_CLOSE, reason="below_min_distance")
    if target_distance_m > max_range_m:
        closing_speed_mps = _finite_float(ground_closing_speed_mps)
        if target_kind in {"zone", "poi", "ground"} and closing_speed_mps > 0.0:
            base["time_to_window_s"] = (target_distance_m - max_range_m) / closing_speed_mps
        return WeaponSolution(
            **base,
            status=beyond_status,
            reason=(
                model_reason
                if beyond_status
                in {STATUS_BEYOND_BALLISTIC_REFERENCE, STATUS_BEYOND_EXPERIMENTAL_REFERENCE}
                else (
                    "beyond_hard_max_distance"
                    if estimate.hard_limited
                    else "beyond_estimated_range"
                )
            ),
        )
    if is_aam:
        return WeaponSolution(
            **base,
            status=STATUS_WITHIN_2D_MAX_ONLY,
            reason="aam_2d_max_only",
        )
    return WeaponSolution(**base, status=within_status, reason=model_reason)


class WeaponSolver:
    """Solve one selected weapon against one already-selected target."""

    def __init__(
        self,
        *,
        trajectory_func: Callable[..., tuple[Any, Any, Any]] = calculate_bomb_trajectory,
        ballistic_model: str | None = None,
    ) -> None:
        self._trajectory_func = trajectory_func
        if (
            ballistic_model is not None
            and ballistic_model not in WeaponBallisticModelConfig.VALID_MODELS
        ):
            raise ValueError(f"unsupported weapon ballistic model: {ballistic_model}")
        self._ballistic_model = ballistic_model

    def _selected_ballistic_model(self) -> str:
        selected = self._ballistic_model or WeaponBallisticModelConfig.selected_model
        if selected in WeaponBallisticModelConfig.VALID_MODELS:
            return selected
        return WeaponBallisticModelConfig.DEFAULT_MODEL

    def solve(
        self,
        weapon: Mapping[str, Any] | None,
        *,
        launch_altitude_m: float,
        launch_speed_mps: float,
        launch_mach: float | None = None,
        target_distance_m: float | None,
        target_relative_deg: float = 0.0,
        target_kind: str = "",
        target_name: str = "",
        target_altitude_m: float | None = None,
        target_aspect_cosine: float | None = None,
        ground_closing_speed_mps: float | None = None,
    ) -> WeaponSolution:
        ballistic_model = self._selected_ballistic_model()
        if weapon is None:
            return WeaponSolution(
                status=STATUS_UNKNOWN_WEAPON,
                model=ballistic_model,
                reason="weapon_not_in_catalog",
            )
        if uses_existing_ccrp(weapon):
            return WeaponSolution(
                status=STATUS_CCRP,
                model=ballistic_model,
                reason="existing_ccrp",
            )
        if target_distance_m is None:
            return WeaponSolution(
                status=STATUS_NO_TARGET,
                model=ballistic_model,
                reason="target_unavailable",
                target_kind=target_kind,
                target_name=target_name,
            )

        altitude_m = _finite_float(launch_altitude_m, default=-1.0)
        speed_mps = _finite_float(launch_speed_mps, default=-1.0)
        distance_m = _finite_float(target_distance_m, default=-1.0)
        relative_deg = _finite_float(target_relative_deg)
        if altitude_m < 0.0 or speed_mps < 10.0 or distance_m <= 0.0:
            return WeaponSolution(
                status=STATUS_INSUFFICIENT_DATA,
                model=ballistic_model,
                reason="invalid_launch_or_target_telemetry",
                target_kind=target_kind,
                target_name=target_name,
                target_distance_m=max(0.0, distance_m),
            )

        fighter_mach = _mach_from_launch_state(altitude_m, speed_mps, launch_mach)
        table_solution = _guidance_envelope_solution(
            weapon,
            ballistic_model=ballistic_model,
            launch_altitude_m=altitude_m,
            launch_mach=fighter_mach,
            target_distance_m=distance_m,
            target_relative_deg=relative_deg,
            target_kind=target_kind,
            target_name=target_name,
            target_aspect_cosine=target_aspect_cosine,
            ground_closing_speed_mps=ground_closing_speed_mps,
        )
        if table_solution is not None:
            return table_solution

        planform = str(weapon.get("planform") or "")
        if planform == "glide":
            if ballistic_model == WeaponBallisticModelConfig.FOXTHREE_COMPATIBLE:
                try:
                    estimate = _foxthree_compatible_glide_envelope(
                        weapon,
                        launch_altitude_m=altitude_m,
                        launch_speed_mps=speed_mps,
                        target_altitude_m=target_altitude_m,
                        target_distance_m=distance_m,
                    )
                    return _solution_from_envelope(
                        estimate,
                        weapon=weapon,
                        ground_closing_speed_mps=ground_closing_speed_mps,
                        target_distance_m=distance_m,
                        target_relative_deg=relative_deg,
                        target_kind=target_kind,
                        target_name=target_name,
                        ballistic_model=ballistic_model,
                        quality=QUALITY_EXPERIMENTAL,
                        model_reason="foxthree_compatible_glide",
                        within_status=STATUS_WITHIN_EXPERIMENTAL_REFERENCE,
                        beyond_status=STATUS_BEYOND_EXPERIMENTAL_REFERENCE,
                    )
                except ArithmeticError, TypeError, ValueError, OverflowError:
                    return WeaponSolution(
                        status=STATUS_INSUFFICIENT_DATA,
                        quality=QUALITY_NONE,
                        model=ballistic_model,
                        reason="foxthree_compatible_glide_unavailable",
                        target_kind=target_kind,
                        target_name=target_name,
                        target_distance_m=distance_m,
                    )
            return WeaponSolution(
                status=STATUS_INSUFFICIENT_DATA,
                quality=QUALITY_NONE,
                model=ballistic_model,
                reason="glide_envelope_unavailable",
                target_kind=target_kind,
                target_name=target_name,
                target_distance_m=distance_m,
            )

        unsupported_reasons = weapon.get("model_unsupported_reasons")
        if bool(unsupported_reasons) or weapon.get("physics_support") is False:
            return WeaponSolution(
                status=STATUS_INSUFFICIENT_DATA,
                model=ballistic_model,
                reason="conditional_propulsion_unsupported",
                target_kind=target_kind,
                target_name=target_name,
                target_distance_m=distance_m,
            )

        try:
            propulsion = str(weapon.get("propulsion") or "")
            within_status = STATUS_IN_ENVELOPE
            beyond_status = STATUS_OUT_OF_RANGE
            if propulsion == "powered":
                estimate = _powered_envelope(
                    weapon,
                    launch_altitude_m=altitude_m,
                    launch_speed_mps=speed_mps,
                    target_distance_m=distance_m,
                )
                quality = QUALITY_TWO_DIMENSIONAL
                model_reason = "powered_point_mass_2d"
            elif propulsion == "unpowered" and weapon.get("control") == "guided":
                visible_reference = find_visible_trajectory_reference(
                    str(weapon.get("id") or ""),
                    launch_altitude_m=altitude_m,
                    launch_speed_mps=speed_mps,
                    target_altitude_m=target_altitude_m,
                    target_kind=target_kind,
                )
                if visible_reference is not None:
                    estimate = _visible_trajectory_reference_envelope(
                        visible_reference,
                        target_distance_m=distance_m,
                    )
                    model_reason = REASON_PLAYER_VISIBLE_TRAJECTORY_REFERENCE
                else:
                    estimate = _guided_normal_envelope(
                        weapon,
                        launch_altitude_m=altitude_m,
                        launch_speed_mps=speed_mps,
                        target_altitude_m=target_altitude_m,
                        target_distance_m=distance_m,
                        trajectory_func=self._trajectory_func,
                    )
                    model_reason = REASON_GUIDED_BALLISTIC_UNCALIBRATED
                quality = QUALITY_EXPERIMENTAL
                within_status = STATUS_WITHIN_EXPERIMENTAL_REFERENCE
                beyond_status = STATUS_BEYOND_EXPERIMENTAL_REFERENCE
            else:
                return WeaponSolution(
                    status=STATUS_INSUFFICIENT_DATA,
                    model=ballistic_model,
                    reason="unsupported_weapon_model",
                    target_kind=target_kind,
                    target_name=target_name,
                    target_distance_m=distance_m,
                )

            return _solution_from_envelope(
                estimate,
                weapon=weapon,
                ground_closing_speed_mps=ground_closing_speed_mps,
                target_distance_m=distance_m,
                target_relative_deg=relative_deg,
                target_kind=target_kind,
                target_name=target_name,
                ballistic_model=ballistic_model,
                quality=quality,
                model_reason=model_reason,
                within_status=within_status,
                beyond_status=beyond_status,
            )
        except ArithmeticError, TypeError, ValueError, OverflowError:
            return WeaponSolution(
                status=STATUS_SOLVER_ERROR,
                quality=QUALITY_NONE,
                model=ballistic_model,
                reason="solver_exception",
                target_kind=target_kind,
                target_name=target_name,
                target_distance_m=distance_m,
            )


def solve_weapon(
    weapon: Mapping[str, Any] | None,
    **inputs: Any,
) -> WeaponSolution:
    """Functional convenience wrapper around :class:`WeaponSolver`."""

    return WeaponSolver().solve(weapon, **inputs)


__all__ = [
    "ALIGN_TOLERANCE_DEG",
    "VALID_QUALITIES",
    "VALID_STATUSES",
    "WeaponSolution",
    "WeaponSolver",
    "isa_air_density",
    "solve_weapon",
    "uses_existing_ccrp",
]
