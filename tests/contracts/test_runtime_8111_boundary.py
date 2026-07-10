# enforces: docs/specs/runtime-8111-boundary.md R8111-01, R8111-02, R8111-04, R8111-06, R8111-08..R8111-10

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from urllib.parse import urlparse

from bomana.config.settings import NetworkConfig
from bomana.core.telemetry import MapObjectsFetcher
from tools import record_8111_session

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_ENDPOINTS = {"/indicators", "/state", "/map_obj.json", "/map_info.json"}
RUNTIME_SOURCES = sorted((ROOT / "bomana").rglob("*.py"))


def runtime_source_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME_SOURCES)


def runtime_8111_endpoints() -> set[str]:
    endpoints: set[str] = set()
    for path in RUNTIME_SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.strip()
                if "127.0.0.1:8111" in text or "localhost:8111" in text:
                    parsed = urlparse(text)
                    if parsed.path:
                        endpoints.add(parsed.path)
            elif isinstance(node, ast.JoinedStr):
                references_api_base = any(
                    isinstance(value, ast.FormattedValue)
                    and ast.unparse(value.value) == "NetworkConfig.API_BASE"
                    for value in node.values
                )
                if references_api_base:
                    endpoints.update(
                        value.value.strip()
                        for value in node.values
                        if isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                        and value.value.strip().startswith("/")
                    )
    return endpoints


def test_runtime_api_base_remains_official_local_8111() -> None:
    assert NetworkConfig.API_BASE in {
        "http://127.0.0.1:8111",
        "http://localhost:8111",
    }


def test_runtime_polling_defaults_match_spec() -> None:
    assert NetworkConfig.POLL_INTERVAL == 0.05
    assert NetworkConfig.BACKOFF_MAX == 1.25


def test_runtime_live_endpoint_whitelist_matches_spec() -> None:
    assert runtime_8111_endpoints() == ALLOWED_ENDPOINTS


def test_runtime_code_does_not_add_memory_or_injection_primitives() -> None:
    source = runtime_source_text()
    forbidden_tokens = (
        "ReadProcessMemory",
        "WriteProcessMemory",
        "CreateRemoteThread",
        "pymem",
        "frida",
        "pyinject",
        "CreateToolhelp32Snapshot",
    )

    assert not [token for token in forbidden_tokens if token in source]

    token_users = [
        path.relative_to(ROOT).as_posix()
        for path in RUNTIME_SOURCES
        if "OpenProcessToken" in path.read_text(encoding="utf-8")
        or "GetTokenInformation" in path.read_text(encoding="utf-8")
    ]
    assert token_users == ["bomana/utils/hotkey_broker.py"]
    broker_source = (ROOT / token_users[0]).read_text(encoding="utf-8")
    assert "GetCurrentProcess" in broker_source
    assert "OpenProcess" in broker_source
    assert "PROCESS_QUERY_LIMITED_INFORMATION" in broker_source
    assert "GetWindowTextW" in broker_source
    assert "QueryFullProcessImageNameW" in broker_source
    assert "WAR_THUNDER_EXECUTABLES" in broker_source
    assert "CreateToolhelp32Snapshot" not in broker_source
    assert "ReadProcessMemory" not in broker_source


def test_runtime_http_json_access_stays_centralized() -> None:
    violations: list[str] = []
    pattern = re.compile(r"\b(requests[.](?:get|post|request)|urlopen|self[.]session[.]get)\s*[(]")
    for path in RUNTIME_SOURCES:
        relative = path.relative_to(ROOT).as_posix()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = pattern.search(line)
            if not match:
                continue
            if relative == "bomana/core/telemetry.py" and match.group(1) == "self.session.get":
                continue
            violations.append(f"{relative}:{line_number}:{match.group(1)}")

    assert violations == []


def test_map_objects_fetcher_does_not_own_map_info_scale_conversion() -> None:
    source = inspect.getsource(MapObjectsFetcher.fetch)

    assert "map_info" not in source


def test_session_recorder_is_fixed_to_official_8111_endpoints() -> None:
    assert record_8111_session.API_BASE in {
        "http://127.0.0.1:8111",
        "http://localhost:8111",
    }
    assert set(record_8111_session.OFFICIAL_ENDPOINTS) == ALLOWED_ENDPOINTS
    assert "api_base" not in vars(record_8111_session.parse_args([]))


def test_session_recorder_omits_machine_identity_and_uses_ignored_output() -> None:
    source = (ROOT / "tools/record_8111_session.py").read_text(encoding="utf-8")
    forbidden_identity_sources = (
        "getpass.getuser",
        "os.getlogin",
        "platform.node",
        "socket.gethostname",
        "COMPUTERNAME",
        "USERNAME",
    )
    forbidden_collection_or_upload = (
        "ReadProcessMemory",
        "CreateToolhelp32Snapshot",
        "OpenProcess(",
        ".post(",
        ".put(",
        "game.log",
        "aces.vromfs",
    )

    assert not [token for token in forbidden_identity_sources if token in source]
    assert not [token for token in forbidden_collection_or_upload if token in source]
    assert record_8111_session.default_output_path().parent == ROOT / "recordings"
    assert "recordings/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
