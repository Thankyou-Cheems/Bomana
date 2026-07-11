# Project Architecture (Bomana)

## Overview
- Bootstrap entry point: `Bomana.pyw` (early Launcher identity boundary, then single-instance guard, DPI setup, root window creation, `App` startup)
- Shared compatibility boundary: `bomana_version.py` (strict App/Launcher `X.Y.Z` parsing, floors, exact signed/staged version agreement, and explicit non-frozen source-development exception)
- Portable launcher: `launcher.pyw` (modern card-based UI, startup auto-check, Tencent CDN-first downloads with GitHub fallback, app/launcher split updates, one-version rollback retention, loopback Web startup preferences, ordinary-integrity offline launch, details/support dialog)
- Launcher package: `launcher/` (manifest verification/projection, download cache pathing, install transactions, app bootstrap helpers, launcher metadata)
- Launcher pure helpers: `launcher/core.py` (download-source normalization, version/asset helpers, checksum and safe zip extraction)
- Project metadata: `bomana/metadata.py` (version, repository, launcher compatibility metadata)
- Central config: `bomana/config/` (explicit feature flag, settings, and static-data submodules)
- Core logic: `bomana/core/` (state, telemetry, ballistics, game logic)
- UI components: `bomana/ui/` (app coordinator, main-window builder, debug support, panel renderer, widgets, dialogs, nav window)
- Utilities: `bomana/utils/` (system, math, file, sound helpers)
- Privileged hotkeys: `bomana/utils/hotkey_broker.py` (ordinary-first game-elevation probe plus IPC/UAC client) and `native/hotkey_broker/` (bundled zero-install fixed-action native broker)
- Bundled UI assets: `bomana/assets/` (private UI font subsets + PNG icon assets)
- External data: `bomana/data/ccrp_bomb_params.json` (CCRP bomb parameters)
- External data: `bomana/data/weapon_fire_control.json` (Datamine-backed aircraft weapon catalog, compatibility, and solver inputs)
- External data: `bomana/data/fm_speed_limits.json` (机型 IAS/Mach 限速库)
- Tools: `tools/update_datamine_assets.py` (refresh generated datamine assets)
- Tools: `tools/blkx_extractor.py` / `tools/weapon_fire_control_extractor.py` / `tools/fm_speed_extractor.py` (single-asset extractors)
- Tools: `tools/datamine_utils.py` (shared datamine source-dir and metadata helpers)
- Tools: `tools/create_version_info.py`, `tools/sample_8111_attitude.py`, and
  `tools/record_8111_session.py` / `tools/replay_8111_session.py` (build
  metadata, diagnostics, and official 8111 session capture/replay)
- Branding assets: `bomana/assets/branding/` (`app.ico`, `app.png`, sponsor images)

## Spec Anchors
- Runtime 8111 boundary: `docs/specs/runtime-8111-boundary.md`
- Release signing and Tencent/EdgeOne deployment: `docs/specs/release-signing.md`
- Tk threading and UI dispatch: `docs/specs/threading-ui-contract.md`
- Privileged hotkey broker: `docs/specs/startup-elevation.md`
- UI presenter boundaries: `docs/specs/ui-presenter-boundary.md`
- Config variants and `ENABLE_*` precedence: `docs/specs/config-variants.md`
- Test layers and quality gates: `docs/specs/testing-quality-gates.md`
- Weapon catalog, selection, solver, and compact presentation: `docs/specs/weapon-fire-control.md`
- Shared navigation markers, close semantics, and action affordances: `docs/specs/navigation-cues.md`
- Local/LAN Web Cockpit, snapshot filtering, pairing, and HTTP lifecycle: `docs/specs/web-dashboard.md`
- App 8 / Launcher 3 identity, candidate, and recovery boundary: `docs/specs/version-compatibility.md`

