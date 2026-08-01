#!/usr/bin/env python3
"""Import a validated raw 8111 recording as a tracked pytest replay fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.replay_8111_session import replay_session  # noqa: E402
from tools.session_8111 import (  # noqa: E402
    RecordedSession,
    SessionFormatError,
    load_recorded_session,
    validate_json_schema,
)

FIXTURE_SCHEMA_PATH = ROOT / "docs/specs/schemas/8111-replay-fixture-manifest.schema.json"
FIXTURE_SCHEMA = json.loads(FIXTURE_SCHEMA_PATH.read_text(encoding="utf-8"))
FIXTURE_VERSION = 1
PRIVACY_PROFILE = "raw-official-8111-v1"


def validate_fixture_manifest(manifest: Any) -> None:
    validate_json_schema(manifest, FIXTURE_SCHEMA, path="fixture manifest")


def _manifest(
    fixture_id: str,
    source: RecordedSession,
    session_path: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    coverage = report["coverage"]
    session_sha256 = hashlib.sha256(session_path.read_bytes()).hexdigest()
    if session_sha256 != source.sha256:
        raise ValueError("tracked fixture bytes differ from the validated source recording")
    manifest = {
        "fixture_version": FIXTURE_VERSION,
        "fixture_id": fixture_id,
        "session_file": session_path.name,
        "session_sha256": session_sha256,
        "source": {
            "recording_sha256": source.sha256,
            "started_at_utc": source.meta["started_at_utc"],
            "samples": len(source.samples),
            "duration_sec": source.summary["duration_sec"],
        },
        "privacy": {
            "profile": PRIVACY_PROFILE,
            "coordinates_preserved": True,
            "recorder_identity_fields_omitted": True,
        },
        "expected": {
            "checks": sorted(report["checks"]),
            "takeoffs_sec": coverage["takeoffs_sec"],
            "landings_sec": coverage["landings_sec"],
            "refits_sec": coverage["refits_sec"],
            "weapon2_pulse_count": len(coverage["weapon2_pulses_sec"]),
            "player_losses_sec": coverage["player_losses_sec"],
            "max_cycle": coverage["max_cycle"],
            "max_sortie_id": coverage["max_sortie_id"],
            "lobby_endpoint_failures": coverage["lobby_endpoint_failures"],
        },
    }
    validate_fixture_manifest(manifest)
    return manifest


def build_fixture(
    recording: Path,
    *,
    fixture_id: str,
    output_dir: Path,
    force: bool = False,
) -> tuple[Path, Path]:
    """Copy exact validated bytes, replay them, and write a provenance manifest."""

    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", fixture_id) is None:
        raise ValueError("fixture id must use lowercase letters, digits, and hyphens")
    if not recording.name.endswith(".jsonl.gz"):
        raise ValueError("tracked raw fixtures must come from a .jsonl.gz recording")
    output_dir = output_dir.resolve()
    stem = fixture_id.replace("-", "_")
    session_path = output_dir / f"{stem}.jsonl.gz"
    manifest_path = output_dir / f"{stem}.manifest.json"
    if not force and (session_path.exists() or manifest_path.exists()):
        raise FileExistsError(f"fixture output already exists in {output_dir}")

    source = load_recorded_session(recording)
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source.path, session_path)
    tracked_session = load_recorded_session(session_path)
    report = replay_session(tracked_session, speed=None, profile="full-sortie")
    if not report["passed"]:
        session_path.unlink(missing_ok=True)
        raise ValueError("raw fixture does not pass the full-sortie profile")
    manifest = _manifest(fixture_id, source, session_path, report)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return session_path, manifest_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path, help="validated raw .jsonl.gz recording")
    parser.add_argument("--fixture-id", required=True, help="lowercase stable fixture identifier")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "tests/fixtures/8111",
        help="tracked fixture directory",
    )
    parser.add_argument("--force", action="store_true", help="replace existing fixture files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        session_path, manifest_path = build_fixture(
            args.recording,
            fixture_id=args.fixture_id,
            output_dir=args.output_dir,
            force=args.force,
        )
    except (FileExistsError, OSError, SessionFormatError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "session": str(session_path),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
