import subprocess
import sys
import tomllib
from pathlib import Path


def read_pyproject() -> dict:
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))


def test_smoke_script_runs_pytest_suite() -> None:
    script = Path("tools/scripts/check_smoke.bat").read_text(encoding="utf-8")

    assert "pytest" in script
    assert "unittest discover" not in script


def test_gitignore_does_not_hide_new_tests() -> None:
    ignored_patterns = {
        line.strip()
        for line in Path(".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "tests/" not in ignored_patterns
    assert "test_*.py" not in ignored_patterns


def test_pytest_uses_sys_capture_for_wsl_windows_temp_stability() -> None:
    pyproject = read_pyproject()
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]

    assert "--capture=sys" in addopts.split()


def test_ruff_defaults_include_runtime_annotation_rules() -> None:
    selected = set(read_pyproject()["tool"]["ruff"]["lint"]["select"])

    assert {"RUF012", "RUF013"} <= selected


def test_asset_generator_dependencies_are_declared() -> None:
    pyproject = read_pyproject()
    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]
    script = Path("tools/generate_ui_assets.py").read_text(encoding="utf-8")

    assert any(dep.lower().startswith("fonttools") for dep in dev_dependencies)
    assert "# /// script" in script
    assert '"fonttools>=4.0.0"' in script


def test_asset_generator_is_importable_without_repo_root_on_initial_path() -> None:
    code = """
import importlib.util
import pathlib
import sys

root = pathlib.Path.cwd().resolve()
script_path = root / "tools" / "generate_ui_assets.py"
sys.path = [
    str(root / "tools"),
    *[path for path in sys.path if path not in ("", str(root), str(root / "tools"))],
]
spec = importlib.util.spec_from_file_location("generate_ui_assets", script_path)
assert spec is not None
assert spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.FONT_FAMILY == "Bomana UI Sans"
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
