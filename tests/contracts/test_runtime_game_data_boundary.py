# enforces: docs/specs/game-data-boundary.md DATA-01..DATA-05

"""Production runtime must obtain game-state data only from official 8111 endpoints."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from bomana.config.settings import NetworkConfig

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_PYTHON = tuple((ROOT / "bomana").rglob("*.py"))
FORBIDDEN_GAME_PROCESS_TOKENS = (
    "ReadProcessMemory",
    "WriteProcessMemory",
    "VirtualQueryEx",
    "NtReadVirtualMemory",
    "CreateRemoteThread",
    "QueueUserAPC",
    "VirtualAllocEx",
    "CreateToolhelp32Snapshot",
    "Process32First",
    "Process32Next",
    "Module32First",
    "Module32Next",
    "QueryFullProcessImageName",
    "detect_war_thunder_integrity",
    "WAR_THUNDER_EXECUTABLES",
    "SetWindowsHookEx",
    "WH_KEYBOARD_LL",
    "GetAsyncKeyState",
    "RegisterRawInputDevices",
    "SendInput",
    "keybd_event",
    "mouse_event",
    "pymem",
    "frida",
    "aces.exe",
)


def test_production_python_contains_no_game_process_or_memory_reader() -> None:
    for path in PRODUCTION_PYTHON:
        source = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_GAME_PROCESS_TOKENS:
            assert token not in source, f"{path.relative_to(ROOT)} contains {token}"


def test_game_api_base_is_fixed_to_official_loopback_8111() -> None:
    parsed = urlparse(NetworkConfig.API_BASE)

    assert parsed.scheme == "http"
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port == 8111
    assert parsed.path in {"", "/"}
    assert not parsed.username
    assert not parsed.password


def test_runtime_game_http_calls_are_confined_to_telemetry_module() -> None:
    network_call_sites: list[Path] = []
    for path in PRODUCTION_PYTHON:
        source = path.read_text(encoding="utf-8")
        if ".session.get(" in source:
            network_call_sites.append(path.relative_to(ROOT))

    assert network_call_sites == [Path("bomana/core/telemetry.py")]
    telemetry_source = (ROOT / network_call_sites[0]).read_text(encoding="utf-8")
    assert "NetworkConfig.API_BASE" in telemetry_source
    for endpoint in (
        "/indicators",
        "/state",
        "/map_obj.json",
        "/map_info.json",
        "/map.img",
        "/icons.ttf",
    ):
        assert endpoint in telemetry_source


def test_production_has_no_second_outbound_game_data_client() -> None:
    request_imports: list[Path] = []
    socket_imports: list[Path] = []
    forbidden_client_tokens = (
        "urllib.request",
        "http.client",
        "import httpx",
        "import aiohttp",
        "import websocket",
        "win32process",
        "import psutil",
    )
    for path in PRODUCTION_PYTHON:
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        if "import requests" in source or "from requests" in source:
            request_imports.append(relative)
        if "\nimport socket" in f"\n{source}" or "\nfrom socket" in f"\n{source}":
            socket_imports.append(relative)
        for token in forbidden_client_tokens:
            assert token not in source, f"{relative} contains alternate client token {token}"

    assert request_imports == [
        Path("bomana/core/logic.py"),
        Path("bomana/core/telemetry.py"),
    ]
    logic_source = (ROOT / request_imports[0]).read_text(encoding="utf-8")
    assert "requests.get(" not in logic_source
    assert "self.session.get(" not in logic_source
    assert socket_imports == []
