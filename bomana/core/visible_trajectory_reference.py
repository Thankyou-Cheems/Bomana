"""Versioned player-visible trajectory observations used as narrow references."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from bomana.config.static_data import VISIBLE_TRAJECTORY_REFERENCES_JSON
from bomana.utils.file_utils import resource_path

SCHEMA_VERSION = 1
GROUND_TARGET_KINDS = frozenset({"ground", "poi", "zone"})

# These tolerances define a deliberately small calibration neighbourhood. They
# are model policy, not precision claims about the transcribed UI values.
LAUNCH_ALTITUDE_TOLERANCE_M = 100.0
LAUNCH_SPEED_TOLERANCE_MPS = 10.0
TARGET_ALTITUDE_TOLERANCE_M = 150.0

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)


class VisibleTrajectoryReferenceError(ValueError):
    """Raised when the authored visible-trajectory asset is invalid."""


@dataclass(frozen=True)
class VisibleTrajectoryPoint:
    flight_time_s: float
    speed_mps: float
    flight_distance_m: float
    x_m: float
    y_m: float


@dataclass(frozen=True)
class VisibleTrajectoryReference:
    id: str
    weapon_id: str
    game_version: str
    capture_date: str
    source_kind: str
    launch_altitude_m: float
    launch_speed_mps: float
    target_altitude_m: float
    target_speed_mps: float
    requested_horizontal_distance_m: float
    target_reached_observed: bool
    runtime_reference: bool
    verified_reach_m: float
    points: tuple[VisibleTrajectoryPoint, ...]

    @property
    def duration_s(self) -> float:
        return self.points[-1].flight_time_s

    def time_at_horizontal_distance(self, distance_m: float) -> float:
        """Interpolate time along the observed path, clamped to its endpoints."""

        distance = max(0.0, _finite_number(distance_m, label="distance_m"))
        if distance <= self.points[0].x_m:
            return self.points[0].flight_time_s
        for lower, upper in zip(self.points, self.points[1:], strict=False):
            if distance > upper.x_m:
                continue
            span_m = upper.x_m - lower.x_m
            if span_m <= 0.0:
                return upper.flight_time_s
            fraction = (distance - lower.x_m) / span_m
            return lower.flight_time_s + fraction * (upper.flight_time_s - lower.flight_time_s)
        return self.points[-1].flight_time_s


def _finite_number(value: Any, *, label: str) -> float:
    try:
        number = float(value)
    except _NUMERIC_PARSE_ERRORS as exc:
        raise VisibleTrajectoryReferenceError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise VisibleTrajectoryReferenceError(f"{label} must be finite")
    return number


def _non_empty_string(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise VisibleTrajectoryReferenceError(f"{label} must be a non-empty string")
    return text


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VisibleTrajectoryReferenceError(f"{label} must be an object")
    return value


def _parse_point(value: Any, *, observation_id: str, index: int) -> VisibleTrajectoryPoint:
    point = _mapping(value, label=f"{observation_id}.points[{index}]")
    values = {
        field: _finite_number(
            point.get(field),
            label=f"{observation_id}.points[{index}].{field}",
        )
        for field in ("flight_time_s", "speed_mps", "flight_distance_m", "x_m", "y_m")
    }
    if any(number < 0.0 for number in values.values()):
        raise VisibleTrajectoryReferenceError(
            f"{observation_id}.points[{index}] values must be non-negative"
        )
    return VisibleTrajectoryPoint(**values)


def _parse_reference(
    value: Any,
    *,
    game_version: str,
    capture_date: str,
    source_kind: str,
) -> VisibleTrajectoryReference:
    raw = _mapping(value, label="observation")
    observation_id = _non_empty_string(raw.get("id"), label="observation.id")
    conditions = _mapping(raw.get("conditions"), label=f"{observation_id}.conditions")
    points_value = raw.get("points")
    if not isinstance(points_value, list) or len(points_value) < 2:
        raise VisibleTrajectoryReferenceError(
            f"{observation_id}.points must contain at least 2 items"
        )
    points = tuple(
        _parse_point(point, observation_id=observation_id, index=index)
        for index, point in enumerate(points_value)
    )
    if points[0].flight_time_s != 0.0 or points[0].x_m != 0.0:
        raise VisibleTrajectoryReferenceError(f"{observation_id} must start at time/x zero")
    for lower, upper in zip(points, points[1:], strict=False):
        if (
            upper.flight_time_s <= lower.flight_time_s
            or upper.flight_distance_m <= lower.flight_distance_m
            or upper.x_m <= lower.x_m
        ):
            raise VisibleTrajectoryReferenceError(
                f"{observation_id} time, path distance, and horizontal position must increase"
            )

    target_reached = raw.get("target_reached_observed") is True
    runtime_reference = raw.get("runtime_reference") is True
    verified_reach_m = _finite_number(
        raw.get("verified_reach_m"), label=f"{observation_id}.verified_reach_m"
    )
    if verified_reach_m < 0.0:
        raise VisibleTrajectoryReferenceError(
            f"{observation_id}.verified_reach_m must be non-negative"
        )
    if runtime_reference:
        if not target_reached or verified_reach_m <= 0.0:
            raise VisibleTrajectoryReferenceError(
                f"{observation_id} runtime reference must visibly reach a positive target"
            )
        endpoint_tolerance_m = max(25.0, verified_reach_m * 0.005)
        if abs(points[-1].x_m - verified_reach_m) > endpoint_tolerance_m:
            raise VisibleTrajectoryReferenceError(
                f"{observation_id} terminal x is inconsistent with verified reach"
            )

    return VisibleTrajectoryReference(
        id=observation_id,
        weapon_id=_non_empty_string(raw.get("weapon_id"), label=f"{observation_id}.weapon_id"),
        game_version=game_version,
        capture_date=capture_date,
        source_kind=source_kind,
        launch_altitude_m=_finite_number(
            conditions.get("launch_altitude_m"),
            label=f"{observation_id}.conditions.launch_altitude_m",
        ),
        launch_speed_mps=_finite_number(
            conditions.get("launch_speed_mps"),
            label=f"{observation_id}.conditions.launch_speed_mps",
        ),
        target_altitude_m=_finite_number(
            conditions.get("target_altitude_m"),
            label=f"{observation_id}.conditions.target_altitude_m",
        ),
        target_speed_mps=_finite_number(
            conditions.get("target_speed_mps"),
            label=f"{observation_id}.conditions.target_speed_mps",
        ),
        requested_horizontal_distance_m=_finite_number(
            conditions.get("requested_horizontal_distance_m"),
            label=f"{observation_id}.conditions.requested_horizontal_distance_m",
        ),
        target_reached_observed=target_reached,
        runtime_reference=runtime_reference,
        verified_reach_m=verified_reach_m,
        points=points,
    )


def load_visible_trajectory_references(
    path: str | Path = VISIBLE_TRAJECTORY_REFERENCES_JSON,
) -> tuple[VisibleTrajectoryReference, ...]:
    """Load and validate the authored visible-trajectory reference asset."""

    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = Path(resource_path(resolved.as_posix()))
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VisibleTrajectoryReferenceError(
            f"unable to read trajectory references: {resolved}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise VisibleTrajectoryReferenceError(
            f"invalid trajectory reference JSON: {resolved}"
        ) from exc
    root = _mapping(payload, label="trajectory reference root")
    if root.get("schema_version") != SCHEMA_VERSION:
        raise VisibleTrajectoryReferenceError(
            f"trajectory reference schema must be {SCHEMA_VERSION}"
        )
    meta = _mapping(root.get("meta"), label="trajectory reference meta")
    game_version = _non_empty_string(meta.get("game_version"), label="meta.game_version")
    capture_date = _non_empty_string(meta.get("capture_date"), label="meta.capture_date")
    source_kind = _non_empty_string(meta.get("source_kind"), label="meta.source_kind")
    if source_kind != "player_visible_war_thunder_ui":
        raise VisibleTrajectoryReferenceError("unsupported trajectory reference source kind")
    observations = root.get("observations")
    if not isinstance(observations, list) or not observations:
        raise VisibleTrajectoryReferenceError("trajectory references must contain observations")
    references = tuple(
        _parse_reference(
            observation,
            game_version=game_version,
            capture_date=capture_date,
            source_kind=source_kind,
        )
        for observation in observations
    )
    ids = [reference.id for reference in references]
    if len(ids) != len(set(ids)):
        raise VisibleTrajectoryReferenceError("trajectory reference IDs must be unique")
    return references


@lru_cache(maxsize=1)
def get_visible_trajectory_references() -> tuple[VisibleTrajectoryReference, ...]:
    return load_visible_trajectory_references()


def find_visible_trajectory_reference(
    weapon_id: str,
    *,
    launch_altitude_m: float,
    launch_speed_mps: float,
    target_altitude_m: float | None,
    target_kind: str,
    references: Iterable[VisibleTrajectoryReference] | None = None,
) -> VisibleTrajectoryReference | None:
    """Match only the small, documented neighbourhood around a visible curve."""

    if str(target_kind or "").strip().casefold() not in GROUND_TARGET_KINDS:
        return None
    if references is None:
        try:
            references = get_visible_trajectory_references()
        except VisibleTrajectoryReferenceError:
            return None
    try:
        launch_altitude = float(launch_altitude_m)
        launch_speed = float(launch_speed_mps)
        target_altitude = None if target_altitude_m is None else float(target_altitude_m)
    except _NUMERIC_PARSE_ERRORS:
        return None
    if not math.isfinite(launch_altitude) or not math.isfinite(launch_speed):
        return None
    if target_altitude is not None and not math.isfinite(target_altitude):
        return None

    for reference in references:
        if not reference.runtime_reference or reference.weapon_id != str(weapon_id or ""):
            continue
        if reference.target_speed_mps != 0.0:
            continue
        if abs(launch_altitude - reference.launch_altitude_m) > LAUNCH_ALTITUDE_TOLERANCE_M:
            continue
        if abs(launch_speed - reference.launch_speed_mps) > LAUNCH_SPEED_TOLERANCE_MPS:
            continue
        if (
            target_altitude is not None
            and abs(target_altitude - reference.target_altitude_m) > TARGET_ALTITUDE_TOLERANCE_M
        ):
            continue
        return reference
    return None


__all__ = [
    "GROUND_TARGET_KINDS",
    "LAUNCH_ALTITUDE_TOLERANCE_M",
    "LAUNCH_SPEED_TOLERANCE_MPS",
    "SCHEMA_VERSION",
    "TARGET_ALTITUDE_TOLERANCE_M",
    "VisibleTrajectoryPoint",
    "VisibleTrajectoryReference",
    "VisibleTrajectoryReferenceError",
    "find_visible_trajectory_reference",
    "get_visible_trajectory_references",
    "load_visible_trajectory_references",
]
