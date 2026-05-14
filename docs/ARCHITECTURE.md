# Project Architecture (Bomana)

## Overview
- Bootstrap entry point: `Bomana.pyw` (single-instance guard, DPI setup, root window creation, `App` startup)
- Portable launcher: `launcher.pyw` (startup auto-check, Tencent CDN-first downloads with GitHub fallback, app/launcher split updates, one-version rollback retention, offline launch, details/support dialog)
- Central config: `bomana/config.py` (metadata, feature flags, config classes)
- Core logic: `bomana/core/` (state, telemetry, ballistics, game logic)
- UI components: `bomana/ui/` (app coordinator, main-window builder, debug support, panel renderer, widgets, dialogs, nav window)
- Utilities: `bomana/utils/` (system, math, file, sound helpers)
- Bundled UI assets: `bomana/assets/` (private UI font subsets + PNG icon assets)
- External data: `bomana/data/ccrp_bomb_params.json` (CCRP bomb parameters)
- External data: `bomana/data/fm_speed_limits.json` (机型 IAS/Mach 限速库)
- Tools: `tools/update_datamine_assets.py` (refresh both generated datamine assets)
- Tools: `tools/blkx_extractor.py` / `tools/fm_speed_extractor.py` (single-asset extractors)
- Tools: `tools/create_version_info.py` / `tools/sample_8111_attitude.py` (build metadata + diagnostics)
- Assets: `app.png`, `sponsor_wechat.png`, `app.ico`

## Repository Layout
```
.
├─ Bomana.pyw                # Thin bootstrap entrypoint
├─ launcher.pyw              # Green launcher (auto update + bootstrap)
├─ bomana/
│  ├─ config.py              # Metadata/flags/config classes
│  ├─ data/
│  │  ├─ ccrp_bomb_params.json # Bomb parameters (CCRP)
│  │  └─ fm_speed_limits.json # Aircraft speed limits (IAS/Mach)
│  ├─ assets/
│  │  ├─ fonts/                # Private Bomana UI Sans font subsets + OFL license
│  │  └─ icons/                # PNG icon assets used instead of emoji glyphs
│  ├─ core/
│  │  ├─ ballistics.py        # Bombing ballistics
│  │  ├─ logic.py             # GameLogic core loop
│  │  ├─ overspeed.py         # Aircraft speed-limit matching + alert grading
│  │  ├─ state.py             # Dataclasses/enums
│  │  └─ telemetry.py         # 8111 fetchers
│  ├─ ui/
│  │  ├─ app.py               # App coordinator (window lifecycle + main UI loop)
│  │  ├─ debug_support.py     # Debug mock snapshot + debug panel helpers
│  │  ├─ dialogs.py           # Settings/About/etc dialogs
│  │  ├─ hud_overlay.py       # Fullscreen HUD overlay skeleton (v6.8.0)
│  │  ├─ icon_assets.py       # Bundled PNG icon loader/cache
│  │  ├─ main_window.py       # Stable main-window skeleton/card layout builder
│  │  ├─ nav_window.py        # Standalone navigation window
│  │  ├─ navigation_runtime.py # Standalone nav lifecycle + display rebuild service
│  │  ├─ navigation_presenter.py # Shared heading-tape target selection/model helpers
│  │  ├─ panel_renderer.py    # Zone/fuel/bombing/speed panel rendering helpers
│  │  ├─ runtime.py           # Tk dispatch + runtime worker thread helpers
│  │  ├─ runtime_services.py  # Global hotkeys, tray, and HUD runtime integrations
│  │  └─ widgets.py           # Pill/HeadingTape widgets
│  └─ utils/
│     ├─ diagnostics.py      # Structured async diagnostics logging
│     ├─ file_utils.py        # Config/state/resource helpers
│     ├─ math_utils.py        # Navigation/math helpers
│     ├─ sound.py             # Sound manager
│     └─ system.py            # Windows/system helpers
├─ docs/                        # Architecture/changelog/privacy/contributing docs
├─ tools/
│  ├─ build_portable.py      # Build launcher/app package/manifest
│  ├─ create_version_info.py # Windows version-info helper for packaging
│  ├─ blkx_extractor.py      # .blkx -> bomana/data/ccrp_bomb_params.json generator
│  ├─ fm_speed_extractor.py  # .blkx -> fm_speed_limits.json generator
│  ├─ generate_ui_assets.py  # Noto Sans SC subset + PNG icon asset generator
│  ├─ update_datamine_assets.py # One command to refresh both generated data assets
│  ├─ sample_8111_attitude.py # HUD baseline sampler
│  ├─ scripts/               # Local build helper scripts (bat/sh)
├─ assets (root files)       # Icons/sponsor image, etc.
└─ README.md                 # Main landing page for GitHub visitors
```

