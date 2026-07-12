#!/usr/bin/env python3
"""Crop/adapt real UI screenshots for the GitHub Pages gallery."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "assets" / "shots"


def fit_long_edge(im: Image.Image, long_edge: int = 2000) -> Image.Image:
    width, height = im.size
    scale = long_edge / max(width, height)
    if scale >= 1:
        return im
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return im.resize(new_size, Image.Resampling.LANCZOS)


def row_mean_luma(im: Image.Image, y: int) -> float:
    pixels = im.load()
    width, _height = im.size
    step = max(1, width // 80)
    total = 0.0
    count = 0
    for x in range(0, width, step):
        red, green, blue = pixels[x, y][:3]
        total += 0.299 * red + 0.587 * green + 0.114 * blue
        count += 1
    return total / max(1, count)


def crop_mobile_browser_chrome(im: Image.Image) -> Image.Image:
    """Remove status bar, address bar, and bottom browser chrome when present."""
    width, height = im.size
    top = 0
    state = "start"
    maybe_app: list[int] = []
    for y in range(0, min(height // 3, 450)):
        luma = row_mean_luma(im, y)
        if state == "start" and luma > 180:
            state = "status"
        elif state == "status" and luma < 50:
            state = "maybe_app"
            maybe_app.append(y)
        elif state == "maybe_app" and luma > 100:
            state = "chrome"
        elif state == "chrome" and luma < 45:
            top = y
            break
    if top == 0 and maybe_app:
        top = maybe_app[0]
    if top < 20 or top > height * 0.28:
        top = int(height * 0.115)

    bottom = height
    # Walk upward through bright browser chrome, stop at dark app body.
    y = height - 1
    while y > int(height * 0.65) and row_mean_luma(im, y) > 170:
        y -= 1
    # Include trailing dark UI (bottom action bar is dark)
    while y > int(height * 0.65) and row_mean_luma(im, y) < 90:
        y -= 1
    # We overshot into the dark bar from below chrome: go back down into dark UI
    while y < height - 1 and row_mean_luma(im, y) > 90:
        y += 1
    # Find the last dark row before white chrome
    last_dark = y
    for scan in range(y, height):
        if row_mean_luma(im, scan) < 90:
            last_dark = scan
        elif row_mean_luma(im, scan) > 180 and scan > int(height * 0.75):
            bottom = last_dark + 1
            break
    else:
        bottom = last_dark + 1

    if bottom <= top + 200:
        top = int(height * 0.115)
        bottom = int(height * 0.88)

    print(f"mobile crop y={top}:{bottom} of {height} -> {bottom - top}px")
    return im.crop((0, top, width, bottom))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: prepare_pages_shots.py <desktop-web.png> <mobile-web.png>",
            file=sys.stderr,
        )
        return 2

    desktop_src = Path(argv[1])
    mobile_src = Path(argv[2])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    desktop = Image.open(desktop_src).convert("RGB")
    mobile = Image.open(mobile_src).convert("RGB")
    print("desktop", desktop.size)
    print("mobile", mobile.size)

    desktop_out = fit_long_edge(desktop, 2200)
    desktop_path = OUT_DIR / "web-cockpit-desktop.png"
    desktop_out.save(desktop_path, "PNG", optimize=True)
    print("wrote", desktop_path, desktop_out.size)

    mobile_crop = crop_mobile_browser_chrome(mobile)
    mobile_out = fit_long_edge(mobile_crop, 1600)
    mobile_path = OUT_DIR / "web-cockpit.png"
    mobile_out.save(mobile_path, "PNG", optimize=True)
    print("wrote", mobile_path, mobile_out.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
