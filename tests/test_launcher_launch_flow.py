from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


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
    window.decision = launcher.LaunchDecision(action="exit", final_version="8.0.0")
    return launcher, window


def test_launcher_exposes_official_paid_preview_action() -> None:
    launcher = load_launcher_module()

    assert launcher.OFFICIAL_SITE_URL == "https://bomana.ruikang.wang/"
    assert 'text="官网预览"' in Path("launcher.pyw").read_text(encoding="utf-8")
    assert "command=self._open_official_site" in Path("launcher.pyw").read_text(encoding="utf-8")


def test_default_launch_keeps_python_app_at_ordinary_integrity(tmp_path: Path) -> None:
    _launcher, window = make_window(tmp_path)
    window._local_app_launch_version = lambda: "8.0.0"

    window._on_launch()

    assert window.decision.action == "launch"
    assert window.decision.final_version == "8.0.0"
    assert window.status_calls[-1][0] == "准备启动"
    assert "普通权限" in window.status_calls[-1][1]
    assert [delay for delay, _callback in window.root.after_calls] == [300]


def test_launcher_shortcut_only_activates_enabled_launch_button(tmp_path: Path) -> None:
    _launcher, window = make_window(tmp_path)
    launches: list[str] = []
    window._on_launch = lambda: launches.append("launch")

    window.launch_btn = type("Button", (), {"cget": lambda _self, _key: "disabled"})()
    assert window._on_launch_shortcut() == "break"
    assert launches == []

    window.launch_btn = type("Button", (), {"cget": lambda _self, _key: "normal"})()
    assert window._on_launch_shortcut() == "break"
    assert launches == ["launch"]