Note: the self-hosted update/statistics service was moved out of this repo; see the README section about `bomana-worker` for the current service repository.

## Runtime Data Flow
1. 8111 API polling via `requests` to `localhost:8111`.
2. State judgement using config classes (Game/Zone/Fuel/etc.).
3. UI render with `tkinter` (timer, panels, hints, debug text).
   - `App` keeps window lifecycle and the main refresh loop.
   - `AppNavigationServices` owns standalone navigation window lifecycle, mode switching, history-mode suspension, and display-change rebuilds.
   - `AppRuntimeServices` owns global hotkey, tray, and HUD overlay lifecycle while preserving the existing `App` callback surface for dialogs and tray actions.
   - `MainWindowBuilder` owns the static card/grid skeleton and pre-allocates fixed label pools for the main window.
   - `AppDebugSupport` owns debug-mode mock snapshots and debug text generation.
   - `AppPanelRenderer` owns zone/airport/fuel/bombing/speed strip rendering and mid-panel layout updates.
   - `navigation_presenter.py` owns UI-only navigation target selection and heading-tape model construction shared by the integrated and standalone navigation surfaces.
   - `runtime.py` owns small runtime thread helpers: background logic polling, daemon thread startup, and safe Tk main-thread callback dispatch.
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
   - On startup (and channel switch), launcher auto-checks both app-package metadata and launcher metadata in a background thread.
   - `UpdateService` coordinates manifest resolution, size probing, app update checks, and launcher update checks while the GUI keeps only worker/event handling.
   - Channel/source/proxy changes during an in-flight check are queued and trigger an automatic follow-up re-check instead of being blocked.
   - Uses Tencent API first (`BOMANA_UPDATE_BASE_URL`) for app and launcher manifests when available.
   - Falls back to GitHub Release metadata when Tencent is unavailable, or when primary only exposes version without downloadable package.
   - Resolves package total size from manifest value or HTTP `Content-Length` probe.
8. Launcher download/apply flow:
   - Download only starts after explicit user confirmation.
   - Streams package with progress and transfer speed updates.
   - Verifies SHA256 (when provided); `InstallTransaction` owns the update lock, staging directory, `app/` replacement, rollback cleanup, and incomplete-install recovery.
   - Successful app installs promote the previous app into `app_previous/` and update local version metadata.
   - Launcher rollback swaps `app/` and `app_previous/`, so exactly one previous app version is retained at a time.
   - Launcher self-update downloads a new `Bomana_launcher_v*.exe`, stages it in an isolated OS temp workspace, runs a detached replacement script with literal-path file operations, exits, swaps the executable, and restarts.
   - Launch action stays available for offline local app start while background checks are still running.
9. Launcher telemetry flow: `version_check` / `launcher_start` / `app_launch` / `launcher_update_result` events to Tencent API (best effort).

Important constraint: runtime data path is official 8111 API only; no memory reads, injection, log decryption, packet inspection, or game file modifications.

## Static Data Provenance
- `bomana/data/ccrp_bomb_params.json`
  - Raw source: War Thunder datamine `aces.vromfs.bin_u/gamedata/weapons/bombguns/*.blkx`
  - Recommended updater: `tools/update_datamine_assets.py`
  - Dedicated generator: `tools/blkx_extractor.py`
  - Runtime consumer: `BombConfig` / CCRP ballistics path
- `bomana/data/fm_speed_limits.json`
  - Raw source: War Thunder datamine `aces.vromfs.bin_u/gamedata/flightmodels/**`
  - Recommended updater: `tools/update_datamine_assets.py`
  - Dedicated generator: `tools/fm_speed_extractor.py`
  - Runtime consumer: `OverspeedAnalyzer` via `/indicators.type -> unit_to_fm -> fm_speed_limits`
