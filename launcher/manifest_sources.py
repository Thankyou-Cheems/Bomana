"""Manifest validation and trusted-field projection for launcher sources."""

from __future__ import annotations

from typing import Any

from launcher.core import (
    _APP_MANIFEST_SIGNATURE_FIELDS,
    _LAUNCHER_MANIFEST_SIGNATURE_FIELDS,
    _TERRAIN_MANIFEST_SIGNATURE_FIELDS,
    parse_launcher_version_from_asset_name,
    require_remote_checksum,
)
from launcher.terrain_store import parse_terrain_manifest

from .verify import project_verified_manifest_fields


def validate_app_manifest_channel(
    manifest: dict[str, Any],
    expected_channel: str,
    label: str,
) -> None:
    channel = str(manifest.get("channel", "")).strip()
    if channel != expected_channel:
        raise RuntimeError(f"{label}通道不匹配")


def validate_app_manifest_entrypoint(entrypoint_value: Any, label: str, default: str) -> str:
    entrypoint = str(entrypoint_value or default).strip() or default
    if entrypoint != default:
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
