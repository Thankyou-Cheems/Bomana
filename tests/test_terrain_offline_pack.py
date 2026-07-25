import hashlib
import json
import zlib
from array import array
from pathlib import Path
from zipfile import ZipFile

import pytest

from bomana.core.terrain_elevation import (
    TERRAIN_GRID_MAGIC,
    TERRAIN_GRID_MAGIC_V2,
    TERRAIN_GRID_PREFIX,
    TerrainDataError,
    TerrainHeightMap,
    TerrainMapDescriptor,
)
from tools.build_terrain_offline_pack import (
    TerrainPackBuildError,
    build_archive,
    build_offline_pack,
    encode_bth2_grid,
    quantize_grid,
    verify_offline_pack,
)


def _source_grid() -> TerrainHeightMap:
    return TerrainHeightMap(
        map_id="test_map",
        width=4,
        height=3,
        world_bounds=(0.0, 0.0, 30.0, 20.0),
        spacing_m=(10.0, 10.0),
        height_offset_m=-20.0,
        height_scale_m=0.1,
        altitude_datum_m=5.0,
        altitude_datum_kind="water_level",
        samples=array("H", (0, 7, 25, 80, 3, 11, 40, 90, 8, 20, 60, 0xFFFF)),
        nodata=0xFFFF,
    )


def _descriptor(raw_sha256: str, *, filename: str = "test_map.bth") -> TerrainMapDescriptor:
    return TerrainMapDescriptor.from_json(
        {
            "id": "test_map",
            "file": filename,
            "fingerprint": "0" * 64,
            "world_bounds": [0.0, 0.0, 30.0, 20.0],
            "map_bounds": [0.0, 0.0, 30.0, 20.0],
            "grid_size": [4, 3],
            "terrain_sha256": raw_sha256,
            "altitude_datum_m": 5.0,
            "altitude_datum_kind": "water_level",
        }
    )


def _write_source_pack(pack_dir: Path) -> None:
    pack_dir.mkdir()
    grid = _source_grid()
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
    (pack_dir / "test_map.bth").write_bytes(
        TERRAIN_GRID_PREFIX.pack(TERRAIN_GRID_MAGIC, len(header_bytes))
        + header_bytes
        + zlib.compress(raw)
    )
    index = {
        "schema_version": 1,
        "kind": "terrain-only",
        "maps": [
            {
                "id": "test_map",
                "file": "test_map.bth",
                "fingerprint": "0" * 64,
                "world_bounds": list(grid.world_bounds),
                "map_bounds": list(grid.world_bounds),
                "grid_size": [grid.width, grid.height],
                "spacing_m": [grid.spacing_x_m, grid.spacing_z_m],
                "interpolation": grid.interpolation,
                "source_kind": "land-ray",
                "terrain_sha256": digest,
                "altitude_datum_m": grid.altitude_datum_m,
                "altitude_datum_kind": grid.altitude_datum_kind,
                "validation": {"p95_abs_error_m": 1.0},
                "quality_target_met": True,
            }
        ],
        "failures": [],
    }
    (pack_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")


def test_quantization_is_bounded_and_preserves_nodata() -> None:
    grid = _source_grid()

    quantized = quantize_grid(grid, max_error_m=0.05)

    assert 8 <= quantized.bits < 16
    assert quantized.max_error_m <= 0.05
    assert quantized.nodata == (1 << quantized.bits) - 1
    assert quantized.samples[-1] == quantized.nodata
    for source, target in zip(grid.samples[:-1], quantized.samples[:-1], strict=True):
        source_height = grid.height_offset_m + source * grid.height_scale_m
        target_height = quantized.height_offset_m + target * quantized.height_scale_m
        assert abs(source_height - target_height) <= 0.05 + 1e-9


def test_zero_error_budget_uses_identity_samples() -> None:
    grid = _source_grid()

    quantized = quantize_grid(grid, max_error_m=0.0)

    assert quantized.bits == 16
    assert quantized.mode == "identity"
    assert quantized.max_error_m == 0.0
    assert quantized.samples == grid.samples


def test_bth2_round_trip_loads_through_production_validator(tmp_path: Path) -> None:
    grid = _source_grid()
    source_raw = grid.samples.tobytes()
    source_digest = hashlib.sha256(source_raw).hexdigest()
    descriptor = _descriptor(source_digest)
    raw_descriptor = {
        "validation": {"p95_abs_error_m": 2.8},
        "source_sha256": "1" * 64,
    }

    encoded = encode_bth2_grid(
        grid,
        descriptor,
        raw_descriptor,
        max_quantization_error_m=0.5,
        quality_p95_limit_m=3.0,
        zstd_level=3,
    )
    path = tmp_path / descriptor.file
    path.write_bytes(encoded.data)
    converted_descriptor = _descriptor(encoded.raw_sha256)

    loaded = TerrainHeightMap.load(path, converted_descriptor)

    assert encoded.data.startswith(TERRAIN_GRID_MAGIC_V2)
    assert encoded.quantization.max_error_m <= 0.2 + 1e-9
    assert encoded.quality_p95_upper_bound_m <= 3.0 + 1e-9
    assert loaded.samples == encoded.quantization.samples
    assert loaded.nodata == encoded.quantization.nodata
    assert loaded.height_at(10.0, 10.0) == pytest.approx(
        encoded.quantization.height_offset_m
        + encoded.quantization.samples[5] * encoded.quantization.height_scale_m
    )


def test_bth2_rejects_trailing_compressed_data(tmp_path: Path) -> None:
    grid = _source_grid()
    source_digest = hashlib.sha256(grid.samples.tobytes()).hexdigest()
    descriptor = _descriptor(source_digest)
    encoded = encode_bth2_grid(
        grid,
        descriptor,
        {"validation": {"p95_abs_error_m": 1.0}},
        max_quantization_error_m=0.5,
        quality_p95_limit_m=3.0,
        zstd_level=3,
    )
    path = tmp_path / descriptor.file
    path.write_bytes(encoded.data + b"trailing")

    with pytest.raises(TerrainDataError, match="sample count"):
        TerrainHeightMap.load(path, _descriptor(encoded.raw_sha256))


def test_full_pack_build_verifies_and_archives(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "terrain-v1"
    archive = tmp_path / "Bomana-terrain-offline.zip"
    _write_source_pack(source)

    manifest = build_offline_pack(
        source,
        output,
        max_quantization_error_m=0.5,
        quality_p95_limit_m=3.0,
        zstd_level=3,
    )
    verification = verify_offline_pack(output)
    archive_result = build_archive(output, archive)

    assert manifest["maps"] == 1
    assert manifest["max_quantization_error_m"] <= 0.5
    assert verification["valid"] is True
    assert verification["maps"] == 1
    assert archive_result["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert archive.with_suffix(".zip.sha256").is_file()
    with ZipFile(archive) as package:
        assert "terrain-v1/index.json" in package.namelist()
        assert "terrain-v1/manifest.json" in package.namelist()
        assert "terrain-v1/INSTALL.txt" in package.namelist()


def test_pack_builder_refuses_nonempty_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "terrain-v1"
    _write_source_pack(source)
    output.mkdir()
    (output / "keep.txt").write_text("user data", encoding="utf-8")

    with pytest.raises(TerrainPackBuildError, match="not empty"):
        build_offline_pack(source, output, zstd_level=3)

    assert (output / "keep.txt").read_text(encoding="utf-8") == "user data"
