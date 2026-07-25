"""Causal release-state estimation from official 8111 map samples."""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass
from typing import Final

from bomana.core.state import MapInfo, ZoneNavigationState
from bomana.core.terrain_elevation import normalized_map_to_world

TRACK_WINDOW_SECONDS: Final = 0.20
TRACK_WINDOW_JITTER_TOLERANCE_SECONDS: Final = 0.03
TRACK_HISTORY_SECONDS: Final = 0.45
MIN_TRACK_SPAN_SECONDS: Final = 0.09
MIN_TRACK_SAMPLES: Final = 3
MAX_TRACK_FIT_SAMPLES: Final = 4
MIN_RELEASE_SPEED_MS: Final = 10.0
MAX_RELEASE_SPEED_MS: Final = 2_500.0
MAX_TRACK_RESIDUAL_M: Final = 80.0
MAX_TRACK_SAMPLE_AGE_SECONDS: Final = 0.15
MAX_CROSS_TRACK_ERROR_M: Final = 100.0
MIN_BODY_HEADING_VECTOR_NORM: Final = 0.5
MIN_BODY_HEADING_RATE_SPAN_SECONDS: Final = 0.02
MAX_BODY_HEADING_RATE_SPAN_SECONDS: Final = 0.25


@dataclass(frozen=True, slots=True)
class ReleaseTrackEstimate:
    """One causal 2D ground-track estimate."""

    valid: bool = False
    world_x_m: float = 0.0
    world_z_m: float = 0.0
    velocity_x_ms: float = 0.0
    velocity_z_ms: float = 0.0
    ground_speed_ms: float = 0.0
    heading_deg: float = 0.0
    residual_rms_m: float = 0.0
    sample_span_s: float = 0.0
    sample_count: int = 0
    sample_time: float = 0.0
    solution_time: float = 0.0
    sample_age_s: float = 0.0


@dataclass(frozen=True, slots=True)
class TargetTrackGeometry:
    """Target position resolved in the current ground-track frame."""

    distance_m: float
    along_track_m: float
    cross_track_m: float
    direction_x: float
    direction_z: float
    target_world_x_m: float
    target_world_z_m: float


def _linear_fit(
    samples: list[tuple[float, float, float]],
) -> tuple[float, float, float, float, float] | None:
    mean_t = sum(sample[0] for sample in samples) / len(samples)
    mean_x = sum(sample[1] for sample in samples) / len(samples)
    mean_z = sum(sample[2] for sample in samples) / len(samples)
    variance_t = sum((sample[0] - mean_t) ** 2 for sample in samples)
    if variance_t <= 1e-9:
        return None
    velocity_x = sum((sample[0] - mean_t) * (sample[1] - mean_x) for sample in samples) / variance_t
    velocity_z = sum((sample[0] - mean_t) * (sample[2] - mean_z) for sample in samples) / variance_t
    latest_t = samples[-1][0]
    fitted_latest_x = mean_x + velocity_x * (latest_t - mean_t)
    fitted_latest_z = mean_z + velocity_z * (latest_t - mean_t)
    residual_sq = 0.0
    for timestamp, world_x, world_z in samples:
        fitted_x = mean_x + velocity_x * (timestamp - mean_t)
        fitted_z = mean_z + velocity_z * (timestamp - mean_t)
        residual_sq += (world_x - fitted_x) ** 2 + (world_z - fitted_z) ** 2
    residual = math.sqrt(residual_sq / len(samples))
    return velocity_x, velocity_z, fitted_latest_x, fitted_latest_z, residual


