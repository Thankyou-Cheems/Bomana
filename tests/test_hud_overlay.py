from unittest import mock

import pytest

from bomana.config import HUDConfig
from bomana.ui.hud_overlay import (
    HUDOverlay,
    HUDOverlayUnavailable,
    HUDPhysicalRect,
    HUDTransparencySupport,
)


def test_hud_physical_rect_clamps_monitor_values() -> None:
    rect = HUDPhysicalRect.from_monitor({"x": "10", "y": "-20", "width": 0, "height": None})

    assert rect.x == 10
    assert rect.y == -20
    assert rect.width == 1
    assert rect.height == 1
    assert rect.tk_geometry() == "1x1+10-20"

    left_monitor = HUDPhysicalRect.from_monitor({"x": -1920, "y": 0, "width": 1280, "height": 720})
    assert left_monitor.tk_geometry() == "1280x720-1920+0"


def test_hud_transparency_support_requires_color_key_or_win32_layer() -> None:
    assert HUDTransparencySupport(tk_color_key=False, win32_layered=False).usable is False
    assert HUDTransparencySupport(tk_color_key=True, win32_layered=False).usable is True
    assert HUDTransparencySupport(tk_color_key=False, win32_layered=True).usable is True


def test_hud_logical_px_uses_hud_scale_without_affecting_monitor_geometry() -> None:
    original_scale = HUDConfig.scale
    HUDConfig.scale = 1.75
    try:
        assert HUDOverlay._logical_px(16) == 28
        assert HUDOverlay._logical_px(0.2, min_value=1) == 1
    finally:
        HUDConfig.scale = original_scale


def test_hud_resolve_top_level_hwnd_degrades_without_win32(monkeypatch) -> None:
    monkeypatch.setattr("bomana.ui.hud_overlay.os.name", "posix")

    assert HUDOverlay._resolve_top_level_hwnd(12345) == 12345


def test_hud_window_styles_disable_when_win32_colorkey_fails() -> None:
    overlay = HUDOverlay.__new__(HUDOverlay)
    overlay.hwnd = 12345
    overlay._transparent_color_ref = 0x00010101
    overlay._transparency_support = HUDTransparencySupport(
        tk_color_key=False,
        win32_layered=True,
    )

    with (
        mock.patch("bomana.ui.hud_overlay.Win32.setup_window", return_value=False),
        pytest.raises(HUDOverlayUnavailable),
    ):
        overlay.apply_window_styles(click_through=True, alpha=180)
