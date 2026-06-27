from pathlib import Path

from bomana import launcher_core
from bomana.launcher_install import read_local_app_version


def test_launcher_core_version_and_source_helpers() -> None:
    assert launcher_core.normalize_download_source_mode("tencent") == "primary"
    assert launcher_core.download_source_label("github") == "GitHub"
    assert launcher_core.version_is_newer("6.14.1", "6.14.0")
    assert launcher_core.version_is_older("1.5.0", "1.6.0")
    assert launcher_core.format_min_launcher_requirement("1.6.0") == "启动器 v1.6.0+"


def test_launcher_core_version_comparison_handles_prerelease_metadata() -> None:
    assert launcher_core.extract_version_tuple("2.0.0-rc.1") == (2, 0, 0)
    assert launcher_core.extract_version_tuple("2.0.0+build.5") == (2, 0, 0)
    assert not launcher_core.version_is_newer("2.0.0-rc.1", "2.0.0")
    assert launcher_core.version_is_newer("2.0.0", "2.0.0-rc.1")
    assert not launcher_core.version_is_older("2.0.0", "2.0.0-rc.1")


def test_launcher_core_finds_assets_and_package_root(tmp_path: Path) -> None:
    assets = [{"name": "manifest_Enhanced.json"}, {"name": "Bomana_launcher_v1.6.0.exe"}]
    assert launcher_core.find_asset(assets, "MANIFEST_ENHANCED.JSON") == assets[0]
    assert launcher_core.find_launcher_asset(assets) == assets[1]
    assert (
        launcher_core.parse_launcher_version_from_asset_name("Bomana_launcher_v1.6.0.exe")
        == "1.6.0"
    )

    nested = tmp_path / "pkg"
    nested.mkdir()
    (nested / "Bomana.pyw").write_text("# app\n", encoding="utf-8")
    assert launcher_core.normalize_package_root(tmp_path, "Bomana.pyw") == nested


def test_launcher_install_reads_metadata_version(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    package_dir = app_dir / "bomana"
    package_dir.mkdir(parents=True)
    (package_dir / "config.py").write_text(
        "from bomana import metadata as _metadata\n__version__ = _metadata.__version__\n",
        encoding="utf-8",
    )
    (package_dir / "metadata.py").write_text('__version__ = "7.0.0"\n', encoding="utf-8")

    assert read_local_app_version(app_dir) == "7.0.0"
