"""Strict App/Launcher compatibility boundary shared by both runtimes."""

from __future__ import annotations

import os
import re
import sys
from typing import Final

MIN_SUPPORTED_APP_VERSION: Final = "8.0.0"
MIN_SUPPORTED_LAUNCHER_VERSION: Final = "3.0.0"

_STRICT_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$",
    re.ASCII,
)


class VersionCompatibilityError(RuntimeError):
    """A stable, user-visible compatibility rejection."""


def parse_strict_version(value: object) -> tuple[int, int, int]:
    """Parse one bounded ASCII ``X.Y.Z`` identity without normalization."""

    if not isinstance(value, str):
        raise TypeError("version identity must be a string")
    match = _STRICT_VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError("version identity must be strict ASCII X.Y.Z")
    return tuple(int(part) for part in match.groups())


def require_minimum_version(
    value: object,
    minimum: object,
    *,
    identity_name: str = "版本",
) -> str:
    """Return ``value`` when strict and at least ``minimum``; otherwise fail closed."""

    try:
        parsed_value = parse_strict_version(value)
    except (TypeError, ValueError) as exc:
        raise VersionCompatibilityError(f"{identity_name}格式无效") from exc
    try:
        parsed_minimum = parse_strict_version(minimum)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("内部最低兼容版本配置无效") from exc
    if parsed_value < parsed_minimum:
        raise VersionCompatibilityError(f"{identity_name}过旧：v{value}，要求 >= v{minimum}")
    return str(value)


def require_exact_version(
    value: object,
    expected: object,
    *,
    identity_name: str = "应用版本",
) -> str:
    """Require two independently strict identities to be exactly equal."""

    try:
        parsed_value = parse_strict_version(value)
    except (TypeError, ValueError) as exc:
        raise VersionCompatibilityError(f"{identity_name}格式无效") from exc
    try:
        parsed_expected = parse_strict_version(expected)
    except (TypeError, ValueError) as exc:
        raise VersionCompatibilityError("已验证签名清单版本格式无效") from exc
    if parsed_value != parsed_expected:
        raise VersionCompatibilityError(
            f"签名清单版本与暂存包版本不匹配：清单 v{expected}，包内 v{value}"
        )
    return str(value)


def validate_app_launcher_identity(
    launcher_version: object | None = None,
    *,
    source_development: object | None = None,
    frozen: bool | None = None,
) -> str | None:
    """Validate the launcher identity before the App imports runtime components.

    Only a missing identity may be bypassed, and only by the exact development
    marker in a demonstrably non-frozen process.
    """

    if launcher_version is None:
        launcher_version = os.environ.get("BOMANA_LAUNCHER_VERSION")
    if source_development is None:
        source_development = os.environ.get("BOMANA_SOURCE_DEVELOPMENT")
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    if launcher_version is None:
        if source_development == "1" and not frozen:
            return None
        raise VersionCompatibilityError("启动器身份缺失")

    return require_minimum_version(
        launcher_version,
        MIN_SUPPORTED_LAUNCHER_VERSION,
        identity_name="启动器版本",
    )
