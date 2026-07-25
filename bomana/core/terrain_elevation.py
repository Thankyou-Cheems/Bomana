"""Terrain-only target elevation lookup for bomb prediction.

The runtime consumes locally generated ``BTH1`` grids and compressed ``BTH2``
offline packs.  It never reads the game process or game files and uses the
official 8111 tactical-map image only to select the matching offline grid.
Buildings, vegetation, vehicles, and other scene objects are intentionally
absent from these grids.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import struct
import sys
import threading
import zlib
from array import array
from compression import zstd
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from PIL import Image

TERRAIN_PACK_SCHEMA_VERSION: Final = 1
TERRAIN_GRID_MAGIC_V1: Final = b"BTH1"
TERRAIN_GRID_MAGIC_V2: Final = b"BTH2"
# Kept as the original magic for source compatibility with existing callers and tests.
TERRAIN_GRID_MAGIC: Final = TERRAIN_GRID_MAGIC_V1
TERRAIN_GRID_PREFIX: Final = struct.Struct("<4sI")
TERRAIN_GRID_V2_ENCODING: Final = "gradient-zigzag-shuffle-zstd"
TERRAIN_NODATA: Final = 0xFFFF
FINGERPRINT_WIDTH: Final = 17
FINGERPRINT_HEIGHT: Final = 16
FINGERPRINT_BITS: Final = (FINGERPRINT_WIDTH - 1) * FINGERPRINT_HEIGHT
DEFAULT_MAX_FINGERPRINT_DISTANCE: Final = 40
DEFAULT_MIN_FINGERPRINT_MARGIN: Final = 8
MAX_INDEX_BYTES: Final = 4 * 1024 * 1024
MAX_GRID_BYTES: Final = 128 * 1024 * 1024
MAX_TACTICAL_MAP_WIDTH: Final = 4096
MAX_TACTICAL_MAP_HEIGHT: Final = 4096
MAX_TACTICAL_MAP_PIXELS: Final = 16 * 1024 * 1024
BUNDLED_TERRAIN_PACK_DIR: Final = Path(__file__).resolve().parents[1] / "data" / "terrain-v1"


class TerrainDataError(RuntimeError):
    """Raised when a generated terrain pack violates the runtime contract."""


def _decompress_zlib_exact(payload: bytes, expected_size: int) -> bytes:
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(payload, expected_size + 1)
        if len(raw) > expected_size or decompressor.unconsumed_tail:
            raise TerrainDataError("terrain grid payload exceeds its declared dimensions")
        raw += decompressor.flush()
    except zlib.error as exc:
        raise TerrainDataError(f"terrain grid payload is invalid: {exc}") from exc
    if len(raw) != expected_size or not decompressor.eof or decompressor.unused_data:
        raise TerrainDataError("terrain grid sample count does not match its dimensions")
    return raw


def _decompress_zstd_exact(payload: bytes, expected_size: int) -> bytes:
    try:
        decompressor = zstd.ZstdDecompressor()
        raw = decompressor.decompress(payload, expected_size + 1)
    except zstd.ZstdError as exc:
        raise TerrainDataError(f"terrain grid payload is invalid: {exc}") from exc
    if len(raw) != expected_size or not decompressor.eof or decompressor.unused_data:
        raise TerrainDataError("terrain grid sample count does not match its dimensions")
    return raw


def _unshuffle_uint16(payload: bytes) -> bytes:
    if len(payload) % 2:
        raise TerrainDataError("terrain grid shuffled payload has an invalid length")
    sample_count = len(payload) // 2
    raw = bytearray(len(payload))
    raw[0::2] = payload[:sample_count]
    raw[1::2] = payload[sample_count:]
    return bytes(raw)


def _decode_gradient_samples(payload: bytes, width: int, height: int) -> array[int]:
    residuals = array("H")
    residuals.frombytes(_unshuffle_uint16(payload))
    if sys.byteorder != "little":
        residuals.byteswap()
    if len(residuals) != width * height:
        raise TerrainDataError("terrain grid predictor dimensions do not match")

    samples = array("H", [0]) * len(residuals)
    for index, encoded_delta in enumerate(residuals):
        column = index % width
        if index < width:
            predictor = 0 if column == 0 else samples[index - 1]
        elif column == 0:
            predictor = samples[index - width]
        else:
            predictor = (
                samples[index - 1] + samples[index - width] - samples[index - width - 1]
            ) & 0xFFFF
        signed_delta = (encoded_delta >> 1) ^ -(encoded_delta & 1)
        samples[index] = (predictor + signed_delta) & 0xFFFF
    return samples


def _little_endian_bytes(samples: array[int]) -> bytes:
    canonical = array("H", samples)
    if sys.byteorder != "little":
        canonical.byteswap()
    return canonical.tobytes()


def default_terrain_pack_dir() -> Path:
    override = os.environ.get("BOMANA_TERRAIN_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if BUNDLED_TERRAIN_PACK_DIR.is_dir():
        return BUNDLED_TERRAIN_PACK_DIR
    return Path.home() / ".bomana" / "terrain-v1"


def pil_image_dhash(source: Image.Image) -> str:
    """Return the runtime tactical-map hash for an already decoded image."""
    width, height = source.size
    if (
        width <= 0
        or height <= 0
        or width > MAX_TACTICAL_MAP_WIDTH
        or height > MAX_TACTICAL_MAP_HEIGHT
        or width * height > MAX_TACTICAL_MAP_PIXELS
    ):
        raise TerrainDataError(
            f"tactical-map image dimensions exceed the runtime limit: {width}x{height}"
        )
    grayscale = source.convert("L").resize(
        (FINGERPRINT_WIDTH, FINGERPRINT_HEIGHT),
        Image.Resampling.LANCZOS,
    )
    flattened = getattr(grayscale, "get_flattened_data", None)
    pixels = tuple(flattened() if flattened is not None else grayscale.getdata())
    value = 0
    for row in range(FINGERPRINT_HEIGHT):
        start = row * FINGERPRINT_WIDTH
        for column in range(FINGERPRINT_WIDTH - 1):
            value = (value << 1) | int(pixels[start + column] > pixels[start + column + 1])
    return f"{value:0{FINGERPRINT_BITS // 4}x}"


def image_dhash(image_bytes: bytes) -> str:
    """Return a 256-bit horizontal difference hash for a tactical-map image."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            return pil_image_dhash(source)
    except (Image.DecompressionBombError, OSError, ValueError) as exc:
        raise TerrainDataError(f"invalid tactical-map image: {exc}") from exc


