# App And Launcher Version Compatibility Spec

Status: Draft
Owner: Bomana maintainers
Prefix: `COMPAT-`

## Scope

This spec governs strict App/Launcher version parsing, packaged App launcher
identity, installed and staged App validation, online install, local import,
rollback, and incomplete-install recovery for the App 8 / Launcher 3 boundary.

## Non-goals

- This spec does not change release-manifest schema version 1, Ed25519 signing,
  signed field sets, update-service internals, or release deployment ordering.
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
  `3.0.0`.
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
  version and `8.0.0` floor before replacement without treating ZIP filenames
  as version identity.
- `COMPAT-16`: Rollback MUST validate the previous slot's strict App version and
  `8.0.0` floor before any current/previous slot swap.
- `COMPAT-17`: Incomplete-install recovery MUST validate every candidate slot's
  strict App version and `8.0.0` floor before promoting it into the current App
  slot.
- `COMPAT-18`: Installed-App launch MUST validate the selected installation's
  strict App version and `8.0.0` floor before Launcher bootstrap enters it.
- `COMPAT-19`: A compatibility rejection MUST preserve every pre-existing valid
  App slot and surface a stable user-visible reason naming malformed identity,
  below-floor App, below-floor Launcher, or signed/staged version mismatch. The
  final Launcher-to-App handoff MUST surface any new recovery rejection that
  appeared after the Launcher window was rendered, synchronously before App
  entry; a separately validated valid current App MAY continue afterward.
- `COMPAT-20`: This boundary MUST retain manifest `schema_version: 1` and the
  exact App and Launcher signed field sets in the release-signing contract; it MUST NOT add a
  compatibility field to either signed payload or manifest schema.

## Contract Coverage

- [behavioral] `tests/contracts/test_version_compatibility.py` enforces
  `COMPAT-01..COMPAT-04`, `COMPAT-07..COMPAT-13`, `COMPAT-17`, and `COMPAT-20`
  with strict-parser adversarial cases, early App identity order,
  shared-call-site scans, data-only candidate inspection, all-slot recovery
  prevalidation, and unchanged manifest schema/signed-field assertions.
- [behavioral] `tests/test_launcher_launch_flow.py` enforces `COMPAT-03..COMPAT-08`,
  `COMPAT-10..COMPAT-12`, `COMPAT-18`, and `COMPAT-19` with installed launch and
  bootstrap identity cases plus initial and final-handoff user-visible recovery
  rejection propagation.
- [behavioral] `tests/test_launcher_update_service.py` enforces
  `COMPAT-03..COMPAT-06` and `COMPAT-11..COMPAT-19` with verified-online,
  signed/staged mismatch, local import, rollback, recovery, and valid-slot
  preservation cases.
- [behavioral] `tests/test_launcher_core.py` enforces `COMPAT-02`, `COMPAT-03`,
  `COMPAT-11..COMPAT-17`, and `COMPAT-19` with package metadata extraction and
  install-transaction preflight failures.
- [behavioral] `tests/test_build_metadata.py` enforces `COMPAT-04..COMPAT-07`,
  `COMPAT-13`, `COMPAT-14`, and `COMPAT-20` through App/Launcher metadata,
  package-manifest agreement, and unchanged schema/signature fields.
- [manual] Packaged Launcher smoke confirms `COMPAT-07..COMPAT-10`,
  `COMPAT-18`, and `COMPAT-19` before release without claiming that source-mode
  tests prove the frozen initialization boundary.
