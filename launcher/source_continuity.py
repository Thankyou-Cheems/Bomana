"""Pure whole-source selection and local-continuity rules for Launcher delivery.

Transport adapters fetch a signed Distribution Descriptor, its referenced App
manifest, and the two App assets.  This module verifies that all three belong
to one selected source before exposing them to an installer.  It deliberately
does not fetch bytes, persist state, or decide UI presentation.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlparse

from launcher.launch_contract import (
    PUBLIC_CHANNELS,
    RELEASE_CHANNELS,
    AppManifest,
    CompatibilityState,
    DistributionDescriptor,
    LaunchContractError,
    app_compatibility,
    contract_document_sha256,
    parse_app_manifest,
    parse_distribution_descriptor,
    validate_descriptor_app_binding,
)
from launcher.manifest_sources import (
    ManifestSourceError,
    validate_public_fallback_descriptor,
    validate_public_fallback_url,
)

PRIMARY_SOURCE = "primary"
GITHUB_SOURCE = "github"
_SUPPORTED_SOURCES = frozenset({PRIMARY_SOURCE, GITHUB_SOURCE})


class SourceContinuityError(LaunchContractError):
    """Raised when a transport source cannot prove a complete release view."""


class ContinuityState(StrEnum):
    """The transport decision before the Launcher projects its user-facing state."""

    REMOTE = "remote"
    LOCAL_FALLBACK = "local_fallback"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SourceBoundAppManifest:
    """One signed App manifest and its same-source package and changelog URLs."""

    source: str
    manifest_url: str
    document: Mapping[str, Any]
    package_asset: str
    package_url: str
    changelog_asset: str
    changelog_url: str


class DistributionSourceAdapter(Protocol):
    """Minimal network boundary used by the deterministic source selector."""

    source: str

    def load_descriptor(self) -> Mapping[str, Any]: ...

    def load_app_manifest(self, manifest_url: str) -> SourceBoundAppManifest: ...

    def owns_url(self, url: str) -> bool: ...


@dataclass(frozen=True)
class ResolvedDistribution:
    """A verified App release whose descriptor, manifest, and assets share one source."""

    source: str
    descriptor_document: Mapping[str, Any]
    descriptor: DistributionDescriptor
    app: AppManifest
    manifest_url: str
    package_url: str
    changelog_url: str
    from_last_known_good: bool = False


@dataclass(frozen=True)
class LastKnownGoodDescriptor:
    """A source-tagged descriptor cache, never an independent version authority."""

    source: str
    descriptor_document: Mapping[str, Any]
    descriptor_sha256: str
    acquired_at: str


@dataclass(frozen=True)
class ContinuityDecision:
    """Pure release-resolution result with an optional compatible local fallback."""

    state: ContinuityState
    remote: ResolvedDistribution | None = None
    local_app: AppManifest | None = None
    diagnostics: tuple[str, ...] = ()

    @property
    def can_start_locally(self) -> bool:
        return self.state is ContinuityState.LOCAL_FALLBACK and self.local_app is not None


def cache_last_known_good(
    resolved: ResolvedDistribution,
    *,
    acquired_at: str,
) -> LastKnownGoodDescriptor:
    """Create a cache record only from a release that already passed full binding checks."""

    timestamp = str(acquired_at).strip()
    if not timestamp:
        raise SourceContinuityError("last-known-good acquisition time is required")
    document = _copy_document(resolved.descriptor_document)
    return LastKnownGoodDescriptor(
        source=resolved.source,
        descriptor_document=document,
        descriptor_sha256=contract_document_sha256(document),
        acquired_at=timestamp,
    )


def resolve_complete_source(
    channel: str,
    *,
    adapter: DistributionSourceAdapter,
    public_keys: Mapping[str, str],
    last_known_good: LastKnownGoodDescriptor | None = None,
) -> ResolvedDistribution:
    """Resolve one signed descriptor view without crossing to another source.

    Supplying ``last_known_good`` bypasses only descriptor retrieval.  The
    referenced manifest and both assets still come from the cache's exact
    source adapter, and the manifest digest remains bound to the descriptor.
    """

    selected_channel = _require_channel(channel)
    source = _adapter_source(adapter)
    if last_known_good is None:
        descriptor_document = _copy_document(adapter.load_descriptor())
    else:
        descriptor_document = _last_known_good_document(last_known_good, source)

    descriptor = parse_distribution_descriptor(
        descriptor_document,
        public_keys=public_keys,
    )
    if descriptor.source != source:
        raise SourceContinuityError("distribution descriptor source does not match adapter source")
    if source == GITHUB_SOURCE:
        try:
            validate_public_fallback_descriptor(
                descriptor,
                url_is_owned=adapter.owns_url,
            )
        except ManifestSourceError as exc:
            raise SourceContinuityError(str(exc)) from exc
    else:
        _validate_descriptor_reference_urls(descriptor, adapter)
    reference = descriptor.app_reference(selected_channel)
    manifest_url = _require_owned_url(adapter, reference.manifest_url, "app manifest URL")
    fetched = adapter.load_app_manifest(manifest_url)
    _validate_source_bound_manifest(fetched, source=source, manifest_url=manifest_url)
    app = parse_app_manifest(fetched.document, public_keys=public_keys)
    validate_descriptor_app_binding(
        descriptor,
        channel=selected_channel,
        manifest_document=fetched.document,
        manifest=app,
    )
    _validate_source_bound_assets(fetched, app, adapter=adapter)
    return ResolvedDistribution(
        source=source,
        descriptor_document=descriptor_document,
        descriptor=descriptor,
        app=app,
        manifest_url=manifest_url,
        package_url=_require_https_url(fetched.package_url, "package asset URL"),
        changelog_url=_require_https_url(fetched.changelog_url, "changelog asset URL"),
        from_last_known_good=last_known_good is not None,
    )


def resolve_with_local_continuity(
    channel: str,
    *,
    primary: DistributionSourceAdapter,
    github: DistributionSourceAdapter | None,
    public_keys: Mapping[str, str],
    launcher_version: str,
    runtime_contract_version: int,
    local_app: AppManifest | None = None,
    last_known_good: LastKnownGoodDescriptor | None = None,
) -> ContinuityDecision:
    """Prefer primary, reuse only its bound cache, then use GitHub for public channels.

    Enhanced has no GitHub attempt, including a cached GitHub descriptor.  If
    all eligible remote views fail, a verified caller may start a local App
    when its signed channel and compatibility floors still match.
    """

    selected_channel = _require_channel(channel)
    diagnostics: list[str] = []
    remote = _try_source(
        PRIMARY_SOURCE,
        selected_channel,
        adapter=primary,
        public_keys=public_keys,
        diagnostics=diagnostics,
    )
    if remote is None and _cache_matches_source(last_known_good, PRIMARY_SOURCE):
        remote = _try_source(
            PRIMARY_SOURCE,
            selected_channel,
            adapter=primary,
            public_keys=public_keys,
            diagnostics=diagnostics,
            last_known_good=last_known_good,
            attempt_name="cached_primary",
        )
    if remote is None and selected_channel in PUBLIC_CHANNELS and github is not None:
        remote = _try_source(
            GITHUB_SOURCE,
            selected_channel,
            adapter=github,
            public_keys=public_keys,
            diagnostics=diagnostics,
        )
    if (
        remote is None
        and selected_channel in PUBLIC_CHANNELS
        and github is not None
        and _cache_matches_source(last_known_good, GITHUB_SOURCE)
    ):
        remote = _try_source(
            GITHUB_SOURCE,
            selected_channel,
            adapter=github,
            public_keys=public_keys,
            diagnostics=diagnostics,
            last_known_good=last_known_good,
            attempt_name="cached_github",
        )
    if _github_candidate_is_stale(
        remote,
        selected_channel,
        local_app,
        launcher_version=launcher_version,
        runtime_contract_version=runtime_contract_version,
    ):
        diagnostics.append("github_stale")
        remote = None
    if remote is not None:
        return ContinuityDecision(
            state=ContinuityState.REMOTE,
            remote=remote,
            diagnostics=tuple(diagnostics),
        )

    if _local_app_is_compatible(
        selected_channel,
        local_app,
        launcher_version=launcher_version,
        runtime_contract_version=runtime_contract_version,
    ):
        return ContinuityDecision(
            state=ContinuityState.LOCAL_FALLBACK,
            local_app=local_app,
            diagnostics=tuple(diagnostics),
        )
    if local_app is not None:
        diagnostics.append("local_incompatible")
    return ContinuityDecision(state=ContinuityState.UNAVAILABLE, diagnostics=tuple(diagnostics))


def _try_source(
    expected_source: str,
    channel: str,
    *,
    adapter: DistributionSourceAdapter,
    public_keys: Mapping[str, str],
    diagnostics: list[str],
    last_known_good: LastKnownGoodDescriptor | None = None,
    attempt_name: str | None = None,
) -> ResolvedDistribution | None:
    name = attempt_name or expected_source
    try:
        if _adapter_source(adapter) != expected_source:
            raise SourceContinuityError("selected source does not match adapter source")
        return resolve_complete_source(
            channel,
            adapter=adapter,
            public_keys=public_keys,
            last_known_good=last_known_good,
        )
    except Exception as exc:
        suffix = "rejected" if isinstance(exc, LaunchContractError) else "unavailable"
        diagnostics.append(f"{name}_{suffix}")
        return None


def _validate_source_bound_manifest(
    fetched: SourceBoundAppManifest,
    *,
    source: str,
    manifest_url: str,
) -> None:
    if _require_source(fetched.source) != source:
        raise SourceContinuityError("app manifest source does not match selected source")
    if _require_https_url(fetched.manifest_url, "app manifest URL") != manifest_url:
        raise SourceContinuityError("app manifest URL does not match distribution descriptor")


def _validate_descriptor_reference_urls(
    descriptor: DistributionDescriptor,
    adapter: DistributionSourceAdapter,
) -> None:
    for reference in descriptor.artifacts:
        _require_owned_url(adapter, reference.manifest_url, f"{reference.kind} manifest URL")
        if reference.object_base_url is not None:
            _require_owned_url(adapter, reference.object_base_url, "terrain object base URL")


def _validate_source_bound_assets(
    fetched: SourceBoundAppManifest,
    app: AppManifest,
    *,
    adapter: DistributionSourceAdapter,
) -> None:
    if fetched.package_asset != app.package_asset:
        raise SourceContinuityError("package asset does not match signed app manifest")
    if fetched.changelog_asset != app.changelog_asset:
        raise SourceContinuityError("changelog asset does not match signed app manifest")
    _require_source_asset_url(adapter, fetched.package_url, "package asset URL")
    _require_source_asset_url(adapter, fetched.changelog_url, "changelog asset URL")


def _last_known_good_document(
    cached: LastKnownGoodDescriptor,
    source: str,
) -> dict[str, Any]:
    if _require_source(cached.source) != source:
        raise SourceContinuityError("last-known-good source does not match adapter source")
    document = _copy_document(cached.descriptor_document)
    if contract_document_sha256(document) != cached.descriptor_sha256:
        raise SourceContinuityError("last-known-good descriptor digest does not match")
    return document


def _cache_matches_source(cached: LastKnownGoodDescriptor | None, source: str) -> bool:
    return cached is not None and cached.source == source


def _local_app_is_compatible(
    channel: str,
    local_app: AppManifest | None,
    *,
    launcher_version: str,
    runtime_contract_version: int,
) -> bool:
    if local_app is None or local_app.channel != channel:
        return False
    return (
        app_compatibility(
            local_app,
            launcher_version=launcher_version,
            runtime_contract_version=runtime_contract_version,
        )
        is CompatibilityState.COMPATIBLE
    )


def _github_candidate_is_stale(
    remote: ResolvedDistribution | None,
    channel: str,
    local_app: AppManifest | None,
    *,
    launcher_version: str,
    runtime_contract_version: int,
) -> bool:
    if remote is None or remote.source != GITHUB_SOURCE:
        return False
    if not _local_app_is_compatible(
        channel,
        local_app,
        launcher_version=launcher_version,
        runtime_contract_version=runtime_contract_version,
    ):
        return False
    assert local_app is not None
    return _semantic_version(remote.app.app_version) <= _semantic_version(local_app.app_version)


def _semantic_version(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _adapter_source(adapter: DistributionSourceAdapter) -> str:
    return _require_source(adapter.source)


def _require_owned_url(
    adapter: DistributionSourceAdapter,
    value: object,
    label: str,
) -> str:
    url = _require_https_url(value, label)
    try:
        owned = adapter.owns_url(url)
    except Exception as exc:
        raise SourceContinuityError(f"{label} ownership validation failed") from exc
    if owned is not True:
        raise SourceContinuityError(f"{label} does not belong to selected source")
    return url


def _require_source_asset_url(
    adapter: DistributionSourceAdapter,
    value: object,
    label: str,
) -> str:
    url = _require_https_url(value, label)
    if _adapter_source(adapter) != GITHUB_SOURCE:
        return _require_owned_url(adapter, url, label)
    try:
        validate_public_fallback_url(url, url_is_owned=adapter.owns_url)
    except ManifestSourceError as exc:
        raise SourceContinuityError(str(exc)) from exc
    return url


def _require_channel(channel: str) -> str:
    selected = str(channel).strip()
    if selected not in RELEASE_CHANNELS:
        raise ValueError("requested channel is unsupported")
    return selected


def _require_source(value: object) -> str:
    source = str(value).strip()
    if source not in _SUPPORTED_SOURCES:
        raise SourceContinuityError("distribution source is unsupported")
    return source


def _require_https_url(value: object, label: str) -> str:
    url = str(value).strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SourceContinuityError(f"{label} is not a safe HTTPS URL")
    return url


def _copy_document(document: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise SourceContinuityError("distribution document must be an object")
    return copy.deepcopy(dict(document))


__all__ = [
    "ContinuityDecision",
    "ContinuityState",
    "DistributionSourceAdapter",
    "GITHUB_SOURCE",
    "LastKnownGoodDescriptor",
    "PRIMARY_SOURCE",
    "ResolvedDistribution",
    "SourceBoundAppManifest",
    "SourceContinuityError",
    "cache_last_known_good",
    "resolve_complete_source",
    "resolve_with_local_continuity",
]
