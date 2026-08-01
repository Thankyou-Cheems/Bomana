"""Structured diagnostics logging."""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import logging.handlers
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

_LOGGER_NAME = "bomana.diagnostics"
_RESERVED_ATTRS = set(logging.makeLogRecord({}).__dict__)
_LOCK = threading.Lock()
_LISTENER: logging.handlers.QueueListener | None = None
_HANDLER: logging.Handler | None = None
_QUEUE_HANDLER: logging.Handler | None = None
_LOG_PATH: Path | None = None


class JsonLineFormatter(logging.Formatter):
    """Format records as one compact JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }
        for key, value in sorted(record.__dict__.items()):
            if key in _RESERVED_ATTRS or key in {"event", "message", "asctime"}:
                continue
            payload[key] = _json_safe(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def configure_diagnostics(log_path: str | os.PathLike[str] | None = None) -> Path | None:
    """Start the background diagnostics writer.

    Calls from UI or polling threads enqueue records only; the QueueListener owns disk I/O.
    """
    global _HANDLER, _LISTENER, _LOG_PATH, _QUEUE_HANDLER

    with _LOCK:
        if _LISTENER is not None:
            return _LOG_PATH

        path = Path(log_path) if log_path is not None else Path.home() / ".wttimer_diagnostics.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                path,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        except OSError:
            return None

        file_handler.setFormatter(JsonLineFormatter())
        record_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
        queue_handler = logging.handlers.QueueHandler(record_queue)

        logger = logging.getLogger(_LOGGER_NAME)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()
        logger.addHandler(queue_handler)

        listener = logging.handlers.QueueListener(
            record_queue, file_handler, respect_handler_level=True
        )
        listener.start()

        _HANDLER = file_handler
        _LISTENER = listener
        _LOG_PATH = path
        _QUEUE_HANDLER = queue_handler
        atexit.register(shutdown_diagnostics)
        return path


def shutdown_diagnostics() -> None:
    """Flush and stop the background diagnostics writer."""
    global _HANDLER, _LISTENER, _LOG_PATH, _QUEUE_HANDLER

    with _LOCK:
        listener = _LISTENER
        handler = _HANDLER
        logger = logging.getLogger(_LOGGER_NAME)
        logger.handlers.clear()
        _LISTENER = None
        _HANDLER = None
        _QUEUE_HANDLER = None
        _LOG_PATH = None

    if listener is not None:
        with contextlib.suppress(OSError, RuntimeError, ValueError):
            listener.stop()
    if handler is not None:
        with contextlib.suppress(OSError, RuntimeError, ValueError):
            handler.close()


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Emit a structured diagnostics event."""
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        return
    extra = {"event": event}
    extra.update(fields)
    logger.log(level, event, extra=extra)


def log_exception(event: str, exc: BaseException, **fields: Any) -> None:
    """Emit a structured diagnostics event for a caught exception."""
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        return
    extra = {"event": event, "error": str(exc), "error_type": type(exc).__name__}
    extra.update(fields)
    logger.error(event, exc_info=(type(exc), exc, exc.__traceback__), extra=extra)


def app_context() -> dict[str, Any]:
    """Small runtime context that is useful on startup diagnostics."""
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
