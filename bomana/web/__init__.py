"""Bomana local/LAN Web Cockpit runtime."""

from bomana.web.server import WebDashboardRuntime
from bomana.web.snapshot import DashboardSnapshotStore

__all__ = ["DashboardSnapshotStore", "WebDashboardRuntime"]
