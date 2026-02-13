# -*- coding: utf-8 -*-
"""One-shot clog parsing helpers for hybrid scheme C.

This module only reads local `.clog` files from disk and never touches
game process memory.
"""

import ctypes
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

if os.name == "nt":
    import msvcrt


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


def _open_binary_shared(path: Path):
    """Open file with shared read/write flags on Windows for in-use clog."""
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
        raise OSError(err, "CreateFileW failed")

    try:
        fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
    except OSError:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise
    return os.fdopen(fd, "rb")


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
        raise FileNotFoundError("key file not found: %s" % path)

    raw = path.read_bytes()
    if not raw:
        raise ValueError("key file is empty: %s" % path)

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
                raise ValueError("invalid key byte value: %s" % value)
            key.append(value)
        if key:
            return key, str(path)

    return list(raw), str(path)


def _find_latest_clog_file(clog_dir: Path) -> Optional[Path]:
    if (not clog_dir.exists()) or (not clog_dir.is_dir()):
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


def collect_players_one_shot(
    clog_file: Optional[str] = None,
    clog_dir: Optional[str] = None,
    key_file: Optional[str] = None,
    max_log_bytes: int = 8 * 1024 * 1024,
    max_log_lines: int = 60000,
) -> Dict[str, Any]:
    """Read/decrypt clog once and extract candidate players."""
    warnings: List[str] = []

    try:
        xor_key, key_source = _load_xor_key(str(key_file or ""))
    except (OSError, ValueError) as exc:
        xor_key, key_source = list(DEFAULT_XOR_KEY), "builtin_default_fallback"
        warnings.append("key load failed (%s); fallback to builtin key" % exc)

    target_file: Optional[Path] = None
    source_dir = ""
    if clog_file:
        p = Path(clog_file).expanduser()
        if p.exists() and p.is_file():
            target_file = p
        else:
            return {
                "ok": False,
                "status": "clog_file_not_found",
                "source": str(p),
                "key_source": key_source,
                "warnings": warnings,
                "error": "clog file not found",
                "extract": {},
            }
    else:
        if clog_dir:
            d = Path(clog_dir).expanduser()
        else:
            d = _discover_clog_dir()
            if d is None:
                return {
                    "ok": True,
                    "status": "no_clog_dir",
                    "source": "",
                    "key_source": key_source,
                    "warnings": warnings + ["no clog dir discovered"],
                    "error": "",
                    "extract": {},
                }
        source_dir = str(d)
        target_file = _find_latest_clog_file(d)
        if target_file is None:
            return {
                "ok": True,
                "status": "no_clog_file",
                "source": source_dir,
                "key_source": key_source,
                "warnings": warnings + ["no *.clog found"],
                "error": "",
                "extract": {},
            }

    try:
        encrypted, start_offset, file_size = _read_tail_bytes_shared(target_file, int(max_log_bytes))
    except OSError as exc:
        return {
            "ok": False,
            "status": "read_error",
            "source": str(target_file),
            "key_source": key_source,
            "warnings": warnings,
            "error": str(exc),
            "extract": {},
        }

    if not encrypted:
        return {
            "ok": True,
            "status": "empty",
            "source": str(target_file),
            "key_source": key_source,
            "warnings": warnings,
            "error": "",
            "read_window": {
                "file_size": int(file_size),
                "tail_start_offset": int(start_offset),
                "tail_bytes_read": 0,
            },
            "extract": {
                "scan_stats": {"total_lines_scanned": 0, "candidate_lines": 0, "players_detected": 0},
                "players": [],
                "session_markers": [],
                "evidence": [],
            },
        }

    decrypted = _xor_decrypt(encrypted, xor_key, start_offset=start_offset)
    text = decrypted.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > int(max_log_lines):
        lines = lines[-int(max_log_lines):]
    extract = _extract_clog_candidates(lines)

    return {
        "ok": True,
        "status": "parsed",
        "source": str(target_file),
        "source_dir": source_dir,
        "key_source": key_source,
        "warnings": warnings,
        "error": "",
        "read_window": {
            "file_size": int(file_size),
            "tail_start_offset": int(start_offset),
            "tail_bytes_read": len(encrypted),
        },
        "extract": extract,
    }

