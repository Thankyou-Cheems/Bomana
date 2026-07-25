"""Content-addressed terrain resource storage for the portable launcher."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

TERRAIN_SCHEMA_VERSION: Final = 1
TERRAIN_DATA_DIR_NAME: Final = "terrain"
TERRAIN_MANIFEST_ASSET: Final = "terrain_manifest.json"
TERRAIN_OBJECT_ASSET_PREFIX: Final = "Bomana_terrain_object_"
TERRAIN_CURRENT_FILE_NAME: Final = "current.json"
TERRAIN_LOCK_FILE_NAME: Final = ".terrain_update.lock"
TERRAIN_LOCK_STALE_SEC: Final = 30 * 60
MAX_TERRAIN_FILES: Final = 1024
MAX_TERRAIN_FILE_BYTES: Final = 128 * 1024 * 1024
MAX_TERRAIN_TOTAL_BYTES: Final = 512 * 1024 * 1024
MAX_TERRAIN_STATE_BYTES: Final = 2 * 1024 * 1024
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
PACK_ID_RE: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ASSET_RE: Final = re.compile(rf"^{TERRAIN_OBJECT_ASSET_PREFIX}[0-9a-f]{{64}}(?:[.][a-z0-9]+)?$")

StatusCallback = Callable[[str, str, float | None, str], None]
CancelCallback = Callable[[], bool]
ObjectProgressCallback = Callable[[int, int | None], None]
ObjectFetcher = Callable[["TerrainFile", Path, ObjectProgressCallback], str]


class TerrainStoreError(RuntimeError):
    """Raised when a terrain manifest or local store violates its contract."""


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
        self.current_path = self.root / TERRAIN_CURRENT_FILE_NAME
        self.lock_path = self.root / TERRAIN_LOCK_FILE_NAME

    def _object_path(self, item: TerrainFile) -> Path:
        return self.objects_dir / item.sha256

    def _pack_name(self, manifest: TerrainManifest) -> str:
        return f"{manifest.pack_id}-{manifest.revision[:20]}"

    def _pack_path(self, manifest: TerrainManifest) -> Path:
        return self.packs_dir / self._pack_name(manifest)

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
        item: TerrainFile,
        fetch_object: ObjectFetcher,
        progress_cb: ObjectProgressCallback,
    ) -> str:
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        destination = self._object_path(item)
        temp = destination.with_name(f".{item.sha256}.{uuid.uuid4().hex}.download")
        try:
            source_name = fetch_object(item, temp, progress_cb)
            if not _valid_file(temp, item):
                raise TerrainStoreError(f"下载的地形对象校验失败: {item.path}")
            os.replace(temp, destination)
            return str(source_name or "").strip()
        finally:
            temp.unlink(missing_ok=True)
            temp.with_name(f"{temp.name}.part").unlink(missing_ok=True)

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

    def sync(
        self,
        manifest: TerrainManifest,
        *,
        fetch_object: ObjectFetcher,
        seed_dirs: Iterable[Path] = (),
        status_cb: StatusCallback | None = None,
        cancel_cb: CancelCallback | None = None,
    ) -> TerrainSyncResult:
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
            for index, item in enumerate(download_files, start=1):
                if cancel_cb and cancel_cb():
                    raise TerrainStoreError("已取消当前操作")

                def object_progress(
                    downloaded: int,
                    _total: int | None,
                    *,
                    _item: TerrainFile = item,
                    _index: int = index,
                    _completed: int = completed_download_bytes,
                ) -> None:
                    if not status_cb:
                        return
                    bounded = min(max(int(downloaded), 0), _item.size_bytes)
                    denominator = max(bytes_to_download, 1)
                    progress = (_completed + bounded) / denominator
                    status_cb(
                        "正在差量更新地形",
                        (
                            f"{_index}/{len(download_files)}：{_item.path}\n"
                            f"本次只需下载 {bytes_to_download} 字节变化对象。"
                        ),
                        min(max(progress, 0.0), 0.92),
                        "info",
                    )

                source = self._download_object(item, fetch_object, object_progress)
                if source and source not in source_names:
                    source_names.append(source)
                completed_download_bytes += item.size_bytes

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
                source_names=tuple(source_names),
            )
        finally:
            self._release_lock()


__all__ = [
    "ASSET_RE",
    "MAX_TERRAIN_TOTAL_BYTES",
    "TERRAIN_MANIFEST_ASSET",
    "TERRAIN_OBJECT_ASSET_PREFIX",
    "TERRAIN_SCHEMA_VERSION",
    "TerrainFile",
    "TerrainManifest",
    "TerrainStore",
    "TerrainStoreError",
    "TerrainSyncPlan",
    "TerrainSyncResult",
    "parse_terrain_manifest",
    "sha256_file",
    "terrain_manifest_payload",
    "terrain_revision",
    "terrain_store_root",
]
