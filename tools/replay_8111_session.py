#!/usr/bin/env python3
"""Replay a validated 8111 recording through production GameLogic."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bomana.core.logic import GameLogic  # noqa: E402
from bomana.core.state import Phase, UISnapshot  # noqa: E402
from bomana.core.telemetry import Budget, FetchResult  # noqa: E402
from tools.session_8111 import (  # noqa: E402
    MAP_INFO_ENDPOINT,
    RecordedSession,
    SessionFormatError,
    load_recorded_session,
)


class ReplayClock:
    """Wall clock controlled by each recording sample's elapsed time."""

    def __init__(self, started_at_utc: str) -> None:
        self._epoch = datetime.fromisoformat(started_at_utc.replace("Z", "+00:00")).timestamp()
        self.elapsed_sec = 0.0

    def set_elapsed(self, elapsed_sec: float) -> None:
        self.elapsed_sec = elapsed_sec

    def time(self) -> float:
        return self._epoch + self.elapsed_sec


class RecordedHttpJson:
    """HttpJson-compatible adapter that can only return the active local frame."""

    def __init__(self) -> None:
        self._responses: dict[str, dict[str, Any]] = {}
        self._latest_map_info: dict[str, Any] | None = None

    def set_sample(self, sample: dict[str, Any]) -> None:
        self._responses = sample["responses"]
        if MAP_INFO_ENDPOINT in self._responses:
            self._latest_map_info = self._responses[MAP_INFO_ENDPOINT]

    def get_json(self, url: str, _budget: Budget) -> FetchResult:
        endpoint = urlparse(url).path
        recorded = (
            self._latest_map_info
            if endpoint == MAP_INFO_ENDPOINT
            else self._responses.get(endpoint)
        )
        if recorded is None:
            return FetchResult(endpoint=endpoint, ok=False, error_kind="not_recorded")
        return FetchResult(
            endpoint=endpoint,
            ok=bool(recorded["ok"]),
            payload=recorded.get("payload"),
            error_kind=str(recorded.get("error_kind") or ""),
            elapsed_ms=float(recorded.get("elapsed_ms") or 0.0),
            status_code=recorded.get("status_code"),
        )


@dataclass
class ReplayObserver:
    """Collect sanitized, user-auditable coverage from snapshots and raw controls."""

    phase_transitions: list[dict[str, Any]] = field(default_factory=list)
    takeoffs: list[float] = field(default_factory=list)
    landings: list[float] = field(default_factory=list)
    refits: list[float] = field(default_factory=list)
    weapon2_pulses: list[float] = field(default_factory=list)
    player_losses: list[float] = field(default_factory=list)
    max_cycle: int = 0
    max_sortie_id: int = 0
    overspeed_levels: set[str] = field(default_factory=set)
    lobby_failures: int = 0
    _previous_phase: Phase | None = None
    _previous_on_ground: bool | None = None
    _previous_sortie_id: int = 0
    _previous_weapon2: bool = False
    _previous_player: bool | None = None
    _alive_seen: bool = False

    @staticmethod
    def _weapon2_active(sample: dict[str, Any]) -> bool:
        indicators = sample["responses"]["/indicators"]
        payload = indicators.get("payload")
        if not indicators["ok"] or not isinstance(payload, dict):
            return False
        value = payload.get("weapon2", 0)
        try:
            return float(value) > 0.0
        except TypeError, ValueError:
            return bool(value)

    def observe(self, elapsed_sec: float, sample: dict[str, Any], snapshot: UISnapshot) -> None:
        if not self._alive_seen:
            self.lobby_failures += sum(
                not response["ok"] for response in sample["responses"].values()
            )
        if snapshot.phase == Phase.ALIVE:
            self._alive_seen = True

        if snapshot.phase != self._previous_phase:
            self.phase_transitions.append(
                {
                    "elapsed_sec": elapsed_sec,
                    "from": self._previous_phase.name if self._previous_phase else None,
                    "to": snapshot.phase.name,
                }
            )
            self._previous_phase = snapshot.phase

        if (
            snapshot.phase in (Phase.ALIVE, Phase.LOSS_PENDING)
            and snapshot.source_debug.player_present
        ):
            if self._previous_on_ground is True and not snapshot.on_ground:
                self.takeoffs.append(elapsed_sec)
            elif self._previous_on_ground is False and snapshot.on_ground:
                self.landings.append(elapsed_sec)
            self._previous_on_ground = snapshot.on_ground

        if self._previous_sortie_id > 0 and snapshot.sortie_id > self._previous_sortie_id:
            self.refits.append(elapsed_sec)
        self._previous_sortie_id = snapshot.sortie_id
        self.max_sortie_id = max(self.max_sortie_id, snapshot.sortie_id)

        weapon2 = self._weapon2_active(sample)
        if weapon2 and not self._previous_weapon2:
            self.weapon2_pulses.append(elapsed_sec)
        self._previous_weapon2 = weapon2

        player = snapshot.source_debug.player_present
        if self._previous_player is True and not player:
            self.player_losses.append(elapsed_sec)
        self._previous_player = player

        self.max_cycle = max(self.max_cycle, snapshot.cycle or 0)
        self.overspeed_levels.add(snapshot.overspeed_level)


