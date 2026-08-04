"""CheemsPay subscription boundary for the portable Launcher.

The module deliberately separates three concerns:

* CheemsPay owns interactive authorization, device registration, and receipt issue.
* Bomana verifies a pinned, device-bound receipt before granting subscriber access.
* Artifact manifests, hashes, installation, and rollback remain Launcher concerns.

No payment or account model is reproduced in Bomana.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import importlib
import json
import os
import re
import secrets
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from launcher.core import (
    ed25519_public_key_from_private_key,
    ed25519_sign,
    ed25519_verify,
)
from launcher.distribution_build import current_build_metadata
from launcher.subscription_key_contract import (
    CHEEMSPAY_LICENSE_PUBLIC_KEYS as _CONTRACT_LICENSE_KEYS,
)

CHEEMSPAY_BASE_URL = "https://pay.ruikang.wang"
CHEEMSPAY_LICENSE_ISSUER = f"{CHEEMSPAY_BASE_URL}/api/licenses"
CHEEMSPAY_CLIENT_ID = "bomana-desktop"
BOMANA_APP_ID = "bomana"
SUPER_BOMB_FEATURE = "bomana.super_bomber"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
MAX_OFFLINE_RECEIPT_AGE = timedelta(days=14)
ARTIFACT_GRANT_MAX_AGE = timedelta(minutes=5)
JWT_CLOCK_SKEW = timedelta(seconds=60)
TERRAIN_MANIFEST_RESOURCE = "terrain/terrain_manifest.json"
TERRAIN_OBJECTS_PATH = "/downloads/terrain/objects/"

_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
_MAX_JSON_BYTES = 1024 * 1024
_MAX_JWT_BYTES = 64 * 1024


def _load_pinned_license_keys() -> dict[str, str]:
    try:
        keys_module = importlib.import_module("bomana_subscription_public_keys")
    except ModuleNotFoundError as exc:
        if exc.name != "bomana_subscription_public_keys":
            raise
        return dict(_CONTRACT_LICENSE_KEYS)
    try:
        pinned_keys = dict(getattr(keys_module, "CHEEMSPAY_LICENSE_PUBLIC_KEYS", {}))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("packaged CheemsPay receipt keys are invalid") from exc
    if pinned_keys != dict(_CONTRACT_LICENSE_KEYS):
        raise RuntimeError(
            "packaged CheemsPay receipt keys do not match the repository trust contract"
        )
    return pinned_keys


_PINNED_LICENSE_KEYS = _load_pinned_license_keys()

CHEEMSPAY_LICENSE_PUBLIC_KEYS: dict[str, str] = dict(_PINNED_LICENSE_KEYS)


class SubscriptionAccessReason(StrEnum):
    ALLOWED = "allowed"
    MISSING_RECEIPT = "missing_receipt"
    INVALID_RECEIPT = "invalid_receipt"
    RECEIPT_EXPIRED = "receipt_expired"
    ENTITLEMENT_EXPIRED = "entitlement_expired"
    WRONG_DEVICE = "wrong_device"
    WRONG_APP = "wrong_app"
    MISSING_FEATURE = "missing_feature"


class DeviceAuthorizationState(StrEnum):
    APPROVED = "approved"
    PENDING = "authorization_pending"
    SLOW_DOWN = "slow_down"
    DENIED = "access_denied"
    EXPIRED = "expired_token"


class ReceiptValidationError(RuntimeError):
    """A fail-closed cached-receipt rejection."""

    def __init__(self, reason: SubscriptionAccessReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class CheemsPayApiError(RuntimeError):
    """A typed error returned by, or encountered while reaching, CheemsPay."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class DeviceCredential:
    """A local Ed25519 device identity accepted by CheemsPay."""

    private_seed: bytes = field(repr=False)
    public_key_spki: str
    key_thumbprint: str

    @classmethod
    def generate(cls) -> DeviceCredential:
        return cls.from_seed(secrets.token_bytes(32))

    @classmethod
    def from_seed(cls, seed: bytes) -> DeviceCredential:
        if len(seed) != 32:
            raise ValueError("device private seed must contain exactly 32 bytes")
        private_key = base64.b64encode(seed).decode("ascii")
        raw_public_key = base64.b64decode(
            ed25519_public_key_from_private_key(private_key),
            validate=True,
        )
        spki = _ED25519_SPKI_PREFIX + raw_public_key
        return cls(
            private_seed=bytes(seed),
            public_key_spki=_base64url_encode(spki),
            key_thumbprint=_base64url_encode(hashlib.sha256(spki).digest()),
        )

    def sign(self, message: bytes) -> str:
        private_key = base64.b64encode(self.private_seed).decode("ascii")
        return _base64url_encode(ed25519_sign(message, private_key))


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_at: datetime
    interval_seconds: int


