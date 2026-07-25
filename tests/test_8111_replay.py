from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from bomana.core.clock import SystemClock
from bomana.core.logic import GameLogic
from bomana.core.telemetry import HttpJson
from tools.build_8111_replay_fixture import build_fixture, validate_fixture_manifest
from tools.replay_8111_session import _parse_speed, replay_session
from tools.session_8111 import OFFICIAL_ENDPOINTS, SessionFormatError, load_recorded_session

FIXTURE_DIR = Path(__file__).parent / "fixtures/8111"
REAL_SORTIE_MANIFEST = FIXTURE_DIR / "full_sortie_20260710.manifest.json"


def _success(payload: Any) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    return {
        "ok": True,
        "error_kind": "",
        "elapsed_ms": 1.0,
        "status_code": 200,
        "body_size": len(body),
        "body_sha256": "a" * 64,
        "content_type": "application/json",
        "payload": payload,
        "payload_type": type(payload).__name__,
    }


def _failure(kind: str = "invalid_json") -> dict[str, Any]:
    return {
        "ok": False,
        "error_kind": kind,
        "elapsed_ms": 1.0,
        "status_code": 200,
        "body_size": 0,
        "body_sha256": "b" * 64,
        "content_type": "application/json",
    }


def _sample(
    seq: int,
    elapsed: float,
    *,
    player: bool,
    ias: float,
    fuel: float,
    weapon2: int = 0,
    map_failure: bool = False,
    map_info: bool = False,
) -> dict[str, Any]:
    indicators = {
        "valid": True,
        "type": "saab_jas39c_south_africa" if player else "dummy_plane",
        "weapon2": weapon2,
    }
    state = {
        "valid": True,
        "IAS, km/h": ias,
        "Vy, m/s": 0.0,
        "Mfuel, kg": fuel,
        "Mfuel0, kg": 4000.0,
        "H, m": 1000.0 if ias >= 80.0 else 0.0,
        "TAS, km/h": ias,
        "M": 1.4 if ias >= 1500.0 else 0.4,
        "gear, %": 0.0 if ias >= 80.0 else 100.0,
    }
    map_payload = (
        [{"type": "aircraft", "icon": "player", "x": 0.5, "y": 0.5, "dx": 1, "dy": 0}]
        if player
        else []
    )
    responses = {
        "/indicators": _success(indicators),
        "/state": _success(state),
        "/map_obj.json": _failure() if map_failure else _success(map_payload),
    }
    if map_info:
        responses["/map_info.json"] = _success(
            {
                "valid": True,
                "grid_size": [1000.0, 1000.0],
                "grid_steps": [100.0, 100.0],
                "grid_zero": [0.0, 0.0],
                "map_min": [0.0, 0.0],
                "map_max": [1000.0, 1000.0],
            }
        )
    return {
        "record_type": "sample",
        "seq": seq,
        "elapsed_sec": elapsed,
        "responses": responses,
    }


