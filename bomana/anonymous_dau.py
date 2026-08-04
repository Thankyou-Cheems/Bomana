"""Portable implementation of Bomana's anonymous daily-active contract.

The Launcher and Standalone Green Lite deliberately share this small,
standard-library-only module.  It knows nothing about application data,
receipts, accounts, hardware, or release installation state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

SCHEMA_VERSION = 1
DAU_PATH = "/api/v1/telemetry/dau"
DEFAULT_UPDATE_BASE_URL = "https://bomanaupdate.ruikang.wang"
REQUEST_TIMEOUT_SECONDS = 1.5
INSTALL_SECRET_FILE_NAME = "install_secret.bin"
REPORT_STAMP_FILE_NAME = "reported_utc_day"
INSTALL_SECRET_BYTES = 32
DAU_CHANNELS = frozenset({"Lite", "Standard", "Enhanced"})

_state_lock = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_day(current: datetime) -> str:
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).date().isoformat()


def _require_channel(channel: str) -> str:
    if channel not in DAU_CHANNELS:
        raise ValueError("daily-active channel must be Lite, Standard, or Enhanced")
    return channel


def _require_utc_day(utc_day: str) -> str:
    try:
        return date.fromisoformat(utc_day).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("daily-active token requires an ISO UTC date") from exc


def build_daily_active_payload(
    install_secret: bytes,
    *,
    channel: str,
    utc_day: str,
) -> dict[str, object]:
    """Create the exact allowlisted payload for one installation UTC day."""

    if len(install_secret) != INSTALL_SECRET_BYTES:
        raise ValueError("daily-active installation secret has an invalid length")
    day = _require_utc_day(utc_day)
    token = hmac.new(install_secret, day.encode("ascii"), hashlib.sha256).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "install_day_token": token,
        "channel": _require_channel(channel),
    }


def default_state_dir(installation_scope: str = "launcher") -> Path:
    """Return current-user state outside both managed and portable packages."""

    if installation_scope not in {"launcher", "green"}:
        raise ValueError("daily-active installation scope is not supported")
    appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if not appdata:
        appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "Bomana" / "telemetry" / installation_scope
    return Path.home() / ".local" / "share" / "Bomana" / "telemetry" / installation_scope


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_bytes(value)
        os.replace(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink()


def _load_or_create_install_secret(state_dir: Path) -> bytes:
    path = state_dir / INSTALL_SECRET_FILE_NAME
    try:
        secret = path.read_bytes()
    except OSError:
        secret = b""
    if len(secret) == INSTALL_SECRET_BYTES:
        return secret

    secret = secrets.token_bytes(INSTALL_SECRET_BYTES)
    _atomic_write_bytes(path, secret)
    return secret


def _claim_utc_day(state_dir: Path, utc_day: str) -> bool:
    """Reserve a UTC day locally before transport to bound launch attempts."""

    path = state_dir / REPORT_STAMP_FILE_NAME
    try:
        if path.read_text(encoding="ascii").strip() == utc_day:
            return False
    except OSError, UnicodeError:
        pass
    _atomic_write_bytes(path, utc_day.encode("ascii"))
    return True


def daily_active_endpoint(update_base_url: str | None = None) -> str:
    """Resolve the independent endpoint without query parameters or fragments."""

    raw_base = (
        os.environ.get("BOMANA_UPDATE_BASE_URL", DEFAULT_UPDATE_BASE_URL)
        if update_base_url is None
        else update_base_url
    )
    parsed = urlsplit(str(raw_base).strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("daily-active endpoint base is invalid")
    path = f"{parsed.path.rstrip('/')}{DAU_PATH}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _validate_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path != DAU_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("daily-active endpoint must be the query-free DAU path")
    return endpoint


def _post_json(endpoint: str, payload: dict[str, object], *, timeout: float) -> None:
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    response = urlopen(request, timeout=timeout)
    try:
        status = response.getcode()
        if status < 200 or status >= 300:
            raise OSError(f"daily-active endpoint returned HTTP {status}")
    finally:
        response.close()


def report_daily_active(
    *,
    channel: str,
    state_dir: Path | None = None,
    endpoint: str | None = None,
    now: Callable[[], datetime] = _utc_now,
    post_json: Callable[..., None] = _post_json,
    installation_scope: str = "launcher",
) -> bool:
    """Attempt one anonymous report and swallow every local or network failure."""

    try:
        _require_channel(channel)
        current_day = _utc_day(now())
        active_state_dir = (
            default_state_dir(installation_scope) if state_dir is None else Path(state_dir)
        )
        with _state_lock:
            secret = _load_or_create_install_secret(active_state_dir)
            if not _claim_utc_day(active_state_dir, current_day):
                return False
        payload = build_daily_active_payload(secret, channel=channel, utc_day=current_day)
        target = _validate_endpoint(endpoint or daily_active_endpoint())
        post_json(target, payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False
    return True


def start_daily_active_report(
    *,
    channel: str,
    state_dir: Path | None = None,
    endpoint: str | None = None,
    now: Callable[[], datetime] = _utc_now,
    reporter: Callable[..., bool] = report_daily_active,
    thread_factory: Callable[..., Any] = threading.Thread,
    installation_scope: str = "launcher",
) -> Any | None:
    """Schedule reporting without doing disk or network work on the caller thread."""

    try:
        _require_channel(channel)
    except Exception:
        return None

    def run() -> None:
        with suppress(Exception):
            reporter(
                channel=channel,
                state_dir=state_dir,
                endpoint=endpoint,
                now=now,
                installation_scope=installation_scope,
            )

    try:
        worker = thread_factory(target=run, name="BomanaDailyActive", daemon=True)
        worker.start()
        return worker
    except Exception:
        return None


__all__ = [
    "DAU_CHANNELS",
    "DAU_PATH",
    "DEFAULT_UPDATE_BASE_URL",
    "INSTALL_SECRET_BYTES",
    "INSTALL_SECRET_FILE_NAME",
    "REPORT_STAMP_FILE_NAME",
    "REQUEST_TIMEOUT_SECONDS",
    "SCHEMA_VERSION",
    "build_daily_active_payload",
    "daily_active_endpoint",
    "default_state_dir",
    "report_daily_active",
    "start_daily_active_report",
]
