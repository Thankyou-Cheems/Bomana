from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path

from bomana import anonymous_dau

ROOT = Path(__file__).resolve().parents[1]


def _utc_now(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T12:00:00+00:00").astimezone(UTC)


def test_green_uses_the_shared_hmac_daily_active_contract(tmp_path: Path) -> None:
    sent: list[tuple[str, dict[str, object], float]] = []
    secret = bytes(range(anonymous_dau.INSTALL_SECRET_BYTES))
    (tmp_path / anonymous_dau.INSTALL_SECRET_FILE_NAME).write_bytes(secret)

    def post_json(endpoint: str, payload: dict[str, object], *, timeout: float) -> None:
        sent.append((endpoint, payload, timeout))

    assert anonymous_dau.report_daily_active(
        channel="Lite",
        state_dir=tmp_path,
        installation_scope="green",
        now=lambda: _utc_now("2026-08-03"),
        endpoint="https://example.test/api/v1/telemetry/dau",
        post_json=post_json,
    )
    assert not anonymous_dau.report_daily_active(
        channel="Lite",
        state_dir=tmp_path,
        installation_scope="green",
        now=lambda: _utc_now("2026-08-03"),
        endpoint="https://example.test/api/v1/telemetry/dau",
        post_json=post_json,
    )

    assert sent == [
        (
            "https://example.test/api/v1/telemetry/dau",
            {
                "schema_version": 1,
                "install_day_token": hmac.new(
                    secret,
                    b"2026-08-03",
                    hashlib.sha256,
                ).hexdigest(),
                "channel": "Lite",
            },
            anonymous_dau.REQUEST_TIMEOUT_SECONDS,
        )
    ]
    assert (tmp_path / anonymous_dau.REPORT_STAMP_FILE_NAME).read_text(encoding="ascii") == (
        "2026-08-03"
    )


def test_green_report_generates_only_a_random_32_byte_secret(tmp_path: Path) -> None:
    assert not anonymous_dau.report_daily_active(
        channel="Lite",
        state_dir=tmp_path,
        installation_scope="green",
        now=lambda: _utc_now("2026-08-03"),
        endpoint="not an endpoint",
    )

    secret = (tmp_path / anonymous_dau.INSTALL_SECRET_FILE_NAME).read_bytes()
    assert len(secret) == anonymous_dau.INSTALL_SECRET_BYTES
    assert secret != b"\x00" * anonymous_dau.INSTALL_SECRET_BYTES


def test_green_endpoint_rejects_the_legacy_event_collector(tmp_path: Path) -> None:
    called = False

    def post_json(*_args, **_kwargs) -> None:
        nonlocal called
        called = True

    assert not anonymous_dau.report_daily_active(
        channel="Lite",
        state_dir=tmp_path,
        installation_scope="green",
        now=lambda: _utc_now("2026-08-03"),
        endpoint="https://example.test/api/v1/event",
        post_json=post_json,
    )
    assert not called


def test_green_transport_failures_are_silent_and_do_not_run_inline(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    captured: dict[str, object] = {}

    class DeferredThread:
        def __init__(self, *, target, name: str, daemon: bool) -> None:
            captured.update(target=target, name=name, daemon=daemon)

        def start(self) -> None:
            captured["started"] = True

    def reporter(**kwargs: object) -> bool:
        calls.append(dict(kwargs))
        raise OSError("offline")

    worker = anonymous_dau.start_daily_active_report(
        channel="Lite",
        state_dir=tmp_path,
        installation_scope="green",
        reporter=reporter,
        thread_factory=DeferredThread,
    )

    assert worker is not None
    assert captured["name"] == "BomanaDailyActive"
    assert captured["daemon"] is True
    assert captured["started"] is True
    assert calls == []

    target = captured["target"]
    assert callable(target)
    target()
    assert len(calls) == 1
    assert calls[0]["channel"] == "Lite"
    assert calls[0]["installation_scope"] == "green"


def test_green_entrypoint_imports_no_legacy_reporter_or_launcher_runtime() -> None:
    source = (ROOT / "Bomana.pyw").read_text(encoding="utf-8")

    assert "from bomana.anonymous_dau import start_daily_active_report" in source
    assert "from bomana.dau" not in source
    assert 'start_daily_active_report(channel="Lite", installation_scope="green")' in source
