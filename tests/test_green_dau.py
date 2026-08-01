from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bomana import dau


class _Response:
    @staticmethod
    def raise_for_status() -> None:
        return None


def test_green_dau_payload_matches_server_daily_active_counter(tmp_path: Path, monkeypatch) -> None:
    posted: list[tuple[str, dict[str, object], float]] = []
    monkeypatch.setattr(dau, "_read_machine_guid", lambda: "machine-guid")

    def post_json(endpoint: str, payload: dict[str, object], *, timeout: float) -> None:
        posted.append((endpoint, payload, timeout))

    def now() -> datetime:
        return datetime(2026, 8, 1, 12, 30, tzinfo=UTC)

    assert dau.report_green_daily_active(
        app_version="8.7.0",
        state_dir=tmp_path,
        now=now,
        post_json=post_json,
    )
    assert not dau.report_green_daily_active(
        app_version="8.7.0",
        state_dir=tmp_path,
        now=now,
        post_json=post_json,
    )

    assert len(posted) == 1
    endpoint, payload, timeout = posted[0]
    assert endpoint == dau.DAU_ENDPOINT
    assert timeout == dau.REQUEST_TIMEOUT_SECONDS
    assert payload == {
        "event": "version_check",
        "event_time_utc": "2026-08-01T12:30:00Z",
        "channel": "Lite",
        "launcher_version": "green",
        "app_version": "8.7.0",
        "local_version": "8.7.0",
        "device_id": dau.hashlib.sha256(b"Bomana|machine|machine-guid").hexdigest()[:32],
        "install_id": (tmp_path / dau.INSTALL_ID_FILE_NAME).read_text(encoding="utf-8"),
    }
    assert (tmp_path / dau.SUCCESS_STAMP_FILE_NAME).read_text(encoding="utf-8") == "2026-08-01"


def test_failed_green_dau_does_not_advance_daily_stamp(tmp_path: Path) -> None:
    attempts = 0

    def fail(_endpoint: str, _payload: dict[str, object], *, timeout: float) -> None:
        nonlocal attempts
        attempts += 1
        assert timeout == dau.REQUEST_TIMEOUT_SECONDS
        raise OSError("offline")

    def now() -> datetime:
        return datetime(2026, 8, 1, tzinfo=UTC)

    with pytest.raises(OSError, match="offline"):
        dau.report_green_daily_active(
            app_version="8.7.0",
            state_dir=tmp_path,
            now=now,
            post_json=fail,
        )
    with pytest.raises(OSError, match="offline"):
        dau.report_green_daily_active(
            app_version="8.7.0",
            state_dir=tmp_path,
            now=now,
            post_json=fail,
        )

    assert attempts == 2
    assert not (tmp_path / dau.SUCCESS_STAMP_FILE_NAME).exists()


def test_green_dau_opt_out_skips_identity_and_network(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / dau.OPT_OUT_FILE_NAME).touch()
    monkeypatch.setattr(
        dau,
        "_client_identity",
        lambda _state_dir: pytest.fail("identity must not be built after opt-out"),
    )

    assert not dau.report_green_daily_active(
        app_version="8.7.0",
        state_dir=tmp_path,
        post_json=lambda *_args, **_kwargs: pytest.fail("network must not run"),
    )


def test_green_dau_start_only_schedules_background_work() -> None:
    captured: dict[str, object] = {}

    class FakeThread:
        def __init__(self, *, target, name: str, daemon: bool) -> None:
            captured.update(target=target, name=name, daemon=daemon, started=False)

        def start(self) -> None:
            captured["started"] = True

    reporter_called = False

    def reporter(**_kwargs) -> bool:
        nonlocal reporter_called
        reporter_called = True
        return True

    thread = dau.start_green_dau_report(
        app_version="8.7.0",
        distribution_mode="green",
        reporter=reporter,
        thread_factory=FakeThread,
    )

    assert thread is not None
    assert captured == {
        "target": captured["target"],
        "name": "BomanaGreenDAU",
        "daemon": True,
        "started": True,
    }
    assert not reporter_called

    captured["target"]()
    assert reporter_called


def test_managed_app_does_not_schedule_green_dau() -> None:
    assert (
        dau.start_green_dau_report(
            app_version="8.7.0",
            distribution_mode="managed",
            thread_factory=lambda **_kwargs: pytest.fail("thread must not be created"),
        )
        is None
    )


def test_thread_start_failure_is_swallowed_without_inline_logging(monkeypatch) -> None:
    class BrokenThread:
        def __init__(self, **_kwargs) -> None:
            raise OSError("thread unavailable")

    monkeypatch.setattr(
        dau,
        "_log_report_failure",
        lambda _exc: pytest.fail("startup failure must not perform diagnostic I/O inline"),
    )

    assert (
        dau.start_green_dau_report(
            app_version="8.7.0",
            distribution_mode="green",
            thread_factory=BrokenThread,
        )
        is None
    )


def test_post_json_uses_bounded_timeout_and_json_headers() -> None:
    captured: dict[str, object] = {}

    def post(endpoint: str, *, data: bytes, headers: dict[str, str], timeout: float):
        captured["endpoint"] = endpoint
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _Response()

    dau._post_json(
        "https://example.test/event",
        {"app_version": "8.7.0", "event": "version_check"},
        timeout=1.25,
        post=post,
    )

    assert captured["endpoint"] == "https://example.test/event"
    assert captured["timeout"] == 1.25
    assert captured["headers"] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "BomanaGreen/8.7.0",
    }
    assert captured["data"] == b'{"app_version":"8.7.0","event":"version_check"}'
