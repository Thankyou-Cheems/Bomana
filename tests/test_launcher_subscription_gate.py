from __future__ import annotations

import importlib.machinery
import importlib.util
import queue
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from launcher.subscription_access import (
    SubscriptionAccessDecision,
    SubscriptionAccessReason,
)
from launcher.terrain_store import TerrainMapProgress


def load_launcher_module():
    module_name = "launcher_subscription_gate_under_test"
    if module_name in sys.modules:
        return sys.modules[module_name]
    loader = importlib.machinery.SourceFileLoader(module_name, "launcher.pyw")
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


@dataclass
class FakeWorkflow:
    cached: SubscriptionAccessDecision
    refreshed: SubscriptionAccessDecision
    refresh_count: int = 0

    def cached_access(self) -> SubscriptionAccessDecision:
        return self.cached

    def refresh_cached_receipt(self) -> SubscriptionAccessDecision:
        self.refresh_count += 1
        return self.refreshed


def window_with(workflow: FakeWorkflow | None, channel: str = "Enhanced"):
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.channel = channel
    window.source_test_mode = False
    window.subscription_workflow = workflow
    window.subscription_setup_error = "subscription unavailable"
    window.events = queue.Queue()
    return window


def test_unsubscribed_projection_hides_super_bomb_channel_and_features() -> None:
    load_launcher_module()
    window = window_with(None, channel="Standard")
    window.subscription_decision = SubscriptionAccessDecision(
        allowed=False,
        reason=SubscriptionAccessReason.MISSING_RECEIPT,
    )

    assert window._available_channel_ids() == ("Standard", "Lite")
    assert not window._super_bomb_access_allowed()
    assert not window._super_bomb_features_visible()


def test_subscribed_projection_restores_super_bomb_channel_and_features() -> None:
    load_launcher_module()
    window = window_with(None, channel="Enhanced")
    window.subscription_decision = SubscriptionAccessDecision(
        allowed=True,
        reason=SubscriptionAccessReason.ALLOWED,
    )

    assert window._available_channel_ids() == ("Enhanced", "Standard", "Lite")
    assert window._super_bomb_access_allowed()
    assert window._super_bomb_features_visible()


def test_source_test_mode_keeps_enhanced_projection_without_subscription() -> None:
    load_launcher_module()
    window = window_with(None, channel="Enhanced")
    window.source_test_mode = True
    window.subscription_decision = SubscriptionAccessDecision(
        allowed=False,
        reason=SubscriptionAccessReason.MISSING_RECEIPT,
    )

    assert window._available_channel_ids() == ("Enhanced", "Standard", "Lite")
    assert window._super_bomb_features_visible()


def test_installed_app_channel_reads_profile_without_importing_app_code(tmp_path) -> None:
    launcher = load_launcher_module()
    profile = tmp_path / "app" / "bomana" / "config" / "feature_profile.py"
    profile.parent.mkdir(parents=True)
    profile.write_text('EDITION_CHANNEL = "Enhanced"\n', encoding="utf-8")

    assert launcher._installed_app_channel(tmp_path) == "Enhanced"

    profile.write_text("EDITION_CHANNEL = 'Standard'\n", encoding="utf-8")
    assert launcher._installed_app_channel(tmp_path) == "Standard"


def test_public_channels_bypass_subscription_authority() -> None:
    window = window_with(None, channel="Standard")

    decision = window._require_subscription_access()

    assert decision.allowed
    assert decision.reason is SubscriptionAccessReason.ALLOWED


def test_subscription_store_opens_the_real_cheemspay_store(monkeypatch) -> None:
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.running = False
    opened: list[tuple[str, int]] = []
    monkeypatch.setattr(
        launcher.webbrowser,
        "open",
        lambda url, new=0: opened.append((url, new)) or True,
    )

    window._open_subscription_store()

    assert opened == [("https://pay.ruikang.wang/", 2)]


def test_enhanced_uses_cached_receipt_without_network_refresh() -> None:
    allowed = SubscriptionAccessDecision(True, SubscriptionAccessReason.ALLOWED)
    workflow = FakeWorkflow(cached=allowed, refreshed=allowed)
    window = window_with(workflow)

    decision = window._require_subscription_access()

    assert decision.allowed
    assert workflow.refresh_count == 0