## Repository Layout
```
.
├─ Bomana.pyw                # Thin bootstrap entrypoint
├─ bomana_version.py         # Shared strict App/Launcher compatibility boundary
├─ launcher.pyw              # Green launcher distribution/PyInstaller entrypoint
├─ launcher/
│  ├─ metadata.py            # Launcher version source for build/deploy tooling
│  ├─ core.py                # Pure launcher helpers used by launcher.pyw
│  ├─ manifest_sources.py    # Verified manifest projection helpers
│  ├─ verify.py              # Verify-before-trust helper boundary
│  ├─ download_cache.py      # Download directory fallback and cache naming
│  ├─ install_txn.py         # Install/rollback transaction primitives
│  └─ bootstrap.py           # App-package import isolation and launch helpers
├─ bomana/
│  ├─ config/                # Package marker plus explicit feature/settings/static-data submodules
│  ├─ metadata.py            # Project metadata and version constants
│  ├─ data/
│  │  ├─ ccrp_bomb_params.json # Bomb parameters (CCRP)
│  │  ├─ weapon_fire_control.json # Aircraft weapon catalog + compatibility + solver inputs
│  │  └─ fm_speed_limits.json # Aircraft speed limits (IAS/Mach)
│  ├─ assets/
│  │  ├─ branding/             # App icon, promo image, sponsor image
│  │  ├─ fonts/                # Private Bomana UI Sans font subsets + OFL license
│  │  ├─ icons/                # PNG icon assets used instead of emoji glyphs
│  │  └─ web/                  # Self-hosted Web Cockpit HTML/CSS/JS/SVG assets
│  ├─ core/
│  │  ├─ ballistics.py        # Bombing ballistics
│  │  ├─ ccrp_scheduler.py    # CCRP input gating, calculation, and result storage helpers
│  │  ├─ diagnostics.py       # Endpoint diagnostic counters and log throttling
│  │  ├─ lifecycle.py         # Life/reset/landing state transitions
│  │  ├─ logic.py             # GameLogic core loop
│  │  ├─ navigation.py        # Navigation scale, bearing, and distance helpers
│  │  ├─ overspeed.py         # Aircraft speed-limit matching + alert grading
│  │  ├─ state.py             # Dataclasses/enums
│  │  ├─ timing_store.py      # Battle-scoped timer signature helpers
│  │  ├─ weapon_catalog.py    # Schema-backed weapon catalog and manual selection
│  │  ├─ weapon_scheduler.py  # Lock-safe weapon-solution scheduling
│  │  ├─ weapon_envelope.py   # Pure Datamine condition-table interpolation
│  │  ├─ weapon_solver.py     # Conditional AAM/AGM references + powered/guided fallbacks
│  │  └─ telemetry.py         # 8111 fetchers
│  ├─ ui/
│  │  ├─ app.py               # App coordinator (window lifecycle + main UI loop)
│  │  ├─ debug_support.py     # Debug mock snapshot + debug panel helpers
│  │  ├─ dialogs.py           # Settings/About/etc dialogs
│  │  ├─ settings_form.py     # Headless settings dialog value collection/validation/payload helpers
│  │  ├─ hud_overlay.py       # Fullscreen HUD overlay runtime
│  │  ├─ icon_assets.py       # Bundled PNG icon loader/cache
│  │  ├─ main_window.py       # Stable main-window skeleton/card layout builder
│  │  ├─ nav_window.py        # Standalone navigation window
│  │  ├─ navigation_runtime.py # Standalone nav lifecycle + display rebuild service
│  │  ├─ dialog_presenter.py # Headless settings dialog option/summary view models
│  │  ├─ hud_presenter.py    # Headless HUD target/standby view models
│  │  ├─ navigation_presenter.py # Shared heading-tape target selection/model helpers
│  │  ├─ panel_presenter.py  # Headless fuel/bombing/speed panel view models
│  │  ├─ panel_renderer.py    # Zone/fuel/bombing/speed panel rendering helpers
│  │  ├─ runtime.py           # Tk dispatch + runtime worker thread helpers
│  │  ├─ runtime_services.py  # Global hotkeys, tray, and HUD runtime integrations
│  │  ├─ settings_runtime.py  # SettingsDialog persistence-success runtime side effects
│  │  ├─ snapshot_presenter.py # Headless lifecycle/status presentation model helpers
│  │  ├─ text_utils.py        # Shared Tk text measurement, wrapping, and elision helpers
│  │  ├─ theme.py             # Runtime Tk theme tokens
│  │  ├─ tk_style.py          # Shared Tk palette/action-button styling tokens
│  │  ├─ window_geometry.py   # Headless snap-anchor geometry helpers used by App
│  │  └─ widgets.py           # Pill/HeadingTape widgets
│  ├─ web/
│  │  ├─ server.py            # Listeners, scoped sessions, write security, and async completion
│  │  ├─ control.py           # Schema-backed semantic commands and immutable control projection
│  │  └─ snapshot.py          # Schema-backed, read-only UISnapshot projection
│  └─ utils/
│     ├─ hotkey_broker.py    # Minimal game elevation probe, bundled broker hash lock, UAC/IPC client
│     ├─ diagnostics.py      # Structured async diagnostics logging
│     ├─ file_utils.py        # Config/state/resource helpers
│     ├─ math_utils.py        # Navigation/math helpers
│     ├─ sound.py             # Sound manager
│     └─ system.py            # Windows/system helpers
├─ native/
│  └─ hotkey_broker/          # Optional elevated fixed-action RegisterHotKey runtime (Rust)
├─ docs/                       # GitHub Pages + architecture/changelog/privacy/contributing docs
├─ tools/
│  ├─ build_portable.py      # Build launcher/app package/manifest
│  ├─ create_version_info.py # Windows version-info helper for packaging
│  ├─ blkx_extractor.py      # .blkx -> bomana/data/ccrp_bomb_params.json generator
│  ├─ datamine_utils.py      # Shared datamine directory + source metadata helpers
│  ├─ fm_speed_extractor.py  # .blkx -> fm_speed_limits.json generator
│  ├─ weapon_fire_control_extractor.py # Datamine reference graph -> weapon catalog
│  ├─ generate_ui_assets.py  # Noto Sans SC subset + PNG icon asset generator
│  ├─ update_datamine_assets.py # One command to refresh generated data assets
│  ├─ sample_8111_attitude.py # HUD baseline sampler
│  ├─ record_8111_session.py  # Gzip JSONL capture of official 8111 session payloads
│  ├─ replay_8111_session.py  # Validated virtual-time replay through production GameLogic
│  ├─ session_8111.py         # Shared schema validation and completed-session loader
│  ├─ scripts/               # Local build helper scripts (bat/sh)
└─ README.md                 # Main landing page for GitHub visitors
```