@dataclass(frozen=True)
class AuthorizationPoll:
    state: DeviceAuthorizationState
    access_token: str = field(default="", repr=False)
    retry_after_seconds: int = 0


@dataclass(frozen=True)
class RegisteredDevice:
    device_id: str
    key_thumbprint: str


@dataclass(frozen=True)
class ArtifactGrant:
    token: str = field(repr=False)
    resource: str
    download_url: str
    expires_at: datetime
    # CheemsPay may return the current public CDN locator when the granted
    # resource is the Enhanced terrain manifest.  The grant URL itself stays
    # the private gateway URL so it remains available as a per-object fallback.
    terrain_object_base_url: str = ""


@dataclass(frozen=True)
class AuthorizedArtifactRequest:
    """A short-lived grant plus the local device proof needed to use it."""

    grant: ArtifactGrant
    credential: DeviceCredential = field(repr=False)

    @property
    def resource(self) -> str:
        return self.grant.resource

    @property
    def download_url(self) -> str:
        return self.grant.download_url

    @property
    def terrain_object_base_url(self) -> str:
        return self.grant.terrain_object_base_url

    def headers(self, *, now: datetime | None = None) -> dict[str, str]:
        current = _as_utc(now or datetime.now(UTC))
        if current >= self.grant.expires_at + JWT_CLOCK_SKEW:
            raise CheemsPayApiError(401, "ARTIFACT_GRANT_EXPIRED", "Artifact grant expired")
        path = urlparse(self.grant.download_url).path
        timestamp = _request_timestamp(current)
        signature = self.credential.sign(
            canonical_device_request(
                method="GET",
                path=path,
                timestamp=timestamp,
                raw_body=b"",
            ).encode("utf-8")
        )
        return {
            "Authorization": f"Bearer {self.grant.token}",
            "X-Device-Timestamp": timestamp,
            "X-Device-Signature": signature,
        }


@dataclass(frozen=True)
class SubscriptionReceipt:
    token: str = field(repr=False)
    subject: str
    product_id: str
    features: frozenset[str]
    device_key_thumbprint: str
    service_expires_at: datetime
    receipt_expires_at: datetime
    issued_at: datetime
    entitlement_version: int
    jti: str
    key_id: str


@dataclass(frozen=True)
class SubscriptionAccessDecision:
    allowed: bool
    reason: SubscriptionAccessReason
    receipt: SubscriptionReceipt | None = None


@dataclass(frozen=True)
class JsonHttpResponse:
    status_code: int
    payload: Mapping[str, Any]


class JsonTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonHttpResponse: ...


class SubscriptionAuthority(Protocol):
    """Port owned by the Launcher-facing subscription workflow."""

    def begin_device_authorization(self) -> DeviceAuthorization: ...

    def poll_device_authorization(self, device_code: str) -> AuthorizationPoll: ...

    def register_device(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_name: str,
    ) -> RegisteredDevice: ...

    def refresh_receipt(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_id: str,
    ) -> str: ...

    def issue_artifact_grant(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_id: str,
        resource: str,
    ) -> ArtifactGrant: ...