def test_enhanced_refreshes_then_fails_closed_without_entitlement() -> None:
    missing = SubscriptionAccessDecision(False, SubscriptionAccessReason.MISSING_RECEIPT)
    workflow = FakeWorkflow(cached=missing, refreshed=missing)
    window = window_with(workflow)

    with pytest.raises(RuntimeError, match="尚未登录 CheemsPay"):
        window._require_subscription_access()

    assert workflow.refresh_count == 1
    event_type, payload = window.events.get_nowait()
    assert event_type == "subscription_state"
    assert payload == {"allowed": False, "reason": "missing_receipt"}


class ExplodingWorkflow:
    """Fail the test if a public UI refresh tries to read subscriber access."""

    calls = 0

    def cached_access(self) -> SubscriptionAccessDecision:
        self.calls += 1
        raise AssertionError("public UI must not read subscriber access")


class FakeWidget:
    def __init__(self) -> None:
        self.configured: dict[str, object] = {}

    def config(self, **kwargs: object) -> None:
        self.configured.update(kwargs)


class FakeStringVar:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def test_public_ui_refresh_is_static_and_never_renders_subscriber_failure_copy() -> None:
    launcher = load_launcher_module()
    workflow = ExplodingWorkflow()
    window = object.__new__(launcher.LauncherWindow)
    window.channel = "Standard"
    window.source_test_mode = False
    window.running = False
    window.subscription_workflow = workflow
    window.subscription_setup_error = "receipt protocol failed"
    window.subscription_decision = SubscriptionAccessDecision(
        allowed=False,
        reason=SubscriptionAccessReason.WRONG_DEVICE,
    )
    window.subscription_status_lbl = FakeWidget()
    window._refresh_channel_menu = lambda: False
    window._refresh_feature_visibility = lambda: None

    window._refresh_subscription_ui()

    assert workflow.calls == 0
    copy = str(window.subscription_status_lbl.configured["text"])
    assert "超级爆弹版" in copy
    assert "设备" not in copy
    assert "协议" not in copy
    assert "CheemsPay" not in copy


def test_public_ui_exposes_purchase_and_authorization_actions() -> None:
    source = Path("launcher.pyw").read_text(encoding="utf-8")

    assert "self.subscription_store_btn = tk.Button" in source
    assert 'text="购买 / 试用"' in source
    assert "self.subscription_login_btn = tk.Button" in source
    assert "command=self._begin_subscription_login" in source


def test_subscription_login_lazily_initializes_workflow_from_public_channel() -> None:
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.running = False
    window.source_test_mode = False
    window.subscription_workflow = None
    window.subscription_setup_error = ""
    window.current_task = ""
    started: list[str] = []
    initialized: list[bool] = []
    window._ensure_subscription_workflow = lambda: initialized.append(True) or True
    window._set_status = lambda *_args: None
    window._set_running = lambda running: setattr(window, "running", running)
    window._start_worker = lambda task: started.append(task)

    window._begin_subscription_login()

    assert initialized == [True]
    assert window.current_task == "subscription_login"
    assert started == ["subscription_login"]


def test_successful_subscription_event_refreshes_receipt_before_menu_projection() -> None:
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.events = queue.Queue()
    window.events.put(("subscription_done", {"ok": True, "detail": "授权成功"}))
    window.root = type("FakeRoot", (), {"after": lambda self, delay, callback: None})()
    window.current_task = "subscription_login"
    window.running = True
    window.subscription_decision = SubscriptionAccessDecision(
        allowed=False,
        reason=SubscriptionAccessReason.MISSING_RECEIPT,
    )
    calls: list[str] = []

    def refresh_cached_access() -> None:
        calls.append("refresh")
        window.subscription_decision = SubscriptionAccessDecision(
            allowed=True,
            reason=SubscriptionAccessReason.ALLOWED,
        )

    window._set_running = lambda running: setattr(window, "running", running)
    window._refresh_cached_subscription_access = refresh_cached_access
    window._refresh_subscription_ui = lambda: calls.append(
        "ui:" + str(window.subscription_decision.allowed)
    )
    window._set_status = lambda *_args: None
    window._begin_check = lambda **_kwargs: None

    window._poll_events()

    assert calls == ["refresh", "ui:True"]
    assert window.subscription_decision.allowed


