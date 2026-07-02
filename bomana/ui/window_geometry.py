"""Headless window geometry helpers shared by Tk coordinators."""

from __future__ import annotations

from typing import Any


def capture_snap_anchor(
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    snap_enabled: bool,
    snap_distance: int,
    monitor: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not snap_enabled or not monitor:
        return None

    mon_x = int(monitor.get("x", 0))
    mon_y = int(monitor.get("y", 0))
    mon_w = int(monitor.get("width", 0))
    mon_h = int(monitor.get("height", 0))
    threshold = max(1, int(snap_distance))

    left_gap = x - mon_x
    right_gap = (mon_x + mon_w) - (x + w)
    top_gap = y - mon_y
    bottom_gap = (mon_y + mon_h) - (y + h)

    horizontal = None
    vertical = None

    if abs(left_gap) <= threshold:
        horizontal = ("left", left_gap)
    elif abs(right_gap) <= threshold:
        horizontal = ("right", right_gap)

    if abs(top_gap) <= threshold:
        vertical = ("top", top_gap)
    elif abs(bottom_gap) <= threshold:
        vertical = ("bottom", bottom_gap)

    if not horizontal and not vertical:
        return None
    return {"monitor": monitor, "horizontal": horizontal, "vertical": vertical}


def apply_snap_anchor(
    x: int,
    y: int,
    w: int,
    h: int,
    anchor: dict[str, Any],
) -> tuple[int, int]:
    monitor = anchor.get("monitor") or {}
    mon_x = int(monitor.get("x", 0))
    mon_y = int(monitor.get("y", 0))
    mon_w = int(monitor.get("width", 0))
    mon_h = int(monitor.get("height", 0))

    horizontal = anchor.get("horizontal")
    vertical = anchor.get("vertical")

    if horizontal and mon_w > 0:
        edge, gap = horizontal
        gap = int(gap)
        if edge == "left":
            x = mon_x + gap
        elif edge == "right":
            x = mon_x + mon_w - w - gap

    if vertical and mon_h > 0:
        edge, gap = vertical
        gap = int(gap)
        if edge == "top":
            y = mon_y + gap
        elif edge == "bottom":
            y = mon_y + mon_h - h - gap

    return x, y
