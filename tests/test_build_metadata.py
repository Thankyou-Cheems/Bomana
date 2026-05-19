import importlib.util
from pathlib import Path

from bomana import metadata

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


def test_version_info_falls_back_from_config_to_metadata() -> None:
    create_version_info = load_tool_module("create_version_info", "tools/create_version_info.py")

    assert create_version_info.read_version(ROOT / "bomana" / "config.py") == metadata.__version__
