from __future__ import annotations

import ast
from pathlib import Path

# enforces: docs/specs/threading-ui-contract.md THREAD-02..THREAD-05

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


def test_tk_event_dispatcher_posts_with_after_zero() -> None:
    source = read_source("bomana/ui/runtime.py")

    assert "class TkEventDispatcher" in source
    assert "self.root.after(0, callback, *args)" in source


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


def test_global_hotkeys_post_callbacks_with_root_after_zero() -> None:
    source = read_source("bomana/utils/system.py")

    assert "class GlobalHotkeys" in source
    assert "self.root.after(0, lambda keys=unique_keys: self.error_cb(keys))" in source
    assert "self.root.after(0, cb)" in source


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
