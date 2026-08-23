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

## [8.7.15]

### Added

- The strike encyclopedia now includes an exact weapon-count calculator for
  ordinary HE bombs. Counts use the desktop `gameparams` HP-to-TNT coefficient
  (`1 kg TNT = 8 mission HP`) and `explosive.blkx` strength equivalents.
- High-tier air EC bases: Mk 83 needs 12 bombs to destroy and 11 to trigger
  the 90% fire tail; Mk 82 is 28 / 25; FAB-500M-62 is 10 / 9.

### Fixed

- Corrected the north-up handedness of encyclopedia airport diagrams so module
  left/right matches the navigation map.

### Boundaries

- Napalm weapons such as Mk 77 stay unlabeled; the calculator does not invent a
  TNT count for them.
- The official Wiki "about six Mk 83" note remains historical guidance and is
  not the live formula.
- Standard, Lite, and the Lite green bundle include the encyclopedia and
  calculator. They still omit CCRP, strike solving, and Web Cockpit.

## [8.7.14]

### Added

- Added the source-backed strike encyclopedia to Standard, Lite, and the Lite
  green bundle. Users can open it from the main window or system tray.
- Generated four airport diagrams from bundled `start/end/width` geometry
  instead of copying a community image. The diagrams are explicitly labeled
  as offline planar module geometry, not server hitboxes.
- Published six EC balance-level durability bands, raw explosive fields, and
  separate official Wiki TNTe references without inventing an HP-to-TNT
  conversion.

### Boundaries

- Public packages include only the read-only encyclopedia, its static airport
  catalog, and UI. They still exclude CCRP, weapon solvers, rigid-body data,
  terrain packs, and the Web cockpit.

## [8.7.2]

### Changed

- Refreshed the public IAS/Mach speed-limit asset from
  `War-Thunder-Datamine` `2.57.1.65` (`f05f050e0631`), adding newly present
  aircraft mappings and limits.
- Normalized both `fm/...` and legacy `/fm/...` references in the extractor and
  runtime, so French F-16/Tornado variants resolve their shared flight model.
- Kept the public closure limited to `fm_speed_limits.json`; the offline bomb
  catalog remains subscriber-only.

## Launcher 3.4.4

- 并行下载订阅地形对象，减少 67 张地图首次安装时的串行等待。
- 保留逐对象断点续传、SHA256 校验和失败回滚边界。

## Launcher 3.4.5

- 修复 Windows 单文件启动器自更新后重启时复用旧 PyInstaller 临时环境，导致
  `python314.dll` 无法加载的问题。
- 重启子进程前显式重置 PyInstaller 解包环境，保留手动启动时相同的干净加载路径。

## Launcher 3.4.6

- 修复切换 CheemsPay 账户或在网页端删除设备后重新授权时复用失效设备
  `device_id`，导致本地提示没有可用 entitlement 的问题。
- 交互式授权现在会幂等重注册设备；若旧设备 key 已停用，则自动轮换本机设备身份。

## Launcher 3.4.3

### Changed

- Rotated the release manifest signing key after the previous private key was
  unavailable. New launchers trust both the active key and the previous public
  key so already-installed public App packages remain updateable.
- Because the old private key cannot sign the migration package, installing
  Launcher 3.4.3 once is required; later Launcher updates resume normally.

## Launcher 3.4.2

### Fixed

- Fixed the Windows self-update handoff so the PowerShell replacement script
  actually executes after the current launcher exits.

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