class UrllibJsonTransport:
    """Production HTTPS adapter with bounded JSON responses."""

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.ssl_context = ssl.create_default_context()

    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonHttpResponse:
        _require_secure_url(url)
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "Bomana-Launcher/3",
            **dict(headers or {}),
        }
        request = Request(
            url,
            data=body,
            headers=request_headers,
            method=method.upper(),
        )
        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            ) as response:
                raw = response.read(_MAX_JSON_BYTES + 1)
                status_code = int(response.status)
        except HTTPError as exc:
            raw = exc.read(_MAX_JSON_BYTES + 1)
            status_code = int(exc.code)
        except (OSError, URLError) as exc:
            raise CheemsPayApiError(0, "NETWORK_ERROR", f"CheemsPay request failed: {exc}") from exc
        if len(raw) > _MAX_JSON_BYTES:
            raise CheemsPayApiError(
                status_code, "RESPONSE_TOO_LARGE", "CheemsPay response is too large"
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CheemsPayApiError(
                status_code,
                "INVALID_RESPONSE",
                "CheemsPay returned invalid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise CheemsPayApiError(
                status_code,
                "INVALID_RESPONSE",
                "CheemsPay returned a non-object response",
            )
        return JsonHttpResponse(status_code=status_code, payload=payload)


class CheemsPaySubscriptionAuthority:
    """Production adapter for CheemsPay device authorization and receipts."""

    def __init__(
        self,
        *,
        base_url: str = CHEEMSPAY_BASE_URL,
        transport: JsonTransport | None = None,
        client_id: str = CHEEMSPAY_CLIENT_ID,
        app_id: str = BOMANA_APP_ID,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        _require_secure_url(self.base_url)
        self.transport = transport or UrllibJsonTransport()
        self.client_id = client_id
        self.app_id = app_id
        self.now = now or (lambda: datetime.now(UTC))

    def begin_device_authorization(self) -> DeviceAuthorization:
        response = self._post_json(
            "/api/auth/device/code",
            {
                "client_id": self.client_id,
                "scope": "openid profile offline_access",
            },
        )
        payload = _require_success(response)
        expires_in = _positive_int(payload.get("expires_in"), "expires_in")
        interval = _positive_int(payload.get("interval", 5), "interval")
        verification_uri = self._absolute_url(_required_string(payload, "verification_uri"))
        complete = self._absolute_url(_required_string(payload, "verification_uri_complete"))
        return DeviceAuthorization(
            device_code=_required_string(payload, "device_code"),
            user_code=_required_string(payload, "user_code"),
            verification_uri=verification_uri,
            verification_uri_complete=complete,
            expires_at=_as_utc(self.now()) + timedelta(seconds=expires_in),
            interval_seconds=interval,
        )

    def poll_device_authorization(self, device_code: str) -> AuthorizationPoll:
        response = self._post_json(
            "/api/auth/device/token",
            {
                "grant_type": DEVICE_GRANT_TYPE,
                "device_code": device_code,
                "client_id": self.client_id,
            },
        )
        if 200 <= response.status_code < 300:
            return AuthorizationPoll(
                state=DeviceAuthorizationState.APPROVED,
                access_token=_required_string(response.payload, "access_token"),
            )
        code = _response_error_code(response.payload)
        if code == DeviceAuthorizationState.PENDING:
            return AuthorizationPoll(DeviceAuthorizationState.PENDING)
        if code == DeviceAuthorizationState.SLOW_DOWN:
            return AuthorizationPoll(DeviceAuthorizationState.SLOW_DOWN, retry_after_seconds=5)
        if code == DeviceAuthorizationState.DENIED:
            return AuthorizationPoll(DeviceAuthorizationState.DENIED)
        if code == DeviceAuthorizationState.EXPIRED:
            return AuthorizationPoll(DeviceAuthorizationState.EXPIRED)
        raise _api_error(response)

    def register_device(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_name: str,
    ) -> RegisteredDevice:
        response = self._post_json(
            "/api/devices",
            {
                "appId": self.app_id,
                "name": device_name,
                "publicKeySpki": credential.public_key_spki,
            },
            access_token=access_token,
        )
        payload = _require_success(response)
        registered = RegisteredDevice(
            device_id=_required_string(payload, "deviceId"),
            key_thumbprint=_required_string(payload, "keyThumbprint"),
        )
        if not hmac.compare_digest(registered.key_thumbprint, credential.key_thumbprint):
            raise CheemsPayApiError(
                response.status_code,
                "DEVICE_KEY_MISMATCH",
                "CheemsPay registered a different device key",
            )
        return registered

    def refresh_receipt(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_id: str,
    ) -> str:
        path = "/api/licenses/refresh"
        raw_body = _json_body({"appId": self.app_id})
        response = self.transport.request_json(
            "POST",
            self._absolute_url(path),
            body=raw_body,
            headers=self._device_headers(
                access_token,
                credential,
                device_id,
                method="POST",
                path=path,
                raw_body=raw_body,
            ),
        )
        return _required_string(_require_success(response), "token")

    def issue_artifact_grant(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_id: str,
        resource: str,
    ) -> ArtifactGrant:
        normalized_resource = normalize_artifact_resource(resource)
        path = "/api/artifacts/grants"
        raw_body = _json_body(
            {
                "appId": self.app_id,
                "resource": normalized_resource,
            }
        )
        response = self.transport.request_json(
            "POST",
            self._absolute_url(path),
            body=raw_body,
            headers=self._device_headers(
                access_token,
                credential,
                device_id,
                method="POST",
                path=path,
                raw_body=raw_body,
            ),
        )
        payload = _require_success(response)
        returned_resource = normalize_artifact_resource(_required_exact_string(payload, "resource"))
        if not hmac.compare_digest(returned_resource, normalized_resource):
            raise CheemsPayApiError(
                response.status_code,
                "ARTIFACT_RESOURCE_MISMATCH",
                "CheemsPay authorized a different artifact resource",
            )
        token = _required_exact_string(payload, "token")
        if len(token.encode("utf-8")) > _MAX_JWT_BYTES:
            raise CheemsPayApiError(
                response.status_code,
                "INVALID_RESPONSE",
                "CheemsPay artifact grant is too large",
            )
        download_url = _required_exact_string(payload, "downloadUrl")
        self._require_same_origin(download_url)
        parsed_download = urlparse(download_url)
        if (
            parsed_download.query
            or parsed_download.fragment
            or not parsed_download.path.endswith(f"/{normalized_resource}")
        ):
            raise CheemsPayApiError(
                response.status_code,
                "INVALID_RESPONSE",
                "CheemsPay artifact URL does not match the authorized resource",
            )
        expires_at = _api_datetime(payload.get("expiresAt"), "expiresAt")
        current = _as_utc(self.now())
        if not current < expires_at <= current + ARTIFACT_GRANT_MAX_AGE + JWT_CLOCK_SKEW:
            raise CheemsPayApiError(
                response.status_code,
                "INVALID_RESPONSE",
                "CheemsPay artifact grant expiry is invalid",
            )
        terrain_object_base_url = _optional_terrain_object_base_url(
            payload.get("terrainObjectBaseUrl"),
            resource=normalized_resource,
        )
        return ArtifactGrant(
            token=token,
            resource=returned_resource,
            download_url=download_url,
            expires_at=expires_at,
            terrain_object_base_url=terrain_object_base_url,
        )

    def _device_headers(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_id: str,
        *,
        method: str,
        path: str,
        raw_body: bytes,
    ) -> dict[str, str]:
        timestamp = _request_timestamp(_as_utc(self.now()))
        signature = credential.sign(
            canonical_device_request(
                method=method,
                path=path,
                timestamp=timestamp,
                raw_body=raw_body,
            ).encode("utf-8")
        )
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Device-Id": device_id,
            "X-Device-Timestamp": timestamp,
            "X-Device-Signature": signature,
        }

    def _require_same_origin(self, url: str) -> None:
        _require_secure_url(url)
        expected = urlparse(self.base_url)
        actual = urlparse(url)
        if (
            actual.username
            or actual.password
            or (actual.scheme, actual.hostname, actual.port)
            != (expected.scheme, expected.hostname, expected.port)
        ):
            raise CheemsPayApiError(
                0,
                "INVALID_RESPONSE",
                "CheemsPay artifact URL must use the configured origin",
            )

    def _post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        access_token: str = "",
    ) -> JsonHttpResponse:
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return self.transport.request_json(
            "POST",
            self._absolute_url(path),
            body=_json_body(payload),
            headers=headers,
        )

    def _absolute_url(self, path: str) -> str:
        value = urljoin(f"{self.base_url}/", path.lstrip("/"))
        _require_secure_url(value)
        return value


