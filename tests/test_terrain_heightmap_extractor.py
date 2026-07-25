import json
import math
import struct
from pathlib import Path

import pytest

from tools.terrain_heightmap_extractor import (
    HMAP_CBLOCK_DELTAC_VERSION,
    HMAP_WIDTH_BITS,
    LAND_RAY_CELL,
    AltitudeDatum,
    HeightMapTracer,
    LandRayTracer,
    apply_altitude_datums_to_pack,
    audit_terrain_pack,
    build_native_heightmap_grid,
    build_terrain_grid,
    decompress_heightmap,
    decompress_land_ray,
    encode_terrain_grid,
    find_heightmap,
    find_land_mesh,
    iter_dbld_blocks,
    read_altitude_datum,
    resolve_level_config_dir,
    validate_terrain_grid,
)


def _array_payload(count: int, raw: bytes) -> bytes:
    return struct.pack("<I", count) + raw


def _single_triangle_land_ray() -> bytes:
    header = b"LTdump" + struct.pack(
        "<iif3f6f",
        1,
        1,
        100.0,
        0.0,
        0.0,
        0.0,
        0.0,
        10.0,
        0.0,
        100.0,
        30.0,
        100.0,
    )
    cell = LAND_RAY_CELL.pack(
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        1.0,
        1.0,
        0.0,
        30.0,
        0,
        0,
        1,
        0,
        0,
        0,
        0,
    )
    grid = struct.pack("<2I", 0, 2)
    faces = struct.pack("<6H", 0, 1, 2, 1, 3, 2)
    vertices = struct.pack(
        "<16H",
        0,
        10,
        0,
        0,
        100,
        20,
        0,
        0,
        0,
        30,
        100,
        0,
        100,
        40,
        100,
        0,
    )
    face_indices = struct.pack("<2H", 0, 1)
    return b"".join(
        (
            header,
            _array_payload(1, cell),
            _array_payload(2, grid),
            _array_payload(0, b""),
            _array_payload(6, faces),
            _array_payload(4, vertices),
            _array_payload(2, face_indices),
        )
    )


def _synthetic_level(stream: bytes) -> bytes:
    decoded = struct.pack("<I", len(stream)) + stream
    land_header = b"lndm" + struct.pack(
        "<iffiiiiiiiii",
        4,
        1.0,
        1.0,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        20,
    )
    land_data = land_header + struct.pack("<I", len(decoded)) + decoded
    block = struct.pack("<I", 4 + len(land_data)) + b"lmap" + land_data
    return b"DBLD3x64" + b"\0" * 4 + block


def _synthetic_heightmap_level() -> bytes:
    width = height = 8
    width_version = width | (HMAP_CBLOCK_DELTAC_VERSION << HMAP_WIDTH_BITS)
    header = struct.pack(
        "<5fII4iI",
        10.0,
        -50.0,
        1000.0,
        0.0,
        0.0,
        width_version,
        height,
        0,
        0,
        width,
        height,
        3,
    )
    block_info = struct.pack("<HH", 100, 1000)
    absolute_variance = bytes(range(width * height))
    delta_variance = bytes(
        [absolute_variance[0]]
        + [
            (absolute_variance[index] - absolute_variance[index - 1]) & 0xFF
            for index in range(1, len(absolute_variance))
        ]
    )
    chunk = block_info + delta_variance
    heightmap = header + struct.pack("<I", len(chunk)) + chunk
    block = struct.pack("<I", 4 + len(heightmap)) + b"\0HM2" + heightmap
    return b"DBLD3x64" + b"\0" * 4 + block


def test_synthetic_land_ray_returns_barycentric_terrain_height() -> None:
    tracer = LandRayTracer(_single_triangle_land_ray())

    assert tracer.height_at(25.0, 25.0) == pytest.approx(17.5)
    assert tracer.height_at(75.0, 75.0) == pytest.approx(32.5)
    assert tracer.height_at(101.0, 25.0) is None
    assert tracer.height_at(math.nan, 25.0) is None


def test_dbld_lmap_contract_and_regular_grid_validation() -> None:
    level = _synthetic_level(_single_triangle_land_ray())
    blocks = iter_dbld_blocks(level)
    block, header = find_land_mesh(level)
    stream = decompress_land_ray(level, header)
    tracer = LandRayTracer(stream)
    grid = build_terrain_grid(tracer, spacing_m=50.0)
    validation = validate_terrain_grid(tracer, grid, sample_count=1000, seed=7)

    assert blocks == (block,)
    assert block.tag == b"lmap"
    assert header.ray_block_offset > block.data_offset
    assert grid.width == 3
    assert grid.height == 3
    assert grid.height_at(25.0, 25.0) == pytest.approx(17.5, abs=0.1)
    assert validation["compared"] > 400
    assert validation["p95_abs_error_m"] < 0.1


