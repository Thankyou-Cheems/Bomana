from pathlib import Path

import pytest

from launcher import core as launcher_core
from launcher.install_txn import (
    read_local_app_version,
    require_compatible_app_version,
    validate_app_package_root,
)


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
    assert (
        launcher_core.parse_launcher_version_from_asset_name(
            "Bomana_launcher_v1.6.0_test-test-20260804T041413Z.exe"
        )
        == "1.6.0"
    )
    assert (
        launcher_core.parse_launcher_version_from_asset_name("Bomana_launcher_v1.6.0_candidate.exe")
        == ""
    )

    nested = tmp_path / "pkg"
    nested.mkdir()
    (nested / "Bomana.pyw").write_text("# app\n", encoding="utf-8")
    assert launcher_core.normalize_package_root(tmp_path, "Bomana.pyw") == nested


def test_ed25519_matches_rfc8032_empty_message_vector() -> None:
    private_key = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    public_key = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    expected_signature = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )

    assert launcher_core.ed25519_public_key_from_private_key(private_key) == (
        "11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo="
    )
    signature = launcher_core.ed25519_sign(b"", private_key)

    assert signature == expected_signature
    assert launcher_core.ed25519_verify(b"", signature, public_key)


def test_release_manifest_signature_rejects_tampering() -> None:
    private_key = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    public_key = launcher_core.ed25519_public_key_from_private_key(private_key)
    manifest = {
        "schema_version": 2,
        "channel": "Enhanced",
        "app_version": "6.14.4",
        "min_launcher_version": "2.0.0",
        "entrypoint": "Bomana.pyw",
        "package_asset": "Bomana_app_Enhanced_v6.14.4.zip",
        "package_sha256": "a" * 64,
        "changelog_asset": "CHANGELOG_Enhanced_v6.14.4.md",
        "changelog_sha256": "c" * 64,
    }
    signed = launcher_core.sign_release_manifest(
        manifest,
        private_key,
        key_id="test-key",
    )

    launcher_core.verify_release_manifest_signature(
        signed,
        public_keys={"test-key": public_key},
    )
    signed["package_url"] = "https://example.invalid/app.zip"

    launcher_core.verify_release_manifest_signature(
        signed,
        public_keys={"test-key": public_key},
    )
    signed["package_sha256"] = "b" * 64

    with pytest.raises(RuntimeError, match="发布签名校验失败"):
        launcher_core.verify_release_manifest_signature(
            signed,
            public_keys={"test-key": public_key},
        )


def test_release_manifest_signature_rejects_kind_confusion() -> None:
    private_key = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    public_key = launcher_core.ed25519_public_key_from_private_key(private_key)
    signed = launcher_core.sign_release_manifest(
        {
            "schema_version": 2,
            "channel": "Enhanced",
            "app_version": "6.14.4",
            "min_launcher_version": "2.0.0",
            "entrypoint": "Bomana.pyw",
            "package_asset": "Bomana_app_Enhanced_v6.14.4.zip",
            "package_sha256": "a" * 64,
            "changelog_asset": "CHANGELOG_Enhanced_v6.14.4.md",
            "changelog_sha256": "c" * 64,
        },
        private_key,
        key_id="test-key",
    )
    signed.update(
        {
            "launcher_version": "9.9.9",
            "launcher_asset": "Bomana_launcher_v9.9.9.exe",
            "launcher_sha256": "b" * 64,
            "launcher_size_bytes": 123,
        }
    )

    with pytest.raises(RuntimeError, match="不能同时包含"):
        launcher_core.verify_release_manifest_signature(
            signed,
            public_keys={"test-key": public_key},
            expected_kind="launcher",
        )


def test_launcher_install_reads_metadata_version(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    package_dir = app_dir / "bomana"
    config_dir = package_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "__init__.py").write_text(
        "from bomana import metadata as _metadata\n__version__ = _metadata.__version__\n",
        encoding="utf-8",
    )
    (package_dir / "metadata.py").write_text('__version__ = "8.0.0"\n', encoding="utf-8")

    assert read_local_app_version(app_dir) == "8.0.0"
    assert require_compatible_app_version(app_dir) == "8.0.0"


@pytest.mark.parametrize("version", ["7.99.99", " 8.0.0", "08.0.0", "8.0.0-rc1"])
def test_launcher_install_rejects_incompatible_candidate_identity(
    tmp_path: Path,
    version: str,
) -> None:
    app_dir = tmp_path / "app"
    package_dir = app_dir / "bomana"
    package_dir.mkdir(parents=True)
    (package_dir / "metadata.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="(格式无效|过旧)"):
        require_compatible_app_version(app_dir)


def test_launcher_install_rejects_legacy_config_py_marker(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    package_dir = app_dir / "bomana"
    package_dir.mkdir(parents=True)
    (app_dir / "Bomana.pyw").write_text("# entry\n", encoding="utf-8")
    (app_dir / "bomana_version.py").write_text("# boundary\n", encoding="utf-8")
    (package_dir / "metadata.py").write_text('__version__ = "7.0.0"\n', encoding="utf-8")
    (package_dir / "config.py").write_text('__version__ = "7.0.0"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="bomana/config/__init__\\.py"):
        validate_app_package_root(app_dir, "Bomana.pyw")


def test_launcher_install_requires_shared_version_boundary_in_app_package(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    config_dir = app_dir / "bomana" / "config"
    config_dir.mkdir(parents=True)
    (app_dir / "Bomana.pyw").write_text("# entry\n", encoding="utf-8")
    (config_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "bomana" / "metadata.py").write_text(
        '__version__ = "8.0.0"\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="bomana_version\\.py"):
        validate_app_package_root(app_dir, "Bomana.pyw")
