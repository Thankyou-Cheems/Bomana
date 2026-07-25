import hashlib
import io
import json
import struct
import zlib
from array import array
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import bomana.core.terrain_elevation as terrain_elevation
from bomana.core.state import MapInfo
from bomana.core.terrain_elevation import (
    TERRAIN_GRID_MAGIC,
    TERRAIN_GRID_PREFIX,
    TerrainDataError,
    TerrainElevationService,
    TerrainHeightMap,
    TerrainMapDescriptor,
    image_dhash,
    normalized_map_to_world,
)


def test_default_terrain_pack_prefers_explicit_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override = tmp_path / "override"
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setattr(terrain_elevation, "BUNDLED_TERRAIN_PACK_DIR", bundled)
    monkeypatch.setenv("BOMANA_TERRAIN_DIR", str(override))

    assert terrain_elevation.default_terrain_pack_dir() == override


def test_default_terrain_pack_uses_bundled_release_before_user_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.delenv("BOMANA_TERRAIN_DIR", raising=False)
    monkeypatch.setattr(terrain_elevation, "BUNDLED_TERRAIN_PACK_DIR", bundled)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))

    assert terrain_elevation.default_terrain_pack_dir() == bundled

    bundled.rmdir()
    assert terrain_elevation.default_terrain_pack_dir() == tmp_path / "home" / ".bomana" / (
        "terrain-v1"
    )


