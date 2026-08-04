"""Immutable distribution identity embedded into a packaged Launcher.

The vNext Launcher has two intentionally incompatible build identities:
production and the isolated real-device test route.  Runtime configuration may
repeat the embedded base URL but may never switch a packaged Launcher across
those identities.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlparse

PRODUCTION_PROFILE = "production"
ISOLATED_TEST_PROFILE = "isolated-test"
PRODUCTION_BASE_URL = "https://bomanaupdate.ruikang.wang"
ISOLATED_TEST_BASE_URL = "https://tempbomanaupdate.ruikang.wang"
TEST_DISTRIBUTION_HOST = "tempbomanaupdate.ruikang.wang"
TEST_BUILD_MARKER = "ISOLATED TEST BUILD"

_GENERATED_CONFIG_START = "# >>> BOMANA DISTRIBUTION BUILD CONFIG >>>"
_GENERATED_CONFIG_END = "# <<< BOMANA DISTRIBUTION BUILD CONFIG <<<"


class DistributionBuildError(RuntimeError):
    """Raised when a Launcher crosses its embedded distribution boundary."""


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DistributionBuildError(f"{label} must be a non-empty string")
    return value.strip()


def _normalize_base_url(value: object, label: str) -> str:
    url = _required_text(value, label).rstrip("/")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise DistributionBuildError(f"{label} must be a stable HTTPS origin") from exc
    hostname = parsed.hostname
    if (
        parsed.scheme != "https"
        or hostname is None
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise DistributionBuildError(f"{label} must be a stable HTTPS origin")
    return f"https://{hostname.rstrip('.').lower()}"


@dataclass(frozen=True)
class DistributionBuildMetadata:
    """The profile and artifact verifier identity compiled into one Launcher."""

    profile: str
    base_url: str
    artifact_key_id: str
    artifact_public_keys: Mapping[str, str]
    test_marker: str
    github_fallback_allowed: bool

    def __post_init__(self) -> None:
        profile = _required_text(self.profile, "distribution build profile")
        if profile not in (PRODUCTION_PROFILE, ISOLATED_TEST_PROFILE):
            raise DistributionBuildError("distribution build profile is unsupported")
        base_url = _normalize_base_url(self.base_url, "distribution base URL")
        key_id = _required_text(self.artifact_key_id, "artifact signing key id")
        if not isinstance(self.artifact_public_keys, Mapping):
            raise DistributionBuildError("artifact verification keys must be a mapping")
        keys = {
            _required_text(candidate_key_id, "artifact verification key id"): _required_text(
                candidate_key,
                "artifact verification key",
            )
            for candidate_key_id, candidate_key in self.artifact_public_keys.items()
        }
        if key_id not in keys:
            raise DistributionBuildError(
                "artifact signing key id is absent from the artifact verifier"
            )
        if not isinstance(self.github_fallback_allowed, bool):
            raise DistributionBuildError("GitHub fallback flag must be boolean")
        marker = self.test_marker if isinstance(self.test_marker, str) else ""

        if profile == PRODUCTION_PROFILE:
            if base_url == ISOLATED_TEST_BASE_URL:
                raise DistributionBuildError("production build rejects the test distribution host")
            if marker:
                raise DistributionBuildError("production build must not carry a test marker")
            if not self.github_fallback_allowed:
                raise DistributionBuildError(
                    "production build must retain its GitHub fallback policy"
                )
        else:
            if base_url != ISOLATED_TEST_BASE_URL:
                raise DistributionBuildError("isolated test build requires the isolated test route")
            if marker != TEST_BUILD_MARKER:
                raise DistributionBuildError("isolated test build marker is invalid")
            if self.github_fallback_allowed:
                raise DistributionBuildError("isolated test build rejects GitHub fallback")
            if set(keys) != {key_id}:
                raise DistributionBuildError(
                    "isolated test build requires exactly one test artifact key"
                )

        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "artifact_key_id", key_id)
        object.__setattr__(
            self, "artifact_public_keys", MappingProxyType(dict(sorted(keys.items())))
        )
        object.__setattr__(self, "test_marker", marker)

    @property
    def isolated_test(self) -> bool:
        return self.profile == ISOLATED_TEST_PROFILE


# >>> BOMANA DISTRIBUTION BUILD CONFIG >>>
_EMBEDDED_PROFILE = "production"
_EMBEDDED_BASE_URL = "https://bomanaupdate.ruikang.wang"
_EMBEDDED_ARTIFACT_KEY_ID = "bomana-release-2026-08-v2"
_EMBEDDED_ARTIFACT_PUBLIC_KEYS = {
    "bomana-release-2026-08-v2": "zSMo0z0dAKYP2j0pV68vJ0NvtonEV1CVyMWz/f5Rd6s=",
}
_EMBEDDED_TEST_MARKER = ""
_EMBEDDED_GITHUB_FALLBACK_ALLOWED = True
# <<< BOMANA DISTRIBUTION BUILD CONFIG <<<


def current_build_metadata() -> DistributionBuildMetadata:
    """Return the immutable profile data compiled into this Launcher build."""

    return DistributionBuildMetadata(
        profile=_EMBEDDED_PROFILE,
        base_url=_EMBEDDED_BASE_URL,
        artifact_key_id=_EMBEDDED_ARTIFACT_KEY_ID,
        artifact_public_keys=_EMBEDDED_ARTIFACT_PUBLIC_KEYS,
        test_marker=_EMBEDDED_TEST_MARKER,
        github_fallback_allowed=_EMBEDDED_GITHUB_FALLBACK_ALLOWED,
    )


def artifact_verifier_public_keys(
    metadata: DistributionBuildMetadata | None = None,
) -> Mapping[str, str]:
    """Return only the artifact keys compiled for this build profile."""

    selected = current_build_metadata() if metadata is None else metadata
    return selected.artifact_public_keys


def resolve_runtime_base_url(
    configured_base_url: str | None,
    *,
    metadata: DistributionBuildMetadata | None = None,
) -> str:
    """Resolve a runtime URL only when it matches the embedded build profile."""

    selected = current_build_metadata() if metadata is None else metadata
    requested = "" if configured_base_url is None else configured_base_url.strip()
    if not requested:
        return selected.base_url
    candidate = _normalize_base_url(requested, "runtime distribution base URL")
    if candidate != selected.base_url:
        raise DistributionBuildError(
            "runtime distribution base URL does not match the embedded distribution build profile"
        )
    return selected.base_url


def render_embedded_distribution_build_module(
    source: str,
    metadata: DistributionBuildMetadata,
) -> str:
    """Render a source-equivalent module with only one embedded build identity."""

    start_region = f"\n{_GENERATED_CONFIG_START}\n"
    end_region = f"\n{_GENERATED_CONFIG_END}\n"
    start = source.find(start_region)
    end = source.find(end_region, start + len(start_region))
    if start < 0 or end < 0 or end < start:
        raise DistributionBuildError("distribution build source has no generated config region")
    config = "\n".join(
        (
            _GENERATED_CONFIG_START,
            f"_EMBEDDED_PROFILE = {metadata.profile!r}",
            f"_EMBEDDED_BASE_URL = {metadata.base_url!r}",
            f"_EMBEDDED_ARTIFACT_KEY_ID = {metadata.artifact_key_id!r}",
            f"_EMBEDDED_ARTIFACT_PUBLIC_KEYS = {dict(metadata.artifact_public_keys)!r}",
            f"_EMBEDDED_TEST_MARKER = {metadata.test_marker!r}",
            f"_EMBEDDED_GITHUB_FALLBACK_ALLOWED = {metadata.github_fallback_allowed!r}",
            _GENERATED_CONFIG_END,
        )
    )
    return source[: start + 1] + config + source[end + len(end_region) - 1 :]


__all__ = [
    "DistributionBuildError",
    "DistributionBuildMetadata",
    "ISOLATED_TEST_BASE_URL",
    "ISOLATED_TEST_PROFILE",
    "PRODUCTION_BASE_URL",
    "PRODUCTION_PROFILE",
    "TEST_BUILD_MARKER",
    "TEST_DISTRIBUTION_HOST",
    "artifact_verifier_public_keys",
    "current_build_metadata",
    "render_embedded_distribution_build_module",
    "resolve_runtime_base_url",
]
