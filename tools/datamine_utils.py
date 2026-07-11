"""Shared helpers for Bomana datamine extraction tools."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

BOMBGUNS_SUBDIR = Path("aces.vromfs.bin_u") / "gamedata" / "weapons" / "bombguns"
FLIGHTMODELS_SUBDIR = Path("aces.vromfs.bin_u") / "gamedata" / "flightmodels"
WEAPONS_SUBDIR = Path("aces.vromfs.bin_u") / "gamedata" / "weapons"
ROCKETGUNS_SUBDIR = WEAPONS_SUBDIR / "rocketguns"
CONTAINERS_SUBDIR = WEAPONS_SUBDIR / "containers"
WEAPON_LOCALIZATION_FILE = Path("lang.vromfs.bin_u") / "lang" / "units_weaponry.csv"
_GIT_COMMAND_ERRORS = (OSError, subprocess.SubprocessError)
_SMALL_CALIBER_MM_RE = re.compile(r"(?<!\d)(\d{2,3})\s*_?mm(?![a-z])", re.IGNORECASE)


class SchemaValidationError(ValueError):
    """Raised when a generated datamine asset violates its canonical schema."""


def normalize_datamine_caliber_m(
    raw_caliber_m: float,
    *identity_values: str,
) -> tuple[float, dict[str, Any] | None]:
    """Correct a narrowly provable Datamine decimal-shift anomaly.

    The correction is accepted only when Datamine identities independently say
    ``NNmm`` and the numeric field is exactly ten times that SI value. Both the
    raw value and the Datamine-only evidence are retained by callers.
    """

    raw_value = float(raw_caliber_m)
    evidence: list[str] = []
    expected_values: set[float] = set()
    for identity in identity_values:
        text = str(identity or "")
        for match in _SMALL_CALIBER_MM_RE.finditer(text):
            millimeters = int(match.group(1))
            if millimeters >= 200:
                continue
            expected_values.add(millimeters / 1000.0)
            evidence.append(text)

    if len(expected_values) != 1:
        return raw_value, None
    expected = next(iter(expected_values))
    if not math.isclose(raw_value, expected * 10.0, rel_tol=0.0, abs_tol=1e-12):
        return raw_value, None
    return expected, {
        "field": "caliber_m",
        "rule": "datamine_mm_identity_decimal_shift",
        "raw_value": raw_value,
        "normalized_value": expected,
        "evidence": sorted(set(evidence)),
    }


def require_datamine_dir(root: Path, relative_dir: Path) -> Path:
    """Return a required datamine directory or raise a clear error."""
    directory = root / relative_dir
    if not directory.exists():
        raise FileNotFoundError(f"missing directory: {directory}")
    return directory


def read_datamine_version(root: Path) -> str:
    """Read the datamine repo's game version marker when available."""
    version_path = root / "version"
    try:
        return version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_git_commit(root: Path) -> str:
    """Return the current git commit for a datamine checkout when available."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except _GIT_COMMAND_ERRORS:
        return ""

    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def read_git_remote(root: Path) -> str:
    """Return the origin URL for a datamine checkout when available."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except _GIT_COMMAND_ERRORS:
        return ""

    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def require_clean_git_checkout(root: Path) -> None:
    """Reject a dirty or non-git datamine tree before generating bundled data."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except _GIT_COMMAND_ERRORS as exc:
        raise RuntimeError(f"unable to inspect datamine checkout: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or "not a git checkout"
        raise RuntimeError(f"unable to inspect datamine checkout: {detail}")
    if completed.stdout.strip():
        raise RuntimeError("datamine checkout is dirty; commit or remove local changes first")


def load_json_schema(path: Path) -> dict[str, Any]:
    """Load one canonical JSON Schema document."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SchemaValidationError(f"{path}: schema root must be an object")
    return payload


def _schema_error(path: str, message: str) -> SchemaValidationError:
    return SchemaValidationError(f"{path}: {message}")


