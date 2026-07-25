"""Pinned terrain source-archive validation for independent release builds."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parent.parent
TERRAIN_RELEASE_SPEC_PATH: Final = ROOT / "tools" / "release_assets" / "terrain-v1.json"
DEFAULT_TERRAIN_PACK_DIR: Final = ROOT / "build" / "terrain-offline-balanced" / "terrain-v1"
MAX_TERRAIN_METADATA_BYTES: Final = 4 * 1024 * 1024
MAX_TERRAIN_ARCHIVE_BYTES: Final = 256 * 1024 * 1024
MAX_TERRAIN_EXTRACTED_BYTES: Final = 256 * 1024 * 1024
TERRAIN_PACK_DOCUMENTATION_FILES: Final = frozenset({"INSTALL.txt"})
LOCAL_PATH_METADATA_FIELDS: Final = frozenset({"game_root", "level_config_dir"})
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
PACK_ID_RE: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class TerrainReleaseError(RuntimeError):
    """Raised when the pinned terrain source release is missing or invalid."""


@dataclass(frozen=True, slots=True)
class TerrainReleaseSpec:
    schema_version: int
    pack_id: str
    archive_asset: str
    archive_sha256: str
    archive_size_bytes: int
    archive_root: str
    map_count: int
    package_prefix: str
    download_urls: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _load_bounded_json(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TerrainReleaseError(f"terrain metadata is unavailable: {path}") from exc
    if size <= 0 or size > MAX_TERRAIN_METADATA_BYTES:
        raise TerrainReleaseError(f"terrain metadata size is invalid: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerrainReleaseError(f"terrain metadata is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise TerrainReleaseError(f"terrain metadata is not an object: {path}")
    return payload


def _safe_filename(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    candidate = PurePosixPath(text)
    if (
        not text
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.name != text
        or text in {".", ".."}
    ):
        raise TerrainReleaseError(f"{field} must be a safe filename")
    return text


def _safe_relative_path(value: object, *, field: str) -> PurePosixPath:
    text = str(value or "").strip().replace("\\", "/")
    candidate = PurePosixPath(text)
    if (
        not text
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise TerrainReleaseError(f"{field} must be a safe relative path")
    return candidate


def load_terrain_release_spec(
    path: Path = TERRAIN_RELEASE_SPEC_PATH,
) -> TerrainReleaseSpec:
    payload = _load_bounded_json(path)
    try:
        schema_version = int(payload["schema_version"])
        pack_id = str(payload["pack_id"]).strip()
        archive_asset = _safe_filename(payload["archive_asset"], field="archive_asset")
        archive_sha256 = str(payload["archive_sha256"]).strip().lower()
        archive_size_bytes = int(payload["archive_size_bytes"])
        archive_root = _safe_filename(payload["archive_root"], field="archive_root")
        map_count = int(payload["map_count"])
        package_prefix = _safe_relative_path(
            payload["package_prefix"],
            field="package_prefix",
        ).as_posix()
        raw_urls = payload["download_urls"]
    except (KeyError, TypeError, ValueError) as exc:
        raise TerrainReleaseError("terrain release spec fields are invalid") from exc
    if schema_version != 1:
        raise TerrainReleaseError("terrain release spec schema is unsupported")
    if not PACK_ID_RE.fullmatch(pack_id):
        raise TerrainReleaseError("terrain pack_id is invalid")
    if not SHA256_RE.fullmatch(archive_sha256):
        raise TerrainReleaseError("terrain archive_sha256 is invalid")
    if not 0 < archive_size_bytes <= MAX_TERRAIN_ARCHIVE_BYTES:
        raise TerrainReleaseError("terrain archive_size_bytes is invalid")
    if map_count <= 0:
        raise TerrainReleaseError("terrain map_count must be positive")
    if not isinstance(raw_urls, list):
        raise TerrainReleaseError("terrain download_urls must be a list")
    download_urls = tuple(str(value).strip() for value in raw_urls if str(value).strip())
    if not download_urls or any(
        not value.startswith("https://") or value.rsplit("/", 1)[-1] != archive_asset
        for value in download_urls
    ):
        raise TerrainReleaseError("terrain download_urls must be pinned HTTPS asset URLs")
    return TerrainReleaseSpec(
        schema_version=schema_version,
        pack_id=pack_id,
        archive_asset=archive_asset,
        archive_sha256=archive_sha256,
        archive_size_bytes=archive_size_bytes,
        archive_root=archive_root,
        map_count=map_count,
        package_prefix=package_prefix,
        download_urls=download_urls,
    )


def validate_terrain_archive(
    archive_path: Path,
    spec: TerrainReleaseSpec | None = None,
) -> dict[str, int | str]:
    resolved_spec = spec or load_terrain_release_spec()
    try:
        archive_size = archive_path.stat().st_size
    except OSError as exc:
        raise TerrainReleaseError(f"terrain archive is unavailable: {archive_path}") from exc
    if archive_size != resolved_spec.archive_size_bytes:
        raise TerrainReleaseError(
            f"terrain archive size mismatch: {archive_size} != {resolved_spec.archive_size_bytes}"
        )
    archive_sha256 = sha256_file(archive_path)
    if archive_sha256 != resolved_spec.archive_sha256:
        raise TerrainReleaseError("terrain archive SHA-256 mismatch")

    expected_root = f"{resolved_spec.archive_root}/"
    extracted_bytes = 0
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for entry in archive.infolist():
                name = entry.filename.replace("\\", "/")
                candidate = _safe_relative_path(name.rstrip("/"), field="terrain archive entry")
                if not name.startswith(expected_root) or candidate.as_posix() in seen:
                    raise TerrainReleaseError("terrain archive layout is invalid")
                seen.add(candidate.as_posix())
                if entry.is_dir():
                    continue
                if entry.file_size < 0:
                    raise TerrainReleaseError("terrain archive entry size is invalid")
                extracted_bytes += entry.file_size
                if extracted_bytes > MAX_TERRAIN_EXTRACTED_BYTES:
                    raise TerrainReleaseError("terrain archive extracted size exceeds limit")
    except (OSError, zipfile.BadZipFile) as exc:
        raise TerrainReleaseError("terrain archive is invalid") from exc
    for required in ("index.json", "manifest.json"):
        if f"{resolved_spec.archive_root}/{required}" not in seen:
            raise TerrainReleaseError(f"terrain archive is missing {required}")
    return {
        "pack_id": resolved_spec.pack_id,
        "archive_size_bytes": archive_size,
        "archive_sha256": archive_sha256,
        "extracted_size_bytes": extracted_bytes,
    }


def validate_terrain_pack(
    pack_dir: Path,
    spec: TerrainReleaseSpec | None = None,
    *,
    _allow_local_path_metadata: bool = False,
) -> dict[str, int | str]:
    resolved_spec = spec or load_terrain_release_spec()
    index = _load_bounded_json(pack_dir / "index.json")
    manifest = _load_bounded_json(pack_dir / "manifest.json")
    if not _allow_local_path_metadata and LOCAL_PATH_METADATA_FIELDS.intersection(index):
        raise TerrainReleaseError("terrain index contains local path metadata")
    raw_maps = index.get("maps")
    raw_files = manifest.get("files")
    if index.get("schema_version") != 1 or not isinstance(raw_maps, list):
        raise TerrainReleaseError("terrain index schema is invalid")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "bomana-terrain-offline-pack"
        or not isinstance(raw_files, list)
    ):
        raise TerrainReleaseError("terrain build manifest schema is invalid")
    if len(raw_maps) != resolved_spec.map_count or manifest.get("maps") != resolved_spec.map_count:
        raise TerrainReleaseError("terrain map count does not match the pinned release")

    indexed_files: set[str] = set()
    for item in raw_maps:
        if not isinstance(item, dict):
            raise TerrainReleaseError("terrain index map entry is invalid")
        indexed_files.add(_safe_filename(item.get("file"), field="terrain map file"))
    if len(indexed_files) != resolved_spec.map_count:
        raise TerrainReleaseError("terrain index map files are incomplete or duplicated")

    manifest_files: set[str] = set()
    total_grid_bytes = 0
    for item in raw_files:
        if not isinstance(item, dict):
            raise TerrainReleaseError("terrain manifest file entry is invalid")
        filename = _safe_filename(item.get("path"), field="terrain manifest file")
        try:
            expected_bytes = int(item["bytes"])
            expected_sha256 = str(item["sha256"]).strip().lower()
        except (KeyError, TypeError, ValueError) as exc:
            raise TerrainReleaseError("terrain manifest file metadata is invalid") from exc
        if (
            filename in manifest_files
            or expected_bytes <= 0
            or not SHA256_RE.fullmatch(expected_sha256)
        ):
            raise TerrainReleaseError("terrain manifest file metadata is invalid")
        path = pack_dir / filename
        try:
            actual_bytes = path.stat().st_size
        except OSError as exc:
            raise TerrainReleaseError(f"terrain grid is unavailable: {filename}") from exc
        if actual_bytes != expected_bytes or sha256_file(path) != expected_sha256:
            raise TerrainReleaseError(f"terrain grid integrity mismatch: {filename}")
        manifest_files.add(filename)
        if filename != "index.json":
            total_grid_bytes += actual_bytes

    if manifest_files != indexed_files | {"index.json"}:
        raise TerrainReleaseError("terrain index and build manifest file sets differ")
    if int(manifest.get("output_grid_bytes") or -1) != total_grid_bytes:
        raise TerrainReleaseError("terrain build manifest byte total is invalid")
    actual_files: set[str] = set()
    try:
        pack_entries = tuple(pack_dir.iterdir())
    except OSError as exc:
        raise TerrainReleaseError(f"terrain pack is unavailable: {pack_dir}") from exc
    for path in pack_entries:
        if path.is_symlink() or not path.is_file():
            raise TerrainReleaseError(f"terrain pack contains an unsupported entry: {path.name}")
        actual_files.add(path.name)
    required_files = manifest_files | {"manifest.json"}
    if not required_files.issubset(actual_files) or not (actual_files - required_files).issubset(
        TERRAIN_PACK_DOCUMENTATION_FILES
    ):
        raise TerrainReleaseError("terrain pack contains missing or unexpected files")
    return {
        "pack_id": resolved_spec.pack_id,
        "map_count": resolved_spec.map_count,
        "grid_size_bytes": total_grid_bytes,
        "archive_sha256": resolved_spec.archive_sha256,
    }


def sanitize_terrain_pack_metadata(
    pack_dir: Path,
    spec: TerrainReleaseSpec | None = None,
) -> bool:
    """Remove maintainer-local paths while preserving the pack's internal hashes."""
    resolved_spec = spec or load_terrain_release_spec()
    validate_terrain_pack(
        pack_dir,
        resolved_spec,
        _allow_local_path_metadata=True,
    )
    index_path = pack_dir / "index.json"
    manifest_path = pack_dir / "manifest.json"
    index = _load_bounded_json(index_path)
    removed = LOCAL_PATH_METADATA_FIELDS.intersection(index)
    if not removed:
        return False
    for field in LOCAL_PATH_METADATA_FIELDS:
        index.pop(field, None)
    index_bytes = json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"

    manifest = _load_bounded_json(manifest_path)
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise TerrainReleaseError("terrain build manifest schema is invalid")
    index_item = next(
        (
            item
            for item in raw_files
            if isinstance(item, dict) and item.get("path") == "index.json"
        ),
        None,
    )
    if index_item is None:
        raise TerrainReleaseError("terrain build manifest is missing index.json")
    index_item["bytes"] = len(index_bytes)
    index_item["sha256"] = hashlib.sha256(index_bytes).hexdigest()
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )

    index_temp = index_path.with_name(f".{index_path.name}.sanitize")
    manifest_temp = manifest_path.with_name(f".{manifest_path.name}.sanitize")
    try:
        index_temp.write_bytes(index_bytes)
        manifest_temp.write_bytes(manifest_bytes)
        os.replace(index_temp, index_path)
        os.replace(manifest_temp, manifest_path)
    finally:
        index_temp.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)
    validate_terrain_pack(pack_dir, resolved_spec)
    return True