def test_launcher_main_runs_only_ordinary_launch_decision(monkeypatch, tmp_path: Path) -> None:
    launcher = load_launcher_module()
    launched: list[tuple[Path, str]] = []
    reported: list[str] = []
    recovery_warnings: list[str] = []
    pending_recovery_warnings: list[str] = []

    class FakeWindow:
        channel = "Lite"
        source_test_mode = True

        def __init__(
            self,
            _base: Path,
            _channel: str,
            recovery_warning: str = "",
        ) -> None:
            recovery_warnings.append(recovery_warning)

        def run(self):
            return launcher.LaunchDecision(action="launch", final_version="8.0.0")

    class ImmediateThread:
        def __init__(self, *, target, args, daemon) -> None:
            assert daemon is True
            self.target = target
            self.args = args

        def start(self) -> None:
            reported.append("report")

    monkeypatch.setattr(launcher, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(
        launcher,
        "_recover_incomplete_install",
        lambda _base: "安装恢复失败：恢复备份应用版本格式无效",
    )
    monkeypatch.setattr(
        launcher,
        "_set_pending_recovery_warning",
        lambda warning: pending_recovery_warnings.append(warning),
    )
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
    assert recovery_warnings == ["安装恢复失败：恢复备份应用版本格式无效"]
    assert pending_recovery_warnings == ["安装恢复失败：恢复备份应用版本格式无效"]


def _write_app_package(base: Path, version: str, entry_source: str = "") -> Path:
    app_dir = base / "app"
    config_dir = app_dir / "bomana" / "config"
    config_dir.mkdir(parents=True)
    (app_dir / "Bomana.pyw").write_text(entry_source or "pass\n", encoding="utf-8")
    (app_dir / "bomana_version.py").write_text(
        "# shared compatibility boundary\n",
        encoding="utf-8",
    )
    (config_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "bomana" / "metadata.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    return app_dir


def test_recovery_rejection_is_returned_for_launcher_user_warning(
    monkeypatch,
    tmp_path: Path,
) -> None:
    launcher = load_launcher_module()
    _write_app_package(tmp_path, "8.0.0")
    backup_metadata = tmp_path / launcher.APP_BACKUP_DIR_NAME / "bomana" / "metadata.py"
    backup_metadata.parent.mkdir(parents=True)
    backup_metadata.write_text('__version__ = "malformed"\n', encoding="utf-8")
    logs: list[str] = []
    monkeypatch.setattr(launcher, "_log", lambda _base, message: logs.append(message))

    warning = launcher._recover_incomplete_install(tmp_path)

    assert warning == "安装恢复失败：恢复备份应用版本格式无效"
    assert logs == [warning]
    assert launcher.install_txn.read_local_app_version(tmp_path / launcher.APP_DIR_NAME) == "8.0.0"
    assert backup_metadata.exists()


def test_recovery_warning_is_composed_into_visible_launcher_detail() -> None:
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.recovery_warning = "恢复暂存应用版本过旧：v7.9.0，要求 >= v8.0.0"

    detail = window._with_recovery_warning("有效的本地 App 仍可启动。")

    assert detail == (
        "安装恢复已安全停止：恢复暂存应用版本过旧：v7.9.0，要求 >= v8.0.0\n"
        "有效的本地 App 仍可启动。"
    )


def test_final_handoff_surfaces_only_a_new_recovery_warning() -> None:
    launcher = load_launcher_module()
    warnings: list[str] = []
    surface_warning = launcher._launcher_bootstrap.surface_new_recovery_warning

    surface_warning("", "", lambda warning: warnings.append(warning) or True)
    surface_warning("already visible", "already visible", lambda warning: False)
    surface_warning(
        "new rejection", "already visible", lambda warning: warnings.append(warning) or True
    )

    assert warnings == ["new rejection"]


def test_final_handoff_fails_closed_if_new_warning_cannot_be_shown(tmp_path: Path) -> None:
    launcher = load_launcher_module()
    runtime_lookups: list[Path] = []

    with pytest.raises(launcher.VersionCompatibilityError, match="new rejection"):
        launcher._launcher_bootstrap.launch_app(
            tmp_path,
            "Enhanced",
            recover_incomplete_install=lambda _base: "new rejection",
            app_runtime_dir=lambda base: runtime_lookups.append(base) or base / "app",
            is_local_app_ready=lambda _base: True,
            is_source_test_run=lambda _base: False,
            read_app_version=lambda _app_dir: "8.0.0",
            default_entrypoint="Bomana.pyw",
            web_dashboard_autostart=True,
            web_dashboard_auto_open=False,
            web_dashboard_lan_enabled=False,
            displayed_recovery_warning="already visible",
            recovery_warning_callback=lambda _warning: False,
        )

    assert runtime_lookups == []


def test_launcher_handoff_passes_initial_recovery_warning_in_memory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    launcher = load_launcher_module()
    captured: dict[str, object] = {}
    launcher._set_pending_recovery_warning("initial visible warning")
    monkeypatch.setattr(
        launcher._launcher_bootstrap,
        "launch_app",
        lambda *args, **kwargs: captured.update({"args": args, "kwargs": kwargs}),
    )
    (tmp_path / launcher.APP_DIR_NAME / "bomana" / "data" / "terrain-v1").mkdir(parents=True)

    launcher._launch_app(tmp_path, "Enhanced")

    assert captured["args"] == (tmp_path, "Enhanced")
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["displayed_recovery_warning"] == "initial visible warning"
    assert kwargs["recovery_warning_callback"] is launcher._show_handoff_recovery_warning


def test_installed_launch_rejects_below_floor_before_decision(tmp_path: Path) -> None:
    _launcher, window = make_window(tmp_path)
    window.source_test_mode = False
    _write_app_package(tmp_path, "7.99.99")

    assert window._local_app_launch_version() is None
    assert window.status_calls[-1][0] == "无法启动"
    assert "过旧" in window.status_calls[-1][1]
    assert window.decision.action == "exit"


def test_launcher_state_web_preferences_require_real_booleans() -> None:
    launcher = load_launcher_module()

    assert launcher._strict_saved_bool({}, "web_dashboard_autostart", True) is True
    assert launcher._strict_saved_bool({}, "web_dashboard_auto_open", False) is False
    assert launcher._strict_saved_bool({}, "web_dashboard_lan_enabled", False) is False
    assert launcher._strict_saved_bool({"value": False}, "value", True) is False
    assert launcher._strict_saved_bool({"value": "false"}, "value", True) is True
    assert launcher._strict_saved_bool({"value": 0}, "value", True) is True


def test_launcher_state_save_migrates_to_exact_three_web_preferences(tmp_path: Path) -> None:
    launcher, window = make_window(tmp_path)
    window.use_system_proxy = False
    window.download_source_mode = "primary"
    window.web_dashboard_autostart = False
    window.web_dashboard_auto_open = True
    window.web_dashboard_lan_enabled = True
    launcher._write_state(
        tmp_path,
        {
            "web_dashboard_autostart": "false",
            "web_dashboard_host": "192.168.1.7",
            "web_dashboard_lan_control": True,
            "preserved_non_web_value": "keep",
        },
    )

    window._save_launcher_state(extra={"web_dashboard_session": "stale"})

    state = launcher._read_state(tmp_path)
    assert {key for key in state if key.startswith("web_dashboard_")} == {
        "web_dashboard_autostart",
        "web_dashboard_auto_open",
        "web_dashboard_lan_enabled",
    }
    assert state["web_dashboard_autostart"] is False
    assert state["web_dashboard_auto_open"] is True
    assert state["web_dashboard_lan_enabled"] is True
    assert state["preserved_non_web_value"] == "keep"


def test_bootstrap_handoff_uses_launcher_identity_and_in_memory_web_preferences(
    tmp_path: Path,
) -> None:
    launcher = load_launcher_module()
    result_path = tmp_path / "handoff.json"
    entry = (
        "import json, os\n"
        "from pathlib import Path\n"
        f"Path({str(result_path)!r}).write_text(json.dumps({{\n"
        "    'boundary': __import__('bomana_version').BOUNDARY_SOURCE,\n"
        "    'launcher': os.environ.get('BOMANA_LAUNCHER_VERSION'),\n"
        "    'autostart': os.environ.get('BOMANA_WEB_DASHBOARD_AUTOSTART'),\n"
        "    'auto_open': os.environ.get('BOMANA_WEB_DASHBOARD_AUTO_OPEN'),\n"
        "    'lan_enabled': os.environ.get('BOMANA_WEB_DASHBOARD_LAN_ENABLED'),\n"
        "}), encoding='utf-8')\n"
    )
    app_dir = _write_app_package(tmp_path, "8.0.0", entry)
    (app_dir / "bomana" / "data" / "terrain-v1").mkdir(parents=True)
    (app_dir / "bomana_version.py").write_text(
        'BOUNDARY_SOURCE = "installed"\n',
        encoding="utf-8",
    )

    class FrozenBoundaryLoader:
        def create_module(self, _spec):
            return None

        def exec_module(self, module) -> None:
            module.BOUNDARY_SOURCE = "frozen"

    class FrozenBoundaryFinder:
        def find_spec(self, fullname, _path=None, _target=None):
            if fullname == "bomana_version":
                return importlib.machinery.ModuleSpec(fullname, FrozenBoundaryLoader())
            return None

    frozen_finder = FrozenBoundaryFinder()
    launcher._set_pending_web_preferences(True, True, True)
    old_cwd = Path.cwd()
    old_path = list(sys.path)
    old_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "bomana_version" or name == "bomana" or name.startswith("bomana.")
    }
    previous = {
        name: os.environ.get(name)
        for name in (
            "BOMANA_LAUNCHER_VERSION",
            "BOMANA_WEB_DASHBOARD_AUTOSTART",
            "BOMANA_WEB_DASHBOARD_AUTO_OPEN",
            "BOMANA_WEB_DASHBOARD_LAN_ENABLED",
        )
    }
    sys.meta_path.insert(0, frozen_finder)
    try:
        launcher._launch_app(tmp_path, "Enhanced")
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_path
        if frozen_finder in sys.meta_path:
            sys.meta_path.remove(frozen_finder)
        for name in tuple(sys.modules):
            if name == "bomana_version" or name == "bomana" or name.startswith("bomana."):
                sys.modules.pop(name, None)
        sys.modules.update(old_modules)

    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "boundary": "installed",
        "launcher": "3.4.0",
        "autostart": "1",
        "auto_open": "1",
        "lan_enabled": "1",
    }
    for name, old_value in previous.items():
        assert os.environ.get(name) == old_value