def test_hm2_delta_blocks_preserve_native_samples_and_diamond_interpolation() -> None:
    level = _synthetic_heightmap_level()
    _block, header = find_heightmap(level)
    block_infos, variance = decompress_heightmap(level, header)
    tracer = HeightMapTracer(header, block_infos, variance)
    grid = build_native_heightmap_grid(tracer)
    validation = validate_terrain_grid(tracer, grid, sample_count=500, seed=13)

    assert variance == bytes(range(64))
    assert tracer.sample_raw(0, 0) == 100
    assert tracer.sample_raw(7, 7) == 100 + (63 * 1000 + 127) // 255
    assert grid.interpolation == "diamond"
    assert grid.nodata is None
    assert grid.height_at(23.0, 47.0) == pytest.approx(tracer.height_at(23.0, 47.0))
    assert validation["p95_abs_error_m"] == pytest.approx(0.0)


def test_level_config_water_level_defines_8111_altitude_datum(tmp_path: Path) -> None:
    levels = tmp_path / "aces.vromfs.bin_u" / "levels"
    levels.mkdir(parents=True)
    config = levels / "air_israel.blkx"
    config.write_text(
        json.dumps(
            {
                "water_level": 60.0,
                "mapCoord0": [-65536.0, -65536.0],
                "mapCoord1": [65536.0, 65536.0],
            }
        ),
        encoding="utf-8",
    )
    (levels / "kursk.blkx").write_text(
        json.dumps(
            {
                "tag": "kursk",
                "mapCoord0": [-32768.0, -32768.0],
                "mapCoord1": [32768.0, 32768.0],
            }
        ),
        encoding="utf-8",
    )

    resolved = resolve_level_config_dir(tmp_path)
    datum = read_altitude_datum(resolved, "air_israel")

    assert resolved == levels
    assert datum.value_m == 60.0
    assert datum.kind == "water_level"
    assert datum.map_bounds == (-65536.0, -65536.0, 65536.0, 65536.0)
    assert len(datum.source_sha256) == 64
    default_datum = read_altitude_datum(resolved, "kursk")
    assert default_datum.value_m == 0.0
    assert default_datum.kind == "water_level_default_zero"


def test_existing_pack_can_receive_altitude_datums_without_resampling(tmp_path: Path) -> None:
    level = _synthetic_heightmap_level()
    _block, header = find_heightmap(level)
    block_infos, variance = decompress_heightmap(level, header)
    grid = build_native_heightmap_grid(HeightMapTracer(header, block_infos, variance))
    initial_datum = AltitudeDatum(
        value_m=0.0,
        kind="water_level",
        source_file="air_israel.blkx",
        source_sha256="0" * 64,
        map_bounds=(-65536.0, -65536.0, 65536.0, 65536.0),
    )
    encoded, metadata = encode_terrain_grid(
        "air_israel",
        grid,
        source_sha256="1" * 64,
        altitude_datum=initial_datum,
        validation={"requested": 0, "compared": 0},
    )
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    grid_path = pack_dir / "air_israel.bth"
    grid_path.write_bytes(encoded)
    (pack_dir / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "maps": [
                    {
                        "id": "air_israel",
                        "file": grid_path.name,
                        "fingerprint": "0" * 64,
                        "world_bounds": list(grid.world_bounds),
                        "grid_size": [grid.width, grid.height],
                        "terrain_sha256": metadata["raw_sha256"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "air_israel.blkx").write_text(
        json.dumps(
            {
                "water_level": 60.0,
                "mapCoord0": [-65536.0, -65536.0],
                "mapCoord1": [65536.0, 65536.0],
            }
        ),
        encoding="utf-8",
    )

    index = apply_altitude_datums_to_pack(pack_dir, config_dir)

    assert index["maps"][0]["altitude_datum_m"] == 60.0
    assert index["maps"][0]["map_bounds"] == [
        -65536.0,
        -65536.0,
        65536.0,
        65536.0,
    ]
    assert "game_root" not in index
    assert "level_config_dir" not in index
    updated = grid_path.read_bytes()
    header_size = struct.unpack_from("<I", updated, 4)[0]
    updated_header = json.loads(updated[8 : 8 + header_size])
    assert updated_header["altitude_datum_m"] == 60.0
    audit = audit_terrain_pack(pack_dir)
    assert audit["valid"] is True
    assert audit["loaded_maps"] == 1
    assert audit["altitude_datum_kinds"] == {"water_level": 1}
    assert audit["validation_p95_m"] == {"maps": 0, "mean": None, "max": None}
