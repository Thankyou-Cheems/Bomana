from __future__ import annotations

import ast
from pathlib import Path

# enforces: docs/specs/startup-elevation.md ELEV-01..ELEV-08

ROOT = Path(__file__).resolve().parents[2]


def read_source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def method_source(source: str, class_name: str, method_name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return ast.get_source_segment(source, child) or ""
    raise AssertionError(f"method not found: {class_name}.{method_name}")


def function_source(source: str, function_name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function not found: {function_name}")


def test_launcher_build_remains_as_invoker() -> None:
    build_source = read_source("tools/build_portable.py").lower()

    assert "--uac-admin" not in build_source
    assert "requireadministrator" not in build_source
    assert "uiaccess=true" not in build_source


def test_default_app_action_uses_bounded_elevation_handoff() -> None:
    launcher_source = read_source("launcher.pyw")
    on_launch = method_source(launcher_source, "LauncherWindow", "_on_launch")
    main_body = function_source(launcher_source, "main")

    assert "self._request_elevated_launch(final_version)" in on_launch
    assert "parse_elevated_app_request" in main_body
    assert main_body.index("parse_elevated_app_request") < main_body.index("LauncherWindow(")
    assert "is_current_process_elevated" in main_body
    assert "_launch_app(base, elevated_channel)" in main_body


def test_elevation_helper_is_current_process_only_and_has_one_input_backend() -> None:
    elevation_source = read_source("launcher/elevation.py")
    runtime_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "bomana").rglob("*.py")
    )

    assert "GetCurrentProcess" in elevation_source
    assert "OpenProcessToken" in elevation_source
    assert "GetTokenInformation" in elevation_source
    assert "ShellExecuteExW" in elevation_source
    assert '"runas"' in elevation_source
    assert "use_last_error=True" in elevation_source
    assert "subprocess.list2cmdline" in elevation_source
    forbidden_elevation_tokens = (
        "CreateToolhelp32Snapshot",
        "Process32First",
        "Process32Next",
        "aces.exe",
        "aces_BE.exe",
        "EasyAntiCheat",
    )
    assert not [token for token in forbidden_elevation_tokens if token in elevation_source]

    forbidden_input_tokens = (
        "SetWindowsHookExW",
        "WH_KEYBOARD_LL",
        "GetAsyncKeyState",
        "RIDEV_INPUTSINK",
    )
    assert "RegisterHotKey" in runtime_source
    assert not [token for token in forbidden_input_tokens if token in runtime_source]


def test_denial_surface_keeps_both_retry_and_ordinary_launch() -> None:
    launcher_source = read_source("launcher.pyw")
    fallback_body = method_source(
        launcher_source,
        "LauncherWindow",
        "_show_elevation_fallback",
    )

    assert "F7-F11" in fallback_body
    assert "8111" in fallback_body
    assert "管理员权限重试" in launcher_source
    assert "普通权限启动" in fallback_body
    assert "pack_forget" not in fallback_body


def test_one_click_maps_to_one_shell_execute_request() -> None:
    launcher_source = read_source("launcher.pyw")
    request_body = method_source(
        launcher_source,
        "LauncherWindow",
        "_request_elevated_launch",
    )

    assert request_body.count("request_elevated_app(") == 1
    assert "while " not in request_body
    assert request_body.count("self._request_elevated_launch(") == 0