- Generated JSON metadata records the datamine source version and git commit when available.

## Configuration & Persistence
- Runtime configuration lives in `bomana/config.py`.
- User config/state stored as JSON in the user home directory (`FileConfig.CONFIG_FILE` / `STATE_FILE`).
- Timer state restore is battle-scoped: `STATE_FILE` stores a 8111-derived battle signature and `GameLogic` applies the pending timer only after the next live battle context matches it.
- Feature flags (`ENABLE_*`) drive compile-time variants and UI availability. All variants share the same config file.

## Functional Areas (Conceptual)
- Timer & lifecycle
- Zone/airfield navigation
- Fuel management
- CCRP bombing predictor
- UI overlays & global hotkeys

## Runtime Thread Boundary
- Tk widgets are owned by the Tk main thread. Background callbacks must use `TkEventDispatcher.post()` or an existing `root.after(0, ...)` bridge before touching UI state.
- `LogicPoller` owns the `GameLogic.tick()` background loop. It samples 8111 data and updates core state only; UI reads immutable `UISnapshot` values from the main refresh loop.
- `GlobalHotkeys` listens on a Windows message thread and posts configured callbacks back to Tk.
- `pystray` runs on a daemon tray thread. Menu callbacks must dispatch UI actions through `TkEventDispatcher` instead of calling app methods directly.
- `SoundManager` owns its own worker queue for audio playback. UI code enqueues sound requests and does not block on playback.

## 8111 Map Coordinate Contract
- `MapInfoFetcher` owns `/map_info.json` retrieval and cache refresh timing on `GameState.map_info`.
- `MapObjectsFetcher` owns `/map_obj.json` parsing only. It returns player, zone, and airfield positions in the normalized coordinates provided by 8111 and does not accept or interpret `map_info`.
- `GameLogic` owns coordinate semantics for navigation. It derives X/Y meter scale from cached `MapInfo.map_min/map_max` and applies that scale when calculating bearing, distance, ground speed, and airfield/zone display values.

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
- `launcher_manifest.json` (launcher version/package metadata + SHA256)
- `Bomana_app_<Variant>_vX.Y.Z.zip` (updatable application package)
- `manifest_<Variant>.json` (channel/version/package metadata + SHA256 + `min_launcher_version`)
- `checksums_*.txt` (SHA256 checksum info)

Bundled assets:
- App packages include `bomana/assets/` automatically because `build_app_zip()` packages the whole `bomana/` tree.
- Launcher builds also add `bomana/assets/` so launcher/dialog text can use the same private UI font when running as a onefile executable.

Local build helper:
- `tools\scripts\build_portable.bat <Variant> <all|app|launcher>`
- `tools\scripts\build_app_package.bat <Variant>` (only app zip + manifest)
- `tools\scripts\build_launcher.bat [version]` (only universal launcher exe)

CI:
- `.github/workflows/quality.yml` runs lightweight pull-request / `main` push gates on `windows-latest`:
  - Python 3.14 + `uv sync --extra dev --frozen`
  - `uv run --extra dev ruff check .`
  - `uv run --extra dev ruff format --check .`
  - `tools\scripts\check_smoke.bat`
  - This workflow intentionally does not enforce a coverage threshold or pretend to replace real War Thunder / `localhost:8111` smoke validation.
- `.github/workflows/build.yml` runs separate jobs for:
  - `build_app`: app package + manifest
  - `build_launcher`: launcher exe + `launcher_manifest.json`
- tag-driven release targets:
  - `vX.Y.Z`: full release (launcher + app packages)
  - `vX.Y.Z-app`: app packages only
  - `vX.Y.Z-launcher`: launcher only
- `workflow_dispatch` also supports `build_target=all|app|launcher`.
- `.github/workflows/deploy-manifests-to-server.yml` syncs manifests, app zips, launcher exe, and `launcher_manifest.json` to the Tencent/EdgeOne update server.

## Documentation Map
- `README.md`: public landing page, install paths, feature overview, compliance statement
- `docs/QUICKSTART.md`: condensed player/developer quick start
- `docs/CONTRIBUTING.md`: current contribution workflow, `bd` tracking, release expectations
- `docs/PRIVACY.md`: launcher telemetry/update-service privacy disclosure
- `docs/PITFALLS.md`: operational failure log for maintainers

