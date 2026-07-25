#!/usr/bin/env python3
# ruff: noqa: E402
"""Capture current Tk navigation and CCRP widgets for the public site."""

from __future__ import annotations

import argparse
import ctypes
import sys
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bomana.ui.nav_window as nav_window_module
from bomana.config.settings import PanelConfig
from bomana.ui.bombing_bar import BombingBar, CCRPCueProjection
from bomana.ui.nav_window import NavigationWindow
from bomana.ui.theme import Theme
from bomana.ui.widgets import HeadingTape

DEFAULT_OUTPUT_DIR = ROOT / "docs" / "assets" / "shots"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for nav-hud.png, nav-precision.png, and ccrp-compact.png.",
    )
    return parser.parse_args()


def scaled_font(font, *, size_mult: float = 1.0, min_size: int = 1):
    return font[0], max(min_size, round(font[1] * size_mult))


def capture_widget(widget: tk.Misc, path: Path) -> tuple[int, int]:
    widget.update_idletasks()
    x = widget.winfo_rootx()
    y = widget.winfo_rooty()
    width = widget.winfo_width()
    height = widget.winfo_height()
    if width <= 1 or height <= 1:
        raise RuntimeError(f"widget has invalid capture geometry: {width}x{height}")
    image = ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)
    image.save(path, "PNG", optimize=True)
    return width, height


def capture_navigation(root: tk.Tk, output_dir: Path) -> list[tuple[Path, tuple[int, int]]]:
    old_enable_ccrp = nav_window_module.ENABLE_CCRP
    old_scale = PanelConfig.navigation_bar_scale
    old_width = PanelConfig.navigation_bar_width
    old_position = PanelConfig.navigation_window_pos
    nav_window_module.ENABLE_CCRP = False
    PanelConfig.navigation_bar_scale = 1.0
    PanelConfig.navigation_bar_width = 3.5
    PanelConfig.navigation_window_pos = (80, 80)

    app = SimpleNamespace(
        root=root,
        scale=1.0,
        _locked=False,
        _scaled_font=scaled_font,
        navigation_services=SimpleNamespace(switch_to_integrated=lambda: None),
    )
    nav = None
    try:
        targets = [
            {
                "type": "zone",
                "relative": 0.24,
                "distance_km": 7.0,
                "is_primary": True,
                "is_target": True,
            },
            {
                "type": "friendly",
                "relative": -18.0,
                "distance_km": 12.0,
                "is_primary": False,
            },
            {
                "type": "enemy",
                "relative": 25.0,
                "distance_km": 33.0,
                "is_primary": False,
            },
            {
                "type": "poi",
                "relative": -4.0,
                "distance_km": 3.8,
                "is_primary": False,
            },
        ]
        nav = NavigationWindow(app)
        nav.show()
        nav.apply_window_styles(click_through=False, alpha=255)
        nav.heading_lbl.configure(text="航向 090°")
        nav.tolerance_lbl.configure(text="精细航线 ±1.0°")
        nav.heading_tape.update_tape_multi(90.0, targets, 7.0)
        nav.window.update()

        nav_path = output_dir / "nav-hud.png"
        precision_path = output_dir / "nav-precision.png"
        captures = [(nav_path, capture_widget(nav.main_frame, nav_path))]

        precision_host = tk.Toplevel(root)
        precision_host.overrideredirect(True)
        precision_host.attributes("-topmost", True)
        precision_host.configure(bg=Theme.BG)
        precision_host.geometry("+80+320")
        precision_tape = HeadingTape(
            precision_host,
            width=338,
            height=36,
            text_scale=1.0,
        )
        precision_tape.pack()
        precision_tape.update_tape_multi(90.0, targets, 7.0)
        precision_host.update()
        try:
            captures.append(
                (precision_path, capture_widget(precision_tape, precision_path))
            )
        finally:
            precision_host.destroy()
        return captures
    finally:
        if nav is not None:
            nav.destroy()
        nav_window_module.ENABLE_CCRP = old_enable_ccrp
        PanelConfig.navigation_bar_scale = old_scale
        PanelConfig.navigation_bar_width = old_width
        PanelConfig.navigation_window_pos = old_position


def capture_ccrp(root: tk.Tk, output_dir: Path) -> tuple[Path, tuple[int, int]]:
    host = tk.Toplevel(root)
    host.overrideredirect(True)
    host.attributes("-topmost", True)
    host.configure(bg=Theme.GRAYPILL)
    host.geometry("720x180+80+360")
    app = SimpleNamespace(
        root=root,
        scale=1.0,
        _scaled_font=scaled_font,
        _toggle_bombing_mode=lambda: None,
        _toggle_panel=lambda _panel: None,
        _show_bomb_selector=lambda: None,
        _toggle_bomb_target_mode=lambda: None,
    )
    bar = BombingBar(host, app, scale=1.0, standalone=False)
    bar.frame.pack(fill="x")
    bar._target_summary_full_text = "高186m·战区#2 3.12km"
    bar.release_lbl.configure(text="接近", fg=Theme.YELLOW)
    bar.weapon_btn.configure(text="MK82 500磅")
    bar.target_mode_btn.configure(text="目标：战区 [F6]")
    bar.cue.set_projection(CCRPCueProjection(0.18, Theme.YELLOW, "T−2.4s"))
    host.update()
    bar._refresh_target_summary()
    bar.cue._draw()
    host.update()

    path = output_dir / "ccrp-compact.png"
    try:
        return path, capture_widget(bar.frame, path)
    finally:
        bar.destroy()
        host.destroy()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()

    root = tk.Tk()
    root.withdraw()
    try:
        captures = capture_navigation(root, output_dir)
        captures.append(capture_ccrp(root, output_dir))
    finally:
        root.destroy()

    for path, (width, height) in captures:
        print(f"captured={path} size={width}x{height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
