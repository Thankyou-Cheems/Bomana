#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
War Thunder flightmodel speed-limit extractor.

Input: extracted War-Thunder-Datamine repository root.
Output: JSON file with:
  - unit_to_fm mapping (for /indicators.type resolution)
  - fm_speed_limits (IAS VNE + Mach MNE, incl. sweep interpolation points)
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

Number = Union[int, float]


def _remove_json_comments(text: str) -> str:
    """Remove // and /* */ comments so .blkx JSON can be parsed robustly."""
    text = re.sub(r"//.*?(?=\n|$)", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


def _parse_blkx(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    try:
        return json.loads(_remove_json_comments(raw))
    except json.JSONDecodeError:
        return None


def _safe_get(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _normalize_limit_value(value: Any) -> Optional[Union[float, List[List[float]]]]:
    """
    Normalize VNE/MNE value from .blkx:
    - scalar -> float
    - sweep list [s0, v0, s1, v1, ...] -> [[s0, v0], [s1, v1], ...]
    """
    scalar = _to_float(value)
    if scalar is not None:
        return scalar

    if isinstance(value, list):
        if len(value) < 2:
            return None
        if len(value) % 2 != 0:
            return None
        out: List[List[float]] = []
        for i in range(0, len(value), 2):
            sweep = _to_float(value[i])
            limit = _to_float(value[i + 1])
            if sweep is None or limit is None:
                return None
            out.append([sweep, limit])
        out.sort(key=lambda pair: pair[0])
        return out

    if isinstance(value, str) and "," in value:
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if len(parts) < 2 or len(parts) % 2 != 0:
            return None
        out = []
        for i in range(0, len(parts), 2):
            sweep = _to_float(parts[i])
            limit = _to_float(parts[i + 1])
            if sweep is None or limit is None:
                return None
            out.append([sweep, limit])
        out.sort(key=lambda pair: pair[0])
        return out

    return None


def _extract_fm_limits(path: Path) -> Optional[Tuple[str, Dict[str, Any]]]:
    data = _parse_blkx(path)
    if not isinstance(data, dict):
        return None

    fm_name = path.stem
    vne_raw = _safe_get(data, "Aerodynamics", "WingPlane", "Strength", "VNE", default=None)
    if vne_raw is None:
        # Legacy FMs often expose VNE at the top level.
        vne_raw = data.get("Vne")
    if vne_raw is None:
        # Final fallback used by some control-limited flightmodels.
        vne_raw = data.get("VneControl")
    mne_raw = _safe_get(data, "Aerodynamics", "WingPlane", "Strength", "MNE", default=None)
    if mne_raw is None:
        # Legacy FMs often expose MNE as top-level VneMach.
        mne_raw = data.get("VneMach")

    vne = _normalize_limit_value(vne_raw)
    mne = _normalize_limit_value(mne_raw)

    if vne is None and mne is None:
        return None

    return fm_name, {
        "ias": vne,
        "mach": mne,
    }


def _extract_unit_mapping(path: Path) -> Optional[Tuple[str, str]]:
    data = _parse_blkx(path)
    if not isinstance(data, dict):
        return None

    unit_name = path.stem
    fm_file = data.get("fmFile")
    if not isinstance(fm_file, str) or not fm_file:
        return None

    fm_name = fm_file.replace("\\", "/").strip()
    if fm_name.startswith("fm/"):
        fm_name = fm_name[3:]
    if fm_name.endswith(".blk"):
        fm_name = fm_name[:-4]
    elif fm_name.endswith(".blkx"):
        fm_name = fm_name[:-5]
    fm_name = fm_name.strip()
    if not fm_name:
        return None

    return unit_name, fm_name


def extract_from_root(root: Path) -> Dict[str, Any]:
    flightmodels_dir = root / "aces.vromfs.bin_u" / "gamedata" / "flightmodels"
    fm_dir = flightmodels_dir / "fm"

    if not flightmodels_dir.exists():
        raise FileNotFoundError(f"missing directory: {flightmodels_dir}")
    if not fm_dir.exists():
        raise FileNotFoundError(f"missing directory: {fm_dir}")

    fm_limits: Dict[str, Dict[str, Any]] = {}
    unit_to_fm: Dict[str, str] = {}

    fm_files = sorted(fm_dir.glob("*.blkx"))
    for fm_file in fm_files:
        row = _extract_fm_limits(fm_file)
        if row is None:
            continue
        name, payload = row
        fm_limits[name] = payload

    unit_files = sorted(p for p in flightmodels_dir.glob("*.blkx") if p.is_file())
    for unit_file in unit_files:
        row = _extract_unit_mapping(unit_file)
        if row is None:
            continue
        unit_name, fm_name = row
        unit_to_fm[unit_name] = fm_name

    return {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_root_name": root.name,
            "source_subdir": "aces.vromfs.bin_u/gamedata/flightmodels",
            "fm_records": len(fm_limits),
            "unit_records": len(unit_to_fm),
        },
        "unit_to_fm": unit_to_fm,
        "fm_speed_limits": fm_limits,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract IAS/Mach speed limits + unit mapping from War-Thunder-Datamine."
    )
    parser.add_argument(
        "root",
        help="War-Thunder-Datamine root path",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="bomana/data/fm_speed_limits.json",
        help="output json path (default: bomana/data/fm_speed_limits.json)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = Path(args.output).resolve()

    try:
        payload = extract_from_root(root)
    except FileNotFoundError as exc:
        print(f"[error] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[error] extraction failed: {exc}")
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = payload.get("meta", {})
    print(f"[ok] fm={meta.get('fm_records', 0)} unit={meta.get('unit_records', 0)} -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
