from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from launcher.core import ed25519_public_key_from_private_key, ed25519_sign, ed25519_verify
from launcher.subscription_access import (
    ArtifactGrant,
    AuthorizationPoll,
    CheemsPayApiError,
    CheemsPaySubscriptionAuthority,
    DeviceAuthorization,
    DeviceAuthorizationState,
    DeviceCredential,
    InMemorySubscriptionAuthority,
    JsonHttpResponse,
    ReceiptVerifier,
    RegisteredDevice,
    SubscriptionAccessReason,
    canonical_device_request,
    normalize_artifact_resource,
)
from launcher.subscription_store import (
    FileSubscriptionSessionStore,
    InMemorySubscriptionSessionStore,
    StoredSubscriptionSession,
    WindowsDpapiProtector,
)
from launcher.subscription_workflow import SubscriptionWorkflow

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
LICENSE_SEED = bytes(range(32))
DEVICE_SEED = bytes(range(32, 64))
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def license_key() -> tuple[str, str]:
    private_key = base64.b64encode(LICENSE_SEED).decode("ascii")
    raw_public = base64.b64decode(
        ed25519_public_key_from_private_key(private_key),
        validate=True,
    )
    return private_key, b64url(SPKI_PREFIX + raw_public)


def issue_receipt(
    credential: DeviceCredential,
    *,
    now: datetime = NOW,
    expires_in: timedelta = timedelta(days=7),
    service_expires_in: timedelta = timedelta(days=30),
    features: list[str] | None = None,
    app_id: str = "bomana",
) -> tuple[str, dict[str, Any]]:
    private_key, _public_key = license_key()
    header = {"alg": "EdDSA", "kid": "test-license", "typ": "JWT"}
    claims = {
        "iss": "https://pay.ruikang.wang/api/licenses",
        "aud": "bomana",
        "sub": "user-1",
        "jti": "receipt-1",
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
        "app_id": app_id,
        "product_id": "super-bomber-365",
        "features": features if features is not None else ["bomana.super_bomber"],
        "device_key_thumbprint": credential.key_thumbprint,
        "service_expires_at": (now + service_expires_in).isoformat().replace("+00:00", "Z"),
        "entitlement_version": 4,
    }
    encoded_header = b64url(
        json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    encoded_claims = b64url(
        json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = b64url(ed25519_sign(signing_input, private_key))
    return f"{encoded_header}.{encoded_claims}.{signature}", claims


def verifier() -> ReceiptVerifier:
    _private_key, public_key = license_key()
    return ReceiptVerifier(public_keys={"test-license": public_key})


def test_valid_device_bound_receipt_grants_super_bomb_access() -> None:
    credential = DeviceCredential.from_seed(DEVICE_SEED)
    token, _claims = issue_receipt(credential)

    decision = verifier().evaluate(
        token,
        device_key_thumbprint=credential.key_thumbprint,
        now=NOW,
    )

    assert decision.allowed
    assert decision.reason is SubscriptionAccessReason.ALLOWED
    assert decision.receipt is not None
    assert decision.receipt.product_id == "super-bomber-365"
    assert decision.receipt.entitlement_version == 4
    assert decision.receipt.features == {"bomana.super_bomber"}


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"device": "another-device"}, SubscriptionAccessReason.WRONG_DEVICE),
        ({"features": ["bomana.standard"]}, SubscriptionAccessReason.MISSING_FEATURE),
        ({"app_id": "another-app"}, SubscriptionAccessReason.WRONG_APP),
        ({"expires_in": timedelta(days=-1)}, SubscriptionAccessReason.RECEIPT_EXPIRED),
        (
            {"service_expires_in": timedelta(seconds=-1)},
            SubscriptionAccessReason.ENTITLEMENT_EXPIRED,
        ),
    ],
)
def test_receipt_rejections_are_typed(
    mutation: dict[str, Any],
    expected: SubscriptionAccessReason,
) -> None:
    credential = DeviceCredential.from_seed(DEVICE_SEED)
    token, _claims = issue_receipt(
        credential,
        features=mutation.get("features"),
        app_id=mutation.get("app_id", "bomana"),
        expires_in=mutation.get("expires_in", timedelta(days=7)),
        service_expires_in=mutation.get("service_expires_in", timedelta(days=30)),
    )

    decision = verifier().evaluate(
        token,
        device_key_thumbprint=mutation.get("device", credential.key_thumbprint),
        now=NOW,
    )

    assert not decision.allowed
    assert decision.reason is expected