def _pattern_image(*, invert: bool = False) -> bytes:
    image = Image.new("RGB", (128, 128), "white" if invert else "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 72, 46), fill="black" if invert else "white")
    draw.ellipse((52, 54, 120, 120), fill="black" if invert else "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_tactical_map_hash_rejects_oversized_decoded_dimensions() -> None:
    image = Image.new(
        "L",
        (terrain_elevation.MAX_TACTICAL_MAP_WIDTH + 1, 1),
        0,
    )
    output = io.BytesIO()
    image.save(output, format="PNG")

    with pytest.raises(TerrainDataError, match="dimensions exceed"):
        image_dhash(output.getvalue())


def test_tactical_map_hash_enforces_pixel_budget_before_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(terrain_elevation, "MAX_TACTICAL_MAP_PIXELS", 100)
    image = Image.new("RGB", (11, 10), "black")

    with pytest.raises(TerrainDataError, match="dimensions exceed"):
        terrain_elevation.pil_image_dhash(image)


def _write_grid_pack(
    pack_dir: Path,
    image_bytes: bytes,
    *,
    map_bounds: tuple[float, float, float, float] = (-100.0, -200.0, 100.0, 200.0),
) -> None:
    samples = array("H", (0, 100, 200, 300))
    raw = samples.tobytes()
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    header = {
        "schema_version": 1,
        "map_id": "test_map",
        "width": 2,
        "height": 2,
        "world_bounds": [-100.0, -200.0, 100.0, 200.0],
        "map_bounds": list(map_bounds),
        "height_offset_m": 10.0,
        "height_scale_m": 0.5,
        "altitude_datum_m": 10.0,
        "altitude_datum_kind": "water_level",
        "raw_sha256": raw_sha256,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode()
    grid_bytes = (
        TERRAIN_GRID_PREFIX.pack(TERRAIN_GRID_MAGIC, len(header_bytes))
        + header_bytes
        + zlib.compress(raw)
    )
    pack_dir.mkdir()
    (pack_dir / "test_map.bth").write_bytes(grid_bytes)
    index = {
        "schema_version": 1,
        "maps": [
            {
                "id": "test_map",
                "file": "test_map.bth",
                "fingerprint": image_dhash(image_bytes),
                "world_bounds": [-100.0, -200.0, 100.0, 200.0],
                "map_bounds": list(map_bounds),
                "grid_size": [2, 2],
                "terrain_sha256": raw_sha256,
                "altitude_datum_m": 10.0,
                "altitude_datum_kind": "water_level",
            }
        ],
    }
    (pack_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")


def test_normalized_8111_coordinates_convert_to_world_xz_with_inverted_y() -> None:
    assert normalized_map_to_world(
        0.25,
        0.75,
        [-100.0, -200.0],
        [100.0, 200.0],
    ) == pytest.approx((-50.0, -100.0))


def test_service_identifies_map_and_interpolates_target_height(tmp_path: Path) -> None:
    image_bytes = _pattern_image()
    pack_dir = tmp_path / "terrain"
    _write_grid_pack(pack_dir, image_bytes)
    service = TerrainElevationService(pack_dir)

    match = service.update_map_image(
        image_bytes,
        map_min=(-100.0, -200.0),
        map_max=(100.0, 200.0),
    )

    assert match is not None
    assert match.map_id == "test_map"
    assert match.distance == 0
    assert service.current_altitude_datum_m == pytest.approx(10.0)
    assert service.height_at_world(0.0, 0.0) == pytest.approx(75.0)
    map_info = MapInfo(
        valid=True,
        map_min=[-100.0, -200.0],
        map_max=[100.0, 200.0],
    )
    assert service.height_at_normalized(0.5, 0.5, map_info) == pytest.approx(75.0)
    assert service.altitude_context_at_normalized(0.5, 0.5, map_info) == pytest.approx((75.0, 10.0))


def test_service_rejects_unrelated_map_image(tmp_path: Path) -> None:
    reference = _pattern_image()
    pack_dir = tmp_path / "terrain"
    _write_grid_pack(pack_dir, reference)
    service = TerrainElevationService(pack_dir, max_fingerprint_distance=0)

    assert service.update_map_image(_pattern_image(invert=True)) is None
    assert service.current_altitude_datum_m is None
    assert service.height_at_world(0.0, 0.0) is None


def test_service_rejects_matching_image_with_incompatible_map_bounds(tmp_path: Path) -> None:
    image_bytes = _pattern_image()
    pack_dir = tmp_path / "terrain"
    _write_grid_pack(pack_dir, image_bytes)
    service = TerrainElevationService(pack_dir)

    assert (
        service.update_map_image(
            image_bytes,
            map_min=(-1000.0, -1000.0),
            map_max=(1000.0, 1000.0),
        )
        is None
    )


def test_service_matches_8111_map_bounds_separately_from_grid_coverage(
    tmp_path: Path,
) -> None:
    image_bytes = _pattern_image()
    pack_dir = tmp_path / "terrain"
    _write_grid_pack(
        pack_dir,
        image_bytes,
        map_bounds=(-1000.0, -1000.0, 1000.0, 1000.0),
    )
    service = TerrainElevationService(pack_dir)

    match = service.update_map_image(
        image_bytes,
        map_min=(-1000.0, -1000.0),
        map_max=(1000.0, 1000.0),
    )

    assert match is not None
    assert service.height_at_world(0.0, 0.0) == pytest.approx(75.0)
    assert service.height_at_world(500.0, 0.0) is None


def test_descriptor_rejects_parent_path_escape() -> None:
    with pytest.raises(Exception, match="unsafe name"):
        TerrainMapDescriptor.from_json(
            {
                "id": "test",
                "file": "../test.bth",
                "fingerprint": "0" * 64,
                "world_bounds": [0.0, 0.0, 1.0, 1.0],
                "map_bounds": [0.0, 0.0, 1.0, 1.0],
                "grid_size": [2, 2],
                "terrain_sha256": "0" * 64,
                "altitude_datum_m": 0.0,
                "altitude_datum_kind": "water_level_default_zero",
            }
        )


def test_grid_header_prefix_is_fixed_little_endian() -> None:
    assert TERRAIN_GRID_PREFIX.pack(TERRAIN_GRID_MAGIC, 7) == b"BTH1" + struct.pack("<I", 7)


def test_explicit_water_surface_clamps_underwater_terrain_only() -> None:
    common = {
        "map_id": "surface",
        "width": 2,
        "height": 2,
        "world_bounds": (0.0, 0.0, 1.0, 1.0),
        "spacing_m": (1.0, 1.0),
        "height_offset_m": -100.0,
        "height_scale_m": 1.0,
        "samples": array("H", (0, 0, 0, 0)),
    }
    water = TerrainHeightMap(
        **common,
        altitude_datum_m=60.0,
        altitude_datum_kind="water_level",
    )
    dry = TerrainHeightMap(
        **common,
        altitude_datum_m=0.0,
        altitude_datum_kind="water_level_default_zero",
    )

    assert water.altitude_at(0.5, 0.5) == pytest.approx(0.0)
    assert dry.altitude_at(0.5, 0.5) == pytest.approx(-100.0)


def test_native_diamond_grid_keeps_uint16_max_as_valid_height(tmp_path: Path) -> None:
    samples = array("H", (0, 100, 200, 0xFFFF))
    raw = samples.tobytes()
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    header = {
        "schema_version": 1,
        "map_id": "native_map",
        "width": 2,
        "height": 2,
        "world_bounds": [0.0, 0.0, 20.0, 20.0],
        "map_bounds": [0.0, 0.0, 20.0, 20.0],
        "spacing_m": [10.0, 10.0],
        "interpolation": "diamond",
        "height_offset_m": 0.0,
        "height_scale_m": 1.0,
        "altitude_datum_m": 0.0,
        "altitude_datum_kind": "water_level_default_zero",
        "nodata": None,
        "raw_sha256": raw_sha256,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode()
    grid_path = tmp_path / "native_map.bth"
    grid_path.write_bytes(
        TERRAIN_GRID_PREFIX.pack(TERRAIN_GRID_MAGIC, len(header_bytes))
        + header_bytes
        + zlib.compress(raw)
    )
    descriptor = TerrainMapDescriptor.from_json(
        {
            "id": "native_map",
            "file": "native_map.bth",
            "fingerprint": "0" * 64,
            "world_bounds": [0.0, 0.0, 20.0, 20.0],
            "map_bounds": [0.0, 0.0, 20.0, 20.0],
            "grid_size": [2, 2],
            "terrain_sha256": raw_sha256,
            "altitude_datum_m": 0.0,
            "altitude_datum_kind": "water_level_default_zero",
        }
    )

    grid = TerrainHeightMap.load(grid_path, descriptor)

    assert grid.height_at(10.0, 10.0) == pytest.approx(65535.0)
    assert grid.height_at(20.0, 20.0) is None
