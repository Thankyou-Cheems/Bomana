#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""One-shot PoC for scheme C: localhost:8111 + clog hybrid snapshot.

This script is intentionally standalone and non-invasive:
- 8111 is queried once for a realtime snapshot.
- clog is read/decrypted once for candidate player/vehicle extraction.
- outputs a merged JSON report to help feasibility validation.

It does NOT hook game process memory and does NOT modify game files.
"""

import argparse
import ctypes
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests

if os.name == "nt":
    import msvcrt


DEFAULT_API_BASE = "http://127.0.0.1:8111"
DEFAULT_CONNECT_TIMEOUT = 0.15
DEFAULT_READ_TIMEOUT = 0.25

DEFAULT_CLOG_DIR_CANDIDATES = (
    Path.home() / "Saved Games" / "Gaijin" / "WarThunder" / ".game_logs",
    Path.home() / "Documents" / "My Games" / "WarThunder" / ".game_logs",
    Path.home() / "My Games" / "WarThunder" / ".game_logs",
)

PLAYER_HINT_WORDS = (
    "player",
    "nickname",
    "nick",
    "pilot",
    "sender",
    "joined",
    "spawn",
    "killed",
    "team",
    "squad",
    "userid",
    "user_id",
)

SESSION_HINT_WORDS = (
    "session",
    "battle",
    "match",
    "room",
    "server",
    "lobby",
)

NAME_STOP_WORDS = {
    "player",
    "nickname",
    "nick",
    "pilot",
    "sender",
    "joined",
    "spawn",
    "killed",
    "team",
    "server",
    "session",
    "battle",
    "match",
    "lobby",
    "room",
    "userid",
    "user_id",
    "uid",
    "true",
    "false",
    "null",
}

NAME_PATTERNS = (
    re.compile(
        r'"(?:nickname|nick|name|player|pilot|sender)"\s*:\s*"(?P<name>[^"]{2,36})"',
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:nickname|nick|name|player|pilot|sender)\s*[=:]\s*[\"']?(?P<name>[A-Za-z0-9_.\-\[\]]{2,36})[\"']?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?<=\s)|^)(?P<name>[A-Za-z0-9_.\-\[\]]{3,32})\s+(?:joined|spawned|left|killed|damaged|team)\b",
        re.IGNORECASE,
    ),
)

VEHICLE_PATTERNS = (
    re.compile(
        r'"(?:vehicle|aircraft|unit|plane)"\s*:\s*"(?P<vehicle>[^"]{2,60})"',
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:vehicle|aircraft|unit|plane)\s*[=:]\s*[\"']?(?P<vehicle>[A-Za-z0-9_.\-/]{2,60})[\"']?",
        re.IGNORECASE,
    ),
)

SAMPLE_DECRYPTED_LINES = [
    '[INFO] session_start server="eu-1" session_id=abc123',
    '[NET] player_join nickname="AcePilot" uid=10001 team=1',
    '[NET] player_join nickname="Bandit_42" uid=10002 team=2',
    '[NET] spawn nickname="AcePilot" vehicle="f_16c_block_50"',
    '[NET] spawn nickname="Bandit_42" vehicle="mig_29_9_13"',
    '[KILL] killer="Bandit_42" victim="AcePilot"',
]

# Default XOR key from community decrypter reference.
# Can be overridden with --key-file.
DEFAULT_XOR_KEY = [
    130, 135, 151, 64, 141, 139, 70, 11, 187, 115, 148, 3, 229, 179, 131, 83,
    105, 107, 131, 218, 149, 175, 74, 35, 135, 229, 151, 172, 36, 88, 175, 54,
    78, 225, 90, 249, 241, 1, 75, 177, 173, 182, 76, 76, 250, 116, 40, 105,
    194, 139, 17, 23, 213, 182, 71, 206, 179, 183, 205, 85, 254, 249, 193, 36,
    255, 174, 144, 46, 73, 108, 78, 9, 146, 129, 78, 103, 188, 107, 156, 222,
    177, 15, 104, 186, 139, 128, 68, 5, 135, 94, 243, 78, 254, 9, 151, 50,
    192, 173, 159, 233, 187, 253, 77, 6, 145, 80, 137, 110, 224, 232, 238, 153,
    83, 0, 60, 166, 184, 34, 65, 50, 177, 189, 245, 40, 80, 224, 114, 174,
]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_dump(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_latest_clog_file(clog_dir: Path) -> Optional[Path]:
    if not clog_dir.exists() or not clog_dir.is_dir():
        return None
    files = [p for p in clog_dir.glob("*.clog") if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _discover_clog_dir() -> Optional[Path]:
    env_val = os.environ.get("WT_CLOG_DIR", "").strip()
    if env_val:
        p = Path(env_val).expanduser()
        if p.exists() and p.is_dir():
            return p
    for candidate in DEFAULT_CLOG_DIR_CANDIDATES:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _open_binary_shared(path: Path):
    """Open file with shared read/write flags on Windows to handle in-use clog."""
    if os.name != "nt":
        return path.open("rb")

    generic_read = 0x80000000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_share_delete = 0x00000004
    open_existing = 3
    file_attribute_normal = 0x00000080
    invalid_handle_value = ctypes.c_void_p(-1).value

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p

    handle = create_file(
        str(path),
        generic_read,
        file_share_read | file_share_write | file_share_delete,
        None,
        open_existing,
        file_attribute_normal,
        None,
    )
    if handle == invalid_handle_value:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateFileW failed for {path}")

    try:
        fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
    except OSError:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise
    return os.fdopen(fd, "rb")


def _read_tail_lines(path: Path, max_bytes: int, max_lines: int) -> List[str]:
    data, _start, _size = _read_tail_bytes_shared(path, max_bytes)
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _read_tail_bytes_shared(path: Path, max_bytes: int) -> Tuple[bytes, int, int]:
    with _open_binary_shared(path) as f:
        f.seek(0, 2)
        size = f.tell()
        start = max(0, int(size) - max(1, int(max_bytes)))
        f.seek(start)
        data = f.read()
    return data, start, int(size)


def _xor_decrypt(data: bytes, key: List[int], start_offset: int = 0) -> bytes:
    if not key:
        return data
    out = bytearray(len(data))
    key_len = len(key)
    start_mod = int(start_offset) % key_len
    for i, b in enumerate(data):
        out[i] = b ^ key[(start_mod + i) % key_len]
    return bytes(out)


def _load_xor_key(key_file: str) -> Tuple[List[int], str]:
    if not key_file:
        return list(DEFAULT_XOR_KEY), "builtin_default"

    path = Path(key_file).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"key file not found: {path}")

    raw = path.read_bytes()
    if not raw:
        raise ValueError(f"key file is empty: {path}")

    text_like = all((32 <= b <= 126) or (b in (9, 10, 13)) for b in raw)
    if text_like:
        txt = raw.decode("utf-8", errors="ignore").strip()
        tokens = txt.split()
        key: List[int] = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            base = 16 if token.lower().startswith("0x") or re.fullmatch(r"[0-9A-Fa-f]{1,2}", token) else 10
            value = int(token, base)
            if value < 0 or value > 255:
                raise ValueError(f"invalid key byte value {value} from token: {token}")
            key.append(value)
        if key:
            return key, str(path)

    return list(raw), str(path)


def _normalize_name(raw: str) -> Optional[str]:
    name = str(raw or "").strip().strip('"\'')
    if not name:
        return None
    if len(name) < 2 or len(name) > 36:
        return None
    lowered = name.lower()
    if lowered in NAME_STOP_WORDS:
        return None
    if re.fullmatch(r"\d+", name):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.\-\[\] ]{2,36}", name):
        return None
    return name


def _normalize_vehicle(raw: str) -> Optional[str]:
    vehicle = str(raw or "").strip().strip('"\'')
    if not vehicle:
        return None
    if len(vehicle) < 2 or len(vehicle) > 60:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.\-/ ]{2,60}", vehicle):
        return None
    return vehicle


def _extract_clog_candidates(lines: Iterable[str]) -> Dict[str, Any]:
    players: Dict[str, Dict[str, Any]] = {}
    evidence: List[Dict[str, Any]] = []
    session_markers: List[Dict[str, Any]] = []
    total_lines = 0
    candidate_lines = 0

    for idx, line in enumerate(lines, start=1):
        total_lines += 1
        raw = line.strip()
        if not raw:
            continue

        lowered = raw.lower()
        if any(word in lowered for word in SESSION_HINT_WORDS) and len(session_markers) < 30:
            session_markers.append({"line_no": idx, "line": raw[:220]})

        if not any(word in lowered for word in PLAYER_HINT_WORDS):
            continue
        candidate_lines += 1

        names_found: Set[str] = set()
        vehicles_found: Set[str] = set()

        for pattern in NAME_PATTERNS:
            for match in pattern.finditer(raw):
                name = _normalize_name(match.group("name"))
                if name:
                    names_found.add(name)

        for pattern in VEHICLE_PATTERNS:
            for match in pattern.finditer(raw):
                vehicle = _normalize_vehicle(match.group("vehicle"))
                if vehicle:
                    vehicles_found.add(vehicle)

        if not names_found:
            continue

        for name in sorted(names_found):
            entry = players.setdefault(
                name,
                {
                    "name": name,
                    "hits": 0,
                    "vehicles": set(),
                },
            )
            entry["hits"] += 1
            entry["vehicles"].update(vehicles_found)

        if len(evidence) < 120:
            evidence.append(
                {
                    "line_no": idx,
                    "line": raw[:260],
                    "names": sorted(names_found),
                    "vehicles": sorted(vehicles_found),
                }
            )

    player_list: List[Dict[str, Any]] = []
    for item in players.values():
        player_list.append(
            {
                "name": item["name"],
                "hits": int(item["hits"]),
                "vehicles": sorted(item["vehicles"]),
            }
        )
    player_list.sort(key=lambda x: (-int(x["hits"]), x["name"].lower()))

    return {
        "scan_stats": {
            "total_lines_scanned": total_lines,
            "candidate_lines": candidate_lines,
            "players_detected": len(player_list),
        },
        "players": player_list,
        "session_markers": session_markers,
        "evidence": evidence,
    }


def _fetch_json(session: requests.Session, url: str, timeout: Tuple[float, float]) -> Dict[str, Any]:
    try:
        response = session.get(url, timeout=timeout)
    except requests.RequestException as exc:
        return {"ok": False, "status": None, "error": str(exc), "json": None}

    if not response.ok:
        return {"ok": False, "status": response.status_code, "error": "http_error", "json": None}

    try:
        payload = response.json()
    except ValueError:
        return {"ok": False, "status": response.status_code, "error": "invalid_json", "json": None}

    return {"ok": True, "status": response.status_code, "error": "", "json": payload}


def _collect_8111_snapshot(
    api_base: str,
    connect_timeout: float,
    read_timeout: float,
    include_gamechat: bool,
    include_hudmsg: bool,
) -> Dict[str, Any]:
    timeout = (max(0.01, connect_timeout), max(0.01, read_timeout))
    session = requests.Session()
    session.trust_env = False

    endpoints = {
        "indicators": f"{api_base}/indicators",
        "state": f"{api_base}/state",
        "map_obj": f"{api_base}/map_obj.json",
    }
    if include_gamechat:
        endpoints["gamechat"] = f"{api_base}/gamechat?lastId=0"
    if include_hudmsg:
        endpoints["hudmsg"] = f"{api_base}/hudmsg"

    out: Dict[str, Any] = {"endpoints": {}, "summary": {}}
    for name, url in endpoints.items():
        out["endpoints"][name] = _fetch_json(session, url, timeout)

    ind = out["endpoints"].get("indicators", {}).get("json")
    st = out["endpoints"].get("state", {}).get("json")
    mp = out["endpoints"].get("map_obj", {}).get("json")
    gc = out["endpoints"].get("gamechat", {}).get("json")

    map_objects: List[Dict[str, Any]] = []
    if isinstance(mp, list):
        map_objects = [x for x in mp if isinstance(x, dict)]
    elif isinstance(mp, dict):
        objs = mp.get("objects", [])
        if isinstance(objs, list):
            map_objects = [x for x in objs if isinstance(x, dict)]

    player_icon_count = 0
    zone_count = 0
    airfield_count = 0
    for obj in map_objects:
        obj_type = str(obj.get("type", "") or "")
        icon = str(obj.get("icon", "") or "")
        if obj_type == "aircraft" and icon == "Player":
            player_icon_count += 1
        elif obj_type == "bombing_point":
            zone_count += 1
        elif obj_type == "airfield":
            airfield_count += 1

    chat_senders: Set[str] = set()
    if isinstance(gc, list):
        for row in gc:
            if isinstance(row, dict):
                sender = _normalize_name(str(row.get("sender", "") or ""))
                if sender:
                    chat_senders.add(sender)

    out["summary"] = {
        "api_up": any(bool(v.get("ok")) for v in out["endpoints"].values()),
        "aircraft_type": str((ind or {}).get("type", "") or "") if isinstance(ind, dict) else "",
        "map_obj_count": len(map_objects),
        "map_player_icon_count": player_icon_count,
        "map_zone_count": zone_count,
        "map_airfield_count": airfield_count,
        "chat_sender_count": len(chat_senders),
        "chat_senders": sorted(chat_senders),
        "state_ias_kmh": (st or {}).get("IAS, km/h", 0) if isinstance(st, dict) else 0,
        "state_altitude_m": (st or {}).get("H, m", 0) if isinstance(st, dict) else 0,
    }
    return out


def _resolve_clog_lines(args: argparse.Namespace, xor_key: List[int], key_source: str) -> Dict[str, Any]:
    if args.use_sample_clog:
        return {
            "ok": True,
            "mode": "sample",
            "source": "embedded_sample",
            "lines": list(SAMPLE_DECRYPTED_LINES),
            "warnings": [],
        }

    warnings: List[str] = []

    if args.decrypted_log:
        path = Path(args.decrypted_log).expanduser()
        if not path.exists():
            return {"ok": False, "error": f"decrypted log not found: {path}"}
        lines = _read_tail_lines(path, args.max_log_bytes, args.max_log_lines)
        return {
            "ok": True,
            "mode": "decrypted_log",
            "source": str(path),
            "lines": lines,
            "warnings": warnings,
        }

    clog_file: Optional[Path] = None
    if args.clog_file:
        p = Path(args.clog_file).expanduser()
        if p.exists() and p.is_file():
            clog_file = p
        else:
            return {"ok": False, "error": f"clog file not found: {p}"}
    else:
        clog_dir: Optional[Path]
        if args.clog_dir:
            clog_dir = Path(args.clog_dir).expanduser()
        else:
            clog_dir = _discover_clog_dir()
            if clog_dir is None:
                return {
                    "ok": True,
                    "mode": "none",
                    "source": "",
                    "lines": [],
                    "warnings": ["no clog dir discovered; skip clog stage"],
                }
        clog_file = _find_latest_clog_file(clog_dir)
        if clog_file is None:
            return {
                "ok": True,
                "mode": "none",
                "source": str(clog_dir),
                "lines": [],
                "warnings": [f"no *.clog found under {clog_dir}"],
            }

    try:
        encrypted, start_offset, file_size = _read_tail_bytes_shared(clog_file, args.max_log_bytes)
    except OSError as exc:
        return {
            "ok": False,
            "error": f"failed to open/read clog with shared mode: {exc}",
            "clog_file": str(clog_file),
        }

    if not encrypted:
        return {
            "ok": True,
            "mode": "clog_empty",
            "source": str(clog_file),
            "lines": [],
            "warnings": ["selected clog file is empty"],
            "key_source": key_source,
        }

    decrypted = _xor_decrypt(encrypted, xor_key, start_offset=start_offset)
    text = decrypted.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > args.max_log_lines:
        lines = lines[-args.max_log_lines:]

    out_path_str = ""
    if args.decrypted_output or args.keep_decrypted_output:
        if args.decrypted_output:
            out_path = Path(args.decrypted_output).expanduser()
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = Path("tools") / "output" / f"decrypted_clog_{stamp}.log"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(decrypted)
        out_path_str = str(out_path)

    return {
        "ok": True,
        "mode": "clog_decrypt_shared_read_once",
        "source": str(clog_file),
        "decrypted_output": out_path_str,
        "key_source": key_source,
        "read_window": {
            "file_size": int(file_size),
            "tail_start_offset": int(start_offset),
            "tail_bytes_read": len(encrypted),
        },
        "lines": lines,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PoC: one-shot hybrid snapshot from 8111 + clog."
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="8111 base URL.")
    parser.add_argument("--connect-timeout", type=float, default=DEFAULT_CONNECT_TIMEOUT)
    parser.add_argument("--read-timeout", type=float, default=DEFAULT_READ_TIMEOUT)
    parser.add_argument("--disable-gamechat", action="store_true", help="Skip /gamechat query.")
    parser.add_argument("--disable-hudmsg", action="store_true", help="Skip /hudmsg query.")

    parser.add_argument(
        "--use-sample-clog",
        action="store_true",
        help="Use embedded decrypted clog sample lines for parser verification.",
    )
    parser.add_argument("--decrypted-log", default="", help="Path to already decrypted clog text file.")
    parser.add_argument("--clog-file", default="", help="Path to raw .clog file.")
    parser.add_argument("--clog-dir", default="", help="Directory containing .clog files.")
    parser.add_argument(
        "--key-file",
        default="",
        help="Optional XOR key file. Supports text bytes (hex/dec) or raw bytes. Defaults to built-in key.",
    )
    parser.add_argument(
        "--decrypted-output",
        default="",
        help="Optional path to write decrypted tail bytes for inspection.",
    )
    parser.add_argument(
        "--keep-decrypted-output",
        action="store_true",
        help="Keep auto-created decrypted log file.",
    )

    parser.add_argument("--max-log-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--max-log-lines", type=int, default=60000)
    parser.add_argument("--output", default="", help="Output JSON path.")
    args = parser.parse_args()

    started = time.time()
    pre_warnings: List[str] = []

    try:
        xor_key, key_source = _load_xor_key(str(args.key_file or ""))
    except (OSError, ValueError) as exc:
        xor_key, key_source = list(DEFAULT_XOR_KEY), "builtin_default_fallback"
        pre_warnings.append(f"key load failed ({exc}); fallback to builtin key")

    snapshot_8111 = _collect_8111_snapshot(
        api_base=str(args.api_base).rstrip("/"),
        connect_timeout=float(args.connect_timeout),
        read_timeout=float(args.read_timeout),
        include_gamechat=not bool(args.disable_gamechat),
        include_hudmsg=not bool(args.disable_hudmsg),
    )

    clog_stage = _resolve_clog_lines(args, xor_key, key_source)
    warnings: List[str] = list(pre_warnings)
    clog_parse: Dict[str, Any] = {
        "scan_stats": {"total_lines_scanned": 0, "candidate_lines": 0, "players_detected": 0},
        "players": [],
        "session_markers": [],
        "evidence": [],
    }
    if clog_stage.get("ok"):
        warnings.extend(clog_stage.get("warnings", []))
        lines = clog_stage.get("lines", []) or []
        clog_parse = _extract_clog_candidates(lines)
    else:
        warnings.append(str(clog_stage.get("error", "unknown clog stage error")))

    clog_players = {p.get("name", "") for p in clog_parse.get("players", []) if p.get("name")}
    chat_players = set(snapshot_8111.get("summary", {}).get("chat_senders", []))
    merged_names = sorted(clog_players | chat_players)

    report = {
        "meta": {
            "generated_at": _now_iso(),
            "duration_sec": round(time.time() - started, 3),
            "mode": "hybrid_8111_clog_one_shot",
        },
        "inputs": {
            "api_base": str(args.api_base).rstrip("/"),
            "clog_stage": {
                "ok": bool(clog_stage.get("ok")),
                "mode": clog_stage.get("mode", "unknown"),
                "source": clog_stage.get("source", ""),
                "decrypted_output": clog_stage.get("decrypted_output", ""),
                "key_source": clog_stage.get("key_source", key_source),
                "read_window": clog_stage.get("read_window", {}),
            },
        },
        "snapshot_8111": snapshot_8111,
        "clog_extract": clog_parse,
        "merge": {
            "clog_player_count": len(clog_players),
            "chat_player_count": len(chat_players),
            "merged_player_count": len(merged_names),
            "merged_players": merged_names,
        },
        "feasibility": {
            "scheme_c_basic_feasible": bool(
                snapshot_8111.get("summary", {}).get("api_up") and len(clog_players) > 0
            ),
            "notes": [
                "PoC only: clog parser is heuristic and needs real decrypted samples for rule hardening.",
                "clog stage is one-shot only (no tailing) per test scope.",
            ],
        },
        "warnings": warnings,
    }

    if args.output:
        out_path = Path(args.output)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path("tools") / "output" / f"hybrid_8111_clog_probe_{stamp}.json"
    _json_dump(report, out_path)

    print(
        json.dumps(
            {
                "output": str(out_path),
                "api_up": bool(snapshot_8111.get("summary", {}).get("api_up")),
                "clog_players": len(clog_players),
                "merged_players": len(merged_names),
                "warnings": len(warnings),
            },
            ensure_ascii=False,
        )
    )
    if not snapshot_8111.get("summary", {}).get("api_up"):
        print("warning: 8111 endpoints not available. ensure War Thunder battle session is running.")
    if len(clog_players) == 0:
        print("warning: no player candidates extracted from clog stage.")


if __name__ == "__main__":
    main()
