import hashlib
import json
import zlib
from array import array
from pathlib import Path

from PIL import Image

from bomana.core.terrain_elevation import (
    TERRAIN_GRID_MAGIC,
    TERRAIN_GRID_PREFIX,
    TerrainHeightMap,
    TerrainMapDescriptor,
)
from tools.terrain_heightmap_viewer import (
    LoadedTerrain,
    build_palette,
    export_map_preview,
    list_maps,
    render_terrain_preview,
)


def _grid() -> TerrainHeightMap:
    return TerrainHeightMap(
        map_id="preview_map",
        width=4,
        height=3,
        world_bounds=(0.0, 0.0, 30.0, 20.0),
        spacing_m=(10.0, 10.0),
        height_offset_m=-10.0,
        height_scale_m=1.0,
        altitude_datum_m=5.0,
        altitude_datum_kind="water_level",
        samples=array("H", (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 0xFFFF)),
        nodata=0xFFFF,
    )


def _descriptor(digest: str) -> TerrainMapDescriptor:
    return TerrainMapDescriptor.from_json(
        {
            "id": "preview_map",
            "file": "preview_map.bth",
            "fingerprint": "0" * 64,
            "world_bounds": [0.0, 0.0, 30.0, 20.0],
            "map_bounds": [0.0, 0.0, 30.0, 20.0],
            "grid_size": [4, 3],
            "terrain_sha256": digest,
            "altitude_datum_m": 5.0,
            "altitude_datum_kind": "water_level",
        }
    )


def _loaded() -> LoadedTerrain:
    grid = _grid()
    digest = hashlib.sha256(grid.samples.tobytes()).hexdigest()
    return LoadedTerrain(
        pack_dir=Path("terrain-v1"),
        raw_descriptor={"quantization_bits": 12},
        descriptor=_descriptor(digest),
        grid=grid,
    )


def _write_pack(pack_dir: Path) -> None:
    pack_dir.mkdir()
    grid = _grid()
    raw = grid.samples.tobytes()
    digest = hashlib.sha256(raw).hexdigest()
    header = {
        "schema_version": 1,
        "map_id": grid.map_id,
        "width": grid.width,
        "height": grid.height,
        "world_bounds": list(grid.world_bounds),
        "map_bounds": list(grid.world_bounds),
        "spacing_m": [grid.spacing_x_m, grid.spacing_z_m],
        "interpolation": grid.interpolation,
        "height_offset_m": grid.height_offset_m,
        "height_scale_m": grid.height_scale_m,
        "altitude_datum_m": grid.altitude_datum_m,
        "altitude_datum_kind": grid.altitude_datum_kind,
        "nodata": grid.nodata,
        "raw_sha256": digest,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    (pack_dir / "preview_map.bth").write_bytes(
        TERRAIN_GRID_PREFIX.pack(TERRAIN_GRID_MAGIC, len(header_bytes))
        + header_bytes
        + zlib.compress(raw)
    )
    (pack_dir / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "maps": [
                    {
                        "id": "preview_map",
                        "file": "preview_map.bth",
                        "fingerprint": "0" * 64,
                        "world_bounds": list(grid.world_bounds),
                        "map_bounds": list(grid.world_bounds),
                        "grid_size": [grid.width, grid.height],
                        "terrain_sha256": digest,
                        "altitude_datum_m": grid.altitude_datum_m,
                        "altitude_datum_kind": grid.altitude_datum_kind,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_all_pseudocolor_palettes_have_256_rgb_entries() -> None:
    for name in ("terrain", "viridis", "turbo", "grayscale"):
        palette = build_palette(name)
        assert len(palette) == 256 * 3
        assert all(0 <= channel <= 255 for channel in palette)


def test_preview_uses_effective_8111_altitude_and_transparent_nodata() -> None:
    preview = render_terrain_preview(
        _loaded(),
        palette="terrain",
        max_size=128,
        height_mode="altitude",
        include_legend=False,
    )

    assert preview.image.size == (4, 3)
    assert preview.minimum_m == 0.0
    assert preview.maximum_m == 35.0
    assert preview.quantization_bits == 12
    # Source rows are flipped into tactical-map orientation, so source bottom-right is top-right.
    assert preview.image.getpixel((3, 0))[3] == 0
    assert preview.image.getpixel((0, 0))[3] == 255


def test_preview_legend_contains_map_and_height_context() -> None:
    preview = render_terrain_preview(
        _loaded(),
        palette="viridis",
        max_size=128,
        height_mode="world",
        include_legend=True,
    )

    assert preview.image.width > preview.preview_size[0]
    assert preview.image.height >= 360
    assert preview.minimum_m == -10.0
    assert preview.maximum_m == 40.0


def test_pack_export_writes_openable_png_with_metadata(tmp_path: Path) -> None:
    pack_dir = tmp_path / "terrain-v1"
    output = tmp_path / "preview.png"
    _write_pack(pack_dir)

    preview = export_map_preview(
        pack_dir,
        "preview_map",
        output,
        palette="turbo",
        max_size=128,
    )

    assert list_maps(pack_dir) == ["preview_map"]
    assert preview.map_id == "preview_map"
    with Image.open(output) as image:
        image.verify()
    with Image.open(output) as image:
        metadata = json.loads(image.text["Bomana terrain preview"])
        assert metadata["map_id"] == "preview_map"
        assert metadata["palette"] == "turbo"
