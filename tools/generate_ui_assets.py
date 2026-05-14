#!/usr/bin/env python3
"""Generate bundled UI font subsets and PNG icon assets."""

from __future__ import annotations

import re
import tempfile
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSET_ROOT = ROOT / "bomana" / "assets"
FONT_DIR = ASSET_ROOT / "fonts"
ICON_DIR = ASSET_ROOT / "icons"

FONT_SOURCE_URL = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/main/"
    "Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf"
)
FONT_LICENSE_URL = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/LICENSE"
FONT_FAMILY = "Bomana UI Sans"
FONT_COPYRIGHT = "Derived from Noto Sans SC, Copyright 2014-2021 Adobe and Google."

SCAN_EXTENSIONS = {".py", ".pyw", ".md", ".json", ".toml"}
EXTRA_GLYPHS = (
    "".join(chr(i) for i in range(0x20, 0x7F))
    + "，。！？；：（）【】《》、·"
    + "│─━…℃°±←→↑↓↻"
    + "✓✕✖★⚠➤○●⊚⌂"
)


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Bomana-asset-generator"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def collect_project_text() -> str:
    chars: set[str] = set(EXTRA_GLYPHS)
    ignored_parts = {".git", ".venv", "__pycache__", "build", "dist"}
    for path in ROOT.rglob("*"):
        if path.is_dir() or path.suffix.lower() not in SCAN_EXTENSIONS:
            continue
        if any(part in ignored_parts for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for char in text:
            codepoint = ord(char)
            if 0x20 <= codepoint <= 0x7E or codepoint >= 0xA0:
                chars.add(char)
    return "".join(sorted(chars))


def set_name_record(font: TTFont, name_id: int, value: str) -> None:
    name_table = font["name"]
    for record in name_table.names:
        if record.nameID == name_id:
            record.string = value.encode(record.getEncoding(), errors="replace")


def rename_font(font: TTFont, *, subfamily: str) -> None:
    full_name = f"{FONT_FAMILY} {subfamily}"
    ps_name = re.sub(r"[^A-Za-z0-9-]", "", full_name.replace(" ", "-"))
    set_name_record(font, 1, FONT_FAMILY)
    set_name_record(font, 2, subfamily)
    set_name_record(font, 3, f"{ps_name};Bomana")
    set_name_record(font, 4, full_name)
    set_name_record(font, 5, "Version 1.000; subset for Bomana")
    set_name_record(font, 6, ps_name)
    set_name_record(font, 13, "Licensed under the SIL Open Font License, Version 1.1.")
    set_name_record(font, 14, "https://openfontlicense.org")
    set_name_record(font, 16, FONT_FAMILY)
    set_name_record(font, 17, subfamily)
    set_name_record(font, 18, full_name)
    set_name_record(font, 0, FONT_COPYRIGHT)


def build_font_subset(source_font: Path, text: str, *, weight: int, subfamily: str) -> None:
    font = TTFont(source_font)
    font = instancer.instantiateVariableFont(font, {"wght": weight}, inplace=True)

    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.name_languages = ["*"]
    options.recalc_bounds = True
    options.recalc_timestamp = False

    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    rename_font(font, subfamily=subfamily)

    out_path = FONT_DIR / f"BomanaUiSans-{subfamily}.ttf"
    font.save(out_path)


def draw_icon(kind: str, size: int) -> Image.Image:
    scale = size / 64.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def xy(values: tuple[float, ...]) -> tuple[int, ...]:
        return tuple(round(v * scale) for v in values)

    if kind == "target":
        draw.polygon([xy((18, 12))[0:2], xy((52, 32))[0:2], xy((18, 52))[0:2]], fill="#ffd166")
        draw.line(xy((18, 12, 18, 52)), fill="#2b1d00", width=max(1, int(4 * scale)))
    elif kind == "zone":
        draw.ellipse(xy((14, 14, 50, 50)), outline="#d7dde8", width=max(2, int(5 * scale)))
        draw.ellipse(xy((27, 27, 37, 37)), fill="#d7dde8")
    elif kind == "airfield_friendly":
        draw.ellipse(
            xy((9, 9, 55, 55)), fill="#39d98a", outline="#0b3d28", width=max(2, int(4 * scale))
        )
        draw.polygon(
            [xy((32, 13))[0:2], xy((43, 43))[0:2], xy((32, 37))[0:2], xy((21, 43))[0:2]],
            fill="#f5fff9",
        )
    elif kind == "airfield_enemy":
        draw.ellipse(
            xy((9, 9, 55, 55)), fill="#ff5c5c", outline="#4a1111", width=max(2, int(4 * scale))
        )
        draw.line(xy((22, 22, 42, 42)), fill="#fff2f2", width=max(2, int(6 * scale)))
        draw.line(xy((42, 22, 22, 42)), fill="#fff2f2", width=max(2, int(6 * scale)))
    elif kind == "warning":
        draw.polygon(
            [xy((32, 7))[0:2], xy((58, 54))[0:2], xy((6, 54))[0:2]],
            fill="#ffb84d",
            outline="#4a2a00",
        )
        draw.rectangle(xy((29, 23, 35, 40)), fill="#2b1d00")
        draw.ellipse(xy((28, 44, 36, 52)), fill="#2b1d00")
    elif kind == "ok":
        draw.ellipse(
            xy((7, 7, 57, 57)), fill="#39d98a", outline="#0b3d28", width=max(2, int(4 * scale))
        )
        draw.line(xy((18, 33, 28, 43, 47, 21)), fill="#f5fff9", width=max(2, int(7 * scale)))
    elif kind == "danger":
        draw.ellipse(
            xy((7, 7, 57, 57)), fill="#ff5c5c", outline="#4a1111", width=max(2, int(4 * scale))
        )
        draw.rectangle(xy((29, 17, 35, 39)), fill="#fff2f2")
        draw.ellipse(xy((28, 44, 36, 52)), fill="#fff2f2")
    elif kind == "explosion":
        draw.polygon(
            [
                xy((32, 3))[0:2],
                xy((39, 22))[0:2],
                xy((58, 15))[0:2],
                xy((47, 32))[0:2],
                xy((61, 45))[0:2],
                xy((40, 43))[0:2],
                xy((32, 61))[0:2],
                xy((24, 43))[0:2],
                xy((3, 45))[0:2],
                xy((17, 32))[0:2],
                xy((6, 15))[0:2],
                xy((25, 22))[0:2],
            ],
            fill="#ff5c5c",
            outline="#4a1111",
        )
        draw.ellipse(xy((21, 21, 43, 43)), fill="#ffd166")
    elif kind == "bomb":
        draw.ellipse(
            xy((17, 22, 48, 53)), fill="#3d4655", outline="#111820", width=max(2, int(4 * scale))
        )
        draw.rectangle(xy((36, 13, 45, 25)), fill="#3d4655")
        draw.polygon([xy((40, 9))[0:2], xy((57, 8))[0:2], xy((47, 22))[0:2]], fill="#ffb84d")
    elif kind == "aircraft":
        draw.polygon(
            [xy((32, 5))[0:2], xy((45, 57))[0:2], xy((32, 48))[0:2], xy((19, 57))[0:2]],
            fill="#66d9ff",
        )
        draw.polygon(
            [xy((12, 32))[0:2], xy((52, 32))[0:2], xy((42, 42))[0:2], xy((22, 42))[0:2]],
            fill="#c9f3ff",
        )
    elif kind == "climb":
        draw.line(xy((12, 46, 49, 14)), fill="#66d9ff", width=max(2, int(7 * scale)))
        draw.polygon([xy((49, 14))[0:2], xy((49, 34))[0:2], xy((32, 14))[0:2]], fill="#66d9ff")
    elif kind == "aim":
        draw.ellipse(xy((10, 10, 54, 54)), outline="#ff6b6b", width=max(2, int(4 * scale)))
        draw.line(xy((32, 7, 32, 21)), fill="#ff6b6b", width=max(1, int(3 * scale)))
        draw.line(xy((32, 43, 32, 57)), fill="#ff6b6b", width=max(1, int(3 * scale)))
        draw.line(xy((7, 32, 21, 32)), fill="#ff6b6b", width=max(1, int(3 * scale)))
        draw.line(xy((43, 32, 57, 32)), fill="#ff6b6b", width=max(1, int(3 * scale)))
    elif kind == "clock":
        draw.ellipse(xy((9, 9, 55, 55)), outline="#d7dde8", width=max(2, int(5 * scale)))
        draw.line(xy((32, 32, 32, 17)), fill="#d7dde8", width=max(2, int(4 * scale)))
        draw.line(xy((32, 32, 45, 38)), fill="#d7dde8", width=max(2, int(4 * scale)))
    elif kind == "fuel":
        draw.rounded_rectangle(
            xy((18, 11, 43, 56)),
            radius=int(6 * scale),
            fill="#66d9ff",
            outline="#153344",
            width=max(2, int(4 * scale)),
        )
        draw.rectangle(xy((23, 17, 38, 27)), fill="#0b1f2a")
        draw.line(xy((43, 24, 53, 31, 53, 48)), fill="#66d9ff", width=max(2, int(5 * scale)))
    elif kind == "speed":
        draw.arc(
            xy((10, 14, 54, 58)), start=200, end=340, fill="#ffd166", width=max(2, int(5 * scale))
        )
        draw.line(xy((32, 42, 48, 27)), fill="#ff5c5c", width=max(2, int(5 * scale)))
        draw.ellipse(xy((27, 37, 37, 47)), fill="#d7dde8")
    elif kind == "checklist":
        draw.rounded_rectangle(
            xy((13, 8, 51, 56)),
            radius=int(5 * scale),
            fill="#d7dde8",
            outline="#293241",
            width=max(2, int(4 * scale)),
        )
        draw.line(xy((22, 25, 29, 32, 42, 18)), fill="#39d98a", width=max(2, int(5 * scale)))
        draw.line(xy((22, 43, 42, 43)), fill="#293241", width=max(1, int(4 * scale)))
    else:
        draw.rectangle(xy((12, 12, 52, 52)), fill="#d7dde8")

    return img


def build_icons() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for kind in (
        "target",
        "zone",
        "airfield_friendly",
        "airfield_enemy",
        "warning",
        "ok",
        "danger",
        "explosion",
        "bomb",
        "aircraft",
        "climb",
        "aim",
        "clock",
        "fuel",
        "speed",
        "checklist",
    ):
        for size in (12, 14, 16, 18, 20):
            draw_icon(kind, size).save(ICON_DIR / f"{kind}_{size}.png")


def main() -> int:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    ICON_DIR.mkdir(parents=True, exist_ok=True)

    text = collect_project_text()
    with tempfile.TemporaryDirectory() as tmp_dir:
        source_font = Path(tmp_dir) / "NotoSansSC-VF.ttf"
        source_font.write_bytes(download_bytes(FONT_SOURCE_URL))
        (FONT_DIR / "LICENSE-NotoSansSC-OFL.txt").write_bytes(download_bytes(FONT_LICENSE_URL))
        build_font_subset(source_font, text, weight=400, subfamily="Regular")
        build_font_subset(source_font, text, weight=700, subfamily="Bold")

    build_icons()
    print(f"Generated fonts in {FONT_DIR}")
    print(f"Generated icons in {ICON_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