Note: the self-hosted update/statistics service was moved out of this repo; see the README section about `bomana-worker` for the current service repository.

## Runtime Data Flow
1. 8111 API polling via `requests` to `localhost:8111`.
2. State judgement using config classes (Game/Zone/Fuel/etc.).
   - `GameLogic` remains the polling/orchestration boundary.
   - `navigation.py`, `timing_store.py`, `lifecycle.py`, `diagnostics.py`,
     `ccrp_scheduler.py`, `weapon_catalog.py`, `weapon_scheduler.py`, and
     `weapon_solver.py` own focused helper responsibilities extracted from the
     former monolithic logic module.
   - Free-fall/high-drag stores keep the existing CCRP path. AAMs and AGMs with valid
     Datamine `guidance/tableN` data use those conditional launch-envelope
     tables before the one-dimensional powered fallback; a table reference is
     independent of whether the fallback can model complex propulsion.
     Supported powered weapons and guided bombs use the same separate
     prepare/compute/apply path: lock-owned
     state is projected into a work item, the numerical estimate runs outside
     the state lock, and only a still-current selection/target/model result is
     applied. Glide weapons still have no validated native-equivalent
     lift/autopilot provider: the default selectable policy supplies an
     explicitly experimental FoxThree-compatible energy-height estimate, while
     strict mode reports unavailable; neither path reuses the free-fall proxy.
   - Weapon selection is manual unless a future directed 8111 capture proves a
     named selection field. Button/release pulses such as `weapon2` are never
     treated as a selected category.
3. UI render with `tkinter` (timer, panels, hints, debug text).
   - `App` keeps window lifecycle and the main refresh loop.
   - `AppNavigationServices` owns standalone navigation window lifecycle, mode switching, history-mode suspension, and display-change rebuilds.
   - `AppRuntimeServices` owns global hotkey, tray, and HUD overlay lifecycle while preserving the existing `App` callback surface for dialogs and tray actions.
   - `MainWindowBuilder` owns the static card/grid skeleton and pre-allocates fixed label pools for the main window.
   - `AppDebugSupport` owns debug-mode mock snapshots and debug text generation.
   - `AppPanelRenderer` owns zone/airport/fuel/weapon-solution/speed strip rendering and mid-panel layout updates.
   - `navigation_presenter.py` owns UI-only navigation target selection and heading-tape model construction shared by the integrated and standalone navigation surfaces.
   - `panel_presenter.py`, `hud_presenter.py`, `dialog_presenter.py`, and `snapshot_presenter.py` own headless view models for strings, colors, target selection, and option summaries. Tk modules apply those models while retaining widget layout and runtime side effects.
   - `runtime.py` owns small runtime thread helpers: background logic polling, daemon thread startup, and safe Tk main-thread callback dispatch.
   - `settings_runtime.py` owns SettingsDialog side effects that run only after config persistence succeeds.
   - `settings_form.py` owns headless settings value collection, validation, hotkey conflict checks, and save-payload construction; `dialogs.py` remains the Tk modal entrypoint and applies messagebox/file/runtime side effects.
   - `text_utils.py` owns shared Tk text measurement, label wrapping, elision, and scaled control-length helpers used by main-window and dialog layout.
   - `window_geometry.py` owns snap-anchor capture/application helpers so App geometry coordination can be tested without a Tk root.
   - `theme.py` owns runtime theme tokens, while `tk_style.py` owns shared Tk palette/action-button styling used by the launcher and modal app dialogs.
4. Alerts and sounds via `SoundConfig` + Windows Beep/custom files; `SoundManager` serializes playback through one worker queue and drops overlapping requests while a sound is active.
5. Diagnostics flow:
   - `Bomana.pyw` initializes `bomana/utils/diagnostics.py` at startup.
   - Runtime diagnostics are JSONL records written to `.wttimer_diagnostics.log` next to the user config file.
   - UI and 8111 polling threads enqueue structured events through `QueueHandler`; the background listener owns disk I/O.
   - Initial coverage includes app start/exit, config migration/persistence errors, endpoint failures/recovery, navigation target changes, and HUD lifecycle/toggle failures.
