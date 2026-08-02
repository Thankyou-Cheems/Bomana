from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from bomana_version import (
    APP_REQUIRED_LAUNCHER_VERSION,
    MIN_SUPPORTED_APP_VERSION,
    MIN_SUPPORTED_LAUNCHER_VERSION,
    VersionCompatibilityError,
    parse_strict_version,
    require_exact_version,
    require_minimum_version,
    validate_app_launcher_identity,
)

ROOT = Path(__file__).resolve().parents[1]


def test_shared_version_boundary_accepts_only_strict_ascii_identity() -> None:
    assert MIN_SUPPORTED_APP_VERSION == "8.0.0"
    assert MIN_SUPPORTED_LAUNCHER_VERSION == "3.0.0"
    assert APP_REQUIRED_LAUNCHER_VERSION == "3.4.0"
    assert parse_strict_version("8.0.0") == (8, 0, 0)
    assert require_minimum_version("8.0.1", "8.0.0") == "8.0.1"
    assert require_exact_version("8.0.0", "8.0.0") == "8.0.0"

    for malformed in (True, 8, " 8.0.0", "8.0.0 ", "08.0.0", "8.0.0-rc1"):
        with pytest.raises((TypeError, ValueError)):
            parse_strict_version(malformed)


def test_app_launcher_identity_has_one_narrow_source_exception() -> None:
    assert (
        validate_app_launcher_identity(
            None,
            source_development="1",
            frozen=False,
        )
        is None
    )

    with pytest.raises(VersionCompatibilityError, match="身份缺失"):
        validate_app_launcher_identity(None, source_development="0", frozen=False)
    with pytest.raises(VersionCompatibilityError, match="身份缺失"):
        validate_app_launcher_identity(None, source_development="1", frozen=True)
    with pytest.raises(VersionCompatibilityError, match="格式无效"):
        validate_app_launcher_identity(" 3.0.0", source_development="1", frozen=False)
    with pytest.raises(VersionCompatibilityError, match="格式无效"):
        validate_app_launcher_identity("", source_development="1", frozen=False)
    with pytest.raises(VersionCompatibilityError, match="过旧"):
        validate_app_launcher_identity("2.99.99", source_development="1", frozen=False)
    with pytest.raises(VersionCompatibilityError, match="过旧"):
        validate_app_launcher_identity("3.2.2", source_development="1", frozen=False)
    assert (
        validate_app_launcher_identity(
            "3.4.0",
            source_development="0",
            frozen=True,
        )
        == "3.4.0"
    )


def test_app_entry_rejects_missing_identity_before_runtime_initialization(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("BOMANA_LAUNCHER_VERSION", None)
    env.pop("BOMANA_SOURCE_DEVELOPMENT", None)
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(ROOT / "Bomana.pyw")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode != 0
    assert "启动器身份缺失" in (result.stdout + result.stderr)
    assert not (tmp_path / ".wttimer_diagnostics.log").exists()


def test_app_entry_rejects_old_launcher_before_runtime_initialization(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["BOMANA_LAUNCHER_VERSION"] = "3.2.2"
    env["BOMANA_SOURCE_DEVELOPMENT"] = "1"
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(ROOT / "Bomana.pyw")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode != 0
    assert "启动器版本过旧" in (result.stdout + result.stderr)
    assert "要求 >= v3.4.0" in (result.stdout + result.stderr)
    assert not (tmp_path / ".wttimer_diagnostics.log").exists()
