# Changelog

User-visible release notes are published with each signed release. This file
tracks the public/private architecture transition without reproducing private
implementation history.

## Unreleased

### Fixed

- Versioned the CheemsPay receipt public key as a repository-owned trust root.
  Launcher builds now fail if CI supplies a different key id or public key, and
  packaged runtime keys are checked against the same contract so existing
  subscription sessions are not blocked by an accidental key replacement.

## Launcher 3.5.2

### Fixed

- Refresh the persisted CheemsPay receipt when authorization completes so the
  Enhanced channel becomes available immediately without restarting Launcher.

## Launcher 3.5.1

### Fixed

- Added visible purchase/trial and authorization actions to the default public
  channel so users can complete CheemsPay device authorization before switching
  to Enhanced.

## [8.7.3]

### Changed

- Reissued the public App packages under the Launcher 3.5.0 compatibility
  floor and the new vNext artifact signing root.
- Kept Enhanced and terrain delivery outside the public App package boundary.

## Launcher 3.5.0

### Changed

- Started the vNext release boundary with the Grill-approved signing root
  `bomana-release-2026-08-v2`; the retired `bomana-release-2026-08` and
  `bomana-release-2026-06` roots are no
  longer trusted or carried into new Launcher packages.
- Retired the legacy cross-root self-update path. Users install Launcher 3.5.0
  manually once, after which normal self-update remains available within the
  vNext signing root.

## Launcher 3.4.2

### Changed

- Terrain Catalog map entries now carry signed Chinese display names. The
  Launcher reads the catalog name first and keeps the bundled table only as a
  fallback for legacy catalogs, so later map renames and additions do not
  require another Launcher upgrade.

## Launcher 3.4.1

### Fixed

- Standard and Lite startup now silently ignore saved Super Bomb-only Web
  cockpit preferences instead of interrupting launch with a warning.
- Updated the pinned CheemsPay production receipt key used by the packaged
  launcher so approved device authorizations are accepted again.

### Changed

- Regenerated the bundled CJK UI font subset from the current launcher text.

## Launcher 3.4.0

### Changed

- Isolated managed App current/previous/backup/staging slots per `Lite`,
  `Standard`, and `Enhanced` channel, with safe migration of marked legacy
  installs. Updating one channel no longer overwrites another channel's
  rollback point.
- Raised the public App download floor to Launcher 3.4.0. Older Launchers can
  still self-update, but cannot download or install an App package until that
  self-update completes.
- Added a `官网预览` action that opens `https://bomana.ruikang.wang/` for a
  browser preview of the paid edition.

## Launcher 3.3.2

### Changed

- Added a direct `购买 / 试用` action to the public Launcher. It opens the
  production CheemsPay storefront where the current one-year authorization and
  three-day trial are managed, then lets the user refresh the device-bound
  receipt after payment.

## [8.7.1]

### Changed

- Republished the public Lite and Standard packages after the Launcher 3.4.0
  channel-slot migration. This patch release keeps the package URL immutable
  while raising the signed App download floor to Launcher 3.4.0.

## [8.7.0]

### Added

- Added a Lite-only green ZIP that bundles Python 3.14 and all runtime
  dependencies. It runs directly after extraction and does not require the
  Bomana Launcher.
- Added a green-build daily-active report using the existing anonymous
  `version_check` event. It succeeds at most once per UTC day and can be
  disabled with `BOMANA_DISABLE_DAU=1` or `~/.bomana_disable_dau`.

### Changed

- Moved all green-build filesystem and network reporting work onto a daemon
  thread. Reporting timeout, endpoint failure, state corruption, and thread
  startup failure cannot reject or delay the main UI startup path.
- Extended public release CI, checksums, artifact attestations, documentation,
  and package closure tests to cover Standard, managed Lite, and green Lite.
- Bumped the Launcher artifact to 3.3.1 so the current binary uses a new,
  immutable download URL instead of replacing the previously published 3.3.0
  bytes. App 8.7.0 originally kept 3.3.0 as its minimum compatible Launcher
  floor; the 3.4.0 release raises that floor for the channel-slot migration.
- Launcher-only tags no longer replace the latest application Release, keeping
  the stable `releases/latest` green-download URL on the full public release.

## [8.6.2]

### Changed

- Defined Lite and Standard as the only public MIT App editions.
- Reserved the stable `Enhanced` channel for the paid Super Bomb subscription.
- Centralized edition identity, access class, feature policy, and public build
  eligibility in one module.
- Added a CheemsPay device-authorization client, pinned subscription-receipt
  verification, and Windows DPAPI persistence to the universal Launcher.
- Changed public App CI and packaging to build Standard and Lite only.
- Replaced direct subscriber imports with an optional Strike Prediction port.
- Reduced tests to public behavior, integration contracts, release integrity,
  and final artifact closure.

### Removed from the public closure

- Super Bomb prediction/model implementation and private data catalogs.
- Offline terrain payload generation and subscriber-only deployment paths.
- Web Cockpit implementation and assets.
- Private calibration/extraction tools, behavior tests, schemas, and detailed
  implementation documentation.

### Required before production cutover

- Configure the pinned CheemsPay receipt-verification public key in Launcher CI.
- Provision a private source remote and private CI for `Enhanced`.
- Require a short-lived artifact grant on both the private manifest and artifact
  download endpoints.
- Validate clean-checkout Lite, Standard, Launcher, and private Enhanced
  artifacts before changing public Git history or live release routes.

Earlier releases remain subject to the license and release notes that
accompanied those revisions.
