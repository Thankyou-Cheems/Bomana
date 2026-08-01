"""Download-cache path selection and artifact naming for the launcher."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse


def unique_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve(strict=False)).casefold()
        except Exception:
            key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


def download_dir_candidates(
    base: Path,
    *,
    env_root: str,
    user_downloads_dir: Callable[[], Path],
    launcher_data_root: Callable[[Path], Path],
    temp_root: Path,
    base_path_key: Callable[[Path], str],
    download_dir_name: str,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.append(user_downloads_dir())
    with suppress(Exception):
        candidates.append(launcher_data_root(base) / download_dir_name)
    candidates.append(temp_root / "Bomana" / download_dir_name / base_path_key(base))
    return unique_paths(tuple(candidates))


def launcher_download_dir(
    base: Path,
    *,
    candidates: Callable[[Path], tuple[Path, ...]],
    can_write_dir: Callable[[Path], bool],
) -> Path:
    attempted: list[str] = []
    for candidate in candidates(base):
        attempted.append(str(candidate))
        if can_write_dir(candidate):
            return candidate
    detail = "；".join(attempted) if attempted else "无可用候选目录"
    raise RuntimeError(f"无法创建可写下载目录。已尝试：{detail}")


def download_cache_filename(
    prefix: str,
    remote_version: str,
    artifact_name: str,
    checksum: str,
    suffix: str,
    *,
    sha256_bytes: Callable[[bytes], str],
) -> str:
    name_seed = str(artifact_name or "").strip() or str(remote_version or "").strip()
    stem = Path(urlparse(name_seed).path).stem or str(remote_version or "").strip() or "download"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "download"
    digest_part = (
        str(checksum or "").strip().lower()[:12] or sha256_bytes(name_seed.encode("utf-8"))[:12]
    )
    return f"{prefix}_{safe_stem}_{digest_part}{suffix}"
