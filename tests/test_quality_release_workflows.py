import importlib.util
from pathlib import Path

import pytest

from bomana import metadata

ROOT = Path(__file__).resolve().parents[1]


def load_tool_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tencent_deploy_workflow_is_manual_only() -> None:
    workflow = (ROOT / ".github/workflows/deploy-manifests-to-server.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "workflow_run:" not in workflow
    assert "Build and Release Bomana Portable" not in workflow


def test_build_release_workflow_reads_version_from_metadata_without_dev_fallback() -> None:
    workflow = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")

    assert "bomana/metadata.py" in workflow
    assert 'bomana/config.py || echo "dev"' not in workflow
    assert "无法从 bomana/metadata.py 提取 __version__" in workflow


def test_local_deploy_script_validates_required_assets(tmp_path: Path) -> None:
    script_path = ROOT / "tools/deploy_update_assets.py"
    spec = importlib.util.spec_from_file_location("deploy_update_assets", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(FileNotFoundError, match="Bomana_app_Enhanced_v9.9.9.zip"):
        module.required_assets(tmp_path, "app", "9.9.9", "1.0.0")


def test_local_deploy_script_accepts_build_portable_all_checksum_names(tmp_path: Path) -> None:
    deploy = load_tool_module("deploy_update_assets_all", "tools/deploy_update_assets.py")
    launcher_version = "2.0.0"

    for channel in deploy.CHANNELS:
        (tmp_path / f"Bomana_app_{channel}_v{metadata.__version__}.zip").touch()
        (tmp_path / f"manifest_{channel}.json").touch()
        (tmp_path / f"checksums_app_{channel}.txt").touch()
    (tmp_path / f"Bomana_launcher_v{launcher_version}.exe").touch()
    (tmp_path / "launcher_manifest.json").touch()
    (tmp_path / "checksums_launcher.txt").touch()

    assets = deploy.required_assets(tmp_path, "all", metadata.__version__, launcher_version)

    assert tmp_path / "checksums_app_Enhanced.txt" in assets
    assert tmp_path / "checksums_launcher.txt" in assets


def test_build_portable_rejects_app_version_mismatch() -> None:
    build_portable = load_tool_module("build_portable_app_version", "tools/build_portable.py")

    build_portable.validate_requested_version(
        metadata.__version__,
        "app",
        metadata.__version__,
        "2.0.0",
    )
    with pytest.raises(RuntimeError, match="app expected"):
        build_portable.validate_requested_version(
            "9.9.9",
            "app",
            metadata.__version__,
            "2.0.0",
        )


def test_build_portable_rejects_launcher_version_mismatch() -> None:
    build_portable = load_tool_module("build_portable_launcher_version", "tools/build_portable.py")
    launcher_version = "2.0.0"

    build_portable.validate_requested_version(
        launcher_version,
        "launcher",
        metadata.__version__,
        launcher_version,
    )
    with pytest.raises(RuntimeError, match="launcher expected"):
        build_portable.validate_requested_version(
            "9.9.9",
            "launcher",
            metadata.__version__,
            launcher_version,
        )


def test_build_portable_all_rejects_ambiguous_single_version() -> None:
    build_portable = load_tool_module("build_portable_all_version", "tools/build_portable.py")

    with pytest.raises(RuntimeError, match="launcher expected"):
        build_portable.validate_requested_version(
            metadata.__version__,
            "all",
            metadata.__version__,
            "2.0.0",
        )


def test_build_portable_writes_deployable_checksum_names(tmp_path: Path) -> None:
    build_portable = load_tool_module("build_portable_checksums", "tools/build_portable.py")
    app_zip = tmp_path / f"Bomana_app_Enhanced_v{metadata.__version__}.zip"
    launcher = tmp_path / "Bomana_launcher_v2.0.0.exe"
    app_zip.write_bytes(b"app")
    launcher.write_bytes(b"launcher")

    app_checksum = build_portable.write_checksum_info(
        tmp_path,
        "Enhanced",
        metadata.__version__,
        None,
        app_zip,
        None,
        "app",
    )
    launcher_checksum = build_portable.write_checksum_info(
        tmp_path,
        "Universal",
        None,
        "2.0.0",
        None,
        launcher,
        "launcher",
    )

    assert app_checksum.name == "checksums_app_Enhanced.txt"
    assert launcher_checksum.name == "checksums_launcher.txt"
    assert not (tmp_path / "checksums_portable_Enhanced.txt").exists()
