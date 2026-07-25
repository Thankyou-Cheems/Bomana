#!/usr/bin/env python3
"""Extract terrain-only elevation samples from War Thunder level binaries.

The client ``levels/*.bin`` files are Dagor ``DBLD3x64`` containers.  This tool
prefers their native ``HM2`` physics heightmap and otherwise reads the version-4
``lmap/lndm`` compressed ``LTdump`` ray-tracing mesh.  Scene objects (``SCN``),
generated instances/vegetation (``RIGz``), and splines are deliberately outside
the extraction path.

Oodle-compressed assets require an external compatible decompressor.  The
``--ooz`` option accepts the command-line tool from https://github.com/powzix/ooz;
``--oodle-dll`` accepts a separately licensed local Oodle runtime.  No
third-party decoder code or binary is bundled with Bomana.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import random
import statistics
import struct
import subprocess
import sys
import tempfile
import zlib
from array import array
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bomana.core.terrain_elevation import (  # noqa: E402
    DEFAULT_MIN_FINGERPRINT_MARGIN,
    TERRAIN_GRID_MAGIC,
    TERRAIN_GRID_MAGIC_V2,
    TERRAIN_GRID_PREFIX,
    TERRAIN_NODATA,
    TerrainDataError,
    TerrainHeightMap,
    TerrainMapDescriptor,
    default_terrain_pack_dir,
    fingerprint_distance,
    pil_image_dhash,
)

DBLD_MAGIC: Final = b"DBLD3x64"
LAND_MAGIC: Final = b"lndm"
LAND_VERSION: Final = 4
LAND_RAY_MAGIC: Final = b"LTdump"
ALTITUDE_DATUM_FORMULA: Final = (
    "explicit_water:max(terrain_world_y,water_level)-water_level;default_zero:terrain_world_y"
)

BLOCK_LENGTH_MASK: Final = 0x3FFFFFFF
BLOCK_FLAG_SHIFT: Final = 30
BLOCK_COMPRESSION_NONE: Final = 0
BLOCK_COMPRESSION_ZSTD: Final = 1
BLOCK_COMPRESSION_OODLE: Final = 2

GRID_SIZE_BITS: Final = 10
GRID_SIZE_MASK: Final = (1 << GRID_SIZE_BITS) - 1
LAND_RAY_CELL = struct.Struct("<4f4ff7I")
HMAP_TAG: Final = b"\0HM2"
HMAP_WIDTH_BITS: Final = 24
HMAP_WIDTH_MASK: Final = (1 << HMAP_WIDTH_BITS) - 1
HMAP_CBLOCK_DELTAC_VERSION: Final = 2
HMAP_HIERARCHY_OFFSETS: Final = (
    0,
    1,
    5,
    21,
    85,
    341,
    1365,
    5461,
    21845,
    87381,
    349525,
    1398101,
    5592405,
    22369621,
    89478485,
)
DXP_MAGIC: Final = b"DxP2"
DXP_DDSX_MAGIC: Final = b"DDSx"
DXP_HEADER_SIZE: Final = 16
DXP_DUMP_TABLE_SIZE: Final = 16
DXP_DUMP_STRING_OFFSET: Final = 0x38
DXP_DDSX_HEADER_SIZE: Final = 32
DXP_RECORD_SIZE: Final = 24
TERRAIN_PACK_SCHEMA_VERSION: Final = 1


class TerrainExtractionError(RuntimeError):
    """Raised when a client terrain asset violates the supported contract."""


@dataclass(frozen=True)
class TaggedBlock:
    tag: bytes
    data_offset: int
    data_size: int
    flags: int


@dataclass(frozen=True)
class LandMeshHeader:
    grid_cell_size: float
    land_cell_size: float
    map_size_x: int
    map_size_y: int
    origin_x: int
    origin_y: int
    use_tile: bool
    ray_block_offset: int


@dataclass(frozen=True)
class HeightMapHeader:
    cell_size: float
    height_min_m: float
    height_range_m: float
    offset_x: float
    offset_z: float
    width: int
    height: int
    mirror: bool
    block_shift: int
    hierarchy_subsize: int
    chunk_size: int
    data_offset: int
    data_end: int


@dataclass(frozen=True)
class ArraySlice:
    offset: int
    count: int
    item_size: int

    @property
    def byte_size(self) -> int:
        return self.count * self.item_size


@dataclass(frozen=True)
class DxpTextureEntry:
    name: str
    format: str
    flags: int
    width: int
    height: int
    levels: int
    decoded_size: int
    packed_size: int
    data_offset: int


@dataclass(frozen=True)
class TerrainGridBuild:
    width: int
    height: int
    world_bounds: tuple[float, float, float, float]
    spacing_x_m: float
    spacing_z_m: float
    height_offset_m: float
    height_scale_m: float
    samples: array
    valid_samples: int
    interpolation: str = "bilinear"
    nodata: int | None = TERRAIN_NODATA

    def height_at(self, world_x: float, world_z: float) -> float | None:
        min_x, min_z, max_x, max_z = self.world_bounds
        if not (min_x <= world_x <= max_x and min_z <= world_z <= max_z):
            return None
        if self.interpolation == "diamond":
            grid_x = (world_x - min_x) / self.spacing_x_m
            grid_z = (world_z - min_z) / self.spacing_z_m
            x0 = math.floor(grid_x)
            z0 = math.floor(grid_z)
            if not (0 <= x0 < self.width and 0 <= z0 < self.height):
                return None
            x1 = min(x0 + 1, self.width - 1)
            z1 = min(z0 + 1, self.height - 1)
            decoded = tuple(
                self._decoded(index)
                for index in (
                    z0 * self.width + x0,
                    z0 * self.width + x1,
                    z1 * self.width + x0,
                    z1 * self.width + x1,
                )
            )
            if any(value is None for value in decoded):
                return None
            h0, hx, hz, hxz = (float(value) for value in decoded)
            return self._diamond_height(
                grid_x - x0 - 0.5,
                grid_z - z0 - 0.5,
                h0,
                hx,
                hz,
                hxz,
            )
        grid_x = (world_x - min_x) * (self.width - 1) / (max_x - min_x)
        grid_z = (world_z - min_z) * (self.height - 1) / (max_z - min_z)
        x0 = min(math.floor(grid_x), self.width - 2)
        z0 = min(math.floor(grid_z), self.height - 2)
        fx = min(max(grid_x - x0, 0.0), 1.0)
        fz = min(max(grid_z - z0, 0.0), 1.0)
        indices = (
            z0 * self.width + x0,
            z0 * self.width + x0 + 1,
            (z0 + 1) * self.width + x0,
            (z0 + 1) * self.width + x0 + 1,
        )
        weights = ((1.0 - fx) * (1.0 - fz), fx * (1.0 - fz), (1.0 - fx) * fz, fx * fz)
        weighted_height = 0.0
        valid_weight = 0.0
        for index, weight in zip(indices, weights, strict=True):
            height = self._decoded(index)
            if height is not None:
                weighted_height += height * weight
                valid_weight += weight
        return weighted_height / valid_weight if valid_weight > 1e-9 else None

    def _decoded(self, index: int) -> float | None:
        sample = self.samples[index]
        if self.nodata is not None and sample == self.nodata:
            return None
        return self.height_offset_m + sample * self.height_scale_m

    @staticmethod
    def _diamond_height(
        x: float,
        z: float,
        h0: float,
        hx: float,
        hz: float,
        hxz: float,
    ) -> float:
        midpoint = (h0 + hx + hz + hxz) * 0.25
        if x >= z:
            if x + z >= 0.0:
                return midpoint + (x - z) * (hx - midpoint) + (x + z) * (hxz - midpoint)
            return midpoint + (x - z) * (hx - midpoint) - (x + z) * (h0 - midpoint)
        if x + z >= 0.0:
            return midpoint + (z - x) * (hz - midpoint) + (x + z) * (hxz - midpoint)
        return midpoint + (z - x) * (hz - midpoint) - (x + z) * (h0 - midpoint)


@dataclass(frozen=True)
class AltitudeDatum:
    value_m: float
    kind: str
    source_file: str
    source_sha256: str
    map_bounds: tuple[float, float, float, float]


def _checked_slice(data: bytes, offset: int, size: int, label: str) -> memoryview:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise TerrainExtractionError(
            f"{label} is outside the file: offset={offset}, size={size}, file={len(data)}"
        )
    return memoryview(data)[offset : offset + size]


def _u32(data: bytes | memoryview, offset: int, label: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise TerrainExtractionError(f"missing uint32 for {label} at {offset}")
    return struct.unpack_from("<I", data, offset)[0]


def _i32(data: bytes | memoryview, offset: int, label: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise TerrainExtractionError(f"missing int32 for {label} at {offset}")
    return struct.unpack_from("<i", data, offset)[0]


def iter_dbld_blocks(data: bytes) -> tuple[TaggedBlock, ...]:
    """Return validated top-level Dagor tagged blocks."""
    if not data.startswith(DBLD_MAGIC):
        raise TerrainExtractionError("not a DBLD3x64 level binary")
    if len(data) < 12:
        raise TerrainExtractionError("truncated DBLD header")

    blocks: list[TaggedBlock] = []
    offset = 12
    while offset + 8 <= len(data):
        raw_length = _u32(data, offset, "tagged block length")
        length = raw_length & BLOCK_LENGTH_MASK
        flags = raw_length >> BLOCK_FLAG_SHIFT
        if length < 4:
            raise TerrainExtractionError(f"invalid tagged block length {length} at {offset}")
        end = offset + 4 + length
        if end > len(data):
            raise TerrainExtractionError(f"tagged block at {offset} overruns the file")
        tag = bytes(data[offset + 4 : offset + 8])
        blocks.append(
            TaggedBlock(
                tag=tag,
                data_offset=offset + 8,
                data_size=length - 4,
                flags=flags,
            )
        )
        offset = end
        if tag.rstrip(b"\0") == b"END":
            break
    return tuple(blocks)


def find_land_mesh(data: bytes) -> tuple[TaggedBlock, LandMeshHeader]:
    block = next(
        (candidate for candidate in iter_dbld_blocks(data) if candidate.tag == b"lmap"), None
    )
    if block is None:
        raise TerrainExtractionError("level has no lmap terrain block")
    if block.flags != BLOCK_COMPRESSION_NONE:
        raise TerrainExtractionError(f"compressed top-level lmap is unsupported: {block.flags}")
    _checked_slice(data, block.data_offset, block.data_size, "lmap")

    offset = block.data_offset
    if bytes(data[offset : offset + 4]) != LAND_MAGIC:
        raise TerrainExtractionError("lmap does not contain an lndm land mesh")
    version = _i32(data, offset + 4, "land mesh version")
    if version != LAND_VERSION:
        raise TerrainExtractionError(f"unsupported land mesh version {version}")

    (
        grid_cell_size,
        land_cell_size,
        map_size_x,
        map_size_y,
        origin_x,
        origin_y,
        use_tile,
    ) = struct.unpack_from("<ffiiiii", data, offset + 8)
    base_data_offset = offset + 36
    _mesh_map_rel, _detail_rel, _tile_rel, ray_rel = struct.unpack_from(
        "<iiii", data, base_data_offset
    )
    ray_block_offset = base_data_offset + ray_rel - 4
    if ray_rel <= 0 or not (
        block.data_offset <= ray_block_offset < block.data_offset + block.data_size
    ):
        raise TerrainExtractionError("lmap has no in-range land-ray block")

    return block, LandMeshHeader(
        grid_cell_size=float(grid_cell_size),
        land_cell_size=float(land_cell_size),
        map_size_x=int(map_size_x),
        map_size_y=int(map_size_y),
        origin_x=int(origin_x),
        origin_y=int(origin_y),
        use_tile=bool(use_tile),
        ray_block_offset=ray_block_offset,
    )


def find_heightmap(data: bytes) -> tuple[TaggedBlock, HeightMapHeader]:
    """Locate and validate a version-2 Dagor compressed heightmap block."""
    block = next(
        (candidate for candidate in iter_dbld_blocks(data) if candidate.tag == HMAP_TAG),
        None,
    )
    if block is None:
        raise TerrainExtractionError("level has no HM2 heightmap block")
    if block.flags != BLOCK_COMPRESSION_NONE:
        raise TerrainExtractionError(f"compressed top-level HM2 is unsupported: {block.flags}")
    header_size = struct.calcsize("<5fII4iI")
    _checked_slice(data, block.data_offset, header_size, "HM2 header")
    (
        cell_size,
        height_min_m,
        height_range_m,
        offset_x,
        offset_z,
        width_version,
        height_mirrored,
        _exclude_min_x,
        _exclude_min_z,
        _exclude_max_x,
        _exclude_max_z,
        chunk_descriptor,
    ) = struct.unpack_from("<5fII4iI", data, block.data_offset)
    version = width_version >> HMAP_WIDTH_BITS
    width = width_version & HMAP_WIDTH_MASK
    height = height_mirrored & 0x7FFFFFFF
    mirror = bool(height_mirrored >> 31)
    if version != HMAP_CBLOCK_DELTAC_VERSION:
        raise TerrainExtractionError(f"unsupported HM2 version {version}")
    if not math.isfinite(cell_size) or cell_size <= 0.0:
        raise TerrainExtractionError("HM2 cell size is invalid")
    if not all(
        math.isfinite(value) for value in (height_min_m, height_range_m, offset_x, offset_z)
    ):
        raise TerrainExtractionError("HM2 world metadata is invalid")
    if height_range_m <= 0.0 or width < 2 or height < 2:
        raise TerrainExtractionError("HM2 dimensions or height range are invalid")

    block_shift = chunk_descriptor & 0xFF
    hierarchy_bits = (chunk_descriptor >> 8) & 0xF
    hierarchy_subsize = 1 << hierarchy_bits if hierarchy_bits else 0
    chunk_size = chunk_descriptor & ~0xFFF
    if not 1 <= block_shift <= 7:
        raise TerrainExtractionError(f"HM2 block shift is invalid: {block_shift}")
    block_width = 1 << block_shift
    if width % block_width or height % block_width:
        raise TerrainExtractionError(f"HM2 dimensions {width}x{height} are not block-aligned")
    if hierarchy_subsize:
        hierarchy_ratio = width // hierarchy_subsize
        if (
            width != height
            or hierarchy_ratio < 2
            or hierarchy_ratio * hierarchy_subsize != width
            or hierarchy_ratio & (hierarchy_ratio - 1)
        ):
            raise TerrainExtractionError("HM2 hierarchy dimensions are invalid")
        hierarchy_levels = hierarchy_ratio.bit_length() - 1
        if hierarchy_levels >= len(HMAP_HIERARCHY_OFFSETS):
            raise TerrainExtractionError("HM2 hierarchy has too many levels")
    if chunk_size and chunk_size < 1 << (2 * block_shift):
        raise TerrainExtractionError("HM2 variance chunk is smaller than one block")

    return block, HeightMapHeader(
        cell_size=float(cell_size),
        height_min_m=float(height_min_m),
        height_range_m=float(height_range_m),
        offset_x=float(offset_x),
        offset_z=float(offset_z),
        width=int(width),
        height=int(height),
        mirror=mirror,
        block_shift=int(block_shift),
        hierarchy_subsize=int(hierarchy_subsize),
        chunk_size=int(chunk_size),
        data_offset=block.data_offset + header_size,
        data_end=block.data_offset + block.data_size,
    )


def _resolve_ooz(explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    env_path = os.environ.get("BOMANA_OOZ_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if directory:
            candidates.append(Path(directory) / "ooz.exe")
            candidates.append(Path(directory) / "ooz")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise TerrainExtractionError("Oodle terrain block requires --ooz PATH or BOMANA_OOZ_PATH")


def _ooz_decompress(payload: bytes, decoded_size: int, decoder: Path) -> bytes:
    if decoded_size <= 0:
        raise TerrainExtractionError("Oodle stream has an invalid decoded size")
    with tempfile.TemporaryDirectory(prefix="bomana-terrain-") as temp_dir:
        input_path = Path(temp_dir) / "input.oodle"
        output_path = Path(temp_dir) / "output.bin"
        input_path.write_bytes(struct.pack("<Q", decoded_size) + payload)
        result = subprocess.run(
            [str(decoder), "-f", str(input_path), str(output_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if result.returncode != 0 or not output_path.is_file():
            detail = (result.stderr or result.stdout or "unknown decoder failure").strip()
            raise TerrainExtractionError(f"Oodle decompression failed: {detail}")
        decoded = output_path.read_bytes()
    if len(decoded) != decoded_size:
        raise TerrainExtractionError(
            f"Oodle decoded size mismatch: expected {decoded_size}, got {len(decoded)}"
        )
    return decoded


def _resolve_oodle_dll(explicit: Path | None) -> Path | None:
    candidate = explicit
    if candidate is None:
        env_path = os.environ.get("BOMANA_OODLE_DLL_PATH", "").strip()
        candidate = Path(env_path) if env_path else None
    if candidate is None:
        return None
    if not candidate.is_file():
        raise TerrainExtractionError(f"Oodle DLL does not exist: {candidate}")
    return candidate.resolve()


def _oodle_dll_decompress(payload: bytes, decoded_size: int, dll_path: Path) -> bytes:
    if os.name != "nt":
        raise TerrainExtractionError("Oodle DLL decompression is available only on Windows")
    if decoded_size <= 0:
        raise TerrainExtractionError("Oodle stream has an invalid decoded size")
    try:
        library = ctypes.CDLL(str(dll_path))
        decompress = library.OodleLZ_Decompress
    except (OSError, AttributeError) as exc:
        raise TerrainExtractionError(f"cannot load OodleLZ_Decompress: {exc}") from exc
    decompress.argtypes = (
        ctypes.c_void_p,
        ctypes.c_ssize_t,
        ctypes.c_void_p,
        ctypes.c_ssize_t,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ssize_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ssize_t,
        ctypes.c_int,
    )
    decompress.restype = ctypes.c_ssize_t
    source = ctypes.create_string_buffer(payload)
    destination = ctypes.create_string_buffer(decoded_size)
    result = decompress(
        source,
        len(payload),
        destination,
        decoded_size,
        1,
        0,
        0,
        None,
        0,
        None,
        None,
        None,
        0,
        3,
    )
    if result != decoded_size:
        raise TerrainExtractionError(
            f"Oodle DLL decoded size mismatch: expected {decoded_size}, got {result}"
        )
    return destination.raw[:decoded_size]


def _decompress_dagor_block(
    data: bytes,
    offset: int,
    data_end: int,
    decoded_size: int,
    *,
    label: str,
    ooz_path: Path | None,
    oodle_dll_path: Path | None,
) -> tuple[bytes, int]:
    if offset + 4 > data_end:
        raise TerrainExtractionError(f"{label} has no block header")
    raw_length = _u32(data, offset, f"{label} length")
    packed_size = raw_length & BLOCK_LENGTH_MASK
    flags = raw_length >> BLOCK_FLAG_SHIFT
    payload_offset = offset + 4
    if payload_offset + packed_size > data_end:
        raise TerrainExtractionError(f"{label} overruns the HM2 block")
    payload = bytes(_checked_slice(data, payload_offset, packed_size, f"{label} payload"))
    if flags == BLOCK_COMPRESSION_NONE:
        decoded = payload
    elif flags == BLOCK_COMPRESSION_OODLE:
        dll_path = _resolve_oodle_dll(oodle_dll_path)
        if dll_path is not None:
            decoded = _oodle_dll_decompress(payload, decoded_size, dll_path)
        else:
            decoded = _ooz_decompress(payload, decoded_size, _resolve_ooz(ooz_path))
    elif flags == BLOCK_COMPRESSION_ZSTD:
        raise TerrainExtractionError(f"{label} uses unsupported Zstandard compression")
    else:
        raise TerrainExtractionError(f"{label} has unknown compression flag {flags}")
    if len(decoded) != decoded_size:
        raise TerrainExtractionError(
            f"{label} decoded size mismatch: expected {decoded_size}, got {len(decoded)}"
        )
    return decoded, payload_offset + packed_size


def decompress_heightmap(
    level_data: bytes,
    header: HeightMapHeader,
    *,
    ooz_path: Path | None = None,
    oodle_dll_path: Path | None = None,
) -> tuple[bytes, bytes]:
    """Decode HM2 block metadata and delta-coded per-pixel variance bytes."""
    block_width = 1 << header.block_shift
    block_size_shift = header.block_shift * 2
    block_size = 1 << block_size_shift
    blocks_wide = header.width // block_width
    blocks_high = header.height // block_width
    block_count = blocks_wide * blocks_high
    block_info_size = block_count * 4

    hierarchy_size = 0
    if header.hierarchy_subsize:
        hierarchy_ratio = header.width // header.hierarchy_subsize
        hierarchy_levels = hierarchy_ratio.bit_length() - 1
        hierarchy_size = HMAP_HIERARCHY_OFFSETS[hierarchy_levels] * 16

    cursor = header.data_offset
    variance = bytearray(header.width * header.height)
    if header.chunk_size:
        blocks_per_chunk = header.chunk_size >> block_size_shift
        chunk_count = math.ceil(block_count / blocks_per_chunk)
        metadata, cursor = _decompress_dagor_block(
            level_data,
            cursor,
            header.data_end,
            block_info_size + hierarchy_size,
            label="HM2 metadata chunk",
            ooz_path=ooz_path,
            oodle_dll_path=oodle_dll_path,
        )
        block_infos = metadata[:block_info_size]
        for chunk_index in range(1, chunk_count + 1):
            first_block = (chunk_index - 1) * blocks_per_chunk
            last_block = min(block_count, chunk_index * blocks_per_chunk)
            decoded_size = (last_block - first_block) * block_size
            decoded, cursor = _decompress_dagor_block(
                level_data,
                cursor,
                header.data_end,
                decoded_size,
                label=f"HM2 variance chunk {chunk_index}/{chunk_count}",
                ooz_path=ooz_path,
                oodle_dll_path=oodle_dll_path,
            )
            start = first_block * block_size
            variance[start : start + decoded_size] = decoded
    else:
        decoded, cursor = _decompress_dagor_block(
            level_data,
            cursor,
            header.data_end,
            block_info_size + len(variance) + hierarchy_size,
            label="HM2 data chunk",
            ooz_path=ooz_path,
            oodle_dll_path=oodle_dll_path,
        )
        block_infos = decoded[:block_info_size]
        variance[:] = decoded[block_info_size : block_info_size + len(variance)]

    trailing = level_data[cursor : header.data_end]
    if len(trailing) > 15 or any(trailing):
        raise TerrainExtractionError(f"HM2 has {len(trailing)} unexplained trailing bytes")

    for block_offset in range(0, len(variance), block_size):
        last = variance[block_offset]
        for index in range(block_offset + 1, block_offset + block_size):
            last = (last + variance[index]) & 0xFF
            variance[index] = last
    return block_infos, bytes(variance)


class HeightMapTracer:
    """Read-only view of a decoded native Dagor compressed heightmap."""

    def __init__(
        self,
        header: HeightMapHeader,
        block_infos: bytes,
        variance: bytes,
    ) -> None:
        self.header = header
        self.num_cells_x = header.width
        self.num_cells_y = header.height
        self.cell_size = header.cell_size
        self.offset_x = header.offset_x
        self.offset_z = header.offset_z
        self.height_offset_m = header.height_min_m
        self.height_scale_m = header.height_range_m / 65535.0
        self.block_width = 1 << header.block_shift
        self.block_mask = self.block_width - 1
        self.block_size_shift = header.block_shift * 2
        self.block_size = 1 << self.block_size_shift
        self.blocks_wide = header.width // self.block_width
        self.blocks_high = header.height // self.block_width
        block_count = self.blocks_wide * self.blocks_high
        if len(block_infos) != block_count * 4:
            raise TerrainExtractionError("HM2 block-info size does not match its dimensions")
        if len(variance) != header.width * header.height:
            raise TerrainExtractionError("HM2 variance size does not match its dimensions")
        self._block_infos = block_infos
        self._variance = variance

    def sample_raw(self, x: int, z: int) -> int:
        if not (0 <= x < self.num_cells_x and 0 <= z < self.num_cells_y):
            raise TerrainExtractionError(f"HM2 sample ({x}, {z}) is out of range")
        block_x = x >> self.header.block_shift
        block_z = z >> self.header.block_shift
        block_index = block_x + block_z * self.blocks_wide
        minimum, delta = struct.unpack_from("<HH", self._block_infos, block_index * 4)
        if delta == 0:
            return minimum
        within_x = x & self.block_mask
        within_z = z & self.block_mask
        variance_index = (
            (block_index << self.block_size_shift)
            + within_x
            + (within_z << self.header.block_shift)
        )
        return minimum + (self._variance[variance_index] * delta + 127) // 255

    def raw_samples(self, *, progress_label: str = "") -> array:
        samples = array("H", [0]) * (self.num_cells_x * self.num_cells_y)
        progress_every = max(1, self.blocks_high // 16)
        for block_z in range(self.blocks_high):
            for block_x in range(self.blocks_wide):
                block_index = block_x + block_z * self.blocks_wide
                minimum, delta = struct.unpack_from("<HH", self._block_infos, block_index * 4)
                variance_start = block_index << self.block_size_shift
                target_x = block_x * self.block_width
                target_z = block_z * self.block_width
                for within_z in range(self.block_width):
                    target = (target_z + within_z) * self.num_cells_x + target_x
                    source = variance_start + within_z * self.block_width
                    if delta == 0:
                        samples[target : target + self.block_width] = (
                            array("H", [minimum]) * self.block_width
                        )
                    else:
                        for within_x in range(self.block_width):
                            value = self._variance[source + within_x]
                            samples[target + within_x] = minimum + (value * delta + 127) // 255
            if progress_label and (
                block_z + 1 == self.blocks_high or (block_z + 1) % progress_every == 0
            ):
                print(
                    f"[{progress_label}] native HM2 blocks {block_z + 1}/{self.blocks_high}",
                    file=sys.stderr,
                    flush=True,
                )
        return samples

    def height_at(self, x: float, z: float) -> float | None:
        if not math.isfinite(x) or not math.isfinite(z):
            return None
        grid_x = (x - self.offset_x) / self.cell_size
        grid_z = (z - self.offset_z) / self.cell_size
        cell_x = math.floor(grid_x)
        cell_z = math.floor(grid_z)
        if not (0 <= cell_x < self.num_cells_x and 0 <= cell_z < self.num_cells_y):
            return None
        next_x = min(cell_x + 1, self.num_cells_x - 1)
        next_z = min(cell_z + 1, self.num_cells_y - 1)
        heights = tuple(
            self.height_offset_m + raw * self.height_scale_m
            for raw in (
                self.sample_raw(cell_x, cell_z),
                self.sample_raw(next_x, cell_z),
                self.sample_raw(cell_x, next_z),
                self.sample_raw(next_x, next_z),
            )
        )
        return TerrainGridBuild._diamond_height(
            grid_x - cell_x - 0.5,
            grid_z - cell_z - 0.5,
            heights[0],
            heights[1],
            heights[2],
            heights[3],
        )

    def describe(self) -> dict[str, object]:
        return {
            "kind": "heightmap",
            "num_cells": [self.num_cells_x, self.num_cells_y],
            "cell_size_m": self.cell_size,
            "offset": [self.offset_x, self.offset_z],
            "height_min_m": self.height_offset_m,
            "height_range_m": self.header.height_range_m,
            "block_width": self.block_width,
            "chunk_size": self.header.chunk_size,
            "mirror": self.header.mirror,
        }


def decompress_land_ray(
    level_data: bytes,
    header: LandMeshHeader,
    *,
    ooz_path: Path | None = None,
) -> bytes:
    """Decode the lmap ray-tracer stream and return its serialized bytes."""
    raw_length = _u32(level_data, header.ray_block_offset, "land-ray block length")
    block_length = raw_length & BLOCK_LENGTH_MASK
    flags = raw_length >> BLOCK_FLAG_SHIFT
    payload_offset = header.ray_block_offset + 4
    payload = bytes(_checked_slice(level_data, payload_offset, block_length, "land-ray block"))

    if flags == BLOCK_COMPRESSION_NONE:
        decoded = payload
    elif flags == BLOCK_COMPRESSION_OODLE:
        if len(payload) < 5:
            raise TerrainExtractionError("truncated Oodle land-ray block")
        decoded_size = _u32(payload, 0, "Oodle decoded size")
        decoder = _resolve_ooz(ooz_path)
        decoded = _ooz_decompress(payload[4:], decoded_size, decoder)
    elif flags == BLOCK_COMPRESSION_ZSTD:
        raise TerrainExtractionError("Zstandard land-ray blocks are not yet supported")
    else:
        raise TerrainExtractionError(f"unknown land-ray compression flag {flags}")

    if len(decoded) < 10:
        raise TerrainExtractionError("decoded land-ray stream is truncated")
    declared_size = _u32(decoded, 0, "land-ray dump size")
    if declared_size > len(decoded) - 4:
        raise TerrainExtractionError(
            f"land-ray dump declares {declared_size} bytes, only {len(decoded) - 4} remain"
        )
    stream = decoded[4 : 4 + declared_size]
    if not stream.startswith(LAND_RAY_MAGIC):
        raise TerrainExtractionError("decoded land-ray stream has no LTdump signature")
    return stream


class LandRayTracer:
    """Read-only query view over a serialized Dagor LTdump terrain mesh."""

    def __init__(self, stream: bytes) -> None:
        if not stream.startswith(LAND_RAY_MAGIC):
            raise TerrainExtractionError("not an LTdump stream")
        if len(stream) < 58:
            raise TerrainExtractionError("truncated LTdump header")

        self._data = stream
        (
            self.num_cells_x,
            self.num_cells_y,
            self.cell_size,
            self.offset_x,
            self.offset_y,
            self.offset_z,
            self.bbox_min_x,
            self.bbox_min_y,
            self.bbox_min_z,
            self.bbox_max_x,
            self.bbox_max_y,
            self.bbox_max_z,
        ) = struct.unpack_from("<iif3f6f", stream, len(LAND_RAY_MAGIC))
        if self.num_cells_x <= 0 or self.num_cells_y <= 0 or self.cell_size <= 0:
            raise TerrainExtractionError("invalid LTdump grid dimensions")

        offset = len(LAND_RAY_MAGIC) + struct.calcsize("<iif3f6f")
        self.cells, offset = self._read_array(offset, LAND_RAY_CELL.size, "cells")
        self.grid, offset = self._read_array(offset, 4, "grid")
        self.grid_heights, offset = self._read_array(offset, 4, "grid heights")
        self.faces, offset = self._read_array(offset, 2, "faces")
        self.vertices, offset = self._read_array(offset, 8, "vertices")
        self.face_indices, offset = self._read_array(offset, 2, "face indices")
        if self.cells.count != self.num_cells_x * self.num_cells_y:
            raise TerrainExtractionError(
                "LTdump cell count does not match its declared grid dimensions"
            )
        if offset != len(stream):
            raise TerrainExtractionError(
                f"LTdump has {len(stream) - offset} unexplained trailing bytes"
            )

    def _read_array(self, offset: int, item_size: int, label: str) -> tuple[ArraySlice, int]:
        count = _u32(self._data, offset, f"{label} count")
        offset += 4
        byte_size = count * item_size
        _checked_slice(self._data, offset, byte_size, label)
        return ArraySlice(offset=offset, count=count, item_size=item_size), offset + byte_size

    def _array_u16(self, array: ArraySlice, index: int, label: str) -> int:
        if not 0 <= index < array.count:
            raise TerrainExtractionError(f"{label} index {index} is out of range")
        return struct.unpack_from("<H", self._data, array.offset + index * 2)[0]

    def _array_u32(self, array: ArraySlice, index: int, label: str) -> int:
        if not 0 <= index < array.count:
            raise TerrainExtractionError(f"{label} index {index} is out of range")
        return struct.unpack_from("<I", self._data, array.offset + index * 4)[0]

    def _vertex(
        self,
        index: int,
        scale: tuple[float, float, float, float],
        offset: tuple[float, float, float, float],
    ) -> tuple[float, float, float]:
        if not 0 <= index < self.vertices.count:
            raise TerrainExtractionError(f"vertex index {index} is out of range")
        packed = struct.unpack_from("<4H", self._data, self.vertices.offset + index * 8)
        return (
            packed[0] * scale[0] + offset[0],
            packed[1] * scale[1] + offset[1],
            packed[2] * scale[2] + offset[2],
        )

    @staticmethod
    def _triangle_height(
        x: float,
        z: float,
        a: tuple[float, float, float],
        b: tuple[float, float, float],
        c: tuple[float, float, float],
    ) -> float | None:
        denominator = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
        if abs(denominator) <= 1e-12:
            return None
        wa = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / denominator
        wb = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / denominator
        wc = 1.0 - wa - wb
        tolerance = 2e-5
        if wa < -tolerance or wb < -tolerance or wc < -tolerance:
            return None
        return wa * a[1] + wb * b[1] + wc * c[1]

    def height_at(self, x: float, z: float) -> float | None:
        """Return the top terrain triangle height at world X/Z, if covered."""
        if not math.isfinite(x) or not math.isfinite(z):
            return None
        local_x = (x - self.offset_x) / self.cell_size
        local_z = (z - self.offset_z) / self.cell_size
        if not (0.0 <= local_x <= self.num_cells_x and 0.0 <= local_z <= self.num_cells_y):
            return None
        local_x = min(local_x, math.nextafter(float(self.num_cells_x), 0.0))
        local_z = min(local_z, math.nextafter(float(self.num_cells_y), 0.0))
        cell_x = math.floor(local_x)
        cell_z = math.floor(local_z)

        cell_index = cell_x + cell_z * self.num_cells_x
        values = LAND_RAY_CELL.unpack_from(
            self._data, self.cells.offset + cell_index * LAND_RAY_CELL.size
        )
        cell_offset = tuple(float(value) for value in values[0:4])
        cell_scale = tuple(float(value) for value in values[4:8])
        grid_start = int(values[10])
        first_and_grid_size = int(values[11])
        faces_start = int(values[12])
        vertices_start = int(values[13])
        grid_size = first_and_grid_size & GRID_SIZE_MASK
        if grid_size == 0:
            return None

        fraction_x = min(max(local_x - cell_x, 0.0), math.nextafter(1.0, 0.0))
        fraction_z = min(max(local_z - cell_z, 0.0), math.nextafter(1.0, 0.0))
        grid_x = min(int(fraction_x * grid_size), grid_size - 1)
        grid_z = min(int(fraction_z * grid_size), grid_size - 1)
        grid_index = grid_x + grid_z * grid_size
        first_face_index = first_and_grid_size >> GRID_SIZE_BITS
        start = first_face_index + self._array_u32(self.grid, grid_start + grid_index, "grid")
        end = first_face_index + self._array_u32(self.grid, grid_start + grid_index + 1, "grid")
        if end < start or end > self.face_indices.count:
            raise TerrainExtractionError("invalid LTdump face-index range")

        result: float | None = None
        for candidate_index in range(start, end):
            face_index = self._array_u16(self.face_indices, candidate_index, "face indices")
            face_base = faces_start + face_index * 3
            vertex_indices = (
                vertices_start + self._array_u16(self.faces, face_base, "faces"),
                vertices_start + self._array_u16(self.faces, face_base + 1, "faces"),
                vertices_start + self._array_u16(self.faces, face_base + 2, "faces"),
            )
            height = self._triangle_height(
                x,
                z,
                self._vertex(vertex_indices[0], cell_scale, cell_offset),
                self._vertex(vertex_indices[1], cell_scale, cell_offset),
                self._vertex(vertex_indices[2], cell_scale, cell_offset),
            )
            if height is not None and (result is None or height > result):
                result = height
        return result

    def describe(self) -> dict[str, object]:
        return {
            "num_cells": [self.num_cells_x, self.num_cells_y],
            "cell_size_m": self.cell_size,
            "offset": [self.offset_x, self.offset_y, self.offset_z],
            "bbox_min": [self.bbox_min_x, self.bbox_min_y, self.bbox_min_z],
            "bbox_max": [self.bbox_max_x, self.bbox_max_y, self.bbox_max_z],
            "counts": {
                "cells": self.cells.count,
                "grid": self.grid.count,
                "grid_heights": self.grid_heights.count,
                "faces": self.faces.count,
                "vertices": self.vertices.count,
                "face_indices": self.face_indices.count,
            },
        }


def load_level_terrain(
    level_path: Path, *, ooz_path: Path | None = None
) -> tuple[LandMeshHeader, LandRayTracer]:
    level_data = level_path.read_bytes()
    _block, header = find_land_mesh(level_data)
    stream = decompress_land_ray(level_data, header, ooz_path=ooz_path)
    return header, LandRayTracer(stream)


def load_heightmap_terrain(
    level_path: Path,
    *,
    ooz_path: Path | None = None,
    oodle_dll_path: Path | None = None,
) -> tuple[HeightMapHeader, HeightMapTracer]:
    level_data = level_path.read_bytes()
    _block, header = find_heightmap(level_data)
    block_infos, variance = decompress_heightmap(
        level_data,
        header,
        ooz_path=ooz_path,
        oodle_dll_path=oodle_dll_path,
    )
    return header, HeightMapTracer(header, block_infos, variance)


def load_level_elevation_source(
    level_path: Path,
    *,
    ooz_path: Path | None = None,
    oodle_dll_path: Path | None = None,
) -> tuple[str, LandRayTracer | HeightMapTracer]:
    """Prefer the native heightmap and fall back to the terrain triangle mesh."""
    level_data = level_path.read_bytes()
    if any(block.tag == HMAP_TAG for block in iter_dbld_blocks(level_data)):
        _block, header = find_heightmap(level_data)
        block_infos, variance = decompress_heightmap(
            level_data,
            header,
            ooz_path=ooz_path,
            oodle_dll_path=oodle_dll_path,
        )
        return "heightmap", HeightMapTracer(header, block_infos, variance)
    _block, header = find_land_mesh(level_data)
    stream = decompress_land_ray(level_data, header, ooz_path=ooz_path)
    return "land-ray", LandRayTracer(stream)


def read_dxp_textures(pack_path: Path) -> tuple[bytes, tuple[DxpTextureEntry, ...]]:
    """Read the base ``locations_maps.dxp.bin`` texture catalog."""
    data = pack_path.read_bytes()
    if len(data) < DXP_HEADER_SIZE + DXP_DUMP_STRING_OFFSET:
        raise TerrainExtractionError("DxP2 map texture pack is truncated")
    if not data.startswith(DXP_MAGIC):
        raise TerrainExtractionError("map texture pack is not DxP2")
    version = _u32(data, 4, "DxP2 version")
    count = _u32(data, 8, "DxP2 texture count")
    if version != 2 or count <= 0:
        raise TerrainExtractionError(f"unsupported DxP2 header: version={version}, count={count}")

    dump_offset = DXP_HEADER_SIZE
    names_table = dump_offset + _u32(data, dump_offset, "DxP2 names table")
    headers_offset = dump_offset + _u32(
        data,
        dump_offset + DXP_DUMP_TABLE_SIZE,
        "DxP2 DDSx table",
    )
    records_offset = dump_offset + _u32(
        data,
        dump_offset + DXP_DUMP_TABLE_SIZE * 2,
        "DxP2 record table",
    )
    names_start = dump_offset + DXP_DUMP_STRING_OFFSET
    _checked_slice(data, names_start, names_table - names_start, "DxP2 names")
    _checked_slice(data, headers_offset, count * DXP_DDSX_HEADER_SIZE, "DxP2 DDSx headers")
    _checked_slice(data, records_offset, count * DXP_RECORD_SIZE, "DxP2 records")

    names: list[str] = []
    cursor = names_start
    for _ in range(count):
        terminator = data.find(b"\0", cursor, names_table)
        if terminator < 0:
            raise TerrainExtractionError("DxP2 name table is truncated")
        try:
            raw_name = data[cursor:terminator].decode("ascii")
        except UnicodeDecodeError as exc:
            raise TerrainExtractionError("DxP2 texture name is not ASCII") from exc
        names.append(raw_name.split("*", 1)[0])
        cursor = terminator + 1

    entries: list[DxpTextureEntry] = []
    for index, name in enumerate(names):
        header_offset = headers_offset + index * DXP_DDSX_HEADER_SIZE
        if data[header_offset : header_offset + 4] != DXP_DDSX_MAGIC:
            raise TerrainExtractionError(f"texture {name} has no DDSx header")
        texture_format = data[header_offset + 4 : header_offset + 8].decode(
            "ascii",
            errors="replace",
        )
        flags = _u32(data, header_offset + 8, f"{name} DDSx flags")
        width, height = struct.unpack_from("<HH", data, header_offset + 12)
        levels = data[header_offset + 16]
        decoded_size = _u32(data, header_offset + 24, f"{name} decoded size")
        header_packed_size = _u32(data, header_offset + 28, f"{name} packed size")

        record_offset = records_offset + index * DXP_RECORD_SIZE
        data_offset = _u32(data, record_offset + 12, f"{name} data offset")
        packed_size = _u32(data, record_offset + 16, f"{name} record packed size")
        if header_packed_size != packed_size:
            raise TerrainExtractionError(f"texture {name} packed sizes disagree")
        _checked_slice(data, data_offset, packed_size, f"{name} texture payload")
        entries.append(
            DxpTextureEntry(
                name=name,
                format=texture_format,
                flags=flags,
                width=int(width),
                height=int(height),
                levels=int(levels),
                decoded_size=decoded_size,
                packed_size=packed_size,
                data_offset=data_offset,
            )
        )
    return data, tuple(entries)


def decode_dxp_texture(
    pack_data: bytes,
    entry: DxpTextureEntry,
    *,
    ooz_path: Path | None = None,
    oodle_dll_path: Path | None = None,
) -> Image.Image:
    """Decode one single-level DXT tactical map from a DxP2 texture pack."""
    if entry.width <= 0 or entry.height <= 0 or entry.levels < 1:
        raise TerrainExtractionError(
            f"texture {entry.name} has unsupported dimensions or mip levels"
        )
    payload = bytes(
        _checked_slice(
            pack_data,
            entry.data_offset,
            entry.packed_size,
            f"{entry.name} payload",
        )
    )
    if entry.packed_size == entry.decoded_size:
        decoded = payload
    else:
        dll_path = _resolve_oodle_dll(oodle_dll_path)
        if dll_path is not None:
            decoded = _oodle_dll_decompress(payload, entry.decoded_size, dll_path)
        else:
            decoded = _ooz_decompress(payload, entry.decoded_size, _resolve_ooz(ooz_path))
    decoder_formats = {"DXT1": 1, "DXT3": 2, "DXT5": 3}
    decoder_format = decoder_formats.get(entry.format)
    if decoder_format is None:
        raise TerrainExtractionError(f"texture {entry.name} uses unsupported format {entry.format}")
    block_size = 8 if entry.format == "DXT1" else 16
    base_level_size = math.ceil(entry.width / 4) * math.ceil(entry.height / 4) * block_size
    if len(decoded) < base_level_size:
        raise TerrainExtractionError(f"texture {entry.name} base mip is truncated")
    try:
        return Image.frombytes(
            "RGBA",
            (entry.width, entry.height),
            decoded[:base_level_size],
            "bcn",
            decoder_format,
        )
    except ValueError as exc:
        raise TerrainExtractionError(f"texture {entry.name} DXT decode failed: {exc}") from exc


def air_map_candidates(
    levels_dir: Path,
    entries: tuple[DxpTextureEntry, ...],
) -> tuple[tuple[str, DxpTextureEntry, Path], ...]:
    """Select dedicated, arcade, and legacy maps used by air battles."""
    candidates: list[tuple[str, DxpTextureEntry, Path]] = []
    seen: set[str] = set()
    for entry in entries:
        if not entry.name.endswith("_map"):
            continue
        map_id = entry.name.removesuffix("_map")
        if map_id.startswith(("avg_", "avn_")) or map_id in seen:
            continue
        level_path = levels_dir / f"{map_id}.bin"
        if not level_path.is_file():
            continue
        seen.add(map_id)
        candidates.append((map_id, entry, level_path))
    return tuple(candidates)


def resolve_level_config_dir(path: Path) -> Path:
    """Resolve either an extracted VROMFS root or its concrete levels directory."""
    resolved = path.resolve()
    candidates = (
        resolved,
        resolved / "levels",
        resolved / "aces.vromfs.bin_u" / "levels",
    )
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.blkx")):
            return candidate
    raise TerrainExtractionError(
        f"level config root has no extracted levels/*.blkx files: {resolved}"
    )


def read_altitude_datum(level_config_dir: Path, map_id: str) -> AltitudeDatum:
    """Read the world-Y origin used by 8111 altitude from a level config."""
    config_path = level_config_dir / f"{map_id}.blkx"
    if not config_path.is_file():
        raise TerrainExtractionError(f"level altitude config is missing: {config_path}")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerrainExtractionError(
            f"level altitude config is invalid: {config_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise TerrainExtractionError(f"level altitude config is not an object: {config_path}")
    try:
        map_min = tuple(float(value) for value in payload["mapCoord0"])
        map_max = tuple(float(value) for value in payload["mapCoord1"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TerrainExtractionError(f"level map bounds are invalid: {config_path}: {exc}") from exc
    if (
        len(map_min) != 2
        or len(map_max) != 2
        or not all(math.isfinite(value) for value in (*map_min, *map_max))
        or map_max[0] <= map_min[0]
        or map_max[1] <= map_min[1]
    ):
        raise TerrainExtractionError(f"level map bounds are invalid: {config_path}")
    raw_value = payload.get("water_level", 0.0)
    try:
        value_m = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise TerrainExtractionError(
            f"level water_level is not numeric: {config_path}: {raw_value!r}"
        ) from exc
    if not math.isfinite(value_m):
        raise TerrainExtractionError(f"level water_level is not finite: {config_path}")
    return AltitudeDatum(
        value_m=value_m,
        kind="water_level" if "water_level" in payload else "water_level_default_zero",
        source_file=config_path.name,
        source_sha256=_sha256_file(config_path),
        map_bounds=(map_min[0], map_min[1], map_max[0], map_max[1]),
    )


def build_terrain_grid(
    tracer: LandRayTracer,
    *,
    spacing_m: float,
    progress_label: str = "",
) -> TerrainGridBuild:
    """Sample an LTdump mesh into a quantized regular X/Z height grid."""
    if not math.isfinite(spacing_m) or not 8.0 <= spacing_m <= 2048.0:
        raise TerrainExtractionError("grid spacing must be between 8 and 2048 metres")
    min_x = float(tracer.offset_x)
    min_z = float(tracer.offset_z)
    max_x = min_x + tracer.num_cells_x * tracer.cell_size
    max_z = min_z + tracer.num_cells_y * tracer.cell_size
    width = math.ceil((max_x - min_x) / spacing_m) + 1
    height = math.ceil((max_z - min_z) / spacing_m) + 1
    if width * height > 16_800_000:
        raise TerrainExtractionError(f"terrain grid is too large: {width}x{height}")
    spacing_x = (max_x - min_x) / (width - 1)
    spacing_z = (max_z - min_z) / (height - 1)

    heights = array("f")
    valid_min = math.inf
    valid_max = -math.inf
    valid_samples = 0
    progress_every = max(1, height // 16)
    for row in range(height):
        world_z = min_z + row * spacing_z
        for column in range(width):
            world_x = min_x + column * spacing_x
            value = tracer.height_at(world_x, world_z)
            if value is None or not math.isfinite(value):
                heights.append(math.nan)
                continue
            heights.append(value)
            valid_min = min(valid_min, value)
            valid_max = max(valid_max, value)
            valid_samples += 1
        if progress_label and (row + 1 == height or (row + 1) % progress_every == 0):
            print(
                f"[{progress_label}] grid {row + 1}/{height}",
                file=sys.stderr,
                flush=True,
            )
    if valid_samples == 0:
        raise TerrainExtractionError("terrain grid contains no valid samples")

    height_scale = max(0.05, (valid_max - valid_min) / (TERRAIN_NODATA - 1))
    samples = array("H")
    for value in heights:
        if math.isnan(value):
            samples.append(TERRAIN_NODATA)
            continue
        quantized = round((value - valid_min) / height_scale)
        samples.append(min(max(quantized, 0), TERRAIN_NODATA - 1))
    return TerrainGridBuild(
        width=width,
        height=height,
        world_bounds=(min_x, min_z, max_x, max_z),
        spacing_x_m=spacing_x,
        spacing_z_m=spacing_z,
        height_offset_m=valid_min,
        height_scale_m=height_scale,
        samples=samples,
        valid_samples=valid_samples,
    )


def build_native_heightmap_grid(
    tracer: HeightMapTracer,
    *,
    progress_label: str = "",
) -> TerrainGridBuild:
    """Preserve an HM2 map's native samples and game interpolation exactly."""
    max_x = tracer.offset_x + tracer.num_cells_x * tracer.cell_size
    max_z = tracer.offset_z + tracer.num_cells_y * tracer.cell_size
    samples = tracer.raw_samples(progress_label=progress_label)
    return TerrainGridBuild(
        width=tracer.num_cells_x,
        height=tracer.num_cells_y,
        world_bounds=(tracer.offset_x, tracer.offset_z, max_x, max_z),
        spacing_x_m=tracer.cell_size,
        spacing_z_m=tracer.cell_size,
        height_offset_m=tracer.height_offset_m,
        height_scale_m=tracer.height_scale_m,
        samples=samples,
        valid_samples=len(samples),
        interpolation="diamond",
        nodata=None,
    )