@dataclass
class InMemorySubscriptionAuthority:
    """Deterministic adapter for workflow tests and offline demos."""

    authorization: DeviceAuthorization
    poll_results: list[AuthorizationPoll]
    registered_device: RegisteredDevice
    receipt_token: str
    artifact_grant: ArtifactGrant | None = None
    calls: list[str] = field(default_factory=list)

    def begin_device_authorization(self) -> DeviceAuthorization:
        self.calls.append("begin")
        return self.authorization

    def poll_device_authorization(self, device_code: str) -> AuthorizationPoll:
        self.calls.append(f"poll:{device_code}")
        if not self.poll_results:
            return AuthorizationPoll(DeviceAuthorizationState.PENDING)
        return self.poll_results.pop(0)

    def register_device(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_name: str,
    ) -> RegisteredDevice:
        self.calls.append(f"register:{device_name}")
        if self.registered_device.key_thumbprint != credential.key_thumbprint:
            raise CheemsPayApiError(409, "DEVICE_KEY_MISMATCH", "device key mismatch")
        return self.registered_device

    def refresh_receipt(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_id: str,
    ) -> str:
        self.calls.append(f"refresh:{device_id}")
        return self.receipt_token

    def issue_artifact_grant(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_id: str,
        resource: str,
    ) -> ArtifactGrant:
        normalized_resource = normalize_artifact_resource(resource)
        self.calls.append(f"grant:{device_id}:{normalized_resource}")
        if self.artifact_grant is None:
            raise CheemsPayApiError(404, "ARTIFACT_NOT_FOUND", "artifact grant unavailable")
        if self.artifact_grant.resource != normalized_resource:
            raise CheemsPayApiError(409, "ARTIFACT_RESOURCE_MISMATCH", "artifact mismatch")
        return self.artifact_grant


