# -*- coding: utf-8 -*-
"""Shared navigation presentation helpers for UI surfaces."""

import math
from dataclasses import dataclass
from typing import Any

from bomana.config import Theme, ZoneConfig


@dataclass(frozen=True)
class NavigationTapeModel:
    """Data needed by heading-tape based navigation surfaces."""

    targets: list[dict[str, Any]]
    active_targets_info: list[dict[str, Any]]
    primary_zone: Any | None


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
        except TypeError, ValueError:
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

    for zone in getattr(snap, "zones", []):
        is_primary = bool(primary_zone is not None and zone.id == primary_zone.id)
        targets.append(
            {
                "type": "zone",
                "relative": zone.relative,
                "distance_km": zone.distance_km,
                "is_primary": is_primary,
                "is_target": bool(zone.is_target or is_primary),
            }
        )
        if is_primary:
            active_targets_info.append(
                {
                    "type": "zone",
                    "name": "战区",
                    "icon": "⊚",
                    "relative": zone.relative,
                    "distance_km": zone.distance_km,
                    "ete_str": getattr(zone, "ete_str", ""),
                    "color": Theme.RED,
                }
            )

    if getattr(snap, "friendly_airfield", None):
        af = snap.friendly_airfield
        is_in_front = abs(af.relative) <= 90
        targets.append(
            {
                "type": "friendly",
                "relative": af.relative,
                "distance_km": af.distance_km,
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
                    "relative": af.relative,
                    "distance_km": af.distance_km,
                    "ete_str": getattr(af, "ete_str", ""),
                    "color": Theme.BLUE,
                }
            )

    for af in getattr(snap, "enemy_airfields", []) or []:
        is_in_front = abs(af.relative) <= 90
        targets.append(
            {
                "type": "enemy",
                "relative": af.relative,
                "distance_km": af.distance_km,
                "is_primary": False,
                "is_target": is_in_front,
            }
        )
        if getattr(af, "is_target", False) and is_in_front:
            active_targets_info.append(
                {
                    "type": "enemy",
                    "name": "敌方",
                    "icon": "✈",
                    "relative": af.relative,
                    "distance_km": af.distance_km,
                    "ete_str": getattr(af, "ete_str", ""),
                    "color": Theme.ORANGE,
                }
            )

    if getattr(snap, "zone_destroyed_alert", False):
        for dz in destroyed_zones or []:
            if hasattr(dz, "relative"):
                targets.append(
                    {
                        "type": "destroyed",
                        "relative": dz.relative,
                        "distance_km": dz.distance * ZoneConfig.DISTANCE_SCALE,
                        "is_primary": False,
                    }
                )

    return NavigationTapeModel(
        targets=targets,
        active_targets_info=active_targets_info,
        primary_zone=primary_zone,
    )
