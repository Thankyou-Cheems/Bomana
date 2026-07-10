from __future__ import annotations

import ast
from pathlib import Path

# enforces: docs/specs/threading-ui-contract.md THREAD-02..THREAD-06, THREAD-08, THREAD-09, HOTKEY-01, HOTKEY-02, HOTKEY-04

ROOT = Path(__file__).resolve().parents[2]
TK_MUTATORS = (
    ".attributes(",
    ".config(",
    ".configure(",
    ".destroy(",
    ".geometry(",
    ".grid(",
    ".pack(",
    ".place(",
    ".title(",
    ".winfo_",
)


def read_source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def nested_functions_in_method(source: str, method_name: str) -> list[ast.FunctionDef]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            return [child for child in ast.walk(node) if isinstance(child, ast.FunctionDef)]
    raise AssertionError(f"method not found: {method_name}")


def method_source(source: str, class_name: str, method_name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return ast.get_source_segment(source, child) or ""
    raise AssertionError(f"method not found: {class_name}.{method_name}")


def test_tk_event_dispatcher_post_only_queues_callbacks() -> None:
    source = read_source("bomana/ui/runtime.py")
    post_body = method_source(source, "TkEventDispatcher", "post")
    schedule_body = method_source(source, "TkEventDispatcher", "_schedule")

    assert "class TkEventDispatcher" in source
    assert "self._pending.put((callback, args))" in post_body
    assert ".after(" not in post_body
    assert "self.root.after(self._poll_interval_ms, self._drain)" in schedule_body


def test_tray_callbacks_dispatch_back_to_tk_thread() -> None:
    source = read_source("bomana/ui/runtime_services.py")
    callback_names = {
        function.name
        for function in nested_functions_in_method(source, "init_tray")
        if function.name.startswith(("do_", "toggle_"))
    }

    assert callback_names
    for callback_name in callback_names:
        start = source.index(f"def {callback_name}")
        next_def = source.find("\n        def ", start + 1)
        body = source[start : next_def if next_def != -1 else len(source)]
        assert "app.dispatcher.post(" in body, callback_name
    assert 'start_daemon_thread("BomanaTray", self.tray.run)' in source


def test_global_hotkeys_use_tk_owned_message_window() -> None:
    source = read_source("bomana/utils/system.py")
    hotkey_source = source[source.index("class GlobalHotkeys") :]
    start_body = method_source(source, "GlobalHotkeys", "start")
    create_body = method_source(source, "GlobalHotkeys", "_create_message_window")
    dispatch_body = method_source(source, "GlobalHotkeys", "_dispatch_hotkey")
    runtime_source = read_source("bomana/ui/runtime_services.py")

    assert "class GlobalHotkeys" in source
    assert "RegisterHotKey" in start_body
    assert "CreateWindowExW" in create_body
    assert "HWND_MESSAGE" in create_body
    assert "self.dispatch(" in dispatch_body
    assert "self._deliver_hotkey" in dispatch_body
    assert "global_hotkey_received" in hotkey_source
    assert "self.app.dispatcher.post" in runtime_source
    assert "GetMessageW" not in hotkey_source
    assert "PostThreadMessageW" not in hotkey_source
    assert "self.root.after" not in hotkey_source
    assert "threading.Thread" not in hotkey_source


def test_privileged_broker_reader_dispatches_before_app_callbacks() -> None:
    source = read_source("bomana/utils/hotkey_broker.py")
    read_body = method_source(source, "ElevatedHotkeyBrokerClient", "_read_frames")
    dispatch_body = method_source(source, "ElevatedHotkeyBrokerClient", "_dispatch_frame")
    deliver_body = method_source(source, "ElevatedHotkeyBrokerClient", "_deliver_action")

    assert 'name="BomanaHotkeyBrokerPipe"' in source
    assert "self.dispatch(self.ready_cb, failed)" in dispatch_body
    assert "self.dispatch(self._deliver_action, binding)" in dispatch_body
    assert "binding.callback()" in deliver_body
    assert "binding.callback()" not in read_body
    assert "tk." not in read_body
    assert ".after(" not in read_body


def test_windows_hotkey_probe_stays_minimal_and_local_backend_starts_first() -> None:
    broker_source = read_source("bomana/utils/hotkey_broker.py")
    runtime_source = read_source("bomana/ui/runtime_services.py")
    init_body = method_source(runtime_source, "AppRuntimeServices", "init_global_hotkeys")

    assert init_body.index("self._start_local_hotkeys(hotkeys)") < init_body.index(
        "detect_war_thunder_integrity()"
    )
    assert "EnumWindows" in broker_source
    assert "GetWindowTextW" in broker_source
    assert "PROCESS_QUERY_LIMITED_INFORMATION" in broker_source
    assert "CreateToolhelp32Snapshot" not in broker_source
    assert "ReadProcessMemory" not in broker_source


def test_windows_hotkey_path_bans_hook_and_polling_fallbacks() -> None:
    runtime_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "bomana").rglob("*.py")
    )
    forbidden_tokens = (
        "SetWindowsHookExW",
        "WH_KEYBOARD_LL",
        "CallNextHookEx",
        "UnhookWindowsHookEx",
        "GetAsyncKeyState",
        "GetKeyState",
    )

    assert "RegisterHotKey" in runtime_source
    assert not [token for token in forbidden_tokens if token in runtime_source]


def test_logic_poller_worker_body_does_not_touch_tk_widgets() -> None:
    source = read_source("bomana/ui/runtime.py")
    tree = ast.parse(source)
    run_body = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run":
            run_body = ast.get_source_segment(source, node) or ""
            break

    assert "self.game.tick()" in run_body
    assert "tk." not in run_body
    assert not [token for token in TK_MUTATORS if token in run_body]


def test_sound_manager_has_no_tk_dependency() -> None:
    source = read_source("bomana/utils/sound.py")

    assert "import tkinter" not in source
    assert "from tkinter" not in source
    assert "queue.Queue" in source
    assert "threading.Thread" in source
    assert "self._queue.put(" in source


def test_diagnostics_uses_queue_listener_for_disk_io() -> None:
    source = read_source("bomana/utils/diagnostics.py")

    assert "logging.handlers.QueueHandler" in source
    assert "logging.handlers.QueueListener" in source
    assert "record_queue" in source