class ReceiptVerifier:
    """Verify a CheemsPay receipt using only pinned Ed25519 public keys."""

    def __init__(
        self,
        *,
        public_keys: Mapping[str, str] | None = None,
        issuer: str = CHEEMSPAY_LICENSE_ISSUER,
        audience: str = BOMANA_APP_ID,
        required_feature: str = SUPER_BOMB_FEATURE,
    ) -> None:
        self.public_keys = dict(
            CHEEMSPAY_LICENSE_PUBLIC_KEYS if public_keys is None else public_keys
        )
        self.issuer = issuer
        self.audience = audience
        self.required_feature = required_feature

    def evaluate(
        self,
        token: str,
        *,
        device_key_thumbprint: str,
        now: datetime | None = None,
    ) -> SubscriptionAccessDecision:
        if not str(token or "").strip():
            return SubscriptionAccessDecision(
                allowed=False,
                reason=SubscriptionAccessReason.MISSING_RECEIPT,
            )
        try:
            receipt = self.verify(
                token,
                device_key_thumbprint=device_key_thumbprint,
                now=now,
            )
        except ReceiptValidationError as exc:
            return SubscriptionAccessDecision(allowed=False, reason=exc.reason)
        return SubscriptionAccessDecision(
            allowed=True,
            reason=SubscriptionAccessReason.ALLOWED,
            receipt=receipt,
        )

    def verify(
        self,
        token: str,
        *,
        device_key_thumbprint: str,
        now: datetime | None = None,
    ) -> SubscriptionReceipt:
        encoded = str(token or "").strip()
        if not encoded or len(encoded.encode("utf-8")) > _MAX_JWT_BYTES:
            self._reject(SubscriptionAccessReason.INVALID_RECEIPT, "receipt size is invalid")
        parts = encoded.split(".")
        if len(parts) != 3:
            self._reject(SubscriptionAccessReason.INVALID_RECEIPT, "receipt is not a JWT")
        header = _decode_json_segment(parts[0], "receipt header")
        claims = _decode_json_segment(parts[1], "receipt claims")
        if header.get("alg") != "EdDSA" or header.get("typ") != "JWT":
            self._reject(SubscriptionAccessReason.INVALID_RECEIPT, "receipt algorithm is invalid")
        key_id = _required_claim_string(header, "kid", self._reject)
        encoded_key = str(self.public_keys.get(key_id, "")).strip()
        if not encoded_key:
            self._reject(SubscriptionAccessReason.INVALID_RECEIPT, "receipt key is not pinned")
        public_key = _ed25519_public_key_from_spki(encoded_key)
        signature = _base64url_decode(parts[2], "receipt signature")
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        if not ed25519_verify(signing_input, signature, public_key):
            self._reject(SubscriptionAccessReason.INVALID_RECEIPT, "receipt signature is invalid")

        current = _as_utc(now or datetime.now(UTC))
        issuer = _required_claim_string(claims, "iss", self._reject)
        if issuer != self.issuer:
            self._reject(SubscriptionAccessReason.INVALID_RECEIPT, "receipt issuer is invalid")
        if self.audience not in _audiences(claims.get("aud")):
            self._reject(SubscriptionAccessReason.INVALID_RECEIPT, "receipt audience is invalid")
        if _required_claim_string(claims, "app_id", self._reject) != self.audience:
            self._reject(SubscriptionAccessReason.WRONG_APP, "receipt belongs to another app")

        issued_at = _numeric_date(claims.get("iat"), "iat", self._reject)
        expires_at = _numeric_date(claims.get("exp"), "exp", self._reject)
        if issued_at > current + JWT_CLOCK_SKEW:
            self._reject(
                SubscriptionAccessReason.INVALID_RECEIPT, "receipt is issued in the future"
            )
        if current >= expires_at + JWT_CLOCK_SKEW:
            self._reject(SubscriptionAccessReason.RECEIPT_EXPIRED, "receipt has expired")
        if expires_at <= issued_at:
            self._reject(SubscriptionAccessReason.INVALID_RECEIPT, "receipt dates are inverted")
        if expires_at - issued_at > MAX_OFFLINE_RECEIPT_AGE + JWT_CLOCK_SKEW:
            self._reject(SubscriptionAccessReason.INVALID_RECEIPT, "offline receipt is too long")

        service_expires_at = _iso_datetime(
            claims.get("service_expires_at"),
            "service_expires_at",
            self._reject,
        )
        if current >= service_expires_at:
            self._reject(
                SubscriptionAccessReason.ENTITLEMENT_EXPIRED,
                "subscription entitlement has expired",
            )
        if expires_at > service_expires_at + JWT_CLOCK_SKEW:
            self._reject(
                SubscriptionAccessReason.INVALID_RECEIPT,
                "receipt outlives the subscription entitlement",
            )

        thumbprint = _required_claim_string(
            claims,
            "device_key_thumbprint",
            self._reject,
        )
        if not hmac.compare_digest(thumbprint, str(device_key_thumbprint or "")):
            self._reject(SubscriptionAccessReason.WRONG_DEVICE, "receipt belongs to another device")
        features = _string_set(claims.get("features"), "features", self._reject)
        if self.required_feature not in features:
            self._reject(
                SubscriptionAccessReason.MISSING_FEATURE,
                "receipt does not grant Super Bomb access",
            )
        entitlement_version = _non_negative_int(
            claims.get("entitlement_version"),
            "entitlement_version",
            self._reject,
        )
        return SubscriptionReceipt(
            token=encoded,
            subject=_required_claim_string(claims, "sub", self._reject),
            product_id=_required_claim_string(claims, "product_id", self._reject),
            features=features,
            device_key_thumbprint=thumbprint,
            service_expires_at=service_expires_at,
            receipt_expires_at=expires_at,
            issued_at=issued_at,
            entitlement_version=entitlement_version,
            jti=_required_claim_string(claims, "jti", self._reject),
            key_id=key_id,
        )

    @staticmethod
    def _reject(reason: SubscriptionAccessReason, message: str) -> None:
        raise ReceiptValidationError(reason, message)


