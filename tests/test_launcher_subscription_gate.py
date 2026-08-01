from __future__ import annotations

import importlib.machinery
import importlib.util
import queue
import sys
from dataclasses import dataclass

import pytest

from launcher.subscription_access import (
    SubscriptionAccessDecision,
    SubscriptionAccessReason,
)


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
