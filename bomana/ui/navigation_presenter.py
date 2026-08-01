"""Shared navigation presentation helpers for UI surfaces."""

import math
from dataclasses import dataclass
from typing import Any

from bomana.config.settings import ZoneConfig
from bomana.core import navigation
from bomana.ui.theme import Theme
from bomana.utils.math_utils import calculate_relative_bearing

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)
AAM_NAVIGATION_NOTICE = "战区解算已暂停，仅进行导航"


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
    mode_notice: str = ""


def _snapshot_map_target(snap: Any, point: Any) -> tuple[float, float] | None:
    """Project one normalized immutable map point into tape-relative coordinates."""
    try:
        px = float(snap.map_player_x)
        py = float(snap.map_player_y)
        tx = float(point.x)
        ty = float(point.y)
        heading = float(getattr(snap, "player_heading", 0.0))
    except (*_NUMERIC_PARSE_ERRORS, AttributeError):
        return None
    if not all(math.isfinite(value) for value in (px, py, tx, ty, heading)):
        return None

    scale: tuple[float, float] | None = None
    try:
        scale_x = float(snap.map_scale_x_m)
        scale_y = float(snap.map_scale_y_m)
        if math.isfinite(scale_x) and math.isfinite(scale_y) and scale_x > 0 and scale_y > 0:
            scale = (scale_x, scale_y)
    except (*_NUMERIC_PARSE_ERRORS, AttributeError):
        pass

    bearing, distance_norm = navigation.bearing_distance_norm(px, py, tx, ty, scale)
    distance_km = distance_norm * ZoneConfig.DISTANCE_SCALE
    relative = calculate_relative_bearing(heading, bearing)
    if not (math.isfinite(distance_km) and math.isfinite(relative)) or distance_km <= 0.0:
        return None
    return relative, distance_km


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
    aam_navigation = str(getattr(snap, "weapon_role", "") or "").strip().lower() == "aam"
    bombing_target_mode = (
        str(getattr(snap, "bombing_target_mode", "zone") or "zone").strip().lower()
    )
    poi_mode = not aam_navigation and bombing_target_mode == "poi"
    primary_zone = (
        None
        if aam_navigation or poi_mode
        else select_display_primary_zone(getattr(snap, "zones", []))
    )
    interest_point = getattr(snap, "interest_point", None)
    poi_navigation = poi_mode and interest_point is not None
    primary_target = interest_point if poi_navigation else primary_zone
    primary_target_info: dict[str, Any] | None = None
    mode_notice = AAM_NAVIGATION_NOTICE if aam_navigation else ""

    traceback_point = getattr(snap, "traceback_point", None)
    if traceback_point is not None:
        traceback_relative = _safe_float(getattr(traceback_point, "relative", 0.0))
        traceback_distance = _safe_float(getattr(traceback_point, "distance_km", 0.0))
        targets.append(
            {
                "type": "traceback",
                "relative": traceback_relative,
                "distance_km": traceback_distance,
                "is_primary": False,
                "is_target": True,
                "name": str(getattr(traceback_point, "name", "") or "上次坠毁点"),
            }
        )

    if interest_point is not None and not aam_navigation:
        poi_relative = _safe_float(getattr(interest_point, "relative", 0.0))
        poi_distance = _safe_float(getattr(interest_point, "distance_km", 0.0))
        poi_name = str(getattr(interest_point, "name", "") or "兴趣点")
        targets.append(
            {
                "type": "poi",
                "relative": poi_relative,
                "distance_km": poi_distance,
                "is_primary": poi_navigation,
                "is_target": True,
                "name": poi_name,
            }
        )
        if poi_navigation:
            primary_target_info = {
                "type": "poi",
                "name": poi_name,
                "icon": "◆",
                "relative": poi_relative,
                "distance_km": poi_distance,
                "ete_str": getattr(interest_point, "ete_str", ""),
                "color": Theme.YELLOW,
            }
            active_targets_info.append(primary_target_info)

    if aam_navigation:
        seen_candidates: set[tuple[str, str]] = set()
        for point in getattr(snap, "map_points", ()) or ():
            point_kind = str(getattr(point, "kind", "") or "")
            if point_kind not in {"hostile_aircraft", "poi"}:
                continue
            projected = _snapshot_map_target(snap, point)
            if projected is None:
                continue
            point_id = str(getattr(point, "id", "") or "")
            target_type = "hostile_aircraft" if point_kind == "hostile_aircraft" else "poi"
            candidate_key = (target_type, point_id)
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            relative, distance_km = projected
            targets.append(
                {
                    "type": target_type,
                    "relative": relative,
                    "distance_km": distance_km,
                    "is_primary": False,
                    "is_target": True,
                    "name": str(
                        getattr(point, "label", "")
                        or ("敌机" if target_type == "hostile_aircraft" else "兴趣点")
                    ),
                }
            )

    for zone in getattr(snap, "zones", []):
        zone_id = getattr(zone, "id", None)
        primary_zone_id = getattr(primary_zone, "id", None)
        is_primary = bool(
            not aam_navigation
            and not poi_mode
            and primary_zone is not None
            and zone_id == primary_zone_id
        )
        zone_relative = _safe_float(getattr(zone, "relative", 0.0))
        zone_distance = _safe_float(getattr(zone, "distance_km", 0.0))
        zone_is_target = bool(
            not aam_navigation and not poi_mode and getattr(zone, "is_target", False)
        )
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
        mode_notice=mode_notice,
    )
