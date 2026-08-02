# Subscription Access Contract

Prefix: `SUB-`

## Scope

This contract governs the boundary between Bomana's universal Launcher,
CheemsPay, and the subscriber-only Super Bomb release channel. It covers OAuth
device authorization, device proof, signed offline receipts, local protection,
and paid-artifact eligibility.

It does not claim that rewriting public Git history revokes licenses already
granted for earlier MIT revisions. It also does not move payment, account,
refund, or device-allowance policy into Bomana.

## Normative Clauses

- `SUB-01`: Lite and Standard MUST be usable without contacting CheemsPay.
- `SUB-02`: Enhanced MUST be treated as a Subscriber Edition even though its
  stable Release Channel name remains `Enhanced`.
- `SUB-03`: Interactive desktop login MUST use CheemsPay's OAuth device flow;
  Bomana MUST NOT collect or store the user's CheemsPay password.
- `SUB-04`: Bomana MUST register an Ed25519 device public key and prove receipt
  refresh requests with the matching private key using CheemsPay's canonical
  method/path/timestamp/body-hash payload.
- `SUB-05`: A receipt MUST fail closed unless its EdDSA signature uses a pinned
  key and its issuer, audience, `app_id`, `bomana.super_bomber` feature,
  device-key thumbprint, `exp`, `service_expires_at`, and entitlement version
  are valid.
- `SUB-06`: An offline receipt MUST NOT remain usable more than 14 days after
  issue or beyond the underlying service entitlement.
- `SUB-07`: The device seed, bearer session, device id, and receipt MUST be
  stored under the current Windows user with DPAPI protection and atomic file
  replacement. They MUST NOT be written to Launcher logs.
- `SUB-08`: The packaged Launcher MUST pin the CheemsPay license public key at
  build time; missing key material MUST fail the Launcher build.
- `SUB-08A`: The CheemsPay key id and public key MUST come from the repository-owned
  `docs/specs/subscription-key-contract.md` and
  `launcher/subscription_key_contract.py`; CI-provided copies MUST match exactly.
  A replacement or removal of the primary trust root MUST fail the build.
- `SUB-09`: The Launcher MUST re-check subscriber access before resolving or
  downloading Enhanced updates and before launching a locally selected
  Enhanced installation. A cached valid receipt may authorize offline launch.
- `SUB-10`: Client-side checks are not paid-artifact isolation. Before the first
  subscriber production release, the manifest and artifact service MUST also
  require a short-lived CheemsPay-derived artifact grant for Enhanced bytes;
  direct public Enhanced URLs or GitHub Release assets are non-compliant.
- `SUB-10A`: Every grant MUST bind one normalized logical resource and the
  registered device key. The Launcher MUST add a fresh device signature to the
  exact gateway `GET` path and MUST reject redirects while sending grant or
  device-proof headers.
- `SUB-10B`: The private boundary covers the Enhanced application manifest,
  application ZIP, changelog, terrain manifest, and each content-addressed
  terrain object. Signed release manifests and SHA256 checks remain mandatory
  after CheemsPay authorization.
- `SUB-11`: Subscription integration MUST NOT add process-memory input. Strike
  Prediction remains limited to official 8111 observations, user-selected
  configuration, bundled static data, and offline terrain.
- `SUB-12`: Public-history rewriting may occur only after the private release
  closure is independently recoverable and Lite/Standard build and launch from
  the candidate public history.

## Contract Coverage

- [behavioral] `SUB-03..SUB-08` are covered by
  `tests/test_subscription_access.py`: CheemsPay request shape, Ed25519 device
  proof, receipt rejection, exact-resource grant issuance, both adapters,
  DPAPI, atomic persistence, workflow device reuse, and signed gateway GETs.
- [behavioral] `SUB-01..SUB-02` and `SUB-09` are covered by
  `tests/test_launcher_subscription_gate.py`: public-channel bypass and
  Enhanced fail-closed refresh behavior.
- [behavioral] `SUB-08` and `SUB-08A` are covered by
  `tests/test_build_metadata.py`, `tests/test_subscription_key_contract.py`, and
  `tests/test_quality_release_workflows.py` through source/runtime parity and
  build-time trust-root pinning.
- [behavioral] `SUB-10..SUB-10B` client behavior is covered by
  `tests/test_launcher_update_service.py`: Enhanced has no public fallback,
  every private resource obtains a fresh grant, protected requests reject
  redirects, and downloaded bytes retain signature/SHA verification.
- [manual] `SUB-10..SUB-10B`: CheemsPay's artifact-grant and isolated gateway tests
  cover entitlement state, grant claims, public-key-only verification, exact
  resource matching, device proof, path containment, and HTTP byte ranges.
- [manual] `SUB-10..SUB-12` remain production release gates until the reviewed
  CheemsPay gateway is deployed, the private artifact tree is mounted, old
  public Enhanced assets/references are removed, and clean-clone checks pass.
