from __future__ import annotations

from bomana.ui.window_geometry import apply_snap_anchor, capture_snap_anchor


def test_capture_snap_anchor_records_screen_edges() -> None:
    monitor = {"x": 100, "y": 50, "width": 800, "height": 600}

    anchor = capture_snap_anchor(
        102,
        60,
        300,
        200,
        snap_enabled=True,
        snap_distance=12,
        monitor=monitor,
    )

    assert anchor == {
        "monitor": monitor,
        "horizontal": ("left", 2),
        "vertical": ("top", 10),
    }


def test_apply_snap_anchor_preserves_right_bottom_gap_after_resize() -> None:
    monitor = {"x": 0, "y": 0, "width": 1000, "height": 800}
    anchor = {
        "monitor": monitor,
        "horizontal": ("right", 12),
        "vertical": ("bottom", 20),
    }

    assert apply_snap_anchor(0, 0, 400, 300, anchor) == (588, 480)


def test_capture_snap_anchor_returns_none_when_not_near_edge() -> None:
    assert (
        capture_snap_anchor(
            200,
            200,
            300,
            200,
            snap_enabled=True,
            snap_distance=12,
            monitor={"x": 0, "y": 0, "width": 1000, "height": 800},
        )
        is None
    )