6. Overspeed flow:
   - `TelemetryFetcher` reads `type` + IAS/TAS/Mach + `wing_sweep_indicator`.
   - `OverspeedAnalyzer` resolves `/indicators.type` -> `unit_to_fm` -> FM limits.
   - IAS/Mach dual-channel grading (`safe/caution/warning/critical`) drives compact speed strip + alert sound.
7. Launcher check flow:
   - `launcher.pyw` remains the user-facing and PyInstaller entrypoint, while
     the `launcher/` package owns development-time launcher boundaries.
   - On startup (and channel switch), launcher auto-checks both app-package metadata and launcher metadata in a background thread.
   - `UpdateService` coordinates manifest resolution, size probing, app update checks, and launcher update checks while the GUI keeps only worker/event handling.
   - Channel/source/proxy changes during an in-flight check are queued and trigger an automatic follow-up re-check instead of being blocked.
   - Uses Tencent API first (`BOMANA_UPDATE_BASE_URL`) for app and launcher manifests when available.
   - Falls back to GitHub Release metadata when Tencent is unavailable, or when primary only exposes version without downloadable package.
   - App and launcher manifests must include an Ed25519 `manifest_signature`; `launcher.verify` and `launcher.manifest_sources` verify against pinned release public keys before projecting trusted version, asset, or SHA256 fields. Canonical field ownership is in `docs/specs/release-signing.md`.
   - The Tencent/EdgeOne service does not hold the release private key. It forwards `manifest_signature` from the deployed JSON manifests and may add service-derived fields such as `package_url`, `source_name`, `package_size`, and the launcher compatibility alias `package_sha256`.
   - `tools/build_portable.py` signs manifests from `BOMANA_RELEASE_ED25519_PRIVATE_KEY`, requires the matching `BOMANA_RELEASE_ED25519_PUBLIC_KEY`, and injects that public key into packaged launchers through a temporary `launcher/release_public_keys.py` module.
   - Resolves package total size from manifest value or HTTP `Content-Length` probe.
   - Launcher 3.0.0 uses `bomana_version.py` as the only strict compatibility parser. App and Launcher manifests keep schema version 1 and their existing signed field sets; compatibility does not add a new signed field.
   - The redesigned tkinter surface groups status, primary launch/update action, channel/source/proxy controls, and Web startup preferences without adding a runtime dependency. The proxy labels describe the existing preferred-path/fallback behavior instead of changing it.
8. Launcher download/apply flow:
   - Download only starts after explicit user confirmation.
   - Streams package with progress and transfer speed updates.
   - Verifies SHA256 after signed-manifest validation; `launcher/install_txn.py` owns the update lock, staging directory, `app/` replacement, rollback cleanup, and incomplete-install recovery.
   - Launch, verified online install, local ZIP import, rollback, and incomplete-install recovery all read `bomana/metadata.py` as data and reject malformed or below-8.0.0 candidates before any valid slot is renamed, replaced, deleted, or swapped. Online staging additionally requires the package version to equal the already-verified signed manifest version exactly.
   - Successful app installs promote the previous app into `app_previous/` and update local version metadata.
   - Launcher rollback swaps `app/` and `app_previous/`, so exactly one previous app version is retained at a time.
   - Launcher self-update downloads a new `Bomana_launcher_v*.exe`, stages it in an isolated OS temp workspace, runs a detached replacement script with literal-path file operations, exits, swaps the executable, and restarts.
   - Launch action stays available for offline local app start while background checks are still running.
   - Launcher download/update/install and App launch all remain at ordinary user integrity. `BOMANA_RUNTIME_ROOT`, `cwd`, `sys.path`, and the `launcher.bootstrap` app-package import finder force installed `app/bomana` modules and resources to win over launcher-bundled modules without crossing UAC.
   - Immediately before App entry, bootstrap supplies its own `BOMANA_LAUNCHER_VERSION` plus strict `0`/`1` values for loopback Web autostart and local-page auto-open. `Bomana.pyw` validates Launcher 3.0.0+ before importing diagnostics, Tk, `GameLogic`, runtime services, or Web listeners. Only `BOMANA_SOURCE_DEVELOPMENT=1` in an explicitly non-frozen source process may bypass a missing identity; malformed or old identities still fail.
   - Launcher persists only `web_dashboard_autostart` (default `true`) and `web_dashboard_auto_open` (default `false`). The App owns listener creation, selected port, pairing URL, browser-open timing, and every LAN/control runtime decision.
