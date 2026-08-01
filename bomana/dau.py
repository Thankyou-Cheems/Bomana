"""Best-effort daily-active reporting for the standalone Lite green build.

The managed Lite and Standard packages rely on the Launcher for this event.
Only the frozen green distribution starts this reporter. All filesystem and
network work runs on a daemon thread so reporting can never gate the UI.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DAU_ENDPOINT = "https://bomanaupdate.ruikang.wang/api/v1/event"
DISTRIBUTION_MODE_ENV = "BOMANA_DISTRIBUTION_MODE"
DISABLE_DAU_ENV = "BOMANA_DISABLE_DAU"
GREEN_DISTRIBUTION_MODE = "green"
GREEN_LAUNCHER_IDENTITY = "green"
INSTALL_ID_FILE_NAME = ".bomana_green_install_id"
SUCCESS_STAMP_FILE_NAME = ".bomana_green_dau_utc"
OPT_OUT_FILE_NAME = ".bomana_disable_dau"
REQUEST_TIMEOUT_SECONDS = 1.5

_INSTALL_ID_RE = re.compile(r"[0-9a-f]{32}", re.ASCII)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink()


def _load_or_create_install_id(state_dir: Path) -> str:
    path = state_dir / INSTALL_ID_FILE_NAME
    try:
        value = path.read_text(encoding="utf-8").strip().lower()
        if _INSTALL_ID_RE.fullmatch(value):
            return value
    except OSError, UnicodeError:
        pass

    install_id = uuid.uuid4().hex
    with suppress(OSError):
        _atomic_write_text(path, install_id)
    return install_id


def _read_machine_guid() -> str:
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            value, _kind = winreg.QueryValueEx(key, "MachineGuid")
        return str(value).strip()
    except OSError, ImportError:
        return ""


def _client_identity(state_dir: Path) -> dict[str, str]:
    install_id = _load_or_create_install_id(state_dir)
    machine_guid = _read_machine_guid()
    if machine_guid:
        raw = f"Bomana|machine|{machine_guid}"
    else:
        machine_name = os.environ.get("COMPUTERNAME", "").strip()
        raw = f"Bomana|fallback|{machine_name}|{install_id}"
    return {
        "device_id": hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:32],
        "install_id": install_id,
    }


def _post_json(
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    post: Callable[..., Any] | None = None,
) -> None:
    if post is None:
        import requests

        post = requests.post
    response = post(
        endpoint,
        data=json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"BomanaGreen/{payload.get('app_version', '')}",
        },
        timeout=timeout,
    )
    response.raise_for_status()


def _dau_disabled(state_dir: Path) -> bool:
    disabled = os.environ.get(DISABLE_DAU_ENV, "").strip().lower()
    return disabled in {"1", "true", "yes", "on"} or (state_dir / OPT_OUT_FILE_NAME).is_file()


def report_green_daily_active(
    *,
    app_version: str,
    state_dir: Path | None = None,
    now: Callable[[], datetime] = _utc_now,
    post_json: Callable[..., None] = _post_json,
) -> bool:
    """Report one successful ``version_check`` per UTC day.

    The update service uses distinct device/install identities on this event
    for its DAU counters. A failed request does not advance the local stamp, so
    a later launch can retry.
    """

    active_state_dir = Path.home() if state_dir is None else Path(state_dir)
    if _dau_disabled(active_state_dir):
        return False

    current = now().astimezone(UTC)
    utc_day = current.date().isoformat()
    stamp_path = active_state_dir / SUCCESS_STAMP_FILE_NAME
    try:
        if stamp_path.read_text(encoding="utf-8").strip() == utc_day:
            return False
    except OSError, UnicodeError:
        pass

    identity = _client_identity(active_state_dir)
    payload: dict[str, Any] = {
        "event": "version_check",
        "event_time_utc": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channel": "Lite",
        "launcher_version": GREEN_LAUNCHER_IDENTITY,
        "app_version": app_version,
        "local_version": app_version,
        "device_id": identity["device_id"],
        "install_id": identity["install_id"],
    }
    post_json(DAU_ENDPOINT, payload, timeout=REQUEST_TIMEOUT_SECONDS)
    _atomic_write_text(stamp_path, utc_day)
    return True


def _log_report_failure(exc: Exception) -> None:
    try:
        from bomana.utils.diagnostics import log_event

        log_event(
            "green_dau_report_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
    except Exception:
        pass


def start_green_dau_report(
    *,
    app_version: str,
    state_dir: Path | None = None,
    distribution_mode: str | None = None,
    reporter: Callable[..., bool] = report_green_daily_active,
    thread_factory: Callable[..., Any] = threading.Thread,
) -> Any | None:
    """Schedule green-build DAU work without executing I/O inline."""

    mode = (
        os.environ.get(DISTRIBUTION_MODE_ENV, "")
        if distribution_mode is None
        else distribution_mode
    )
    if str(mode).strip().lower() != GREEN_DISTRIBUTION_MODE:
        return None

    def run() -> None:
        try:
            reporter(app_version=app_version, state_dir=state_dir)
        except Exception as exc:
            _log_report_failure(exc)

    try:
        thread = thread_factory(
            target=run,
            name="BomanaGreenDAU",
            daemon=True,
        )
        thread.start()
        return thread
    except Exception:
        return None
