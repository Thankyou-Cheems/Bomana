# enforces: docs/specs/version-compatibility.md COMPAT-01..COMPAT-04 COMPAT-07..COMPAT-13 COMPAT-17 COMPAT-20

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

from launcher import core as launcher_core
from launcher import install_txn

ROOT = Path(__file__).resolve().parents[2]
VERSION_BOUNDARY = ROOT / "bomana_version.py"


def _load_version_boundary() -> ModuleType:
    assert VERSION_BOUNDARY.exists(), "bomana_version.py is the required shared boundary"
    spec = importlib.util.spec_from_file_location("bomana_version_contract", VERSION_BOUNDARY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_parser_accepts_only_bounded_strict_x_y_z() -> None:
    boundary = _load_version_boundary()
    parse = boundary.parse_strict_version

    assert parse("0.0.0") == (0, 0, 0)
    assert parse("8.0.0") == (8, 0, 0)
    assert parse("999999999.999999999.999999999") == (
        999999999,
        999999999,
        999999999,
    )

    rejected = (
        None,
        True,
        False,
        8,
        8.0,
        "",
        "8",
        "8.0",
        "8.0.0.0",
        "v8.0.0",
        "08.0.0",
        "8.00.0",
        "8.0.00",
        "+8.0.0",
        "-8.0.0",
        " 8.0.0",
        "8.0.0 ",
        "8.0.0-rc1",
        "8.0.0+build",
        "1000000000.0.0",
        "８.０.０",
    )
    for value in rejected:
        with pytest.raises((TypeError, ValueError)):
            parse(value)


def test_app_and_launcher_floors_are_exactly_8_and_3() -> None:
    boundary = _load_version_boundary()
    app_metadata = (ROOT / "bomana/metadata.py").read_text(encoding="utf-8")
    launcher_metadata = (ROOT / "launcher/metadata.py").read_text(encoding="utf-8")
    build = (ROOT / "tools/build_portable.py").read_text(encoding="utf-8")

    assert boundary.MIN_SUPPORTED_APP_VERSION == "8.0.0"
    assert boundary.MIN_SUPPORTED_LAUNCHER_VERSION == "3.0.0"
    app_version_match = re.search(
        r'^__version__ = "([0-9]+[.][0-9]+[.][0-9]+)"$', app_metadata, re.M
    )
    assert app_version_match is not None
    assert boundary.parse_strict_version(
        app_version_match.group(1)
    ) >= boundary.parse_strict_version(boundary.MIN_SUPPORTED_APP_VERSION)
    assert 'PORTABLE_MIN_LAUNCHER_VERSION = "3.0.0"' in app_metadata
    assert 'LAUNCHER_VERSION = "3.1.0"' in launcher_metadata
    assert 'PACKAGED_LAUNCHER_RUNTIME_MIN_LAUNCHER_VERSION = "3.0.0"' in build


def test_all_compatibility_entry_paths_use_the_shared_boundary() -> None:
    sources = {
        "app entry": (ROOT / "Bomana.pyw").read_text(encoding="utf-8"),
        "launcher entry": (ROOT / "launcher.pyw").read_text(encoding="utf-8"),
        "install transactions": (ROOT / "launcher/install_txn.py").read_text(encoding="utf-8"),
    }
    for label, source in sources.items():
        assert "bomana_version" in source, label

    launcher = sources["launcher entry"]
    transactions = sources["install transactions"]
    for flow_marker in (
        "_local_app_launch_version",
        "import_zip",
        "rollback",
        "recover_incomplete",
    ):
        assert flow_marker in "\n".join((launcher, transactions))
    assert "require_minimum_version" in launcher
    assert "require_minimum_version" in transactions
    assert "require_exact_version" in transactions


def test_packaged_app_guard_precedes_runtime_imports() -> None:
    entry = (ROOT / "Bomana.pyw").read_text(encoding="utf-8")
    bootstrap = (ROOT / "launcher/bootstrap.py").read_text(encoding="utf-8")
    guard = entry.index("\nvalidate_app_launcher_identity(")

    for runtime_import in (
        "import tkinter",
        "from bomana.config",
        "from bomana.ui",
        "from bomana.utils.diagnostics",
        "from bomana.utils.system",
    ):
        assert guard < entry.index(runtime_import)
    assert '"BOMANA_LAUNCHER_VERSION"' in bootstrap
    assert "LAUNCHER_VERSION" in bootstrap
    assert "BOMANA_SOURCE_DEVELOPMENT" in entry or "BOMANA_SOURCE_DEVELOPMENT" in (
        ROOT / "bomana_version.py"
    ).read_text(encoding="utf-8")


def test_staged_version_is_read_as_data_without_importing_candidate_code() -> None:
    transactions = (ROOT / "launcher/install_txn.py").read_text(encoding="utf-8")

    assert "_read_literal_version" in transactions
    assert ".read_text(" in transactions
    assert "importlib" not in transactions
    assert "runpy" not in transactions
    assert "exec(" not in transactions


def test_recovery_prevalidates_every_slot_before_mutating_valid_backup(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / install_txn.APP_BACKUP_DIR_NAME
    new_dir = tmp_path / f"{install_txn.APP_DIR_NAME}_new"
    for candidate, version in ((backup_dir, "8.1.0"), (new_dir, "malformed")):
        metadata_dir = candidate / "bomana"
        metadata_dir.mkdir(parents=True)
        (metadata_dir / "metadata.py").write_text(
            f'__version__ = "{version}"\n',
            encoding="utf-8",
        )
        (candidate / "slot-marker.txt").write_text(version, encoding="utf-8")

    assert install_txn.InstallTransaction.recover_incomplete(tmp_path) == []
    assert not (tmp_path / install_txn.APP_DIR_NAME).exists()
    assert (backup_dir / "slot-marker.txt").read_text(encoding="utf-8") == "8.1.0"
    assert (new_dir / "slot-marker.txt").read_text(encoding="utf-8") == "malformed"


def test_recovery_treats_a_dangling_reparse_entry_as_a_present_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_dir = tmp_path / install_txn.APP_BACKUP_DIR_NAME
    metadata_dir = backup_dir / "bomana"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "metadata.py").write_text('__version__ = "8.1.0"\n', encoding="utf-8")
    dangling_new = tmp_path / f"{install_txn.APP_DIR_NAME}_new"
    real_lexists = install_txn.os.path.lexists
    monkeypatch.setattr(
        install_txn.os.path,
        "lexists",
        lambda path: Path(path) == dangling_new or real_lexists(path),
    )

    assert install_txn.InstallTransaction.recover_incomplete(tmp_path) == []
    assert backup_dir.exists()
    assert not (tmp_path / install_txn.APP_DIR_NAME).exists()


def test_release_manifest_v1_and_signed_fields_are_unchanged() -> None:
    app_schema = json.loads(
        (ROOT / "docs/specs/schemas/app-manifest.schema.json").read_text(encoding="utf-8")
    )
    launcher_schema = json.loads(
        (ROOT / "docs/specs/schemas/launcher-manifest.schema.json").read_text(encoding="utf-8")
    )

    assert (
        tuple(app_schema["x-signed-fields"])
        == (
            "schema_version",
            "channel",
            "app_version",
            "min_launcher_version",
            "entrypoint",
            "package_asset",
            "package_sha256",
        )
        == launcher_core._APP_MANIFEST_SIGNATURE_FIELDS
    )
    assert (
        tuple(launcher_schema["x-signed-fields"])
        == (
            "schema_version",
            "launcher_version",
            "launcher_asset",
            "launcher_sha256",
            "launcher_size_bytes",
        )
        == launcher_core._LAUNCHER_MANIFEST_SIGNATURE_FIELDS
    )
    assert app_schema["properties"]["schema_version"]["minimum"] == 1
    assert launcher_schema["properties"]["schema_version"]["minimum"] == 1
    assert "min_app_version" not in app_schema["properties"]
    assert "min_app_version" not in launcher_schema["properties"]
