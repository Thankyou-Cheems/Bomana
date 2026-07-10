from __future__ import annotations

import ast
from pathlib import Path

# enforces: docs/specs/startup-elevation.md ELEV-01..ELEV-10

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


def test_only_fixed_program_files_broker_path_crosses_uac() -> None:
    source = read_source("bomana/utils/hotkey_broker.py")
    request_body = function_source(source, "_request_runas")
    path_body = function_source(source, "installed_broker_path")

    assert 'BROKER_EXECUTABLE_NAME = "BomanaHotkeyBroker.exe"' in source
    assert 'Path("Bomana") / BROKER_DIRECTORY_NAME' in source
    assert "SHGetKnownFolderPath" in source
    assert "os.environ" not in path_body
    assert 'info.lpVerb = "runas"' in request_body
    assert "info.lpFile = str(path)" in request_body
    assert "subprocess.list2cmdline" in request_body
    assert "verify_authenticode(actual)" in source
    assert "WinVerifyTrust" in source


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


def test_installer_forces_protected_program_files_acl() -> None:
    setup_source = read_source("native/hotkey_broker_setup/src/main.rs")

    assert "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;BU)" in setup_source
    assert "PROTECTED_DACL_SECURITY_INFORMATION" in setup_source
    assert "SetNamedSecurityInfoW" in setup_source
    assert "apply_protected_acl(&directory)?" in setup_source
    assert "apply_protected_acl(&target)?" in setup_source


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


def test_release_tooling_refuses_unsigned_broker_artifacts() -> None:
    source = read_source("tools/build_hotkey_broker.py")
    workflow = read_source(".github/workflows/build.yml")

    assert 'PFX_B64_ENV = "BOMANA_AUTHENTICODE_PFX_B64"' in source
    assert 'PFX_PASSWORD_ENV = "BOMANA_AUTHENTICODE_PFX_PASSWORD"' in source
    assert "release_certificate_context()" in source
    assert source.count("authenticode_sign(") >= 3
    assert 'signtool, "verify", "/pa", "/all"' in source
    assert "BOMANA_AUTHENTICODE_PFX_B64" in workflow
    assert "tools/build_hotkey_broker.py" in workflow
    assert "BomanaHotkeyBrokerSetup.exe" in workflow
