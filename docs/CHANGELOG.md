# Changelog

User-visible release notes are published with each signed release. This file
tracks the public/private architecture transition without reproducing private
implementation history.

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
