#!/usr/bin/env python3
"""Build a signed, content-addressed Bomana terrain release."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from launcher.core import (  # noqa: E402
    RELEASE_MANIFEST_DEFAULT_KEY_ID,
    ed25519_public_key_from_private_key,
    sign_release_manifest,
)
from launcher.terrain_store import (  # noqa: E402
    TERRAIN_MANIFEST_ASSET,
    TERRAIN_OBJECT_ASSET_PREFIX,
    TerrainFile,
    TerrainManifest,
    parse_terrain_manifest,
    sha256_file,
    terrain_manifest_payload,
    terrain_revision,
)
from tools.terrain_release import (  # noqa: E402
    DEFAULT_TERRAIN_PACK_DIR,
    TERRAIN_PACK_DOCUMENTATION_FILES,
    TerrainReleaseError,
    load_terrain_release_spec,
    validate_terrain_pack,
)

SIGNING_PRIVATE_KEY_ENV = "BOMANA_RELEASE_ED25519_PRIVATE_KEY"
SIGNING_PUBLIC_KEY_ENV = "BOMANA_RELEASE_ED25519_PUBLIC_KEY"
SIGNING_KEY_ID_ENV = "BOMANA_RELEASE_SIGNING_KEY_ID"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "terrain-release"
CHECKSUM_FILE_NAME = "checksums_terrain.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack",
        default=str(DEFAULT_TERRAIN_PACK_DIR),
        help="Validated terrain pack directory.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for the signed manifest and immutable objects.",
    )
    return parser.parse_args()


def release_signing_key_context() -> tuple[str, str]:
    private_key = os.environ.get(SIGNING_PRIVATE_KEY_ENV, "").strip()
    public_key = os.environ.get(SIGNING_PUBLIC_KEY_ENV, "").strip()
    key_id = os.environ.get(SIGNING_KEY_ID_ENV, RELEASE_MANIFEST_DEFAULT_KEY_ID).strip()
    if not private_key:
        raise RuntimeError(f"{SIGNING_PRIVATE_KEY_ENV} is required")
    if not public_key:
        raise RuntimeError(f"{SIGNING_PUBLIC_KEY_ENV} is required")
    if ed25519_public_key_from_private_key(private_key) != public_key:
        raise RuntimeError(f"{SIGNING_PRIVATE_KEY_ENV} does not match {SIGNING_PUBLIC_KEY_ENV}")
    if not key_id:
        raise RuntimeError(f"{SIGNING_KEY_ID_ENV} must not be empty")
    return private_key, key_id


def _object_asset(path: Path, digest: str) -> str:
    suffix = path.suffix.lower()
    if not suffix or not suffix[1:].isalnum():
        suffix = ".bin"
    return f"{TERRAIN_OBJECT_ASSET_PREFIX}{digest}{suffix}"


def collect_terrain_files(pack_dir: Path) -> tuple[TerrainFile, ...]:
    files: list[TerrainFile] = []
    for path in sorted(pack_dir.iterdir(), key=lambda item: item.name):
        if path.name in TERRAIN_PACK_DOCUMENTATION_FILES:
            continue
        if path.is_symlink() or not path.is_file():
            raise TerrainReleaseError(f"terrain pack contains an unsupported entry: {path.name}")
        digest = sha256_file(path)
        files.append(
            TerrainFile(
                path=path.name,
                asset=_object_asset(path, digest),
                sha256=digest,
                size_bytes=path.stat().st_size,
            )
        )
    return tuple(files)


def build_terrain_release(
    pack_dir: Path,
    output_dir: Path,
    *,
    private_key: str,
    key_id: str,
) -> tuple[Path, tuple[Path, ...]]:
    spec = load_terrain_release_spec()
    validate_terrain_pack(pack_dir, spec)
    files = collect_terrain_files(pack_dir)
    revision = terrain_revision(spec.pack_id, spec.map_count, files)
    parsed = parse_terrain_manifest(
        {
            "schema_version": 1,
            "terrain_pack_id": spec.pack_id,
            "terrain_revision": revision,
            "map_count": spec.map_count,
            "total_size_bytes": sum(item.size_bytes for item in files),
            "files": [
                {
                    "path": item.path,
                    "asset": item.asset,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in files
            ],
        }
    )
    manifest = TerrainManifest(
        schema_version=parsed.schema_version,
        pack_id=parsed.pack_id,
        revision=parsed.revision,
        map_count=parsed.map_count,
        total_size_bytes=parsed.total_size_bytes,
        files=parsed.files,
    )

    objects_dir = output_dir / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)
    object_paths: list[Path] = []
    copied_hashes: set[str] = set()
    for item in manifest.files:
        destination = objects_dir / item.asset
        if item.sha256 not in copied_hashes:
            source = pack_dir / item.path
            if destination.exists():
                if (
                    destination.stat().st_size != item.size_bytes
                    or sha256_file(destination) != item.sha256
                ):
                    raise TerrainReleaseError(
                        f"refusing to overwrite mismatched immutable object: {destination}"
                    )
            else:
                shutil.copy2(source, destination)
            object_paths.append(destination)
            copied_hashes.add(item.sha256)

    signed = sign_release_manifest(
        terrain_manifest_payload(manifest),
        private_key,
        key_id=key_id,
    )
    manifest_path = output_dir / TERRAIN_MANIFEST_ASSET
    manifest_path.write_text(
        json.dumps(signed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checksum_lines = [
        f"{sha256_file(manifest_path)}  {manifest_path.name}",
        *(
            f"{sha256_file(path)}  objects/{path.name}"
            for path in sorted(object_paths, key=lambda item: item.name)
        ),
        "",
    ]
    (output_dir / CHECKSUM_FILE_NAME).write_text(
        "\n".join(checksum_lines),
        encoding="ascii",
    )
    return manifest_path, tuple(object_paths)


def main() -> int:
    args = parse_args()
    pack_dir = Path(args.pack).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    private_key, key_id = release_signing_key_context()
    manifest_path, objects = build_terrain_release(
        pack_dir,
        output_dir,
        private_key=private_key,
        key_id=key_id,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"terrain_manifest={manifest_path}", flush=True)
    print(f"terrain_revision={manifest['terrain_revision']}", flush=True)
    print(f"terrain_objects={len(objects)}", flush=True)
    print(f"terrain_bytes={manifest['total_size_bytes']}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, TerrainReleaseError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from None
