"""Manifest validation and trusted-field projection for launcher sources."""

from __future__ import annotations

from collections.abc import Callable
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

from launcher.core import (
    _APP_MANIFEST_SIGNATURE_FIELDS,
    _LAUNCHER_MANIFEST_SIGNATURE_FIELDS,
    _TERRAIN_MANIFEST_SIGNATURE_FIELDS,
    parse_launcher_version_from_asset_name,
    require_remote_checksum,
)
from launcher.launch_contract import PUBLIC_CHANNELS, DistributionDescriptor
from launcher.terrain_store import parse_terrain_manifest

from .verify import project_verified_manifest_fields


class ManifestSourceError(RuntimeError):
    """Raised when an external manifest source violates its trust boundary."""


def validate_public_fallback_descriptor(
    descriptor: DistributionDescriptor,
    *,
    url_is_owned: Callable[[str], bool],
) -> None:
    """Allow GitHub fallback metadata to name only public Launcher artifacts.

    The descriptor is expected to have passed signature validation before it
    reaches this policy projection.  The adapter owns the source-specific URL
    allow-list, so the client cannot combine a GitHub descriptor with a URL
    from another service.
    """

    if descriptor.source != "github":
        raise ManifestSourceError("public fallback descriptor must be from GitHub")
    for reference in descriptor.artifacts:
        public_app = reference.kind == "app" and reference.channel in PUBLIC_CHANNELS
        if reference.kind != "launcher" and not public_app:
            raise ManifestSourceError(
                "public fallback descriptor may contain only Launcher, Lite, and Standard"
            )
        validate_public_fallback_url(reference.manifest_url, url_is_owned=url_is_owned)


def validate_public_fallback_url(
    url: str,
    *,
    url_is_owned: Callable[[str], bool],
) -> None:
    """Require one public GitHub fallback URL to pass origin and ownership checks."""

    _require_public_https_endpoint(url)
    try:
        owned = url_is_owned(url)
    except Exception as exc:
        raise ManifestSourceError("public fallback URL ownership validation failed") from exc
    if owned is not True:
        raise ManifestSourceError("public fallback URL does not belong to GitHub")


def _require_public_https_endpoint(url: str) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if parsed.scheme != "https" or not hostname:
        raise ManifestSourceError("public fallback URL is not a public HTTPS endpoint")
    host = hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ManifestSourceError("public fallback URL is not a public HTTPS endpoint")
    try:
        address = ip_address(host)
    except ValueError:
        if ":" in host:
            raise ManifestSourceError(
                "public fallback URL is not a public HTTPS endpoint"
            ) from None
        return
    if not address.is_global:
        raise ManifestSourceError("public fallback URL is not a public HTTPS endpoint")


def validate_app_manifest_channel(
    manifest: dict[str, Any],
    expected_channel: str,
    label: str,
) -> None:
    channel = str(manifest.get("channel", "")).strip()
    if channel != expected_channel:
        raise RuntimeError(f"{label}通道不匹配")


def validate_app_manifest_entrypoint(
    entrypoint_value: Any,
    label: str,
    default: str,
    *,
    channel: str = "",
) -> str:
    entrypoint = str(entrypoint_value or default).strip() or default
    allowed = {default}
    if str(channel).strip() == "Enhanced":
        allowed.add("Bomana.pyc")
    if entrypoint not in allowed:
        raise RuntimeError(f"{label}入口文件不受支持")
    return entrypoint


def verified_app_manifest_fields(
    manifest: dict[str, Any],
    *,
    channel: str,
    label: str,
    default_entrypoint: str,
    public_keys: dict[str, str] | None = None,
) -> dict[str, Any]:
    fields = project_verified_manifest_fields(
        manifest,
        _APP_MANIFEST_SIGNATURE_FIELDS,
        manifest_label=label,
        expected_kind="app",
        public_keys=public_keys,
    )
    validate_app_manifest_channel(fields, channel, label)
    remote_version = str(fields.get("app_version", "")).strip()
    package_asset = str(fields.get("package_asset", "")).strip()
    changelog_asset = str(fields.get("changelog_asset", "")).strip()
    if not remote_version or not package_asset or not changelog_asset:
        raise RuntimeError("发布清单字段缺失")
    return {
        "remote_version": remote_version,
        "min_launcher_version": str(fields.get("min_launcher_version", "")).strip(),
        "package_asset": package_asset,
        "package_sha256": require_remote_checksum(
            fields.get("package_sha256", ""),
            artifact_label=label,
        ),
        "changelog_asset": changelog_asset,
        "changelog_sha256": require_remote_checksum(
            fields.get("changelog_sha256", ""),
            artifact_label=f"{label}更新日志",
        ),
        "entrypoint": validate_app_manifest_entrypoint(
            fields.get("entrypoint", default_entrypoint),
            label,
            default_entrypoint,
            channel=channel,
        ),
    }


def verified_launcher_manifest_fields(
    manifest: dict[str, Any],
    *,
    label: str,
    public_keys: dict[str, str] | None = None,
) -> dict[str, Any]:
    fields = project_verified_manifest_fields(
        manifest,
        _LAUNCHER_MANIFEST_SIGNATURE_FIELDS,
        manifest_label=label,
        expected_kind="launcher",
        public_keys=public_keys,
    )
    remote_version = str(fields.get("launcher_version", "")).strip()
    asset_name = str(fields.get("launcher_asset", "")).strip()
    if not asset_name or not remote_version:
        raise RuntimeError("启动器发布清单字段缺失")
    if parse_launcher_version_from_asset_name(asset_name) != remote_version:
        raise RuntimeError("启动器发布清单版本与资产名不匹配")
    return {
        "remote_version": remote_version,
        "package_asset": asset_name,
        "package_sha256": require_remote_checksum(
            fields.get("launcher_sha256", ""),
            artifact_label=label,
        ),
        "launcher_size_bytes": fields.get("launcher_size_bytes"),
    }


def verified_terrain_manifest_fields(
    manifest: dict[str, Any],
    *,
    label: str,
    public_keys: dict[str, str] | None = None,
) -> dict[str, Any]:
    fields = project_verified_manifest_fields(
        manifest,
        _TERRAIN_MANIFEST_SIGNATURE_FIELDS,
        manifest_label=label,
        expected_kind="terrain",
        public_keys=public_keys,
    )
    parsed = parse_terrain_manifest(fields)
    return {
        "schema_version": parsed.schema_version,
        "terrain_pack_id": parsed.pack_id,
        "terrain_revision": parsed.revision,
        "map_count": parsed.map_count,
        "total_size_bytes": parsed.total_size_bytes,
        "files": [
            {
                "path": item.path,
                "asset": item.asset,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in parsed.files
        ],
    }
