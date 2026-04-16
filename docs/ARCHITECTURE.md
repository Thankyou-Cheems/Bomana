# Project Architecture (Bomana)

## Overview
- Bootstrap entry point: `Bomana.pyw` (single-instance guard, DPI setup, root window creation, `App` startup)
- Portable launcher: `launcher.pyw` (startup auto-check, Tencent CDN-first downloads with GitHub fallback, app/launcher split updates, one-version rollback retention, offline launch, details/support dialog)
- Central config: `bomana/config.py` (metadata, feature flags, config classes)
- Core logic: `bomana/core/` (state, telemetry, ballistics, game logic)
- UI components: `bomana/ui/` (app coordinator, main-window builder, debug support, panel renderer, widgets, dialogs, nav window)
- Utilities: `bomana/utils/` (system, math, file, sound helpers)
- External data: `bomana/data/ccrp_bomb_params.json` (CCRP bomb parameters)
- External data: `bomana/data/fm_speed_limits.json` (机型 IAS/Mach 限速库)
- Tools: `tools/blkx_extractor.py` (generate CCRP bomb parameters from .blkx)
- Tools: `tools/fm_speed_extractor.py` (generate speed-limit DB from datamine flightmodels)
- Tools: `tools/create_version_info.py` / `tools/sample_8111_attitude.py` / `tools/probe_hybrid_8111_clog.py` (build metadata + diagnostics)
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
│  ├─ core/
│  │  ├─ ballistics.py        # Bombing ballistics
│  │  ├─ clog_probe.py        # Optional one-shot clog parser (shared-read + XOR)
│  │  ├─ logic.py             # GameLogic core loop
│  │  ├─ overspeed.py         # Aircraft speed-limit matching + alert grading
│  │  ├─ state.py             # Dataclasses/enums
│  │  └─ telemetry.py         # 8111 fetchers
│  ├─ ui/
│  │  ├─ app.py               # App coordinator (window lifecycle + main UI loop)
│  │  ├─ debug_support.py     # Debug mock snapshot + debug panel helpers
│  │  ├─ dialogs.py           # Settings/About/etc dialogs
│  │  ├─ hud_overlay.py       # Fullscreen HUD overlay skeleton (v6.8.0)
│  │  ├─ main_window.py       # Stable main-window skeleton/card layout builder
│  │  ├─ nav_window.py        # Standalone navigation window
│  │  ├─ panel_renderer.py    # Zone/fuel/bombing/speed panel rendering helpers
│  │  └─ widgets.py           # Pill/HeadingTape widgets
│  └─ utils/
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
│  ├─ sample_8111_attitude.py # HUD baseline sampler
│  ├─ probe_hybrid_8111_clog.py # Optional clog-probe helper
│  ├─ scripts/               # Local build helper scripts (bat/sh)
├─ assets (root files)       # Icons/sponsor image, etc.
└─ README.md                 # Main landing page for GitHub visitors
```

Note: the self-hosted update/statistics service was moved out of this repo; see the README section about `bomana-worker` for the current service repository.

## Runtime Data Flow
1. 8111 API polling via `requests` to `localhost:8111`.
2. State judgement using config classes (Game/Zone/Fuel/etc.).
3. UI render with `tkinter` (timer, panels, hints, debug text).
   - `App` keeps window lifecycle, hotkeys, tray, and the main refresh loop.
   - `MainWindowBuilder` owns the static card/grid skeleton and pre-allocates fixed label pools for the main window.
   - `AppDebugSupport` owns debug-mode mock snapshots and debug text generation.
   - `AppPanelRenderer` owns zone/airport/fuel/bombing/speed strip rendering and mid-panel layout updates.
4. Alerts and sounds via `SoundConfig` + Windows Beep.
5. Overspeed flow:
   - `TelemetryFetcher` reads `type` + IAS/TAS/Mach + `wing_sweep_indicator`.
   - `OverspeedAnalyzer` resolves `/indicators.type` -> `unit_to_fm` -> FM limits.
   - IAS/Mach dual-channel grading (`safe/caution/warning/critical`) drives compact speed strip + alert sound.
6. Optional hybrid probe flow (default disabled):
   - `ENABLE_CLOG_PROBE=False` by default; no behavior change in normal builds.
   - Can be temporarily enabled for local validation with `BOMANA_ENABLE_CLOG_PROBE=1`.
   - When enabled, `GameLogic` schedules one-shot clog parse after ALIVE confirmation (`ClogConfig.TRIGGER_DELAY_SEC`).
   - Parser reads latest `.clog` with Windows shared-read flags, XOR-decrypts tail bytes, and extracts candidate player/vehicle lines.
   - Probe runs in a background thread and updates debug diagnostic state without blocking the main tick loop.
7. Launcher check flow:
   - On startup (and channel switch), launcher auto-checks both app-package metadata and launcher metadata in a background thread.
   - Channel/source/proxy changes during an in-flight check are queued and trigger an automatic follow-up re-check instead of being blocked.
   - Uses Tencent API first (`BOMANA_UPDATE_BASE_URL`) for app and launcher manifests when available.
   - Falls back to GitHub Release metadata when Tencent is unavailable, or when primary only exposes version without downloadable package.
   - Resolves package total size from manifest value or HTTP `Content-Length` probe.
8. Launcher download/apply flow:
   - Download only starts after explicit user confirmation.
   - Streams package with progress and transfer speed updates.
   - Verifies SHA256 (when provided), replaces `app/`, promotes the previous app into `app_previous/`, and updates local version metadata.
   - Launcher rollback swaps `app/` and `app_previous/`, so exactly one previous app version is retained at a time.
   - Launcher self-update downloads a new `Bomana_launcher_v*.exe`, stages it in an isolated OS temp workspace, runs a detached replacement script with literal-path file operations, exits, swaps the executable, and restarts.
   - Launch action stays available for offline local app start while background checks are still running.
9. Launcher telemetry flow: `version_check` / `launcher_start` / `app_launch` / `launcher_update_result` events to Tencent API (best effort).

Important constraint: default runtime data path is official 8111 API only; no memory reads, injection, or game file modifications. Experimental clog probe remains disabled unless explicitly enabled via config.

## Static Data Provenance
- `bomana/data/ccrp_bomb_params.json`
  - Raw source: War Thunder datamine `aces.vromfs.bin_u/gamedata/weapons/bombguns/*.blkx`
  - Generator: `tools/blkx_extractor.py`
  - Runtime consumer: `BombConfig` / CCRP ballistics path
- `bomana/data/fm_speed_limits.json`
  - Raw source: War Thunder datamine `aces.vromfs.bin_u/gamedata/flightmodels/**`
  - Generator: `tools/fm_speed_extractor.py`
  - Cross-check reference: [KaerMorh/WTSpeeder](https://github.com/KaerMorh/WTSpeeder) for legacy FM fields (`Vne` / `VneMach`) and alert thresholds
  - Runtime consumer: `OverspeedAnalyzer` via `/indicators.type -> unit_to_fm -> fm_speed_limits`

## Configuration & Persistence
- Runtime configuration lives in `bomana/config.py`.
- User config/state stored as JSON in the user home directory (`FileConfig.CONFIG_FILE` / `STATE_FILE`).
- Feature flags (`ENABLE_*`) drive compile-time variants and UI availability. All variants share the same config file.

## Functional Areas (Conceptual)
- Timer & lifecycle
- Zone/airfield navigation
- Fuel management
- CCRP bombing predictor
- UI overlays & global hotkeys

## UI Stability & Performance Guardrails
- Keep panel containers structurally stable during transient 8111 data drops (avoid frame-level mount/unmount churn).
- In `ALIVE/LOSS_PENDING`, treat short `/map_obj.json` jitter conservatively by combining map presence with telemetry entity signals.
- Prefer incremental list updates against prebuilt label pools instead of per-frame widget creation or full `pack_forget()/pack()` cycles.
- Keep the main window on a stable grid/card skeleton (`bomana/ui/main_window.py`) and limit `_recalc_size()` to real structural changes.
- Keep integrated heading-tape row mounted and clear content only when heading is temporarily unavailable.
- `HeadingTape` (`bomana/ui/widgets.py`) uses render-signature dedup to skip equivalent canvas redraw frames.
- Standalone nav window rows (`bomana/ui/nav_window.py`) stay mounted; update text/color only to reduce micro-flicker.

## Build & Release
Portable release uses:
- `Bomana_launcher_vX.Y.Z.exe` (universal bootstrap runtime with channel selector)
- `launcher_manifest.json` (launcher version/package metadata + SHA256)
- `Bomana_app_<Variant>_vX.Y.Z.zip` (updatable application package)
- `manifest_<Variant>.json` (channel/version/package metadata + SHA256 + `min_launcher_version`)
- `checksums_*.txt` (SHA256 checksum info)

Local build helper:
- `tools\scripts\build_portable.bat <Variant> <all|app|launcher>`
- `tools\scripts\build_app_package.bat <Variant>` (only app zip + manifest)
- `tools\scripts\build_launcher.bat [version]` (only universal launcher exe)

CI:
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
- `docs/HUD_BASELINE.md` and `docs/bomana_v680_plan.md`: historical HUD design/reference docs

