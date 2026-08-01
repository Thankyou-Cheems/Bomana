import base64
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
from bomana_version import APP_REQUIRED_LAUNCHER_VERSION
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


def write_shared_app_runtime_assets(root: Path) -> None:
    (root / "bomana_version.py").write_text("# shared version boundary\n", encoding="utf-8")


def source_closure(root: Path) -> frozenset[str]:
    return frozenset(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )


def test_release_source_closure_detects_unexpected_package_file(tmp_path: Path) -> None:
    build_portable = load_tool_module(
        "build_portable_source_closure",
        "tools/build_portable.py",
    )
    root = tmp_path / "repo"
    tracked_asset = root / "bomana" / "assets" / "branding" / "app.png"
    tracked_asset.parent.mkdir(parents=True)
    tracked_asset.write_bytes(b"tracked")
    tracked = source_closure(root)
    unexpected = root / "bomana" / "assets" / "research" / "capture.txt"
    unexpected.parent.mkdir()
    unexpected.write_text("sentinel", encoding="utf-8")

    assert build_portable._unexpected_release_files(
        root,
        "all",
        "Standard",
        tracked,
    ) == ("bomana/assets/research/capture.txt",)


def test_portable_build_reads_version_from_metadata() -> None:
    build_portable = load_tool_module("build_portable", "tools/build_portable.py")
    metadata_text = (ROOT / "bomana" / "metadata.py").read_text(encoding="utf-8")

    assert build_portable.read_version(metadata_text) == metadata.__version__
    assert (
        build_portable.read_min_launcher_version(metadata_text)
        == metadata.PORTABLE_MIN_LAUNCHER_VERSION
    )
    boundary_text = (ROOT / "bomana_version.py").read_text(encoding="utf-8")
    assert (
        build_portable.validate_app_launcher_floor(metadata_text, boundary_text)
        == APP_REQUIRED_LAUNCHER_VERSION
    )


