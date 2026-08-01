"""Coordinate conversion shared by public navigation modules."""

from __future__ import annotations

import math


def normalized_map_to_world(
    x: float,
    y: float,
    map_min: list[float] | tuple[float, float],
    map_max: list[float] | tuple[float, float],
) -> tuple[float, float] | None:
    """Convert 8111 normalized map X/Y to Dagor world X/Z."""

    try:
        normalized_x = float(x)
        normalized_y = float(y)
        min_x = float(map_min[0])
        min_z = float(map_min[1])
        max_x = float(map_max[0])
        max_z = float(map_max[1])
    except IndexError, TypeError, ValueError:
        return None
    values = (normalized_x, normalized_y, min_x, min_z, max_x, max_z)
    if not all(math.isfinite(value) for value in values):
        return None
    if max_x <= min_x or max_z <= min_z:
        return None
    return (
        min_x + normalized_x * (max_x - min_x),
        max_z - normalized_y * (max_z - min_z),
    )


__all__ = ["normalized_map_to_world"]
