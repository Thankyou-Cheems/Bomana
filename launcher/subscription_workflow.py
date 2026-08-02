"""Application service coordinating CheemsPay with local subscription state."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from launcher.subscription_access import (
    AuthorizationPoll,
    AuthorizedArtifactRequest,
    CheemsPayApiError,
    DeviceAuthorization,
    DeviceCredential,
    ReceiptValidationError,
    ReceiptVerifier,
    SubscriptionAccessDecision,
    SubscriptionAccessReason,
    SubscriptionAuthority,
)
from launcher.subscription_store import (
    StoredSubscriptionSession,
    SubscriptionSessionStore,
)


class SubscriptionWorkflow:
    """Own the login-to-receipt workflow without owning payment or entitlement rules."""

    def __init__(
        self,
        *,
        authority: SubscriptionAuthority,
        verifier: ReceiptVerifier,
        store: SubscriptionSessionStore,
    ) -> None:
        self.authority = authority
        self.verifier = verifier
        self.store = store

    def cached_access(self, *, now: datetime | None = None) -> SubscriptionAccessDecision:
        try:
            session = self.store.load()
        except RuntimeError:
            return SubscriptionAccessDecision(
                allowed=False,
                reason=SubscriptionAccessReason.INVALID_RECEIPT,
            )
        if session is None:
            return SubscriptionAccessDecision(
                allowed=False,
                reason=SubscriptionAccessReason.MISSING_RECEIPT,
            )
        credential = DeviceCredential.from_seed(session.private_seed)
        return self.verifier.evaluate(
            session.receipt_token,
            device_key_thumbprint=credential.key_thumbprint,
            now=now,
        )

    def begin_device_authorization(self) -> DeviceAuthorization:
        return self.authority.begin_device_authorization()

    def poll_device_authorization(self, device_code: str) -> AuthorizationPoll:
        return self.authority.poll_device_authorization(device_code)

    def activate_authorized_session(
        self,
        access_token: str,
        *,
        device_name: str,
        now: datetime | None = None,
    ) -> SubscriptionAccessDecision:
        session = self.store.load()
        if session is None:
            credential = DeviceCredential.generate()
            session = StoredSubscriptionSession(
                private_seed=credential.private_seed,
                access_token=access_token,
            )
        else:
            credential = DeviceCredential.from_seed(session.private_seed)
            session = replace(session, access_token=access_token, receipt_token="")

        # Re-register on every interactive login.  This is idempotent for an
        # active device, while allowing account switches and recovery after a
        # user deleted the cached device from CheemsPay.
        try:
            registered = self.authority.register_device(
                access_token,
                credential,
                device_name,
            )
        except CheemsPayApiError as exc:
            if exc.code != "DEVICE_KEY_UNAVAILABLE":
                raise
            # A disabled device key cannot be resurrected.  Start a fresh
            # device identity and register it under the newly authorized user.
            credential = DeviceCredential.generate()
            session = StoredSubscriptionSession(
                private_seed=credential.private_seed,
                access_token=access_token,
            )
            registered = self.authority.register_device(
                access_token,
                credential,
                device_name,
            )

        session = replace(session, device_id=registered.device_id)
        self.store.save(session)

        return self._refresh(session, credential=credential, now=now)

    def refresh_cached_receipt(
        self,
        *,
        now: datetime | None = None,
    ) -> SubscriptionAccessDecision:
        session = self.store.load()
        if session is None or not session.access_token or not session.device_id:
            return SubscriptionAccessDecision(
                allowed=False,
                reason=SubscriptionAccessReason.MISSING_RECEIPT,
            )
        return self._refresh(
            session,
            credential=DeviceCredential.from_seed(session.private_seed),
            now=now,
        )

    def clear(self) -> None:
        self.store.clear()

    def authorize_artifact(
        self,
        resource: str,
        *,
        now: datetime | None = None,
    ) -> AuthorizedArtifactRequest:
        session = self.store.load()
        if session is None or not session.access_token or not session.device_id:
            raise ReceiptValidationError(
                SubscriptionAccessReason.MISSING_RECEIPT,
                "CheemsPay subscription session is incomplete",
            )
        credential = DeviceCredential.from_seed(session.private_seed)
        decision = self.verifier.evaluate(
            session.receipt_token,
            device_key_thumbprint=credential.key_thumbprint,
            now=now,
        )
        if not decision.allowed:
            decision = self._refresh(session, credential=credential, now=now)
        if not decision.allowed:
            raise ReceiptValidationError(
                decision.reason,
                "CheemsPay subscription receipt does not authorize artifacts",
            )
        grant = self.authority.issue_artifact_grant(
            session.access_token,
            credential,
            session.device_id,
            resource,
        )
        return AuthorizedArtifactRequest(grant=grant, credential=credential)

    def _refresh(
        self,
        session: StoredSubscriptionSession,
        *,
        credential: DeviceCredential,
        now: datetime | None,
    ) -> SubscriptionAccessDecision:
        receipt_token = self.authority.refresh_receipt(
            session.access_token,
            credential,
            session.device_id,
        )
        try:
            receipt = self.verifier.verify(
                receipt_token,
                device_key_thumbprint=credential.key_thumbprint,
                now=now,
            )
        except ReceiptValidationError as exc:
            self.store.save(replace(session, receipt_token=""))
            return SubscriptionAccessDecision(
                allowed=False,
                reason=exc.reason,
            )
        self.store.save(replace(session, receipt_token=receipt_token))
        return SubscriptionAccessDecision(
            allowed=True,
            reason=SubscriptionAccessReason.ALLOWED,
            receipt=receipt,
        )


__all__ = ["SubscriptionWorkflow"]