def test_receipt_rejects_signature_tampering_and_excessive_offline_age() -> None:
    credential = DeviceCredential.from_seed(DEVICE_SEED)
    token, _claims = issue_receipt(credential)
    changed = token[:-1] + ("A" if token[-1] != "A" else "B")
    tampered = verifier().evaluate(
        changed,
        device_key_thumbprint=credential.key_thumbprint,
        now=NOW,
    )
    overlong_token, _claims = issue_receipt(credential, expires_in=timedelta(days=15))
    overlong = verifier().evaluate(
        overlong_token,
        device_key_thumbprint=credential.key_thumbprint,
        now=NOW,
    )

    assert tampered.reason is SubscriptionAccessReason.INVALID_RECEIPT
    assert overlong.reason is SubscriptionAccessReason.INVALID_RECEIPT


def test_device_credential_matches_cheemspay_spki_and_request_signature() -> None:
    credential = DeviceCredential.from_seed(DEVICE_SEED)
    spki = base64.urlsafe_b64decode(credential.public_key_spki + "==")
    raw_public = spki[len(SPKI_PREFIX) :]
    raw_body = b'{"appId":"bomana"}'
    canonical = canonical_device_request(
        method="post",
        path="/api/licenses/refresh",
        timestamp="2026-08-01T12:00:00.000Z",
        raw_body=raw_body,
    )
    signature = base64.urlsafe_b64decode(credential.sign(canonical.encode("utf-8")) + "==")

    assert spki.startswith(SPKI_PREFIX)
    assert credential.key_thumbprint == b64url(hashlib.sha256(spki).digest())
    assert canonical == (
        "POST\n/api/licenses/refresh\n2026-08-01T12:00:00.000Z\n"
        f"{hashlib.sha256(raw_body).hexdigest()}"
    )
    assert ed25519_verify(canonical.encode("utf-8"), signature, raw_public)


