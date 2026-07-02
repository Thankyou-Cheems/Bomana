"""Shared navigation presentation helpers for UI surfaces."""

import math
from dataclasses import dataclass
from typing import Any

from bomana.config import Theme, ZoneConfig

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except _NUMERIC_PARSE_ERRORS:
        return default
    return number if math.isfinite(number) else default


@dataclass(frozen=True)
class NavigationTapeModel:
    """Data needed by heading-tape based navigation surfaces."""

    targets: list[dict[str, Any]]
    active_targets_info: list[dict[str, Any]]
    primary_zone: Any | None
    primary_target: Any | None = None
    primary_target_info: dict[str, Any] | None = None


def select_display_primary_zone(zones: list[Any]) -> Any | None:
    """Pick a UI primary zone even when core nav has no active target.

    Some spawn headings can leave all zones outside the target gate. The list
    still has valid rows, but heading-tape overflow cues need one display
    primary. This fallback is UI-only and does not change core lock state.
    """
    target_zone = next((zone for zone in zones if getattr(zone, "is_target", False)), None)
    if target_zone is not None or not zones:
        return target_zone

    ranked: list[tuple[float, float, Any]] = []
    for zone in zones:
        try:
            rel = float(getattr(zone, "relative", 0.0))
            dist = float(getattr(zone, "distance_km", 0.0))
        except _NUMERIC_PARSE_ERRORS:
            continue
        if math.isfinite(rel) and math.isfinite(dist):
            ranked.append((abs(rel), dist, zone))

    if ranked:
        ranked.sort(key=lambda item: (item[0], item[1]))
        return ranked[0][2]
    return zones[0]


def build_navigation_tape_model(
    snap: Any,
    *,
    destroyed_zones: list[Any] | None = None,
) -> NavigationTapeModel:
    """Build shared heading-tape target data for main and standalone nav UI."""
    targets: list[dict[str, Any]] = []
    active_targets_info: list[dict[str, Any]] = []
    primary_zone = select_display_primary_zone(getattr(snap, "zones", []))
    interest_point = getattr(snap, "interest_point", None)
    primary_target = primary_zone
    primary_target_info: dict[str, Any] | None = None

    if interest_point is not None:
        poi_relative = _safe_float(getattr(interest_point, "relative", 0.0))
        poi_distance = _safe_float(getattr(interest_point, "distance_km", 0.0))
        poi_name = str(getattr(interest_point, "name", "") or "兴趣点")
        targets.append(
            {
                "type": "poi",
                "relative": poi_relative,
                "distance_km": poi_distance,
                "is_primary": False,
                "is_target": True,
                "name": poi_name,
            }
        )

    for zone in getattr(snap, "zones", []):
        zone_id = getattr(zone, "id", None)
        primary_zone_id = getattr(primary_zone, "id", None)
        is_primary = bool(primary_zone is not None and zone_id == primary_zone_id)
        zone_relative = _safe_float(getattr(zone, "relative", 0.0))
        zone_distance = _safe_float(getattr(zone, "distance_km", 0.0))
        zone_is_target = bool(getattr(zone, "is_target", False))
        targets.append(
            {
                "type": "zone",
                "relative": zone_relative,
                "distance_km": zone_distance,
                "is_primary": is_primary,
                "is_target": bool(zone_is_target or is_primary),
            }
        )
        if is_primary:
            primary_target_info = {
                "type": "zone",
                "name": "战区",
                "icon": "⊚",
                "relative": zone_relative,
                "distance_km": zone_distance,
                "ete_str": getattr(zone, "ete_str", ""),
                "color": Theme.RED,
            }
            active_targets_info.append(primary_target_info)

    if getattr(snap, "friendly_airfield", None):
        af = snap.friendly_airfield
        af_relative = _safe_float(getattr(af, "relative", 0.0))
        af_distance = _safe_float(getattr(af, "distance_km", 0.0))
        is_in_front = abs(af_relative) <= 90
        targets.append(
            {
                "type": "friendly",
                "relative": af_relative,
                "distance_km": af_distance,
                "is_primary": False,
                "is_target": is_in_front,
            }
        )
        if is_in_front:
            active_targets_info.append(
                {
                    "type": "friendly",
                    "name": "友方",
                    "icon": "✈",
                    "relative": af_relative,
                    "distance_km": af_distance,
                    "ete_str": getattr(af, "ete_str", ""),
                    "color": Theme.BLUE,
                }
            )

    for af in getattr(snap, "enemy_airfields", []) or []:
        af_relative = _safe_float(getattr(af, "relative", 0.0))
        af_distance = _safe_float(getattr(af, "distance_km", 0.0))
        is_in_front = abs(af_relative) <= 90
        is_target = bool(getattr(af, "is_target", False) and is_in_front)
        targets.append(
            {
                "type": "enemy",
                "relative": af_relative,
                "distance_km": af_distance,
                "is_primary": False,
                "is_target": is_target,
            }
        )
        if is_target:
            active_targets_info.append(
                {
                    "type": "enemy",
                    "name": "敌方",
                    "icon": "✈",
                    "relative": af_relative,
                    "distance_km": af_distance,
                    "ete_str": getattr(af, "ete_str", ""),
                    "color": Theme.ORANGE,
                }
            )

    if getattr(snap, "zone_destroyed_alert", False):
        for dz in destroyed_zones or []:
            if hasattr(dz, "relative"):
                distance_km = getattr(dz, "distance_km", None)
                if distance_km is None and hasattr(dz, "distance"):
                    distance_km = dz.distance * ZoneConfig.DISTANCE_SCALE
                targets.append(
                    {
                        "type": "destroyed",
                        "relative": dz.relative,
                        "distance_km": float(distance_km or 0.0),
                        "is_primary": False,
                    }
                )

    return NavigationTapeModel(
        targets=targets,
        active_targets_info=active_targets_info,
        primary_zone=primary_zone,
        primary_target=primary_target,
        primary_target_info=primary_target_info,
    )