def estimate_release_track(
    samples: deque[tuple[float, float, float]],
    *,
    now: float,
) -> ReleaseTrackEstimate:
    """Fit a causal OLS track from at most four samples in the latest 0.20 s."""

    if not samples:
        return ReleaseTrackEstimate(solution_time=now)

    latest_sample_time = samples[-1][0]
    raw_sample_age = now - latest_sample_time
    sample_age = max(0.0, raw_sample_age)
    timing = {
        "sample_time": latest_sample_time,
        "solution_time": now,
        "sample_age_s": sample_age,
    }
    # The regression window belongs to the observation timeline. Endpoint
    # latency is handled separately by bounded projection to ``now``.
    cutoff = latest_sample_time - (TRACK_WINDOW_SECONDS + TRACK_WINDOW_JITTER_TOLERANCE_SECONDS)
    selected = [sample for sample in samples if sample[0] >= cutoff]
    if len(selected) > MAX_TRACK_FIT_SAMPLES:
        selected = selected[-MAX_TRACK_FIT_SAMPLES:]
    if len(selected) < MIN_TRACK_SAMPLES:
        return ReleaseTrackEstimate(sample_count=len(selected), **timing)

    span = selected[-1][0] - selected[0][0]
    if span < MIN_TRACK_SPAN_SECONDS:
        return ReleaseTrackEstimate(
            sample_span_s=span,
            sample_count=len(selected),
            **timing,
        )

    fit = _linear_fit(selected)
    if fit is None:
        return ReleaseTrackEstimate(
            sample_span_s=span,
            sample_count=len(selected),
            **timing,
        )
    velocity_x, velocity_z, latest_x, latest_z, residual = fit
    speed = math.hypot(velocity_x, velocity_z)
    if not MIN_RELEASE_SPEED_MS <= speed <= MAX_RELEASE_SPEED_MS:
        return ReleaseTrackEstimate(
            ground_speed_ms=speed,
            sample_span_s=span,
            sample_count=len(selected),
            **timing,
        )

    projected_x = latest_x + velocity_x * sample_age
    projected_z = latest_z + velocity_z * sample_age
    valid = (
        raw_sample_age >= -1e-6
        and residual <= MAX_TRACK_RESIDUAL_M
        and sample_age <= MAX_TRACK_SAMPLE_AGE_SECONDS
    )
    heading = (math.degrees(math.atan2(velocity_x, velocity_z)) + 360.0) % 360.0
    return ReleaseTrackEstimate(
        valid=valid,
        world_x_m=projected_x,
        world_z_m=projected_z,
        velocity_x_ms=velocity_x,
        velocity_z_ms=velocity_z,
        ground_speed_ms=speed,
        heading_deg=heading,
        residual_rms_m=residual,
        sample_span_s=span,
        sample_count=len(selected),
        **timing,
    )


def reset_release_track(nav: ZoneNavigationState) -> None:
    nav.release_track_samples.clear()
    nav.release_body_heading_samples.clear()
    nav.release_track_valid = False
    nav.release_world_x_m = 0.0
    nav.release_world_z_m = 0.0
    nav.release_velocity_x_ms = 0.0
    nav.release_velocity_z_ms = 0.0
    nav.release_ground_speed_ms = 0.0
    nav.release_track_heading_deg = 0.0
    nav.release_track_residual_m = 0.0
    nav.release_track_sample_span_s = 0.0
    nav.release_track_sample_time = 0.0
    nav.release_track_solution_time = 0.0
    nav.release_track_sample_age_s = 0.0
    nav.release_body_heading_rate_deg_s = 0.0
    nav.release_body_heading_rate_available = False
    nav.ground_speed = 0.0


def _apply_track_estimate(
    nav: ZoneNavigationState,
    estimate: ReleaseTrackEstimate,
) -> None:
    nav.release_track_valid = estimate.valid
    nav.release_world_x_m = estimate.world_x_m
    nav.release_world_z_m = estimate.world_z_m
    nav.release_velocity_x_ms = estimate.velocity_x_ms
    nav.release_velocity_z_ms = estimate.velocity_z_ms
    nav.release_ground_speed_ms = estimate.ground_speed_ms
    nav.release_track_heading_deg = estimate.heading_deg
    nav.release_track_residual_m = estimate.residual_rms_m
    nav.release_track_sample_span_s = estimate.sample_span_s
    nav.release_track_sample_time = estimate.sample_time
    nav.release_track_solution_time = estimate.solution_time
    nav.release_track_sample_age_s = estimate.sample_age_s
    # Preserve the established normalized-unit contract for non-ballistic UI.
    nav.ground_speed = estimate.ground_speed_ms / 100_000.0 if estimate.valid else 0.0


def _angle_delta_deg(current: float, previous: float) -> float:
    return (current - previous + 180.0) % 360.0 - 180.0