def extract_terrain_archive(
    archive_path: Path,
    output_dir: Path,
    spec: TerrainReleaseSpec | None = None,
) -> dict[str, int | str]:
    resolved_spec = spec or load_terrain_release_spec()
    validate_terrain_archive(archive_path, resolved_spec)
    if output_dir.exists():
        sanitize_terrain_pack_metadata(output_dir, resolved_spec)
        return validate_terrain_pack(output_dir, resolved_spec)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="bomana_terrain_extract_",
        dir=output_dir.parent,
    ) as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                archive.extractall(temp_dir)
        except (OSError, zipfile.BadZipFile) as exc:
            raise TerrainReleaseError("failed to extract terrain archive") from exc
        extracted_root = temp_dir / resolved_spec.archive_root
        sanitize_terrain_pack_metadata(extracted_root, resolved_spec)
        summary = validate_terrain_pack(extracted_root, resolved_spec)
        shutil.move(str(extracted_root), str(output_dir))
    return summary


__all__ = [
    "DEFAULT_TERRAIN_PACK_DIR",
    "TERRAIN_PACK_DOCUMENTATION_FILES",
    "TERRAIN_RELEASE_SPEC_PATH",
    "TerrainReleaseError",
    "TerrainReleaseSpec",
    "extract_terrain_archive",
    "load_terrain_release_spec",
    "sanitize_terrain_pack_metadata",
    "sha256_file",
    "validate_terrain_archive",
    "validate_terrain_pack",
]
