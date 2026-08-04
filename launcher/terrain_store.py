"""Content-addressed terrain resource storage for the portable launcher."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Any, Final

TERRAIN_SCHEMA_VERSION: Final = 1
TERRAIN_DATA_DIR_NAME: Final = "terrain"
TERRAIN_MANIFEST_ASSET: Final = "terrain_manifest.json"
TERRAIN_OBJECT_ASSET_PREFIX: Final = "Bomana_terrain_object_"
TERRAIN_CURRENT_FILE_NAME: Final = "current.json"
TERRAIN_SELECTION_FILE_NAME: Final = "selection.json"
TERRAIN_LOCK_FILE_NAME: Final = ".terrain_update.lock"
TERRAIN_LOCK_STALE_SEC: Final = 30 * 60
TERRAIN_PARTIALS_DIR_NAME: Final = "partials"
TERRAIN_CATALOGS_DIR_NAME: Final = "catalogs"
TERRAIN_CATALOG_SCHEMA_VERSION: Final = 2
TERRAIN_SELECTION_SCHEMA_VERSION: Final = 1
TERRAIN_CATALOG_POINTER_SCHEMA_VERSION: Final = 1
TERRAIN_CATALOG_POINTER_KIND: Final = "terrain_catalog"
TERRAIN_DOWNLOAD_WORKERS: Final = 4
TERRAIN_READY: Final = "terrain_ready"
TERRAIN_DEGRADED_STARTUP: Final = "terrain_degraded"
TERRAIN_ACCURACY_NOTICE: Final = (
    "地形数据不完整或不兼容，投弹引导可能不可用或不准确；建议下载完整地形数据包。"
)
MAX_TERRAIN_FILES: Final = 1024
MAX_TERRAIN_FILE_BYTES: Final = 128 * 1024 * 1024
MAX_TERRAIN_TOTAL_BYTES: Final = 512 * 1024 * 1024
MAX_TERRAIN_STATE_BYTES: Final = 2 * 1024 * 1024
MAX_TERRAIN_MAP_DISPLAY_NAME_CHARS: Final = 128
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
PACK_ID_RE: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PACK_DIR_RE: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}-[0-9a-f]{20}$")
ASSET_RE: Final = re.compile(rf"^{TERRAIN_OBJECT_ASSET_PREFIX}[0-9a-f]{{64}}(?:[.][a-z0-9]+)?$")
CATALOG_PACK_DIR_RE: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}-[0-9a-f]{20}-[0-9a-f]{12}$")

StatusCallback = Callable[[str, str, float | None, str], None]
CancelCallback = Callable[[], bool]
ObjectProgressCallback = Callable[[int, int | None], None]
ObjectFetcher = Callable[["TerrainFile", Path, ObjectProgressCallback], str]


class TerrainStoreError(RuntimeError):
    """Raised when a terrain manifest or local store violates its contract."""


class _TerrainAppHostActivated(RuntimeError):
    """Internal control flow used to preserve a resumable partial download."""


@dataclass(frozen=True, slots=True)
class TerrainFile:
    path: str
    asset: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class TerrainManifest:
    schema_version: int
    pack_id: str
    revision: str
    map_count: int
    total_size_bytes: int
    files: tuple[TerrainFile, ...]


@dataclass(frozen=True, slots=True)
class TerrainMap:
    """One stable map identity inside a common Terrain Catalog revision."""

    map_id: str
    files: tuple[TerrainFile, ...]
    display_name_zh: str = ""


@dataclass(frozen=True, slots=True)
class TerrainCatalog:
    """Trusted v2 map-selectable catalog, after contract-layer verification."""

    schema_version: int
    catalog_id: str
    revision: str
    min_runtime_contract_version: int
    shared_files: tuple[TerrainFile, ...]
    maps: tuple[TerrainMap, ...]


@dataclass(frozen=True, slots=True)
class TerrainSyncPlan:
    current: bool
    local_revision: str
    remote_revision: str
    download_files: tuple[TerrainFile, ...]
    seed_files: tuple[TerrainFile, ...]
    cached_files: tuple[TerrainFile, ...]
    bytes_to_download: int
    bytes_to_reuse: int


@dataclass(frozen=True, slots=True)
class TerrainSyncResult:
    pack_dir: Path
    revision: str
    downloaded_bytes: int
    downloaded_objects: int
    reused_objects: int
    already_current: bool
    source_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerrainCatalogSyncResult:
    """Outcome of selected-map maintenance without changing startup authority."""

    status: str
    pack_dir: Path | None
    revision: str
    selected_map_ids: tuple[str, ...]
    downloaded_bytes: int
    downloaded_objects: int
    reused_objects: int
    source_names: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class TerrainMapProgress:
    """Byte-precise readiness for one map in a catalog revision."""

    map_id: str
    selected: bool
    completed_bytes: int
    total_bytes: int
    complete: bool


MapProgressCallback = Callable[[tuple[TerrainMapProgress, ...]], None]


@dataclass(frozen=True, slots=True)
class TerrainCatalogHandoff:
    """Secret-free, map-aware terrain data prepared for a future runtime adapter."""

    status: str
    reason: str
    can_start: bool
    complete: bool
    catalog_revision: str
    catalog_root: Path | None
    selected_map_ids: tuple[str, ...]
    available_maps: tuple[str, ...]
    unavailable_maps: tuple[str, ...]
    notice: str


@dataclass(frozen=True, slots=True)
class TerrainAvailability:
    """Verified terrain coverage for one candidate revision."""

    revision: str
    complete: bool
    available_maps: tuple[str, ...]
    unavailable_maps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerrainStartupState:
    """Non-blocking terrain state for an Enhanced launch surface."""

    status: str
    reason: str
    can_start: bool
    terrain_ready: bool
    download_recommended: bool
    notice: str
    available_maps: tuple[str, ...]
    unavailable_maps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerrainPruneResult:
    """Diagnostic-only result of deferred obsolete-terrain cleanup."""

    revision: str
    removed_objects: int
    removed_packs: int
    removed_partial_revisions: int
    diagnostics: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _safe_pack_filename(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    candidate = PurePosixPath(text)
    if (
        not text
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.name != text
        or text in {".", ".."}
    ):
        raise TerrainStoreError(f"{field} must be a safe filename")
    return text


def terrain_revision(
    pack_id: str,
    map_count: int,
    files: Iterable[TerrainFile],
) -> str:
    payload = {
        "terrain_pack_id": pack_id,
        "map_count": map_count,
        "files": [
            {
                "path": item.path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in sorted(files, key=lambda entry: entry.path)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def terrain_catalog_revision(
    catalog_id: str,
    min_runtime_contract_version: int,
    shared_files: Iterable[TerrainFile],
    maps: Iterable[TerrainMap],
) -> str:
    """Return the revision that binds one catalog's map/object membership."""

    payload = {
        "terrain_catalog_id": catalog_id,
        "min_runtime_contract_version": min_runtime_contract_version,
        "shared_files": [
            {
                "path": item.path,
                "asset": item.asset,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in sorted(shared_files, key=lambda entry: entry.path)
        ],
        "maps": [
            _terrain_map_payload(terrain_map)
            for terrain_map in sorted(maps, key=lambda entry: entry.map_id)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _terrain_map_payload(terrain_map: TerrainMap) -> dict[str, Any]:
    """Render the signed map fields while preserving old no-name revisions."""

    payload: dict[str, Any] = {
        "map_id": terrain_map.map_id,
        "files": [
            {
                "path": item.path,
                "asset": item.asset,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in sorted(terrain_map.files, key=lambda entry: entry.path)
        ],
    }
    if terrain_map.display_name_zh:
        payload["display_name_zh"] = terrain_map.display_name_zh
    return payload


def _parse_catalog_file(raw: object, *, paths: set[str], sizes: dict[str, int]) -> TerrainFile:
    if not isinstance(raw, Mapping) or set(raw) != {"path", "asset", "sha256", "size_bytes"}:
        raise TerrainStoreError("terrain catalog file entry is invalid")
    path = _safe_pack_filename(raw.get("path"), field="terrain catalog file path")
    asset = _safe_pack_filename(raw.get("asset"), field="terrain catalog object asset")
    sha256 = str(raw.get("sha256") or "").strip().lower()
    try:
        size_bytes = int(raw["size_bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TerrainStoreError("terrain catalog object size is invalid") from exc
    if path in paths or not SHA256_RE.fullmatch(sha256):
        raise TerrainStoreError("terrain catalog contains a duplicate or invalid file")
    if not ASSET_RE.fullmatch(asset) or sha256 not in asset:
        raise TerrainStoreError("terrain catalog object asset does not match its content hash")
    if not 0 < size_bytes <= MAX_TERRAIN_FILE_BYTES:
        raise TerrainStoreError("terrain catalog object size is out of range")
    previous_size = sizes.setdefault(sha256, size_bytes)
    if previous_size != size_bytes:
        raise TerrainStoreError("terrain catalog object hash has conflicting sizes")
    paths.add(path)
    return TerrainFile(
        path=path,
        asset=asset,
        sha256=sha256,
        size_bytes=size_bytes,
    )


def parse_terrain_catalog(payload: Mapping[str, Any]) -> TerrainCatalog:
    """Parse the explicit v2 catalog shape after its signature has been verified.

    The old flat terrain manifest remains a separate v1 type so callers cannot
    accidentally treat a transitional document as map-selectable delivery.
    """

    expected_fields = {
        "schema_version",
        "terrain_catalog_id",
        "terrain_revision",
        "min_runtime_contract_version",
        "shared_files",
        "maps",
    }
    if set(payload) != expected_fields:
        raise TerrainStoreError("terrain catalog fields are invalid")
    try:
        schema_version = int(payload["schema_version"])
        catalog_id = str(payload["terrain_catalog_id"]).strip()
        revision = str(payload["terrain_revision"]).strip().lower()
        min_runtime_contract_version = int(payload["min_runtime_contract_version"])
        raw_shared_files = payload["shared_files"]
        raw_maps = payload["maps"]
    except (KeyError, TypeError, ValueError) as exc:
        raise TerrainStoreError("terrain catalog fields are invalid") from exc
    if schema_version != TERRAIN_CATALOG_SCHEMA_VERSION:
        raise TerrainStoreError("terrain catalog schema is unsupported")
    if not PACK_ID_RE.fullmatch(catalog_id):
        raise TerrainStoreError("terrain catalog id is invalid")
    if not SHA256_RE.fullmatch(revision):
        raise TerrainStoreError("terrain catalog revision is invalid")
    if min_runtime_contract_version < 1:
        raise TerrainStoreError("terrain catalog runtime contract is invalid")
    if not isinstance(raw_shared_files, list) or not raw_shared_files:
        raise TerrainStoreError("terrain catalog shared files are invalid")
    if not isinstance(raw_maps, list) or not 0 < len(raw_maps) < MAX_TERRAIN_FILES:
        raise TerrainStoreError("terrain catalog maps are invalid")

    paths: set[str] = set()
    sizes: dict[str, int] = {}
    shared_files = tuple(
        sorted(
            (_parse_catalog_file(raw, paths=paths, sizes=sizes) for raw in raw_shared_files),
            key=lambda item: item.path,
        )
    )
    if not {"index.json", "manifest.json"}.issubset(item.path for item in shared_files):
        raise TerrainStoreError("terrain catalog is missing runtime metadata")

    maps: list[TerrainMap] = []
    map_ids: set[str] = set()
    for raw_map in raw_maps:
        if not isinstance(raw_map, Mapping) or set(raw_map) not in (
            {"map_id", "files"},
            {"map_id", "files", "display_name_zh"},
        ):
            raise TerrainStoreError("terrain catalog map entry is invalid")
        map_id = str(raw_map.get("map_id") or "").strip()
        raw_files = raw_map.get("files")
        raw_display_name = raw_map.get("display_name_zh", "")
        if not PACK_ID_RE.fullmatch(map_id) or map_id in map_ids:
            raise TerrainStoreError("terrain catalog map id is invalid")
        if not isinstance(raw_display_name, str):
            raise TerrainStoreError("terrain catalog map display name is invalid")
        display_name_zh = raw_display_name.strip()
        if len(display_name_zh) > MAX_TERRAIN_MAP_DISPLAY_NAME_CHARS:
            raise TerrainStoreError("terrain catalog map display name is too long")
        if any(ord(character) < 32 or ord(character) == 127 for character in display_name_zh):
            raise TerrainStoreError("terrain catalog map display name contains control characters")
        if not isinstance(raw_files, list) or not raw_files:
            raise TerrainStoreError("terrain catalog map files are invalid")
        files = tuple(
            sorted(
                (_parse_catalog_file(raw, paths=paths, sizes=sizes) for raw in raw_files),
                key=lambda item: item.path,
            )
        )
        maps.append(
            TerrainMap(
                map_id=map_id,
                files=files,
                display_name_zh=display_name_zh,
            )
        )
        map_ids.add(map_id)

    maps_tuple = tuple(sorted(maps, key=lambda item: item.map_id))
    total_files = len(shared_files) + sum(len(terrain_map.files) for terrain_map in maps_tuple)
    total_bytes = sum(item.size_bytes for item in shared_files) + sum(
        item.size_bytes for terrain_map in maps_tuple for item in terrain_map.files
    )
    if total_files > MAX_TERRAIN_FILES or total_bytes > MAX_TERRAIN_TOTAL_BYTES:
        raise TerrainStoreError("terrain catalog exceeds local limits")
    if (
        terrain_catalog_revision(
            catalog_id,
            min_runtime_contract_version,
            shared_files,
            maps_tuple,
        )
        != revision
    ):
        raise TerrainStoreError("terrain catalog revision does not match its map set")
    return TerrainCatalog(
        schema_version=schema_version,
        catalog_id=catalog_id,
        revision=revision,
        min_runtime_contract_version=min_runtime_contract_version,
        shared_files=shared_files,
        maps=maps_tuple,
    )


def terrain_catalog_payload(catalog: TerrainCatalog) -> dict[str, Any]:
    """Render the catalog bytes retained by a local active-catalog pointer."""

    return {
        "schema_version": catalog.schema_version,
        "terrain_catalog_id": catalog.catalog_id,
        "terrain_revision": catalog.revision,
        "min_runtime_contract_version": catalog.min_runtime_contract_version,
        "shared_files": [
            {
                "path": item.path,
                "asset": item.asset,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in catalog.shared_files
        ],
        "maps": [_terrain_map_payload(terrain_map) for terrain_map in catalog.maps],
    }


def parse_terrain_manifest(payload: dict[str, Any]) -> TerrainManifest:
    try:
        schema_version = int(payload["schema_version"])
        pack_id = str(payload["terrain_pack_id"]).strip()
        revision = str(payload["terrain_revision"]).strip().lower()
        map_count = int(payload["map_count"])
        total_size_bytes = int(payload["total_size_bytes"])
        raw_files = payload["files"]
    except (KeyError, TypeError, ValueError) as exc:
        raise TerrainStoreError("terrain manifest fields are invalid") from exc
    if schema_version != TERRAIN_SCHEMA_VERSION:
        raise TerrainStoreError("terrain manifest schema is unsupported")
    if not PACK_ID_RE.fullmatch(pack_id):
        raise TerrainStoreError("terrain manifest pack id is invalid")
    if not SHA256_RE.fullmatch(revision):
        raise TerrainStoreError("terrain manifest revision is invalid")
    if not 0 < map_count < MAX_TERRAIN_FILES:
        raise TerrainStoreError("terrain manifest map count is invalid")
    if not isinstance(raw_files, list) or not 2 < len(raw_files) <= MAX_TERRAIN_FILES:
        raise TerrainStoreError("terrain manifest file list is invalid")

    parsed: list[TerrainFile] = []
    seen_paths: set[str] = set()
    object_sizes: dict[str, int] = {}
    for raw in raw_files:
        if not isinstance(raw, dict) or set(raw) != {
            "path",
            "asset",
            "sha256",
            "size_bytes",
        }:
            raise TerrainStoreError("terrain manifest file entry is invalid")
        path = _safe_pack_filename(raw.get("path"), field="terrain file path")
        asset = _safe_pack_filename(raw.get("asset"), field="terrain object asset")
        sha256 = str(raw.get("sha256") or "").strip().lower()
        try:
            size_bytes = int(raw["size_bytes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TerrainStoreError("terrain object size is invalid") from exc
        if path in seen_paths or not SHA256_RE.fullmatch(sha256):
            raise TerrainStoreError("terrain manifest contains a duplicate or invalid file")
        if not ASSET_RE.fullmatch(asset) or sha256 not in asset:
            raise TerrainStoreError("terrain object asset does not match its content hash")
        if not 0 < size_bytes <= MAX_TERRAIN_FILE_BYTES:
            raise TerrainStoreError("terrain object size is out of range")
        previous_size = object_sizes.setdefault(sha256, size_bytes)
        if previous_size != size_bytes:
            raise TerrainStoreError("terrain object hash has conflicting sizes")
        parsed.append(
            TerrainFile(
                path=path,
                asset=asset,
                sha256=sha256,
                size_bytes=size_bytes,
            )
        )
        seen_paths.add(path)

    required_metadata = {"index.json", "manifest.json"}
    if not required_metadata.issubset(seen_paths):
        raise TerrainStoreError("terrain manifest is missing runtime metadata")
    if sum(item.path.endswith(".bth") for item in parsed) != map_count:
        raise TerrainStoreError("terrain manifest map files do not match map count")
    computed_total = sum(item.size_bytes for item in parsed)
    if total_size_bytes != computed_total or not 0 < computed_total <= MAX_TERRAIN_TOTAL_BYTES:
        raise TerrainStoreError("terrain manifest total size is invalid")
    files = tuple(sorted(parsed, key=lambda item: item.path))
    if terrain_revision(pack_id, map_count, files) != revision:
        raise TerrainStoreError("terrain manifest revision does not match its file set")
    return TerrainManifest(
        schema_version=schema_version,
        pack_id=pack_id,
        revision=revision,
        map_count=map_count,
        total_size_bytes=total_size_bytes,
        files=files,
    )


def terrain_manifest_payload(manifest: TerrainManifest) -> dict[str, Any]:
    return {
        "schema_version": manifest.schema_version,
        "terrain_pack_id": manifest.pack_id,
        "terrain_revision": manifest.revision,
        "map_count": manifest.map_count,
        "total_size_bytes": manifest.total_size_bytes,
        "files": [
            {
                "path": item.path,
                "asset": item.asset,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in manifest.files
        ],
    }


def terrain_store_root(launcher_data_root: Path) -> Path:
    return launcher_data_root / TERRAIN_DATA_DIR_NAME


def _valid_file(path: Path, item: TerrainFile) -> bool:
    try:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == item.size_bytes
            and sha256_file(path) == item.sha256
        )
    except OSError:
        return False


class TerrainStore:
    """Owns immutable terrain objects and atomically selected runtime packs."""

    def __init__(self, launcher_data_root: Path) -> None:
        self.root = terrain_store_root(launcher_data_root)
        self.objects_dir = self.root / "objects"
        self.packs_dir = self.root / "packs"
        self.catalogs_dir = self.root / TERRAIN_CATALOGS_DIR_NAME
        self.partials_dir = self.root / TERRAIN_PARTIALS_DIR_NAME
        self.current_path = self.root / TERRAIN_CURRENT_FILE_NAME
        self.selection_path = self.root / TERRAIN_SELECTION_FILE_NAME
        self.lock_path = self.root / TERRAIN_LOCK_FILE_NAME

    def _object_path(self, item: TerrainFile) -> Path:
        return self.objects_dir / item.sha256

    def _pack_name(self, manifest: TerrainManifest) -> str:
        return f"{manifest.pack_id}-{manifest.revision[:20]}"

    def _pack_path(self, manifest: TerrainManifest) -> Path:
        return self.packs_dir / self._pack_name(manifest)

    def _partial_path(
        self,
        manifest: TerrainManifest | TerrainCatalog,
        item: TerrainFile,
    ) -> Path:
        return self.partials_dir / manifest.revision / f"{item.sha256}.part"

    @staticmethod
    def _catalog_map_ids(catalog: TerrainCatalog) -> tuple[str, ...]:
        return tuple(terrain_map.map_id for terrain_map in catalog.maps)

    @staticmethod
    def _catalog_selection_hash(selected_map_ids: Iterable[str]) -> str:
        encoded = json.dumps(
            sorted(selected_map_ids),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:12]

    @staticmethod
    def _catalog_files(
        catalog: TerrainCatalog,
        selected_map_ids: Iterable[str],
    ) -> tuple[TerrainFile, ...]:
        selected = frozenset(selected_map_ids)
        files = list(catalog.shared_files)
        for terrain_map in catalog.maps:
            if terrain_map.map_id in selected:
                files.extend(terrain_map.files)
        return tuple(sorted(files, key=lambda item: item.path))

    def _catalog_pack_name(
        self,
        catalog: TerrainCatalog,
        selected_map_ids: Iterable[str],
    ) -> str:
        return (
            f"{catalog.catalog_id}-{catalog.revision[:20]}-"
            f"{self._catalog_selection_hash(selected_map_ids)}"
        )

    def _catalog_pack_path(
        self,
        catalog: TerrainCatalog,
        selected_map_ids: Iterable[str],
    ) -> Path:
        return self.catalogs_dir / self._catalog_pack_name(catalog, selected_map_ids)

    def _read_current_payload(self) -> dict[str, Any] | None:
        try:
            if not self.current_path.is_file():
                return None
            size = self.current_path.stat().st_size
            if size <= 0 or size > MAX_TERRAIN_STATE_BYTES:
                return None
            payload = json.loads(self.current_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except OSError, UnicodeDecodeError, json.JSONDecodeError:
            return None

    def _read_selection(self) -> tuple[str, tuple[str, ...]]:
        try:
            if not self.selection_path.is_file():
                return "", ()
            if self.selection_path.stat().st_size > MAX_TERRAIN_STATE_BYTES:
                return "", ()
            payload = json.loads(self.selection_path.read_text(encoding="utf-8"))
        except OSError, UnicodeDecodeError, json.JSONDecodeError:
            return "", ()
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "terrain_catalog_id",
            "map_ids",
        }:
            return "", ()
        if payload.get("schema_version") != TERRAIN_SELECTION_SCHEMA_VERSION:
            return "", ()
        catalog_id = str(payload.get("terrain_catalog_id") or "").strip()
        raw_map_ids = payload.get("map_ids")
        if not PACK_ID_RE.fullmatch(catalog_id) or not isinstance(raw_map_ids, list):
            return "", ()
        map_ids = tuple(sorted({str(item).strip() for item in raw_map_ids}))
        if len(map_ids) != len(raw_map_ids) or any(
            not PACK_ID_RE.fullmatch(item) for item in map_ids
        ):
            return "", ()
        return catalog_id, map_ids

    def _write_selection(self, catalog_id: str, map_ids: tuple[str, ...]) -> None:
        payload = {
            "schema_version": TERRAIN_SELECTION_SCHEMA_VERSION,
            "terrain_catalog_id": catalog_id,
            "map_ids": list(map_ids),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.selection_path.with_name(f".{self.selection_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as file_obj:
                json.dump(payload, file_obj, ensure_ascii=False, indent=2)
                file_obj.write("\n")
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temp, self.selection_path)
        finally:
            temp.unlink(missing_ok=True)

    def selected_map_ids(self, catalog: TerrainCatalog | None = None) -> tuple[str, ...]:
        """Return durable desired state without triggering a terrain transfer."""

        catalog_id, map_ids = self._read_selection()
        if catalog is None:
            return map_ids
        if catalog_id != catalog.catalog_id:
            return ()
        supported = frozenset(self._catalog_map_ids(catalog))
        return tuple(map_id for map_id in map_ids if map_id in supported)

    def has_map_selection(self, catalog: TerrainCatalog | None = None) -> bool:
        """Return whether the user has initialized selection for ``catalog``.

        An initialized empty tuple is meaningful: it represents an explicit
        deselection, so callers must not treat it as a first-visit state.
        """

        catalog_id, _map_ids = self._read_selection()
        if not catalog_id:
            return False
        return catalog is None or catalog_id == catalog.catalog_id

    def set_map_selection(
        self,
        catalog: TerrainCatalog,
        map_ids: Iterable[str],
    ) -> tuple[str, ...]:
        """Persist an explicit desired map set; transfer remains a separate action."""

        selected = tuple(sorted({str(map_id).strip() for map_id in map_ids}))
        supported = frozenset(self._catalog_map_ids(catalog))
        if any(map_id not in supported for map_id in selected):
            raise TerrainStoreError("terrain selection contains an unknown map")
        self._write_selection(catalog.catalog_id, selected)
        return selected

    def select_all_maps(self, catalog: TerrainCatalog) -> tuple[str, ...]:
        """Persist every current catalog map as the durable desired set."""

        return self.set_map_selection(catalog, self._catalog_map_ids(catalog))

    @staticmethod
    def _catalog_map_dependencies(
        catalog: TerrainCatalog,
    ) -> dict[str, tuple[TerrainFile, ...]]:
        dependencies: dict[str, tuple[TerrainFile, ...]] = {}
        for terrain_map in catalog.maps:
            unique: dict[str, TerrainFile] = {item.sha256: item for item in catalog.shared_files}
            for item in terrain_map.files:
                unique.setdefault(item.sha256, item)
            dependencies[terrain_map.map_id] = tuple(unique.values())
        return dependencies

    def catalog_map_progress(
        self,
        catalog: TerrainCatalog,
        selected_map_ids: Iterable[str] | None = None,
    ) -> tuple[TerrainMapProgress, ...]:
        """Read one map-level progress snapshot from verified objects and partials."""

        selected = frozenset(
            self.selected_map_ids(catalog)
            if selected_map_ids is None
            else (str(value).strip() for value in selected_map_ids)
        )
        dependencies = self._catalog_map_dependencies(catalog)
        unique_objects = self._unique_objects(
            item for values in dependencies.values() for item in values
        )
        completed_hashes = {
            item.sha256 for item in unique_objects if _valid_file(self._object_path(item), item)
        }
        partial_bytes: dict[str, int] = {}
        for item in unique_objects:
            if item.sha256 in completed_hashes:
                continue
            partial = self._partial_path(catalog, item)
            try:
                size = (
                    partial.stat().st_size if partial.is_file() and not partial.is_symlink() else 0
                )
            except OSError:
                size = 0
            partial_bytes[item.sha256] = max(0, min(item.size_bytes, size))
        return tuple(
            TerrainMapProgress(
                map_id=map_id,
                selected=map_id in selected,
                completed_bytes=sum(
                    item.size_bytes
                    if item.sha256 in completed_hashes
                    else partial_bytes.get(item.sha256, 0)
                    for item in items
                ),
                total_bytes=sum(item.size_bytes for item in items),
                complete=all(item.sha256 in completed_hashes for item in items),
            )
            for map_id, items in dependencies.items()
        )

    def _catalog_pointer_from_current(
        self,
    ) -> tuple[TerrainCatalog, tuple[str, ...], Path] | None:
        payload = self._read_current_payload()
        if payload is None or set(payload) != {
            "pointer_schema_version",
            "kind",
            "catalog",
            "selected_map_ids",
            "pack_dir",
        }:
            return None
        if (
            payload.get("pointer_schema_version") != TERRAIN_CATALOG_POINTER_SCHEMA_VERSION
            or payload.get("kind") != TERRAIN_CATALOG_POINTER_KIND
            or not isinstance(payload.get("catalog"), dict)
            or not isinstance(payload.get("selected_map_ids"), list)
        ):
            return None
        try:
            catalog = parse_terrain_catalog(payload["catalog"])
        except TerrainStoreError:
            return None
        selected_map_ids = tuple(
            sorted({str(item).strip() for item in payload["selected_map_ids"]})
        )
        supported = frozenset(self._catalog_map_ids(catalog))
        if len(selected_map_ids) != len(payload["selected_map_ids"]) or any(
            map_id not in supported for map_id in selected_map_ids
        ):
            return None
        pack_name = str(payload.get("pack_dir") or "").strip()
        if not CATALOG_PACK_DIR_RE.fullmatch(pack_name):
            return None
        return catalog, selected_map_ids, self.catalogs_dir / pack_name

    def _validate_catalog_pack(
        self,
        catalog: TerrainCatalog,
        selected_map_ids: Iterable[str],
        pack_dir: Path,
    ) -> bool:
        try:
            return (
                pack_dir.parent == self.catalogs_dir
                and not pack_dir.is_symlink()
                and pack_dir.is_dir()
                and all(
                    _valid_file(pack_dir / item.path, item)
                    for item in self._catalog_files(catalog, selected_map_ids)
                )
            )
        except OSError:
            return False

    def current_catalog(self) -> TerrainCatalog | None:
        """Return the active v2 Catalog only when its selected pack verifies."""

        pointer = self._catalog_pointer_from_current()
        if pointer is None:
            return None
        catalog, selected_map_ids, pack_dir = pointer
        if not self._validate_catalog_pack(catalog, selected_map_ids, pack_dir):
            return None
        return catalog

    def current_catalog_selection(self) -> tuple[str, ...]:
        pointer = self._catalog_pointer_from_current()
        if pointer is None:
            return ()
        catalog, selected_map_ids, pack_dir = pointer
        if not self._validate_catalog_pack(catalog, selected_map_ids, pack_dir):
            return ()
        return selected_map_ids

    def current_catalog_pack_dir(self) -> Path | None:
        pointer = self._catalog_pointer_from_current()
        if pointer is None:
            return None
        catalog, selected_map_ids, pack_dir = pointer
        return (
            pack_dir if self._validate_catalog_pack(catalog, selected_map_ids, pack_dir) else None
        )

    def catalog_handoff(
        self,
        catalog: TerrainCatalog,
        *,
        terrain_compatible: bool = True,
    ) -> TerrainCatalogHandoff:
        """Prepare non-secret per-map availability without making terrain a startup gate.

        This value intentionally stays local to the terrain adapter.  A runtime
        handoff receives only an active, verified catalog path plus map IDs; it
        never needs receipts, object URLs, signing material, or transfer state.
        """

        all_map_ids = self._catalog_map_ids(catalog)
        selected_map_ids = self.selected_map_ids(catalog)
        if not terrain_compatible:
            return TerrainCatalogHandoff(
                status=TERRAIN_DEGRADED_STARTUP,
                reason="incompatible",
                can_start=True,
                complete=False,
                catalog_revision=catalog.revision,
                catalog_root=None,
                selected_map_ids=selected_map_ids,
                available_maps=(),
                unavailable_maps=all_map_ids,
                notice=TERRAIN_ACCURACY_NOTICE,
            )
        pointer = self._catalog_pointer_from_current()
        if pointer is None:
            return TerrainCatalogHandoff(
                status=TERRAIN_DEGRADED_STARTUP,
                reason="missing",
                can_start=True,
                complete=False,
                catalog_revision=catalog.revision,
                catalog_root=None,
                selected_map_ids=selected_map_ids,
                available_maps=(),
                unavailable_maps=all_map_ids,
                notice=TERRAIN_ACCURACY_NOTICE,
            )
        active_catalog, active_selection, pack_dir = pointer
        if active_catalog.catalog_id != catalog.catalog_id or not self._validate_catalog_pack(
            active_catalog, active_selection, pack_dir
        ):
            return TerrainCatalogHandoff(
                status=TERRAIN_DEGRADED_STARTUP,
                reason="inactive",
                can_start=True,
                complete=False,
                catalog_revision=catalog.revision,
                catalog_root=None,
                selected_map_ids=selected_map_ids,
                available_maps=(),
                unavailable_maps=all_map_ids,
                notice=TERRAIN_ACCURACY_NOTICE,
            )
        active_map_ids = self._catalog_map_ids(active_catalog)
        available_maps = active_selection
        unavailable_maps = tuple(
            map_id for map_id in active_map_ids if map_id not in active_selection
        )
        complete = not unavailable_maps
        previous_revision = active_catalog.revision != catalog.revision
        return TerrainCatalogHandoff(
            status=TERRAIN_READY if complete else TERRAIN_DEGRADED_STARTUP,
            reason=(
                "previous_revision"
                if previous_revision
                else ("ready" if complete else "incomplete")
            ),
            can_start=True,
            complete=complete,
            catalog_revision=active_catalog.revision,
            catalog_root=pack_dir,
            selected_map_ids=active_selection,
            available_maps=available_maps,
            unavailable_maps=unavailable_maps,
            notice="" if complete else TERRAIN_ACCURACY_NOTICE,
        )

    def _manifest_from_current(self) -> TerrainManifest | None:
        payload = self._read_current_payload()
        if payload is None:
            return None
        try:
            manifest = parse_terrain_manifest(payload)
            if payload.get("pack_dir") != self._pack_name(manifest):
                return None
            return manifest
        except TerrainStoreError:
            return None

    def _validate_pack(self, manifest: TerrainManifest) -> bool:
        pack_dir = self._pack_path(manifest)
        return pack_dir.is_dir() and all(
            _valid_file(pack_dir / item.path, item) for item in manifest.files
        )

    def current_pack_dir(self) -> Path | None:
        manifest = self.current_manifest()
        if manifest is None:
            return None
        return self._pack_path(manifest)

    def current_manifest(self) -> TerrainManifest | None:
        """Return the selected manifest only when every pack object still verifies."""

        manifest = self._manifest_from_current()
        if manifest is None or not self._validate_pack(manifest):
            return None
        return manifest

    def current_revision(self) -> str:
        manifest = self.current_manifest()
        return manifest.revision if manifest is not None else ""

    def availability(self, manifest: TerrainManifest | None) -> TerrainAvailability:
        """Return hash-verified object coverage without activating or downloading."""

        if manifest is None:
            return TerrainAvailability(
                revision="",
                complete=False,
                available_maps=(),
                unavailable_maps=(),
            )
        verified = {
            item.sha256: _valid_file(self._object_path(item), item) for item in manifest.files
        }
        metadata_ready = all(
            verified[item.sha256]
            for item in manifest.files
            if item.path in {"index.json", "manifest.json"}
        )
        available_maps: list[str] = []
        unavailable_maps: list[str] = []
        for item in manifest.files:
            if not item.path.endswith(".bth"):
                continue
            map_id = Path(item.path).stem
            if metadata_ready and verified[item.sha256]:
                available_maps.append(map_id)
            else:
                unavailable_maps.append(map_id)
        return TerrainAvailability(
            revision=manifest.revision,
            complete=all(verified.values()),
            available_maps=tuple(available_maps),
            unavailable_maps=tuple(unavailable_maps),
        )

    def startup_state(
        self,
        manifest: TerrainManifest | None,
        *,
        terrain_compatible: bool = True,
    ) -> TerrainStartupState:
        """Describe terrain readiness while always preserving Enhanced startup."""

        availability = self.availability(manifest)
        active_manifest = self.current_manifest()
        active_revision = active_manifest.revision if active_manifest is not None else ""
        terrain_ready = bool(
            terrain_compatible
            and manifest is not None
            and availability.complete
            and active_revision == manifest.revision
        )
        if terrain_ready:
            return TerrainStartupState(
                status=TERRAIN_READY,
                reason="ready",
                can_start=True,
                terrain_ready=True,
                download_recommended=False,
                notice="",
                available_maps=availability.available_maps,
                unavailable_maps=availability.unavailable_maps,
            )
        if not terrain_compatible:
            reason = "incompatible"
        elif manifest is None:
            reason = "missing"
        elif availability.complete:
            reason = "inactive"
        else:
            reason = "incomplete"
        return TerrainStartupState(
            status=TERRAIN_DEGRADED_STARTUP,
            reason=reason,
            can_start=True,
            terrain_ready=False,
            download_recommended=True,
            notice=TERRAIN_ACCURACY_NOTICE,
            available_maps=availability.available_maps,
            unavailable_maps=availability.unavailable_maps,
        )

    @staticmethod
    def _find_seed(item: TerrainFile, seed_dirs: Iterable[Path]) -> Path | None:
        for seed_dir in seed_dirs:
            candidate = seed_dir / item.path
            if _valid_file(candidate, item):
                return candidate
        return None

    @staticmethod
    def _unique_objects(files: Iterable[TerrainFile]) -> tuple[TerrainFile, ...]:
        objects: dict[str, TerrainFile] = {}
        for item in files:
            objects.setdefault(item.sha256, item)
        return tuple(sorted(objects.values(), key=lambda item: item.path))

    def plan(
        self,
        manifest: TerrainManifest,
        *,
        seed_dirs: Iterable[Path] = (),
    ) -> TerrainSyncPlan:
        local_manifest = self._manifest_from_current()
        local_revision = local_manifest.revision if local_manifest is not None else ""
        if (
            local_manifest is not None
            and local_manifest.revision == manifest.revision
            and self._validate_pack(manifest)
        ):
            return TerrainSyncPlan(
                current=True,
                local_revision=local_revision,
                remote_revision=manifest.revision,
                download_files=(),
                seed_files=(),
                cached_files=self._unique_objects(manifest.files),
                bytes_to_download=0,
                bytes_to_reuse=manifest.total_size_bytes,
            )

        cached: list[TerrainFile] = []
        seeded: list[TerrainFile] = []
        downloads: list[TerrainFile] = []
        seeds = tuple(seed_dirs)
        for item in self._unique_objects(manifest.files):
            if _valid_file(self._object_path(item), item):
                cached.append(item)
            elif self._find_seed(item, seeds) is not None:
                seeded.append(item)
            else:
                downloads.append(item)
        bytes_to_download = sum(item.size_bytes for item in downloads)
        unique_total = sum(item.size_bytes for item in self._unique_objects(manifest.files))
        return TerrainSyncPlan(
            current=False,
            local_revision=local_revision,
            remote_revision=manifest.revision,
            download_files=tuple(downloads),
            seed_files=tuple(seeded),
            cached_files=tuple(cached),
            bytes_to_download=bytes_to_download,
            bytes_to_reuse=unique_total - bytes_to_download,
        )

    def _acquire_lock(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            if self.lock_path.exists():
                age = time.time() - self.lock_path.stat().st_mtime
                if age >= TERRAIN_LOCK_STALE_SEC:
                    self.lock_path.unlink()
        except OSError:
            pass
        try:
            descriptor = os.open(
                str(self.lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise TerrainStoreError("检测到另一个地形更新任务正在进行，请稍后重试。") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_obj:
            file_obj.write(f"pid={os.getpid()}\n")

    def _release_lock(self) -> None:
        with suppress(OSError):
            self.lock_path.unlink()

    def _install_seed_object(
        self,
        item: TerrainFile,
        seed_dirs: Iterable[Path],
    ) -> bool:
        seed = self._find_seed(item, seed_dirs)
        if seed is None:
            return False
        destination = self._object_path(item)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{item.sha256}.{uuid.uuid4().hex}.seed")
        try:
            try:
                os.link(seed, temp)
            except OSError:
                shutil.copyfile(seed, temp)
            if not _valid_file(temp, item):
                raise TerrainStoreError(f"复用的地形对象校验失败: {item.path}")
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
        return True

    def _download_object(
        self,
        manifest: TerrainManifest | TerrainCatalog,
        item: TerrainFile,
        fetch_object: ObjectFetcher,
        progress_cb: ObjectProgressCallback,
    ) -> str:
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        destination = self._object_path(item)
        partial = self._partial_path(manifest, item)
        partial.parent.mkdir(parents=True, exist_ok=True)
        try:
            if partial.is_symlink() or (partial.exists() and not partial.is_file()):
                raise TerrainStoreError(f"地形断点文件无效: {item.path}")
            if partial.exists() and partial.stat().st_size > item.size_bytes:
                partial.unlink()
        except OSError as exc:
            raise TerrainStoreError(f"无法准备地形断点文件: {item.path}") from exc
        if _valid_file(partial, item):
            os.replace(partial, destination)
            return ""
        source_name = fetch_object(item, partial, progress_cb)
        if not _valid_file(partial, item):
            raise TerrainStoreError(f"下载的地形对象校验失败: {item.path}")
        os.replace(partial, destination)
        return str(source_name or "").strip()

    def _remaining_download_bytes(
        self,
        manifest: TerrainManifest | TerrainCatalog,
        item: TerrainFile,
    ) -> int:
        """Return additional bytes needed without counting a retained prefix twice."""

        partial = self._partial_path(manifest, item)
        try:
            if partial.is_symlink() or not partial.is_file():
                return item.size_bytes
            partial_size = partial.stat().st_size
        except OSError:
            return item.size_bytes
        if partial_size <= 0:
            return item.size_bytes
        if partial_size >= item.size_bytes:
            return 0 if _valid_file(partial, item) else item.size_bytes
        return item.size_bytes - partial_size

    def _assemble_pack(self, manifest: TerrainManifest) -> Path:
        self.packs_dir.mkdir(parents=True, exist_ok=True)
        target = self._pack_path(manifest)
        if self._validate_pack(manifest):
            return target
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        stage = self.packs_dir / f".{self._pack_name(manifest)}.{uuid.uuid4().hex}.new"
        stage.mkdir(parents=False, exist_ok=False)
        try:
            for item in manifest.files:
                source = self._object_path(item)
                if not _valid_file(source, item):
                    raise TerrainStoreError(f"地形对象在组装前失效: {item.path}")
                destination = stage / item.path
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copyfile(source, destination)
            if not all(_valid_file(stage / item.path, item) for item in manifest.files):
                raise TerrainStoreError("组装后的地形包完整性校验失败")
            os.replace(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
        return target

    def _write_current(self, manifest: TerrainManifest) -> None:
        payload = terrain_manifest_payload(manifest)
        payload["pack_dir"] = self._pack_name(manifest)
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.current_path.with_name(f".{self.current_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as file_obj:
                json.dump(payload, file_obj, ensure_ascii=False, indent=2)
                file_obj.write("\n")
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temp, self.current_path)
        finally:
            temp.unlink(missing_ok=True)

    def _assemble_catalog_pack(
        self,
        catalog: TerrainCatalog,
        selected_map_ids: tuple[str, ...],
    ) -> Path:
        files = self._catalog_files(catalog, selected_map_ids)
        self.catalogs_dir.mkdir(parents=True, exist_ok=True)
        target = self._catalog_pack_path(catalog, selected_map_ids)
        if self._validate_catalog_pack(catalog, selected_map_ids, target):
            return target
        if target.exists():
            target = self.catalogs_dir / (
                f"{catalog.catalog_id}-{catalog.revision[:20]}-{uuid.uuid4().hex[:12]}"
            )
        stage = self.catalogs_dir / f".{target.name}.{uuid.uuid4().hex}.new"
        stage.mkdir(parents=False, exist_ok=False)
        try:
            for item in files:
                source = self._object_path(item)
                if not _valid_file(source, item):
                    raise TerrainStoreError(
                        f"terrain object failed before catalog activation: {item.path}"
                    )
                destination = stage / item.path
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copyfile(source, destination)
            if not all(_valid_file(stage / item.path, item) for item in files):
                raise TerrainStoreError("assembled terrain catalog is invalid")
            os.replace(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
        return target

    def _write_current_catalog(
        self,
        catalog: TerrainCatalog,
        selected_map_ids: tuple[str, ...],
        pack_dir: Path,
    ) -> None:
        payload = {
            "pointer_schema_version": TERRAIN_CATALOG_POINTER_SCHEMA_VERSION,
            "kind": TERRAIN_CATALOG_POINTER_KIND,
            "catalog": terrain_catalog_payload(catalog),
            "selected_map_ids": list(selected_map_ids),
            "pack_dir": pack_dir.name,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.current_path.with_name(f".{self.current_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as file_obj:
                json.dump(payload, file_obj, ensure_ascii=False, indent=2)
                file_obj.write("\n")
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temp, self.current_path)
        finally:
            temp.unlink(missing_ok=True)

    def sync_catalog(
        self,
        catalog: TerrainCatalog,
        *,
        fetch_object: ObjectFetcher,
        app_host_active: Callable[[], bool] | None = None,
        disk_free_bytes: Callable[[Path], int] | None = None,
        map_progress_cb: MapProgressCallback | None = None,
        max_workers: int = TERRAIN_DOWNLOAD_WORKERS,
    ) -> TerrainCatalogSyncResult:
        """Stage selected-map objects and atomically point at the verified catalog."""

        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise TerrainStoreError("地形下载并发数无效")
        self._acquire_lock()
        try:
            active_pack_dir = self.current_catalog_pack_dir()
            source_names: list[str] = []
            downloaded_objects: dict[str, TerrainFile] = {}
            map_dependencies = self._catalog_map_dependencies(catalog)
            all_catalog_objects = self._unique_objects(
                item for values in map_dependencies.values() for item in values
            )
            completed_hashes = {
                item.sha256
                for item in all_catalog_objects
                if _valid_file(self._object_path(item), item)
            }
            progress_bytes: dict[str, int] = {}
            for item in all_catalog_objects:
                if item.sha256 in completed_hashes:
                    continue
                partial = self._partial_path(catalog, item)
                try:
                    size = (
                        partial.stat().st_size
                        if partial.is_file() and not partial.is_symlink()
                        else 0
                    )
                except OSError:
                    size = 0
                progress_bytes[item.sha256] = max(0, min(item.size_bytes, size))
            progress_lock = Lock()

            def emit_map_progress(selected_map_ids: tuple[str, ...]) -> None:
                if map_progress_cb is None:
                    return
                selected_set = frozenset(selected_map_ids)
                with progress_lock:
                    snapshot = tuple(
                        TerrainMapProgress(
                            map_id=map_id,
                            selected=map_id in selected_set,
                            completed_bytes=sum(
                                item.size_bytes
                                if item.sha256 in completed_hashes
                                else progress_bytes.get(item.sha256, 0)
                                for item in items
                            ),
                            total_bytes=sum(item.size_bytes for item in items),
                            complete=all(item.sha256 in completed_hashes for item in items),
                        )
                        for map_id, items in map_dependencies.items()
                    )
                    map_progress_cb(snapshot)

            def paused(
                status: str,
                selected_map_ids: tuple[str, ...],
                message: str,
            ) -> TerrainCatalogSyncResult:
                return TerrainCatalogSyncResult(
                    status=status,
                    pack_dir=active_pack_dir,
                    revision=catalog.revision,
                    selected_map_ids=selected_map_ids,
                    downloaded_bytes=sum(item.size_bytes for item in downloaded_objects.values()),
                    downloaded_objects=len(downloaded_objects),
                    reused_objects=0,
                    source_names=tuple(sorted(set(source_names))),
                    message=message,
                )

            while True:
                selected_map_ids = self.selected_map_ids(catalog)
                emit_map_progress(selected_map_ids)
                if app_host_active is not None and app_host_active():
                    return paused(
                        "paused_app_host",
                        selected_map_ids,
                        "应用正在运行，地形维护已暂停；请在应用结束后重试。",
                    )
                pointer = self._catalog_pointer_from_current()
                if (
                    pointer is not None
                    and pointer[0].revision == catalog.revision
                    and pointer[1] == selected_map_ids
                    and self._validate_catalog_pack(catalog, selected_map_ids, pointer[2])
                ):
                    files = self._catalog_files(catalog, selected_map_ids)
                    return TerrainCatalogSyncResult(
                        status="already_current",
                        pack_dir=pointer[2],
                        revision=catalog.revision,
                        selected_map_ids=selected_map_ids,
                        downloaded_bytes=sum(
                            item.size_bytes for item in downloaded_objects.values()
                        ),
                        downloaded_objects=len(downloaded_objects),
                        reused_objects=len(self._unique_objects(files)),
                        source_names=tuple(sorted(set(source_names))),
                        message="选中的地形地图已经是最新版本。",
                    )

                files = self._catalog_files(catalog, selected_map_ids)
                download_files = tuple(
                    item
                    for item in self._unique_objects(files)
                    if not _valid_file(self._object_path(item), item)
                )
                if not download_files:
                    if self.selected_map_ids(catalog) != selected_map_ids:
                        continue
                    if app_host_active is not None and app_host_active():
                        return paused(
                            "paused_app_host",
                            selected_map_ids,
                            "应用正在运行，地形维护已暂停；请在应用结束后重试。",
                        )
                    try:
                        pack_dir = self._assemble_catalog_pack(catalog, selected_map_ids)
                    except OSError as exc:
                        if exc.errno != errno.ENOSPC and getattr(exc, "winerror", None) != 112:
                            raise
                        return paused(
                            "paused_insufficient_disk",
                            selected_map_ids,
                            "可用存储空间不足，地形维护已暂停；请释放存储空间后重试。",
                        )
                    if self.selected_map_ids(catalog) != selected_map_ids:
                        continue
                    if app_host_active is not None and app_host_active():
                        return paused(
                            "paused_app_host",
                            selected_map_ids,
                            "应用正在运行，地形维护已暂停；请在应用结束后重试。",
                        )
                    try:
                        self._write_current_catalog(catalog, selected_map_ids, pack_dir)
                    except OSError as exc:
                        if exc.errno != errno.ENOSPC and getattr(exc, "winerror", None) != 112:
                            raise
                        return paused(
                            "paused_insufficient_disk",
                            selected_map_ids,
                            "可用存储空间不足，地形维护已暂停；请释放存储空间后重试。",
                        )
                    return TerrainCatalogSyncResult(
                        status="activated",
                        pack_dir=pack_dir,
                        revision=catalog.revision,
                        selected_map_ids=selected_map_ids,
                        downloaded_bytes=sum(
                            item.size_bytes for item in downloaded_objects.values()
                        ),
                        downloaded_objects=len(downloaded_objects),
                        reused_objects=len(self._unique_objects(files))
                        - len({item.sha256 for item in files} & set(downloaded_objects)),
                        source_names=tuple(sorted(set(source_names))),
                        message="选中的地形地图已完成验证并原子启用。",
                    )

                required_bytes = sum(
                    self._remaining_download_bytes(catalog, item) for item in download_files
                )
                available_bytes = (
                    disk_free_bytes(self.root)
                    if disk_free_bytes is not None
                    else shutil.disk_usage(self.root).free
                )
                if available_bytes < required_bytes:
                    return paused(
                        "paused_insufficient_disk",
                        selected_map_ids,
                        "可用存储空间不足，地形维护已暂停；请释放存储空间后重试。",
                    )
                try:
                    shared_hashes = {item.sha256 for item in catalog.shared_files}
                    missing_shared = tuple(
                        item for item in download_files if item.sha256 in shared_hashes
                    )
                    batch_candidates = missing_shared or download_files
                    worker_count = min(
                        max_workers,
                        TERRAIN_DOWNLOAD_WORKERS,
                        len(batch_candidates),
                    )
                    batch = batch_candidates[:worker_count]
                    progress_selection = selected_map_ids

                    def download_one(
                        item: TerrainFile,
                        selection: tuple[str, ...] = progress_selection,
                    ) -> tuple[TerrainFile, str]:
                        def progress(done: int, _total: int | None) -> None:
                            if app_host_active is not None and app_host_active():
                                raise _TerrainAppHostActivated
                            with progress_lock:
                                progress_bytes[item.sha256] = max(
                                    0,
                                    min(item.size_bytes, int(done)),
                                )
                            emit_map_progress(selection)

                        source = self._download_object(
                            catalog,
                            item,
                            fetch_object,
                            progress,
                        )
                        with progress_lock:
                            completed_hashes.add(item.sha256)
                            progress_bytes[item.sha256] = item.size_bytes
                        emit_map_progress(selection)
                        return item, source

                    if worker_count == 1:
                        completed = [download_one(batch[0])]
                    else:
                        completed = []
                        with ThreadPoolExecutor(
                            max_workers=worker_count,
                            thread_name_prefix="bomana-terrain-catalog",
                        ) as executor:
                            futures = [executor.submit(download_one, item) for item in batch]
                            try:
                                for future in as_completed(futures):
                                    completed.append(future.result())
                            except Exception:
                                for future in futures:
                                    future.cancel()
                                raise
                except _TerrainAppHostActivated:
                    return paused(
                        "paused_app_host",
                        selected_map_ids,
                        "应用已经启动，地形维护已暂停；当前断点会在应用结束后续传。",
                    )
                except OSError as exc:
                    if exc.errno != errno.ENOSPC and getattr(exc, "winerror", None) != 112:
                        raise
                    return paused(
                        "paused_insufficient_disk",
                        selected_map_ids,
                        "可用存储空间不足，地形维护已暂停；请释放存储空间后重试。",
                    )
                for item, source in completed:
                    downloaded_objects[item.sha256] = item
                    if source:
                        source_names.append(source)
        finally:
            self._release_lock()

    def sync(
        self,
        manifest: TerrainManifest,
        *,
        fetch_object: ObjectFetcher,
        seed_dirs: Iterable[Path] = (),
        status_cb: StatusCallback | None = None,
        cancel_cb: CancelCallback | None = None,
        max_workers: int = TERRAIN_DOWNLOAD_WORKERS,
    ) -> TerrainSyncResult:
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise TerrainStoreError("地形下载并发数无效")
        seeds = tuple(seed_dirs)
        self._acquire_lock()
        try:
            plan = self.plan(manifest, seed_dirs=seeds)
            if plan.current:
                pack_dir = self._pack_path(manifest)
                if status_cb:
                    status_cb(
                        "地形数据已是最新",
                        f"{manifest.map_count} 张地图均已通过完整性校验，无需下载。",
                        1.0,
                        "success",
                    )
                return TerrainSyncResult(
                    pack_dir=pack_dir,
                    revision=manifest.revision,
                    downloaded_bytes=0,
                    downloaded_objects=0,
                    reused_objects=len(plan.cached_files),
                    already_current=True,
                    source_names=(),
                )

            if cancel_cb and cancel_cb():
                raise TerrainStoreError("已取消当前操作")
            self.objects_dir.mkdir(parents=True, exist_ok=True)
            for index, item in enumerate(plan.seed_files, start=1):
                if cancel_cb and cancel_cb():
                    raise TerrainStoreError("已取消当前操作")
                if status_cb:
                    status_cb(
                        "正在复用已有地形",
                        f"{index}/{len(plan.seed_files)}：{item.path}",
                        None,
                        "info",
                    )
                self._install_seed_object(item, seeds)

            download_files = tuple(
                item
                for item in self._unique_objects(manifest.files)
                if not _valid_file(self._object_path(item), item)
            )
            bytes_to_download = sum(item.size_bytes for item in download_files)
            completed_download_bytes = 0
            source_names: list[str] = []
            progress_lock = Lock()
            progress_by_object: dict[str, int] = {}

            def download_one(index: int, item: TerrainFile) -> tuple[TerrainFile, str]:
                nonlocal completed_download_bytes
                if cancel_cb and cancel_cb():
                    raise TerrainStoreError("已取消当前操作")

                def object_progress(
                    downloaded: int,
                    _total: int | None,
                    *,
                    _item: TerrainFile = item,
                    _index: int = index,
                ) -> None:
                    if not status_cb:
                        return
                    bounded = min(max(int(downloaded), 0), _item.size_bytes)
                    denominator = max(bytes_to_download, 1)
                    with progress_lock:
                        progress_by_object[_item.sha256] = bounded
                        progress = (
                            completed_download_bytes + sum(progress_by_object.values())
                        ) / denominator
                    status_cb(
                        "正在并行更新地形",
                        (
                            f"{_index}/{len(download_files)}：{_item.path}\n"
                            f"本次只需下载 {bytes_to_download} 字节变化对象。"
                        ),
                        min(max(progress, 0.0), 0.92),
                        "info",
                    )

                source = self._download_object(manifest, item, fetch_object, object_progress)
                with progress_lock:
                    progress_by_object.pop(item.sha256, None)
                    completed_download_bytes += item.size_bytes
                return item, source

            worker_count = min(max_workers, TERRAIN_DOWNLOAD_WORKERS, len(download_files))
            completed: list[tuple[TerrainFile, str]] = []
            if worker_count == 1:
                completed = [
                    download_one(index, item) for index, item in enumerate(download_files, start=1)
                ]
            elif worker_count > 1:
                with ThreadPoolExecutor(
                    max_workers=worker_count,
                    thread_name_prefix="bomana-terrain",
                ) as executor:
                    futures = [
                        executor.submit(download_one, index, item)
                        for index, item in enumerate(download_files, start=1)
                    ]
                    try:
                        for future in as_completed(futures):
                            completed.append(future.result())
                    except Exception:
                        for future in futures:
                            future.cancel()
                        raise

            for _item, source in completed:
                if source:
                    source_names.append(source)

            if cancel_cb and cancel_cb():
                raise TerrainStoreError("已取消当前操作")
            if status_cb:
                status_cb(
                    "正在启用地形数据",
                    "正在组装并原子切换新的地形版本...",
                    0.96,
                    "info",
                )
            pack_dir = self._assemble_pack(manifest)
            self._write_current(manifest)
            return TerrainSyncResult(
                pack_dir=pack_dir,
                revision=manifest.revision,
                downloaded_bytes=completed_download_bytes,
                downloaded_objects=len(download_files),
                reused_objects=len(self._unique_objects(manifest.files)) - len(download_files),
                already_current=False,
                source_names=tuple(sorted(set(source_names))),
            )
        finally:
            self._release_lock()

    def prune_after_host_exit(
        self,
        *,
        app_host_active: Callable[[], bool] | None = None,
    ) -> TerrainPruneResult:
        """Remove obsolete revisions after the App host has ended.

        Callers schedule this for a later Launcher start, never while an App
        might still read a terrain pack.  Failure is returned as diagnostics so
        the active revision and a normal Enhanced launch remain unaffected.
        """

        manifest = self.current_manifest()
        catalog_pointer = self._catalog_pointer_from_current()
        active_catalog: TerrainCatalog | None = None
        active_catalog_selection: tuple[str, ...] = ()
        active_catalog_pack_name = ""
        if manifest is not None:
            active_revision = manifest.revision
            active_objects = {item.sha256 for item in manifest.files}
            active_legacy_pack_name = self._pack_name(manifest)
        elif catalog_pointer is not None and self._validate_catalog_pack(
            catalog_pointer[0],
            catalog_pointer[1],
            catalog_pointer[2],
        ):
            active_catalog, active_catalog_selection, active_catalog_pack = catalog_pointer
            active_revision = active_catalog.revision
            active_objects = {
                item.sha256
                for item in self._catalog_files(active_catalog, active_catalog_selection)
            }
            active_legacy_pack_name = ""
            active_catalog_pack_name = active_catalog_pack.name
        else:
            return TerrainPruneResult(
                revision="",
                removed_objects=0,
                removed_packs=0,
                removed_partial_revisions=0,
                diagnostics=("没有可验证的活动地形版本，跳过过期清理。",),
            )
        if app_host_active is not None and app_host_active():
            return TerrainPruneResult(
                revision=active_revision,
                removed_objects=0,
                removed_packs=0,
                removed_partial_revisions=0,
                diagnostics=("应用仍在运行，已延迟清理过期地形。",),
            )
        try:
            self._acquire_lock()
        except TerrainStoreError as exc:
            return TerrainPruneResult(
                revision=active_revision,
                removed_objects=0,
                removed_packs=0,
                removed_partial_revisions=0,
                diagnostics=(str(exc),),
            )
        removed_objects = 0
        removed_packs = 0
        removed_partial_revisions = 0
        diagnostics: list[str] = []
        try:
            try:
                pack_paths = tuple(self.packs_dir.iterdir()) if self.packs_dir.is_dir() else ()
            except OSError as exc:
                diagnostics.append(f"无法枚举过期地形包: {exc}")
                pack_paths = ()
            for path in pack_paths:
                if active_legacy_pack_name and path.name == active_legacy_pack_name:
                    continue
                try:
                    if (
                        path.is_symlink()
                        or not path.is_dir()
                        or not PACK_DIR_RE.fullmatch(path.name)
                    ):
                        diagnostics.append(f"跳过非受管地形包路径: {path.name}")
                        continue
                    shutil.rmtree(path)
                    removed_packs += 1
                except OSError as exc:
                    diagnostics.append(f"无法清理过期地形包 {path.name}: {exc}")

            try:
                catalog_paths = (
                    tuple(self.catalogs_dir.iterdir()) if self.catalogs_dir.is_dir() else ()
                )
            except OSError as exc:
                diagnostics.append(f"无法枚举过期地形目录: {exc}")
                catalog_paths = ()
            for path in catalog_paths:
                if active_catalog_pack_name and path.name == active_catalog_pack_name:
                    continue
                try:
                    if (
                        path.is_symlink()
                        or not path.is_dir()
                        or not CATALOG_PACK_DIR_RE.fullmatch(path.name)
                    ):
                        diagnostics.append(f"跳过非受管地形目录: {path.name}")
                        continue
                    shutil.rmtree(path)
                    removed_packs += 1
                except OSError as exc:
                    diagnostics.append(f"无法清理过期地形目录 {path.name}: {exc}")

            try:
                object_paths = (
                    tuple(self.objects_dir.iterdir()) if self.objects_dir.is_dir() else ()
                )
            except OSError as exc:
                diagnostics.append(f"无法枚举地形对象: {exc}")
                object_paths = ()
            for path in object_paths:
                if path.name in active_objects:
                    continue
                try:
                    if (
                        path.is_symlink()
                        or not path.is_file()
                        or not SHA256_RE.fullmatch(path.name)
                    ):
                        diagnostics.append(f"跳过非受管地形对象路径: {path.name}")
                        continue
                    path.unlink()
                    removed_objects += 1
                except OSError as exc:
                    diagnostics.append(f"无法清理过期地形对象 {path.name}: {exc}")

            try:
                partial_paths = (
                    tuple(self.partials_dir.iterdir()) if self.partials_dir.is_dir() else ()
                )
            except OSError as exc:
                diagnostics.append(f"无法枚举地形断点目录: {exc}")
                partial_paths = ()
            for path in partial_paths:
                if path.name == active_revision:
                    continue
                try:
                    if path.is_symlink() or not path.is_dir() or not SHA256_RE.fullmatch(path.name):
                        diagnostics.append(f"跳过非受管地形断点目录: {path.name}")
                        continue
                    shutil.rmtree(path)
                    removed_partial_revisions += 1
                except OSError as exc:
                    diagnostics.append(f"无法清理过期地形断点目录 {path.name}: {exc}")
        finally:
            self._release_lock()
        return TerrainPruneResult(
            revision=active_revision,
            removed_objects=removed_objects,
            removed_packs=removed_packs,
            removed_partial_revisions=removed_partial_revisions,
            diagnostics=tuple(diagnostics),
        )


__all__ = [
    "ASSET_RE",
    "CATALOG_PACK_DIR_RE",
    "TERRAIN_ACCURACY_NOTICE",
    "TERRAIN_CATALOG_SCHEMA_VERSION",
    "TERRAIN_DEGRADED_STARTUP",
    "TERRAIN_DOWNLOAD_WORKERS",
    "MAX_TERRAIN_TOTAL_BYTES",
    "TERRAIN_MANIFEST_ASSET",
    "TERRAIN_OBJECT_ASSET_PREFIX",
    "TERRAIN_PARTIALS_DIR_NAME",
    "TERRAIN_READY",
    "TERRAIN_SCHEMA_VERSION",
    "TerrainAvailability",
    "TerrainCatalog",
    "TerrainCatalogHandoff",
    "TerrainCatalogSyncResult",
    "TerrainFile",
    "TerrainManifest",
    "TerrainMap",
    "TerrainMapProgress",
    "TerrainPruneResult",
    "TerrainStore",
    "TerrainStoreError",
    "TerrainStartupState",
    "TerrainSyncPlan",
    "TerrainSyncResult",
    "parse_terrain_catalog",
    "parse_terrain_manifest",
    "sha256_file",
    "terrain_catalog_payload",
    "terrain_catalog_revision",
    "terrain_manifest_payload",
    "terrain_revision",
    "terrain_store_root",
]
