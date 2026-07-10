"""Validate and load Bomana 8111 session recordings."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

ROOT = Path(__file__).resolve().parent.parent
SESSION_RECORD_SCHEMA_PATH = ROOT / "docs/specs/schemas/8111-session-record.schema.json"
SESSION_RECORD_SCHEMA = json.loads(SESSION_RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_VERSION = int(SESSION_RECORD_SCHEMA["x-format-version"])
API_BASE = str(SESSION_RECORD_SCHEMA["$defs"]["meta"]["properties"]["api_base"]["const"])
OFFICIAL_ENDPOINTS = tuple(
    SESSION_RECORD_SCHEMA["$defs"]["meta"]["properties"]["endpoints"]["const"]
)
FAST_ENDPOINTS = OFFICIAL_ENDPOINTS[:3]
MAP_INFO_ENDPOINT = OFFICIAL_ENDPOINTS[3]


class SessionFormatError(ValueError):
    """Raised when a recording does not satisfy its schema or stream contract."""


@dataclass(frozen=True)
class RecordedSession:
    """A fully validated recording ready for deterministic replay."""

    path: Path
    sha256: str
    meta: dict[str, Any]
    samples: tuple[dict[str, Any], ...]
    summary: dict[str, Any]


def _schema_error(path: str, message: str) -> SessionFormatError:
    return SessionFormatError(f"{path}: {message}")


def _resolve_ref(ref: str, schema: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise SessionFormatError(f"unsupported schema reference: {ref}")
    return schema["$defs"][ref.removeprefix(prefix)]


def _validate(
    value: Any,
    rules: dict[str, Any],
    path: str,
    schema: dict[str, Any],
) -> None:
    if not rules:
        return
    if "$ref" in rules:
        _validate(value, _resolve_ref(rules["$ref"], schema), path, schema)
        return
    if "oneOf" in rules:
        matches = 0
        for candidate in rules["oneOf"]:
            try:
                _validate(value, candidate, path, schema)
            except SessionFormatError:
                continue
            matches += 1
        if matches != 1:
            raise _schema_error(path, f"expected one schema match, got {matches}")
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
        properties = rules.get("properties", {})
        unknown = set(value) - set(properties)
        additional = rules.get("additionalProperties", True)
        if additional is False and unknown:
            raise _schema_error(path, f"unknown fields {sorted(unknown)!r}")
        if isinstance(additional, dict):
            for field in unknown:
                _validate(value[field], additional, f"{path}.{field}", schema)
        for field, field_rules in properties.items():
            if field in value:
                _validate(value[field], field_rules, f"{path}.{field}", schema)
    elif expected_type == "array":
        if not isinstance(value, list):
            raise _schema_error(path, "expected array")
        if item_rules := rules.get("items"):
            for index, item in enumerate(value):
                _validate(item, item_rules, f"{path}[{index}]", schema)
        if rules.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True) for item in value]
            if len(canonical) != len(set(canonical)):
                raise _schema_error(path, "expected unique items")
    elif expected_type == "string":
        if not isinstance(value, str):
            raise _schema_error(path, "expected string")
        if "maxLength" in rules and len(value) > rules["maxLength"]:
            raise _schema_error(path, "string is too long")
        if "pattern" in rules and re.fullmatch(rules["pattern"], value) is None:
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


def validate_json_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str = "document",
) -> None:
    """Validate JSON using the schema subset used by Bomana's local formats."""

    _validate(value, schema, path, schema)


def validate_session_record(record: Any, *, path: str = "record") -> None:
    """Validate one JSONL record against the canonical recording schema."""

    validate_json_schema(record, SESSION_RECORD_SCHEMA, path=path)


def _open_recording(path: Path) -> TextIO:
    if path.name.endswith(".gz"):
        return gzip.open(path, mode="rt", encoding="utf-8")
    return path.open(mode="r", encoding="utf-8")


def _empty_endpoint_stats() -> dict[str, dict[str, Any]]:
    return {
        endpoint: {"attempts": 0, "ok": 0, "failures": 0, "errors": {}}
        for endpoint in OFFICIAL_ENDPOINTS
    }


def summarize_session_samples(
    samples: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    stats = _empty_endpoint_stats()
    aircraft_types: set[str] = set()
    for sample in samples:
        for endpoint, result in sample["responses"].items():
            endpoint_stat = stats[endpoint]
            endpoint_stat["attempts"] += 1
            if result["ok"]:
                endpoint_stat["ok"] += 1
            else:
                endpoint_stat["failures"] += 1
                error_kind = str(result.get("error_kind") or "unknown")
                errors = endpoint_stat["errors"]
                errors[error_kind] = errors.get(error_kind, 0) + 1
        indicators = sample["responses"]["/indicators"]
        payload = indicators.get("payload")
        if indicators["ok"] and isinstance(payload, dict):
            aircraft = str(payload.get("type") or "").strip()
            if aircraft:
                aircraft_types.add(aircraft)
    return stats, sorted(aircraft_types)


def load_recorded_session(path: Path) -> RecordedSession:
    """Load a complete recording and reject schema or stream-level drift."""

    resolved = path.expanduser().resolve()
    try:
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        with _open_recording(resolved) as stream:
            records: list[dict[str, Any]] = []
            for line_number, line in enumerate(stream, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise _schema_error(f"line {line_number}", f"invalid JSON: {exc.msg}") from exc
                validate_session_record(record, path=f"line {line_number}")
                records.append(record)
    except (OSError, EOFError) as exc:
        raise SessionFormatError(f"cannot read recording {resolved}: {exc}") from exc

    if len(records) < 2:
        raise SessionFormatError("recording must contain meta and summary records")
    if records[0]["record_type"] != "meta":
        raise SessionFormatError("first record must be meta")
    if records[-1]["record_type"] != "summary":
        raise SessionFormatError("last record must be summary")
    if any(record["record_type"] != "sample" for record in records[1:-1]):
        raise SessionFormatError("only sample records may appear between meta and summary")

    meta = records[0]
    samples = records[1:-1]
    summary = records[-1]
    previous_elapsed = -1.0
    for expected_seq, sample in enumerate(samples):
        if sample["seq"] != expected_seq:
            raise SessionFormatError(
                f"sample sequence mismatch: expected {expected_seq}, got {sample['seq']}"
            )
        elapsed = float(sample["elapsed_sec"])
        if elapsed < previous_elapsed:
            raise SessionFormatError(f"sample {expected_seq} elapsed_sec is not monotonic")
        previous_elapsed = elapsed

    if summary["schema_version"] != meta["schema_version"]:
        raise SessionFormatError("meta and summary schema versions differ")
    if summary["samples"] != len(samples):
        raise SessionFormatError(
            f"summary sample count is {summary['samples']}, actual count is {len(samples)}"
        )
    if samples and float(summary["duration_sec"]) < float(samples[-1]["elapsed_sec"]):
        raise SessionFormatError("summary duration precedes the final sample")
    expected_stats, expected_aircraft = summarize_session_samples(samples)
    if summary["endpoint_stats"] != expected_stats:
        raise SessionFormatError("summary endpoint statistics do not match samples")
    if summary["aircraft_types"] != expected_aircraft:
        raise SessionFormatError("summary aircraft types do not match samples")

    return RecordedSession(
        path=resolved,
        sha256=digest,
        meta=meta,
        samples=tuple(samples),
        summary=summary,
    )