def _stats(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {
        endpoint: {"attempts": 0, "ok": 0, "failures": 0, "errors": {}}
        for endpoint in OFFICIAL_ENDPOINTS
    }
    for sample in samples:
        for endpoint, response in sample["responses"].items():
            result[endpoint]["attempts"] += 1
            if response["ok"]:
                result[endpoint]["ok"] += 1
            else:
                result[endpoint]["failures"] += 1
                kind = response["error_kind"]
                errors = result[endpoint]["errors"]
                errors[kind] = errors.get(kind, 0) + 1
    return result


def _write_full_sortie(path: Path) -> None:
    samples = [
        _sample(0, 0.0, player=False, ias=0.0, fuel=0.0, map_failure=True, map_info=True),
        _sample(1, 2.0, player=False, ias=0.0, fuel=0.0, map_failure=True),
        _sample(2, 10.0, player=True, ias=0.0, fuel=3000.0),
        _sample(3, 11.1, player=True, ias=0.0, fuel=3000.0),
        _sample(4, 20.0, player=True, ias=300.0, fuel=2900.0),
        _sample(5, 600.0, player=True, ias=0.0, fuel=2000.0),
        _sample(6, 610.0, player=True, ias=0.0, fuel=3000.0),
        _sample(7, 620.0, player=True, ias=300.0, fuel=2950.0),
        _sample(8, 700.0, player=True, ias=500.0, fuel=2800.0, weapon2=1),
        _sample(9, 701.0, player=True, ias=500.0, fuel=2790.0),
        _sample(10, 920.0, player=True, ias=1550.0, fuel=2500.0),
        _sample(11, 930.0, player=False, ias=1550.0, fuel=2500.0),
    ]
    records = [
        {
            "record_type": "meta",
            "schema_version": 1,
            "started_at_utc": "2026-07-10T10:00:00.000Z",
            "api_base": "http://127.0.0.1:8111",
            "endpoints": list(OFFICIAL_ENDPOINTS),
            "interval_sec": 0.25,
            "map_info_interval_sec": 30.0,
            "label": "synthetic-full-sortie",
            "game_version": "test",
            "mode": "SB",
        },
        *samples,
        {
            "record_type": "summary",
            "schema_version": 1,
            "finished_at_utc": "2026-07-10T10:15:31.000Z",
            "duration_sec": 931.0,
            "samples": len(samples),
            "interrupted": False,
            "aircraft_types": ["dummy_plane", "saab_jas39c_south_africa"],
            "endpoint_stats": _stats(samples),
        },
    ]
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")


def test_full_sortie_replay_drives_production_logic_with_virtual_time(tmp_path: Path) -> None:
    recording = tmp_path / "full-sortie.jsonl"
    _write_full_sortie(recording)

    report = replay_session(
        load_recorded_session(recording),
        speed=None,
        profile="full-sortie",
    )

    assert report["passed"] is True
    assert all(report["checks"].values())
    assert report["replay"]["processed_samples"] == 12
    assert report["coverage"]["max_cycle"] == 2
    assert report["coverage"]["max_sortie_id"] == 2
    assert report["coverage"]["takeoffs_sec"] == [20.0, 620.0]
    assert report["coverage"]["landings_sec"] == [600.0]
    assert report["coverage"]["refits_sec"] == [610.0]


def test_tracked_real_sortie_fixture_replays_in_standard_suite() -> None:
    manifest = json.loads(REAL_SORTIE_MANIFEST.read_text(encoding="utf-8"))
    validate_fixture_manifest(manifest)
    recording = FIXTURE_DIR / manifest["session_file"]
    fixture_hash = hashlib.sha256(recording.read_bytes()).hexdigest()

    assert fixture_hash == manifest["session_sha256"]
    assert fixture_hash == manifest["source"]["recording_sha256"]
    assert manifest["privacy"] == {
        "profile": "raw-official-8111-v1",
        "coordinates_preserved": True,
        "recorder_identity_fields_omitted": True,
    }

    session = load_recorded_session(recording)
    assert len(session.samples) == manifest["source"]["samples"] == 4281
    assert session.summary["duration_sec"] == manifest["source"]["duration_sec"]
    report = replay_session(session, speed=None, profile="full-sortie")
    expected = manifest["expected"]

    assert report["passed"] is True
    assert sorted(report["checks"]) == expected["checks"]
    assert all(report["checks"].values())
    assert report["coverage"]["takeoffs_sec"] == expected["takeoffs_sec"]
    assert report["coverage"]["landings_sec"] == expected["landings_sec"]
    assert report["coverage"]["refits_sec"] == expected["refits_sec"]
    assert len(report["coverage"]["weapon2_pulses_sec"]) == expected["weapon2_pulse_count"]
    assert report["coverage"]["player_losses_sec"] == expected["player_losses_sec"]
    assert report["coverage"]["max_cycle"] == expected["max_cycle"]
    assert report["coverage"]["max_sortie_id"] == expected["max_sortie_id"]
    assert report["coverage"]["lobby_endpoint_failures"] == expected["lobby_endpoint_failures"]


def test_real_sortie_weapon_pulses_do_not_claim_selected_store_identity() -> None:
    manifest = json.loads(REAL_SORTIE_MANIFEST.read_text(encoding="utf-8"))
    session = load_recorded_session(FIXTURE_DIR / manifest["session_file"])
    indicator_keys: set[str] = set()
    weapon2_values: set[float] = set()

    for sample in session.samples:
        result = sample["responses"]["/indicators"]
        payload = result.get("payload")
        if not result["ok"] or not isinstance(payload, dict):
            continue
        indicator_keys.update(str(key) for key in payload)
        if "weapon2" in payload:
            weapon2_values.add(float(payload["weapon2"]))

    assert {"weapon2", "weapon4"} <= indicator_keys
    assert weapon2_values == {0.0, 1.0}
    assert not any(
        token in key.lower()
        for key in indicator_keys
        for token in ("selected", "loadout", "missile", "bomb", "ammo")
    )


def test_fixture_importer_copies_validated_gzip_bytes_exactly(tmp_path: Path) -> None:
    plain = tmp_path / "source.jsonl"
    recording = tmp_path / "source.jsonl.gz"
    _write_full_sortie(plain)
    recording.write_bytes(gzip.compress(plain.read_bytes(), mtime=0))

    session_path, manifest_path = build_fixture(
        recording,
        fixture_id="test-full-sortie",
        output_dir=tmp_path / "fixtures",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert session_path.read_bytes() == recording.read_bytes()
    assert manifest["session_sha256"] == manifest["source"]["recording_sha256"]
    assert manifest["privacy"]["coordinates_preserved"] is True


def test_fixture_manifest_rejects_changed_raw_privacy_profile() -> None:
    manifest = json.loads(REAL_SORTIE_MANIFEST.read_text(encoding="utf-8"))
    manifest["privacy"]["coordinates_preserved"] = False

    with pytest.raises(SessionFormatError):
        validate_fixture_manifest(manifest)


def test_normal_game_logic_keeps_production_clock_and_http_defaults() -> None:
    game = GameLogic()

    assert isinstance(game.clock, SystemClock)
    assert game.session is not None
    assert isinstance(game.http, HttpJson)


def test_loader_rejects_sequence_tampering(tmp_path: Path) -> None:
    recording = tmp_path / "tampered.jsonl"
    _write_full_sortie(recording)
    records = [json.loads(line) for line in recording.read_text(encoding="utf-8").splitlines()]
    records[2]["seq"] = 99
    recording.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")

    with pytest.raises(SessionFormatError, match="sequence mismatch"):
        load_recorded_session(recording)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "invalid"])
def test_speed_rejects_non_positive_or_non_finite_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_speed(value)


def test_max_speed_has_no_sleep_rate() -> None:
    assert _parse_speed("max") is None
    assert _parse_speed("20") == 20.0
