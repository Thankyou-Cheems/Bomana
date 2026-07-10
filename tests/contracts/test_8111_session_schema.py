# enforces: docs/specs/runtime-8111-boundary.md R8111-11

from __future__ import annotations

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tools import record_8111_session as recorder

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs/specs/schemas/8111-session-record.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


class ContractClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds

    def utc_now(self) -> datetime:
        return datetime(2026, 7, 10, tzinfo=UTC)


class ContractResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.content = json.dumps(payload).encode()
        self.status_code = 200
        self.ok = True
        self.headers = {"content-type": "application/json"}

    def json(self) -> Any:
        return self.payload


class ContractSession:
    trust_env = True

    def get(self, url: str, timeout: tuple[float, float]) -> ContractResponse:
        assert timeout == (recorder.CONNECT_TIMEOUT_SEC, recorder.READ_TIMEOUT_SEC)
        payload: Any = [] if url.endswith("/map_obj.json") else {"valid": True}
        return ContractResponse(payload)


def _resolve_ref(ref: str) -> dict[str, Any]:
    prefix = "#/$defs/"
    assert ref.startswith(prefix), ref
    return SCHEMA["$defs"][ref.removeprefix(prefix)]


def assert_matches_schema(value: Any, rules: dict[str, Any]) -> None:
    if not rules:
        return
    if "$ref" in rules:
        assert_matches_schema(value, _resolve_ref(rules["$ref"]))
        return
    if "oneOf" in rules:
        matches = 0
        for candidate in rules["oneOf"]:
            try:
                assert_matches_schema(value, candidate)
            except AssertionError:
                continue
            matches += 1
        assert matches == 1, f"expected one schema match, got {matches}: {value!r}"
        return
    if "const" in rules:
        assert value == rules["const"]
    if "enum" in rules:
        assert value in rules["enum"]

    expected_type = rules.get("type")
    if expected_type == "object":
        assert isinstance(value, dict)
        required = set(rules.get("required", ()))
        assert required <= set(value), f"missing fields: {sorted(required - set(value))}"
        properties = rules.get("properties", {})
        additional = rules.get("additionalProperties", True)
        unknown = set(value) - set(properties)
        if additional is False:
            assert not unknown, f"unknown fields: {sorted(unknown)}"
        elif isinstance(additional, dict):
            for field in unknown:
                assert_matches_schema(value[field], additional)
        for field, field_rules in properties.items():
            if field in value:
                assert_matches_schema(value[field], field_rules)
    elif expected_type == "array":
        assert isinstance(value, list)
        if item_rules := rules.get("items"):
            for item in value:
                assert_matches_schema(item, item_rules)
        if rules.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True) for item in value]
            assert len(canonical) == len(set(canonical))
    elif expected_type == "string":
        assert isinstance(value, str)
        if "maxLength" in rules:
            assert len(value) <= rules["maxLength"]
        if "pattern" in rules:
            assert re.fullmatch(rules["pattern"], value)
    elif expected_type == "integer":
        assert isinstance(value, int) and not isinstance(value, bool)
    elif expected_type == "number":
        assert isinstance(value, int | float) and not isinstance(value, bool)
    elif expected_type == "boolean":
        assert isinstance(value, bool)

    if "minimum" in rules:
        assert value >= rules["minimum"]


def _success_response(payload: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "error_kind": "",
        "elapsed_ms": 1.25,
        "status_code": 200,
        "body_size": 42,
        "body_sha256": "a" * 64,
        "content_type": "application/json",
        "payload": payload,
        "payload_type": type(payload).__name__,
    }


def _endpoint_stat() -> dict[str, Any]:
    return {"attempts": 1, "ok": 1, "failures": 0, "errors": {}}


def valid_records() -> list[dict[str, Any]]:
    return [
        {
            "record_type": "meta",
            "schema_version": 1,
            "started_at_utc": "2026-07-10T10:00:00.000Z",
            "api_base": "http://127.0.0.1:8111",
            "endpoints": list(recorder.OFFICIAL_ENDPOINTS),
            "interval_sec": 0.25,
            "map_info_interval_sec": 30.0,
            "label": "sortie",
            "game_version": "2.49",
            "mode": "SB",
        },
        {
            "record_type": "sample",
            "seq": 0,
            "elapsed_sec": 0.0,
            "responses": {
                "/indicators": _success_response({"type": "f-16a"}),
                "/state": _success_response({"IAS, km/h": 420.0}),
                "/map_obj.json": _success_response([]),
                "/map_info.json": _success_response({"map_min": [0, 0]}),
            },
        },
        {
            "record_type": "summary",
            "schema_version": 1,
            "finished_at_utc": "2026-07-10T10:10:00.000Z",
            "duration_sec": 600.0,
            "samples": 2400,
            "interrupted": True,
            "aircraft_types": ["f-16a"],
            "endpoint_stats": {
                endpoint: _endpoint_stat() for endpoint in recorder.OFFICIAL_ENDPOINTS
            },
        },
    ]


def test_recorder_and_contract_load_the_same_schema_version() -> None:
    assert recorder.SESSION_RECORD_SCHEMA_PATH == SCHEMA_PATH
    assert recorder.SESSION_RECORD_SCHEMA == SCHEMA
    assert recorder.SCHEMA_VERSION == SCHEMA["x-format-version"] == 1


def test_valid_meta_sample_and_summary_records_match_schema() -> None:
    for record in valid_records():
        assert_matches_schema(record, SCHEMA)


def test_actual_recorded_jsonl_matches_schema(tmp_path: Path) -> None:
    output = tmp_path / "contract.jsonl"
    recorder.record_session(
        recorder.RecorderConfig(
            output=output,
            interval_sec=0.05,
            duration_sec=0.1,
            map_info_interval_sec=30.0,
        ),
        session=ContractSession(),
        clock=ContractClock(),
        progress=lambda *_args: None,
    )

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [record["record_type"] for record in records] == [
        "meta",
        "sample",
        "sample",
        "summary",
    ]
    for record in records:
        assert_matches_schema(record, SCHEMA)


@pytest.mark.parametrize("record_index", [0, 1, 2])
def test_missing_required_field_is_rejected(record_index: int) -> None:
    record = copy.deepcopy(valid_records()[record_index])
    record.pop(next(iter(SCHEMA["$defs"][record["record_type"]]["required"])))

    with pytest.raises(AssertionError):
        assert_matches_schema(record, SCHEMA)


def test_unknown_field_and_invalid_body_hash_are_rejected() -> None:
    meta, sample, _summary = copy.deepcopy(valid_records())
    meta["hostname"] = "must-not-be-recorded"
    sample["responses"]["/state"]["body_sha256"] = "not-a-sha256"

    with pytest.raises(AssertionError):
        assert_matches_schema(meta, SCHEMA)
    with pytest.raises(AssertionError):
        assert_matches_schema(sample, SCHEMA)
