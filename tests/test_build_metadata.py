import importlib.util
import json
from pathlib import Path

import pytest

from bomana import launcher_core, metadata

ROOT = Path(__file__).resolve().parents[1]


def load_tool_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_portable_build_reads_version_from_metadata() -> None:
    build_portable = load_tool_module("build_portable", "tools/build_portable.py")
    metadata_text = (ROOT / "bomana" / "metadata.py").read_text(encoding="utf-8")

    assert build_portable.read_version(metadata_text) == metadata.__version__
    assert (
        build_portable.read_min_launcher_version(metadata_text)
        == metadata.PORTABLE_MIN_LAUNCHER_VERSION
    )


TEST_SIGNING_PRIVATE_KEY = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"


def test_launcher_manifest_records_size(tmp_path: Path, monkeypatch) -> None:
    build_portable = load_tool_module("build_portable_manifest", "tools/build_portable.py")
    monkeypatch.setenv(build_portable.SIGNING_PRIVATE_KEY_ENV, TEST_SIGNING_PRIVATE_KEY)
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


def test_build_portable_generates_and_restores_launcher_public_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    build_portable = load_tool_module("build_portable_release_keys", "tools/build_portable.py")
    monkeypatch.setenv(build_portable.SIGNING_PRIVATE_KEY_ENV, TEST_SIGNING_PRIVATE_KEY)
    monkeypatch.setenv(build_portable.SIGNING_KEY_ID_ENV, "test-key")
    (tmp_path / "bomana").mkdir()

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

    assert create_version_info.read_version(ROOT / "bomana" / "config.py") == metadata.__version__