def test_portable_build_rejects_mismatched_app_launcher_floor() -> None:
    build_portable = load_tool_module("build_portable_floor", "tools/build_portable.py")

    with pytest.raises(RuntimeError, match="App Launcher floor mismatch"):
        build_portable.validate_app_launcher_floor(
            'PORTABLE_MIN_LAUNCHER_VERSION = "3.4.0"\n',
            'APP_REQUIRED_LAUNCHER_VERSION = "3.3.0"\n',
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
    (root / "bomana" / "data" / "visible_trajectory_references.json").write_text(
        "{}\n", encoding="utf-8"
    )
    write_shared_app_runtime_assets(root)
    broker = tmp_path / "BomanaHotkeyBroker.exe"
    broker.write_bytes(b"native broker payload")

    package = build_portable.build_app_zip(
        root,
        "Lite",
        "1.2.3",
        output,
        broker,
        source_closure(root),
    )

    with zipfile.ZipFile(package) as archive:
        assert "bomana/bin/BomanaHotkeyBroker.exe" in archive.namelist()
        assert "bomana/data/weapon_fire_control.json" not in archive.namelist()
        assert "bomana/data/visible_trajectory_references.json" not in archive.namelist()
        checksum = archive.read("bomana/bin/BomanaHotkeyBroker.sha256").decode("ascii")
        assert checksum == f"{build_portable.sha256_file(broker)}  BomanaHotkeyBroker.exe\n"


def test_app_package_renders_edition_profile_without_source_mutation(tmp_path: Path) -> None:
    build_portable = load_tool_module("build_portable_edition_profile", "tools/build_portable.py")
    root = tmp_path / "repo"
    output = tmp_path / "dist"
    config_dir = root / "bomana" / "config"
    config_dir.mkdir(parents=True)
    output.mkdir()
    (root / "Bomana.pyw").write_text("pass\n", encoding="utf-8")
    (root / "bomana" / "__init__.py").write_text("", encoding="utf-8")
    profile_path = config_dir / "feature_profile.py"
    source_profile = 'EDITION_CHANNEL = "Standard"\n'
    profile_path.write_text(source_profile, encoding="utf-8")
    write_shared_app_runtime_assets(root)
    broker = tmp_path / "BomanaHotkeyBroker.exe"
    broker.write_bytes(b"native broker payload")

    package = build_portable.build_app_zip(
        root,
        "Lite",
        "1.2.3",
        output,
        broker,
        source_closure(root),
    )

    with zipfile.ZipFile(package) as archive:
        packaged_profile = archive.read("bomana/config/feature_profile.py").decode("utf-8")
    assert packaged_profile == 'EDITION_CHANNEL = "Lite"\n'
    assert profile_path.read_text(encoding="utf-8") == source_profile


def test_public_builder_rejects_subscriber_edition(tmp_path: Path) -> None:
    build_portable = load_tool_module("build_portable_public_only", "tools/build_portable.py")
    root = tmp_path / "repo"
    output = tmp_path / "dist"
    (root / "bomana").mkdir(parents=True)
    output.mkdir()
    broker = tmp_path / "BomanaHotkeyBroker.exe"
    broker.write_bytes(b"native broker payload")

    with pytest.raises(ValueError, match="private closure"):
        build_portable.build_app_zip(
            root,
            "Enhanced",
            "1.2.3",
            output,
            broker,
            source_closure(root),
        )


SUBSCRIBER_PACKAGE_PATHS = {
    "bomana/core/ballistics.py",
    "bomana/core/offline_rigidbody_solver.py",
    "bomana/core/terrain_elevation.py",
    "bomana/core/weapon_solver.py",
    "bomana/ui/bombing_runtime.py",
    "bomana/web/__init__.py",
    "bomana/web/control.py",
    "bomana/web/server.py",
    "bomana/web/snapshot.py",
    "bomana/assets/web/index.html",
    "bomana/assets/web/dashboard.css",
    "bomana/assets/web/dashboard.js",
    "bomana/assets/web/qrcode.js",
    "bomana/assets/web/favicon.svg",
    "docs/specs/schemas/web-dashboard-command.schema.json",
    "docs/specs/schemas/web-dashboard-command-response.schema.json",
    "docs/specs/schemas/web-dashboard-control-state.schema.json",
}


def _seed_subscriber_package_tree(root: Path) -> None:
    core_dir = root / "bomana" / "core"
    ui_dir = root / "bomana" / "ui"
    web_module_dir = root / "bomana" / "web"
    web_asset_dir = root / "bomana" / "assets" / "web"
    data_dir = root / "bomana" / "data"
    schema_dir = root / "docs" / "specs" / "schemas"
    for directory in (core_dir, ui_dir, web_module_dir, web_asset_dir, data_dir, schema_dir):
        directory.mkdir(parents=True, exist_ok=True)
    (root / "Bomana.pyw").write_text("pass\n", encoding="utf-8")
    (root / "bomana" / "__init__.py").write_text("", encoding="utf-8")
    for name in ("__init__.py", "control.py", "server.py", "snapshot.py"):
        (web_module_dir / name).write_text("", encoding="utf-8")
    for name in (
        "ballistics.py",
        "offline_rigidbody_solver.py",
        "terrain_elevation.py",
        "weapon_solver.py",
    ):
        (core_dir / name).write_text("", encoding="utf-8")
    (ui_dir / "bombing_runtime.py").write_text("", encoding="utf-8")
    for name in ("index.html", "dashboard.css", "dashboard.js", "qrcode.js", "favicon.svg"):
        (web_asset_dir / name).write_text(name, encoding="utf-8")
    (data_dir / "weapon_fire_control.json").write_text("{}\n", encoding="utf-8")
    (data_dir / "visible_trajectory_references.json").write_text("{}\n", encoding="utf-8")
    (schema_dir / "weapon-fire-control.schema.json").write_text("{}\n", encoding="utf-8")
    write_shared_app_runtime_assets(root)


@pytest.mark.parametrize("variant", ["Standard", "Lite"])
def test_public_app_packages_omit_subscriber_closure(tmp_path: Path, variant: str) -> None:
    build_portable = load_tool_module(
        f"build_portable_subscriber_closure_{variant.lower()}",
        "tools/build_portable.py",
    )
    root = tmp_path / "repo"
    output = tmp_path / "dist"
    output.mkdir()
    _seed_subscriber_package_tree(root)
    broker = tmp_path / "BomanaHotkeyBroker.exe"
    broker.write_bytes(b"native broker payload")

    package = build_portable.build_app_zip(
        root,
        variant,
        "1.2.3",
        output,
        broker,
        source_closure(root),
    )

    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert "bomana_version.py" in names
        assert not (SUBSCRIBER_PACKAGE_PATHS & names)
        assert not any(name.startswith("bomana/web/") for name in names)
        assert not any(name.startswith("bomana/assets/web/") for name in names)
        assert not any(name.startswith("bomana/data/terrain-") for name in names)


def test_packaged_launcher_runtime_contract_matches_pyproject() -> None:
    build_portable = load_tool_module(
        "build_portable_runtime_contract",
        "tools/build_portable.py",
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["version"] == metadata.__version__

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
        "bomana_subscription_public_keys",
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
            "Standard",
            metadata.__version__,
            f"Bomana_app_Standard_v{metadata.__version__}.zip",
            "a" * 64,
            metadata.PORTABLE_MIN_LAUNCHER_VERSION,
            f"CHANGELOG_Standard_v{metadata.__version__}.md",
            "c" * 64,
        )


def test_build_portable_writes_version_specific_changelog(tmp_path: Path) -> None:
    build_portable = load_tool_module("build_portable_changelog", "tools/build_portable.py")
    root = tmp_path / "repo"
    output = tmp_path / "dist"
    root.mkdir()
    output.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [2.0.0]\n\n- new feature\n\n---\n## [1.0.0]\n\n- old\n",
        encoding="utf-8",
    )

    path = build_portable.write_changelog_asset(root, output, "Standard", "2.0.0")

    assert path.name == "CHANGELOG_Standard_v2.0.0.md"
    assert "new feature" in path.read_text(encoding="utf-8")
    assert "old" not in path.read_text(encoding="utf-8")


