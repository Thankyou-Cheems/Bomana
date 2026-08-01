from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import requests

from tools import record_8111_session as recorder


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0
        self.started = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += max(0.0, seconds)

    def utc_now(self) -> datetime:
        return self.started + timedelta(seconds=self.value - 100.0)


class FakeResponse:
    def __init__(
        self,
        payload: Any = None,
        *,
        status_code: int = 200,
        invalid_json: bool = False,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.headers = {"content-type": "application/json"}
        self.content = (
            b"not-json" if invalid_json else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        self._invalid_json = invalid_json

    def json(self) -> Any:
        if self._invalid_json:
            raise ValueError("invalid json")
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.trust_env = True
        self.close_called = False
        self.calls: list[str] = []

    def get(self, url: str, timeout: tuple[float, float]) -> FakeResponse:
        assert timeout == (
            recorder.CONNECT_TIMEOUT_SEC,
            recorder.READ_TIMEOUT_SEC,
        )
        endpoint = url.removeprefix(recorder.API_BASE)
        self.calls.append(endpoint)
        payloads = {
            "/indicators": {"type": "f-16a", "compass1": 91.5},
            "/state": {"valid": True, "IAS, km/h": 420.0, "H, m": 2200.0},
            "/map_obj.json": [{"type": "aircraft", "icon": "Player"}],
            "/map_info.json": {"map_min": [0, 0], "map_max": [100000, 100000]},
        }
        return FakeResponse(payloads[endpoint])

    def close(self) -> None:
        self.close_called = True


class InterruptingSession(FakeSession):
    def get(self, url: str, timeout: tuple[float, float]) -> FakeResponse:
        if len(self.calls) >= 4:
            raise KeyboardInterrupt
        return super().get(url, timeout)


class MapInfoRetrySession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.map_info_attempts = 0

    def get(self, url: str, timeout: tuple[float, float]) -> FakeResponse:
        if url.endswith("/map_info.json"):
            self.map_info_attempts += 1
            if self.map_info_attempts == 1:
                self.calls.append("/map_info.json")
                return FakeResponse(status_code=503)
        return super().get(url, timeout)


def _read_gzip_jsonl(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, mode="rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def test_record_session_writes_synchronized_raw_payloads_and_summary(tmp_path: Path) -> None:
    output = tmp_path / "session.jsonl.gz"
    clock = FakeClock()
    session = FakeSession()

    summary = recorder.record_session(
        recorder.RecorderConfig(
            output=output,
            interval_sec=0.25,
            duration_sec=0.5,
            map_info_interval_sec=30.0,
            label="full sortie",
            game_version="2.49",
            mode="SB",
        ),
        session=session,
        clock=clock,
        progress=lambda *_args: None,
    )

    records = _read_gzip_jsonl(output)
    assert [record["record_type"] for record in records] == [
        "meta",
        "sample",
        "sample",
        "summary",
    ]
    meta, first, second, stored_summary = records
    assert meta["api_base"] == "http://127.0.0.1:8111"
    assert meta["endpoints"] == list(recorder.OFFICIAL_ENDPOINTS)
    assert set(meta) == {
        "record_type",
        "schema_version",
        "started_at_utc",
        "api_base",
        "endpoints",
        "interval_sec",
        "map_info_interval_sec",
        "label",
        "game_version",
        "mode",
    }
    assert first["responses"]["/indicators"]["payload"]["type"] == "f-16a"
    assert first["responses"]["/state"]["payload"]["IAS, km/h"] == 420.0
    assert first["responses"]["/map_obj.json"]["payload"] == [
        {"type": "aircraft", "icon": "Player"}
    ]
    assert "/map_info.json" in first["responses"]
    assert "/map_info.json" not in second["responses"]
    assert len(first["responses"]["/state"]["body_sha256"]) == 64
    assert summary == stored_summary
    assert summary["samples"] == 2
    assert summary["aircraft_types"] == ["f-16a"]
    assert summary["endpoint_stats"]["/indicators"] == {
        "attempts": 2,
        "ok": 2,
        "failures": 0,
        "errors": {},
    }
    assert session.trust_env is False
    assert not session.close_called
    assert not output.with_name(f"{output.name}.partial").exists()


def test_record_session_finalizes_valid_gzip_on_ctrl_c(tmp_path: Path) -> None:
    output = tmp_path / "interrupted.jsonl.gz"

    summary = recorder.record_session(
        recorder.RecorderConfig(output=output, interval_sec=0.25),
        session=InterruptingSession(),
        clock=FakeClock(),
        progress=lambda *_args: None,
    )

    records = _read_gzip_jsonl(output)
    assert records[-1] == summary
    assert summary["interrupted"] is True
    assert summary["samples"] == 1


def test_record_session_retries_map_info_before_battle_becomes_available(tmp_path: Path) -> None:
    output = tmp_path / "map-info-retry.jsonl.gz"
    session = MapInfoRetrySession()

    summary = recorder.record_session(
        recorder.RecorderConfig(
            output=output,
            interval_sec=0.25,
            duration_sec=1.2,
            map_info_interval_sec=30.0,
        ),
        session=session,
        clock=FakeClock(),
        progress=lambda *_args: None,
    )

    assert session.map_info_attempts == 2
    assert summary["endpoint_stats"]["/map_info.json"] == {
        "attempts": 2,
        "ok": 1,
        "failures": 1,
        "errors": {"status": 1},
    }


@pytest.mark.parametrize(
    ("response", "error_kind"),
    [
        (FakeResponse(status_code=503), "status"),
        (FakeResponse(invalid_json=True), "invalid_json"),
    ],
)
def test_fetch_endpoint_records_failures_without_response_body(
    response: FakeResponse,
    error_kind: str,
) -> None:
    class SingleResponseSession:
        def get(self, _url: str, timeout: tuple[float, float]) -> FakeResponse:
            return response

    result = recorder._fetch_endpoint(
        SingleResponseSession(),
        "/state",
        clock=FakeClock(),
    )

    assert result["ok"] is False
    assert result["error_kind"] == error_kind
    assert "payload" not in result
    assert result["body_size"] > 0


def test_fetch_endpoint_classifies_request_timeout() -> None:
    class TimeoutSession:
        def get(self, _url: str, timeout: tuple[float, float]) -> FakeResponse:
            raise requests.Timeout

    result = recorder._fetch_endpoint(
        TimeoutSession(),
        "/state",
        clock=FakeClock(),
    )

    assert result == {"ok": False, "error_kind": "timeout", "elapsed_ms": 0.0}


def test_recorder_rejects_overwrite_without_force(tmp_path: Path) -> None:
    output = tmp_path / "existing.jsonl.gz"
    output.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        recorder.record_session(
            recorder.RecorderConfig(output=output, duration_sec=0.1),
            session=FakeSession(),
            clock=FakeClock(),
            progress=lambda *_args: None,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interval_sec", float("nan")),
        ("duration_sec", float("inf")),
        ("map_info_interval_sec", float("-inf")),
    ],
)
def test_recorder_rejects_non_finite_timing_options(
    tmp_path: Path,
    field: str,
    value: float,
) -> None:
    values = {"output": tmp_path / "invalid.jsonl.gz", field: value}

    with pytest.raises(ValueError, match="must be finite"):
        recorder.RecorderConfig(**values).validate()
