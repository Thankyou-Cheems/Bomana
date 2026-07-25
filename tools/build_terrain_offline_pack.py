#!/usr/bin/env python3
"""Build a compact, integrity-checked offline terrain pack from a BTH1 pack.

The output remains a drop-in ``terrain-v1`` directory, but each grid uses the
runtime-compatible BTH2 payload: optional error-bounded sample quantization,
a reversible two-dimensional predictor, byte shuffling, and Zstandard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import zipfile
from array import array
from collections import Counter
from compression import zstd
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bomana.core.terrain_elevation import (  # noqa: E402
    TERRAIN_GRID_MAGIC_V2,
    TERRAIN_GRID_PREFIX,
    TERRAIN_GRID_V2_ENCODING,
    TerrainDataError,
    TerrainHeightMap,
    TerrainMapDescriptor,
    default_terrain_pack_dir,
)

DEFAULT_MAX_QUANTIZATION_ERROR_M: Final = 0.5
DEFAULT_QUALITY_P95_LIMIT_M: Final = 3.0
DEFAULT_ZSTD_LEVEL: Final = 15
MIN_QUANTIZATION_BITS: Final = 8
MAX_QUANTIZATION_BITS: Final = 16
MIB: Final = 1024 * 1024


class TerrainPackBuildError(RuntimeError):
    """Raised when a source pack cannot produce a trustworthy offline pack."""


@dataclass(frozen=True)
class QuantizedGrid:
    samples: array[int]
    height_offset_m: float
    height_scale_m: float
    nodata: int | None
    bits: int
    mode: str
    max_error_m: float


@dataclass(frozen=True)
class EncodedGrid:
    data: bytes
    raw_sha256: str
    quantization: QuantizedGrid
    quality_p95_upper_bound_m: float | None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(MIB), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _little_endian_bytes(samples: array[int]) -> bytes:
    canonical = array("H", samples)
    if sys.byteorder != "little":
        canonical.byteswap()
    return canonical.tobytes()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _valid_sample_range(grid: TerrainHeightMap) -> tuple[int, int, int]:
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
        raise TerrainPackBuildError(f"terrain grid has no valid samples: {grid.map_id}")
    return minimum, maximum, count


def _identity_grid(grid: TerrainHeightMap) -> QuantizedGrid:
    return QuantizedGrid(
        samples=array("H", grid.samples),
        height_offset_m=grid.height_offset_m,
        height_scale_m=grid.height_scale_m,
        nodata=grid.nodata,
        bits=16,
        mode="identity",
        max_error_m=0.0,
    )


def quantize_grid(
    grid: TerrainHeightMap,
    *,
    max_error_m: float,
) -> QuantizedGrid:
    """Use the smallest safe integer depth or preserve the source samples exactly."""
    if not math.isfinite(max_error_m) or max_error_m < 0.0:
        raise TerrainPackBuildError("maximum quantization error must be finite and non-negative")
    if max_error_m == 0.0:
        return _identity_grid(grid)

    source_min, source_max, _valid_count = _valid_sample_range(grid)
    height_range_m = (source_max - source_min) * grid.height_scale_m
    if source_min == source_max:
        nodata = None if grid.nodata is None else (1 << MIN_QUANTIZATION_BITS) - 1
        samples = array(
            "H",
            (
                nodata if grid.nodata is not None and value == grid.nodata else 0
                for value in grid.samples
            ),
        )
        return QuantizedGrid(
            samples=samples,
            height_offset_m=grid.height_offset_m + source_min * grid.height_scale_m,
            height_scale_m=grid.height_scale_m,
            nodata=nodata,
            bits=MIN_QUANTIZATION_BITS,
            mode="range",
            max_error_m=0.0,
        )

    selected_bits: int | None = None
    selected_valid_max = 0
    for bits in range(MIN_QUANTIZATION_BITS, MAX_QUANTIZATION_BITS):
        valid_max = (1 << bits) - (1 if grid.nodata is None else 2)
        if height_range_m / (2.0 * valid_max) <= max_error_m:
            selected_bits = bits
            selected_valid_max = valid_max
            break
    if selected_bits is None:
        return _identity_grid(grid)

    target_nodata = None if grid.nodata is None else (1 << selected_bits) - 1
    source_span = source_max - source_min
    lookup = array("H", [0]) * 65536
    actual_max_error_m = 0.0
    for source_value in range(source_min, source_max + 1):
        target_value = round((source_value - source_min) * selected_valid_max / source_span)
        lookup[source_value] = target_value
        source_height = (source_value - source_min) * grid.height_scale_m
        target_height = target_value * height_range_m / selected_valid_max
        actual_max_error_m = max(actual_max_error_m, abs(source_height - target_height))
    if grid.nodata is not None and target_nodata is not None:
        lookup[grid.nodata] = target_nodata
    if actual_max_error_m > max_error_m + 1e-9:
        raise TerrainPackBuildError(
            f"quantization error exceeds its budget for {grid.map_id}: "
            f"{actual_max_error_m:.6f} > {max_error_m:.6f}"
        )

    samples = array("H", (lookup[value] for value in grid.samples))
    return QuantizedGrid(
        samples=samples,
        height_offset_m=grid.height_offset_m + source_min * grid.height_scale_m,
        height_scale_m=height_range_m / selected_valid_max,
        nodata=target_nodata,
        bits=selected_bits,
        mode="range",
        max_error_m=actual_max_error_m,
    )


def _gradient_residuals(samples: array[int], width: int, height: int) -> bytes:
    if len(samples) != width * height:
        raise TerrainPackBuildError("terrain predictor dimensions do not match")
    residuals = array("H", [0]) * len(samples)
    for index, value in enumerate(samples):
        column = index % width
        if index < width:
            predictor = 0 if column == 0 else samples[index - 1]
        elif column == 0:
            predictor = samples[index - width]
        else:
            predictor = (
                samples[index - 1] + samples[index - width] - samples[index - width - 1]
            ) & 0xFFFF
        modular_delta = (value - predictor) & 0xFFFF
        signed_delta = modular_delta if modular_delta < 0x8000 else modular_delta - 0x10000
        residuals[index] = ((signed_delta << 1) ^ (signed_delta >> 15)) & 0xFFFF
    raw = _little_endian_bytes(residuals)
    return raw[0::2] + raw[1::2]


def _finite_p95(raw_descriptor: dict[str, Any]) -> float | None:
    validation = raw_descriptor.get("validation")
    if not isinstance(validation, dict):
        return None
    value = validation.get("p95_abs_error_m")
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def encode_bth2_grid(
    grid: TerrainHeightMap,
    descriptor: TerrainMapDescriptor,
    raw_descriptor: dict[str, Any],
    *,
    max_quantization_error_m: float,
    quality_p95_limit_m: float,
    zstd_level: int,
) -> EncodedGrid:
    source_p95_m = _finite_p95(raw_descriptor)
    error_budget_m = max_quantization_error_m
    if source_p95_m is not None:
        error_budget_m = min(error_budget_m, max(0.0, quality_p95_limit_m - source_p95_m))
    quantized = quantize_grid(grid, max_error_m=error_budget_m)
    raw = _little_endian_bytes(quantized.samples)
    raw_sha256 = _sha256_bytes(raw)
    predicted = _gradient_residuals(quantized.samples, grid.width, grid.height)
    payload = zstd.compress(predicted, level=zstd_level)
    quality_upper = source_p95_m + quantized.max_error_m if source_p95_m is not None else None
    header: dict[str, Any] = {
        "schema_version": 2,
        "encoding": TERRAIN_GRID_V2_ENCODING,
        "map_id": grid.map_id,
        "width": grid.width,
        "height": grid.height,
        "world_bounds": list(grid.world_bounds),
        "map_bounds": list(descriptor.map_bounds),
        "spacing_m": [grid.spacing_x_m, grid.spacing_z_m],
        "interpolation": grid.interpolation,
        "height_offset_m": quantized.height_offset_m,
        "height_scale_m": quantized.height_scale_m,
        "altitude_datum_m": grid.altitude_datum_m,
        "altitude_datum_kind": grid.altitude_datum_kind,
        "nodata": quantized.nodata,
        "valid_samples": sum(
            1
            for value in quantized.samples
            if quantized.nodata is None or value != quantized.nodata
        ),
        "source_sha256": raw_descriptor.get("source_sha256", ""),
        "source_terrain_sha256": descriptor.terrain_sha256,
        "raw_sha256": raw_sha256,
        "quantization_bits": quantized.bits,
        "quantization_mode": quantized.mode,
        "quantization_max_error_m": quantized.max_error_m,
        "source_validation_p95_m": source_p95_m,
        "quality_p95_upper_bound_m": quality_upper,
    }
    for key in (
        "altitude_datum_source_file",
        "altitude_datum_source_sha256",
        "validation",
    ):
        if key in raw_descriptor:
            header[key] = raw_descriptor[key]
    header_bytes = json.dumps(
        header,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    data = (
        TERRAIN_GRID_PREFIX.pack(TERRAIN_GRID_MAGIC_V2, len(header_bytes)) + header_bytes + payload
    )
    return EncodedGrid(
        data=data,
        raw_sha256=raw_sha256,
        quantization=quantized,
        quality_p95_upper_bound_m=quality_upper,
    )


def _load_source_index(input_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    index_path = input_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerrainPackBuildError(f"source terrain index is invalid: {exc}") from exc
    if not isinstance(index, dict) or index.get("schema_version") != 1:
        raise TerrainPackBuildError("source terrain index schema is unsupported")
    maps = index.get("maps")
    failures = index.get("failures", [])
    if not isinstance(maps, list) or not maps:
        raise TerrainPackBuildError("source terrain index has no maps")
    if not isinstance(failures, list) or failures:
        raise TerrainPackBuildError("source terrain pack is incomplete")
    if not all(isinstance(item, dict) for item in maps):
        raise TerrainPackBuildError("source terrain map descriptors are invalid")
    return index, maps


def _prepare_output_dir(output_dir: Path, input_dir: Path) -> None:
    if output_dir.resolve() == input_dir.resolve():
        raise TerrainPackBuildError("output directory must differ from the source pack")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise TerrainPackBuildError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def build_offline_pack(
    input_dir: Path,
    output_dir: Path,
    *,
    max_quantization_error_m: float = DEFAULT_MAX_QUANTIZATION_ERROR_M,
    quality_p95_limit_m: float = DEFAULT_QUALITY_P95_LIMIT_M,
    zstd_level: int = DEFAULT_ZSTD_LEVEL,
) -> dict[str, Any]:
    if not math.isfinite(max_quantization_error_m) or max_quantization_error_m < 0.0:
        raise TerrainPackBuildError("maximum quantization error must be non-negative")
    if not math.isfinite(quality_p95_limit_m) or quality_p95_limit_m <= 0.0:
        raise TerrainPackBuildError("quality P95 limit must be positive")
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    source_index, source_maps = _load_source_index(input_dir)
    _prepare_output_dir(output_dir, input_dir)

    source_index_sha256 = _sha256_file(input_dir / "index.json")
    converted_maps: list[dict[str, Any]] = []
    bit_depths: Counter[int] = Counter()
    total_source_bytes = 0
    total_output_bytes = 0
    max_observed_error_m = 0.0
    max_quality_upper_m = 0.0

    for position, raw_descriptor in enumerate(source_maps, 1):
        descriptor = TerrainMapDescriptor.from_json(raw_descriptor)
        source_path = input_dir / descriptor.file
        grid = TerrainHeightMap.load(source_path, descriptor)
        encoded = encode_bth2_grid(
            grid,
            descriptor,
            raw_descriptor,
            max_quantization_error_m=max_quantization_error_m,
            quality_p95_limit_m=quality_p95_limit_m,
            zstd_level=zstd_level,
        )
        output_path = output_dir / descriptor.file
        _write_atomic(output_path, encoded.data)

        converted = dict(raw_descriptor)
        converted["terrain_sha256"] = encoded.raw_sha256
        converted["source_terrain_sha256"] = descriptor.terrain_sha256
        converted["storage_format"] = "BTH2"
        converted["quantization_bits"] = encoded.quantization.bits
        converted["quantization_mode"] = encoded.quantization.mode
        converted["quantization_max_error_m"] = encoded.quantization.max_error_m
        converted["quality_p95_upper_bound_m"] = encoded.quality_p95_upper_bound_m
        converted["quality_target_met"] = (
            encoded.quality_p95_upper_bound_m is None
            or encoded.quality_p95_upper_bound_m <= quality_p95_limit_m + 1e-9
        )
        converted_descriptor = TerrainMapDescriptor.from_json(converted)
        TerrainHeightMap.load(output_path, converted_descriptor)
        converted_maps.append(converted)

        source_size = source_path.stat().st_size
        output_size = output_path.stat().st_size
        total_source_bytes += source_size
        total_output_bytes += output_size
        bit_depths[encoded.quantization.bits] += 1
        max_observed_error_m = max(
            max_observed_error_m,
            encoded.quantization.max_error_m,
        )
        if encoded.quality_p95_upper_bound_m is not None:
            max_quality_upper_m = max(max_quality_upper_m, encoded.quality_p95_upper_bound_m)
        print(
            f"[{position:02d}/{len(source_maps):02d}] {descriptor.map_id}: "
            f"{source_size / MIB:.2f} -> {output_size / MIB:.2f} MiB, "
            f"{encoded.quantization.bits}-bit, "
            f"max error {encoded.quantization.max_error_m:.3f} m",
            file=sys.stderr,
            flush=True,
        )

    output_index = dict(source_index)
    output_index["generated_at"] = datetime.now(UTC).isoformat()
    output_index["storage"] = {
        "format": "BTH2",
        "encoding": TERRAIN_GRID_V2_ENCODING,
        "compression": "zstd",
        "zstd_level": zstd_level,
        "max_quantization_error_m": max_quantization_error_m,
        "quality_p95_limit_m": quality_p95_limit_m,
        "source_index_sha256": source_index_sha256,
    }
    output_index["maps"] = converted_maps
    index_bytes = json.dumps(output_index, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    _write_atomic(output_dir / "index.json", index_bytes)

    manifest_files = []
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if path.is_file():
            manifest_files.append(
                {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "bomana-terrain-offline-pack",
        "generated_at": output_index["generated_at"],
        "maps": len(converted_maps),
        "source_grid_bytes": total_source_bytes,
        "output_grid_bytes": total_output_bytes,
        "compression_ratio": total_output_bytes / total_source_bytes,
        "quantization_bit_depths": {str(bits): count for bits, count in sorted(bit_depths.items())},
        "max_quantization_error_m": max_observed_error_m,
        "max_quality_p95_upper_bound_m": max_quality_upper_m,
        "files": manifest_files,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    _write_atomic(output_dir / "manifest.json", manifest_bytes)
    install_text = (
        "Bomana offline terrain pack (BTH2)\n\n"
        "Requires a Bomana build with BTH2 terrain support.\n"
        "Close Bomana, back up any existing %USERPROFILE%\\.bomana\\terrain-v1,\n"
        "then extract this terrain-v1 directory under %USERPROFILE%\\.bomana.\n"
        "Restart Bomana and verify that target_altitude_source reports terrain.\n"
    )
    _write_atomic(output_dir / "INSTALL.txt", install_text.encode("utf-8"))
    return manifest


def verify_offline_pack(output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    index, maps = _load_source_index(output_dir)
    storage = index.get("storage")
    if not isinstance(storage, dict) or storage.get("format") != "BTH2":
        raise TerrainPackBuildError("offline terrain pack has no BTH2 storage metadata")
    failures: list[dict[str, str]] = []
    total_bytes = 0
    bit_depths: Counter[int] = Counter()
    max_error_m = 0.0
    max_quality_upper_m = 0.0
    for raw_descriptor in maps:
        map_id = str(raw_descriptor.get("id", ""))
        try:
            descriptor = TerrainMapDescriptor.from_json(raw_descriptor)
            path = output_dir / descriptor.file
            TerrainHeightMap.load(path, descriptor)
            total_bytes += path.stat().st_size
            bits = int(raw_descriptor["quantization_bits"])
            bit_depths[bits] += 1
            error_m = float(raw_descriptor["quantization_max_error_m"])
            max_error_m = max(max_error_m, error_m)
            quality_upper = raw_descriptor.get("quality_p95_upper_bound_m")
            if isinstance(quality_upper, (int, float)):
                max_quality_upper_m = max(max_quality_upper_m, float(quality_upper))
            if raw_descriptor.get("quality_target_met") is not True:
                raise TerrainPackBuildError("quality target is not met")
        except (
            KeyError,
            OSError,
            TerrainDataError,
            TerrainPackBuildError,
            TypeError,
            ValueError,
        ) as exc:
            failures.append({"id": map_id, "error": str(exc)})
    return {
        "valid": not failures and len(maps) > 0,
        "maps": len(maps),
        "total_grid_bytes": total_bytes,
        "quantization_bit_depths": {str(bits): count for bits, count in sorted(bit_depths.items())},
        "max_quantization_error_m": max_error_m,
        "max_quality_p95_upper_bound_m": max_quality_upper_m,
        "failures": failures,
    }


def build_archive(pack_dir: Path, archive_path: Path) -> dict[str, Any]:
    pack_dir = pack_dir.resolve()
    archive_path = archive_path.resolve()
    if archive_path.exists():
        raise TerrainPackBuildError(f"archive already exists: {archive_path}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(pack_dir.iterdir(), key=lambda item: item.name):
            if path.is_file():
                archive.write(path, arcname=f"{pack_dir.name}/{path.name}")
    digest = _sha256_file(archive_path)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    _write_atomic(checksum_path, f"{digest}  {archive_path.name}\n".encode("ascii"))
    return {
        "path": str(archive_path),
        "bytes": archive_path.stat().st_size,
        "sha256": digest,
        "checksum_path": str(checksum_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=default_terrain_pack_dir())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument(
        "--max-quantization-error",
        type=float,
        default=DEFAULT_MAX_QUANTIZATION_ERROR_M,
    )
    parser.add_argument(
        "--quality-p95-limit",
        type=float,
        default=DEFAULT_QUALITY_P95_LIMIT_M,
    )
    parser.add_argument("--zstd-level", type=int, default=DEFAULT_ZSTD_LEVEL)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.verify_only:
            result = verify_offline_pack(args.output)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["valid"] else 2
        manifest = build_offline_pack(
            args.input,
            args.output,
            max_quantization_error_m=args.max_quantization_error,
            quality_p95_limit_m=args.quality_p95_limit,
            zstd_level=args.zstd_level,
        )
        verification = verify_offline_pack(args.output)
        result: dict[str, Any] = {
            "output": str(args.output.resolve()),
            "manifest": manifest,
            "verification": verification,
        }
        if args.archive is not None:
            result["archive"] = build_archive(args.output, args.archive)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if verification["valid"] else 2
    except (OSError, TerrainDataError, TerrainPackBuildError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