def canonical_device_request(
    *,
    method: str,
    path: str,
    timestamp: str,
    raw_body: bytes,
) -> str:
    """Match CheemsPay's canonical device-proof request byte-for-byte."""

    return "\n".join(
        (
            method.upper(),
            path,
            timestamp,
            hashlib.sha256(raw_body).hexdigest(),
        )
    )


def normalize_artifact_resource(value: str) -> str:
    """Validate the shared CheemsPay logical-resource grammar without rewriting it."""

    resource = str(value or "")
    segments = resource.split("/")
    if (
        not resource
        or resource != resource.strip()
        or len(resource) > 240
        or resource.startswith("/")
        or resource.endswith("/")
        or "\\" in resource
        or "//" in resource
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", resource) is None
        or any(segment in {"", ".", ".."} for segment in segments)
    ):
        raise ValueError("artifact resource must be a normalized logical path")
    return resource


def validate_license_public_key(encoded_key: str) -> None:
    """Fail unless a build-time key is a raw or SPKI-wrapped Ed25519 key."""

    _ed25519_public_key_from_spki(encoded_key)


def _require_secure_url(url: str) -> None:
    parsed = urlparse(str(url or ""))
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if not parsed.hostname or (
        parsed.scheme != "https" and not (parsed.scheme == "http" and loopback)
    ):
        raise ValueError("CheemsPay URL must use HTTPS (HTTP is allowed only on loopback)")


