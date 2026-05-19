#!/usr/bin/env python3
"""
Refresh Bomana static datamine assets from one War-Thunder-Datamine checkout.

This is the preferred maintainer entrypoint. It updates both:
- bomana/data/ccrp_bomb_params.json
- bomana/data/fm_speed_limits.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from blkx_extractor import BlkxExtractor
from datamine_utils import (
    BOMBGUNS_SUBDIR,
    read_datamine_version,
    read_git_commit,
    require_datamine_dir,
)
from fm_speed_extractor import extract_from_root

_JSON_READ_ERRORS = (OSError, json.JSONDecodeError)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _count_existing_bombs(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except _JSON_READ_ERRORS:
        return None
    params = payload.get("ballistic_params", {})
    return len(params) if isinstance(params, dict) else None


def _count_existing_speed_rows(path: Path) -> tuple[int, int] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except _JSON_READ_ERRORS:
        return None
    meta = payload.get("meta", {})
    if not isinstance(meta, dict):
        return None
    fm_records = meta.get("fm_records")
    unit_records = meta.get("unit_records")
    if isinstance(fm_records, int) and isinstance(unit_records, int):
        return fm_records, unit_records
    return None


def update_assets(
    datamine_root: Path,
    *,
    bomb_output: Path,
    speed_output: Path,
    show_bomb_report: bool,
) -> int:
    bombguns_dir = require_datamine_dir(datamine_root, BOMBGUNS_SUBDIR)

    previous_bombs = _count_existing_bombs(bomb_output)
    previous_speed_rows = _count_existing_speed_rows(speed_output)

    extractor = BlkxExtractor(verbose=show_bomb_report)
    extractor.process_directory(bombguns_dir)
    if not extractor.results:
        raise RuntimeError("no bomb parameters extracted")
    if show_bomb_report:
        extractor.generate_report()
    bombs = extractor.export_ccrp_params(
        str(bomb_output),
        source_root=datamine_root,
        source_subdir=BOMBGUNS_SUBDIR,
    )

    speed_payload = extract_from_root(datamine_root)
    _write_json(speed_output, speed_payload)
    speed_meta = speed_payload["meta"]

    version = read_datamine_version(datamine_root) or "unknown"
    commit = read_git_commit(datamine_root)
    commit_label = commit[:12] if commit else "unknown"

    print("\n[summary] Bomana datamine assets refreshed")
    print(f"  source: version={version} commit={commit_label}")
    print(f"  bombs: {previous_bombs if previous_bombs is not None else '-'} -> {len(bombs)}")
    if previous_speed_rows is None:
        print(
            "  speed: - -> "
            f"fm={speed_meta.get('fm_records', 0)} unit={speed_meta.get('unit_records', 0)}"
        )
    else:
        prev_fm, prev_unit = previous_speed_rows
        print(
            "  speed: "
            f"fm={prev_fm} unit={prev_unit} -> "
            f"fm={speed_meta.get('fm_records', 0)} unit={speed_meta.get('unit_records', 0)}"
        )
    print(f"  wrote: {bomb_output}")
    print(f"  wrote: {speed_output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Bomana bomb + speed-limit JSON from War-Thunder-Datamine."
    )
    parser.add_argument("datamine_root", help="War-Thunder-Datamine repo root path")
    parser.add_argument(
        "--bomb-output",
        default="bomana/data/ccrp_bomb_params.json",
        help="bomb JSON output path",
    )
    parser.add_argument(
        "--speed-output",
        default="bomana/data/fm_speed_limits.json",
        help="speed-limit JSON output path",
    )
    parser.add_argument(
        "--no-bomb-report",
        action="store_true",
        help="skip the detailed bomb extraction console report",
    )
    args = parser.parse_args()

    datamine_root = Path(args.datamine_root).resolve()
    bomb_output = Path(args.bomb_output).resolve()
    speed_output = Path(args.speed_output).resolve()

    try:
        return update_assets(
            datamine_root,
            bomb_output=bomb_output,
            speed_output=speed_output,
            show_bomb_report=not args.no_bomb_report,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[error] {exc}")
        return 1
    except Exception as exc:
        print(f"[error] update failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
