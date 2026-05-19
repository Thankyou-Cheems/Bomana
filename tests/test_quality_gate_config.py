from pathlib import Path


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
