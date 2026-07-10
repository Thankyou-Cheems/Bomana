#!/usr/bin/env python3
"""Record synchronized raw payloads from War Thunder's official 8111 API."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TextIO

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bomana.config.settings import ZoneConfig  # noqa: E402

SESSION_RECORD_SCHEMA_PATH = ROOT / "docs/specs/schemas/8111-session-record.schema.json"
SESSION_RECORD_SCHEMA = json.loads(SESSION_RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_VERSION = int(SESSION_RECORD_SCHEMA["x-format-version"])
API_BASE = "http://127.0.0.1:8111"
FAST_ENDPOINTS = ("/indicators", "/state", "/map_obj.json")
MAP_INFO_ENDPOINT = "/map_info.json"
OFFICIAL_ENDPOINTS = (*FAST_ENDPOINTS, MAP_INFO_ENDPOINT)
DEFAULT_INTERVAL_SEC = 0.25
DEFAULT_PROGRESS_INTERVAL_SEC = 5.0
CONNECT_TIMEOUT_SEC = 0.15
READ_TIMEOUT_SEC = 0.30
MAP_INFO_RETRY_SEC = 1.0


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...

    def utc_now(self) -> datetime: ...


class SystemClock:
    @staticmethod
    def monotonic() -> float:
        return time.monotonic()

    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(seconds)

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class RecorderConfig:
    output: Path
    interval_sec: float = DEFAULT_INTERVAL_SEC
    duration_sec: float = 0.0
    map_info_interval_sec: float = ZoneConfig.MAP_INFO_CACHE_SEC
    label: str = ""
    game_version: str = ""
    mode: str = "SB"
    force: bool = False

    def validate(self) -> None:
        for name, value in (
            ("interval", self.interval_sec),
            ("duration", self.duration_sec),
            ("map-info interval", self.map_info_interval_sec),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0.05 <= self.interval_sec <= 10.0:
            raise ValueError("interval must be between 0.05 and 10 seconds")
        if self.duration_sec < 0.0:
            raise ValueError("duration must be zero or greater")
        if self.map_info_interval_sec < self.interval_sec:
            raise ValueError("map-info interval must be at least the sample interval")
        if not (self.output.name.endswith(".jsonl") or self.output.name.endswith(".jsonl.gz")):
            raise ValueError("output must end with .jsonl or .jsonl.gz")
        for name, value in (
            ("label", self.label),
            ("game-version", self.game_version),
            ("mode", self.mode),
        ):
            if len(value) > 200:
                raise ValueError(f"{name} must be 200 characters or fewer")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_output_path(clock: Clock | None = None) -> Path:
    active_clock = clock or SystemClock()
    stamp = active_clock.utc_now().strftime("%Y%m%d_%H%M%S")
    return ROOT / "recordings" / f"8111_session_{stamp}.jsonl.gz"


def _partial_path(output: Path) -> Path:
    return output.with_name(f"{output.name}.partial")


def _open_text(path: Path, *, compressed: bool) -> TextIO:
    if compressed:
        return gzip.open(path, mode="wt", encoding="utf-8", newline="\n")
    return path.open(mode="w", encoding="utf-8", newline="\n")


def _write_record(stream: TextIO, payload: dict[str, Any]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    stream.write("\n")


def _fetch_endpoint(
    session: requests.Session,
    endpoint: str,
    *,
    clock: Clock,
) -> dict[str, Any]:
    started = clock.monotonic()
    try:
        response = session.get(
            f"{API_BASE}{endpoint}",
            timeout=(CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC),
        )
    except requests.Timeout:
        return {
            "ok": False,
            "error_kind": "timeout",
            "elapsed_ms": round(max(0.0, clock.monotonic() - started) * 1000.0, 3),
        }
    except requests.RequestException:
        return {
            "ok": False,
            "error_kind": "request_error",
            "elapsed_ms": round(max(0.0, clock.monotonic() - started) * 1000.0, 3),
        }

    elapsed_ms = round(max(0.0, clock.monotonic() - started) * 1000.0, 3)
    content = bytes(response.content or b"")
    result: dict[str, Any] = {
        "ok": False,
        "status_code": int(response.status_code),
        "elapsed_ms": elapsed_ms,
        "body_size": len(content),
        "body_sha256": hashlib.sha256(content).hexdigest(),
        "content_type": str(response.headers.get("content-type", "")),
    }
    if not response.ok:
        result["error_kind"] = "status"
        return result

    try:
        payload = response.json()
    except ValueError:
        result["error_kind"] = "invalid_json"
        return result

    result.update(
        {
            "ok": True,
            "error_kind": "",
            "payload": payload,
            "payload_type": type(payload).__name__,
        }
    )
    return result


def _empty_endpoint_stats() -> dict[str, dict[str, Any]]:
    return {
        endpoint: {"attempts": 0, "ok": 0, "failures": 0, "errors": {}}
        for endpoint in OFFICIAL_ENDPOINTS
    }


def _update_endpoint_stats(
    endpoint_stats: dict[str, dict[str, Any]],
    endpoint: str,
    result: dict[str, Any],
) -> None:
    stats = endpoint_stats[endpoint]
    stats["attempts"] += 1
    if result.get("ok"):
        stats["ok"] += 1
        return
    stats["failures"] += 1
    error_kind = str(result.get("error_kind") or "unknown")
    errors: dict[str, int] = stats["errors"]
    errors[error_kind] = errors.get(error_kind, 0) + 1


def _default_progress(
    elapsed_sec: float,
    samples: int,
    endpoint_stats: dict[str, dict[str, Any]],
) -> None:
    attempts = sum(int(stats["attempts"]) for stats in endpoint_stats.values())
    failures = sum(int(stats["failures"]) for stats in endpoint_stats.values())
    print(
        f"[recording] elapsed={elapsed_sec:7.1f}s samples={samples:5d} "
        f"endpoint_failures={failures}/{attempts}",
        flush=True,
    )


def record_session(
    config: RecorderConfig,
    *,
    session: requests.Session | None = None,
    clock: Clock | None = None,
    progress: Callable[[float, int, dict[str, dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    config.validate()
    active_clock = clock or SystemClock()
    active_progress = progress or _default_progress
    output = config.output.absolute()
    partial = _partial_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not config.force and (output.exists() or partial.exists()):
        raise FileExistsError(f"output already exists: {output}")
    if config.force:
        output.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)

    owned_session = session is None
    active_session = session or requests.Session()
    if hasattr(active_session, "trust_env"):
        active_session.trust_env = False

    started_at = active_clock.utc_now()
    started_monotonic = active_clock.monotonic()
    next_sample = started_monotonic
    next_map_info = started_monotonic
    next_progress = started_monotonic + DEFAULT_PROGRESS_INTERVAL_SEC
    endpoint_stats = _empty_endpoint_stats()
    aircraft_types: set[str] = set()
    samples = 0
    interrupted = False
    compressed = output.name.endswith(".gz")

    try:
        with _open_text(partial, compressed=compressed) as stream:
            _write_record(
                stream,
                {
                    "record_type": "meta",
                    "schema_version": SCHEMA_VERSION,
                    "started_at_utc": _utc_text(started_at),
                    "api_base": API_BASE,
                    "endpoints": list(OFFICIAL_ENDPOINTS),
                    "interval_sec": config.interval_sec,
                    "map_info_interval_sec": config.map_info_interval_sec,
                    "label": config.label,
                    "game_version": config.game_version,
                    "mode": config.mode,
                },
            )

            try:
                while True:
                    now = active_clock.monotonic()
                    elapsed_sec = max(0.0, now - started_monotonic)
                    if config.duration_sec > 0.0 and elapsed_sec >= config.duration_sec:
                        break
                    if now < next_sample:
                        active_clock.sleep(next_sample - now)
                        continue

                    endpoints = list(FAST_ENDPOINTS)
                    map_info_due = now >= next_map_info
                    if map_info_due:
                        endpoints.append(MAP_INFO_ENDPOINT)

                    responses: dict[str, dict[str, Any]] = {}
                    for endpoint in endpoints:
                        result = _fetch_endpoint(active_session, endpoint, clock=active_clock)
                        responses[endpoint] = result
                        _update_endpoint_stats(endpoint_stats, endpoint, result)

                    if map_info_due:
                        map_info_ok = bool(responses[MAP_INFO_ENDPOINT].get("ok"))
                        next_map_info = now + (
                            config.map_info_interval_sec
                            if map_info_ok
                            else min(MAP_INFO_RETRY_SEC, config.map_info_interval_sec)
                        )

                    indicators = responses.get("/indicators", {})
                    payload = indicators.get("payload")
                    if isinstance(payload, dict):
                        aircraft = str(payload.get("type") or "").strip()
                        if aircraft:
                            aircraft_types.add(aircraft)

                    _write_record(
                        stream,
                        {
                            "record_type": "sample",
                            "seq": samples,
                            "elapsed_sec": round(elapsed_sec, 6),
                            "responses": responses,
                        },
                    )
                    samples += 1
                    if samples % max(1, round(1.0 / config.interval_sec)) == 0:
                        stream.flush()

                    after_sample = active_clock.monotonic()
                    next_sample += config.interval_sec
                    if next_sample <= after_sample:
                        missed = int((after_sample - next_sample) // config.interval_sec) + 1
                        next_sample += missed * config.interval_sec
                    if after_sample >= next_progress:
                        active_progress(
                            max(0.0, after_sample - started_monotonic),
                            samples,
                            endpoint_stats,
                        )
                        next_progress = after_sample + DEFAULT_PROGRESS_INTERVAL_SEC
            except KeyboardInterrupt:
                interrupted = True

            finished_monotonic = active_clock.monotonic()
            summary = {
                "record_type": "summary",
                "schema_version": SCHEMA_VERSION,
                "finished_at_utc": _utc_text(active_clock.utc_now()),
                "duration_sec": round(max(0.0, finished_monotonic - started_monotonic), 6),
                "samples": samples,
                "interrupted": interrupted,
                "aircraft_types": sorted(aircraft_types),
                "endpoint_stats": endpoint_stats,
            }
            _write_record(stream, summary)
            stream.flush()

        os.replace(partial, output)
        return summary
    finally:
        if owned_session:
            active_session.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output .jsonl or .jsonl.gz path (default: recordings/8111_session_<UTC>.jsonl.gz)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="recording duration in seconds; zero records until Ctrl+C",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SEC,
        help="sample interval in seconds (default: 0.25)",
    )
    parser.add_argument(
        "--map-info-interval",
        type=float,
        default=ZoneConfig.MAP_INFO_CACHE_SEC,
        help="map_info sample interval in seconds (default: 30)",
    )
    parser.add_argument("--label", default="", help="optional local recording label")
    parser.add_argument("--game-version", default="", help="optional War Thunder version")
    parser.add_argument("--mode", default="SB", help="optional mode label (default: SB)")
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    clock = SystemClock()
    output = args.output or default_output_path(clock)
    config = RecorderConfig(
        output=output,
        interval_sec=args.interval,
        duration_sec=args.duration,
        map_info_interval_sec=args.map_info_interval,
        label=args.label,
        game_version=args.game_version,
        mode=args.mode,
        force=args.force,
    )
    print(f"Recording official 8111 endpoints to: {output.absolute()}")
    print("Start before entering battle; press Ctrl+C once after the sortie ends.")
    try:
        summary = record_session(config, clock=clock)
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "output": str(output.absolute()),
                "samples": summary["samples"],
                "duration_sec": summary["duration_sec"],
                "interrupted": summary["interrupted"],
                "aircraft_types": summary["aircraft_types"],
            },
            ensure_ascii=False,
        )
    )
    if not any(stats["ok"] for stats in summary["endpoint_stats"].values()):
        print("warning: no successful 8111 responses were recorded; enter a live battle and retry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
