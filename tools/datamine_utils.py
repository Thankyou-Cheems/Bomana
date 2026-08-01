"""Shared helpers for Bomana's public flight-model extraction tools."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

FLIGHTMODELS_SUBDIR = Path("aces.vromfs.bin_u") / "gamedata" / "flightmodels"
_GIT_COMMAND_ERRORS = (OSError, subprocess.SubprocessError)


class SchemaValidationError(ValueError):
    """Raised when a generated datamine asset violates its canonical schema."""


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

    if "oneOf" in rules:
        matches = 0
        for option in rules["oneOf"]:
            try:
                _validate_json_schema(value, option, path, schema)
            except SchemaValidationError:
                continue
            matches += 1
        if matches != 1:
            raise _schema_error(path, f"expected exactly one schema match, got {matches}")
        return

    if "const" in rules and value != rules["const"]:
        raise _schema_error(path, f"expected constant {rules['const']!r}")
    if "enum" in rules and value not in rules["enum"]:
        raise _schema_error(path, f"not in allowed values {rules['enum']!r}")

    expected_type = rules.get("type")
    if isinstance(expected_type, list):
        for option in expected_type:
            branch = dict(rules)
            branch["type"] = option
            try:
                _validate_json_schema(value, branch, path, schema)
            except SchemaValidationError:
                continue
            return
        raise _schema_error(path, f"expected one of types {expected_type!r}")
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
    elif expected_type == "null":
        if value is not None:
            raise _schema_error(path, "expected null")
        return

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