def validate_terrain_grid(
    tracer: LandRayTracer | HeightMapTracer,
    grid: TerrainGridBuild,
    *,
    sample_count: int,
    seed: int,
) -> dict[str, float | int]:
    if sample_count <= 0:
        return {"requested": 0, "compared": 0}
    rng = random.Random(seed)
    min_x, min_z, max_x, max_z = grid.world_bounds
    errors: list[float] = []
    for _ in range(sample_count):
        world_x = rng.uniform(min_x, max_x)
        world_z = rng.uniform(min_z, max_z)
        exact = tracer.height_at(world_x, world_z)
        interpolated = grid.height_at(world_x, world_z)
        if exact is not None and interpolated is not None:
            errors.append(abs(exact - interpolated))
    if not errors:
        return {"requested": sample_count, "compared": 0}
    errors.sort()

    def percentile(fraction: float) -> float:
        index = min(len(errors) - 1, round((len(errors) - 1) * fraction))
        return errors[index]

    return {
        "requested": sample_count,
        "compared": len(errors),
        "mean_abs_error_m": statistics.fmean(errors),
        "p50_abs_error_m": percentile(0.50),
        "p95_abs_error_m": percentile(0.95),
        "p99_abs_error_m": percentile(0.99),
        "max_abs_error_m": errors[-1],
    }