def fingerprint_distance(left: str, right: str) -> int:
    if len(left) != FINGERPRINT_BITS // 4 or len(right) != FINGERPRINT_BITS // 4:
        raise TerrainDataError("map fingerprint has an invalid length")
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError as exc:
        raise TerrainDataError("map fingerprint is not hexadecimal") from exc


def normalized_map_to_world(
    x: float,
    y: float,
    map_min: list[float] | tuple[float, float],
    map_max: list[float] | tuple[float, float],
) -> tuple[float, float] | None:
    """Convert 8111 normalized map X/Y to Dagor world X/Z.

    The tactical-map vertical axis points down, so normalized Y is measured
    from ``map_max[1]`` toward ``map_min[1]``.
    """
    try:
        normalized_x = float(x)
        normalized_y = float(y)
        min_x = float(map_min[0])
        min_z = float(map_min[1])
        max_x = float(map_max[0])
        max_z = float(map_max[1])
    except IndexError, TypeError, ValueError:
        return None
    values = (normalized_x, normalized_y, min_x, min_z, max_x, max_z)
    if not all(math.isfinite(value) for value in values):
        return None
    if max_x <= min_x or max_z <= min_z:
        return None
    world_x = min_x + normalized_x * (max_x - min_x)
    world_z = max_z - normalized_y * (max_z - min_z)
    return world_x, world_z