def _resolve_schema_ref(ref: str, schema: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise SchemaValidationError(f"unsupported schema reference: {ref}")
    target: Any = schema.get("$defs", {})
    for token in ref.removeprefix(prefix).split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or token not in target:
            raise SchemaValidationError(f"unresolved schema reference: {ref}")
        target = target[token]
    if not isinstance(target, dict):
        raise SchemaValidationError(f"schema reference is not an object: {ref}")
    return target


def _validate_json_schema(
    value: Any,
    rules: dict[str, Any],
    path: str,
    schema: dict[str, Any],
) -> None:
    if "$ref" in rules:
        _validate_json_schema(value, _resolve_schema_ref(str(rules["$ref"]), schema), path, schema)
        return

    if "const" in rules and value != rules["const"]:
        raise _schema_error(path, f"expected constant {rules['const']!r}")
    if "enum" in rules and value not in rules["enum"]:
        raise _schema_error(path, f"not in allowed values {rules['enum']!r}")

    expected_type = rules.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise _schema_error(path, "expected object")
        required = set(rules.get("required", ()))
        missing = required - set(value)
        if missing:
            raise _schema_error(path, f"missing fields {sorted(missing)!r}")
        minimum = int(rules.get("minProperties", 0))
        if len(value) < minimum:
            raise _schema_error(path, f"expected at least {minimum} properties")
        properties = rules.get("properties", {})
        unknown = set(value) - set(properties)
        additional = rules.get("additionalProperties", True)
        if additional is False and unknown:
            raise _schema_error(path, f"unknown fields {sorted(unknown)!r}")
        if isinstance(additional, dict):
            for field in unknown:
                _validate_json_schema(value[field], additional, f"{path}.{field}", schema)
        for field, field_rules in properties.items():
            if field in value:
                _validate_json_schema(value[field], field_rules, f"{path}.{field}", schema)
    elif expected_type == "array":
        if not isinstance(value, list):
            raise _schema_error(path, "expected array")
        minimum = int(rules.get("minItems", 0))
        if len(value) < minimum:
            raise _schema_error(path, f"expected at least {minimum} items")
        maximum = rules.get("maxItems")
        if maximum is not None and len(value) > int(maximum):
            raise _schema_error(path, f"expected at most {int(maximum)} items")
        if item_rules := rules.get("items"):
            for index, item in enumerate(value):
                _validate_json_schema(item, item_rules, f"{path}[{index}]", schema)
        if rules.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True) for item in value]
            if len(canonical) != len(set(canonical)):
                raise _schema_error(path, "expected unique items")
    elif expected_type == "string":
        if not isinstance(value, str):
            raise _schema_error(path, "expected string")
        minimum = int(rules.get("minLength", 0))
        if len(value) < minimum:
            raise _schema_error(path, f"expected at least {minimum} characters")
        if (pattern := rules.get("pattern")) and re.search(str(pattern), value) is None:
            raise _schema_error(path, "string does not match pattern")
    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise _schema_error(path, "expected integer")
    elif expected_type == "number":
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise _schema_error(path, "expected number")
        if not math.isfinite(value):
            raise _schema_error(path, "expected finite number")
    elif expected_type == "boolean" and not isinstance(value, bool):
        raise _schema_error(path, "expected boolean")

    if "minimum" in rules and value < rules["minimum"]:
        raise _schema_error(path, f"must be at least {rules['minimum']}")
    if "exclusiveMinimum" in rules and value <= rules["exclusiveMinimum"]:
        raise _schema_error(path, f"must be greater than {rules['exclusiveMinimum']}")
    if "maximum" in rules and value > rules["maximum"]:
        raise _schema_error(path, f"must be at most {rules['maximum']}")


def validate_json_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str = "document",
) -> None:
    """Validate JSON using the schema subset used by Bomana's local assets."""
    _validate_json_schema(value, schema, path, schema)


def build_source_metadata(root: Path, relative_dir: Path) -> dict[str, str]:
    """Build reproducible source metadata for generated static JSON."""
    return {
        "source_root_name": root.name,
        "source_subdir": relative_dir.as_posix(),
        "source_version": read_datamine_version(root),
        "source_commit": read_git_commit(root),
    }
