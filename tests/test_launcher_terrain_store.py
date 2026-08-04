from __future__ import annotations

import errno
import hashlib
from pathlib import Path
from threading import Lock
from time import sleep

import pytest

import launcher.terrain_store as terrain_store_module
from launcher.terrain_store import (
    TERRAIN_DEGRADED_STARTUP,
    TERRAIN_OBJECT_ASSET_PREFIX,
    TerrainFile,
    TerrainMap,
    TerrainStore,
    TerrainStoreError,
    parse_terrain_catalog,
    parse_terrain_manifest,
    terrain_catalog_revision,
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
    map_count = sum(path.endswith(".bth") for path in contents)
    revision = terrain_revision("terrain-v1", map_count, files)
    return parse_terrain_manifest(
        {
            "schema_version": 1,
            "terrain_pack_id": "terrain-v1",
            "terrain_revision": revision,
            "map_count": map_count,
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


def _terrain_catalog(
    shared_contents: dict[str, bytes],
    map_contents: dict[str, dict[str, bytes]],
    display_names: dict[str, str] | None = None,
):
    def files_for(contents: dict[str, bytes]) -> tuple[TerrainFile, ...]:
        return tuple(
            TerrainFile(
                path=path,
                asset=(
                    f"{TERRAIN_OBJECT_ASSET_PREFIX}{hashlib.sha256(data).hexdigest()}"
                    f"{Path(path).suffix}"
                ),
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
            )
            for path, data in sorted(contents.items())
        )

    shared_files = files_for(shared_contents)
    maps = tuple(
        TerrainMap(
            map_id=map_id,
            files=files_for(contents),
            display_name_zh=(display_names or {}).get(map_id, ""),
        )
        for map_id, contents in sorted(map_contents.items())
    )
    revision = terrain_catalog_revision("terrain-v2", 1, shared_files, maps)
    return parse_terrain_catalog(
        {
            "schema_version": 2,
            "terrain_catalog_id": "terrain-v2",
            "terrain_revision": revision,
            "min_runtime_contract_version": 1,
            "shared_files": [
                {
                    "path": item.path,
                    "asset": item.asset,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in shared_files
            ],
            "maps": [
                {
                    "map_id": terrain_map.map_id,
                    "files": [
                        {
                            "path": item.path,
                            "asset": item.asset,
                            "sha256": item.sha256,
                            "size_bytes": item.size_bytes,
                        }
                        for item in terrain_map.files
                    ],
                    **(
                        {"display_name_zh": terrain_map.display_name_zh}
                        if terrain_map.display_name_zh
                        else {}
                    ),
                }
                for terrain_map in maps
            ],
        }
    )


def test_catalog_display_name_is_versioned_and_old_catalogs_still_parse() -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2}',
    }
    map_contents = {"map_a": {"map_a.bth": b"map-a"}}

    legacy = _terrain_catalog(shared_contents, map_contents)
    named = _terrain_catalog(shared_contents, map_contents, {"map_a": "目录名称"})

    assert legacy.maps[0].display_name_zh == ""
    assert named.maps[0].display_name_zh == "目录名称"
    assert legacy.revision != named.revision


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


def test_empty_selection_is_distinct_from_uninitialized_selection(tmp_path: Path) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    catalog = _terrain_catalog(
        shared_contents,
        {"map_a": {"map_a.bth": b"map-a"}},
    )
    store = TerrainStore(tmp_path / "launcher-data")

    assert store.has_map_selection(catalog) is False
    assert store.selected_map_ids(catalog) == ()

    store.set_map_selection(catalog, ())

    assert store.has_map_selection(catalog) is True
    assert store.selected_map_ids(catalog) == ()


def test_catalog_selection_persists_and_syncs_only_selected_maps(tmp_path: Path) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    map_contents = {
        "map_a": {"map_a.bth": b"map-a", "map_a_shared.bin": b"shared-grid"},
        "map_b": {"map_b.bth": b"map-b", "map_b_shared.bin": b"shared-grid"},
    }
    catalog = _terrain_catalog(shared_contents, map_contents)
    all_contents = {**shared_contents, **map_contents["map_a"], **map_contents["map_b"]}
    store = TerrainStore(tmp_path / "launcher-data")
    calls: list[str] = []

    assert store.set_map_selection(catalog, ("map_a",)) == ("map_a",)

    first = store.sync_catalog(catalog, fetch_object=_fetcher(all_contents, calls))

    assert first.status == "activated"
    assert set(calls) == {"index.json", "manifest.json", "map_a.bth", "map_a_shared.bin"}
    assert "map_b.bth" not in calls
    assert TerrainStore(tmp_path / "launcher-data").selected_map_ids() == ("map_a",)

    calls.clear()
    store.set_map_selection(catalog, ("map_b",))

    second = store.sync_catalog(catalog, fetch_object=_fetcher(all_contents, calls))

    assert second.status == "activated"
    assert calls == ["map_b.bth"]
    assert store.current_catalog() == catalog


def test_catalog_sync_reports_precise_progress_for_each_map_during_parallel_downloads(
    tmp_path: Path,
) -> None:
    shared_contents = {
        "index.json": b"shared-index",
        "manifest.json": b"shared-manifest",
    }
    map_contents = {
        "map_a": {"map_a.bth": b"map-a-payload"},
        "map_b": {"map_b.bth": b"map-b-payload-longer"},
    }
    catalog = _terrain_catalog(shared_contents, map_contents)
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(catalog, ())
    store.sync_catalog(catalog, fetch_object=_fetcher(shared_contents, []), max_workers=2)
    store.set_map_selection(catalog, ("map_a", "map_b"))
    snapshots = []

    def fetch_with_progress(item, destination: Path, progress_cb):
        payload = map_contents[item.path.removesuffix(".bth")][item.path]
        midpoint = max(1, len(payload) // 2)
        destination.write_bytes(payload[:midpoint])
        progress_cb(midpoint, len(payload))
        with destination.open("ab") as file_obj:
            file_obj.write(payload[midpoint:])
        progress_cb(len(payload), len(payload))
        return "parallel-test-source"

    result = store.sync_catalog(
        catalog,
        fetch_object=fetch_with_progress,
        map_progress_cb=snapshots.append,
        max_workers=2,
    )

    assert result.status == "activated"
    assert snapshots
    final = {item.map_id: item for item in snapshots[-1]}
    shared_size = sum(len(value) for value in shared_contents.values())
    assert final["map_a"].total_bytes == shared_size + len(map_contents["map_a"]["map_a.bth"])
    assert final["map_b"].total_bytes == shared_size + len(map_contents["map_b"]["map_b.bth"])
    assert final["map_a"].completed_bytes == final["map_a"].total_bytes
    assert final["map_b"].completed_bytes == final["map_b"].total_bytes
    assert final["map_a"].complete is True
    assert final["map_b"].complete is True
    assert any(
        0 < item.completed_bytes < item.total_bytes
        for snapshot in snapshots
        for item in snapshot
        if item.map_id in {"map_a", "map_b"}
    )


def test_catalog_sync_pauses_and_preserves_the_previous_active_catalog(tmp_path: Path) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    v1_maps = {
        "map_a": {"map_a.bth": b"map-a-v1"},
        "map_b": {"map_b.bth": b"map-b-v1"},
    }
    v2_maps = {
        "map_a": {"map_a.bth": b"map-a-v2"},
        "map_b": {"map_b.bth": b"map-b-v2"},
    }
    v1 = _terrain_catalog(shared_contents, v1_maps)
    v2 = _terrain_catalog(shared_contents, v2_maps)
    all_v1_contents = {**shared_contents, **v1_maps["map_a"], **v1_maps["map_b"]}
    all_v2_contents = {**shared_contents, **v2_maps["map_a"], **v2_maps["map_b"]}
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(v1, ("map_a",))
    active = store.sync_catalog(v1, fetch_object=_fetcher(all_v1_contents, []))
    calls: list[str] = []

    paused_for_host = store.sync_catalog(
        v2,
        fetch_object=_fetcher(all_v2_contents, calls),
        app_host_active=lambda: True,
    )

    assert paused_for_host.status == "paused_app_host"
    assert calls == []
    assert store.current_catalog() == v1

    paused_for_disk = store.sync_catalog(
        v2,
        fetch_object=_fetcher(all_v2_contents, calls),
        disk_free_bytes=lambda _path: 0,
    )

    assert paused_for_disk.status == "paused_insufficient_disk"
    assert "存储" in paused_for_disk.message
    assert store.current_catalog() == v1

    def fail_selected(item, destination: Path, progress_cb):
        if item.path == "map_a.bth":
            raise OSError("simulated selected map interruption")
        return _fetcher(all_v2_contents, calls)(item, destination, progress_cb)

    with pytest.raises(OSError, match="selected map interruption"):
        store.sync_catalog(v2, fetch_object=fail_selected)

    assert store.current_catalog() == v1
    assert store.current_catalog_pack_dir() == active.pack_dir

    activated = store.sync_catalog(v2, fetch_object=_fetcher(all_v2_contents, calls))

    assert activated.status == "activated"
    assert calls == ["map_a.bth"]
    assert store.current_catalog() == v2


def test_catalog_handoff_keeps_using_the_previous_active_revision_while_candidate_waits(
    tmp_path: Path,
) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    v1_maps = {
        "map_a": {"map_a.bth": b"map-a-v1"},
        "map_b": {"map_b.bth": b"map-b-v1"},
    }
    v2_maps = {
        "map_a": {"map_a.bth": b"map-a-v2"},
        "map_b": {"map_b.bth": b"map-b-v2"},
    }
    v1 = _terrain_catalog(shared_contents, v1_maps)
    v2 = _terrain_catalog(shared_contents, v2_maps)
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(v1, ("map_a",))
    active = store.sync_catalog(
        v1,
        fetch_object=_fetcher({**shared_contents, **v1_maps["map_a"]}, []),
    )

    handoff = store.catalog_handoff(v2)

    assert handoff.can_start is True
    assert handoff.catalog_revision == v1.revision
    assert handoff.catalog_root == active.pack_dir
    assert handoff.available_maps == ("map_a",)
    assert handoff.unavailable_maps == ("map_b",)
    assert store.current_catalog() == v1


def test_catalog_sync_counts_only_missing_partial_bytes_for_disk_pause(
    tmp_path: Path,
) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    map_data = b"resumable-map-object"
    map_contents = {"map_a": {"map_a.bth": map_data}}
    catalog = _terrain_catalog(shared_contents, map_contents)
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(catalog, ())
    store.sync_catalog(catalog, fetch_object=_fetcher(shared_contents, []))
    store.set_map_selection(catalog, ("map_a",))
    item = catalog.maps[0].files[0]
    partial = store.partials_dir / catalog.revision / f"{item.sha256}.part"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(map_data[:7])

    def resume(item_to_fetch, destination: Path, progress_cb):
        assert item_to_fetch == item
        assert destination.read_bytes() == map_data[:7]
        with destination.open("ab") as file_obj:
            file_obj.write(map_data[7:])
        progress_cb(len(map_data), len(map_data))
        return "resumed-source"

    result = store.sync_catalog(
        catalog,
        fetch_object=resume,
        disk_free_bytes=lambda _path: len(map_data) - 7,
    )

    assert result.status == "activated"
    assert result.downloaded_objects == 1
    assert (result.pack_dir / "map_a.bth").read_bytes() == map_data


def test_catalog_sync_pauses_mid_object_and_resumes_after_app_exit(tmp_path: Path) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    map_data = b"resumable-map-after-app-start"
    catalog = _terrain_catalog(
        shared_contents,
        {"map_a": {"map_a.bth": map_data}},
    )
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(catalog, ())
    store.sync_catalog(catalog, fetch_object=_fetcher(shared_contents, []), max_workers=1)
    store.set_map_selection(catalog, ("map_a",))
    host_active = False

    def interrupted_for_app(item, destination: Path, progress_cb):
        nonlocal host_active
        assert item.path == "map_a.bth"
        destination.write_bytes(map_data[:7])
        host_active = True
        progress_cb(7, len(map_data))
        raise AssertionError("host callback must pause before fetch returns")

    paused = store.sync_catalog(
        catalog,
        fetch_object=interrupted_for_app,
        app_host_active=lambda: host_active,
        max_workers=1,
    )

    item = catalog.maps[0].files[0]
    partial = store.partials_dir / catalog.revision / f"{item.sha256}.part"
    assert paused.status == "paused_app_host"
    assert partial.read_bytes() == map_data[:7]

    host_active = False

    def resumed(item_to_fetch, destination: Path, progress_cb):
        assert item_to_fetch == item
        existing = destination.read_bytes()
        assert existing == map_data[:7]
        with destination.open("ab") as file_obj:
            file_obj.write(map_data[len(existing) :])
        progress_cb(len(map_data), len(map_data))
        return "resumed-test-source"

    activated = store.sync_catalog(
        catalog,
        fetch_object=resumed,
        app_host_active=lambda: host_active,
        max_workers=1,
    )

    assert activated.status == "activated"
    assert (activated.pack_dir / "map_a.bth").read_bytes() == map_data
    assert partial.exists() is False


def test_catalog_sync_turns_runtime_disk_exhaustion_into_an_actionable_pause(
    tmp_path: Path,
) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    v1_maps = {"map_a": {"map_a.bth": b"map-a-v1"}}
    v2_maps = {"map_a": {"map_a.bth": b"map-a-v2-with-more-data"}}
    v1 = _terrain_catalog(shared_contents, v1_maps)
    v2 = _terrain_catalog(shared_contents, v2_maps)
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(v1, ("map_a",))
    active = store.sync_catalog(
        v1,
        fetch_object=_fetcher({**shared_contents, **v1_maps["map_a"]}, []),
    )
    candidate_item = v2.maps[0].files[0]

    def exhaust_disk(item, destination: Path, progress_cb):
        assert item == candidate_item
        destination.write_bytes(v2_maps["map_a"]["map_a.bth"][:5])
        progress_cb(5, item.size_bytes)
        raise OSError(errno.ENOSPC, "simulated disk exhaustion")

    result = store.sync_catalog(v2, fetch_object=exhaust_disk)

    assert result.status == "paused_insufficient_disk"
    assert "存储" in result.message
    assert store.current_catalog() == v1
    assert store.current_catalog_pack_dir() == active.pack_dir
    partial = store.partials_dir / v2.revision / f"{candidate_item.sha256}.part"
    assert partial.read_bytes() == v2_maps["map_a"]["map_a.bth"][:5]


def test_catalog_activation_disk_exhaustion_keeps_the_previous_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    v1_maps = {"map_a": {"map_a.bth": b"map-a-v1"}}
    v2_maps = {"map_a": {"map_a.bth": b"map-a-v2"}}
    v1 = _terrain_catalog(shared_contents, v1_maps)
    v2 = _terrain_catalog(shared_contents, v2_maps)
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(v1, ("map_a",))
    active = store.sync_catalog(
        v1,
        fetch_object=_fetcher({**shared_contents, **v1_maps["map_a"]}, []),
    )
    original_link = terrain_store_module.os.link
    original_copyfile = terrain_store_module.shutil.copyfile

    def reject_catalog_hardlink(source, destination, *args, **kwargs):
        if store.catalogs_dir in Path(destination).parents:
            raise OSError(errno.EXDEV, "simulated cross-device link")
        return original_link(source, destination, *args, **kwargs)

    def exhaust_catalog_copy(source, destination, *args, **kwargs):
        if store.catalogs_dir in Path(destination).parents:
            raise OSError(errno.ENOSPC, "simulated activation disk exhaustion")
        return original_copyfile(source, destination, *args, **kwargs)

    monkeypatch.setattr(terrain_store_module.os, "link", reject_catalog_hardlink)
    monkeypatch.setattr(terrain_store_module.shutil, "copyfile", exhaust_catalog_copy)

    result = store.sync_catalog(
        v2,
        fetch_object=_fetcher({**shared_contents, **v2_maps["map_a"]}, []),
    )

    assert result.status == "paused_insufficient_disk"
    assert store.current_catalog() == v1
    assert store.current_catalog_pack_dir() == active.pack_dir


def test_catalog_sync_reconciles_to_the_latest_persisted_selection(tmp_path: Path) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    map_contents = {
        "map_a": {"map_a.bth": b"map-a"},
        "map_b": {"map_b.bth": b"map-b"},
    }
    catalog = _terrain_catalog(shared_contents, map_contents)
    all_contents = {**shared_contents, **map_contents["map_a"], **map_contents["map_b"]}
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(catalog, ("map_a",))
    calls: list[str] = []

    def select_map_b_after_first_object(item, destination: Path, progress_cb):
        result = _fetcher(all_contents, calls)(item, destination, progress_cb)
        if item.path == "index.json":
            store.set_map_selection(catalog, ("map_b",))
        return result

    result = store.sync_catalog(catalog, fetch_object=select_map_b_after_first_object)

    assert result.status == "activated"
    assert result.selected_map_ids == ("map_b",)
    assert "map_a.bth" not in calls
    assert "map_b.bth" in calls
    assert store.current_catalog_selection() == ("map_b",)
    assert (result.pack_dir / "map_b.bth").read_bytes() == b"map-b"
    assert (result.pack_dir / "map_a.bth").exists() is False


def test_catalog_handoff_reports_per_map_degradation_without_blocking_startup(
    tmp_path: Path,
) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    map_contents = {
        "map_a": {"map_a.bth": b"map-a"},
        "map_b": {"map_b.bth": b"map-b"},
    }
    catalog = _terrain_catalog(shared_contents, map_contents)
    all_contents = {**shared_contents, **map_contents["map_a"], **map_contents["map_b"]}
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(catalog, ("map_a",))
    activated = store.sync_catalog(catalog, fetch_object=_fetcher(all_contents, []))

    handoff = store.catalog_handoff(catalog)
    incompatible = store.catalog_handoff(catalog, terrain_compatible=False)

    assert handoff.can_start is True
    assert handoff.catalog_root == activated.pack_dir
    assert handoff.complete is False
    assert handoff.available_maps == ("map_a",)
    assert handoff.unavailable_maps == ("map_b",)
    assert "投弹" in handoff.notice
    assert incompatible.can_start is True
    assert incompatible.catalog_root is None
    assert incompatible.reason == "incompatible"


def test_catalog_pruning_waits_for_host_exit_and_keeps_only_the_active_catalog(
    tmp_path: Path,
) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    v1_maps = {"map_a": {"map_a.bth": b"map-a-v1"}}
    v2_maps = {"map_a": {"map_a.bth": b"map-a-v2"}}
    v1 = _terrain_catalog(shared_contents, v1_maps)
    v2 = _terrain_catalog(shared_contents, v2_maps)
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(v1, ("map_a",))
    first = store.sync_catalog(
        v1,
        fetch_object=_fetcher({**shared_contents, **v1_maps["map_a"]}, []),
    )
    second = store.sync_catalog(
        v2,
        fetch_object=_fetcher({**shared_contents, **v2_maps["map_a"]}, []),
    )

    assert first.pack_dir.exists()
    assert second.pack_dir.exists()

    pruned = store.prune_after_host_exit()

    assert pruned.removed_packs == 1
    assert first.pack_dir.exists() is False
    assert second.pack_dir.exists()
    assert store.current_catalog() == v2


def test_catalog_pruning_is_a_noop_while_the_app_host_is_active(tmp_path: Path) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    v1_maps = {"map_a": {"map_a.bth": b"map-a-v1"}}
    v2_maps = {"map_a": {"map_a.bth": b"map-a-v2"}}
    v1 = _terrain_catalog(shared_contents, v1_maps)
    v2 = _terrain_catalog(shared_contents, v2_maps)
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(v1, ("map_a",))
    first = store.sync_catalog(
        v1,
        fetch_object=_fetcher({**shared_contents, **v1_maps["map_a"]}, []),
    )
    second = store.sync_catalog(
        v2,
        fetch_object=_fetcher({**shared_contents, **v2_maps["map_a"]}, []),
    )

    pruned = store.prune_after_host_exit(app_host_active=lambda: True)

    assert pruned.removed_packs == 0
    assert first.pack_dir.exists()
    assert second.pack_dir.exists()
    assert any("运行" in item for item in pruned.diagnostics)
    assert store.current_catalog() == v2


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

    def corrupt_fetch(item, destination: Path, progress_cb):
        destination.write_bytes(b"x" * item.size_bytes)
        progress_cb(item.size_bytes, item.size_bytes)
        return "bad-source"

    with pytest.raises(TerrainStoreError, match="校验失败"):
        store.sync(v2, fetch_object=corrupt_fetch)

    assert store.current_pack_dir() == first.pack_dir
    assert store.current_revision() == v1.revision
    assert (first.pack_dir / "test_map.bth").read_bytes() == b"map-v1"


def test_terrain_startup_is_non_blocking_with_accuracy_notice(tmp_path: Path) -> None:
    store = TerrainStore(tmp_path / "launcher-data")
    manifest = _terrain_manifest(_contents())

    missing = store.startup_state(manifest)
    incompatible = store.startup_state(manifest, terrain_compatible=False)

    assert missing.status == TERRAIN_DEGRADED_STARTUP
    assert missing.can_start is True
    assert missing.download_recommended is True
    assert "投弹" in missing.notice
    assert incompatible.status == TERRAIN_DEGRADED_STARTUP
    assert incompatible.can_start is True
    assert incompatible.reason == "incompatible"


def test_terrain_store_reports_completed_maps_while_other_maps_are_missing(
    tmp_path: Path,
) -> None:
    store = TerrainStore(tmp_path / "launcher-data")
    v1_contents = {
        "index.json": b'{"schema_version":1,"maps":["map_a","map_b"]}',
        "manifest.json": b'{"schema_version":1}',
        "map_a.bth": b"map-a-v1",
        "map_b.bth": b"map-b-v1",
    }
    v2_contents = {**v1_contents, "map_b.bth": b"map-b-v2"}
    v1 = _terrain_manifest(v1_contents)
    v2 = _terrain_manifest(v2_contents)
    store.sync(v1, fetch_object=_fetcher(v1_contents, []), max_workers=1)

    availability = store.availability(v2)
    startup = store.startup_state(v2)

    assert availability.complete is False
    assert availability.available_maps == ("map_a",)
    assert availability.unavailable_maps == ("map_b",)
    assert startup.can_start is True
    assert startup.available_maps == ("map_a",)
    assert startup.unavailable_maps == ("map_b",)


def test_terrain_store_keeps_a_partial_object_for_a_later_resumed_download(
    tmp_path: Path,
) -> None:
    contents = _contents(b"resumable-map")
    manifest = _terrain_manifest(contents)
    store = TerrainStore(tmp_path / "launcher-data")
    map_item = next(item for item in manifest.files if item.path == "test_map.bth")

    def interrupted_fetch(item, destination: Path, progress_cb):
        data = contents[item.path]
        if item.path != "test_map.bth":
            destination.write_bytes(data)
            progress_cb(len(data), len(data))
            return "initial-source"
        destination.write_bytes(data[:3])
        progress_cb(3, len(data))
        raise OSError("simulated interruption")

    with pytest.raises(OSError, match="interruption"):
        store.sync(manifest, fetch_object=interrupted_fetch, max_workers=1)

    partial = store.partials_dir / manifest.revision / f"{map_item.sha256}.part"
    assert partial.read_bytes() == contents[map_item.path][:3]

    def resumed_fetch(item, destination: Path, progress_cb):
        data = contents[item.path]
        existing = destination.read_bytes() if destination.exists() else b""
        assert data.startswith(existing)
        with destination.open("ab") as file_obj:
            file_obj.write(data[len(existing) :])
        progress_cb(len(data), len(data))
        return "resumed-source"

    result = store.sync(manifest, fetch_object=resumed_fetch, max_workers=1)

    assert result.downloaded_objects == 1
    assert (result.pack_dir / "test_map.bth").read_bytes() == contents["test_map.bth"]
    assert partial.exists() is False


def test_terrain_store_limits_parallel_object_fetches(tmp_path: Path) -> None:
    contents = {
        "index.json": b'{"schema_version":1,"maps":["a","b","c"]}',
        "manifest.json": b'{"schema_version":1}',
        "a.bth": b"a",
        "b.bth": b"b",
        "c.bth": b"c",
    }
    manifest = _terrain_manifest(contents)
    store = TerrainStore(tmp_path / "launcher-data")
    active = 0
    maximum = 0
    lock = Lock()

    def concurrent_fetch(item, destination: Path, progress_cb):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            sleep(0.03)
            data = contents[item.path]
            destination.write_bytes(data)
            progress_cb(len(data), len(data))
            return "bounded-source"
        finally:
            with lock:
                active -= 1

    result = store.sync(manifest, fetch_object=concurrent_fetch, max_workers=2)

    assert result.downloaded_objects == len(contents)
    assert maximum == 2


def test_catalog_sync_bounds_parallel_selected_object_fetches(tmp_path: Path) -> None:
    shared_contents = {
        "index.json": b'{"schema_version":2}',
        "manifest.json": b'{"schema_version":2,"type":"manifest"}',
    }
    map_contents = {
        "map_a": {"map_a.bth": b"a"},
        "map_b": {"map_b.bth": b"b"},
        "map_c": {"map_c.bth": b"c"},
    }
    catalog = _terrain_catalog(shared_contents, map_contents)
    store = TerrainStore(tmp_path / "launcher-data")
    store.set_map_selection(catalog, ())
    store.sync_catalog(catalog, fetch_object=_fetcher(shared_contents, []))
    store.select_all_maps(catalog)
    all_contents = {
        **map_contents["map_a"],
        **map_contents["map_b"],
        **map_contents["map_c"],
    }
    active = 0
    maximum = 0
    lock = Lock()

    def concurrent_fetch(item, destination: Path, progress_cb):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            sleep(0.03)
            data = all_contents[item.path]
            destination.write_bytes(data)
            progress_cb(len(data), len(data))
            return "bounded-source"
        finally:
            with lock:
                active -= 1

    result = store.sync_catalog(
        catalog,
        fetch_object=concurrent_fetch,
        max_workers=2,
    )

    assert result.status == "activated"
    assert result.downloaded_objects == 3
    assert result.selected_map_ids == ("map_a", "map_b", "map_c")
    assert maximum == 2


def test_terrain_store_prunes_only_after_explicit_deferred_cleanup(tmp_path: Path) -> None:
    store = TerrainStore(tmp_path / "launcher-data")
    v1_contents = _contents(b"map-v1")
    v2_contents = _contents(b"map-v2")
    v1 = _terrain_manifest(v1_contents)
    v2 = _terrain_manifest(v2_contents)
    first = store.sync(v1, fetch_object=_fetcher(v1_contents, []), max_workers=1)
    store.sync(v2, fetch_object=_fetcher(v2_contents, []), max_workers=1)
    v1_map = next(item for item in v1.files if item.path == "test_map.bth")

    assert first.pack_dir.exists()
    assert (store.objects_dir / v1_map.sha256).exists()

    pruned = store.prune_after_host_exit()

    assert pruned.diagnostics == ()
    assert pruned.removed_packs == 1
    assert first.pack_dir.exists() is False
    assert (store.objects_dir / v1_map.sha256).exists() is False
    assert store.current_revision() == v2.revision


def test_terrain_store_reports_deferred_prune_failure_without_disabling_active_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TerrainStore(tmp_path / "launcher-data")
    v1_contents = _contents(b"map-v1")
    v2_contents = _contents(b"map-v2")
    v1 = _terrain_manifest(v1_contents)
    v2 = _terrain_manifest(v2_contents)
    first = store.sync(v1, fetch_object=_fetcher(v1_contents, []), max_workers=1)
    store.sync(v2, fetch_object=_fetcher(v2_contents, []), max_workers=1)
    original_rmtree = terrain_store_module.shutil.rmtree

    def fail_old_pack(path: Path, *args, **kwargs) -> None:
        if path == first.pack_dir:
            raise OSError("simulated locked old pack")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(terrain_store_module.shutil, "rmtree", fail_old_pack)

    pruned = store.prune_after_host_exit()

    assert pruned.removed_packs == 0
    assert any("无法清理过期地形包" in item for item in pruned.diagnostics)
    assert store.current_revision() == v2.revision


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
