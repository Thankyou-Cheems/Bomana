from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from launcher.terrain_store import (
    TERRAIN_OBJECT_ASSET_PREFIX,
    TerrainFile,
    TerrainStore,
    TerrainStoreError,
    parse_terrain_manifest,
    terrain_revision,
)


def _terrain_manifest(contents: dict[str, bytes]):
    files = tuple(
        TerrainFile(
            path=path,
            asset=f"{TERRAIN_OBJECT_ASSET_PREFIX}{hashlib.sha256(data).hexdigest()}{Path(path).suffix}",
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )
        for path, data in sorted(contents.items())
    )
    revision = terrain_revision("terrain-v1", 1, files)
    return parse_terrain_manifest(
        {
            "schema_version": 1,
            "terrain_pack_id": "terrain-v1",
            "terrain_revision": revision,
            "map_count": 1,
            "total_size_bytes": sum(len(data) for data in contents.values()),
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


def _contents(map_bytes: bytes = b"map-v1") -> dict[str, bytes]:
    return {
        "index.json": b'{"schema_version":1,"maps":[]}',
        "manifest.json": b'{"schema_version":1}',
        "test_map.bth": map_bytes,
    }


def _fetcher(contents: dict[str, bytes], calls: list[str]):
    by_hash = {hashlib.sha256(data).hexdigest(): data for data in contents.values()}

    def fetch(item, destination: Path, progress_cb):
        calls.append(item.path)
        data = by_hash[item.sha256]
        destination.write_bytes(data)
        progress_cb(len(data), len(data))
        return "test-source"

    return fetch


def test_terrain_store_first_install_then_unchanged_manifest_is_zero_download(
    tmp_path: Path,
) -> None:
    contents = _contents()
    manifest = _terrain_manifest(contents)
    store = TerrainStore(tmp_path / "launcher-data")
    calls: list[str] = []

    first = store.sync(
        manifest,
        fetch_object=_fetcher(contents, calls),
    )

    assert first.downloaded_objects == 3
    assert first.downloaded_bytes == sum(map(len, contents.values()))
    assert first.already_current is False
    assert store.current_pack_dir() == first.pack_dir
    assert store.current_manifest() == manifest
    assert (first.pack_dir / "test_map.bth").read_bytes() == b"map-v1"

    calls.clear()

    def unexpected_fetch(*_args):
        raise AssertionError("unchanged terrain must not use the network")

    second = store.sync(manifest, fetch_object=unexpected_fetch)

    assert second.already_current is True
    assert second.downloaded_bytes == 0
    assert second.downloaded_objects == 0
    assert calls == []


def test_terrain_store_downloads_only_changed_content_object(tmp_path: Path) -> None:
    store = TerrainStore(tmp_path / "launcher-data")
    v1_contents = _contents(b"map-v1")
    v1 = _terrain_manifest(v1_contents)
    store.sync(v1, fetch_object=_fetcher(v1_contents, []))

    v2_contents = _contents(b"map-v2-with-new-grid")
    v2 = _terrain_manifest(v2_contents)
    plan = store.plan(v2)

    assert [item.path for item in plan.download_files] == ["test_map.bth"]
    assert plan.bytes_to_download == len(v2_contents["test_map.bth"])
    assert plan.bytes_to_reuse == sum(
        len(v2_contents[path]) for path in ("index.json", "manifest.json")
    )

    calls: list[str] = []
    result = store.sync(v2, fetch_object=_fetcher(v2_contents, calls))

    assert calls == ["test_map.bth"]
    assert result.downloaded_objects == 1
    assert result.reused_objects == 2
    assert (result.pack_dir / "test_map.bth").read_bytes() == v2_contents["test_map.bth"]


def test_terrain_store_migrates_legacy_pack_without_download(tmp_path: Path) -> None:
    contents = _contents()
    manifest = _terrain_manifest(contents)
    legacy = tmp_path / "legacy" / "terrain-v1"
    legacy.mkdir(parents=True)
    for name, data in contents.items():
        (legacy / name).write_bytes(data)
    store = TerrainStore(tmp_path / "launcher-data")
    plan = store.plan(manifest, seed_dirs=(legacy,))

    assert plan.bytes_to_download == 0
    assert len(plan.seed_files) == 3

    def unexpected_fetch(*_args):
        raise AssertionError("valid legacy terrain must be reused")

    result = store.sync(
        manifest,
        fetch_object=unexpected_fetch,
        seed_dirs=(legacy,),
    )

    assert result.downloaded_bytes == 0
    assert result.reused_objects == 3
    assert store.current_pack_dir() == result.pack_dir


def test_terrain_store_failed_object_does_not_replace_current_pack(tmp_path: Path) -> None:
    store = TerrainStore(tmp_path / "launcher-data")
    v1_contents = _contents(b"map-v1")
    v1 = _terrain_manifest(v1_contents)
    first = store.sync(v1, fetch_object=_fetcher(v1_contents, []))
    v2 = _terrain_manifest(_contents(b"map-v2"))

    def corrupt_fetch(_item, destination: Path, progress_cb):
        destination.write_bytes(b"corrupt")
        progress_cb(7, 7)
        return "bad-source"

    with pytest.raises(TerrainStoreError, match="校验失败"):
        store.sync(v2, fetch_object=corrupt_fetch)

    assert store.current_pack_dir() == first.pack_dir
    assert store.current_revision() == v1.revision
    assert (first.pack_dir / "test_map.bth").read_bytes() == b"map-v1"


def test_terrain_manifest_revision_covers_nested_file_metadata() -> None:
    contents = _contents()
    manifest = _terrain_manifest(contents)
    payload = {
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
    payload["files"][0]["size_bytes"] += 1
    payload["total_size_bytes"] += 1

    with pytest.raises(TerrainStoreError, match="revision"):
        parse_terrain_manifest(payload)