def test_build_portable_rejects_signing_key_mismatch(tmp_path: Path, monkeypatch) -> None:
    build_portable = load_tool_module("build_portable_key_mismatch", "tools/build_portable.py")
    monkeypatch.setenv(build_portable.SIGNING_PRIVATE_KEY_ENV, TEST_SIGNING_PRIVATE_KEY)
    monkeypatch.setenv(build_portable.SIGNING_PUBLIC_KEY_ENV, "A" * 44)

    with pytest.raises(RuntimeError, match=build_portable.SIGNING_PUBLIC_KEY_ENV):
        build_portable.write_manifest(
            tmp_path,
            "Standard",
            metadata.__version__,
            f"Bomana_app_Standard_v{metadata.__version__}.zip",
            "a" * 64,
            metadata.PORTABLE_MIN_LAUNCHER_VERSION,
            f"CHANGELOG_Standard_v{metadata.__version__}.md",
            "c" * 64,
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


def test_build_portable_generates_subscription_key_outside_source_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    build_portable = load_tool_module(
        "build_portable_subscription_keys",
        "tools/build_portable.py",
    )
    raw_public_key = base64.b64decode(TEST_SIGNING_PUBLIC_KEY, validate=True)
    public_key_spki = (
        base64.urlsafe_b64encode(bytes.fromhex("302a300506032b6570032100") + raw_public_key)
        .decode("ascii")
        .rstrip("=")
    )
    monkeypatch.setenv(build_portable.SUBSCRIPTION_PUBLIC_KEY_ENV, public_key_spki)
    monkeypatch.setenv(build_portable.SUBSCRIPTION_KEY_ID_ENV, "cheemspay-test")
    work_dir = tmp_path / "build"
    work_dir.mkdir()

    generated_dir, path = build_portable.write_subscription_public_keys_module(work_dir)

    assert path.parent == generated_dir
    assert tmp_path / "launcher" not in path.parents
    assert "cheemspay-test" in path.read_text(encoding="utf-8")
    assert public_key_spki in path.read_text(encoding="utf-8")


def test_version_info_falls_back_from_config_to_metadata() -> None:
    create_version_info = load_tool_module("create_version_info", "tools/create_version_info.py")

    assert create_version_info.read_version(ROOT / "bomana" / "metadata.py") == metadata.__version__
    assert (
        create_version_info.read_version(ROOT / "bomana" / "config" / "__init__.py")
        == metadata.__version__
    )
    assert create_version_info.read_version(ROOT / "bomana" / "config.py") == "0.0.0"
