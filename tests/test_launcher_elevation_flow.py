from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from launcher import elevation


def load_launcher_module():
    module_name = "launcher_elevation_flow_under_test"
    if module_name in sys.modules:
        return sys.modules[module_name]
    loader = importlib.machinery.SourceFileLoader(module_name, "launcher.pyw")
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


class FakeWidget:
    def __init__(self, manager: str = "") -> None:
        self.manager = manager
        self.options: dict[str, object] = {}
        self.pack_calls: list[dict[str, object]] = []

    def config(self, **kwargs) -> None:
        self.options.update(kwargs)

    def winfo_manager(self) -> str:
        return self.manager

    def pack(self, **kwargs) -> None:
        self.manager = "pack"
        self.pack_calls.append(kwargs)


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []
        self.update_calls = 0

    def update_idletasks(self) -> None:
        self.update_calls += 1

    def after(self, delay: int, callback) -> str:
        self.after_calls.append((delay, callback))
        return "after-id"


def make_window(tmp_path: Path):
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.base = tmp_path
    window.channel = "Enhanced"
    window.source_test_mode = True
    window._allow_unelevated_launch = False
    window._elevation_request_pending = False
    window.root = FakeRoot()
    window.launch_btn = FakeWidget("pack")
    window.elevate_btn = FakeWidget()
    window.elevation_warning_lbl = FakeWidget()
    window.progress_canvas = FakeWidget("pack")
    window._style_action_button = lambda *_args: None
    window._px = lambda value: value
    window.status_calls = []
    window._set_status = lambda *args: window.status_calls.append(args)
    window._commit_launch = lambda: None
    window.decision = launcher.LaunchDecision(action="exit", final_version="7.0.0")
    return launcher, window


def test_default_launch_requests_one_elevated_handoff(monkeypatch, tmp_path: Path) -> None:
    launcher, window = make_window(tmp_path)
    requested: list[str] = []
    window._local_app_launch_version = lambda: "7.0.0"
    window._request_elevated_launch = lambda version: requested.append(version)
    window._prepare_ordinary_launch = lambda _version: raise_unexpected_ordinary_launch()
    monkeypatch.setattr(launcher, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(launcher._launcher_elevation, "is_current_process_elevated", lambda: False)

    window._on_launch()

    assert requested == ["7.0.0"]


def raise_unexpected_ordinary_launch() -> None:
    raise AssertionError("ordinary launch was not expected")


def test_successful_handoff_does_not_run_ordinary_app(monkeypatch, tmp_path: Path) -> None:
    launcher, window = make_window(tmp_path)
    calls: list[dict[str, object]] = []

    def request(**kwargs):
        calls.append(kwargs)
        return elevation.ElevationResult(elevation.ElevationStatus.STARTED)

    monkeypatch.setattr(launcher._launcher_elevation, "request_elevated_app", request)

    window._request_elevated_launch("7.0.0")

    assert len(calls) == 1
    assert calls[0]["channel"] == "Enhanced"
    assert window.decision.action == "elevated_handoff"
    assert window.root.update_calls == 1
    assert [delay for delay, _callback in window.root.after_calls] == [100]
    assert window._allow_unelevated_launch is False


def test_uac_cancel_keeps_persistent_warning_retry_and_ordinary_launch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    launcher, window = make_window(tmp_path)
    monkeypatch.setattr(
        launcher._launcher_elevation,
        "request_elevated_app",
        lambda **_kwargs: elevation.ElevationResult(
            elevation.ElevationStatus.CANCELLED,
            error_code=elevation.ERROR_CANCELLED,
        ),
    )

    window._request_elevated_launch("7.0.0")

    assert window.decision.action == "exit"
    assert window._allow_unelevated_launch is True
    assert window.elevation_warning_lbl.winfo_manager() == "pack"
    assert window.elevate_btn.winfo_manager() == "pack"
    assert window.launch_btn.options["text"] == "普通权限启动"
    assert "F7-F11" in str(window.elevation_warning_lbl.options["text"])
    assert "8111" in str(window.elevation_warning_lbl.options["text"])
    assert window.status_calls[-1][0] == "未授予管理员权限"


def test_ordinary_launch_after_cancel_does_not_request_uac_again(
    monkeypatch,
    tmp_path: Path,
) -> None:
    launcher, window = make_window(tmp_path)
    window._allow_unelevated_launch = True
    window._local_app_launch_version = lambda: "7.0.0"
    ordinary: list[str] = []
    window._prepare_ordinary_launch = lambda version: ordinary.append(version)
    window._request_elevated_launch = lambda _version: raise_unexpected_elevation_request()
    monkeypatch.setattr(launcher, "os", SimpleNamespace(name="nt"))

    window._on_launch()

    assert ordinary == ["7.0.0"]


def raise_unexpected_elevation_request() -> None:
    raise AssertionError("elevation retry was not expected")


def test_internal_elevated_child_bypasses_launcher_ui_and_runs_fixed_app(
    monkeypatch,
    tmp_path: Path,
) -> None:
    launcher = load_launcher_module()
    launched: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        ["launcher.pyw", "--bomana-elevated-app", "--channel", "Lite"],
    )
    monkeypatch.setattr(launcher, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(launcher._launcher_elevation, "is_current_process_elevated", lambda: True)
    monkeypatch.setattr(
        launcher, "_launch_app", lambda base, channel: launched.append((base, channel))
    )
    monkeypatch.setattr(
        launcher,
        "LauncherWindow",
        lambda *_args: raise_unexpected_launcher_ui(),
    )

    launcher.main()

    assert launched == [(tmp_path, "Lite")]


def raise_unexpected_launcher_ui() -> None:
    raise AssertionError("elevated child must not open launcher UI")


def test_internal_child_rechecks_elevation_before_app_launch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    launcher = load_launcher_module()
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        ["launcher.pyw", "--bomana-elevated-app", "--channel", "Enhanced"],
    )
    monkeypatch.setattr(launcher, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(launcher._launcher_elevation, "is_current_process_elevated", lambda: False)
    monkeypatch.setattr(
        launcher,
        "_launch_app",
        lambda *_args: raise_unexpected_app_launch(),
    )
    monkeypatch.setattr(launcher, "_show_error", lambda title, text: errors.append((title, text)))

    launcher.main()

    assert len(errors) == 1
    assert "未获得管理员权限" in errors[0][1]


def raise_unexpected_app_launch() -> None:
    raise AssertionError("non-elevated internal child must not launch the app")
