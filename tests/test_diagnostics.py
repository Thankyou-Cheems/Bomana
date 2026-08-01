import json
import logging

from bomana.utils.diagnostics import configure_diagnostics, log_event, shutdown_diagnostics


def test_diagnostics_writes_structured_jsonl(tmp_path):
    log_path = tmp_path / "diagnostics.log"

    try:
        configured_path = configure_diagnostics(log_path)
        log_event("sample_event", level=logging.WARNING, endpoint="/state", failure_streak=1)
    finally:
        shutdown_diagnostics()

    assert configured_path == log_path
    rows = log_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["event"] == "sample_event"
    assert payload["level"] == "WARNING"
    assert payload["endpoint"] == "/state"
    assert payload["failure_streak"] == 1