9. Privileged hotkey flow:
   - The App registers ordinary `RegisterHotKey` bindings first and never opens UAC automatically. It then enumerates visible top-level windows and queries only the image name and elevation token for exact War Thunder executable names.
   - Confirmed ordinary War Thunder keeps the default path without a privilege notice. Elevated, absent, or unknown game state exposes an optional action; after explicit confirmation, the App resolves `bomana/bin/BomanaHotkeyBroker.exe`, validates its adjacent SHA-256, locks it against write/delete replacement, and requests UAC. No installer or persistent component is used; without Authenticode Windows shows Unknown publisher.
   - The ordinary App creates one local message pipe and stop event per privileged launch with a random nonce, explicit current-user/SYSTEM/Administrators DACL, and remote-client rejection.
   - The native broker validates the App PID/session and pipe server PID, registers only the configured fixed actions once with `RegisterHotKey | MOD_NOREPEAT`, and sends fixed eight-byte action frames back to the App.
   - The pipe reader posts callbacks through `TkEventDispatcher`; UAC denial, missing/tampered broker, or IPC failure restores local `RegisterHotKey`, buttons, tray actions, and 8111 features.
   - The App stop event or App process exit unregisters all broker hotkeys and ends the broker. No hook, polling, game-memory access, service, scheduled task, autostart, network, plugin, or arbitrary command/path surface exists in the broker.
   - `tools/build_hotkey_broker.py` builds only the native runtime. `tools/build_portable.py` embeds it and the adjacent checksum into each App package.
10. Launcher telemetry flow: `version_check` / `launcher_start` / `app_launch` / `launcher_update_result` events to Tencent API (best effort).
11. Web Cockpit flow:
   - `App` publishes the selected live/debug `UISnapshot` plus a copied checklist into `DashboardSnapshotStore`, and separately publishes Tk-owned semantic target state into `DashboardControlStore`; HTTP threads consume only those immutable projections and never poll or proxy port 8111.
   - `WebDashboardRuntime` starts a loopback listener on `127.0.0.1`, preferring port `8777` and trying a bounded set of nearby ports when it is occupied.
   - The tray can explicitly enable one RFC1918 IPv4 listener for the current process. LAN access and LAN control are separate current-run actions; neither is persisted, and Bomana does not bind `0.0.0.0`, modify Windows Firewall/UPnP, or request elevation for the dashboard.
   - Each process has fresh pairing material. Every successful pairing creates a distinct session token, authorization record, CSRF proof, and bounded idempotency store; pairing redirects away from the code-bearing URL and authenticates later reads with an HttpOnly `SameSite=Strict` cookie.
   - Loopback pairings may receive `control`; LAN pairings receive `view` by default. Explicitly enabling LAN control rotates the pairing code and grants control only to later LAN pairings. Revocation advances the authorization epoch, invalidates existing LAN-control sessions immediately, and rotates the code again.
   - The browser receives ownship, zones, airfields, POIs, Trace back, status, timer, flight, fuel, navigation, weapon, bombing, checklist, and alert fields permitted by the active `ENABLE_*` profile. Hostile-aircraft contacts, raw 8111 payloads, and diagnostics are excluded.
   - `POST /api/v1/commands` is the only write route. It requires a current control session, exactly one non-empty same-origin `Origin`, per-session CSRF proof, `application/json` with a declared length of 1..4096 bytes, the shared command schema, and a bounded per-session idempotency key. A valid enqueue returns HTTP 202 with `schema_version: 1`, the idempotency key as `command_id`, `status: "queued"`, and `submitted_revision`; the browser polls `GET /api/v1/control-state` for the later per-session `succeeded` or `rejected` completion, stable reason, submitted revision, and resulting revision.
   - The complete command matrix is exactly `action.reset_timer`,
     `action.cycle_corner`, `state.set_locked`, `state.set_beep_enabled`,
     `state.set_zone_sound_enabled`, `config.set_panel_visibility`,
     `weapon.select`, and `weapon.set_ballistic_model`. The last six use explicit
     targets rather than generic toggles; applicable `ENABLE_*` flags and
     current weapon compatibility remain authoritative.
   - HTTP workers enqueue an immutable envelope through `TkEventDispatcher` and never wait for execution. The Tk owner thread rechecks session epoch/scope, current-run LAN authority, feature flags, catalog/aircraft compatibility, enums, and target validity before applying the existing App semantic path and publishing one bounded completion.
   - All browser resources are packaged under `bomana/assets/web/`; the dashboard has no CDN, remote font, analytics, upload, permissive CORS, synthesized keyboard input, arbitrary callback/config/command path, or new broker/network capability.

Important constraint: runtime data path is official 8111 API only; no memory reads, injection, log decryption, packet inspection, or game file modifications.

## Static Data Provenance
- `bomana/data/ccrp_bomb_params.json`
  - Raw source: War Thunder datamine `aces.vromfs.bin_u/gamedata/weapons/bombguns/*.blkx`
  - Recommended updater: `tools/update_datamine_assets.py`
  - Dedicated generator: `tools/blkx_extractor.py`
  - Shared helper: `tools/datamine_utils.py`
  - Runtime consumer: `BombConfig` / CCRP ballistics path
