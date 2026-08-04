"""Pure managed-runtime handoff and single-host coordination primitives.

This module intentionally models only the Launcher/App boundary.  It does not
start a process, open a browser, inspect a receipt, or persist host state.
Production process locking and UI presentation remain adapters around these
deterministic rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from typing import Any

from launcher.launch_contract import CapabilityEnvelope


class WebLaunchMode(StrEnum):
    """A released application-owned web surface selected by the Launcher."""

    NONE = "none"
    OVERLAY = "overlay"
    STANDALONE = "standalone"


class RuntimeHostExit(StrEnum):
    """The bounded result of a managed App lifetime in the shared host."""

    NORMAL = "normal"
    APPLICATION_ERROR = "application_error"


class RuntimeHostBusyError(RuntimeError):
    """Raised when maintenance is attempted while a managed App owns the host."""


@dataclass(frozen=True)
class LauncherRuntimeIdentity:
    """The non-secret Launcher and shared-runtime compatibility identity."""

    launcher_version: str
    runtime_contract_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.launcher_version, str) or not self.launcher_version.strip():
            raise ValueError("launcher_version must be a non-empty string")
        if (
            not isinstance(self.runtime_contract_version, int)
            or isinstance(self.runtime_contract_version, bool)
            or self.runtime_contract_version < 1
        ):
            raise ValueError("runtime_contract_version must be a positive integer")


@dataclass(frozen=True)
class VerifiedTerrain:
    """Terrain availability supplied only after the terrain adapter verifies it."""

    complete: bool
    location: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.complete, bool):
            raise ValueError("terrain completion must be a boolean")
        if self.location is not None and (
            not isinstance(self.location, str) or not self.location.strip()
        ):
            raise ValueError("terrain location must be a non-empty string when present")
        if not self.complete and self.location is not None:
            raise ValueError("incomplete terrain cannot expose a location")


@dataclass(frozen=True)
class RuntimeHandoff:
    """The complete, non-secret Launcher-to-App context contract.

    Its fields are deliberately closed to the values an App needs at host
    handoff: channel, Launcher/runtime identity, verified terrain, and a
    capability-gated selected web mode.  The App reads its own signed
    capability metadata; this context never transports it.
    """

    channel: str
    identity: LauncherRuntimeIdentity
    terrain: VerifiedTerrain
    web_mode: WebLaunchMode

    def __post_init__(self) -> None:
        if not isinstance(self.channel, str) or not self.channel.strip():
            raise ValueError("channel must be a non-empty string")
        if not isinstance(self.web_mode, WebLaunchMode):
            raise ValueError("web_mode must be a WebLaunchMode")

    @property
    def launcher_version(self) -> str:
        """Compatibility accessor for adapters that receive a handoff."""

        return self.identity.launcher_version

    @property
    def runtime_contract_version(self) -> int:
        """Compatibility accessor for adapters that receive a handoff."""

        return self.identity.runtime_contract_version

    @property
    def terrain_complete(self) -> bool:
        """Compatibility accessor for adapters that receive a handoff."""

        return self.terrain.complete

    @property
    def terrain_path(self) -> str | None:
        """Compatibility accessor for adapters that receive a handoff."""

        return self.terrain.location


@dataclass(frozen=True)
class RuntimeHostOutcome:
    """A concise terminal host state, without reopening the Launcher UI."""

    exit: RuntimeHostExit
    user_message: str
    reopen_launcher: bool = False

    @classmethod
    def normal_exit(cls) -> RuntimeHostOutcome:
        return cls(
            exit=RuntimeHostExit.NORMAL,
            user_message="应用已正常退出。",
        )

    @classmethod
    def application_error(cls) -> RuntimeHostOutcome:
        return cls(
            exit=RuntimeHostExit.APPLICATION_ERROR,
            user_message="应用运行时发生错误；请在下次启动时查看诊断信息。",
        )


@dataclass(frozen=True)
class RuntimeHostLease:
    """Opaque ownership token returned by :class:`RuntimeHostGate`."""

    _token: object = field(repr=False, compare=False)


@dataclass
class RuntimeHostGate:
    """In-memory single-host gate for managed App starts and maintenance.

    The gate is intentionally injectable so a future OS-level singleton adapter
    can preserve the same behavior.  A held lease blocks a second managed App
    start as well as release checks and authorization refreshes.
    """

    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _active_token: object | None = field(default=None, init=False, repr=False)
    _active_channel: str | None = field(default=None, init=False)

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._active_token is not None

    @property
    def active_channel(self) -> str | None:
        with self._lock:
            return self._active_channel

    def try_acquire(self) -> RuntimeHostLease | None:
        """Acquire the managed host, or return ``None`` when it is already busy."""

        with self._lock:
            if self._active_token is not None:
                return None
            token = object()
            self._active_token = token
            self._active_channel = None
            return RuntimeHostLease(token)

    def bind_channel(self, lease: RuntimeHostLease, channel: str) -> None:
        """Record the running channel only for the current lease owner."""

        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("channel must be a non-empty string")
        with self._lock:
            self._require_owner(lease)
            self._active_channel = channel

    def release(self, lease: RuntimeHostLease) -> None:
        """Release the host only when the original owner finishes."""

        with self._lock:
            self._require_owner(lease)
            self._active_token = None
            self._active_channel = None

    def require_idle(self, operation: str) -> None:
        """Fail closed before an update or authorization operation reaches adapters."""

        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must be a non-empty string")
        if self.is_active:
            raise RuntimeHostBusyError(f"a managed application is running; {operation} is deferred")

    def _require_owner(self, lease: RuntimeHostLease) -> None:
        if not isinstance(lease, RuntimeHostLease) or lease._token is not self._active_token:
            raise RuntimeHostBusyError("runtime host lease is not active")


def released_web_modes(
    capabilities: CapabilityEnvelope | Mapping[str, Any],
) -> tuple[WebLaunchMode, ...]:
    """Return only explicitly released and recognized web surfaces.

    The caller supplies capability metadata only after its signed App manifest
    has been verified.  Values not exactly ``True`` and unknown keys fail
    closed, which makes legacy metadata and unreleased standalone web invisible.
    """

    known = _known_capabilities(capabilities)
    modes: list[WebLaunchMode] = []
    if known.get("web_overlay") is True:
        modes.append(WebLaunchMode.OVERLAY)
    if known.get("web_standalone") is True:
        modes.append(WebLaunchMode.STANDALONE)
    return tuple(modes)


def select_web_mode(
    capabilities: CapabilityEnvelope | Mapping[str, Any],
    requested_mode: WebLaunchMode | str | None,
) -> WebLaunchMode:
    """Return a released requested mode, otherwise the safe ``none`` fallback."""

    try:
        requested = WebLaunchMode(requested_mode or WebLaunchMode.NONE)
    except ValueError:
        return WebLaunchMode.NONE
    if requested is WebLaunchMode.NONE:
        return requested
    if requested in released_web_modes(capabilities):
        return requested
    return WebLaunchMode.NONE


def build_runtime_handoff(
    *,
    channel: str,
    launcher_version: str,
    runtime_contract_version: int,
    terrain_complete: bool,
    terrain_location: str | None,
    capabilities: CapabilityEnvelope | Mapping[str, Any],
    requested_web_mode: WebLaunchMode | str | None,
) -> RuntimeHandoff:
    """Build the closed handoff after capability and terrain projection."""

    terrain = VerifiedTerrain(
        complete=terrain_complete,
        location=terrain_location if terrain_complete else None,
    )
    return RuntimeHandoff(
        channel=channel,
        identity=LauncherRuntimeIdentity(
            launcher_version=launcher_version,
            runtime_contract_version=runtime_contract_version,
        ),
        terrain=terrain,
        web_mode=select_web_mode(capabilities, requested_web_mode),
    )


def _known_capabilities(
    capabilities: CapabilityEnvelope | Mapping[str, Any],
) -> Mapping[str, Any]:
    if isinstance(capabilities, CapabilityEnvelope):
        return capabilities.known()
    return capabilities


__all__ = [
    "LauncherRuntimeIdentity",
    "RuntimeHandoff",
    "RuntimeHostBusyError",
    "RuntimeHostExit",
    "RuntimeHostGate",
    "RuntimeHostLease",
    "RuntimeHostOutcome",
    "VerifiedTerrain",
    "WebLaunchMode",
    "build_runtime_handoff",
    "released_web_modes",
    "select_web_mode",
]
