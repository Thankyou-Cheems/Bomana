# App And Launcher Version Compatibility Spec

Status: Draft
Owner: Bomana maintainers
Prefix: `COMPAT-`

## Scope

This spec governs strict App/Launcher version parsing, packaged App launcher
identity, installed and staged App validation, online install, local import,
rollback, and incomplete-install recovery for the App 8 / Launcher 3 boundary.

## Non-goals

- This spec does not change Ed25519 signing, update-service internals, or
  release deployment ordering; those remain governed by the release-signing
  contract.
- It does not authorize importing or executing untrusted staged package code to
  discover a version.
- It does not make version identity a substitute for release signature or
  package SHA256 verification.

## Normative Clauses

- `COMPAT-01`: `bomana_version.py` MUST be the single production parser and
  comparator used for every App/Launcher compatibility decision in this scope.
- `COMPAT-02`: The shared parser MUST accept only an ASCII string matching
  `^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$` and MUST
  reject booleans, numbers, whitespace, signs, leading zeroes, missing or extra
  components, and prerelease/build suffixes.
- `COMPAT-03`: Packaged App identity, installed launch, verified online install,
  local import, rollback, and incomplete-install recovery MUST all pass their
  version strings through the shared strict boundary before compatibility use.
- `COMPAT-04`: The App compatibility floor MUST be exactly `8.0.0`, and the
  Launcher compatibility floor MUST be exactly `3.0.0`.
- `COMPAT-05`: App `8.0.0` and newer MUST reject a launcher identity below
  the shared `3.0.0` protocol floor. Each packaged App release MUST additionally
  carry and enforce its own release-specific Launcher floor before runtime
  imports; managed App `8.7.17` requires Launcher `3.4.0`.
- `COMPAT-06`: Launcher `3.0.0` and newer MUST reject an App identity below
  `8.0.0` on every Launcher-owned candidate path.
- `COMPAT-07`: Launcher bootstrap MUST supply its own strict version through
  `BOMANA_LAUNCHER_VERSION` immediately before entering the App and MUST NOT
  derive that identity from installed App files or persisted launcher state.
- `COMPAT-08`: `Bomana.pyw` MUST validate the launcher identity before importing
  or initializing diagnostics, Tk, GameLogic, App runtime services, Web
  listeners, or any other runtime component.
- `COMPAT-09`: The only missing-launcher-identity exception MUST require both
  `BOMANA_SOURCE_DEVELOPMENT=1` and an explicitly non-frozen process.
- `COMPAT-10`: A frozen process MUST reject a missing, malformed, or below-floor
  launcher identity even when `BOMANA_SOURCE_DEVELOPMENT=1` is present.
- `COMPAT-11`: Launcher candidate inspection MUST read App version metadata as
  data without importing or executing staged, installed, previous, or recovery
  App Python code.
- `COMPAT-12`: A malformed or below-floor candidate MUST fail before any valid
  installation directory is renamed, replaced, deleted, or swapped.
- `COMPAT-13`: Online install MUST verify the signed App manifest under
  the release-signing verify-before-trust contract before parsing or comparing `app_version` or
  `min_launcher_version`.
- `COMPAT-14`: Online install MUST require the strict version inside the staged
  App package to equal the already-verified signed manifest `app_version`
  exactly before replacement.
- `COMPAT-15`: Local ZIP import MUST validate the staged package's strict App
  version, `8.0.0` floor, and literal `PORTABLE_MIN_LAUNCHER_VERSION` before
  replacement without treating ZIP filenames as version identity or executing
  candidate code.
- `COMPAT-16`: Rollback MUST validate the previous slot's strict App version and
  `8.0.0` floor before any current/previous slot swap.
- `COMPAT-17`: Incomplete-install recovery MUST validate every candidate slot's
  strict App version and `8.0.0` floor before promoting it into the current App
  slot.
- `COMPAT-18`: Installed-App launch MUST validate the selected installation's
  strict App version, `8.0.0` floor, and release-specific Launcher floor before
  Launcher bootstrap enters it.
- `COMPAT-19`: A compatibility rejection MUST preserve every pre-existing valid
  App slot and surface a stable user-visible reason naming malformed identity,
  below-floor App, below-floor Launcher, or signed/staged version mismatch. The
  final Launcher-to-App handoff MUST surface any new recovery rejection that
  appeared after the Launcher window was rendered, synchronously before App
  entry; a separately validated valid current App MAY continue afterward.
- `COMPAT-20`: The App release manifest MUST use `schema_version: 2` and retain
  the exact App signed field set from the release-signing contract, including
  its signed changelog asset and SHA256. It MUST NOT add a compatibility field
  beyond `min_launcher_version` to either signed payload or manifest schema.
- `COMPAT-21`: A Launcher below the signed `min_launcher_version` MUST disable
  the App update action and MUST reject a direct download request before any App
  package bytes are fetched.
