"""Versioned signed contracts for Launcher release discovery and handoff.

This module is deliberately pure.  It defines the first integration boundary
for the Launcher architecture without changing the legacy Tk/update paths.
The production adapters that fetch bytes, install archives, or start a process
belong behind :mod:`launcher.orchestrator` in later slices.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

from launcher.core import ed25519_sign, ed25519_verify

CONTRACT_SCHEMA_VERSION = 1
CONTRACT_SIGNATURE_FIELD = "manifest_signature"
CONTRACT_SIGNATURE_ALGORITHM = "ed25519"
RUNTIME_CONTRACT_VERSION = 1
TERRAIN_CATALOG_CONTRACT_KIND = "terrain_catalog"
TERRAIN_CATALOG_SCHEMA_VERSION = 2
TEST_DISTRIBUTION_HOST = "tempbomanaupdate.ruikang.wang"
RELEASE_CHANNELS = ("Enhanced", "Standard", "Lite")
PUBLIC_CHANNELS = ("Standard", "Lite")
KNOWN_OPTIONAL_CAPABILITIES = frozenset(
    {
        "terrain_recommended",
        "terrain_features",
        "web_overlay",
        "web_standalone",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$",
    re.ASCII,
)
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", re.ASCII)
_TERRAIN_CATALOG_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$", re.ASCII)
_TERRAIN_MAP_DISPLAY_NAME_MAX_CHARS = 128


class LaunchContractError(RuntimeError):
    """Raised when signed Launcher contract data is malformed or untrusted."""


class DistributionTrustError(LaunchContractError):
    """Raised when a signed descriptor crosses its configured environment boundary."""


class CompatibilityState(StrEnum):
    """Compatibility projection kept separate from the four primary UI states."""

    COMPATIBLE = "compatible"
    LAUNCHER_UPDATE_REQUIRED = "launcher_update_required"
    RUNTIME_UPDATE_REQUIRED = "runtime_update_required"


class DistributionEnvironment(StrEnum):
    """The only distribution environments accepted by the vNext seam."""

    PRODUCTION = "production"
    TEST = "test"


@dataclass(frozen=True)
class DistributionTrust:
    """Explicitly bind a Launcher build to one release trust configuration.

    Production is deliberately unable to consume the isolated real-device test
    route.  Test builds use an independent public-key map and only resolve the
    isolated primary route, so a test failure cannot silently become a release
    request to production or GitHub.
    """

    environment: DistributionEnvironment
    artifact_public_keys: Mapping[str, str]
    test_distribution_host: str = TEST_DISTRIBUTION_HOST

    def __post_init__(self) -> None:
        try:
            environment = DistributionEnvironment(self.environment)
        except ValueError as exc:
            raise ValueError("distribution environment is unsupported") from exc
        keys = dict(self.artifact_public_keys)
        if not keys:
            raise ValueError("distribution trust requires artifact public keys")
        for key_id, key in keys.items():
            _require_nonempty_string(key_id, "artifact signing key id")
            _require_nonempty_string(key, "artifact signing key")
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "artifact_public_keys", MappingProxyType(keys))
        object.__setattr__(
            self,
            "test_distribution_host",
            _normalize_host(self.test_distribution_host, "test distribution host"),
        )

    @classmethod
    def production(cls, artifact_public_keys: Mapping[str, str]) -> DistributionTrust:
        return cls(
            environment=DistributionEnvironment.PRODUCTION,
            artifact_public_keys=artifact_public_keys,
        )

    @classmethod
    def test(cls, artifact_public_keys: Mapping[str, str]) -> DistributionTrust:
        return cls(
            environment=DistributionEnvironment.TEST,
            artifact_public_keys=artifact_public_keys,
        )


@dataclass(frozen=True)
class CapabilityEnvelope:
    """Signed optional capability metadata.

    Unknown values in ``optional`` intentionally remain data.  A Launcher only
    projects keys it recognizes, so a future optional surface cannot alter an
    older client.  A capability that needs a new protocol must instead raise an
    App compatibility floor.
    """

    schema_version: int
    optional: Mapping[str, Any]
    legacy: bool = False

    @classmethod
    def legacy_fallback(cls) -> CapabilityEnvelope:
        return cls(schema_version=0, optional=MappingProxyType({}), legacy=True)

    @classmethod
    def from_payload(cls, payload: object | None) -> CapabilityEnvelope:
        if payload is None:
            return cls.legacy_fallback()
        if not isinstance(payload, Mapping):
            raise LaunchContractError("capability envelope must be an object")
        if set(payload) != {"schema_version", "optional"}:
            raise LaunchContractError("capability envelope fields are invalid")
        schema_version = _require_positive_int(payload.get("schema_version"), "capability schema")
        if schema_version != CONTRACT_SCHEMA_VERSION:
            raise LaunchContractError("capability envelope schema is unsupported")
        optional = payload.get("optional")
        if not isinstance(optional, Mapping):
            raise LaunchContractError("capability optional fields must be an object")
        projected = dict(optional)
        for name in KNOWN_OPTIONAL_CAPABILITIES:
            if name in projected and not isinstance(projected[name], bool):
                raise LaunchContractError(f"capability {name} must be a boolean")
        _canonical_json_bytes(projected)
        return cls(
            schema_version=schema_version,
            optional=MappingProxyType(projected),
        )

    def known(self) -> Mapping[str, bool]:
        return MappingProxyType(
            {
                name: bool(self.optional.get(name, False))
                for name in sorted(KNOWN_OPTIONAL_CAPABILITIES)
            }
        )


@dataclass(frozen=True)
class AppManifest:
    channel: str
    app_version: str
    min_launcher_version: str
    runtime_contract_version: int
    entrypoint: str
    package_asset: str
    package_sha256: str
    changelog_asset: str
    changelog_sha256: str
    capabilities: CapabilityEnvelope


@dataclass(frozen=True)
class LauncherManifest:
    launcher_version: str
    min_app_version: str
    runtime_contract_version: int
    launcher_asset: str
    launcher_sha256: str
    launcher_size_bytes: int


@dataclass(frozen=True)
class TerrainManifest:
    channel: str
    terrain_pack_id: str
    terrain_revision: str
    min_runtime_contract_version: int
    map_count: int
    total_size_bytes: int
    files: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ManifestReference:
    kind: str
    channel: str | None
    manifest_url: str
    manifest_sha256: str
    object_base_url: str | None = None


@dataclass(frozen=True)
class DistributionDescriptor:
    distribution_revision: str
    source: str
    artifacts: tuple[ManifestReference, ...]

    def reference_for(self, kind: str, channel: str | None = None) -> ManifestReference:
        expected_channel = _normalize_channel(channel) if channel is not None else None
        matches = [
            reference
            for reference in self.artifacts
            if reference.kind == kind and reference.channel == expected_channel
        ]
        if len(matches) != 1:
            suffix = f" for {expected_channel}" if expected_channel else ""
            raise LaunchContractError(f"distribution descriptor has no {kind} manifest{suffix}")
        return matches[0]

    def app_reference(self, channel: str) -> ManifestReference:
        canonical_channel = _normalize_channel(channel)
        if self.source == "github" and canonical_channel == "Enhanced":
            raise LaunchContractError("GitHub distribution cannot serve Enhanced")
        return self.reference_for("app", canonical_channel)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LaunchContractError("contract data is not canonical JSON") from exc
    return serialized.encode("utf-8")


def contract_document_sha256(document: Mapping[str, Any]) -> str:
    """Return the canonical digest used to bind a descriptor to one manifest."""

    return hashlib.sha256(_canonical_json_bytes(dict(document))).hexdigest()


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LaunchContractError(f"{label} must be an object")
    return value


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        detail: list[str] = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if unexpected:
            detail.append(f"unexpected: {', '.join(unexpected)}")
        raise LaunchContractError(f"{label} fields are invalid ({'; '.join(detail)})")


def _require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LaunchContractError(f"{label} must be a non-empty string")
    return value.strip()


def _require_positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LaunchContractError(f"{label} must be a positive integer")
    return value


def _require_sha256(value: object, label: str) -> str:
    digest = _require_nonempty_string(value, label).lower()
    if not _SHA256_RE.fullmatch(digest):
        raise LaunchContractError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def _parse_semver(value: object, label: str) -> tuple[int, int, int]:
    text = _require_nonempty_string(value, label)
    match = _SEMVER_RE.fullmatch(text)
    if match is None:
        raise LaunchContractError(f"{label} must be strict ASCII X.Y.Z")
    return tuple(int(part) for part in match.groups())


def _require_semver(value: object, label: str) -> str:
    _parse_semver(value, label)
    return str(value)


def _normalize_channel(value: object) -> str:
    channel = _require_nonempty_string(value, "channel")
    if channel not in RELEASE_CHANNELS:
        raise LaunchContractError("channel is unsupported")
    return channel


def _require_https_url(value: object, label: str, *, trailing_slash: bool = False) -> str:
    url = _require_nonempty_string(value, label)
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
    ):
        raise LaunchContractError(f"{label} must be a stable HTTPS URL")
    if trailing_slash and not url.endswith("/"):
        raise LaunchContractError(f"{label} must end with a slash")
    return url


def _normalize_host(value: object, label: str) -> str:
    raw = _require_nonempty_string(value, label).rstrip(".").lower()
    parsed = urlparse(f"https://{raw}")
    hostname = parsed.hostname
    if (
        hostname is None
        or parsed.port is not None
        or hostname.rstrip(".").lower() != raw
        or any(character in raw for character in "/?#@")
    ):
        raise ValueError(f"{label} must be a hostname")
    return hostname.rstrip(".").lower()


def _url_host(url: str) -> str:
    hostname = urlparse(url).hostname
    if hostname is None:
        raise LaunchContractError("distribution URL host is invalid")
    return hostname.rstrip(".").lower()


def _safe_asset_name(value: object, label: str) -> str:
    name = _require_nonempty_string(value, label)
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise LaunchContractError(f"{label} must be a single asset name")
    return name


def _signature_fields(kind: str) -> tuple[str, ...]:
    if kind == "app":
        return (
            "schema_version",
            "kind",
            "channel",
            "app_version",
            "min_launcher_version",
            "runtime_contract_version",
            "entrypoint",
            "package_asset",
            "package_sha256",
            "changelog_asset",
            "changelog_sha256",
            "capabilities",
        )
    if kind == "launcher":
        return (
            "schema_version",
            "kind",
            "launcher_version",
            "min_app_version",
            "runtime_contract_version",
            "launcher_asset",
            "launcher_sha256",
            "launcher_size_bytes",
        )
    if kind == "terrain":
        return (
            "schema_version",
            "kind",
            "channel",
            "terrain_pack_id",
            "terrain_revision",
            "min_runtime_contract_version",
            "map_count",
            "total_size_bytes",
            "files",
        )
    if kind == TERRAIN_CATALOG_CONTRACT_KIND:
        return (
            "schema_version",
            "kind",
            "terrain_catalog_id",
            "terrain_revision",
            "min_runtime_contract_version",
            "shared_files",
            "maps",
        )
    if kind == "distribution":
        return (
            "schema_version",
            "kind",
            "distribution_revision",
            "source",
            "artifacts",
        )
    raise LaunchContractError("contract kind is unsupported")


def _without_signature(document: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != CONTRACT_SIGNATURE_FIELD}


def _validate_signature(signature: object) -> tuple[str, bytes]:
    value = _require_mapping(signature, "manifest signature")
    _require_exact_fields(
        value,
        {"algorithm", "key_id", "signature"},
        "manifest signature",
    )
    if value.get("algorithm") != CONTRACT_SIGNATURE_ALGORITHM:
        raise LaunchContractError("manifest signature algorithm is unsupported")
    key_id = _require_nonempty_string(value.get("key_id"), "manifest signature key_id")
    encoded = _require_nonempty_string(value.get("signature"), "manifest signature")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise LaunchContractError("manifest signature is not valid Base64") from exc
    if len(decoded) != 64:
        raise LaunchContractError("manifest signature length is invalid")
    return key_id, decoded


def _validate_app(document: Mapping[str, Any]) -> None:
    _require_exact_fields(document, set(_signature_fields("app")), "app manifest")
    _normalize_channel(document.get("channel"))
    _require_semver(document.get("app_version"), "app version")
    _require_semver(document.get("min_launcher_version"), "minimum launcher version")
    _require_positive_int(document.get("runtime_contract_version"), "runtime contract version")
    _safe_asset_name(document.get("entrypoint"), "app entrypoint")
    _safe_asset_name(document.get("package_asset"), "app package asset")
    _require_sha256(document.get("package_sha256"), "app package SHA-256")
    _safe_asset_name(document.get("changelog_asset"), "app changelog asset")
    _require_sha256(document.get("changelog_sha256"), "app changelog SHA-256")
    CapabilityEnvelope.from_payload(document.get("capabilities"))


def _validate_launcher(document: Mapping[str, Any]) -> None:
    _require_exact_fields(document, set(_signature_fields("launcher")), "launcher manifest")
    _require_semver(document.get("launcher_version"), "launcher version")
    _require_semver(document.get("min_app_version"), "minimum app version")
    _require_positive_int(document.get("runtime_contract_version"), "runtime contract version")
    _safe_asset_name(document.get("launcher_asset"), "launcher asset")
    _require_sha256(document.get("launcher_sha256"), "launcher SHA-256")
    if (
        not isinstance(document.get("launcher_size_bytes"), int)
        or isinstance(document.get("launcher_size_bytes"), bool)
        or document["launcher_size_bytes"] < 1
    ):
        raise LaunchContractError("launcher size must be a positive integer")


def _validate_terrain_file(value: object) -> None:
    item = _require_mapping(value, "terrain file")
    _require_exact_fields(item, {"path", "asset", "sha256", "size_bytes"}, "terrain file")
    _safe_asset_name(item.get("asset"), "terrain object asset")
    path = _require_nonempty_string(item.get("path"), "terrain file path")
    if path.startswith("/") or "\\" in path or ".." in path.split("/"):
        raise LaunchContractError("terrain file path is unsafe")
    _require_sha256(item.get("sha256"), "terrain object SHA-256")
    _require_positive_int(item.get("size_bytes"), "terrain object size")


def _validate_terrain(document: Mapping[str, Any]) -> None:
    _require_exact_fields(document, set(_signature_fields("terrain")), "terrain manifest")
    if _normalize_channel(document.get("channel")) != "Enhanced":
        raise LaunchContractError("terrain manifest must belong to Enhanced")
    pack_id = _require_nonempty_string(document.get("terrain_pack_id"), "terrain pack id")
    if not _REVISION_RE.fullmatch(pack_id):
        raise LaunchContractError("terrain pack id is invalid")
    _require_sha256(document.get("terrain_revision"), "terrain revision")
    _require_positive_int(
        document.get("min_runtime_contract_version"),
        "minimum terrain runtime contract version",
    )
    _require_positive_int(document.get("map_count"), "terrain map count")
    _require_positive_int(document.get("total_size_bytes"), "terrain total size")
    files = document.get("files")
    if not isinstance(files, list) or not files:
        raise LaunchContractError("terrain files must be a non-empty list")
    for item in files:
        _validate_terrain_file(item)


def _validate_terrain_catalog(document: Mapping[str, Any]) -> None:
    _require_exact_fields(
        document,
        set(_signature_fields(TERRAIN_CATALOG_CONTRACT_KIND)),
        "terrain catalog",
    )
    catalog_id = _require_nonempty_string(
        document.get("terrain_catalog_id"),
        "terrain catalog id",
    )
    if not _TERRAIN_CATALOG_ID_RE.fullmatch(catalog_id):
        raise LaunchContractError("terrain catalog id is invalid")
    _require_sha256(document.get("terrain_revision"), "terrain catalog revision")
    _require_positive_int(
        document.get("min_runtime_contract_version"),
        "minimum terrain runtime contract version",
    )
    shared_files = document.get("shared_files")
    if not isinstance(shared_files, list) or not shared_files:
        raise LaunchContractError("terrain catalog shared files must be a non-empty list")
    for item in shared_files:
        _validate_terrain_file(item)
    maps = document.get("maps")
    if not isinstance(maps, list) or not maps:
        raise LaunchContractError("terrain catalog maps must be a non-empty list")
    for raw_map in maps:
        terrain_map = _require_mapping(raw_map, "terrain catalog map")
        map_fields = set(terrain_map)
        if map_fields not in (
            {"map_id", "files"},
            {"map_id", "files", "display_name_zh"},
        ):
            raise LaunchContractError("terrain catalog map fields are invalid")
        map_id = _require_nonempty_string(terrain_map.get("map_id"), "terrain map id")
        if not _TERRAIN_CATALOG_ID_RE.fullmatch(map_id):
            raise LaunchContractError("terrain map id is invalid")
        if "display_name_zh" in terrain_map:
            display_name = terrain_map["display_name_zh"]
            if not isinstance(display_name, str):
                raise LaunchContractError("terrain map display name must be a string")
            if len(display_name.strip()) > _TERRAIN_MAP_DISPLAY_NAME_MAX_CHARS:
                raise LaunchContractError("terrain map display name is too long")
            if any(ord(character) < 32 or ord(character) == 127 for character in display_name):
                raise LaunchContractError("terrain map display name contains control characters")
        files = terrain_map.get("files")
        if not isinstance(files, list) or not files:
            raise LaunchContractError("terrain map files must be a non-empty list")
        for item in files:
            _validate_terrain_file(item)


def _reference_from_payload(value: object) -> ManifestReference:
    item = _require_mapping(value, "distribution artifact")
    kind = _require_nonempty_string(item.get("kind"), "distribution artifact kind")
    if kind == "app":
        _require_exact_fields(
            item,
            {"kind", "channel", "manifest_url", "manifest_sha256"},
            "app distribution artifact",
        )
        return ManifestReference(
            kind=kind,
            channel=_normalize_channel(item.get("channel")),
            manifest_url=_require_https_url(item.get("manifest_url"), "app manifest URL"),
            manifest_sha256=_require_sha256(item.get("manifest_sha256"), "app manifest SHA-256"),
        )
    if kind == "launcher":
        _require_exact_fields(
            item,
            {"kind", "manifest_url", "manifest_sha256"},
            "launcher distribution artifact",
        )
        return ManifestReference(
            kind=kind,
            channel=None,
            manifest_url=_require_https_url(item.get("manifest_url"), "launcher manifest URL"),
            manifest_sha256=_require_sha256(
                item.get("manifest_sha256"),
                "launcher manifest SHA-256",
            ),
        )
    if kind == "terrain":
        _require_exact_fields(
            item,
            {
                "kind",
                "channel",
                "manifest_url",
                "manifest_sha256",
                "object_base_url",
            },
            "terrain distribution artifact",
        )
        return ManifestReference(
            kind=kind,
            channel=_normalize_channel(item.get("channel")),
            manifest_url=_require_https_url(item.get("manifest_url"), "terrain manifest URL"),
            manifest_sha256=_require_sha256(
                item.get("manifest_sha256"),
                "terrain manifest SHA-256",
            ),
            object_base_url=_require_https_url(
                item.get("object_base_url"),
                "terrain object base URL",
                trailing_slash=True,
            ),
        )
    raise LaunchContractError("distribution artifact kind is unsupported")


def _validate_distribution(document: Mapping[str, Any]) -> None:
    _require_exact_fields(
        document, set(_signature_fields("distribution")), "distribution descriptor"
    )
    revision = _require_nonempty_string(
        document.get("distribution_revision"), "distribution revision"
    )
    if not _REVISION_RE.fullmatch(revision):
        raise LaunchContractError("distribution revision is invalid")
    source = _require_nonempty_string(document.get("source"), "distribution source")
    if source not in {"primary", "github"}:
        raise LaunchContractError("distribution source is unsupported")
    raw_artifacts = document.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise LaunchContractError("distribution artifacts must be a non-empty list")
    references = tuple(_reference_from_payload(item) for item in raw_artifacts)
    identities = {(item.kind, item.channel) for item in references}
    if len(identities) != len(references):
        raise LaunchContractError("distribution artifacts have duplicate identities")
    if source == "github" and any(
        item.channel == "Enhanced" or item.kind == "terrain" for item in references
    ):
        raise LaunchContractError("GitHub distribution cannot advertise Enhanced artifacts")


def _validate_distribution_trust(
    descriptor: DistributionDescriptor,
    trust: DistributionTrust,
) -> None:
    hosts = {_url_host(reference.manifest_url) for reference in descriptor.artifacts}
    hosts.update(
        _url_host(reference.object_base_url)
        for reference in descriptor.artifacts
        if reference.object_base_url is not None
    )
    if trust.environment is DistributionEnvironment.PRODUCTION:
        if trust.test_distribution_host in hosts:
            raise DistributionTrustError(
                "production distribution trust rejects the test-only distribution host"
            )
        return
    if descriptor.source != "primary":
        raise DistributionTrustError(
            "test distribution trust only permits the isolated primary source"
        )
    unexpected_hosts = sorted(host for host in hosts if host != trust.test_distribution_host)
    if unexpected_hosts:
        raise DistributionTrustError("test distribution trust rejects a non-test distribution host")


def _validate_unsigned_document(document: Mapping[str, Any], kind: str) -> None:
    _require_exact_fields(document, set(_signature_fields(kind)), f"{kind} contract")
    expected_schema_version = (
        TERRAIN_CATALOG_SCHEMA_VERSION
        if kind == TERRAIN_CATALOG_CONTRACT_KIND
        else CONTRACT_SCHEMA_VERSION
    )
    if document.get("schema_version") != expected_schema_version:
        raise LaunchContractError("contract schema is unsupported")
    if document.get("kind") != kind:
        raise LaunchContractError("contract kind does not match its signed fields")
    if kind == "app":
        _validate_app(document)
    elif kind == "launcher":
        _validate_launcher(document)
    elif kind == "terrain":
        _validate_terrain(document)
    elif kind == TERRAIN_CATALOG_CONTRACT_KIND:
        _validate_terrain_catalog(document)
    elif kind == "distribution":
        _validate_distribution(document)
    else:
        raise LaunchContractError("contract kind is unsupported")


def contract_signature_payload(
    document: Mapping[str, Any], *, expected_kind: str | None = None
) -> bytes:
    """Return canonical signed bytes after validating a contract document."""

    raw = _require_mapping(document, "contract document")
    unsigned = _without_signature(raw)
    kind = _require_nonempty_string(expected_kind or unsigned.get("kind"), "contract kind")
    _validate_unsigned_document(unsigned, kind)
    return _canonical_json_bytes({field: unsigned[field] for field in _signature_fields(kind)})


def sign_contract_document(
    document: Mapping[str, Any],
    private_key: str,
    *,
    key_id: str,
) -> dict[str, Any]:
    """Sign a versioned contract with the Unified Artifact Signing Root."""

    key = _require_nonempty_string(key_id, "contract signing key id")
    unsigned = _without_signature(_require_mapping(document, "contract document"))
    signature = ed25519_sign(contract_signature_payload(unsigned), private_key)
    result = dict(unsigned)
    result[CONTRACT_SIGNATURE_FIELD] = {
        "algorithm": CONTRACT_SIGNATURE_ALGORITHM,
        "key_id": key,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    return result


def verify_contract_document(
    document: Mapping[str, Any],
    *,
    public_keys: Mapping[str, str],
    expected_kind: str | None = None,
) -> None:
    """Verify a document only against artifact-signing roots supplied by Launcher."""

    raw = _require_mapping(document, "contract document")
    kind = _require_nonempty_string(expected_kind or raw.get("kind"), "contract kind")
    expected_fields = set(_signature_fields(kind)) | {CONTRACT_SIGNATURE_FIELD}
    _require_exact_fields(raw, expected_fields, f"{kind} contract")
    key_id, signature = _validate_signature(raw.get(CONTRACT_SIGNATURE_FIELD))
    key_text = _require_nonempty_string(public_keys.get(key_id), "trusted artifact signing key")
    try:
        public_key = base64.b64decode(key_text, validate=True)
    except ValueError as exc:
        raise LaunchContractError("trusted artifact signing key is not valid Base64") from exc
    if len(public_key) != 32:
        raise LaunchContractError("trusted artifact signing key length is invalid")
    if not ed25519_verify(
        contract_signature_payload(raw, expected_kind=kind), signature, public_key
    ):
        raise LaunchContractError("artifact contract signature verification failed")


def parse_app_manifest(
    document: Mapping[str, Any],
    *,
    public_keys: Mapping[str, str],
) -> AppManifest:
    verify_contract_document(document, public_keys=public_keys, expected_kind="app")
    return AppManifest(
        channel=_normalize_channel(document["channel"]),
        app_version=_require_semver(document["app_version"], "app version"),
        min_launcher_version=_require_semver(
            document["min_launcher_version"],
            "minimum launcher version",
        ),
        runtime_contract_version=_require_positive_int(
            document["runtime_contract_version"],
            "runtime contract version",
        ),
        entrypoint=_safe_asset_name(document["entrypoint"], "app entrypoint"),
        package_asset=_safe_asset_name(document["package_asset"], "app package asset"),
        package_sha256=_require_sha256(document["package_sha256"], "app package SHA-256"),
        changelog_asset=_safe_asset_name(document["changelog_asset"], "app changelog asset"),
        changelog_sha256=_require_sha256(
            document["changelog_sha256"],
            "app changelog SHA-256",
        ),
        capabilities=CapabilityEnvelope.from_payload(document["capabilities"]),
    )


def parse_launcher_manifest(
    document: Mapping[str, Any],
    *,
    public_keys: Mapping[str, str],
) -> LauncherManifest:
    verify_contract_document(document, public_keys=public_keys, expected_kind="launcher")
    return LauncherManifest(
        launcher_version=_require_semver(document["launcher_version"], "launcher version"),
        min_app_version=_require_semver(document["min_app_version"], "minimum app version"),
        runtime_contract_version=_require_positive_int(
            document["runtime_contract_version"],
            "runtime contract version",
        ),
        launcher_asset=_safe_asset_name(document["launcher_asset"], "launcher asset"),
        launcher_sha256=_require_sha256(document["launcher_sha256"], "launcher SHA-256"),
        launcher_size_bytes=_require_positive_int(document["launcher_size_bytes"], "launcher size"),
    )


def parse_terrain_manifest(
    document: Mapping[str, Any],
    *,
    public_keys: Mapping[str, str],
) -> TerrainManifest:
    verify_contract_document(document, public_keys=public_keys, expected_kind="terrain")
    files = tuple(MappingProxyType(dict(item)) for item in document["files"])
    return TerrainManifest(
        channel=_normalize_channel(document["channel"]),
        terrain_pack_id=_require_nonempty_string(document["terrain_pack_id"], "terrain pack id"),
        terrain_revision=_require_sha256(document["terrain_revision"], "terrain revision"),
        min_runtime_contract_version=_require_positive_int(
            document["min_runtime_contract_version"],
            "minimum terrain runtime contract version",
        ),
        map_count=_require_positive_int(document["map_count"], "terrain map count"),
        total_size_bytes=_require_positive_int(document["total_size_bytes"], "terrain total size"),
        files=files,
    )


def parse_terrain_catalog_contract(
    document: Mapping[str, Any],
    *,
    public_keys: Mapping[str, str],
) -> dict[str, Any]:
    """Verify a signed v2 catalog and return a terrain-store-ready snapshot.

    The returned payload deliberately excludes both the signing envelope and
    the contract ``kind`` discriminator.  Its six fields therefore match the
    public input accepted by ``terrain_store.parse_terrain_catalog`` exactly.
    """

    verify_contract_document(
        document,
        public_keys=public_keys,
        expected_kind=TERRAIN_CATALOG_CONTRACT_KIND,
    )
    payload = {
        field: document[field]
        for field in _signature_fields(TERRAIN_CATALOG_CONTRACT_KIND)
        if field != "kind"
    }
    verified_snapshot = json.loads(_canonical_json_bytes(payload))
    if not isinstance(verified_snapshot, dict):
        raise LaunchContractError("terrain catalog payload is invalid")
    return verified_snapshot


def parse_distribution_descriptor(
    document: Mapping[str, Any],
    *,
    public_keys: Mapping[str, str],
    trust: DistributionTrust | None = None,
) -> DistributionDescriptor:
    if trust is not None and dict(public_keys) != dict(trust.artifact_public_keys):
        raise LaunchContractError("distribution trust keys do not match artifact verification keys")
    verify_contract_document(document, public_keys=public_keys, expected_kind="distribution")
    descriptor = DistributionDescriptor(
        distribution_revision=_require_nonempty_string(
            document["distribution_revision"],
            "distribution revision",
        ),
        source=_require_nonempty_string(document["source"], "distribution source"),
        artifacts=tuple(_reference_from_payload(item) for item in document["artifacts"]),
    )
    if trust is not None:
        _validate_distribution_trust(descriptor, trust)
    return descriptor


def validate_descriptor_app_binding(
    descriptor: DistributionDescriptor,
    *,
    channel: str,
    manifest_document: Mapping[str, Any],
    manifest: AppManifest,
) -> None:
    """Require one descriptor reference to bind the exact signed app manifest."""

    canonical_channel = _normalize_channel(channel)
    reference = descriptor.app_reference(canonical_channel)
    if reference.manifest_sha256 != contract_document_sha256(manifest_document):
        raise LaunchContractError("distribution descriptor does not bind this app manifest")
    if manifest.channel != canonical_channel:
        raise LaunchContractError("distribution descriptor and app manifest channels differ")


def app_compatibility(
    manifest: AppManifest,
    *,
    launcher_version: str,
    runtime_contract_version: int,
) -> CompatibilityState:
    """Project a signed App floor without pretending a version is lockstep."""

    if _parse_semver(launcher_version, "current launcher version") < _parse_semver(
        manifest.min_launcher_version,
        "minimum launcher version",
    ):
        return CompatibilityState.LAUNCHER_UPDATE_REQUIRED
    if runtime_contract_version < manifest.runtime_contract_version:
        return CompatibilityState.RUNTIME_UPDATE_REQUIRED
    return CompatibilityState.COMPATIBLE


__all__ = [
    "AppManifest",
    "CONTRACT_SCHEMA_VERSION",
    "CONTRACT_SIGNATURE_ALGORITHM",
    "CONTRACT_SIGNATURE_FIELD",
    "CapabilityEnvelope",
    "CompatibilityState",
    "DistributionEnvironment",
    "DistributionDescriptor",
    "DistributionTrust",
    "DistributionTrustError",
    "KNOWN_OPTIONAL_CAPABILITIES",
    "LaunchContractError",
    "LauncherManifest",
    "ManifestReference",
    "PUBLIC_CHANNELS",
    "RELEASE_CHANNELS",
    "RUNTIME_CONTRACT_VERSION",
    "TERRAIN_CATALOG_CONTRACT_KIND",
    "TERRAIN_CATALOG_SCHEMA_VERSION",
    "TEST_DISTRIBUTION_HOST",
    "TerrainManifest",
    "app_compatibility",
    "contract_document_sha256",
    "contract_signature_payload",
    "parse_app_manifest",
    "parse_distribution_descriptor",
    "parse_launcher_manifest",
    "parse_terrain_catalog_contract",
    "parse_terrain_manifest",
    "sign_contract_document",
    "validate_descriptor_app_binding",
    "verify_contract_document",
]