def test_authorized_user_has_one_click_switch_to_super_bomb() -> None:
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.channel = "Standard"
    window.running = False
    window.source_test_mode = False
    window.subscription_decision = SubscriptionAccessDecision(
        allowed=True,
        reason=SubscriptionAccessReason.ALLOWED,
    )
    window.channel_var = FakeStringVar(launcher.CHANNEL_DISPLAY_NAMES["Standard"])
    window._channel_menu_refreshing = False
    calls: list[str] = []
    window._save_launcher_state = lambda: calls.append("save")
    window._refresh_installed_versions = lambda: calls.append("installed")
    window._refresh_local_terrain_snapshot = lambda: calls.append("terrain")
    window._refresh_subscription_ui = lambda: calls.append("subscription")
    window._refresh_feature_visibility = lambda: calls.append("features")
    window._refresh_channel_details = lambda: calls.append("details")
    window._set_status = lambda *args: calls.append(str(args[0]))
    window._begin_check = lambda *, automatic: calls.append(f"check:{automatic}")

    window._switch_to_super_bomb()

    assert window.channel == "Enhanced"
    assert window.channel_var.get() == launcher.CHANNEL_DISPLAY_NAMES["Enhanced"]
    assert calls[-2:] == ["已切换为超级爆弹版", "check:False"]


def test_terrain_progress_callbacks_keep_only_the_newest_ui_snapshot() -> None:
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.events = queue.Queue()
    window._terrain_progress_lock = threading.Lock()
    window._terrain_progress_snapshot = ()
    window._terrain_progress_event_pending = False
    first = TerrainMapProgress("map_a", True, 1, 10, False)
    latest = TerrainMapProgress("map_a", True, 10, 10, True)

    window._emit_terrain_map_progress((first,))
    window._emit_terrain_map_progress((latest,))

    assert window.events.qsize() == 1
    assert window._terrain_progress_snapshot == (latest,)


def test_pause_terrain_download_requests_resumable_background_stop() -> None:
    launcher = load_launcher_module()
    window = object.__new__(launcher.LauncherWindow)
    window.terrain_running = True
    window._terrain_cancel_requested = threading.Event()
    window._terrain_map_dialog_refresh = lambda: None
    window._render_terrain_status = lambda: None

    window._pause_terrain_download()

    assert window._terrain_cancel_requested.is_set()
    assert window.terrain_status_title == "正在暂停地图下载"


def test_public_channel_change_never_reads_subscriber_access() -> None:
    launcher = load_launcher_module()
    workflow = ExplodingWorkflow()
    window = object.__new__(launcher.LauncherWindow)
    window.channel = "Standard"
    window.channel_var = FakeStringVar(launcher.CHANNEL_DISPLAY_NAMES["Lite"])
    window.detected_channel = "Standard"
    window.source_test_mode = False
    window.running = False
    window.current_task = ""
    window.subscription_workflow = workflow
    window.subscription_setup_error = "receipt protocol failed"
    window.subscription_decision = SubscriptionAccessDecision(
        allowed=False,
        reason=SubscriptionAccessReason.WRONG_DEVICE,
    )
    window.subscription_status_lbl = FakeWidget()
    window._channel_menu_refreshing = False
    window._save_launcher_state = lambda: None
    window._refresh_installed_versions = lambda: None
    window._refresh_local_terrain_snapshot = lambda: None
    window._refresh_channel_details = lambda: None
    window._refresh_channel_menu = lambda: False
    window._refresh_feature_visibility = lambda: None
    window._set_status = lambda *_args: None
    automatic_checks: list[bool] = []
    window._begin_check = lambda *, automatic: automatic_checks.append(automatic)

    window._on_channel_changed()

    assert window.channel == "Lite"
    assert automatic_checks == [True]
    assert workflow.calls == 0


def test_public_launch_does_not_read_access_for_mismatched_local_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launcher = load_launcher_module()
    workflow = ExplodingWorkflow()
    window = object.__new__(launcher.LauncherWindow)
    window.base = tmp_path
    window.channel = "Lite"
    window.source_test_mode = False
    window.subscription_workflow = workflow
    window._local_app_launch_version = lambda: "8.7.1"
    prepared: list[str] = []
    window._prepare_ordinary_launch = lambda version: prepared.append(version)
    monkeypatch.setattr(
        launcher,
        "_installed_app_channel",
        lambda _base, _channel: "Enhanced",
    )

    window._on_launch()

    assert prepared == ["8.7.1"]
    assert workflow.calls == 0


def test_public_launcher_surface_omits_local_import_and_download_cache_actions() -> None:
    source = Path("launcher.pyw").read_text(encoding="utf-8")

    assert "self.import_btn = tk.Button" not in source
    assert "self.download_dir_btn = tk.Button" not in source