def _full_sortie_checks(observer: ReplayObserver, processed: int, expected: int) -> dict[str, bool]:
    return {
        "all_samples_processed": processed == expected,
        "lobby_endpoint_failures_observed": observer.lobby_failures > 0,
        "alive_phase_observed": any(item["to"] == "ALIVE" for item in observer.phase_transitions),
        "two_takeoffs_observed": len(observer.takeoffs) >= 2,
        "landing_observed": len(observer.landings) >= 1,
        "refit_observed": len(observer.refits) >= 1,
        "bomb_release_pulse_observed": len(observer.weapon2_pulses) >= 1,
        "cycle_rollover_observed": observer.max_cycle >= 2,
        "critical_overspeed_observed": "critical" in observer.overspeed_levels,
        "player_loss_observed": len(observer.player_losses) >= 1,
    }


def _report_path(input_path: Path) -> Path:
    name = input_path.name.removesuffix(".gz").removesuffix(".jsonl")
    return input_path.with_name(f"{name}.replay-report.json")


def replay_session(
    session: RecordedSession,
    *,
    speed: float | None,
    profile: str,
) -> dict[str, Any]:
    """Run all frames; ``None`` speed means maximum throughput."""

    replay_clock = ReplayClock(session.meta["started_at_utc"])
    recorded_http = RecordedHttpJson()
    game = GameLogic(clock=replay_clock, http=recorded_http)
    observer = ReplayObserver()
    real_started = time.perf_counter()
    processed = 0

    for sample in session.samples:
        elapsed_sec = float(sample["elapsed_sec"])
        if speed is not None:
            target = real_started + elapsed_sec / speed
            delay = target - time.perf_counter()
            if delay > 0.0:
                time.sleep(delay)
        replay_clock.set_elapsed(elapsed_sec)
        recorded_http.set_sample(sample)
        game.tick()
        observer.observe(elapsed_sec, sample, game.snapshot())
        processed += 1

    wall_duration = max(0.0, time.perf_counter() - real_started)
    checks = (
        _full_sortie_checks(observer, processed, len(session.samples))
        if profile == "full-sortie"
        else {"all_samples_processed": processed == len(session.samples)}
    )
    return {
        "report_version": 1,
        "input": {
            "path": str(session.path),
            "sha256": session.sha256,
            "samples": len(session.samples),
            "duration_sec": session.summary["duration_sec"],
            "aircraft_types": session.summary["aircraft_types"],
            "endpoint_stats": session.summary["endpoint_stats"],
        },
        "replay": {
            "profile": profile,
            "speed": "max" if speed is None else speed,
            "processed_samples": processed,
            "wall_duration_sec": round(wall_duration, 6),
            "samples_per_sec": round(processed / wall_duration, 3) if wall_duration else None,
        },
        "coverage": {
            "phase_transitions": observer.phase_transitions,
            "takeoffs_sec": observer.takeoffs,
            "landings_sec": observer.landings,
            "refits_sec": observer.refits,
            "weapon2_pulses_sec": observer.weapon2_pulses,
            "player_losses_sec": observer.player_losses,
            "max_cycle": observer.max_cycle,
            "max_sortie_id": observer.max_sortie_id,
            "overspeed_levels": sorted(observer.overspeed_levels),
            "lobby_endpoint_failures": observer.lobby_failures,
        },
        "checks": checks,
        "passed": all(checks.values()),
        "limitations": [
            "Replay validates deterministic core logic, not Tk rendering or global hotkeys.",
            "Recorded 4 Hz input cannot reproduce timing behavior above the capture cadence.",
        ],
    }


def _parse_speed(value: str) -> float | None:
    if value.lower() == "max":
        return None
    try:
        speed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("speed must be 'max' or a positive number") from exc
    if not math.isfinite(speed) or speed <= 0.0:
        raise argparse.ArgumentTypeError("speed must be 'max' or a positive number")
    return speed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path, help="completed .jsonl or .jsonl.gz recording")
    parser.add_argument(
        "--speed",
        type=_parse_speed,
        default=None,
        help="replay rate such as 20 or 100; default/max runs without sleeping",
    )
    parser.add_argument(
        "--profile",
        choices=("none", "full-sortie"),
        default="none",
        help="coverage profile to enforce",
    )
    parser.add_argument("--report", type=Path, default=None, help="output report JSON path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        session = load_recorded_session(args.recording)
        report = replay_session(session, speed=args.speed, profile=args.profile)
        report_path = (args.report or _report_path(session.path)).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, SessionFormatError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "report": str(report_path),
                "passed": report["passed"],
                "samples": report["replay"]["processed_samples"],
                "wall_duration_sec": report["replay"]["wall_duration_sec"],
                "checks": report["checks"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
