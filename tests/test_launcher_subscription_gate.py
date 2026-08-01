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


def test_public_channels_bypass_subscription_authority() -> None:
    window = window_with(None, channel="Standard")

    decision = window._require_subscription_access()

    assert decision.allowed
    assert decision.reason is SubscriptionAccessReason.ALLOWED


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