- `bomana/data/fm_speed_limits.json`
  - Raw source: War Thunder datamine `aces.vromfs.bin_u/gamedata/flightmodels/**`
  - Recommended updater: `tools/update_datamine_assets.py`
  - Dedicated generator: `tools/fm_speed_extractor.py`
  - Shared helper: `tools/datamine_utils.py`
  - Runtime consumer: `OverspeedAnalyzer` via `/indicators.type -> unit_to_fm -> fm_speed_limits`
- `bomana/data/weapon_fire_control.json`
  - Raw sources: Datamine `gamedata/weapons/{rocketguns,bombguns,containers}`,
    aircraft `gamedata/flightmodels/*.blkx` weapon-slot/preset references, and
    `lang/units_weaponry.csv` localization
  - Shape source: `docs/specs/schemas/weapon-fire-control.schema.json`
  - Recommended updater: `tools/update_datamine_assets.py`
  - Dedicated generator: `tools/weapon_fire_control_extractor.py`
  - Runtime consumers: `WeaponCatalog`, `weapon_solver`, and the existing
    Enhanced-only compact bombing/weapon-solution card
  - Each record retains its source path/SHA-256 and normalized-field JSON
    pointers; AAM/AGM records retain ordered `guidance/tableN` identities, complete
    altitude/carrier-Mach/target-Mach axes, scenario range outputs, and time
    outputs. Top-level metadata retains the Datamine version and full commit.
  - The game's native `buildMissileTrajectoryData` implementation and reusable
    static comparison curves are not present in the current Datamine source, so
    there is no active official-trajectory provider for glide weapons.
- Generated JSON metadata records the datamine source version and git commit when available.

## Offline Session Capture and Replay

- `tools/record_8111_session.py` records synchronized decoded payloads from the
  four official loopback endpoints into gzip JSONL without entering the runtime
  App or changing its polling path.
- `/indicators`, `/state`, and `/map_obj.json` use the configured recording
  interval; `/map_info.json` defaults to the App's 30-second cache cadence.
- Metadata and summaries intentionally omit user, account, and host identifiers.
  Captures default to the gitignored `recordings/` directory. A maintainer may
  explicitly promote a completed capture byte-for-byte into
  `tests/fixtures/8111/`; its manifest locks the source/fixture SHA-256 and
  expected replay timeline.
- `docs/specs/schemas/8111-session-record.schema.json` is the machine-readable
  shape source for each JSONL record. `tools/session_8111.py` validates every
  record and also verifies ordering, monotonic elapsed time, sample totals,
  endpoint statistics, and aircraft-type summary before replay begins.
- `tools/replay_8111_session.py` replaces only `GameLogic`'s injected wall clock
  and HTTP adapter. It advances recorded elapsed time without contacting 8111,
  while the normal App keeps `SystemClock` and `HttpJson` defaults.
- Replay reports contain sanitized transitions and coverage rather than map
  positions. The `full-sortie` profile gates lobby failure, spawn, two takeoffs,
  landing/refit, bomb release, cycle rollover, critical overspeed, and player
  loss. It does not replace Tk/global-hotkey or real-game smoke testing.
- `tools/build_8111_replay_fixture.py` validates and replays a selected raw
  capture before exact-byte import. Coordinates remain available to navigation
  regression tests; identity fields remain absent because the recorder schema
  never collected them. The fixture manifest shape is governed by
  `docs/specs/schemas/8111-replay-fixture-manifest.schema.json`.
- Usage and capture privacy are documented in
  `docs/guides/8111-session-recording.md`; the collection boundary is governed
  by `R8111-09..R8111-16`.

## Configuration & Persistence
- Runtime configuration lives in `bomana/config/`.
- Import configuration through explicit submodules: `bomana.config.feature_profile`, `bomana.config.settings`, and `bomana.config.static_data`.
- User config/state stored as JSON in the user home directory (`FileConfig.CONFIG_FILE` / `STATE_FILE`).
- Timer state restore is battle-scoped: `STATE_FILE` stores a 8111-derived battle signature and `GameLogic` applies the pending timer only after the next live battle context matches it.
- Feature flags (`ENABLE_*`) drive compile-time variants and UI availability. All variants share the same config file.
- For compatibility, legacy `ENABLE_CCRP` and `show_bombing` names gate the
  whole compact weapon-solution card; `selected_weapon` is manual selection and
  falls back to the historical `selected_bomb` value during migration.
- Web commands persist through the same existing App config paths as desktop
  actions: corner, lock, general/zone sound, panel visibility, selected weapon,
  and ballistic model. Failed persistence restores the prior effective state.