def _update_body_heading_rate(
    nav: ZoneNavigationState,
    *,
    sample_time: float,
    direction_x: float | None,
    direction_y: float | None,
) -> None:
    """Update a robust body-heading rate used only by the precision gate."""

    if direction_x is None or direction_y is None:
        return
    try:
        dx = float(direction_x)
        dy = float(direction_y)
    except TypeError, ValueError:
        return
    if not all(math.isfinite(value) for value in (dx, dy)):
        return
    if math.hypot(dx, dy) < MIN_BODY_HEADING_VECTOR_NORM:
        return

    heading = (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0
    samples = nav.release_body_heading_samples
    if samples and sample_time < samples[-1][0] - 1e-6:
        samples.clear()
    if samples and sample_time <= samples[-1][0]:
        return
    samples.append((sample_time, heading))
    history_cutoff = sample_time - TRACK_HISTORY_SECONDS
    while samples and samples[0][0] < history_cutoff:
        samples.popleft()

    rates: list[float] = []
    selected = list(samples)[-4:]
    for (previous_time, previous_heading), (current_time, current_heading) in zip(
        selected[:-1],
        selected[1:],
        strict=True,
    ):
        dt = current_time - previous_time
        if not MIN_BODY_HEADING_RATE_SPAN_SECONDS <= dt <= MAX_BODY_HEADING_RATE_SPAN_SECONDS:
            continue
        rates.append(_angle_delta_deg(current_heading, previous_heading) / dt)
    if not rates:
        nav.release_body_heading_rate_deg_s = 0.0
        nav.release_body_heading_rate_available = False
        return
    nav.release_body_heading_rate_deg_s = statistics.median(rates)
    nav.release_body_heading_rate_available = True


def update_release_track(
    nav: ZoneNavigationState,
    *,
    normalized_x: float,
    normalized_y: float,
    map_info: MapInfo | None,
    now: float | None = None,
    sample_time: float | None = None,
    solution_time: float | None = None,
    body_direction_x: float | None = None,
    body_direction_y: float | None = None,
) -> ReleaseTrackEstimate:
    """Append one 8111 map position and update the navigation release state."""

    resolved_sample_time = sample_time if sample_time is not None else now
    resolved_solution_time = solution_time if solution_time is not None else now
    if map_info is None or not map_info.valid:
        reset_release_track(nav)
        return ReleaseTrackEstimate()
    world = normalized_map_to_world(
        normalized_x,
        normalized_y,
        map_info.map_min,
        map_info.map_max,
    )
    if (
        world is None
        or resolved_sample_time is None
        or resolved_solution_time is None
        or not math.isfinite(resolved_sample_time)
        or not math.isfinite(resolved_solution_time)
    ):
        reset_release_track(nav)
        return ReleaseTrackEstimate()

    if nav.release_track_samples and (
        resolved_sample_time < nav.release_track_samples[-1][0] - 1e-6
    ):
        reset_release_track(nav)

    if nav.release_track_samples and resolved_sample_time <= nav.release_track_samples[-1][0]:
        estimate = estimate_release_track(
            nav.release_track_samples,
            now=resolved_solution_time,
        )
        _apply_track_estimate(nav, estimate)
        return estimate

    _update_body_heading_rate(
        nav,
        sample_time=resolved_sample_time,
        direction_x=body_direction_x,
        direction_y=body_direction_y,
    )
    nav.release_track_samples.append((resolved_sample_time, world[0], world[1]))
    history_cutoff = resolved_sample_time - TRACK_HISTORY_SECONDS
    while nav.release_track_samples and nav.release_track_samples[0][0] < history_cutoff:
        nav.release_track_samples.popleft()

    estimate = estimate_release_track(nav.release_track_samples, now=resolved_solution_time)
    _apply_track_estimate(nav, estimate)
    return estimate


def target_track_geometry(
    nav: ZoneNavigationState,
    *,
    target_x: float,
    target_y: float,
    map_info: MapInfo | None,
) -> TargetTrackGeometry | None:
    """Resolve one target into along/cross-track metres."""

    if not nav.release_track_valid or map_info is None or not map_info.valid:
        return None
    target_world = normalized_map_to_world(
        target_x,
        target_y,
        map_info.map_min,
        map_info.map_max,
    )
    if target_world is None:
        return None
    speed = math.hypot(nav.release_velocity_x_ms, nav.release_velocity_z_ms)
    if speed < MIN_RELEASE_SPEED_MS:
        return None
    direction_x = nav.release_velocity_x_ms / speed
    direction_z = nav.release_velocity_z_ms / speed
    delta_x = target_world[0] - nav.release_world_x_m
    delta_z = target_world[1] - nav.release_world_z_m
    along = delta_x * direction_x + delta_z * direction_z
    cross = direction_x * delta_z - direction_z * delta_x
    return TargetTrackGeometry(
        distance_m=math.hypot(delta_x, delta_z),
        along_track_m=along,
        cross_track_m=cross,
        direction_x=direction_x,
        direction_z=direction_z,
        target_world_x_m=target_world[0],
        target_world_z_m=target_world[1],
    )


__all__ = [
    "MAX_CROSS_TRACK_ERROR_M",
    "ReleaseTrackEstimate",
    "TargetTrackGeometry",
    "estimate_release_track",
    "reset_release_track",
    "target_track_geometry",
    "update_release_track",
]