def _optional_terrain_object_base_url(value: object, *, resource: str) -> str:
    """Validate the CDN locator carried by a terrain-manifest grant response.

    The locator is control-plane metadata, not a bearer credential.  It must
    therefore stay on the build's configured CDN origin and immutable terrain
    object path, without URL decoration.  An omitted locator is accepted for
    older CheemsPay servers; callers retain the private grant gateway as the
    compatibility path.
    """

    if value is None or value == "":
        return ""
    if resource != TERRAIN_MANIFEST_RESOURCE:
        raise CheemsPayApiError(
            0,
            "INVALID_RESPONSE",
            "CheemsPay returned a terrain CDN locator for a non-terrain resource",
        )
    if not isinstance(value, str) or not value or value != value.strip():
        raise CheemsPayApiError(
            0,
            "INVALID_RESPONSE",
            "CheemsPay terrain CDN locator is invalid",
        )
    parsed = urlparse(value)
    configured_host = urlparse(current_build_metadata().base_url).hostname
    configured_hosts = {configured_host.casefold()} if configured_host else set()
    extra_hosts = {
        part.strip().casefold()
        for part in os.environ.get("BOMANA_TERRAIN_CDN_ALLOWED_HOSTS", "").split(",")
        if part.strip()
    }
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise CheemsPayApiError(
            0,
            "INVALID_RESPONSE",
            "CheemsPay terrain CDN locator is outside the configured CDN path",
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.casefold() not in configured_hosts | extra_hosts
        or parsed_port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith(TERRAIN_OBJECTS_PATH)
        or not value.endswith("/")
    ):
        raise CheemsPayApiError(
            0,
            "INVALID_RESPONSE",
            "CheemsPay terrain CDN locator is outside the configured CDN path",
        )
    return value


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _request_timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _api_datetime(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise CheemsPayApiError(0, "INVALID_RESPONSE", f"CheemsPay {name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CheemsPayApiError(
            0,
            "INVALID_RESPONSE",
            f"CheemsPay {name} is invalid",
        ) from exc
    if parsed.tzinfo is None:
        raise CheemsPayApiError(0, "INVALID_RESPONSE", f"CheemsPay {name} has no timezone")
    return _as_utc(parsed)


def _api_error(response: JsonHttpResponse) -> CheemsPayApiError:
    nested = response.payload.get("error")
    nested_error = nested if isinstance(nested, Mapping) else {}
    code = _response_error_code(response.payload) or "HTTP_ERROR"
    message = str(
        nested_error.get("message")
        or response.payload.get("message")
        or response.payload.get("error_description")
        or f"CheemsPay request failed with HTTP {response.status_code}"
    )
    return CheemsPayApiError(response.status_code, code, message)


def _response_error_code(payload: Mapping[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, Mapping):
        return str(error.get("code") or "").strip()
    return str(error or payload.get("code") or "").strip()


def _require_success(response: JsonHttpResponse) -> Mapping[str, Any]:
    if not 200 <= response.status_code < 300:
        raise _api_error(response)
    return response.payload


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise CheemsPayApiError(0, "INVALID_RESPONSE", f"CheemsPay response is missing {name}")
    return value.strip()


def _required_exact_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise CheemsPayApiError(0, "INVALID_RESPONSE", f"CheemsPay response is missing {name}")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise CheemsPayApiError(0, "INVALID_RESPONSE", f"CheemsPay {name} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CheemsPayApiError(0, "INVALID_RESPONSE", f"CheemsPay {name} is invalid") from exc
    if result <= 0:
        raise CheemsPayApiError(0, "INVALID_RESPONSE", f"CheemsPay {name} is invalid")
    return result


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str, label: str) -> bytes:
    raw = str(value or "").strip()
    if not raw:
        raise ReceiptValidationError(SubscriptionAccessReason.INVALID_RECEIPT, f"{label} is empty")
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ReceiptValidationError(
            SubscriptionAccessReason.INVALID_RECEIPT,
            f"{label} is not base64url",
        ) from exc


def _decode_json_segment(value: str, label: str) -> dict[str, Any]:
    raw = _base64url_decode(value, label)
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptValidationError(
            SubscriptionAccessReason.INVALID_RECEIPT,
            f"{label} is not valid JSON",
        ) from exc
    if not isinstance(result, dict):
        raise ReceiptValidationError(
            SubscriptionAccessReason.INVALID_RECEIPT,
            f"{label} is not an object",
        )
    return result


def _ed25519_public_key_from_spki(encoded_key: str) -> bytes:
    der = _base64url_decode(encoded_key, "license public key")
    if len(der) == 32:
        return der
    if not der.startswith(_ED25519_SPKI_PREFIX) or len(der) != len(_ED25519_SPKI_PREFIX) + 32:
        raise ReceiptValidationError(
            SubscriptionAccessReason.INVALID_RECEIPT,
            "license public key is not Ed25519 SPKI",
        )
    return der[len(_ED25519_SPKI_PREFIX) :]


def _required_claim_string(
    claims: Mapping[str, Any],
    name: str,
    reject: Callable[[SubscriptionAccessReason, str], None],
) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        reject(SubscriptionAccessReason.INVALID_RECEIPT, f"receipt claim {name} is invalid")
    return value.strip()


def _audiences(value: Any) -> frozenset[str]:
    if isinstance(value, str) and value:
        return frozenset({value})
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return frozenset(value)
    return frozenset()


def _numeric_date(
    value: Any,
    name: str,
    reject: Callable[[SubscriptionAccessReason, str], None],
) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reject(SubscriptionAccessReason.INVALID_RECEIPT, f"receipt claim {name} is invalid")
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ReceiptValidationError(
            SubscriptionAccessReason.INVALID_RECEIPT,
            f"receipt claim {name} is invalid",
        ) from exc


def _iso_datetime(
    value: Any,
    name: str,
    reject: Callable[[SubscriptionAccessReason, str], None],
) -> datetime:
    if not isinstance(value, str) or not value.strip():
        reject(SubscriptionAccessReason.INVALID_RECEIPT, f"receipt claim {name} is invalid")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReceiptValidationError(
            SubscriptionAccessReason.INVALID_RECEIPT,
            f"receipt claim {name} is invalid",
        ) from exc
    if parsed.tzinfo is None:
        reject(SubscriptionAccessReason.INVALID_RECEIPT, f"receipt claim {name} has no timezone")
    return _as_utc(parsed)


def _string_set(
    value: Any,
    name: str,
    reject: Callable[[SubscriptionAccessReason, str], None],
) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        reject(SubscriptionAccessReason.INVALID_RECEIPT, f"receipt claim {name} is invalid")
    return frozenset(value)


def _non_negative_int(
    value: Any,
    name: str,
    reject: Callable[[SubscriptionAccessReason, str], None],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        reject(SubscriptionAccessReason.INVALID_RECEIPT, f"receipt claim {name} is invalid")
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "ARTIFACT_GRANT_MAX_AGE",
    "ArtifactGrant",
    "AuthorizationPoll",
    "AuthorizedArtifactRequest",
    "BOMANA_APP_ID",
    "CHEEMSPAY_BASE_URL",
    "CHEEMSPAY_CLIENT_ID",
    "CHEEMSPAY_LICENSE_ISSUER",
    "CHEEMSPAY_LICENSE_PUBLIC_KEYS",
    "CheemsPayApiError",
    "CheemsPaySubscriptionAuthority",
    "DeviceAuthorization",
    "DeviceAuthorizationState",
    "DeviceCredential",
    "InMemorySubscriptionAuthority",
    "JsonHttpResponse",
    "JsonTransport",
    "ReceiptValidationError",
    "ReceiptVerifier",
    "RegisteredDevice",
    "SUPER_BOMB_FEATURE",
    "SubscriptionAccessDecision",
    "SubscriptionAccessReason",
    "SubscriptionAuthority",
    "SubscriptionReceipt",
    "UrllibJsonTransport",
    "canonical_device_request",
    "normalize_artifact_resource",
    "validate_license_public_key",
]