def test_launcher_web_preferences_keep_lan_and_autostart_coherent() -> None:
    launcher = load_launcher_module()

    launcher._set_pending_web_preferences(False, False, True)
    assert launcher._PENDING_WEB_DASHBOARD_AUTOSTART is True
    assert launcher._PENDING_WEB_DASHBOARD_LAN_ENABLED is True

    launcher._set_pending_web_preferences(False, True, False)
    assert launcher._PENDING_WEB_DASHBOARD_AUTOSTART is False
    assert launcher._PENDING_WEB_DASHBOARD_LAN_ENABLED is False


@pytest.mark.parametrize("channel", ["Standard", "Lite"])
def test_non_enhanced_channels_force_off_web_preferences(channel: str) -> None:
    launcher = load_launcher_module()

    autostart, auto_open, lan, degraded = launcher._effective_web_preferences_for_channel(
        channel,
        True,
        True,
        True,
    )
    assert (autostart, auto_open, lan) == (False, False, False)
    assert degraded is True
    assert "网页驾驶舱" in launcher._web_cockpit_degradation_message(channel)
    assert channel in launcher._web_cockpit_degradation_message(channel)


def test_enhanced_channel_keeps_web_preferences() -> None:
    launcher = load_launcher_module()

    autostart, auto_open, lan, degraded = launcher._effective_web_preferences_for_channel(
        "Enhanced",
        True,
        False,
        True,
    )
    assert (autostart, auto_open, lan) == (True, False, True)
    assert degraded is False


def test_commit_launch_degrades_web_prefs_for_standard_channel(tmp_path: Path) -> None:
    launcher, window = make_window(tmp_path)
    warnings: list[str] = []
    destroyed: list[bool] = []
    window.channel = "Standard"
    window.web_dashboard_autostart = True
    window.web_dashboard_auto_open = True
    window.web_dashboard_lan_enabled = False
    window.decision = launcher.LaunchDecision(action="launch", final_version="8.0.0")
    window.root.destroy = lambda: destroyed.append(True)
    # make_window stubs _commit_launch; restore the real implementation for this case.
    window._commit_launch = launcher.LauncherWindow._commit_launch.__get__(
        window, launcher.LauncherWindow
    )

    def capture_warning(*_args, **_kwargs):
        if len(_args) > 1:
            warnings.append(str(_args[1]))
        elif "message" in _kwargs:
            warnings.append(str(_kwargs["message"]))

    original = launcher.messagebox.showwarning
    launcher.messagebox.showwarning = capture_warning
    try:
        window._commit_launch()
    finally:
        launcher.messagebox.showwarning = original

    assert destroyed == [True]
    assert warnings and "Standard" in warnings[0]
    assert launcher._PENDING_WEB_DASHBOARD_AUTOSTART is False
    assert launcher._PENDING_WEB_DASHBOARD_AUTO_OPEN is False
    assert launcher._PENDING_WEB_DASHBOARD_LAN_ENABLED is False
