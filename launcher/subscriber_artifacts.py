"""Logical private-artifact namespace shared by Launcher update flows.

The module deliberately knows paths, not accounts or filesystem locations.
CheemsPay decides whether a device may access one exact resource, while the
Launcher continues to verify signed manifests and content hashes.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from launcher.subscription_access import normalize_artifact_resource

APP_RELEASE_ROOT = "releases/enhanced"
APP_MANIFEST_RESOURCE = f"{APP_RELEASE_ROOT}/manifest_Enhanced.json"
TERRAIN_ROOT = "terrain"
TERRAIN_MANIFEST_RESOURCE = f"{TERRAIN_ROOT}/terrain_manifest.json"
TERRAIN_OBJECT_ROOT = f"{TERRAIN_ROOT}/objects"


def app_asset_resource(asset_name: str) -> str:
    return _asset_resource(APP_RELEASE_ROOT, asset_name)


def terrain_object_resource(asset_name: str) -> str:
    return _asset_resource(TERRAIN_OBJECT_ROOT, asset_name)


def _asset_resource(root: str, asset_name: str) -> str:
    asset = str(asset_name or "")
    path = PurePosixPath(asset)
    if not asset or path.name != asset or len(path.parts) != 1:
        raise ValueError("subscriber artifact must use a single safe asset name")
    return normalize_artifact_resource(f"{root}/{asset}")


__all__ = [
    "APP_MANIFEST_RESOURCE",
    "APP_RELEASE_ROOT",
    "TERRAIN_MANIFEST_RESOURCE",
    "TERRAIN_OBJECT_ROOT",
    "app_asset_resource",
    "terrain_object_resource",
]
