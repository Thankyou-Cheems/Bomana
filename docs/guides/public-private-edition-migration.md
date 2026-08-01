# Public and Subscriber Edition Migration

This runbook moves Bomana from one public MIT release closure to two product
closures:

- the public repository builds Lite and Standard;
- the private repository builds the Super Bomb Edition on the stable
  `Enhanced` Release Channel.

Rewriting the official Git history removes old subscriber implementation from
the repository's reachable history. It does not revoke rights already granted
under MIT or remove existing clones, forks, caches, or downloaded release
assets.

## Safety Order

1. Freeze new `Enhanced` publication from the public repository.
2. Record the current public HEAD, all refs, release assets, and CDN objects.
3. Create and verify a complete Git bundle outside both working copies.
4. Create a private working copy with public push disabled.
5. Configure a genuinely private remote and push the preserved refs.
6. Bring the Edition Policy and Subscription Access modules into the private
   repository.
7. Move the Super Bomb release closure using
   `docs/migration/super-bomb-closure.md`; do not rely on ZIP exclusions.
8. Build and launch Lite and Standard from a clean public candidate.
9. Build and launch Enhanced from a clean private checkout.
10. Require a short-lived CheemsPay-derived grant at the Enhanced manifest and
    artifact server; a Launcher-only check is not sufficient.
11. Create an isolated public-history candidate whose root tree contains only
    the verified public closure. Prefer a new root commit over a path-only
    rewrite because subscriber symbols currently share several source files.
12. Audit every reachable public branch and tag, GitHub Release asset, Pages
    artifact, Tencent/EdgeOne object, and configured fallback URL.
13. Present the candidate tree hash, public build evidence, private recovery
    evidence, and deletion list for final review.
14. Only after explicit approval, replace the official public refs and remove
    obsolete official Release/CDN objects.
15. Clone the rewritten public repository into a fresh directory and repeat
    the public build, launch, update, and source-content checks.

## Completed Bootstrap Receipt

- Preserved source HEAD: `8bffbb7a69e33280f45c795842e2eda71c39a53a`
- Verified bundle filename: `Bomana-pre-split-8bffbb7.bundle`
- Bundle size: `18,282,809` bytes
- Bundle SHA-256:
  `F2D20139087FA705A37B9185AECF5AC8F88DF5614BD20E44D942F4ADC5134331`

The private source is now hosted at
`https://github.com/Thankyou-Cheems/Bomana-Super-Bomb` with PRIVATE visibility;
its `main` branch contains the subscriber closure and the historical tags are
preserved there. The local bundle remains the independent recovery path.

CheemsPay commits `c892778` and `9d8c493` are pushed on branch
`codex/bomana-artifact-grants` and reviewed in draft PR 5. They provide a
five-minute resource/device-bound token plus an isolated public-key-only,
read-only artifact gateway. The Launcher now grants and device-signs every
Enhanced app/terrain resource without a public fallback. Production cutover
still requires merging and deploying that PR and mounting the private artifact
tree at the gateway.

## Public Candidate Acceptance

- The repository contains complete Lite and Standard source, tests, build
  definitions, and documentation.
- Public CI has no Enhanced build matrix entry and no Enhanced artifact upload.
- No Super Bomb implementation, model data, private test fixture, or private
  release definition is reachable from any official public ref.
- The public Launcher may retain the `Enhanced` channel identity and the
  CheemsPay client adapter, but it cannot resolve Enhanced bytes without a
  server-issued artifact grant.
- Lite and Standard neither contact CheemsPay nor require a subscription
  receipt.
- A clean clone reproduces public artifacts without reading process memory or
  any offline research workspace.

## Private Candidate Acceptance

- The private repository is independently recoverable from both its remote and
  the verified bundle.
- It owns the complete Super Bomb implementation, model data, private tests,
  build definition, manifest publication, and rollback artifacts.
- The production adapter uses CheemsPay device authorization and signed,
  device-bound receipts; the in-memory adapter exercises the same interface in
  tests.
- Enhanced manifest and artifact delivery fail closed when entitlement or the
  short-lived artifact grant is absent, expired, revoked, or mismatched.
- Production Strike Prediction consumes only official 8111 observations,
  user-selected configuration, bundled static data, and offline terrain.

## Remote Cutover Is Destructive

The final ref replacement, tag deletion, Release-asset deletion, and CDN purge
are intentionally outside this implementation branch. They require a reviewed
target list and explicit approval because they affect collaborators and public
distribution. Keep the old object inventory and bundle receipt with the private
release records after cutover.