def encode_terrain_grid(
    map_id: str,
    grid: TerrainGridBuild,
    *,
    source_sha256: str,
    altitude_datum: AltitudeDatum,
    validation: dict[str, float | int],
) -> tuple[bytes, dict[str, object]]:
    samples = array("H", grid.samples)
    if sys.byteorder != "little":
        samples.byteswap()
    raw = samples.tobytes()
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    header: dict[str, object] = {
        "schema_version": 1,
        "map_id": map_id,
        "width": grid.width,
        "height": grid.height,
        "world_bounds": list(grid.world_bounds),
        "map_bounds": list(altitude_datum.map_bounds),
        "spacing_m": [grid.spacing_x_m, grid.spacing_z_m],
        "interpolation": grid.interpolation,
        "height_offset_m": grid.height_offset_m,
        "height_scale_m": grid.height_scale_m,
        "altitude_datum_m": altitude_datum.value_m,
        "altitude_datum_kind": altitude_datum.kind,
        "altitude_datum_source_file": altitude_datum.source_file,
        "altitude_datum_source_sha256": altitude_datum.source_sha256,
        "nodata": grid.nodata,
        "valid_samples": grid.valid_samples,
        "source_sha256": source_sha256,
        "raw_sha256": raw_sha256,
        "validation": validation,
    }
    header_bytes = json.dumps(
        header,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = (
        TERRAIN_GRID_PREFIX.pack(TERRAIN_GRID_MAGIC, len(header_bytes))
        + header_bytes
        + zlib.compress(raw, level=9)
    )
    return encoded, header


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_bytes(data)
    os.replace(temp_path, path)


def _build_map_grid_worker(
    map_id: str,
    level_path_text: str,
    output_dir_text: str,
    decoder_text: str,
    oodle_dll_text: str,
    spacing_m: float,
    min_spacing_m: float,
    max_p95_error_m: float,
    validation_samples: int,
    fingerprint: str,
    altitude_datum_m: float,
    altitude_datum_kind: str,
    altitude_datum_source_file: str,
    altitude_datum_source_sha256: str,
    map_bounds: tuple[float, float, float, float],
    label: str,
) -> dict[str, object]:
    level_path = Path(level_path_text)
    output_dir = Path(output_dir_text)
    decoder = Path(decoder_text)
    oodle_dll = Path(oodle_dll_text) if oodle_dll_text else None
    source_sha256 = _sha256_file(level_path)
    altitude_datum = AltitudeDatum(
        value_m=altitude_datum_m,
        kind=altitude_datum_kind,
        source_file=altitude_datum_source_file,
        source_sha256=altitude_datum_source_sha256,
        map_bounds=map_bounds,
    )
    source_kind, tracer = load_level_elevation_source(
        level_path,
        ooz_path=decoder,
        oodle_dll_path=oodle_dll,
    )
    if isinstance(tracer, HeightMapTracer):
        grid = build_native_heightmap_grid(tracer, progress_label=label)
    else:
        current_spacing = spacing_m
        grid = build_terrain_grid(
            tracer,
            spacing_m=current_spacing,
            progress_label=label,
        )
        while True:
            validation = validate_terrain_grid(
                tracer,
                grid,
                sample_count=validation_samples,
                seed=int(source_sha256[:16], 16),
            )
            p95 = validation.get("p95_abs_error_m")
            if (
                not isinstance(p95, (int, float))
                or p95 <= max_p95_error_m
                or current_spacing <= min_spacing_m
            ):
                break
            next_spacing = max(min_spacing_m, current_spacing / 2.0)
            print(
                f"[{label}] refining terrain {current_spacing:g}m -> "
                f"{next_spacing:g}m (p95={p95:.3f}m)",
                file=sys.stderr,
                flush=True,
            )
            try:
                next_grid = build_terrain_grid(
                    tracer,
                    spacing_m=next_spacing,
                    progress_label=label,
                )
            except TerrainExtractionError as exc:
                if "terrain grid is too large" not in str(exc):
                    raise
                print(
                    f"[{label}] refinement stopped: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                break
            grid = next_grid
            current_spacing = next_spacing
    validation = validate_terrain_grid(
        tracer,
        grid,
        sample_count=validation_samples,
        seed=int(source_sha256[:16], 16),
    )
    encoded, grid_header = encode_terrain_grid(
        map_id,
        grid,
        source_sha256=source_sha256,
        altitude_datum=altitude_datum,
        validation=validation,
    )
    filename = f"{map_id}.bth"
    _write_atomic(output_dir / filename, encoded)
    print(
        f"[{label}] done: {grid.width}x{grid.height}, {len(encoded)} bytes, "
        f"p95={validation.get('p95_abs_error_m', 'n/a')}",
        file=sys.stderr,
        flush=True,
    )
    return {
        "id": map_id,
        "file": filename,
        "fingerprint": fingerprint,
        "world_bounds": list(grid.world_bounds),
        "map_bounds": list(altitude_datum.map_bounds),
        "grid_size": [grid.width, grid.height],
        "spacing_m": [grid.spacing_x_m, grid.spacing_z_m],
        "interpolation": grid.interpolation,
        "source_kind": source_kind,
        "terrain_sha256": grid_header["raw_sha256"],
        "source_sha256": source_sha256,
        "altitude_datum_m": altitude_datum.value_m,
        "altitude_datum_kind": altitude_datum.kind,
        "altitude_datum_source_file": altitude_datum.source_file,
        "altitude_datum_source_sha256": altitude_datum.source_sha256,
        "validation": validation,
        "quality_target_met": (
            not isinstance(validation.get("p95_abs_error_m"), (int, float))
            or validation["p95_abs_error_m"] <= max_p95_error_m
        ),
    }


def build_air_terrain_pack(
    game_root: Path,
    output_dir: Path,
    *,
    level_config_dir: Path,
    ooz_path: Path | None,
    oodle_dll_path: Path | None,
    spacing_m: float,
    min_spacing_m: float,
    max_p95_error_m: float,
    validation_samples: int,
    workers: int,
    only_map: str = "",
) -> dict[str, object]:
    if not 8.0 <= min_spacing_m <= spacing_m <= 2048.0:
        raise TerrainExtractionError(
            "terrain spacing must satisfy 8 <= min-spacing <= spacing <= 2048"
        )
    if not math.isfinite(max_p95_error_m) or max_p95_error_m <= 0.0:
        raise TerrainExtractionError("maximum P95 error must be positive")
    levels_dir = game_root / "levels"
    texture_pack_path = game_root / "content" / "base" / "res" / "locations_maps.dxp.bin"
    if not levels_dir.is_dir() or not texture_pack_path.is_file():
        raise TerrainExtractionError("game root has no levels or base locations map pack")
    decoder = _resolve_ooz(ooz_path)
    oodle_dll = _resolve_oodle_dll(oodle_dll_path)
    pack_data, entries = read_dxp_textures(texture_pack_path)
    candidates = air_map_candidates(levels_dir, entries)
    if only_map:
        candidates = tuple(candidate for candidate in candidates if candidate[0] == only_map)
        if not candidates:
            raise TerrainExtractionError(f"air map is not present in the client: {only_map}")

    resolved_level_config_dir = resolve_level_config_dir(level_config_dir)
    altitude_datums = {
        map_id: read_altitude_datum(resolved_level_config_dir, map_id)
        for map_id, _texture, _level_path in candidates
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    descriptors: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    fingerprints: dict[str, str] = {}
    for position, (map_id, texture, _level_path) in enumerate(candidates, start=1):
        label = f"{position}/{len(candidates)} {map_id}"
        try:
            print(f"[{label}] decoding tactical-map fingerprint", file=sys.stderr, flush=True)
            with decode_dxp_texture(
                pack_data,
                texture,
                ooz_path=decoder,
                oodle_dll_path=oodle_dll,
            ) as map_image:
                fingerprints[map_id] = pil_image_dhash(map_image)
        except (OSError, TerrainExtractionError, ValueError) as exc:
            failures.append({"id": map_id, "error": str(exc)})
            print(f"[{label}] failed: {exc}", file=sys.stderr, flush=True)

    worker_count = min(max(1, int(workers)), max(1, len(candidates)))
    tasks = [
        (
            map_id,
            str(level_path),
            str(output_dir),
            str(decoder),
            str(oodle_dll) if oodle_dll is not None else "",
            spacing_m,
            min_spacing_m,
            max_p95_error_m,
            validation_samples,
            fingerprints[map_id],
            altitude_datums[map_id].value_m,
            altitude_datums[map_id].kind,
            altitude_datums[map_id].source_file,
            altitude_datums[map_id].source_sha256,
            altitude_datums[map_id].map_bounds,
            f"{position}/{len(candidates)} {map_id}",
        )
        for position, (map_id, _texture, level_path) in enumerate(candidates, start=1)
        if map_id in fingerprints
    ]
    if worker_count == 1:
        for task in tasks:
            map_id = task[0]
            print(f"[{task[-1]}] decoding terrain", file=sys.stderr, flush=True)
            try:
                descriptors.append(_build_map_grid_worker(*task))
            except (OSError, TerrainExtractionError, ValueError) as exc:
                failures.append({"id": map_id, "error": str(exc)})
                print(f"[{task[-1]}] failed: {exc}", file=sys.stderr, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {}
            for task in tasks:
                print(f"[{task[-1]}] queued terrain", file=sys.stderr, flush=True)
                futures[executor.submit(_build_map_grid_worker, *task)] = (task[0], task[-1])
            for future in as_completed(futures):
                map_id, label = futures[future]
                try:
                    descriptors.append(future.result())
                except (OSError, TerrainExtractionError, ValueError) as exc:
                    failures.append({"id": map_id, "error": str(exc)})
                    print(f"[{label}] failed: {exc}", file=sys.stderr, flush=True)

    descriptors.sort(key=lambda item: str(item["id"]))
    failures.sort(key=lambda item: item["id"])

    index: dict[str, object] = {
        "schema_version": TERRAIN_PACK_SCHEMA_VERSION,
        "kind": "terrain-only",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "altitude_datum_formula": ALTITUDE_DATUM_FORMULA,
        "texture_pack_sha256": _sha256_file(texture_pack_path),
        "requested_spacing_m": spacing_m,
        "minimum_spacing_m": min_spacing_m,
        "maximum_p95_error_m": max_p95_error_m,
        "maps": descriptors,
        "failures": failures,
    }
    index_bytes = json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    _write_atomic(output_dir / "index.json", index_bytes)
    return index


def _grid_with_altitude_datum(
    data: bytes,
    *,
    map_id: str,
    altitude_datum: AltitudeDatum,
) -> bytes:
    if len(data) < TERRAIN_GRID_PREFIX.size:
        raise TerrainExtractionError(f"terrain grid is truncated: {map_id}")
    magic, header_size = TERRAIN_GRID_PREFIX.unpack_from(data)
    payload_offset = TERRAIN_GRID_PREFIX.size + header_size
    if (
        magic not in {TERRAIN_GRID_MAGIC, TERRAIN_GRID_MAGIC_V2}
        or header_size <= 0
        or payload_offset > len(data)
    ):
        raise TerrainExtractionError(f"terrain grid header is invalid: {map_id}")
    try:
        header = json.loads(data[TERRAIN_GRID_PREFIX.size : payload_offset].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerrainExtractionError(f"terrain grid header is invalid: {map_id}: {exc}") from exc
    expected_schema = 1 if magic == TERRAIN_GRID_MAGIC else 2
    if (
        not isinstance(header, dict)
        or header.get("schema_version") != expected_schema
        or header.get("map_id") != map_id
    ):
        raise TerrainExtractionError(f"terrain grid identity is invalid: {map_id}")
    header["altitude_datum_m"] = altitude_datum.value_m
    header["altitude_datum_kind"] = altitude_datum.kind
    header["altitude_datum_source_file"] = altitude_datum.source_file
    header["altitude_datum_source_sha256"] = altitude_datum.source_sha256
    header["map_bounds"] = list(altitude_datum.map_bounds)
    encoded_header = json.dumps(
        header,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        TERRAIN_GRID_PREFIX.pack(magic, len(encoded_header))
        + encoded_header
        + data[payload_offset:]
    )


def apply_altitude_datums_to_pack(
    pack_dir: Path,
    level_config_dir: Path,
) -> dict[str, object]:
    """Add exact per-level 8111 altitude origins without rebuilding terrain samples."""
    index_path = pack_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerrainExtractionError(f"terrain pack index is invalid: {index_path}: {exc}") from exc
    if not isinstance(index, dict) or index.get("schema_version") != TERRAIN_PACK_SCHEMA_VERSION:
        raise TerrainExtractionError("terrain pack index schema is unsupported")
    raw_maps = index.get("maps")
    if not isinstance(raw_maps, list) or not raw_maps:
        raise TerrainExtractionError("terrain pack index has no maps")

    resolved_level_config_dir = resolve_level_config_dir(level_config_dir)
    planned: list[tuple[dict[str, object], Path, AltitudeDatum]] = []
    for raw_descriptor in raw_maps:
        if not isinstance(raw_descriptor, dict):
            raise TerrainExtractionError("terrain pack map descriptor is not an object")
        try:
            map_id = str(raw_descriptor["id"])
            filename = str(raw_descriptor["file"])
        except KeyError as exc:
            raise TerrainExtractionError(f"terrain pack map descriptor is invalid: {exc}") from exc
        if not map_id or Path(filename).name != filename:
            raise TerrainExtractionError(f"terrain pack map descriptor has unsafe names: {map_id}")
        grid_path = pack_dir / filename
        datum = read_altitude_datum(resolved_level_config_dir, map_id)
        _grid_with_altitude_datum(
            grid_path.read_bytes(),
            map_id=map_id,
            altitude_datum=datum,
        )
        planned.append((dict(raw_descriptor), grid_path, datum))

    updated_maps: list[dict[str, object]] = []
    for descriptor, grid_path, datum in planned:
        map_id = str(descriptor["id"])
        encoded = _grid_with_altitude_datum(
            grid_path.read_bytes(),
            map_id=map_id,
            altitude_datum=datum,
        )
        _write_atomic(grid_path, encoded)
        descriptor["altitude_datum_m"] = datum.value_m
        descriptor["altitude_datum_kind"] = datum.kind
        descriptor["altitude_datum_source_file"] = datum.source_file
        descriptor["altitude_datum_source_sha256"] = datum.source_sha256
        descriptor["map_bounds"] = list(datum.map_bounds)
        updated_maps.append(descriptor)

    index["maps"] = updated_maps
    index.pop("game_root", None)
    index.pop("level_config_dir", None)
    index["altitude_datum_formula"] = ALTITUDE_DATUM_FORMULA
    index_bytes = json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    _write_atomic(index_path, index_bytes)
    return index


def audit_terrain_pack(pack_dir: Path) -> dict[str, object]:
    """Load every grid through the production validator and summarize quality."""
    index_path = pack_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerrainExtractionError(f"terrain pack index is invalid: {index_path}: {exc}") from exc
    if not isinstance(index, dict) or index.get("schema_version") != TERRAIN_PACK_SCHEMA_VERSION:
        raise TerrainExtractionError("terrain pack index schema is unsupported")
    raw_maps = index.get("maps")
    configured_failures = index.get("failures", [])
    if not isinstance(raw_maps, list):
        raise TerrainExtractionError("terrain pack index maps are missing")
    if not isinstance(configured_failures, list):
        raise TerrainExtractionError("terrain pack failure list is invalid")

    descriptors: list[TerrainMapDescriptor] = []
    load_failures: list[dict[str, str]] = []
    source_kinds: Counter[str] = Counter()
    altitude_datum_kinds: Counter[str] = Counter()
    spacing: Counter[str] = Counter()
    validation_p95_m: list[float] = []
    quality_target_not_met: list[str] = []
    total_bytes = 0
    for raw_descriptor in raw_maps:
        map_id = str(raw_descriptor.get("id", "")) if isinstance(raw_descriptor, dict) else ""
        try:
            descriptor = TerrainMapDescriptor.from_json(raw_descriptor)
            grid_path = pack_dir / descriptor.file
            TerrainHeightMap.load(grid_path, descriptor)
            total_bytes += grid_path.stat().st_size
            descriptors.append(descriptor)
            source_kinds[str(raw_descriptor.get("source_kind", "unknown"))] += 1
            altitude_datum_kinds[descriptor.altitude_datum_kind] += 1
            raw_spacing = raw_descriptor.get("spacing_m", [])
            spacing[json.dumps(raw_spacing, separators=(",", ":"))] += 1
            raw_validation = raw_descriptor.get("validation")
            if isinstance(raw_validation, dict):
                raw_p95 = raw_validation.get("p95_abs_error_m")
                if isinstance(raw_p95, (int, float)) and math.isfinite(raw_p95):
                    validation_p95_m.append(float(raw_p95))
            if raw_descriptor.get("quality_target_met") is False:
                quality_target_not_met.append(descriptor.map_id)
        except (OSError, TerrainDataError, TypeError, ValueError) as exc:
            load_failures.append({"id": map_id, "error": str(exc)})

    ambiguous_pairs: list[dict[str, object]] = []
    for left_index, left in enumerate(descriptors):
        for right in descriptors[left_index + 1 :]:
            if left.map_bounds != right.map_bounds or left.terrain_sha256 == right.terrain_sha256:
                continue
            distance = fingerprint_distance(left.fingerprint, right.fingerprint)
            if distance < DEFAULT_MIN_FINGERPRINT_MARGIN:
                ambiguous_pairs.append(
                    {"left": left.map_id, "right": right.map_id, "distance": distance}
                )

    valid = (
        len(descriptors) == len(raw_maps)
        and not configured_failures
        and not load_failures
        and not ambiguous_pairs
    )
    return {
        "schema_version": TERRAIN_PACK_SCHEMA_VERSION,
        "valid": valid,
        "maps": len(raw_maps),
        "loaded_maps": len(descriptors),
        "total_grid_bytes": total_bytes,
        "source_kinds": dict(sorted(source_kinds.items())),
        "altitude_datum_kinds": dict(sorted(altitude_datum_kinds.items())),
        "spacing_m": dict(sorted(spacing.items())),
        "validation_p95_m": {
            "maps": len(validation_p95_m),
            "mean": statistics.fmean(validation_p95_m) if validation_p95_m else None,
            "max": max(validation_p95_m) if validation_p95_m else None,
        },
        "quality_target_not_met": sorted(quality_target_not_met),
        "configured_failures": configured_failures,
        "load_failures": load_failures,
        "ambiguous_fingerprint_pairs": ambiguous_pairs,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("level", nargs="?", type=Path, help="War Thunder levels/*.bin path")
    parser.add_argument("--ooz", type=Path, help="compatible ooz executable")
    parser.add_argument("--oodle-dll", type=Path, help="local oo2core_9_win64.dll path")
    parser.add_argument("--query", nargs=2, type=float, metavar=("WORLD_X", "WORLD_Z"))
    parser.add_argument("--build-pack", action="store_true", help="build all air-map grids")
    parser.add_argument(
        "--apply-altitude-datums",
        action="store_true",
        help="add per-map 8111 altitude origins to an existing pack",
    )
    parser.add_argument(
        "--audit-pack",
        action="store_true",
        help="validate every grid in an existing local pack",
    )
    parser.add_argument("--game-root", type=Path, help="War Thunder installation directory")
    parser.add_argument(
        "--level-config-dir",
        type=Path,
        help="extracted aces.vromfs.bin levels directory or extraction root",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_terrain_pack_dir(),
        help="local terrain pack directory",
    )
    parser.add_argument(
        "--spacing", type=float, default=64.0, help="initial grid spacing in metres"
    )
    parser.add_argument(
        "--min-spacing",
        type=float,
        default=8.0,
        help="minimum adaptive grid spacing in metres",
    )
    parser.add_argument(
        "--max-p95-error",
        type=float,
        default=3.0,
        help="refine sampled land meshes until P95 error is at most this many metres",
    )
    parser.add_argument(
        "--validation-samples",
        type=int,
        default=5000,
        help="random exact-mesh comparisons per map",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(4, os.cpu_count() or 1),
        help="parallel terrain extraction processes",
    )
    parser.add_argument("--only-map", default="", help="build only one map id")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    action_count = sum(
        bool(action) for action in (args.build_pack, args.apply_altitude_datums, args.audit_pack)
    )
    if action_count > 1:
        parser.error("--build-pack, --apply-altitude-datums, and --audit-pack are exclusive")
    if args.audit_pack:
        audit = audit_terrain_pack(args.output.resolve())
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 0 if audit["valid"] else 2
    if args.apply_altitude_datums:
        if args.level_config_dir is None:
            parser.error("--apply-altitude-datums requires --level-config-dir")
        index = apply_altitude_datums_to_pack(
            args.output.resolve(),
            args.level_config_dir.resolve(),
        )
        print(
            json.dumps(
                {
                    "schema_version": index["schema_version"],
                    "output": str(args.output.resolve()),
                    "maps": len(index["maps"]),
                    "altitude_datums_applied": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.build_pack:
        if args.game_root is None:
            parser.error("--build-pack requires --game-root")
        if args.level_config_dir is None:
            parser.error("--build-pack requires --level-config-dir")
        index = build_air_terrain_pack(
            args.game_root.resolve(),
            args.output.resolve(),
            level_config_dir=args.level_config_dir.resolve(),
            ooz_path=args.ooz,
            oodle_dll_path=args.oodle_dll,
            spacing_m=args.spacing,
            min_spacing_m=args.min_spacing,
            max_p95_error_m=args.max_p95_error,
            validation_samples=max(0, args.validation_samples),
            workers=max(1, args.workers),
            only_map=str(args.only_map or "").strip(),
        )
        summary = {
            "schema_version": index["schema_version"],
            "output": str(args.output.resolve()),
            "maps": len(index["maps"]),
            "failures": index["failures"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if not index["failures"] else 2
    if args.level is None:
        parser.error("LEVEL is required unless --build-pack is used")
    level_path = args.level.resolve()
    header, tracer = load_level_terrain(level_path, ooz_path=args.ooz)
    result: dict[str, object] = {
        "schema_version": 1,
        "source": {
            "path": str(level_path),
            "size": level_path.stat().st_size,
            "sha256": _sha256_file(level_path),
        },
        "land_mesh": {
            "grid_cell_size_m": header.grid_cell_size,
            "land_cell_size_m": header.land_cell_size,
            "map_size": [header.map_size_x, header.map_size_y],
            "origin": [header.origin_x, header.origin_y],
            "use_tile": header.use_tile,
        },
        "land_ray": tracer.describe(),
    }
    if args.query is not None:
        x, z = args.query
        result["query"] = {"x": x, "z": z, "terrain_height_m": tracer.height_at(x, z)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