- `COMPAT-22`: `bomana/metadata.py` and the App-carried
  `bomana_version.py` boundary MUST declare the same release-specific Launcher
  floor. This redundancy is intentional: candidate inspection reads metadata
  as data, while an App copied around Launcher-owned installation paths still
  rejects an old `BOMANA_LAUNCHER_VERSION` before runtime initialization.
- `COMPAT-23`: Missing per-release metadata MAY use the shared `3.0.0` floor
  only for compatibility with older App 8 packages. A present malformed,
  below-protocol, or above-current Launcher requirement MUST fail closed.
- `COMPAT-24`: The public introduction-site hostname MUST NOT be part of the
  Launcher update contract. App, Launcher, and terrain discovery/downloads
  MUST continue to use the dedicated `bomanaupdate.ruikang.wang` origin when
  the introduction site moves from `ruikang.wang/bomana` to
  `bomana.ruikang.wang`.
- `COMPAT-25`: The introduction site MUST obtain normal browser-visible
  release metadata from its same-origin deployed `download-catalog.json` and
  MUST remain usable without cross-origin API permission. The former
  `/bomana` page and asset paths SHOULD remain as path-preserving permanent
  redirects to the canonical hostname.
- `COMPAT-26`: The missing-Launcher exception for the standalone green
  distribution MUST require both the exact build-injected `green` distribution
  identity and a frozen process. A non-frozen source run or managed frozen App
  MUST NOT use this exception. Public CI MUST assemble this distribution from
  the Lite feature profile only.
- `COMPAT-27`: Managed App current, previous, backup, and staging directories
  MUST be isolated under `app_channels/<channel>/` for each of `Lite`,
  `Standard`, and `Enhanced`. Launcher startup MUST recover every channel and
  safely migrate a legacy marked slot before selecting the requested channel;
  an unmarked legacy slot MAY remain available only through the compatibility
  fallback and MUST NOT be copied into a named channel.
- `COMPAT-28`: The first public App manifest that uses the channel-slot layout
  MUST set `min_launcher_version` to the released Launcher `3.4.0` (or a newer
  strict version). A Launcher below that floor MUST be able to resolve and
  install the signed Launcher update, but MUST disable App download and reject
  direct App installation before fetching package bytes. The public update
  service continues to serve the signed manifest; the client-side floor is the
  compatibility gate.

## Contract Coverage

- [behavioral] `tests/contracts/test_version_compatibility.py` enforces
  `COMPAT-01..COMPAT-04`, `COMPAT-07..COMPAT-13`, `COMPAT-17`, `COMPAT-20`, and
  `COMPAT-22`, and `COMPAT-26` with strict-parser adversarial cases, early App identity order,
  shared-call-site scans, data-only candidate inspection, all-slot recovery
  prevalidation, release-floor agreement, and unchanged manifest
  schema/signed-field assertions.
- [behavioral] `tests/test_launcher_launch_flow.py` enforces `COMPAT-03..COMPAT-08`,
  `COMPAT-10..COMPAT-12`, `COMPAT-18`, and `COMPAT-19` with installed launch and
  bootstrap identity cases plus initial and final-handoff user-visible recovery
  rejection propagation.
- [behavioral] `tests/test_launcher_update_service.py` enforces
  `COMPAT-03..COMPAT-06` and `COMPAT-11..COMPAT-19` with verified-online,
  signed/staged mismatch, local import, rollback, recovery, and valid-slot
  preservation cases, plus `COMPAT-21..COMPAT-23` with pre-network and local ZIP
  rejection, and `COMPAT-27..COMPAT-28` with independent channel slots,
  marked legacy migration, and cross-channel package rejection.
- [behavioral] `tests/test_launcher_core.py` enforces `COMPAT-02`, `COMPAT-03`,
  `COMPAT-11..COMPAT-17`, and `COMPAT-19` with package metadata extraction and
  install-transaction preflight failures.
- [behavioral] `tests/test_build_metadata.py` enforces `COMPAT-04..COMPAT-07`,
  `COMPAT-13`, `COMPAT-14`, and `COMPAT-20` through App/Launcher metadata,
  package-manifest agreement, and schema/signature fields.
- [manual] Packaged Launcher smoke confirms `COMPAT-07..COMPAT-10`,
  `COMPAT-18`, and `COMPAT-19` before release without claiming that source-mode
  tests prove the frozen initialization boundary.
- [behavioral] Packaged Lite green smoke confirms `COMPAT-26` by checking the
  bundled Python/native runtime and keeping the frozen executable alive through
  startup without a Launcher identity.
- [static] `tests/test_docs_site.py` enforces `COMPAT-24` and `COMPAT-25` by
  pinning the independent update origin, canonical site hostname, same-origin
  catalog loading, and deployment default. The path-preserving redirect itself
  remains an infrastructure smoke check documented in
  `docs/guides/public-site-cutover.md`.
