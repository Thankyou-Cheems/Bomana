from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from urllib.parse import urlparse

from bomana.config import NetworkConfig
from bomana.core.telemetry import MapObjectsFetcher

# enforces: docs/specs/runtime-8111-boundary.md R8111-01..R8111-04

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


def test_runtime_live_endpoint_whitelist_matches_spec() -> None:
    assert runtime_8111_endpoints() == ALLOWED_ENDPOINTS


def test_runtime_code_does_not_add_memory_or_injection_primitives() -> None:
    source = runtime_source_text()
    forbidden_tokens = (
        "ReadProcessMemory",
        "WriteProcessMemory",
        "OpenProcess(",
        "CreateRemoteThread",
        "pymem",
        "frida",
        "pyinject",
    )

    assert not [token for token in forbidden_tokens if token in source]


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