- Launcher state may persist only the loopback Web autostart and local-page
  auto-open booleans. Listener address/port, pairing, LAN access/control,
  sessions, CSRF, idempotency, and authorization epochs remain App-owned
  process state.

## Functional Areas (Conceptual)
- Timer & lifecycle
- Zone/airfield navigation
- Fuel management
- CCRP bombing predictor + estimated AGM/guided ranges, conditional-table AAM
  references, and selectable experimental/strict handling for uncalibrated
  glide envelopes
- UI overlays & global hotkeys

## Runtime Thread Boundary
- Tk widgets are owned by the Tk main thread. Background callbacks use `TkEventDispatcher.post()` or a Tk-owned queue/poller bridge before touching UI state; background threads do not call `root.after(...)` directly.
- `LogicPoller` owns the `GameLogic.tick()` background loop. It samples 8111 data and updates core state only; UI reads immutable `UISnapshot` values from the main refresh loop.
- `GlobalHotkeys` registers a Win32 message-only window on the Tk owner thread. Its WndProc enqueues `WM_HOTKEY` callbacks through `TkEventDispatcher`, avoiding a separate message thread and reentrant Tk calls.
- `pystray` runs on a daemon tray thread. Menu callbacks must dispatch UI actions through `TkEventDispatcher` instead of calling app methods directly.
- Web Cockpit HTTP workers never import or call Tk. They may validate and enqueue only immutable semantic command envelopes; the Tk owner reauthorizes, rechecks feature/target validity, executes, and publishes completion. Tray actions for opening, copying, or toggling Web Cockpit access/control also cross `TkEventDispatcher`; App shutdown stops both listeners before destroying Tk.
- `SoundManager` owns its own worker queue for audio playback. UI code enqueues sound requests and does not block on playback.

## 8111 Map Coordinate Contract
- `MapInfoFetcher` owns `/map_info.json` retrieval and cache refresh timing on `GameState.map_info`.
- `MapObjectsFetcher` owns `/map_obj.json` parsing only. It returns player,
  currently visible hostile-aircraft contacts, zone, POI, and airfield positions
  in the normalized coordinates provided by 8111 and does not accept or
  interpret `map_info`. It excludes friendly aircraft from fire-control targets
  and does not persist contacts after 8111 stops returning them. Finite hostile
  `dx`/`dy` values are preserved only on the current contact sample; missing
  motion is not reconstructed from prior responses.
- `GameLogic` owns coordinate semantics for navigation and weapon targeting. It
  derives X/Y meter scale from cached `MapInfo.map_min/map_max` and applies that
  scale when calculating bearing, distance, ground speed, airfield/zone display
  values, forward ground targets, and the current two-dimensional hostile-air
  estimate. The AAM path may project current hostile `dx`/`dy` onto line of
  sight as a radial-aspect hint, but unknown target altitude and speed magnitude
  keep the result a conditional reference rather than an intercept solution.
- Trace back retains only the player's own last position from a successful raw
  `/map_obj.json` Player sample. A successful non-empty sequence without Player
  freezes that position, and the existing `LOSS_PENDING -> WAIT_NEXT`
  transition confirms it; source failure, an empty frame, or Player recovery
  cancels the pending sequence. The confirmed point stays in process memory,
  survives only a same-battle respawn, and is projected through the shared
  heading-tape snapshot path without replacing the primary zone target.

## UI Stability & Performance Guardrails
- Keep panel containers structurally stable during transient 8111 data drops (avoid frame-level mount/unmount churn).
- In `ALIVE/LOSS_PENDING`, treat short `/map_obj.json` jitter conservatively by combining map presence with telemetry entity signals.
- Prefer incremental list updates against prebuilt label pools instead of per-frame widget creation or full `pack_forget()/pack()` cycles.
- Keep the main window on a stable grid/card skeleton (`bomana/ui/main_window.py`) and limit `_recalc_size()` to real structural changes.
- Keep integrated heading-tape row mounted and clear content only when heading is temporarily unavailable.
- `HeadingTape` (`bomana/ui/widgets.py`) uses render-signature dedup to skip equivalent canvas redraw frames.
- Standalone nav window rows (`bomana/ui/nav_window.py`) stay mounted; update text/color only to reduce micro-flicker.
- Launcher and modal dialogs must treat DPI/text preferences as the font scale source of truth; normal window resize may reflow text, but must not continuously recalculate widget font sizes.
- Do not rely on system emoji fonts for primary UI. Use `IconManager` PNG assets for visual icons and keep text labels emoji-free.
- `bomana/utils/system.py` privately loads bundled `Bomana UI Sans` fonts before selecting a UI family; this avoids requiring users to install fonts system-wide.

