# enforces: docs/specs/startup-elevation.md ELEV-01..ELEV-12

from __future__ import annotations

import ast
from pathlib import Path

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


def test_launcher_and_python_app_remain_as_invoker() -> None:
    build_source = read_source("tools/build_portable.py").lower()
    launcher_source = read_source("launcher.pyw")
    on_launch = method_source(launcher_source, "LauncherWindow", "_on_launch")
    main_body = function_source(launcher_source, "main")

    assert "--uac-admin" not in build_source
    assert "requireadministrator" not in build_source
    assert "uiaccess=true" not in build_source
    assert "_prepare_ordinary_launch(final_version)" in on_launch
    forbidden = (
        "--bomana-elevated-app",
        "elevated_handoff",
        "request_elevated_app",
        "is_current_process_elevated",
        "ShellExecuteExW",
        '"runas"',
    )
    assert not [token for token in forbidden if token in launcher_source]
    assert "_launch_app(base, selected_channel)" in main_body


def test_ordinary_hotkeys_start_without_game_process_probe_and_uac_is_explicit() -> None:
    runtime_source = read_source("bomana/ui/runtime_services.py")
    app_source = read_source("bomana/ui/app.py")
    init_body = method_source(runtime_source, "AppRuntimeServices", "init_global_hotkeys")
    elevate_body = method_source(
        runtime_source,
        "AppRuntimeServices",
        "enable_elevated_hotkeys",
    )
    action_body = method_source(app_source, "App", "_on_nudge_action")

    assert "self._start_local_hotkeys(hotkeys)" in init_body
    assert "detect_war_thunder_integrity" not in init_body
    assert "ElevatedHotkeyBrokerClient(" not in init_body
    assert "ElevatedHotkeyBrokerClient(" in elevate_body
    assert 'self._hotkey_broker_action == "elevate"' in action_body
    assert "messagebox.askokcancel" in action_body
    assert "未知" in action_body
    assert "不会安装额外程序" in action_body


def test_production_hotkey_client_contains_no_game_process_probe() -> None:
    source = read_source("bomana/utils/hotkey_broker.py")
    forbidden = (
        "detect_war_thunder_integrity",
        "EnumWindows",
        "GetWindowTextW",
        "QueryFullProcessImageNameW",
        "PROCESS_QUERY_LIMITED_INFORMATION",
        "WAR_THUNDER_EXECUTABLES",
        "WAR_THUNDER_WINDOW_TITLE",
        "aces.exe",
        "aces64.exe",
        "aces_be.exe",
        "CreateToolhelp32Snapshot",
        "Process32First",
        "Process32Next",
        "Module32First",
        "ReadProcessMemory",
        "WriteProcessMemory",
    )
    assert not [token for token in forbidden if token in source]


def test_only_fixed_bundled_hash_locked_broker_path_crosses_uac() -> None:
    source = read_source("bomana/utils/hotkey_broker.py")
    request_body = function_source(source, "_request_runas")
    path_body = function_source(source, "bundled_broker_path")

    assert 'BROKER_EXECUTABLE_NAME = "BomanaHotkeyBroker.exe"' in source
    assert 'BROKER_BIN_DIRECTORY = "bin"' in source
    assert "os.environ" not in path_body
    assert 'info.lpVerb = "runas"' in request_body
    assert "info.lpFile = str(path)" in request_body
    assert "subprocess.list2cmdline" in request_body
    assert "verify_bundled_broker" in source
    assert "sha256_file" in source
    assert "_lock_broker_file" in source
    assert "FILE_SHARE_READ" in source
    assert "FILE_SHARE_WRITE" not in source
    assert "FILE_SHARE_DELETE" not in source


