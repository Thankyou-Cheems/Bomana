import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from bomana import metadata
from launcher import core as launcher_core

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


def load_tool_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized_dependency_name(requirement: str) -> str:
    match = DEPENDENCY_NAME_RE.match(requirement)
    assert match is not None
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


def test_portable_build_reads_version_from_metadata() -> None:
    build_portable = load_tool_module("build_portable", "tools/build_portable.py")
    metadata_text = (ROOT / "bomana" / "metadata.py").read_text(encoding="utf-8")

    assert build_portable.read_version(metadata_text) == metadata.__version__
    assert (
        build_portable.read_min_launcher_version(metadata_text)
        == metadata.PORTABLE_MIN_LAUNCHER_VERSION
    )


def test_build_portable_script_runs_without_pythonpath() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"

    result = subprocess.run(
        [sys.executable, "tools/build_portable.py", "--help"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--target" in result.stdout


def test_app_package_bundles_zero_install_hotkey_broker_and_checksum(tmp_path: Path) -> None:
    build_portable = load_tool_module("build_portable_broker", "tools/build_portable.py")
    root = tmp_path / "repo"
    output = tmp_path / "dist"
    (root / "bomana").mkdir(parents=True)
    output.mkdir()
    (root / "Bomana.pyw").write_text("pass\n", encoding="utf-8")
    (root / "bomana" / "__init__.py").write_text("", encoding="utf-8")
    (root / "bomana" / "data").mkdir()
    (root / "bomana" / "data" / "weapon_fire_control.json").write_text("{}\n", encoding="utf-8")
    broker = tmp_path / "BomanaHotkeyBroker.exe"
    broker.write_bytes(b"native broker payload")

    package = build_portable.build_app_zip(root, "Lite", "1.2.3", output, broker)

    with zipfile.ZipFile(package) as archive:
        assert "bomana/bin/BomanaHotkeyBroker.exe" in archive.namelist()
        assert "bomana/data/weapon_fire_control.json" not in archive.namelist()
        checksum = archive.read("bomana/bin/BomanaHotkeyBroker.sha256").decode("ascii")
        assert checksum == f"{build_portable.sha256_file(broker)}  BomanaHotkeyBroker.exe\n"


def test_enhanced_app_package_bundles_weapon_catalog_and_shared_schema(tmp_path: Path) -> None:
    build_portable = load_tool_module("build_portable_weapon_data", "tools/build_portable.py")
    root = tmp_path / "repo"
    output = tmp_path / "dist"
    data_dir = root / "bomana" / "data"
    schema_dir = root / "docs" / "specs" / "schemas"
    data_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)
    output.mkdir()
    (root / "Bomana.pyw").write_text("pass\n", encoding="utf-8")
    (root / "bomana" / "__init__.py").write_text("", encoding="utf-8")
    (data_dir / "weapon_fire_control.json").write_text("{}\n", encoding="utf-8")
    (schema_dir / "weapon-fire-control.schema.json").write_text("{}\n", encoding="utf-8")
    broker = tmp_path / "BomanaHotkeyBroker.exe"
    broker.write_bytes(b"native broker payload")

    package = build_portable.build_app_zip(root, "Enhanced", "1.2.3", output, broker)

    with zipfile.ZipFile(package) as archive:
        assert "bomana/data/weapon_fire_control.json" in archive.namelist()
        assert "docs/specs/schemas/weapon-fire-control.schema.json" in archive.namelist()


@pytest.mark.parametrize("variant", ["Enhanced", "Standard", "Lite"])
def test_all_app_variants_bundle_web_cockpit(tmp_path: Path, variant: str) -> None:
    build_portable = load_tool_module(
        f"build_portable_web_cockpit_{variant.lower()}",
        "tools/build_portable.py",
    )
    root = tmp_path / "repo"
    output = tmp_path / "dist"
    web_module_dir = root / "bomana" / "web"
    web_asset_dir = root / "bomana" / "assets" / "web"
    data_dir = root / "bomana" / "data"
    schema_dir = root / "docs" / "specs" / "schemas"
    for directory in (web_module_dir, web_asset_dir, data_dir, schema_dir, output):
        directory.mkdir(parents=True, exist_ok=True)
    (root / "Bomana.pyw").write_text("pass\n", encoding="utf-8")
    (root / "bomana" / "__init__.py").write_text("", encoding="utf-8")
    for name in ("__init__.py", "server.py", "snapshot.py"):
        (web_module_dir / name).write_text("", encoding="utf-8")
    for name in ("index.html", "dashboard.css", "dashboard.js", "favicon.svg"):
        (web_asset_dir / name).write_text(name, encoding="utf-8")
    (data_dir / "weapon_fire_control.json").write_text("{}\n", encoding="utf-8")
    (schema_dir / "weapon-fire-control.schema.json").write_text("{}\n", encoding="utf-8")
    broker = tmp_path / "BomanaHotkeyBroker.exe"
    broker.write_bytes(b"native broker payload")

    package = build_portable.build_app_zip(root, variant, "1.2.3", output, broker)

    expected = {
        "bomana/web/__init__.py",
        "bomana/web/server.py",
        "bomana/web/snapshot.py",
        "bomana/assets/web/index.html",
        "bomana/assets/web/dashboard.css",
        "bomana/assets/web/dashboard.js",
        "bomana/assets/web/favicon.svg",
    }
    with zipfile.ZipFile(package) as archive:
        assert expected <= set(archive.namelist())


def test_enhanced_app_package_rejects_missing_weapon_assets(tmp_path: Path) -> None:
    build_portable = load_tool_module(
        "build_portable_missing_weapon_data", "tools/build_portable.py"
    )
    root = tmp_path / "repo"
    output = tmp_path / "dist"
    (root / "bomana").mkdir(parents=True)
    output.mkdir()
    (root / "Bomana.pyw").write_text("pass\n", encoding="utf-8")
    (root / "bomana" / "__init__.py").write_text("", encoding="utf-8")
    broker = tmp_path / "BomanaHotkeyBroker.exe"
    broker.write_bytes(b"native broker payload")

    with pytest.raises(RuntimeError, match="missing Enhanced weapon fire-control assets"):
        build_portable.build_app_zip(root, "Enhanced", "1.2.3", output, broker)


def test_packaged_launcher_runtime_contract_matches_pyproject() -> None:
    build_portable = load_tool_module(
        "build_portable_runtime_contract",
        "tools/build_portable.py",
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    pyproject_dependencies = {
        normalized_dependency_name(dependency) for dependency in project["dependencies"]
    }
    launcher_dependencies = {
        normalized_dependency_name(dependency)
        for dependency in build_portable.packaged_launcher_runtime_dependency_names()
    }
    runtime_args = build_portable.pyinstaller_launcher_runtime_args()

    assert launcher_dependencies == pyproject_dependencies
    assert project["requires-python"] == build_portable.PACKAGED_LAUNCHER_REQUIRES_PYTHON
    assert (
        build_portable.PACKAGED_LAUNCHER_RUNTIME_MIN_LAUNCHER_VERSION
        == metadata.PORTABLE_MIN_LAUNCHER_VERSION
    )
    assert runtime_args == [
        "--hidden-import",
        "http.cookies",
        "--hidden-import",
        "http.server",
        "--hidden-import",
        "ipaddress",
        "--hidden-import",
        "mimetypes",
        "--hidden-import",
        "pystray._win32",
        "--hidden-import",
        "socketserver",
        "--hidden-import",
        "winsound",
        "--hidden-import",
        "launcher.release_public_keys",
        "--collect-submodules",
        "PIL",
        "--collect-submodules",
        "pystray",
        "--collect-all",
        "requests",
        "--collect-all",
        "certifi",
    ]


TEST_SIGNING_PRIVATE_KEY = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
TEST_SIGNING_PUBLIC_KEY = "11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo="


def test_launcher_manifest_records_size(tmp_path: Path, monkeypatch) -> None:
    build_portable = load_tool_module("build_portable_manifest", "tools/build_portable.py")
    monkeypatch.setenv(build_portable.SIGNING_PRIVATE_KEY_ENV, TEST_SIGNING_PRIVATE_KEY)
    monkeypatch.setenv(build_portable.SIGNING_PUBLIC_KEY_ENV, TEST_SIGNING_PUBLIC_KEY)
    monkeypatch.setenv(build_portable.SIGNING_KEY_ID_ENV, "test-key")

    manifest_path = build_portable.write_launcher_manifest(
        tmp_path,
        "2.0.0",
        "Bomana_launcher_v2.0.0.exe",
        "abc123",
        12345,
    )

    manifest = manifest_path.read_text(encoding="utf-8")
    assert '"launcher_size_bytes": 12345' in manifest
    parsed = json.loads(manifest)
    launcher_core.verify_release_manifest_signature(
        parsed,
        public_keys={
            "test-key": launcher_core.ed25519_public_key_from_private_key(TEST_SIGNING_PRIVATE_KEY)
        },
    )


def test_build_portable_refuses_unsigned_manifests(tmp_path: Path, monkeypatch) -> None:
    build_portable = load_tool_module("build_portable_unsigned", "tools/build_portable.py")
    monkeypatch.delenv(build_portable.SIGNING_PRIVATE_KEY_ENV, raising=False)

    with pytest.raises(RuntimeError, match=build_portable.SIGNING_PRIVATE_KEY_ENV):
        build_portable.write_manifest(
            tmp_path,
            "Enhanced",
            metadata.__version__,
            f"Bomana_app_Enhanced_v{metadata.__version__}.zip",
            "a" * 64,
            metadata.PORTABLE_MIN_LAUNCHER_VERSION,
        )


def test_build_portable_rejects_signing_key_mismatch(tmp_path: Path, monkeypatch) -> None:
    build_portable = load_tool_module("build_portable_key_mismatch", "tools/build_portable.py")
    monkeypatch.setenv(build_portable.SIGNING_PRIVATE_KEY_ENV, TEST_SIGNING_PRIVATE_KEY)
    monkeypatch.setenv(build_portable.SIGNING_PUBLIC_KEY_ENV, "A" * 44)

    with pytest.raises(RuntimeError, match=build_portable.SIGNING_PUBLIC_KEY_ENV):
        build_portable.write_manifest(
            tmp_path,
            "Enhanced",
            metadata.__version__,
            f"Bomana_app_Enhanced_v{metadata.__version__}.zip",
            "a" * 64,
            metadata.PORTABLE_MIN_LAUNCHER_VERSION,
        )


def test_build_portable_generates_and_restores_launcher_public_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    build_portable = load_tool_module("build_portable_release_keys", "tools/build_portable.py")
    monkeypatch.setenv(build_portable.SIGNING_PRIVATE_KEY_ENV, TEST_SIGNING_PRIVATE_KEY)
    monkeypatch.setenv(build_portable.SIGNING_PUBLIC_KEY_ENV, TEST_SIGNING_PUBLIC_KEY)
    monkeypatch.setenv(build_portable.SIGNING_KEY_ID_ENV, "test-key")
    (tmp_path / "launcher").mkdir()

    path, original = build_portable.write_release_public_keys_module(tmp_path)

    assert original is None
    assert path.name == "release_public_keys.py"
    assert "test-key" in path.read_text(encoding="utf-8")
    assert launcher_core.ed25519_public_key_from_private_key(TEST_SIGNING_PRIVATE_KEY) in (
        path.read_text(encoding="utf-8")
    )

    build_portable.restore_release_public_keys_module(path, original)

    assert not path.exists()


def test_version_info_falls_back_from_config_to_metadata() -> None:
    create_version_info = load_tool_module("create_version_info", "tools/create_version_info.py")

    assert create_version_info.read_version(ROOT / "bomana" / "metadata.py") == metadata.__version__
    assert (
        create_version_info.read_version(ROOT / "bomana" / "config" / "__init__.py")
        == metadata.__version__
    )
    assert create_version_info.read_version(ROOT / "bomana" / "config.py") == "0.0.0"