## Build & Release
Portable release uses:
- `Bomana_launcher_vX.Y.Z.exe` (universal bootstrap runtime with channel selector)
- `launcher_manifest.json` (launcher version/package metadata + SHA256 + Ed25519 manifest signature)
- `Bomana_app_<Variant>_vX.Y.Z.zip` (updatable application package)
- `manifest_<Variant>.json` (channel/version/package metadata + SHA256 + `min_launcher_version` + Ed25519 manifest signature)
- `checksums_app_<Variant>.txt` and `checksums_launcher.txt` (SHA256 checksum info consumed by deployment tooling)

The current compatibility boundary is App `8.0.0` / Launcher `3.0.0`:
Launcher 3 rejects App candidates below 8.0.0 on every candidate path, while a
packaged App 8 validates Launcher 3.0.0+ before runtime initialization. Release
manifest schema version 1 and the established signed field sets remain
unchanged.

Bundled assets:
- App packages include `bomana/assets/` automatically because `build_app_zip()` packages the whole `bomana/` tree.
- Launcher builds also add `bomana/assets/` so launcher/dialog text can use the same private UI font when running as a onefile executable.
- Every App variant includes the self-hosted Web Cockpit assets; feature flags still decide which dashboard capabilities are published.
- Every App variant also includes `bomana_version.py` and the Web command,
  command-response, and control-state schemas used by production validation.
- Root-level branding files were folded into `bomana/assets/branding/`; runtime and packaging paths use only the bundled asset location.

Local build helper:
- `tools\scripts\build_portable.bat <Variant> <all|app|launcher>` (`all` builds the selected variant app plus the universal launcher)
- `tools\scripts\build_app_package.bat <Variant>` (only app zip + manifest)
- `tools\scripts\build_launcher.bat [version]` (only universal launcher exe; optional version must match `LAUNCHER_VERSION`)
- Release manifest builds require both `BOMANA_RELEASE_ED25519_PRIVATE_KEY` and `BOMANA_RELEASE_ED25519_PUBLIC_KEY`; the build fails if the public key does not match the private key. Launcher builds embed the public key into the packaged launcher.

CI:
- `.github/workflows/quality.yml` runs lightweight pull-request / `main` push gates on `windows-latest`:
  - Python 3.14 + `uv sync --extra dev --frozen`
  - `uv run --extra dev ruff check .`
  - `uv run --extra dev ruff format --check .`
  - `tools\scripts\check_smoke.bat` (pytest-based fast suite)
  - This workflow intentionally does not enforce a coverage threshold or pretend to replace real War Thunder / `localhost:8111` smoke validation.
- `.github/workflows/build.yml` runs separate jobs for:
  - `quality`: release-preflight Ruff + pytest smoke checks
  - `build_app`: native broker + app package + manifest + GitHub Artifact Attestation
  - `build_launcher`: launcher exe + `launcher_manifest.json`
- `.github/workflows/build.yml` requires the repository secrets `BOMANA_RELEASE_ED25519_PRIVATE_KEY` and `BOMANA_RELEASE_ED25519_PUBLIC_KEY` for signed manifests. App and Launcher jobs use full-commit-pinned `actions/attest@v4` with narrow OIDC/attestation permissions to publish provenance for final artifacts; no Authenticode PFX is required.
- tag-driven release targets:
  - `vX.Y.Z`: full release (launcher + app packages)
  - `vX.Y.Z-app`: app packages only
  - `vX.Y.Z-launcher`: launcher only
- `workflow_dispatch` also supports `build_target=all|app|launcher`.
- `tools/deploy_update_assets.py` is the only supported Tencent/EdgeOne deployment path for release update assets; it runs from the maintainer workstation, backs up `stats.db`/manifests, uploads app/launcher assets, writes versioned manifests, and verifies public endpoints with the release public key.
- GitHub-hosted Actions must not SSH/rsync/scp release assets to TencentCloudPublic/CVM. That deploy workflow is intentionally absent because the GitHub runner to Tencent network path is slow/unreliable; build and Release creation remain in GitHub Actions, while Tencent update deployment stays local.

## Documentation Map
- `README.md`: public landing page, install paths, feature overview, compliance statement
- `docs/index.html` + `docs/styles.css` + `docs/site.js`: static GitHub Pages landing site served from `main:/docs`
- `docs/QUICKSTART.md`: condensed player/developer quick start
- `docs/CONTRIBUTING.md`: current contribution workflow, `bd` tracking, release expectations
- `docs/specs/`: canonical runtime, release, threading, config, and quality contracts
- `docs/adr/`: durable architecture decisions and their status
- `docs/PRIVACY.md`: launcher telemetry plus local/LAN Web Cockpit privacy disclosure
- `docs/guides/web-cockpit-smoke.md`: real-browser, phone/LAN, Firewall, packaged-build, and live-game manual smoke
- `docs/PITFALLS.md`: operational failure log for maintainers
- `tests/README.md`: test-layer router; quality obligations remain canonical in `docs/specs/testing-quality-gates.md`
