"""Pure launcher helpers shared by the portable launcher UI and tests."""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOWNLOAD_SOURCE_MODE_AUTO = ""
DOWNLOAD_SOURCE_MODE_PRIMARY = "primary"
DOWNLOAD_SOURCE_MODE_GITHUB = "github"
DOWNLOAD_SOURCE_CHOICES = (
    (DOWNLOAD_SOURCE_MODE_AUTO, "自动（沿用现有逻辑）"),
    (DOWNLOAD_SOURCE_MODE_PRIMARY, "腾讯云"),
    (DOWNLOAD_SOURCE_MODE_GITHUB, "GitHub"),
)
DOWNLOAD_SOURCE_DETAILS = {
    DOWNLOAD_SOURCE_MODE_AUTO: "默认：优先腾讯云，失败或缺少下载包时再回退 GitHub。",
    DOWNLOAD_SOURCE_MODE_PRIMARY: "仅使用腾讯云更新服务。检查或下载失败时不再自动回退 GitHub。",
    DOWNLOAD_SOURCE_MODE_GITHUB: "仅使用 GitHub Releases。适合手动排查国内更新链路问题。",
}
DOWNLOAD_SOURCE_LABEL_TO_MODE = {label: mode for mode, label in DOWNLOAD_SOURCE_CHOICES}
DOWNLOAD_SOURCE_MODE_TO_LABEL = dict(DOWNLOAD_SOURCE_CHOICES)
LAUNCHER_ASSET_PREFIX = "Bomana_launcher_v"


@dataclass
class LaunchDecision:
    action: str  # "launch" | "exit"
    final_version: str
    warning: str = ""


def normalize_download_source_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("", "auto", "default"):
        return DOWNLOAD_SOURCE_MODE_AUTO
    if raw in ("primary", "tencent", "cn", "domestic"):
        return DOWNLOAD_SOURCE_MODE_PRIMARY
    if raw in ("github", "gh"):
        return DOWNLOAD_SOURCE_MODE_GITHUB
    return DOWNLOAD_SOURCE_MODE_AUTO


def download_source_label(mode: str) -> str:
    normalized = normalize_download_source_mode(mode)
    return DOWNLOAD_SOURCE_MODE_TO_LABEL.get(
        normalized,
        DOWNLOAD_SOURCE_MODE_TO_LABEL[DOWNLOAD_SOURCE_MODE_AUTO],
    )


def format_size_text(num_bytes: int | None) -> str:
    if num_bytes is None or num_bytes < 0:
        return "未知"
    if num_bytes >= 1073741824:
        return f"{num_bytes / 1073741824:.2f} GB"
    if num_bytes >= 1048576:
        return f"{num_bytes / 1048576:.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"


_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?\s*$")


def extract_version_tuple(version: str) -> tuple[int, ...]:
    text = str(version or "").strip()
    match = _VERSION_RE.match(text)
    if match:
        return tuple(int(part) for part in match.groups(default="0"))
    nums = re.findall(r"\d+", text.split("-", 1)[0].split("+", 1)[0])
    if not nums:
        return (0,)
    return tuple(int(x) for x in nums)


def _is_prerelease(version: str) -> bool:
    release_and_prerelease = str(version or "").strip().split("+", 1)[0]
    return "-" in release_and_prerelease


def version_is_newer(remote: str, local: str) -> bool:
    a = extract_version_tuple(remote)
    b = extract_version_tuple(local)
    n = max(len(a), len(b))
    aa = a + (0,) * (n - len(a))
    bb = b + (0,) * (n - len(b))
    if aa != bb:
        return aa > bb
    return (not _is_prerelease(remote)) and _is_prerelease(local)


def version_is_older(current: str, required: str) -> bool:
    return version_is_newer(required, current)


def format_min_launcher_requirement(required_version: str) -> str:
    ver = str(required_version or "").strip()
    return f"启动器 v{ver}+" if ver else "新版启动器"


def find_asset(assets: list, name: str) -> dict[str, Any] | None:
    for asset in assets:
        if str(asset.get("name", "")).lower() == name.lower():
            return asset
    return None


def normalize_package_root(stage_dir: Path, entrypoint: str) -> Path:
    if (stage_dir / entrypoint).exists():
        return stage_dir
    children = [p for p in stage_dir.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / entrypoint).exists():
        return children[0]
    return stage_dir


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().lower()


def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_path = (target_dir / member.filename).resolve()
            if target_root not in [member_path, *list(member_path.parents)]:
                raise RuntimeError("应用包包含非法路径")
        zf.extractall(target_dir)


def require_remote_checksum(checksum_value: str, *, artifact_label: str) -> str:
    checksum = str(checksum_value or "").strip().lower()
    if not checksum:
        raise RuntimeError(f"{artifact_label}缺少 SHA256 校验值")
    return checksum


def join_base_url_path(base_url: str, path: str) -> str:
    if not path:
        return base_url
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"{base_url}{path}"


def parse_launcher_version_from_asset_name(asset_name: str) -> str:
    name = asset_name.strip()
    suffix = ".exe"
    if not name.lower().startswith(LAUNCHER_ASSET_PREFIX.lower()):
        return ""
    if not name.lower().endswith(suffix):
        return ""
    return name[len(LAUNCHER_ASSET_PREFIX) : -len(suffix)].strip()


def find_launcher_asset(assets: list) -> dict[str, Any] | None:
    for asset in assets:
        name = str(asset.get("name", "")).strip()
        if parse_launcher_version_from_asset_name(name):
            return asset
    return None
