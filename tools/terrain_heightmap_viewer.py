#!/usr/bin/env python3
"""View Bomana BTH1/BTH2 terrain grids as pseudocolor PNG images."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from PIL import Image, ImageDraw, ImageFont, ImageTk, PngImagePlugin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bomana.core.terrain_elevation import (  # noqa: E402
    TerrainDataError,
    TerrainHeightMap,
    TerrainMapDescriptor,
    default_terrain_pack_dir,
)

MIB: Final = 1024 * 1024
DEFAULT_MAX_SIZE: Final = 1600
GUI_MAX_SIZE: Final = 760
PALETTE_STOPS: Final[dict[str, tuple[tuple[float, tuple[int, int, int]], ...]]] = {
    "terrain": (
        (0.00, (16, 48, 87)),
        (0.08, (31, 104, 123)),
        (0.16, (48, 145, 111)),
        (0.28, (91, 166, 82)),
        (0.42, (170, 183, 95)),
        (0.58, (181, 143, 83)),
        (0.72, (133, 100, 79)),
        (0.86, (153, 151, 145)),
        (1.00, (245, 247, 249)),
    ),
    "viridis": (
        (0.00, (68, 1, 84)),
        (0.25, (59, 82, 139)),
        (0.50, (33, 145, 140)),
        (0.75, (94, 201, 98)),
        (1.00, (253, 231, 37)),
    ),
    "turbo": (
        (0.00, (48, 18, 59)),
        (0.14, (38, 84, 214)),
        (0.29, (24, 177, 224)),
        (0.43, (72, 224, 124)),
        (0.57, (190, 232, 54)),
        (0.71, (251, 169, 40)),
        (0.86, (218, 65, 30)),
        (1.00, (122, 4, 3)),
    ),
    "grayscale": (
        (0.00, (0, 0, 0)),
        (1.00, (255, 255, 255)),
    ),
}


class TerrainViewerError(RuntimeError):
    """Raised when a terrain pack cannot be rendered safely."""


@dataclass(frozen=True)
class LoadedTerrain:
    pack_dir: Path
    raw_descriptor: dict[str, Any]
    descriptor: TerrainMapDescriptor
    grid: TerrainHeightMap


@dataclass(frozen=True)
class TerrainPreview:
    image: Image.Image
    map_id: str
    palette: str
    height_mode: str
    minimum_m: float
    maximum_m: float
    source_size: tuple[int, int]
    preview_size: tuple[int, int]
    valid_samples: int
    quantization_bits: int | None


def _default_viewer_pack_dir() -> Path:
    override = os.environ.get("BOMANA_TERRAIN_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    compressed = ROOT / "build" / "terrain-offline-balanced" / "terrain-v1"
    if (compressed / "index.json").is_file():
        return compressed
    return default_terrain_pack_dir()


def _load_index(pack_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pack_dir = pack_dir.expanduser().resolve()
    index_path = pack_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerrainViewerError(f"terrain index is invalid: {index_path}: {exc}") from exc
    if not isinstance(index, dict) or index.get("schema_version") != 1:
        raise TerrainViewerError("terrain index schema is unsupported")
    maps = index.get("maps")
    if not isinstance(maps, list) or not maps or not all(isinstance(item, dict) for item in maps):
        raise TerrainViewerError("terrain index contains no map descriptors")
    return index, maps


def list_maps(pack_dir: Path) -> list[str]:
    _index, maps = _load_index(pack_dir)
    return sorted(str(item.get("id", "")) for item in maps if item.get("id"))


def load_terrain(pack_dir: Path, map_id: str) -> LoadedTerrain:
    pack_dir = pack_dir.expanduser().resolve()
    _index, maps = _load_index(pack_dir)
    raw_descriptor = next((item for item in maps if item.get("id") == map_id), None)
    if raw_descriptor is None:
        raise TerrainViewerError(f"map is not present in the terrain pack: {map_id}")
    descriptor = TerrainMapDescriptor.from_json(raw_descriptor)
    try:
        grid = TerrainHeightMap.load(pack_dir / descriptor.file, descriptor)
    except (OSError, TerrainDataError) as exc:
        raise TerrainViewerError(f"terrain grid cannot be loaded: {map_id}: {exc}") from exc
    return LoadedTerrain(
        pack_dir=pack_dir,
        raw_descriptor=raw_descriptor,
        descriptor=descriptor,
        grid=grid,
    )


def build_palette(name: str) -> list[int]:
    try:
        stops = PALETTE_STOPS[name]
    except KeyError as exc:
        raise TerrainViewerError(f"unknown palette: {name}") from exc
    palette: list[int] = []
    for index in range(256):
        position = index / 255.0
        left = stops[0]
        right = stops[-1]
        for start, end in zip(stops, stops[1:], strict=True):
            if start[0] <= position <= end[0]:
                left, right = start, end
                break
        span = max(1e-12, right[0] - left[0])
        amount = min(1.0, max(0.0, (position - left[0]) / span))
        palette.extend(
            round(left[1][channel] + amount * (right[1][channel] - left[1][channel]))
            for channel in range(3)
        )
    return palette


def _valid_code_range(grid: TerrainHeightMap) -> tuple[int, int, int]:
    minimum = 0xFFFF
    maximum = 0
    count = 0
    for value in grid.samples:
        if grid.nodata is not None and value == grid.nodata:
            continue
        minimum = min(minimum, value)
        maximum = max(maximum, value)
        count += 1
    if count == 0:
        raise TerrainViewerError(f"terrain grid has no valid samples: {grid.map_id}")
    return minimum, maximum, count


def _height_for_code(grid: TerrainHeightMap, code: int, height_mode: str) -> float:
    world_height = grid.height_offset_m + code * grid.height_scale_m
    if height_mode == "world":
        return world_height
    if height_mode != "altitude":
        raise TerrainViewerError(f"unknown height mode: {height_mode}")
    if grid.altitude_datum_kind == "water_level":
        return max(world_height, grid.altitude_datum_m) - grid.altitude_datum_m
    return world_height


def _preview_dimensions(width: int, height: int, max_size: int) -> tuple[int, int]:
    if max_size < 128 or max_size > 8192:
        raise TerrainViewerError("maximum preview size must be between 128 and 8192 pixels")
    scale = min(1.0, max_size / max(width, height))
    return max(2, round(width * scale)), max(2, round(height * scale))


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    filename = "BomanaUiSans-Bold.ttf" if bold else "BomanaUiSans-Regular.ttf"
    path = ROOT / "bomana" / "assets" / "fonts" / filename
    try:
        return ImageFont.truetype(str(path), size=size)
    except OSError:
        return ImageFont.load_default()


def _format_height(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1000.0:
        return f"{value:,.0f} m"
    if magnitude >= 10.0:
        return f"{value:.0f} m"
    return f"{value:.1f} m"


def render_terrain_preview(
    terrain: LoadedTerrain,
    *,
    palette: str = "terrain",
    max_size: int = DEFAULT_MAX_SIZE,
    height_mode: str = "altitude",
    include_legend: bool = True,
) -> TerrainPreview:
    grid = terrain.grid
    source_min, source_max, valid_samples = _valid_code_range(grid)
    minimum_m = _height_for_code(grid, source_min, height_mode)
    maximum_m = _height_for_code(grid, source_max, height_mode)
    if maximum_m < minimum_m:
        minimum_m, maximum_m = maximum_m, minimum_m
    preview_width, preview_height = _preview_dimensions(grid.width, grid.height, max_size)
    horizontal = [
        min(grid.width - 1, round(column * (grid.width - 1) / (preview_width - 1)))
        for column in range(preview_width)
    ]
    color_indices = bytearray(preview_width * preview_height)
    alpha = bytearray(preview_width * preview_height)
    height_span = maximum_m - minimum_m
    for row in range(preview_height):
        # Tactical-map orientation: world max-Z is at the top of the preview.
        source_row = (
            grid.height
            - 1
            - min(
                grid.height - 1,
                round(row * (grid.height - 1) / (preview_height - 1)),
            )
        )
        source_offset = source_row * grid.width
        destination_offset = row * preview_width
        for column, source_column in enumerate(horizontal):
            code = grid.samples[source_offset + source_column]
            destination = destination_offset + column
            if grid.nodata is not None and code == grid.nodata:
                continue
            value_m = _height_for_code(grid, code, height_mode)
            normalized = 0.0 if height_span <= 0.0 else (value_m - minimum_m) / height_span
            color_indices[destination] = round(min(1.0, max(0.0, normalized)) * 255.0)
            alpha[destination] = 255

    indexed = Image.frombytes("L", (preview_width, preview_height), bytes(color_indices))
    indexed.putpalette(build_palette(palette))
    terrain_image = indexed.convert("RGBA")
    terrain_image.putalpha(Image.frombytes("L", terrain_image.size, bytes(alpha)))
    if include_legend:
        image = _compose_legend(
            terrain_image,
            terrain,
            palette=palette,
            height_mode=height_mode,
            minimum_m=minimum_m,
            maximum_m=maximum_m,
        )
    else:
        image = terrain_image
    raw_bits = terrain.raw_descriptor.get("quantization_bits")
    quantization_bits = int(raw_bits) if isinstance(raw_bits, int | float | str) else None
    return TerrainPreview(
        image=image,
        map_id=grid.map_id,
        palette=palette,
        height_mode=height_mode,
        minimum_m=minimum_m,
        maximum_m=maximum_m,
        source_size=(grid.width, grid.height),
        preview_size=(preview_width, preview_height),
        valid_samples=valid_samples,
        quantization_bits=quantization_bits,
    )


def _compose_legend(
    terrain_image: Image.Image,
    terrain: LoadedTerrain,
    *,
    palette: str,
    height_mode: str,
    minimum_m: float,
    maximum_m: float,
) -> Image.Image:
    top = 64
    left = 20
    right_panel = 190
    bottom = 24
    width = terrain_image.width + left + right_panel
    height = max(terrain_image.height + top + bottom, 360)
    background = (18, 24, 32, 255)
    canvas = Image.new("RGBA", (width, height), background)
    canvas.alpha_composite(terrain_image, (left, top))
    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(20, bold=True)
    label_font = _load_font(14)
    small_font = _load_font(12)
    draw.text((left, 16), terrain.grid.map_id, fill=(239, 244, 248, 255), font=title_font)
    mode_label = "8111 target altitude" if height_mode == "altitude" else "Dagor world height"
    draw.text(
        (left, 42),
        f"{terrain.grid.width} x {terrain.grid.height} samples · {mode_label}",
        fill=(164, 176, 190, 255),
        font=small_font,
    )

    bar_x = left + terrain_image.width + 34
    bar_y = top + 12
    bar_width = 28
    bar_height = max(180, min(terrain_image.height - 24, 520))
    gradient_indices = bytearray(bar_width * bar_height)
    for row in range(bar_height):
        value = round((1.0 - row / max(1, bar_height - 1)) * 255.0)
        start = row * bar_width
        gradient_indices[start : start + bar_width] = bytes([value]) * bar_width
    gradient = Image.frombytes("L", (bar_width, bar_height), bytes(gradient_indices))
    gradient.putpalette(build_palette(palette))
    canvas.alpha_composite(gradient.convert("RGBA"), (bar_x, bar_y))
    draw.rectangle(
        (bar_x - 1, bar_y - 1, bar_x + bar_width, bar_y + bar_height),
        outline=(116, 130, 145, 255),
        width=1,
    )
    for tick in range(6):
        fraction = tick / 5.0
        y = round(bar_y + fraction * bar_height)
        value = maximum_m - fraction * (maximum_m - minimum_m)
        draw.line((bar_x + bar_width, y, bar_x + bar_width + 7, y), fill=(177, 188, 199, 255))
        draw.text(
            (bar_x + bar_width + 12, y - 8),
            _format_height(value),
            fill=(225, 231, 237, 255),
            font=label_font,
        )
    draw.text(
        (bar_x, bar_y + bar_height + 18),
        palette,
        fill=(164, 176, 190, 255),
        font=small_font,
    )
    return canvas


def _png_metadata(preview: TerrainPreview, terrain: LoadedTerrain) -> PngImagePlugin.PngInfo:
    info = PngImagePlugin.PngInfo()
    values = {
        "map_id": preview.map_id,
        "palette": preview.palette,
        "height_mode": preview.height_mode,
        "minimum_m": preview.minimum_m,
        "maximum_m": preview.maximum_m,
        "source_grid": list(preview.source_size),
        "preview_grid": list(preview.preview_size),
        "terrain_sha256": terrain.descriptor.terrain_sha256,
        "pack_dir": str(terrain.pack_dir),
    }
    info.add_text("Bomana terrain preview", json.dumps(values, ensure_ascii=False))
    return info


def export_map_preview(
    pack_dir: Path,
    map_id: str,
    output_path: Path,
    *,
    palette: str = "terrain",
    max_size: int = DEFAULT_MAX_SIZE,
    height_mode: str = "altitude",
    include_legend: bool = True,
) -> TerrainPreview:
    terrain = load_terrain(pack_dir, map_id)
    preview = render_terrain_preview(
        terrain,
        palette=palette,
        max_size=max_size,
        height_mode=height_mode,
        include_legend=include_legend,
    )
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.image.save(
        output_path,
        format="PNG",
        optimize=True,
        pnginfo=_png_metadata(preview, terrain),
    )
    return preview


class TerrainViewerApp:
    def __init__(self, pack_dir: Path) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title("Bomana Terrain Pseudocolor Viewer")
        self.root.geometry("1080x900")
        self.pack_var = tk.StringVar(value=str(pack_dir.expanduser().resolve()))
        self.map_var = tk.StringVar()
        self.palette_var = tk.StringVar(value="terrain")
        self.mode_var = tk.StringVar(value="altitude")
        self.status_var = tk.StringVar(value="Ready")
        self.preview: TerrainPreview | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self._build_ui()
        self._reload_maps()

    def _build_ui(self) -> None:
        ttk = self.ttk
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        controls = ttk.Frame(outer)
        controls.pack(fill="x")
        ttk.Label(controls, text="Pack").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.pack_var).grid(
            row=0,
            column=1,
            columnspan=5,
            sticky="ew",
            padx=(8, 8),
        )
        ttk.Button(controls, text="Browse", command=self._choose_pack).grid(row=0, column=6)
        ttk.Label(controls, text="Map").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.map_box = ttk.Combobox(controls, textvariable=self.map_var, state="readonly")
        self.map_box.grid(row=1, column=1, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(controls, text="Palette").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Combobox(
            controls,
            textvariable=self.palette_var,
            values=tuple(PALETTE_STOPS),
            state="readonly",
            width=12,
        ).grid(row=1, column=3, sticky="w", padx=(8, 12), pady=(10, 0))
        ttk.Label(controls, text="Height").grid(row=1, column=4, sticky="w", pady=(10, 0))
        ttk.Combobox(
            controls,
            textvariable=self.mode_var,
            values=("altitude", "world"),
            state="readonly",
            width=10,
        ).grid(row=1, column=5, sticky="w", padx=(8, 12), pady=(10, 0))
        ttk.Button(controls, text="Render", command=self._render).grid(
            row=1, column=6, pady=(10, 0)
        )
        controls.columnconfigure(1, weight=1)
        preview_frame = ttk.Frame(outer, padding=(0, 12, 0, 8))
        preview_frame.pack(fill="both", expand=True)
        self.preview_label = ttk.Label(preview_frame, anchor="center")
        self.preview_label.pack(fill="both", expand=True)
        footer = ttk.Frame(outer)
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.save_button = ttk.Button(footer, text="Save PNG", command=self._save, state="disabled")
        self.save_button.pack(side="right")

    def _choose_pack(self) -> None:
        selected = self.filedialog.askdirectory(initialdir=self.pack_var.get())
        if selected:
            self.pack_var.set(selected)
            self._reload_maps()

    def _reload_maps(self) -> None:
        try:
            maps = list_maps(Path(self.pack_var.get()))
        except (OSError, TerrainViewerError) as exc:
            self.messagebox.showerror("Terrain pack", str(exc))
            return
        self.map_box.configure(values=maps)
        if maps:
            self.map_var.set(maps[0])
            self.status_var.set(f"{len(maps)} maps available")

    def _render(self) -> None:
        map_id = self.map_var.get().strip()
        if not map_id:
            return
        pack_dir = Path(self.pack_var.get())
        palette = self.palette_var.get()
        height_mode = self.mode_var.get()
        self.status_var.set(f"Loading {map_id}...")
        self.save_button.configure(state="disabled")

        def worker() -> None:
            try:
                terrain = load_terrain(pack_dir, map_id)
                preview = render_terrain_preview(
                    terrain,
                    palette=palette,
                    max_size=GUI_MAX_SIZE,
                    height_mode=height_mode,
                )
            except (OSError, TerrainDataError, TerrainViewerError, ValueError) as exc:
                message = str(exc)
                self.root.after(0, lambda: self._render_failed(message))
                return
            self.root.after(0, lambda: self._show_preview(preview))

        threading.Thread(target=worker, daemon=True).start()

    def _render_failed(self, message: str) -> None:
        self.status_var.set("Render failed")
        self.messagebox.showerror("Terrain preview", message)

    def _show_preview(self, preview: TerrainPreview) -> None:
        self.preview = preview
        self.photo = ImageTk.PhotoImage(preview.image)
        self.preview_label.configure(image=self.photo)
        bits = f" · {preview.quantization_bits}-bit" if preview.quantization_bits else ""
        self.status_var.set(
            f"{preview.map_id} · {_format_height(preview.minimum_m)} to "
            f"{_format_height(preview.maximum_m)}{bits}"
        )
        self.save_button.configure(state="normal")

    def _save(self) -> None:
        if self.preview is None:
            return
        path = self.filedialog.asksaveasfilename(
            defaultextension=".png",
            initialfile=f"{self.preview.map_id}-{self.preview.palette}.png",
            filetypes=(("PNG image", "*.png"),),
        )
        if not path:
            return
        self.preview.image.save(path, format="PNG", optimize=True)
        self.status_var.set(f"Saved {path}")

    def run(self) -> None:
        self.root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=_default_viewer_pack_dir())
    parser.add_argument("--map", dest="map_id")
    parser.add_argument("--list", action="store_true", help="list map ids and exit")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--palette", choices=tuple(PALETTE_STOPS), default="terrain")
    parser.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE)
    parser.add_argument("--height", choices=("altitude", "world"), default="altitude")
    parser.add_argument("--no-legend", action="store_true")
    parser.add_argument("--open", action="store_true", help="open the exported PNG")
    parser.add_argument("--gui", action="store_true", help="launch the desktop viewer")
    return parser


def _open_file(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        webbrowser.open(path.as_uri())


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.list:
            for map_id in list_maps(args.pack):
                print(map_id)
            return 0
        if args.gui or not args.map_id:
            TerrainViewerApp(args.pack).run()
            return 0
        output = args.output or (
            ROOT / "dist" / "terrain-previews" / f"{args.map_id}-{args.palette}.png"
        )
        preview = export_map_preview(
            args.pack,
            args.map_id,
            output,
            palette=args.palette,
            max_size=args.max_size,
            height_mode=args.height,
            include_legend=not args.no_legend,
        )
        result = {
            "output": str(output.resolve()),
            "map_id": preview.map_id,
            "palette": preview.palette,
            "height_mode": preview.height_mode,
            "height_range_m": [preview.minimum_m, preview.maximum_m],
            "source_grid": list(preview.source_size),
            "preview_grid": list(preview.preview_size),
            "valid_samples": preview.valid_samples,
            "quantization_bits": preview.quantization_bits,
            "output_bytes": output.resolve().stat().st_size,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.open:
            _open_file(output.resolve())
        return 0
    except (OSError, TerrainDataError, TerrainViewerError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
