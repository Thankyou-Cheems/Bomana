"""Navigation math helpers extracted from GameLogic."""

import math

from bomana.config import ZoneConfig
from bomana.core.state import MapInfo
from bomana.utils.math_utils import (
    calculate_bearing,
    calculate_distance,
    normalize_angle,
)

_SEQUENCE_NUMERIC_PARSE_ERRORS = (TypeError, ValueError, IndexError)


def angle_delta_deg(current: float, previous: float) -> float:
    """Return absolute angle delta mapped through [-180, 180]."""
    return abs(normalize_angle(float(current) - float(previous)))


def map_axis_scale_m(map_info: MapInfo | None) -> tuple[float, float] | None:
    """Extract X/Y meter scales from map_info normalized coordinates."""
    if map_info is None or not getattr(map_info, "valid", False):
        return None
    try:
        min_x, min_y = map_info.map_min
        max_x, max_y = map_info.map_max
        scale_x = abs(float(max_x) - float(min_x))
        scale_y = abs(float(max_y) - float(min_y))
        if scale_x <= 1e-6 or scale_y <= 1e-6:
            return None
        return scale_x, scale_y
    except _SEQUENCE_NUMERIC_PARSE_ERRORS:
        return None


def distance_norm_from_delta(
    dx: float,
    dy: float,
    map_axis_scale_m_value: tuple[float, float] | None,
) -> float:
    """Calculate legacy-compatible distance: actual km / DISTANCE_SCALE."""
    dx = float(dx)
    dy = float(dy)
    if map_axis_scale_m_value is not None:
        moved_m = math.hypot(dx * map_axis_scale_m_value[0], dy * map_axis_scale_m_value[1])
        moved_km = moved_m / 1000.0
        return moved_km / ZoneConfig.DISTANCE_SCALE
    return math.hypot(dx, dy)


def bearing_distance_norm(
    px: float,
    py: float,
    tx: float,
    ty: float,
    map_axis_scale_m_value: tuple[float, float] | None,
) -> tuple[float, float]:
    """Calculate target bearing and legacy-compatible distance."""
    dx = float(tx) - float(px)
    dy = float(ty) - float(py)
    if map_axis_scale_m_value is not None:
        dx_m = dx * map_axis_scale_m_value[0]
        dy_m = dy * map_axis_scale_m_value[1]
        bearing = (math.degrees(math.atan2(dx_m, -dy_m)) + 360.0) % 360.0
        distance_norm = distance_norm_from_delta(dx, dy, map_axis_scale_m_value)
        return bearing, distance_norm

    bearing = calculate_bearing(px, py, tx, ty)
    distance_norm = calculate_distance(px, py, tx, ty)
    return bearing, distance_norm
