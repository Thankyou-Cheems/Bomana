#!/usr/bin/env python3
"""
Refresh Bomana static datamine assets from one War-Thunder-Datamine checkout.

This is the preferred maintainer entrypoint. It updates:
- bomana/data/ccrp_bomb_params.json
- bomana/data/fm_speed_limits.json
- bomana/data/weapon_fire_control.json
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
    require_clean_git_checkout,
    require_datamine_dir,
)
from fm_speed_extractor import extract_from_root
from weapon_fire_control_extractor import extract_catalog, write_catalog

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


def _count_existing_weapons(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except _JSON_READ_ERRORS:
        return None
    weapons = payload.get("weapons", {})
    return len(weapons) if isinstance(weapons, dict) else None


def update_assets(
    datamine_root: Path,
    *,
    bomb_output: Path,
    speed_output: Path,
    show_bomb_report: bool,
    weapon_output: Path | None = None,
    weapon_schema: Path | None = None,
    refresh_speed: bool = True,
    refresh_weapons: bool = True,
) -> int:
    require_clean_git_checkout(datamine_root)
    bombguns_dir = require_datamine_dir(datamine_root, BOMBGUNS_SUBDIR)

    previous_bombs = _count_existing_bombs(bomb_output)
    previous_speed_rows = _count_existing_speed_rows(speed_output) if refresh_speed else None
    previous_weapons = (
        _count_existing_weapons(weapon_output)
        if refresh_weapons and weapon_output is not None
        else None
    )

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

    speed_meta: dict[str, Any] | None = None
    if refresh_speed:
        speed_payload = extract_from_root(datamine_root)
        _write_json(speed_output, speed_payload)
        speed_meta = speed_payload["meta"]

    weapon_meta: dict[str, Any] | None = None
    if refresh_weapons:
        if weapon_output is None or weapon_schema is None:
            raise RuntimeError("weapon output and schema are required when refreshing weapons")
        weapon_payload = extract_catalog(
            datamine_root,
            schema_path=weapon_schema,
            require_clean=False,
        )
        write_catalog(weapon_output, weapon_payload)
        weapon_meta = weapon_payload["meta"]

    version = read_datamine_version(datamine_root) or "unknown"
    commit = read_git_commit(datamine_root)
    commit_label = commit[:12] if commit else "unknown"

    print("\n[summary] Bomana datamine assets refreshed")
    print(f"  source: version={version} commit={commit_label}")
    print(f"  bombs: {previous_bombs if previous_bombs is not None else '-'} -> {len(bombs)}")
    if speed_meta is None:
        print("  speed: unchanged (--skip-speed)")
    elif previous_speed_rows is None:
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
    if weapon_meta is None:
        print("  weapons: unchanged (--skip-weapons)")
    else:
        print(
            "  weapons: "
            f"{previous_weapons if previous_weapons is not None else '-'} -> "
            f"{weapon_meta['weapon_count']} "
            f"(aircraft={weapon_meta['aircraft_count']} "
            f"unresolved={len(weapon_meta['unresolved_references'])})"
        )
    print(f"  wrote: {bomb_output}")
    if speed_meta is not None:
        print(f"  wrote: {speed_output}")
    if weapon_meta is not None:
        print(f"  wrote: {weapon_output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Bomana datamine-backed bomb, speed, and weapon JSON assets."
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
        "--weapon-output",
        default="bomana/data/weapon_fire_control.json",
        help="weapon fire-control JSON output path",
    )
    parser.add_argument(
        "--weapon-schema",
        default="docs/specs/schemas/weapon-fire-control.schema.json",
        help="canonical weapon fire-control schema path",
    )
    parser.add_argument(
        "--no-bomb-report",
        action="store_true",
        help="skip the detailed bomb extraction console report",
    )
    parser.add_argument(
        "--skip-speed",
        action="store_true",
        help="leave fm_speed_limits.json unchanged",
    )
    parser.add_argument(
        "--skip-weapons",
        action="store_true",
        help="leave weapon_fire_control.json unchanged",
    )
    args = parser.parse_args()

    datamine_root = Path(args.datamine_root).resolve()
    bomb_output = Path(args.bomb_output).resolve()
    speed_output = Path(args.speed_output).resolve()
    weapon_output = Path(args.weapon_output).resolve()
    weapon_schema = Path(args.weapon_schema).resolve()

    try:
        return update_assets(
            datamine_root,
            bomb_output=bomb_output,
            speed_output=speed_output,
            show_bomb_report=not args.no_bomb_report,
            weapon_output=weapon_output,
            weapon_schema=weapon_schema,
            refresh_speed=not args.skip_speed,
            refresh_weapons=not args.skip_weapons,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[error] {exc}")
        return 1
    except Exception as exc:
        print(f"[error] update failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
