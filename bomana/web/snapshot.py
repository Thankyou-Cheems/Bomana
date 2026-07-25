"""Versioned, privacy-filtered projection for the Bomana Web Cockpit."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any

from bomana.config.feature_profile import (
    ENABLE_AIRFIELDS,
    ENABLE_CCRP,
    ENABLE_CHECKLIST,
    ENABLE_FUEL,
    ENABLE_ZONES,
)
from bomana.core.state import (
    AirfieldDisplayInfo,
    NavigationPointDisplayInfo,
    Phase,
    TacticalMapPoint,
    UISnapshot,
    ZoneDisplayInfo,
)

SCHEMA_VERSION = 1
MAX_MAP_IMAGE_BYTES = 4 * 1024 * 1024
MAX_MAP_ICON_FONT_BYTES = 1024 * 1024
HOSTILE_MAP_KINDS = frozenset(
    ("hostile_aircraft", "hostile_ground", "hostile_naval", "hostile_unit")
)


@dataclass(frozen=True)
class DashboardCapabilities:
    navigation: bool
    fuel: bool
    checklist: bool
    weapon: bool

    @classmethod
    def current_build(cls) -> DashboardCapabilities:
        return cls(
            navigation=bool(ENABLE_ZONES or ENABLE_AIRFIELDS),
            fuel=bool(ENABLE_FUEL),
            checklist=bool(ENABLE_CHECKLIST),
            weapon=bool(ENABLE_CCRP),
        )


@dataclass(frozen=True)
class PublishedDashboardSnapshot:
    sequence: int
    generated_at: float
    snapshot: UISnapshot
    checklist_items: tuple[str, ...]
    capabilities: DashboardCapabilities
    map_image_available: bool = False
    map_image_revision: int = 0


@dataclass(frozen=True)
class PublishedMapImage:
    revision: int
    content_type: str
    body: bytes


@dataclass(frozen=True)
class PublishedMapIconFont:
    body: bytes


class DashboardSnapshotStore:
    """Thread-safe handoff from the Tk refresh loop to HTTP workers."""

    def __init__(self, *, wall_time=time.time) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._latest: PublishedDashboardSnapshot | None = None
        self._map_image: PublishedMapImage | None = None
        self._map_icon_font: PublishedMapIconFont | None = None
        self._wall_time = wall_time

    def publish(self, snapshot: UISnapshot, checklist_items: list[str] | tuple[str, ...]) -> None:
        safe_items = tuple(str(item).strip() for item in checklist_items if str(item).strip())[:16]
        with self._lock:
            self._sequence += 1
            self._latest = PublishedDashboardSnapshot(
                sequence=self._sequence,
                generated_at=max(0.0, float(self._wall_time())),
                snapshot=snapshot,
                checklist_items=safe_items,
                capabilities=DashboardCapabilities.current_build(),
                map_image_available=self._map_image is not None,
                map_image_revision=(self._map_image.revision if self._map_image else 0),
            )

    def read(self) -> PublishedDashboardSnapshot | None:
        with self._lock:
            return self._latest

    def publish_map_image(self, body: bytes, content_type: str) -> bool:
        safe_body = bytes(body)
        safe_type = str(content_type)
        if (
            not safe_body
            or len(safe_body) > MAX_MAP_IMAGE_BYTES
            or safe_type not in {"image/png", "image/jpeg"}
        ):
            return False
        with self._lock:
            current = self._map_image
            if (
                current is not None
                and current.content_type == safe_type
                and current.body == safe_body
            ):
                return False
            revision = 1 if current is None else current.revision + 1
            self._map_image = PublishedMapImage(revision, safe_type, safe_body)
            return True

    def read_map_image(self) -> PublishedMapImage | None:
        with self._lock:
            return self._map_image

    def publish_map_icon_font(self, body: bytes) -> bool:
        safe_body = bytes(body)
        if (
            not safe_body.startswith(b"\x00\x01\x00\x00")
            or len(safe_body) > MAX_MAP_ICON_FONT_BYTES
        ):
            return False
        with self._lock:
            if self._map_icon_font is not None and self._map_icon_font.body == safe_body:
                return False
            self._map_icon_font = PublishedMapIconFont(safe_body)
            return True

    def read_map_icon_font(self) -> PublishedMapIconFont | None:
        with self._lock:
            return self._map_icon_font


_PHASE_LABELS = {
    Phase.IDLE: "等待游戏",
    Phase.HANGAR: "机库",
    Phase.ARMING: "准备出击",
    Phase.ALIVE: "任务中",
    Phase.LOSS_PENDING: "状态确认中",
    Phase.WAIT_NEXT: "等待复活",
}


def _number(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except TypeError, ValueError:
        result = 0.0
    if not math.isfinite(result):
        result = 0.0
    if minimum is not None:
        result = max(float(minimum), result)
    if maximum is not None:
        result = min(float(maximum), result)
    return result


def _optional_number(
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(result):
        return None
    if minimum is not None:
        result = max(float(minimum), result)
    if maximum is not None:
        result = min(float(maximum), result)
    return result


def _nav_item(
    item: ZoneDisplayInfo | AirfieldDisplayInfo | NavigationPointDisplayInfo,
    *,
    name: str,
    kind: str,
) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "name": name,
        "kind": kind,
        "distance_km": _number(item.distance_km, minimum=0),
        "direction": str(item.direction),
        "relative_deg": _number(item.relative),
        "is_target": bool(item.is_target),
        "ete": str(item.ete_str or ""),
    }


def _map_point(point: TacticalMapPoint) -> dict[str, Any]:
    return {
        "id": str(point.id),
        "kind": str(point.kind),
        "x": _number(point.x, minimum=0, maximum=1),
        "y": _number(point.y, minimum=0, maximum=1),
        "label": str(point.label),
        "color": str(point.color),
        "icon": str(point.icon or "")[:64],
        "is_target": bool(point.is_target),
        "is_friendly": bool(point.is_friendly),
    }


def _filtered_map_points(
    points: tuple[TacticalMapPoint, ...], capabilities: DashboardCapabilities
) -> list[dict[str, Any]]:
    allowed: set[str] = set(HOSTILE_MAP_KINDS)
    if capabilities.navigation:
        allowed.update(("poi", "traceback"))
    if capabilities.navigation and ENABLE_ZONES:
        allowed.add("zone")
    if capabilities.navigation and ENABLE_AIRFIELDS:
        allowed.add("airfield")
    return [_map_point(point) for point in points if point.kind in allowed]


def _weapon_range(
    snapshot: UISnapshot, capabilities: DashboardCapabilities
) -> dict[str, Any] | None:
    if not capabilities.weapon or not snapshot.weapon_solution_valid:
        return None
    scale_x = _optional_number(snapshot.map_scale_x_m, minimum=1)
    scale_y = _optional_number(snapshot.map_scale_y_m, minimum=1)
    maximum = _optional_number(snapshot.weapon_max_range_m, minimum=0)
    minimum = _optional_number(snapshot.weapon_min_range_m, minimum=0)
    if scale_x is None or scale_y is None or maximum is None or maximum <= 0:
        return None
    bounded_minimum = min(maximum, minimum or 0.0)
    return {
        "min_radius_x": min(4.0, bounded_minimum / scale_x),
        "min_radius_y": min(4.0, bounded_minimum / scale_y),
        "max_radius_x": min(4.0, maximum / scale_x),
        "max_radius_y": min(4.0, maximum / scale_y),
        "quality": str(snapshot.weapon_quality or "none"),
    }


def _alerts(snapshot: UISnapshot, capabilities: DashboardCapabilities) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    if snapshot.api_down:
        alerts.append({"level": "danger", "code": "api_down", "text": "8111 数据连接中断"})
    elif snapshot.api_down_pending:
        alerts.append({"level": "warning", "code": "api_pending", "text": "8111 数据暂时不稳定"})
    if snapshot.gear_warning:
        alerts.append({"level": "danger", "code": "gear", "text": "起落架仍处于放下状态"})
    if snapshot.overspeed_level in {"warning", "critical"}:
        alerts.append(
            {
                "level": "danger" if snapshot.overspeed_level == "critical" else "warning",
                "code": "overspeed",
                "text": "已接近或超过当前机型速度限制",
            }
        )
    if capabilities.fuel and snapshot.return_status in {"warning", "danger"}:
        alerts.append(
            {
                "level": "danger" if snapshot.return_status == "danger" else "warning",
                "code": "return_fuel",
                "text": "返航燃油余量不足"
                if snapshot.return_status == "danger"
                else "返航燃油余量偏低",
            }
        )
    if capabilities.navigation and snapshot.zone_destroyed_alert:
        alerts.append(
            {
                "level": "info",
                "code": "zone_destroyed",
                "text": str(snapshot.destroyed_zone_text or "战区已摧毁"),
            }
        )
    return alerts


def build_dashboard_payload(published: PublishedDashboardSnapshot) -> dict[str, Any]:
    """Build the schema-backed response without raw 8111 payloads."""

    snap = published.snapshot
    capabilities = published.capabilities

    zones = (
        [
            _nav_item(zone, name=f"战区 #{index}", kind="zone")
            for index, zone in enumerate(snap.zones, start=1)
        ]
        if capabilities.navigation and ENABLE_ZONES
        else []
    )
    airfields: list[dict[str, Any]] = []
    if capabilities.navigation and ENABLE_AIRFIELDS:
        if snap.friendly_airfield is not None:
            airfields.append(
                _nav_item(snap.friendly_airfield, name="友方机场", kind="friendly_airfield")
            )
        airfields.extend(
            _nav_item(item, name=f"敌方机场 #{index}", kind="enemy_airfield")
            for index, item in enumerate(snap.enemy_airfields, start=1)
        )

    poi = (
        _nav_item(
            snap.interest_point,
            name=str(snap.interest_point.name or "兴趣点"),
            kind="poi",
        )
        if capabilities.navigation and snap.interest_point is not None
        else None
    )
    traceback = (
        _nav_item(snap.traceback_point, name="上次坠毁点", kind="traceback")
        if capabilities.navigation and snap.traceback_point is not None
        else None
    )
    target = next(
        (item for item in [*zones, *airfields, *([poi] if poi else [])] if item["is_target"]),
        None,
    )

    map_points = _filtered_map_points(snap.map_points, capabilities)
    map_player_x = _optional_number(snap.map_player_x, minimum=0, maximum=1)
    map_player_y = _optional_number(snap.map_player_y, minimum=0, maximum=1)
    map_player = (
        {
            "x": map_player_x,
            "y": map_player_y,
            "heading_deg": _number(snap.player_heading),
        }
        if map_player_x is not None and map_player_y is not None
        else None
    )

    weapon_enabled = capabilities.weapon
    return {
        "schema_version": SCHEMA_VERSION,
        "sequence": int(published.sequence),
        "generated_at": _number(published.generated_at, minimum=0),
        "capabilities": {
            "navigation": capabilities.navigation,
            "fuel": capabilities.fuel,
            "checklist": capabilities.checklist,
            "weapon": weapon_enabled,
        },
        "status": {
            "connected": not bool(snap.api_down),
            "api_down": bool(snap.api_down),
            "phase": snap.phase.name.lower(),
            "phase_label": _PHASE_LABELS.get(snap.phase, "未知状态"),
            "on_ground": bool(snap.on_ground),
        },
        "timer": {
            "remaining_sec": _optional_number(snap.remaining_sec, minimum=0),
            "progress": _number(snap.progress, minimum=0, maximum=1),
            "cycle": int(snap.cycle) if snap.cycle is not None and snap.cycle >= 1 else None,
            "life_index": (
                int(snap.life_index)
                if snap.life_index is not None and snap.life_index >= 1
                else None
            ),
            "sortie_id": max(0, int(snap.sortie_id)),
            "cycle_minutes": max(1, min(180, int(snap.timer_cycle_minutes))),
        },
        "flight": {
            "aircraft": str(snap.aircraft_type_name or ""),
            "heading_deg": _number(snap.player_heading),
            "altitude_m": _number(snap.altitude_m),
            "ground_speed_kmh": _number(snap.ground_speed_kmh, minimum=0),
            "ias_kmh": _number(snap.overspeed_current_ias_kmh, minimum=0),
            "mach": _optional_number(snap.overspeed_current_mach, minimum=0),
            "attitude": {
                "pitch_deg": _number(snap.attitude_pitch_deg),
                "roll_deg": _number(snap.attitude_roll_deg),
                "reliable": bool(snap.attitude_reliable),
            },
            "gear": {
                "percent": _number(snap.gear_pct, minimum=0, maximum=100),
                "moving": bool(snap.gear_moving),
                "retracting": bool(snap.gear_retracting),
                "warning": bool(snap.gear_warning),
            },
            "overspeed": {
                "level": str(snap.overspeed_level),
                "ratio": _number(snap.overspeed_ratio, minimum=0),
                "limit_kmh": _number(snap.overspeed_limit_kmh, minimum=0),
                "limit_mach": _number(snap.overspeed_limit_mach, minimum=0),
                "matched": bool(snap.overspeed_match),
            },
        },
        "fuel": {
            "current_kg": _number(snap.fuel_kg, minimum=0) if capabilities.fuel else 0.0,
            "percent": (
                _number(snap.fuel_percent, minimum=0, maximum=100) if capabilities.fuel else 0.0
            ),
            "rate_kg_min": (
                _number(snap.fuel_rate_kg_min, minimum=0) if capabilities.fuel else 0.0
            ),
            "rate_stable": bool(snap.fuel_rate_stable) if capabilities.fuel else False,
            "remaining_min": (
                _optional_number(snap.fuel_remaining_time_min, minimum=0)
                if capabilities.fuel
                else None
            ),
            "return_needed_kg": (
                _number(snap.return_fuel_needed_kg, minimum=0) if capabilities.fuel else 0.0
            ),
            "return_status": str(snap.return_status) if capabilities.fuel else "unavailable",
            "home_distance_km": (
                _number(snap.friendly_distance_km, minimum=0) if capabilities.fuel else 0.0
            ),
        },
        "navigation": {
            "deviation_deg": _number(snap.deviation_angle),
            "deviating": bool(snap.is_deviating),
            "target": target,
            "zones": zones,
            "airfields": airfields,
            "poi": poi,
            "traceback": traceback,
        },
        "weapon": {
            "id": str(snap.weapon_id or "") if weapon_enabled else "",
            "name": str(snap.weapon_display_name or "") if weapon_enabled else "",
            "role": str(snap.weapon_role or "") if weapon_enabled else "",
            "model": str(snap.weapon_model or "") if weapon_enabled else "",
            "quality": str(snap.weapon_quality or "") if weapon_enabled else "none",
            "valid": bool(snap.weapon_solution_valid) if weapon_enabled else False,
            "status": str(snap.weapon_status or "") if weapon_enabled else "unavailable",
            "reason": str(snap.weapon_reason or "") if weapon_enabled else "build_disabled",
            "target_kind": str(snap.weapon_target_kind or "") if weapon_enabled else "",
            "target_name": str(snap.weapon_target_name or "") if weapon_enabled else "",
            "target_distance_km": (
                _number(snap.weapon_target_distance_m, minimum=0) / 1000 if weapon_enabled else 0.0
            ),
            "min_range_km": (
                _number(snap.weapon_min_range_m, minimum=0) / 1000 if weapon_enabled else 0.0
            ),
            "max_range_km": (
                _number(snap.weapon_max_range_m, minimum=0) / 1000 if weapon_enabled else 0.0
            ),
            "head_range_km": (
                _number(snap.weapon_head_range_m, minimum=0) / 1000 if weapon_enabled else 0.0
            ),
            "rear_range_km": (
                _number(snap.weapon_rear_range_m, minimum=0) / 1000 if weapon_enabled else 0.0
            ),
            "time_to_target_s": (
                _number(snap.weapon_time_to_target_s, minimum=0) if weapon_enabled else 0.0
            ),
            "time_to_window_s": (
                _number(snap.weapon_time_to_window_s, minimum=0) if weapon_enabled else 0.0
            ),
        },
        "bombing": {
            "enabled": weapon_enabled,
            "valid": bool(snap.bombing_valid) if weapon_enabled else False,
            "bomb_name": str(snap.bomb_name or "") if weapon_enabled else "",
            "model_id": (str(snap.bomb_trajectory_model_id or "") if weapon_enabled else ""),
            "model_category": (
                str(snap.bomb_trajectory_model_category or "") if weapon_enabled else ""
            ),
            "model_quality": (
                str(snap.bomb_trajectory_model_quality or "") if weapon_enabled else ""
            ),
            "target_altitude_m": (_number(snap.target_altitude_m) if weapon_enabled else 0.0),
            "target_altitude_source": (
                str(snap.target_altitude_source or "") if weapon_enabled else ""
            ),
            "atmosphere_model_id": (str(snap.atmosphere_model_id or "") if weapon_enabled else ""),
            "atmosphere_altitude_datum_m": (
                _number(snap.atmosphere_altitude_datum_m) if weapon_enabled else 0.0
            ),
            "altitude_datum_source": (
                str(snap.altitude_datum_source or "") if weapon_enabled else ""
            ),
            "air_density_sea_level_kg_m3": (
                _number(snap.air_density_sea_level, minimum=0) if weapon_enabled else 0.0
            ),
            "air_density_source": (str(snap.air_density_source or "") if weapon_enabled else ""),
            "state_age_ms": (
                _number(snap.bombing_state_age_s, minimum=0) * 1000 if weapon_enabled else 0.0
            ),
            "map_age_ms": (
                _number(snap.bombing_map_age_s, minimum=0) * 1000 if weapon_enabled else 0.0
            ),
            "endpoint_skew_ms": (
                _number(snap.bombing_endpoint_skew_s, minimum=0) * 1000 if weapon_enabled else 0.0
            ),
            "altitude_projection_m": (
                _number(snap.bombing_altitude_projection_m) if weapon_enabled else 0.0
            ),
            "tas_projection_ms": (
                _number(snap.bombing_tas_projection_ms) if weapon_enabled else 0.0
            ),
            "vertical_acceleration_ms2": (
                _number(snap.bombing_vertical_acceleration_ms2) if weapon_enabled else 0.0
            ),
            "release_state_source": (
                str(snap.bombing_release_state_source or "") if weapon_enabled else ""
            ),
            "maneuver_score": (
                _number(snap.bombing_maneuver_score, minimum=0) if weapon_enabled else 0.0
            ),
            "precision_gate_available": (
                bool(snap.bombing_precision_gate_available) if weapon_enabled else False
            ),
            "target_kind": str(snap.bombing_target_kind or "") if weapon_enabled else "",
            "target_name": str(snap.bombing_target_name or "") if weapon_enabled else "",
            "target_mode": str(snap.bombing_target_mode or "zone") if weapon_enabled else "",
            "release_status": str(snap.release_status or "") if weapon_enabled else "unavailable",
            "release_distance_km": (
                _number(snap.release_distance_m, minimum=0) / 1000 if weapon_enabled else 0.0
            ),
            "time_to_release_s": (
                _number(snap.time_to_release, minimum=0) if weapon_enabled else 0.0
            ),
            "flight_time_s": (_number(snap.bomb_flight_time, minimum=0) if weapon_enabled else 0.0),
            "unavailable_reason": (
                str(snap.bombing_unavailable_reason or "") if weapon_enabled else "build_disabled"
            ),
        },
        "checklist": {"items": list(published.checklist_items) if capabilities.checklist else []},
        "alerts": _alerts(snap, capabilities),
        "map": {
            "available": bool(
                published.map_image_available or map_player is not None or map_points
            ),
            "player": map_player,
            "points": map_points,
            "image": {
                "available": bool(published.map_image_available),
                "revision": max(0, int(published.map_image_revision)),
                "url": "/api/v1/map-image",
            },
            "weapon_range": _weapon_range(snap, capabilities),
        },
    }
