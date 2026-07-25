import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from launcher import core as launcher_core
from launcher.terrain_store import parse_terrain_manifest
from tools import build_terrain_release
from tools.terrain_release import (
    TerrainReleaseError,
    TerrainReleaseSpec,
    extract_terrain_archive,
    sha256_file,
    validate_terrain_archive,
    validate_terrain_pack,
)

TEST_SIGNING_PRIVATE_KEY = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"


def _write_test_release(
    tmp_path: Path,
    *,
    include_local_paths: bool = False,
) -> tuple[Path, Path, TerrainReleaseSpec]:
    pack_dir = tmp_path / "terrain-test"
    pack_dir.mkdir()
    grid = b"BTH2-test-grid"
    grid_path = pack_dir / "test_map.bth"
    grid_path.write_bytes(grid)
    index_path = pack_dir / "index.json"
    index = {
        "schema_version": 1,
        "maps": [{"id": "test_map", "file": grid_path.name}],
    }
    if include_local_paths:
        index.update(
            {
                "game_root": "C:\\Users\\maintainer\\Game",
                "level_config_dir": "C:\\Users\\maintainer\\extracted\\levels",
            }
        )
    index_path.write_text(json.dumps(index), encoding="utf-8")
    index_bytes = index_path.read_bytes()
    (pack_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "bomana-terrain-offline-pack",
                "maps": 1,
                "output_grid_bytes": len(grid),
                "files": [
                    {
                        "path": grid_path.name,
                        "bytes": len(grid),
                        "sha256": hashlib.sha256(grid).hexdigest(),
                    },
                    {
                        "path": index_path.name,
                        "bytes": len(index_bytes),
                        "sha256": hashlib.sha256(index_bytes).hexdigest(),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    archive_path = tmp_path / "terrain-test.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(pack_dir.iterdir()):
            archive.write(path, f"terrain-test/{path.name}")
    spec = TerrainReleaseSpec(
        schema_version=1,
        pack_id="terrain-test",
        archive_asset=archive_path.name,
        archive_sha256=sha256_file(archive_path),
        archive_size_bytes=archive_path.stat().st_size,
        archive_root="terrain-test",
        map_count=1,
        package_prefix="bomana/data/terrain-test",
        download_urls=("https://example.test/terrain-test.zip",),
    )
    return pack_dir, archive_path, spec


def test_validated_terrain_release_extracts_with_closed_file_set(tmp_path: Path) -> None:
    pack_dir, archive_path, spec = _write_test_release(tmp_path)

    assert validate_terrain_pack(pack_dir, spec)["map_count"] == 1
    assert validate_terrain_archive(archive_path, spec)["archive_sha256"] == spec.archive_sha256

    output_dir = tmp_path / "prepared" / "terrain-test"
    summary = extract_terrain_archive(archive_path, output_dir, spec)

    assert summary["grid_size_bytes"] == len(b"BTH2-test-grid")
    assert (output_dir / "test_map.bth").read_bytes() == b"BTH2-test-grid"


def test_terrain_pack_rejects_unexpected_files(tmp_path: Path) -> None:
    pack_dir, _archive_path, spec = _write_test_release(tmp_path)
    (pack_dir / "unexpected.txt").write_text("not part of the release", encoding="utf-8")

    with pytest.raises(TerrainReleaseError, match="missing or unexpected"):
        validate_terrain_pack(pack_dir, spec)


def test_terrain_pack_rejects_local_path_metadata(tmp_path: Path) -> None:
    pack_dir, _archive_path, spec = _write_test_release(
        tmp_path,
        include_local_paths=True,
    )

    with pytest.raises(TerrainReleaseError, match="local path metadata"):
        validate_terrain_pack(pack_dir, spec)


def test_terrain_archive_extraction_sanitizes_local_path_metadata(tmp_path: Path) -> None:
    _pack_dir, archive_path, spec = _write_test_release(
        tmp_path,
        include_local_paths=True,
    )
    output_dir = tmp_path / "prepared" / "terrain-test"

    extract_terrain_archive(archive_path, output_dir, spec)

    index = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))
    assert "game_root" not in index
    assert "level_config_dir" not in index
    assert validate_terrain_pack(output_dir, spec)["map_count"] == 1


def test_terrain_archive_rejects_changed_bytes(tmp_path: Path) -> None:
    _pack_dir, archive_path, spec = _write_test_release(tmp_path)
    with archive_path.open("ab") as file_obj:
        file_obj.write(b"tampered")

    with pytest.raises(TerrainReleaseError, match="size mismatch"):
        validate_terrain_archive(archive_path, spec)


def test_content_addressed_terrain_release_is_signed_and_rebuildable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pack_dir, _archive_path, spec = _write_test_release(tmp_path)
    output_dir = tmp_path / "release"
    monkeypatch.setattr(build_terrain_release, "load_terrain_release_spec", lambda: spec)

    manifest_path, objects = build_terrain_release.build_terrain_release(
        pack_dir,
        output_dir,
        private_key=TEST_SIGNING_PRIVATE_KEY,
        key_id="test-key",
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    launcher_core.verify_release_manifest_signature(
        payload,
        public_keys={
            "test-key": launcher_core.ed25519_public_key_from_private_key(TEST_SIGNING_PRIVATE_KEY)
        },
        expected_kind="terrain",
    )
    manifest = parse_terrain_manifest(payload)
    assert manifest.pack_id == "terrain-test"
    assert manifest.map_count == 1
    assert len(objects) == 3
    assert {item.path for item in manifest.files} == {
        "index.json",
        "manifest.json",
        "test_map.bth",
    }
    assert all(path.name.startswith("Bomana_terrain_object_") for path in objects)

    rebuilt_manifest, rebuilt_objects = build_terrain_release.build_terrain_release(
        pack_dir,
        output_dir,
        private_key=TEST_SIGNING_PRIVATE_KEY,
        key_id="test-key",
    )

    assert rebuilt_manifest.read_bytes() == manifest_path.read_bytes()
    assert rebuilt_objects == objects
