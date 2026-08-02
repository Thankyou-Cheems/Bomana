# CheemsPay Subscription Key Contract

Status: Accepted (2026-08-02)

This contract protects the trust root used to validate Bomana's offline
CheemsPay receipts. The public key is not a secret and is intentionally
versioned in `launcher/subscription_key_contract.py`; the matching private
signing key remains exclusively in CheemsPay deployment configuration.

## Invariants

- The canonical key id is `prod-2026-01`.
- The canonical public key is the value in
  `CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL` in the contract module.
- The Launcher source fallback and the generated PyInstaller module MUST use
  the same key map.
- CI's `CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL` and
  `CHEEMSPAY_LICENSE_KEY_ID` inputs are mirrors of one entry in the contract,
  not alternate sources of truth. A mismatch MUST fail the build before
  packaging. The selected entry may be a newly added key, but the primary
  entry must remain unchanged.
- The primary key id and public key MUST NOT be replaced or removed. Existing
  distributed Launchers and cached receipts depend on this trust root.

## Rotation policy

Replacement of the primary key is prohibited. If an emergency requires a new
trust root, the old key MUST remain in the key map and CheemsPay MUST continue
issuing or verifying receipts compatible with existing Launchers until their
support floor has passed. A new key may only be added under a new key id through
a separately reviewed compatibility change; it must never overwrite
`prod-2026-01`.

## Session compatibility

`StoredSubscriptionSession` deliberately stores the device seed, CheemsPay
access token, device id, and cached receipt only. It does not store a public
key or select a trust root. Therefore a normal key-contract update does not
require session migration: the same device identity and receipt continue to be
checked against the repository-owned key map. A generated package that does
not match this map fails closed at import time.
