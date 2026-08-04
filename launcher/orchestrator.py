"""Pure high-level Launcher orchestration seam.

The real Tk window, HTTP clients, installation transaction, terrain store,
telemetry transport, and Python runtime are adapters.  Keeping their boundary
here lets deterministic tests cover product decisions without a Windows
process, CDN, or CheemsPay session.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from launcher.launch_contract import (
    PUBLIC_CHANNELS,
    RELEASE_CHANNELS,
    RUNTIME_CONTRACT_VERSION,
    AppManifest,
    CapabilityEnvelope,
    CompatibilityState,
    DistributionEnvironment,
    DistributionTrust,
    DistributionTrustError,
    LaunchContractError,
    app_compatibility,
    parse_app_manifest,
    parse_distribution_descriptor,
    validate_descriptor_app_binding,
)
from launcher.runtime_handoff import (
    RuntimeHandoff,
    RuntimeHostGate,
    RuntimeHostOutcome,
    WebLaunchMode,
    build_runtime_handoff,
    released_web_modes,
)


class LauncherState(StrEnum):
    """The only primary user-facing Launcher states."""

    READY_TO_START = "ready_to_start"
    UPDATE_UNAVAILABLE_LOCAL_FALLBACK = "update_unavailable_local_fallback"
    DOWNLOAD_REQUIRED = "download_required"
    REPAIR_REQUIRED = "repair_required"


@dataclass(frozen=True)
class ReceiptAccess:
    """A redacted entitlement projection supplied by the receipt adapter."""

    allowed: bool


@dataclass(frozen=True)
class LocalInstallation:
    """Verified local App identity, or a legacy installation without metadata."""

    channel: str
    app: AppManifest | None
    verified: bool = True
    diagnostic: str = ""

    @property
    def capabilities(self) -> CapabilityEnvelope:
        if self.app is None:
            return CapabilityEnvelope.legacy_fallback()
        return self.app.capabilities

    @property
    def app_version(self) -> str:
        if self.app is None:
            return "legacy"
        return self.app.app_version


@dataclass(frozen=True)
class TerrainStatus:
    """A non-blocking terrain projection supplied by the terrain adapter."""

    complete: bool
    path: str | None = None


@dataclass(frozen=True)
class TelemetryEvent:
    """Bounded operational event with no receipt or artifact URLs."""

    channel: str
    app_version: str
    launcher_version: str
    state: LauncherState
    source: str | None
    terrain_complete: bool


@dataclass(frozen=True)
class ResolvedRelease:
    source: str
    app: AppManifest


@dataclass(frozen=True)
class LaunchDecision:
    """The single final, side-effect-free result of Launcher evaluation."""

    requested_channel: str
    selected_channel: str
    available_channels: tuple[str, ...]
    state: LauncherState
    can_launch: bool
    can_download: bool
    source: str | None
    compatibility: CompatibilityState
    capabilities: Mapping[str, bool]
    web_modes: tuple[WebLaunchMode, ...]
    terrain_degraded: bool
    user_message: str
    diagnostics: tuple[str, ...] = ()
    host_active: bool = False


# Keep the initial prototype name import-compatible while callers converge on
# the product-facing LaunchDecision seam.
LauncherProjection = LaunchDecision


@dataclass(frozen=True)
class LaunchResult:
    projection: LauncherProjection
    started: bool
    host_outcome: RuntimeHostOutcome | None = None


class DistributionAdapter(Protocol):
    def load_descriptor(self, source: str) -> Mapping[str, Any]: ...

    def load_manifest(self, url: str) -> Mapping[str, Any]: ...


class ReceiptAdapter(Protocol):
    def cached_access(self) -> ReceiptAccess: ...

    def refresh_access(self) -> ReceiptAccess: ...


class InstallationAdapter(Protocol):
    def inspect(self, channel: str) -> LocalInstallation | None: ...


class TerrainAdapter(Protocol):
    def inspect(self, channel: str) -> TerrainStatus: ...


class TelemetryAdapter(Protocol):
    def emit(self, event: TelemetryEvent) -> None: ...


class RuntimeAdapter(Protocol):
    def start(self, handoff: RuntimeHandoff) -> None: ...


@dataclass
class InMemoryDistributionAdapter:
    """Deterministic documents-only distribution adapter for integration tests."""

    descriptors: Mapping[str, Mapping[str, Any] | Exception]
    manifests: Mapping[str, Mapping[str, Any] | Exception]
    descriptor_calls: list[str] = field(default_factory=list)
    manifest_calls: list[str] = field(default_factory=list)

    def load_descriptor(self, source: str) -> Mapping[str, Any]:
        self.descriptor_calls.append(source)
        value = self.descriptors.get(source)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise RuntimeError(f"missing {source} distribution descriptor")
        return copy.deepcopy(dict(value))

    def load_manifest(self, url: str) -> Mapping[str, Any]:
        self.manifest_calls.append(url)
        value = self.manifests.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise RuntimeError("missing distribution manifest")
        return copy.deepcopy(dict(value))


@dataclass
class InMemoryReceiptAdapter:
    access: ReceiptAccess
    refreshed_access: ReceiptAccess | None = None
    calls: int = 0
    refresh_calls: int = 0

    def cached_access(self) -> ReceiptAccess:
        self.calls += 1
        return self.access

    def refresh_access(self) -> ReceiptAccess:
        self.refresh_calls += 1
        return self.refreshed_access or self.access


@dataclass
class InMemoryInstallationAdapter:
    installations: Mapping[str, LocalInstallation] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def inspect(self, channel: str) -> LocalInstallation | None:
        self.calls.append(channel)
        return self.installations.get(channel)


@dataclass
class InMemoryTerrainAdapter:
    statuses: Mapping[str, TerrainStatus] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def inspect(self, channel: str) -> TerrainStatus:
        self.calls.append(channel)
        return self.statuses.get(channel, TerrainStatus(complete=False))


@dataclass
class InMemoryTelemetryAdapter:
    fail: bool = False
    events: list[TelemetryEvent] = field(default_factory=list)

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)
        if self.fail:
            raise RuntimeError("telemetry unavailable")


@dataclass
class InMemoryRuntimeAdapter:
    fail: bool = False
    handoffs: list[RuntimeHandoff] = field(default_factory=list)
    on_start: Callable[[RuntimeHandoff], None] | None = None

    def start(self, handoff: RuntimeHandoff) -> None:
        self.handoffs.append(handoff)
        if self.on_start is not None:
            self.on_start(handoff)
        if self.fail:
            raise RuntimeError("runtime unavailable")


class LauncherOrchestrator:
    """Make high-level Launcher decisions using only redacted adapter inputs."""

    def __init__(
        self,
        *,
        launcher_version: str,
        runtime_contract_version: int = RUNTIME_CONTRACT_VERSION,
        artifact_public_keys: Mapping[str, str],
        distribution_trust: DistributionTrust | None = None,
        distribution: DistributionAdapter,
        receipts: ReceiptAdapter,
        installations: InstallationAdapter,
        terrain: TerrainAdapter,
        telemetry: TelemetryAdapter,
        runtime: RuntimeAdapter,
        host_gate: RuntimeHostGate | None = None,
        public_default_channel: str = "Standard",
    ) -> None:
        if public_default_channel not in PUBLIC_CHANNELS:
            raise ValueError("public_default_channel must be Standard or Lite")
        if not isinstance(runtime_contract_version, int) or runtime_contract_version < 1:
            raise ValueError("runtime_contract_version must be a positive integer")
        if distribution_trust is None:
            distribution_trust = DistributionTrust.production(artifact_public_keys)
        elif dict(artifact_public_keys) != dict(distribution_trust.artifact_public_keys):
            raise ValueError(
                "distribution trust must use the configured artifact verification keys"
            )
        self.launcher_version = launcher_version
        self.runtime_contract_version = runtime_contract_version
        self.distribution_trust = distribution_trust
        self.artifact_public_keys = dict(distribution_trust.artifact_public_keys)
        self.distribution = distribution
        self.receipts = receipts
        self.installations = installations
        self.terrain = terrain
        self.telemetry = telemetry
        self.runtime = runtime
        self.host_gate = host_gate if host_gate is not None else RuntimeHostGate()
        self.public_default_channel = public_default_channel

    def evaluate(self, requested_channel: str) -> LauncherProjection:
        """Return a deterministic UI projection without launching or downloading."""

        requested = self._require_channel(requested_channel)
        if self.host_gate.is_active:
            return self._host_active_projection(requested)
        return self._evaluate(requested)

    def _evaluate(self, requested: str) -> LauncherProjection:
        """Evaluate one request while this orchestrator owns no active host lease."""

        selected, enhanced_allowed = self._select_channel(requested)
        available_channels = self._available_channels(enhanced_allowed)
        local = self.installations.inspect(selected)
        if local is not None:
            local_projection = self._local_preflight(
                requested,
                selected,
                available_channels,
                local,
            )
            if local_projection is not None:
                return local_projection

        try:
            remote = self._resolve_release(selected)
        except Exception:
            return self._distribution_unavailable_projection(
                requested,
                selected,
                available_channels,
                local,
            )

        remote_compatibility = app_compatibility(
            remote.app,
            launcher_version=self.launcher_version,
            runtime_contract_version=self.runtime_contract_version,
        )
        if local is not None:
            return self._remote_compatibility_with_local_projection(
                requested,
                selected,
                available_channels,
                local,
                remote,
                remote_compatibility,
            )
        return self._missing_local_projection(
            requested,
            selected,
            available_channels,
            remote,
            remote_compatibility,
        )

    def resolve_release(self, channel: str) -> ResolvedRelease:
        """Resolve one complete signed source; never mix source metadata and bytes."""

        selected = self._require_channel(channel)
        self.host_gate.require_idle("release refresh")
        return self._resolve_release(selected)

    def _resolve_release(self, selected: str) -> ResolvedRelease:
        """Resolve a release for an idle Launcher or the current host owner."""

        failure: Exception | None = None
        for source in self._candidate_sources(selected):
            try:
                return self._resolve_from_source(source, selected)
            except DistributionTrustError:
                raise
            except Exception as exc:
                failure = exc
        if failure is None:
            raise LaunchContractError("no distribution source is available")
        if isinstance(failure, LaunchContractError):
            raise LaunchContractError(str(failure)) from failure
        raise LaunchContractError("no verified distribution source is available") from failure

    def refresh_enhanced_access(self) -> ReceiptAccess:
        """Refresh authorization only before a managed App starts.

        The adapter returns only the redacted access result.  A receipt, session,
        device key, or artifact grant is not part of this orchestration seam.
        """

        self.host_gate.require_idle("authorization refresh")
        return self.receipts.refresh_access()

    def start(
        self,
        requested_channel: str,
        *,
        web_mode: WebLaunchMode | str | None = None,
    ) -> LaunchResult:
        """Run one managed App lifetime through the shared host.

        ``RuntimeAdapter.start`` represents the App lifetime: returning means a
        normal exit and raising means a concise application-error outcome.  The
        host lease is released in either case and never performs receipt cleanup.
        """

        requested = self._require_channel(requested_channel)
        lease = self.host_gate.try_acquire()
        if lease is None:
            return LaunchResult(
                projection=self._host_active_projection(requested),
                started=False,
            )
        try:
            projection = self._evaluate(requested)
            if not projection.can_launch:
                return LaunchResult(projection=projection, started=False)
            local = self.installations.inspect(projection.selected_channel)
            if local is None:
                return LaunchResult(projection=projection, started=False)
            terrain_status = self._terrain_status(projection.selected_channel, local.capabilities)
            handoff = build_runtime_handoff(
                channel=projection.selected_channel,
                launcher_version=self.launcher_version,
                runtime_contract_version=self.runtime_contract_version,
                terrain_complete=terrain_status.complete,
                terrain_location=terrain_status.path,
                capabilities=local.capabilities,
                requested_web_mode=web_mode,
            )
            self.host_gate.bind_channel(lease, handoff.channel)
            try:
                self.runtime.start(handoff)
            except Exception:
                outcome = RuntimeHostOutcome.application_error()
            else:
                outcome = RuntimeHostOutcome.normal_exit()
            with suppress(Exception):
                self.telemetry.emit(
                    TelemetryEvent(
                        channel=handoff.channel,
                        app_version=local.app_version,
                        launcher_version=handoff.launcher_version,
                        state=projection.state,
                        source=projection.source,
                        terrain_complete=handoff.terrain_complete,
                    )
                )
            return LaunchResult(
                projection=projection,
                started=True,
                host_outcome=outcome,
            )
        finally:
            self.host_gate.release(lease)

    def _resolve_from_source(self, source: str, channel: str) -> ResolvedRelease:
        descriptor_document = self.distribution.load_descriptor(source)
        descriptor = parse_distribution_descriptor(
            descriptor_document,
            public_keys=self.artifact_public_keys,
            trust=self.distribution_trust,
        )
        if descriptor.source != source:
            raise LaunchContractError(
                "distribution descriptor source does not match adapter source"
            )
        reference = descriptor.app_reference(channel)
        app_document = self.distribution.load_manifest(reference.manifest_url)
        app = parse_app_manifest(app_document, public_keys=self.artifact_public_keys)
        validate_descriptor_app_binding(
            descriptor,
            channel=channel,
            manifest_document=app_document,
            manifest=app,
        )
        return ResolvedRelease(source=source, app=app)

    def _select_channel(self, requested: str) -> tuple[str, bool]:
        if requested != "Enhanced":
            return requested, False
        access = self.receipts.cached_access()
        if access.allowed:
            return "Enhanced", True
        return self.public_default_channel, False

    @staticmethod
    def _available_channels(enhanced_allowed: bool) -> tuple[str, ...]:
        if enhanced_allowed:
            return ("Enhanced", *PUBLIC_CHANNELS)
        return PUBLIC_CHANNELS

    @staticmethod
    def _require_channel(channel: str) -> str:
        if channel not in RELEASE_CHANNELS:
            raise ValueError("requested channel is unsupported")
        return channel

    def _candidate_sources(self, channel: str) -> tuple[str, ...]:
        if self.distribution_trust.environment is DistributionEnvironment.TEST:
            return ("primary",)
        if channel == "Enhanced":
            return ("primary",)
        return ("primary", "github")

    def _local_preflight(
        self,
        requested: str,
        selected: str,
        available_channels: tuple[str, ...],
        local: LocalInstallation,
    ) -> LauncherProjection | None:
        if not local.verified or local.channel != selected:
            return self._projection(
                requested=requested,
                selected=selected,
                available_channels=available_channels,
                state=LauncherState.REPAIR_REQUIRED,
                can_launch=False,
                can_download=False,
                source=None,
                compatibility=CompatibilityState.COMPATIBLE,
                capabilities=local.capabilities.known(),
                terrain_degraded=False,
                user_message="本地文件需要修复后才能启动。",
                diagnostics=("local_installation_invalid",),
            )
        if local.app is None:
            return None
        compatibility = app_compatibility(
            local.app,
            launcher_version=self.launcher_version,
            runtime_contract_version=self.runtime_contract_version,
        )
        if compatibility is CompatibilityState.COMPATIBLE:
            return None
        return self._projection(
            requested=requested,
            selected=selected,
            available_channels=available_channels,
            state=LauncherState.REPAIR_REQUIRED,
            can_launch=False,
            can_download=False,
            source=None,
            compatibility=compatibility,
            capabilities=local.app.capabilities.known(),
            terrain_degraded=False,
            user_message=self._compatibility_message(compatibility),
            diagnostics=("local_compatibility_rejected",),
        )

    def _distribution_unavailable_projection(
        self,
        requested: str,
        selected: str,
        available_channels: tuple[str, ...],
        local: LocalInstallation | None,
    ) -> LauncherProjection:
        if local is not None and local.verified:
            terrain_status = self._terrain_status(selected, local.capabilities)
            return self._projection(
                requested=requested,
                selected=selected,
                available_channels=available_channels,
                state=LauncherState.UPDATE_UNAVAILABLE_LOCAL_FALLBACK,
                can_launch=True,
                can_download=False,
                source=None,
                compatibility=CompatibilityState.COMPATIBLE,
                capabilities=local.capabilities.known(),
                terrain_degraded=not terrain_status.complete,
                user_message="在线更新暂不可用，仍可启动已安装版本。",
                diagnostics=("distribution_unavailable",),
            )
        return self._projection(
            requested=requested,
            selected=selected,
            available_channels=available_channels,
            state=LauncherState.DOWNLOAD_REQUIRED,
            can_launch=False,
            can_download=False,
            source=None,
            compatibility=CompatibilityState.COMPATIBLE,
            capabilities=CapabilityEnvelope.legacy_fallback().known(),
            terrain_degraded=False,
            user_message="尚未安装此通道；在线下载暂不可用。",
            diagnostics=("distribution_unavailable",),
        )

    def _remote_compatibility_with_local_projection(
        self,
        requested: str,
        selected: str,
        available_channels: tuple[str, ...],
        local: LocalInstallation,
        remote: ResolvedRelease,
        compatibility: CompatibilityState,
    ) -> LauncherProjection:
        terrain_status = self._terrain_status(selected, local.capabilities)
        if compatibility is not CompatibilityState.COMPATIBLE:
            return self._projection(
                requested=requested,
                selected=selected,
                available_channels=available_channels,
                state=LauncherState.READY_TO_START,
                can_launch=True,
                can_download=False,
                source=remote.source,
                compatibility=compatibility,
                capabilities=local.capabilities.known(),
                terrain_degraded=not terrain_status.complete,
                user_message=self._compatibility_message(compatibility),
                diagnostics=("remote_compatibility_rejected",),
            )
        return self._projection(
            requested=requested,
            selected=selected,
            available_channels=available_channels,
            state=LauncherState.READY_TO_START,
            can_launch=True,
            can_download=True,
            source=remote.source,
            compatibility=CompatibilityState.COMPATIBLE,
            capabilities=local.capabilities.known(),
            terrain_degraded=not terrain_status.complete,
            user_message="已就绪，可启动本地应用。",
        )

    def _missing_local_projection(
        self,
        requested: str,
        selected: str,
        available_channels: tuple[str, ...],
        remote: ResolvedRelease,
        compatibility: CompatibilityState,
    ) -> LauncherProjection:
        if compatibility is not CompatibilityState.COMPATIBLE:
            return self._projection(
                requested=requested,
                selected=selected,
                available_channels=available_channels,
                state=LauncherState.DOWNLOAD_REQUIRED,
                can_launch=False,
                can_download=False,
                source=remote.source,
                compatibility=compatibility,
                capabilities=remote.app.capabilities.known(),
                terrain_degraded=False,
                user_message=self._compatibility_message(compatibility),
                diagnostics=("remote_compatibility_rejected",),
            )
        terrain_status = self._terrain_status(selected, remote.app.capabilities)
        return self._projection(
            requested=requested,
            selected=selected,
            available_channels=available_channels,
            state=LauncherState.DOWNLOAD_REQUIRED,
            can_launch=False,
            can_download=True,
            source=remote.source,
            compatibility=CompatibilityState.COMPATIBLE,
            capabilities=remote.app.capabilities.known(),
            terrain_degraded=not terrain_status.complete,
            user_message="尚未安装此通道，需要下载。",
        )

    def _host_active_projection(self, requested: str) -> LauncherProjection:
        """Report the active App without touching update or authorization adapters."""

        return self._projection(
            requested=requested,
            selected=self.host_gate.active_channel or requested,
            available_channels=(),
            state=LauncherState.READY_TO_START,
            can_launch=False,
            can_download=False,
            source=None,
            compatibility=CompatibilityState.COMPATIBLE,
            capabilities=CapabilityEnvelope.legacy_fallback().known(),
            terrain_degraded=False,
            user_message="应用正在运行；请先退出当前应用后再启动、更新或刷新授权。",
            diagnostics=("runtime_host_active",),
            host_active=True,
        )

    def _terrain_status(self, channel: str, capabilities: CapabilityEnvelope) -> TerrainStatus:
        if channel != "Enhanced":
            return TerrainStatus(complete=True)
        if capabilities.legacy:
            return TerrainStatus(complete=False)
        if not capabilities.known()["terrain_recommended"]:
            return TerrainStatus(complete=True)
        return self.terrain.inspect(channel)

    @staticmethod
    def _compatibility_message(compatibility: CompatibilityState) -> str:
        if compatibility is CompatibilityState.LAUNCHER_UPDATE_REQUIRED:
            return "需要更新启动器后才能使用此版本。"
        if compatibility is CompatibilityState.RUNTIME_UPDATE_REQUIRED:
            return "需要更新启动器运行时后才能使用此版本。"
        return "已就绪，可启动本地应用。"

    @staticmethod
    def _projection(
        *,
        requested: str,
        selected: str,
        available_channels: tuple[str, ...],
        state: LauncherState,
        can_launch: bool,
        can_download: bool,
        source: str | None,
        compatibility: CompatibilityState,
        capabilities: Mapping[str, bool],
        terrain_degraded: bool,
        user_message: str,
        diagnostics: tuple[str, ...] = (),
        host_active: bool = False,
    ) -> LauncherProjection:
        return LauncherProjection(
            requested_channel=requested,
            selected_channel=selected,
            available_channels=available_channels,
            state=state,
            can_launch=can_launch,
            can_download=can_download,
            source=source,
            compatibility=compatibility,
            capabilities=capabilities,
            web_modes=released_web_modes(capabilities),
            terrain_degraded=terrain_degraded,
            user_message=user_message,
            diagnostics=diagnostics,
            host_active=host_active,
        )


__all__ = [
    "DistributionAdapter",
    "DistributionTrust",
    "InMemoryDistributionAdapter",
    "InMemoryInstallationAdapter",
    "InMemoryReceiptAdapter",
    "InMemoryRuntimeAdapter",
    "InMemoryTelemetryAdapter",
    "InMemoryTerrainAdapter",
    "InstallationAdapter",
    "LaunchDecision",
    "LaunchResult",
    "LauncherOrchestrator",
    "LauncherProjection",
    "LauncherState",
    "LocalInstallation",
    "ReceiptAccess",
    "ReceiptAdapter",
    "ResolvedRelease",
    "RuntimeAdapter",
    "RuntimeHandoff",
    "RuntimeHostGate",
    "RuntimeHostOutcome",
    "TelemetryAdapter",
    "TelemetryEvent",
    "TerrainAdapter",
    "TerrainStatus",
    "WebLaunchMode",
]