def test_broker_ipc_is_acl_restricted_and_fixed_frame_only() -> None:
    source = read_source("bomana/utils/hotkey_broker.py")

    assert 'sddl = f"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;{sid})"' in source
    assert "PIPE_REJECT_REMOTE_CLIENTS" in source
    assert "FILE_FLAG_FIRST_PIPE_INSTANCE" in source
    assert "FRAME_SIZE = 8" in source
    assert 'FRAME_MAGIC = b"BHK1"' in source
    assert "ACTION_IDS" in source
    assert "decode_frame" in source
    assert "secrets.token_hex(16)" in source
    assert "--command" not in source
    assert "--path" not in source


def test_native_broker_has_only_allowlisted_hotkey_surface() -> None:
    broker_source = read_source("native/hotkey_broker/src/main.rs")

    required = (
        "RegisterHotKey",
        "UnregisterHotKey",
        "MOD_NOREPEAT",
        "GetNamedPipeServerProcessId",
        "MsgWaitForMultipleObjects",
        "ProcessIdToSessionId",
        "reset",
        "lock",
        "corner",
        "beep",
        "zones",
        "bomb_target",
    )
    assert not [token for token in required if token not in broker_source]
    forbidden = (
        "SetWindowsHookEx",
        "WH_KEYBOARD_LL",
        "GetAsyncKeyState",
        "GetKeyState",
        "RegisterRawInputDevices",
        "CreateToolhelp32Snapshot",
        "Process32First",
        "Process32Next",
        "LoadLibrary",
        "Command::new",
        "TcpStream",
        "UdpSocket",
        "std::fs",
        "aces.exe",
        "aces_BE.exe",
        "EasyAntiCheat",
    )
    assert not [token for token in forbidden if token in broker_source]


def test_broker_exits_with_app_or_stop_event_and_never_persists() -> None:
    broker_source = read_source("native/hotkey_broker/src/main.rs")
    client_source = read_source("bomana/utils/hotkey_broker.py")
    combined = f"{broker_source}\n{client_source}"

    assert "OpenProcess" in broker_source
    assert "OpenEventW" in broker_source
    assert "SetEvent" in client_source
    assert "DisconnectNamedPipe" in client_source
    forbidden = (
        "CreateService",
        "OpenSCManager",
        "schtasks",
        "TaskScheduler",
        "RunOnce",
        "CurrentVersion\\Run",
    )
    assert not [token for token in forbidden if token in combined]


def test_no_elevated_path_runs_mutable_python_app_code() -> None:
    launcher_source = read_source("launcher.pyw")
    bootstrap_source = read_source("launcher/bootstrap.py")
    broker_client_source = read_source("bomana/utils/hotkey_broker.py")

    assert "runpy.run_path" in bootstrap_source
    assert "ShellExecuteExW" not in bootstrap_source
    assert "runpy" not in broker_client_source
    assert "Bomana.pyw" not in broker_client_source
    assert "launcher.bootstrap" not in broker_client_source
    assert "--bomana-elevated-app" not in launcher_source
    assert not (ROOT / "launcher" / "elevation.py").exists()


def test_release_packages_zero_install_broker_without_setup_or_authenticode() -> None:
    source = read_source("tools/build_hotkey_broker.py")
    portable_source = read_source("tools/build_portable.py")
    workflow = read_source(".github/workflows/build.yml")

    assert "tools/build_hotkey_broker.py" in workflow
    assert "{APP_DIR}/bin/{HOTKEY_BROKER_NAME}" in portable_source
    assert "HOTKEY_BROKER_CHECKSUM_NAME" in portable_source
    combined = f"{source}\n{portable_source}\n{workflow}"
    for forbidden in (
        "BomanaHotkeyBrokerSetup.exe",
        "hotkey_broker_setup",
        "BOMANA_AUTHENTICODE_PFX_B64",
        "BOMANA_AUTHENTICODE_PFX_PASSWORD",
        "signtool",
    ):
        assert forbidden not in combined
    assert not (ROOT / "native" / "hotkey_broker_setup" / "Cargo.toml").exists()