@dataclass
class FakeTransport:
    responses: list[JsonHttpResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> JsonHttpResponse:
        self.calls.append({"method": method, "url": url, "body": body, "headers": headers})
        return self.responses.pop(0)


def test_cheemspay_adapter_runs_device_flow_and_signs_receipt_refresh() -> None:
    credential = DeviceCredential.from_seed(DEVICE_SEED)
    transport = FakeTransport(
        responses=[
            JsonHttpResponse(
                200,
                {
                    "device_code": "device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "/device",
                    "verification_uri_complete": "/device?user_code=ABCD-EFGH",
                    "expires_in": 1800,
                    "interval": 5,
                },
            ),
            JsonHttpResponse(400, {"error": "authorization_pending"}),
            JsonHttpResponse(200, {"access_token": "access-token"}),
            JsonHttpResponse(
                201,
                {"deviceId": "device-1", "keyThumbprint": credential.key_thumbprint},
            ),
            JsonHttpResponse(200, {"token": "header.payload.signature"}),
        ]
    )
    authority = CheemsPaySubscriptionAuthority(
        base_url="https://pay.ruikang.wang",
        transport=transport,
        now=lambda: NOW,
    )

    authorization = authority.begin_device_authorization()
    pending = authority.poll_device_authorization(authorization.device_code)
    approved = authority.poll_device_authorization(authorization.device_code)
    registered = authority.register_device(
        approved.access_token,
        credential,
        "Test PC",
    )
    receipt = authority.refresh_receipt(
        approved.access_token,
        credential,
        registered.device_id,
    )

    assert authorization.verification_uri == "https://pay.ruikang.wang/device"
    assert pending.state is DeviceAuthorizationState.PENDING
    assert approved.state is DeviceAuthorizationState.APPROVED
    assert receipt == "header.payload.signature"
    refresh_call = transport.calls[-1]
    assert refresh_call["body"] == b'{"appId":"bomana"}'
    assert refresh_call["headers"]["Authorization"] == "Bearer access-token"
    assert refresh_call["headers"]["X-Device-Id"] == "device-1"
    canonical = canonical_device_request(
        method="POST",
        path="/api/licenses/refresh",
        timestamp=refresh_call["headers"]["X-Device-Timestamp"],
        raw_body=refresh_call["body"],
    )
    signature = base64.urlsafe_b64decode(refresh_call["headers"]["X-Device-Signature"] + "==")
    spki = base64.urlsafe_b64decode(credential.public_key_spki + "==")
    assert ed25519_verify(canonical.encode("utf-8"), signature, spki[len(SPKI_PREFIX) :])


def test_cheemspay_adapter_issues_exact_device_bound_artifact_grant() -> None:
    credential = DeviceCredential.from_seed(DEVICE_SEED)
    resource = "releases/enhanced/manifest_Enhanced.json"
    transport = FakeTransport(
        responses=[
            JsonHttpResponse(
                200,
                {
                    "token": "header.payload.signature",
                    "resource": resource,
                    "downloadUrl": f"https://pay.ruikang.wang/subscriber-artifacts/{resource}",
                    "expiresAt": (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                },
            )
        ]
    )
    authority = CheemsPaySubscriptionAuthority(
        base_url="https://pay.ruikang.wang",
        transport=transport,
        now=lambda: NOW,
    )

    grant = authority.issue_artifact_grant(
        "access-token",
        credential,
        "device-1",
        resource,
    )

    assert grant.resource == resource
    assert grant.download_url.endswith(resource)
    call = transport.calls[-1]
    assert call["body"] == (
        b'{"appId":"bomana","resource":"releases/enhanced/manifest_Enhanced.json"}'
    )
    canonical = canonical_device_request(
        method="POST",
        path="/api/artifacts/grants",
        timestamp=call["headers"]["X-Device-Timestamp"],
        raw_body=call["body"],
    )
    signature = base64.urlsafe_b64decode(call["headers"]["X-Device-Signature"] + "==")
    spki = base64.urlsafe_b64decode(credential.public_key_spki + "==")
    assert ed25519_verify(canonical.encode("utf-8"), signature, spki[len(SPKI_PREFIX) :])


@pytest.mark.parametrize(
    "resource",
    [
        " releases/enhanced/app.zip",
        "releases/enhanced/app.zip ",
        "releases//enhanced/app.zip",
        "releases/../app.zip",
        "https://example.test/app.zip",
    ],
)
def test_artifact_resource_grammar_fails_closed(resource: str) -> None:
    with pytest.raises(ValueError, match="normalized logical path"):
        normalize_artifact_resource(resource)


def test_in_memory_authority_is_a_complete_second_adapter() -> None:
    credential = DeviceCredential.from_seed(DEVICE_SEED)
    authorization = DeviceAuthorization(
        device_code="code",
        user_code="USER-CODE",
        verification_uri="https://example.test/device",
        verification_uri_complete="https://example.test/device?user_code=USER-CODE",
        expires_at=NOW + timedelta(minutes=30),
        interval_seconds=5,
    )
    adapter = InMemorySubscriptionAuthority(
        authorization=authorization,
        poll_results=[AuthorizationPoll(DeviceAuthorizationState.APPROVED, "access")],
        registered_device=RegisteredDevice("device-id", credential.key_thumbprint),
        receipt_token="receipt",
        artifact_grant=ArtifactGrant(
            token="grant",
            resource="releases/enhanced/manifest_Enhanced.json",
            download_url=(
                "https://pay.ruikang.wang/subscriber-artifacts/"
                "releases/enhanced/manifest_Enhanced.json"
            ),
            expires_at=NOW + timedelta(minutes=5),
        ),
    )

    assert adapter.begin_device_authorization() is authorization
    poll = adapter.poll_device_authorization("code")
    registered = adapter.register_device("access", credential, "PC")
    assert adapter.refresh_receipt("access", credential, registered.device_id) == "receipt"
    grant = adapter.issue_artifact_grant(
        "access",
        credential,
        registered.device_id,
        "releases/enhanced/manifest_Enhanced.json",
    )
    assert poll.state is DeviceAuthorizationState.APPROVED
    assert grant.token == "grant"
    assert adapter.calls == [
        "begin",
        "poll:code",
        "register:PC",
        "refresh:device-id",
        "grant:device-id:releases/enhanced/manifest_Enhanced.json",
    ]


def test_non_loopback_http_cheemspay_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        CheemsPaySubscriptionAuthority(base_url="http://pay.example.test")


class XorProtector:
    def protect(self, plaintext: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in plaintext)

    def unprotect(self, ciphertext: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in ciphertext)


def test_file_session_store_round_trips_without_plaintext_secrets(tmp_path) -> None:
    path = tmp_path / "subscription.dat"
    store = FileSubscriptionSessionStore(path, XorProtector())
    session = StoredSubscriptionSession(
        private_seed=DEVICE_SEED,
        access_token="access-secret",
        device_id="device-id",
        receipt_token="receipt-secret",
    )

    store.save(session)
    stored_bytes = path.read_bytes()

    assert b"access-secret" not in stored_bytes
    assert b"receipt-secret" not in stored_bytes
    assert store.load() == session
    store.clear()
    assert store.load() is None


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI is platform-specific")
def test_windows_dpapi_round_trip_uses_current_user_scope() -> None:
    protector = WindowsDpapiProtector()
    plaintext = b"Bomana subscription test secret"

    ciphertext = protector.protect(plaintext)

    assert ciphertext != plaintext
    assert plaintext not in ciphertext
    assert protector.unprotect(ciphertext) == plaintext


def test_subscription_workflow_preserves_device_identity_and_caches_verified_receipt() -> None:
    credential = DeviceCredential.from_seed(DEVICE_SEED)
    receipt_token, _claims = issue_receipt(credential)
    store = InMemorySubscriptionSessionStore(StoredSubscriptionSession(private_seed=DEVICE_SEED))
    authorization = DeviceAuthorization(
        device_code="code",
        user_code="USER-CODE",
        verification_uri="https://example.test/device",
        verification_uri_complete="https://example.test/device?user_code=USER-CODE",
        expires_at=NOW + timedelta(minutes=30),
        interval_seconds=5,
    )
    authority = InMemorySubscriptionAuthority(
        authorization=authorization,
        poll_results=[],
        registered_device=RegisteredDevice("device-id", credential.key_thumbprint),
        receipt_token=receipt_token,
        artifact_grant=ArtifactGrant(
            token="artifact-grant",
            resource="releases/enhanced/manifest_Enhanced.json",
            download_url=(
                "https://pay.ruikang.wang/subscriber-artifacts/"
                "releases/enhanced/manifest_Enhanced.json"
            ),
            expires_at=NOW + timedelta(minutes=5),
        ),
    )
    workflow = SubscriptionWorkflow(
        authority=authority,
        verifier=verifier(),
        store=store,
    )

    activated = workflow.activate_authorized_session(
        "access-token",
        device_name="Test PC",
        now=NOW,
    )
    cached = workflow.cached_access(now=NOW)
    refreshed = workflow.refresh_cached_receipt(now=NOW)
    artifact = workflow.authorize_artifact(
        "releases/enhanced/manifest_Enhanced.json",
        now=NOW,
    )

    assert activated.allowed and cached.allowed and refreshed.allowed
    assert store.session is not None
    assert store.session.private_seed == DEVICE_SEED
    assert store.session.device_id == "device-id"
    assert store.session.receipt_token == receipt_token
    headers = artifact.headers(now=NOW)
    assert headers["Authorization"] == "Bearer artifact-grant"
    artifact_canonical = canonical_device_request(
        method="GET",
        path="/subscriber-artifacts/releases/enhanced/manifest_Enhanced.json",
        timestamp=headers["X-Device-Timestamp"],
        raw_body=b"",
    )
    artifact_signature = base64.urlsafe_b64decode(headers["X-Device-Signature"] + "==")
    spki = base64.urlsafe_b64decode(credential.public_key_spki + "==")
    assert ed25519_verify(
        artifact_canonical.encode("utf-8"),
        artifact_signature,
        spki[len(SPKI_PREFIX) :],
    )
    assert authority.calls == [
        "register:Test PC",
        "refresh:device-id",
        "refresh:device-id",
        "grant:device-id:releases/enhanced/manifest_Enhanced.json",
    ]


def test_subscription_workflow_re_registers_cached_device_on_interactive_login() -> None:
    credential = DeviceCredential.from_seed(DEVICE_SEED)
    receipt_token, _claims = issue_receipt(credential)
    store = InMemorySubscriptionSessionStore(
        StoredSubscriptionSession(
            private_seed=DEVICE_SEED,
            access_token="old-access-token",
            device_id="cached-device",
            receipt_token="old-receipt",
        )
    )
    authority = InMemorySubscriptionAuthority(
        authorization=DeviceAuthorization(
            device_code="code",
            user_code="USER-CODE",
            verification_uri="https://example.test/device",
            verification_uri_complete="https://example.test/device?user_code=USER-CODE",
            expires_at=NOW + timedelta(minutes=30),
            interval_seconds=5,
        ),
        poll_results=[],
        registered_device=RegisteredDevice("fresh-device", credential.key_thumbprint),
        receipt_token=receipt_token,
    )
    workflow = SubscriptionWorkflow(
        authority=authority,
        verifier=verifier(),
        store=store,
    )

    decision = workflow.activate_authorized_session(
        "new-access-token",
        device_name="Test PC",
        now=NOW,
    )

    assert decision.allowed
    assert store.session is not None
    assert store.session.device_id == "fresh-device"
    assert store.session.receipt_token == receipt_token
    assert authority.calls == ["register:Test PC", "refresh:fresh-device"]


class RebindingAuthority:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_next_registration = True
        self.credential: DeviceCredential | None = None

    def register_device(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_name: str,
    ) -> RegisteredDevice:
        del access_token
        self.calls.append(f"register:{device_name}")
        if self.fail_next_registration:
            self.fail_next_registration = False
            raise CheemsPayApiError(
                409,
                "DEVICE_KEY_UNAVAILABLE",
                "cached device key is unavailable",
            )
        self.credential = credential
        return RegisteredDevice("rotated-device", credential.key_thumbprint)

    def refresh_receipt(
        self,
        access_token: str,
        credential: DeviceCredential,
        device_id: str,
    ) -> str:
        del access_token, device_id
        self.calls.append(f"refresh:{credential.key_thumbprint}")
        assert self.credential is credential
        return issue_receipt(credential)[0]


def test_subscription_workflow_rotates_disabled_device_key() -> None:
    store = InMemorySubscriptionSessionStore(
        StoredSubscriptionSession(
            private_seed=DEVICE_SEED,
            device_id="disabled-device",
            receipt_token="old-receipt",
        )
    )
    authority = RebindingAuthority()
    workflow = SubscriptionWorkflow(
        authority=authority,
        verifier=verifier(),
        store=store,
    )

    decision = workflow.activate_authorized_session(
        "new-access-token",
        device_name="Test PC",
        now=NOW,
    )

    assert decision.allowed
    assert store.session is not None
    assert store.session.device_id == "rotated-device"
    assert store.session.private_seed != DEVICE_SEED
    assert authority.calls[0] == "register:Test PC"
    assert authority.calls[1].startswith("register:Test PC")
    assert authority.calls[2].startswith("refresh:")
