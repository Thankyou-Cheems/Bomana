from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path


def load_launcher_module():
    module_name = "launcher_launch_flow_under_test"
    if module_name in sys.modules:
        return sys.modules[module_name]
    loader = importlib.machinery.SourceFileLoader(module_name, "launcher.pyw")
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []

    def after(self, delay: int, callback) -> str:
        self.after_calls.append((delay, callback))
        return "after-id"


def make_window(tmp_path: Path):
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.base = tmp_path
    window.channel = "Enhanced"
    window.source_test_mode = True
    window.root = FakeRoot()
    window.status_calls = []
    window._set_status = lambda *args: window.status_calls.append(args)
    window._commit_launch = lambda: None
    window.decision = launcher.LaunchDecision(action="exit", final_version="7.0.0")
    return launcher, window


def test_default_launch_keeps_python_app_at_ordinary_integrity(tmp_path: Path) -> None:
    _launcher, window = make_window(tmp_path)
    window._local_app_launch_version = lambda: "7.0.0"

    window._on_launch()

    assert window.decision.action == "launch"
    assert window.decision.final_version == "7.0.0"
    assert window.status_calls[-1][0] == "准备启动"
    assert "普通权限" in window.status_calls[-1][1]
    assert [delay for delay, _callback in window.root.after_calls] == [300]


def test_launcher_main_runs_only_ordinary_launch_decision(monkeypatch, tmp_path: Path) -> None:
    launcher = load_launcher_module()
    launched: list[tuple[Path, str]] = []
    reported: list[str] = []

    class FakeWindow:
        channel = "Lite"
        source_test_mode = True

        def __init__(self, _base: Path, _channel: str) -> None:
            pass

        def run(self):
            return launcher.LaunchDecision(action="launch", final_version="7.0.0")

    class ImmediateThread:
        def __init__(self, *, target, args, daemon) -> None:
            assert daemon is True
            self.target = target
            self.args = args

        def start(self) -> None:
            reported.append("report")

    monkeypatch.setattr(launcher, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_recover_incomplete_install", lambda _base: None)
    monkeypatch.setattr(launcher, "_cleanup_temp_files_on_launcher_upgrade", lambda _base: None)
    monkeypatch.setattr(launcher, "_cleanup_stale_launcher_self_update_temp", lambda _base: None)
    monkeypatch.setattr(launcher, "_cleanup_legacy_launcher_self_update_files", lambda _base: None)
    monkeypatch.setattr(launcher, "_consume_launcher_update_result", lambda _base: None)
    monkeypatch.setattr(launcher.Win32, "enable_dpi", lambda: None)
    monkeypatch.setattr(launcher, "_detect_channel", lambda: "Enhanced")
    monkeypatch.setattr(launcher, "_build_client_identity", lambda _base: object())
    monkeypatch.setattr(launcher, "LauncherWindow", FakeWindow)
    monkeypatch.setattr(launcher.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        launcher,
        "_launch_app",
        lambda base, channel: launched.append((base, channel)),
    )

    launcher.main()

    assert launched == [(tmp_path, "Lite")]
    assert reported == ["report"]