@dataclass(frozen=True)
class TerrainMapDescriptor:
    map_id: str
    file: str
    fingerprint: str
    world_bounds: tuple[float, float, float, float]
    map_bounds: tuple[float, float, float, float]
    grid_size: tuple[int, int]
    terrain_sha256: str
    altitude_datum_m: float
    altitude_datum_kind: str

    @classmethod
    def from_json(cls, payload: Any) -> TerrainMapDescriptor:
        if not isinstance(payload, dict):
            raise TerrainDataError("terrain map descriptor is not an object")
        try:
            map_id = str(payload["id"])
            filename = str(payload["file"])
            fingerprint = str(payload["fingerprint"])
            bounds = tuple(float(value) for value in payload["world_bounds"])
            map_bounds = tuple(float(value) for value in payload["map_bounds"])
            grid_size = tuple(int(value) for value in payload["grid_size"])
            terrain_sha256 = str(payload["terrain_sha256"])
            altitude_datum_m = float(payload["altitude_datum_m"])
            altitude_datum_kind = str(payload["altitude_datum_kind"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TerrainDataError(f"invalid terrain map descriptor: {exc}") from exc
        if not map_id or Path(filename).name != filename:
            raise TerrainDataError("terrain map descriptor has an unsafe name")
        if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
            raise TerrainDataError("terrain map descriptor has invalid bounds")
        if len(map_bounds) != 4 or not all(math.isfinite(value) for value in map_bounds):
            raise TerrainDataError("terrain map descriptor has invalid map bounds")
        if map_bounds[2] <= map_bounds[0] or map_bounds[3] <= map_bounds[1]:
            raise TerrainDataError("terrain map descriptor has empty map bounds")
        if len(grid_size) != 2 or min(grid_size) < 2:
            raise TerrainDataError("terrain map descriptor has invalid dimensions")
        if len(terrain_sha256) != 64:
            raise TerrainDataError("terrain map descriptor has invalid SHA-256")
        if not math.isfinite(altitude_datum_m):
            raise TerrainDataError("terrain map descriptor has invalid altitude datum")
        if altitude_datum_kind not in {"water_level", "water_level_default_zero"}:
            raise TerrainDataError("terrain map descriptor has invalid altitude datum kind")
        if altitude_datum_kind == "water_level_default_zero" and altitude_datum_m != 0.0:
            raise TerrainDataError("default-zero altitude datum must be zero")
        fingerprint_distance(fingerprint, fingerprint)
        return cls(
            map_id=map_id,
            file=filename,
            fingerprint=fingerprint,
            world_bounds=(bounds[0], bounds[1], bounds[2], bounds[3]),
            map_bounds=(map_bounds[0], map_bounds[1], map_bounds[2], map_bounds[3]),
            grid_size=(grid_size[0], grid_size[1]),
            terrain_sha256=terrain_sha256,
            altitude_datum_m=altitude_datum_m,
            altitude_datum_kind=altitude_datum_kind,
        )

    def matches_map_bounds(self, map_min: Any, map_max: Any) -> bool:
        converted = normalized_map_to_world(0.0, 0.0, map_min, map_max)
        if converted is None:
            return False
        try:
            query = (
                float(map_min[0]),
                float(map_min[1]),
                float(map_max[0]),
                float(map_max[1]),
            )
        except IndexError, TypeError, ValueError:
            return False
        width = max(1.0, self.map_bounds[2] - self.map_bounds[0])
        depth = max(1.0, self.map_bounds[3] - self.map_bounds[1])
        tolerance_x = max(4.0, width * 0.002)
        tolerance_z = max(4.0, depth * 0.002)
        return (
            abs(query[0] - self.map_bounds[0]) <= tolerance_x
            and abs(query[2] - self.map_bounds[2]) <= tolerance_x
            and abs(query[1] - self.map_bounds[1]) <= tolerance_z
            and abs(query[3] - self.map_bounds[3]) <= tolerance_z
        )


class TerrainHeightMap:
    """Validated in-memory view of one quantized terrain grid."""

    def __init__(
        self,
        *,
        map_id: str,
        width: int,
        height: int,
        world_bounds: tuple[float, float, float, float],
        spacing_m: tuple[float, float],
        height_offset_m: float,
        height_scale_m: float,
        altitude_datum_m: float,
        altitude_datum_kind: str,
        samples: array[int],
        interpolation: str = "bilinear",
        nodata: int | None = TERRAIN_NODATA,
    ) -> None:
        self.map_id = map_id
        self.width = width
        self.height = height
        self.world_bounds = world_bounds
        self.spacing_x_m, self.spacing_z_m = spacing_m
        self.height_offset_m = height_offset_m
        self.height_scale_m = height_scale_m
        self.altitude_datum_m = altitude_datum_m
        self.altitude_datum_kind = altitude_datum_kind
        self.samples = samples
        self.interpolation = interpolation
        self.nodata = nodata

    @classmethod
    def load(cls, path: Path, descriptor: TerrainMapDescriptor) -> TerrainHeightMap:
        if path.stat().st_size > MAX_GRID_BYTES:
            raise TerrainDataError(f"terrain grid is too large: {path}")
        data = path.read_bytes()
        if len(data) < TERRAIN_GRID_PREFIX.size:
            raise TerrainDataError("terrain grid is truncated")
        magic, header_size = TERRAIN_GRID_PREFIX.unpack_from(data)
        if magic not in {TERRAIN_GRID_MAGIC_V1, TERRAIN_GRID_MAGIC_V2}:
            raise TerrainDataError("terrain grid magic does not match")
        header_start = TERRAIN_GRID_PREFIX.size
        payload_start = header_start + header_size
        if header_size <= 0 or payload_start > len(data):
            raise TerrainDataError("terrain grid header is out of range")
        try:
            header = json.loads(data[header_start:payload_start].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TerrainDataError(f"terrain grid header is invalid: {exc}") from exc
        expected_schema = 1 if magic == TERRAIN_GRID_MAGIC_V1 else 2
        if not isinstance(header, dict) or header.get("schema_version") != expected_schema:
            raise TerrainDataError("terrain grid schema is unsupported")
        if magic == TERRAIN_GRID_MAGIC_V2:
            if header.get("encoding") != TERRAIN_GRID_V2_ENCODING:
                raise TerrainDataError("terrain grid encoding is unsupported")
            try:
                quantization_bits = int(header["quantization_bits"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TerrainDataError("terrain grid quantization metadata is invalid") from exc
            if not 8 <= quantization_bits <= 16:
                raise TerrainDataError("terrain grid quantization bit depth is invalid")
        try:
            map_id = str(header["map_id"])
            width = int(header["width"])
            height = int(header["height"])
            bounds_raw = tuple(float(value) for value in header["world_bounds"])
            map_bounds_raw = tuple(float(value) for value in header["map_bounds"])
            interpolation = str(header.get("interpolation", "bilinear"))
            height_offset_m = float(header["height_offset_m"])
            height_scale_m = float(header["height_scale_m"])
            altitude_datum_m = float(header["altitude_datum_m"])
            altitude_datum_kind = str(header["altitude_datum_kind"])
            raw_sha256 = str(header["raw_sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TerrainDataError(f"terrain grid metadata is invalid: {exc}") from exc
        if map_id != descriptor.map_id or (width, height) != descriptor.grid_size:
            raise TerrainDataError("terrain grid does not match its index descriptor")
        if len(bounds_raw) != 4 or tuple(bounds_raw) != descriptor.world_bounds:
            raise TerrainDataError("terrain grid bounds do not match its index descriptor")
        if len(map_bounds_raw) != 4 or tuple(map_bounds_raw) != descriptor.map_bounds:
            raise TerrainDataError("terrain map bounds do not match its index descriptor")
        if width < 2 or height < 2 or width * height * 2 > MAX_GRID_BYTES:
            raise TerrainDataError("terrain grid dimensions are invalid")
        if not all(
            math.isfinite(value) for value in (height_offset_m, height_scale_m, altitude_datum_m)
        ):
            raise TerrainDataError("terrain grid quantization is invalid")
        if altitude_datum_m != descriptor.altitude_datum_m:
            raise TerrainDataError("terrain grid altitude datum does not match its index")
        if altitude_datum_kind != descriptor.altitude_datum_kind:
            raise TerrainDataError("terrain grid altitude datum kind does not match its index")
        if height_scale_m <= 0.0:
            raise TerrainDataError("terrain grid height scale must be positive")
        if interpolation not in {"bilinear", "diamond"}:
            raise TerrainDataError("terrain grid interpolation is unsupported")
        try:
            spacing_raw = header.get("spacing_m")
            if spacing_raw is None:
                if interpolation == "diamond":
                    raise TerrainDataError("diamond terrain grid has no spacing metadata")
                spacing_x_m = (bounds_raw[2] - bounds_raw[0]) / (width - 1)
                spacing_z_m = (bounds_raw[3] - bounds_raw[1]) / (height - 1)
            else:
                spacing_x_m = float(spacing_raw[0])
                spacing_z_m = float(spacing_raw[1])
        except (IndexError, TypeError, ValueError) as exc:
            raise TerrainDataError(f"terrain grid spacing is invalid: {exc}") from exc
        if not all(math.isfinite(value) and value > 0.0 for value in (spacing_x_m, spacing_z_m)):
            raise TerrainDataError("terrain grid spacing must be positive")
        sample_spans = (
            width if interpolation == "diamond" else width - 1,
            height if interpolation == "diamond" else height - 1,
        )
        expected_max_x = bounds_raw[0] + sample_spans[0] * spacing_x_m
        expected_max_z = bounds_raw[1] + sample_spans[1] * spacing_z_m
        tolerance = max(spacing_x_m, spacing_z_m) * 1e-5
        if (
            abs(expected_max_x - bounds_raw[2]) > tolerance
            or abs(expected_max_z - bounds_raw[3]) > tolerance
        ):
            raise TerrainDataError("terrain grid spacing does not match its bounds")
        nodata_raw = header.get("nodata", TERRAIN_NODATA)
        if nodata_raw is None:
            nodata = None
        else:
            try:
                nodata = int(nodata_raw)
            except (TypeError, ValueError) as exc:
                raise TerrainDataError(f"terrain grid nodata is invalid: {exc}") from exc
            if not 0 <= nodata <= 0xFFFF:
                raise TerrainDataError("terrain grid nodata is out of range")
        expected_raw_size = width * height * 2
        if magic == TERRAIN_GRID_MAGIC_V1:
            raw = _decompress_zlib_exact(data[payload_start:], expected_raw_size)
            samples = array("H")
            samples.frombytes(raw)
            if sys.byteorder != "little":
                samples.byteswap()
        else:
            predicted = _decompress_zstd_exact(data[payload_start:], expected_raw_size)
            samples = _decode_gradient_samples(predicted, width, height)
            raw = _little_endian_bytes(samples)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != raw_sha256 or digest != descriptor.terrain_sha256:
            raise TerrainDataError("terrain grid SHA-256 does not match")
        return cls(
            map_id=map_id,
            width=width,
            height=height,
            world_bounds=(bounds_raw[0], bounds_raw[1], bounds_raw[2], bounds_raw[3]),
            spacing_m=(spacing_x_m, spacing_z_m),
            height_offset_m=height_offset_m,
            height_scale_m=height_scale_m,
            altitude_datum_m=altitude_datum_m,
            altitude_datum_kind=altitude_datum_kind,
            samples=samples,
            interpolation=interpolation,
            nodata=nodata,
        )

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

    def height_at(self, world_x: float, world_z: float) -> float | None:
        if not math.isfinite(world_x) or not math.isfinite(world_z):
            return None
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
        if valid_weight <= 1e-9:
            return None
        return weighted_height / valid_weight

    def altitude_at(self, world_x: float, world_z: float) -> float | None:
        """Return terrain altitude in the same vertical datum as 8111 ``H, m``."""
        world_height = self.height_at(world_x, world_z)
        if world_height is None:
            return None
        if self.altitude_datum_kind == "water_level":
            world_height = max(world_height, self.altitude_datum_m)
        return world_height - self.altitude_datum_m


@dataclass(frozen=True)
class TerrainMapMatch:
    map_id: str
    distance: int
    margin: int | None


class TerrainElevationService:
    """Thread-safe local pack loader and current-map resolver."""

    def __init__(
        self,
        pack_dir: Path | None = None,
        *,
        max_fingerprint_distance: int = DEFAULT_MAX_FINGERPRINT_DISTANCE,
        min_fingerprint_margin: int = DEFAULT_MIN_FINGERPRINT_MARGIN,
    ) -> None:
        self.pack_dir = (pack_dir or default_terrain_pack_dir()).expanduser()
        self.max_fingerprint_distance = max(0, int(max_fingerprint_distance))
        self.min_fingerprint_margin = max(0, int(min_fingerprint_margin))
        self._lock = threading.Lock()
        self._descriptors: tuple[TerrainMapDescriptor, ...] = ()
        self._current_match: TerrainMapMatch | None = None
        self._current_grid: TerrainHeightMap | None = None
        self._load_error = ""
        self.reload()

    @property
    def available(self) -> bool:
        with self._lock:
            return bool(self._descriptors)

    @property
    def load_error(self) -> str:
        with self._lock:
            return self._load_error

    @property
    def current_match(self) -> TerrainMapMatch | None:
        with self._lock:
            return self._current_match

    @property
    def current_altitude_datum_m(self) -> float | None:
        """Return the active map's Dagor-world offset from the 8111 altitude datum."""
        with self._lock:
            grid = self._current_grid
        return float(grid.altitude_datum_m) if grid is not None else None

    def reload(self) -> bool:
        index_path = self.pack_dir / "index.json"
        try:
            if index_path.stat().st_size > MAX_INDEX_BYTES:
                raise TerrainDataError("terrain index is too large")
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise TerrainDataError("terrain index is not an object")
            if payload.get("schema_version") != TERRAIN_PACK_SCHEMA_VERSION:
                raise TerrainDataError("terrain index schema is unsupported")
            raw_maps = payload.get("maps")
            if not isinstance(raw_maps, list):
                raise TerrainDataError("terrain index maps are missing")
            descriptors = tuple(TerrainMapDescriptor.from_json(item) for item in raw_maps)
            if len({item.map_id for item in descriptors}) != len(descriptors):
                raise TerrainDataError("terrain index contains duplicate map ids")
        except (OSError, json.JSONDecodeError, TerrainDataError) as exc:
            with self._lock:
                self._descriptors = ()
                self._current_match = None
                self._current_grid = None
                self._load_error = str(exc)
            return False
        with self._lock:
            self._descriptors = descriptors
            self._current_match = None
            self._current_grid = None
            self._load_error = ""
        return bool(descriptors)

    def identify_map(
        self,
        image_bytes: bytes,
        *,
        map_min: Any = None,
        map_max: Any = None,
    ) -> TerrainMapMatch | None:
        try:
            fingerprint = image_dhash(image_bytes)
        except TerrainDataError:
            return None
        with self._lock:
            descriptors = self._descriptors
        if map_min is not None and map_max is not None:
            descriptors = tuple(
                item for item in descriptors if item.matches_map_bounds(map_min, map_max)
            )
        ranked = sorted(
            ((fingerprint_distance(fingerprint, item.fingerprint), item) for item in descriptors),
            key=lambda entry: (entry[0], entry[1].map_id),
        )
        if not ranked or ranked[0][0] > self.max_fingerprint_distance:
            return None
        best_distance, best = ranked[0]
        second_distance = ranked[1][0] if len(ranked) > 1 else None
        margin = second_distance - best_distance if second_distance is not None else None
        if margin is not None and margin < self.min_fingerprint_margin:
            ambiguous = tuple(
                item
                for distance, item in ranked
                if distance - best_distance < self.min_fingerprint_margin
            )
            if len({item.terrain_sha256 for item in ambiguous}) != 1:
                return None
        return TerrainMapMatch(map_id=best.map_id, distance=best_distance, margin=margin)

    def update_map_image(
        self,
        image_bytes: bytes,
        *,
        map_min: Any = None,
        map_max: Any = None,
    ) -> TerrainMapMatch | None:
        match = self.identify_map(image_bytes, map_min=map_min, map_max=map_max)
        if match is None:
            with self._lock:
                self._current_match = None
                self._current_grid = None
            return None
        with self._lock:
            current = self._current_match
            if current is not None and current.map_id == match.map_id and self._current_grid:
                self._current_match = match
                return match
            descriptor = next(
                (item for item in self._descriptors if item.map_id == match.map_id),
                None,
            )
        if descriptor is None:
            return None
        try:
            grid = TerrainHeightMap.load(self.pack_dir / descriptor.file, descriptor)
        except OSError, TerrainDataError:
            with self._lock:
                self._current_match = None
                self._current_grid = None
            return None
        with self._lock:
            self._current_match = match
            self._current_grid = grid
        return match

    def height_at_world(self, world_x: float, world_z: float) -> float | None:
        """Return target altitude in the 8111 datum for a world X/Z point."""
        with self._lock:
            grid = self._current_grid
        return grid.altitude_at(world_x, world_z) if grid is not None else None

    def height_at_normalized(self, x: float, y: float, map_info: Any) -> float | None:
        altitude, _datum = self.altitude_context_at_normalized(x, y, map_info)
        return altitude

    def altitude_context_at_normalized(
        self,
        x: float,
        y: float,
        map_info: Any,
    ) -> tuple[float | None, float | None]:
        """Return target altitude and map datum from one active-grid snapshot."""
        if map_info is None or not getattr(map_info, "valid", False):
            return None, None
        world = normalized_map_to_world(x, y, map_info.map_min, map_info.map_max)
        if world is None:
            return None, None
        with self._lock:
            grid = self._current_grid
        if grid is None:
            return None, None
        return grid.altitude_at(*world), float(grid.altitude_datum_m)
