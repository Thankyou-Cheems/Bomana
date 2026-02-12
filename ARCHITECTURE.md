# Project Architecture (Bomana)

## Overview
- Entry point: `Bomana.pyw` (runtime selector: Tk default, optional WinUI3 host mode)
- Portable launcher: `launcher.pyw` (startup auto-check, Tencent version check + GitHub fallback, check/download split, offline launch, details/support dialog)
- Central config: `bomana/config.py` (metadata, feature flags, config classes)
- Core logic: `bomana/core/` (state, telemetry, ballistics, game logic)
- UI components: `bomana/ui/` (app, widgets, dialogs, nav window)
- WinUI bridge/runtime: `bomana/ui/winui_bridge.py`, `bomana/ui/winui_host.py` (phase-1 migration scaffolding)
- Utilities: `bomana/utils/` (system, math, file, sound helpers)
- External data: `ccrp_bomb_params.json` (CCRP bomb parameters)
- Tools: `tools/blkx_extractor.py` (generate CCRP bomb parameters from .blkx)
- WinUI docs: `winui/README.md`, `winui/SNAPSHOT_API.md`
- Assets: `app.png`, `sponsor_wechat.png`, `app.ico`

## Repository Layout
```
.
├─ Bomana.pyw                # Main program entry (Tk default / WinUI3 optional)
├─ launcher.pyw              # Green launcher (auto update + bootstrap)
├─ bomana/
│  ├─ config.py              # Metadata/flags/config classes
│  ├─ core/
│  │  ├─ ballistics.py        # Bombing ballistics
│  │  ├─ logic.py             # GameLogic core loop
│  │  ├─ state.py             # Dataclasses/enums
│  │  └─ telemetry.py         # 8111 fetchers
│  ├─ ui/
│  │  ├─ app.py               # App (Tk UI orchestrator)
│  │  ├─ dialogs.py           # Settings/About/etc dialogs
│  │  ├─ hud_overlay.py       # Fullscreen HUD overlay skeleton (v6.8.0)
│  │  ├─ nav_window.py        # Standalone navigation window
│  │  ├─ winui_bridge.py      # Local HTTP snapshot bridge for WinUI frontend
│  │  ├─ winui_host.py        # WinUI frontend process host/launcher
│  │  └─ widgets.py           # Pill/HeadingTape widgets
│  └─ utils/
│     ├─ file_utils.py        # Config/state/resource helpers
│     ├─ math_utils.py        # Navigation/math helpers
│     ├─ sound.py             # Sound manager
│     └─ system.py            # Windows/system helpers
├─ winui/
│  ├─ Bomana.WinUI3/          # WinUI3 frontend project (Fluent UI)
│  ├─ README.md               # WinUI migration notes / runtime switch
│  └─ SNAPSHOT_API.md         # Bridge contract for frontend polling
│
├─ ccrp_bomb_params.json       # Bomb parameters (CCRP)
├─ tools/
│  ├─ blkx_extractor.py      # .blkx -> ccrp_bomb_params.json generator
│  └─ update_service/        # Optional self-hosted update + DAU stats service
├─ tools/build_portable.py   # Build launcher/app package/manifest (+optional WinUI runtime assets)
├─ tools/build_winui_frontend.py # Build/export WinUI3 runtime to winui/dist
├─ assets (root files)       # Icons/sponsor image, etc.
├─ build.bat / build.sh      # Legacy onefile packaging scripts
├─ build_portable.bat        # Portable packaging helper (Windows)
└─ *.md                      # Docs, changelog, contribution guide
```

## Runtime Data Flow
1. 8111 API polling via `requests` to `localhost:8111`.
2. State judgement using config classes (Game/Zone/Fuel/etc.).
3. UI runtime:
   - `tk` (default): render with `tkinter` (`bomana/ui/app.py`)
   - `winui3` (optional): run `WinUISnapshotBridge` + external WinUI3 frontend EXE
4. WinUI bridge flow (`BOMANA_UI_RUNTIME=winui3`):
   - `WinUISnapshotBridge` polls `GameLogic.tick()/snapshot()` in Python
   - exposes `/snapshot` and `/health` over local loopback HTTP
   - `winui_host` injects bridge URL via environment variables to frontend process
5. Alerts and sounds via `SoundConfig` + Windows Beep (Tk path).
6. Launcher check flow:
   - On startup (and channel switch), launcher auto-checks update metadata.
   - Uses Tencent API first (`BOMANA_UPDATE_BASE_URL`) for version/manifest when available.
   - Falls back to GitHub Release metadata when Tencent is unavailable, or when primary only exposes version without downloadable package.
   - Resolves package total size from manifest value or HTTP `Content-Length` probe.
7. Launcher download/apply flow:
   - Download only starts after explicit user confirmation.
   - Streams package with progress and transfer speed updates.
   - Verifies SHA256 (when provided), replaces `app/`, and updates local version metadata.
   - Launch action stays available for offline local app start.
8. Launcher telemetry flow: `version_check` / `launcher_start` / `app_launch` events to Tencent API (best effort).

Important constraint: only use the official 8111 API. No memory reads, injection, or game file modifications (see `Bomana.pyw` header rules).

## Configuration & Persistence
- Runtime configuration lives in `bomana/config.py`.
- User config/state stored as JSON in the user home directory (`FileConfig.CONFIG_FILE` / `STATE_FILE`).
- Feature flags (`ENABLE_*`) drive compile-time variants and UI availability. All variants share the same config file.
- Runtime UI selection is env-based in phase 1: `BOMANA_UI_RUNTIME=auto|tk|winui3` (`auto` default).

## Functional Areas (Conceptual)
- Timer & lifecycle
- Zone/airfield navigation
- Fuel management
- CCRP bombing predictor
- UI overlays & global hotkeys

## UI Stability & Performance Guardrails
- Keep panel containers structurally stable during transient 8111 data drops (avoid frame-level mount/unmount churn).
- In `ALIVE/LOSS_PENDING`, treat short `/map_obj.json` jitter conservatively by combining map presence with telemetry entity signals.
- Prefer incremental list updates in `bomana/ui/app.py` (update visible labels and hide only overflow items) instead of per-frame full `pack_forget()/pack()` cycles.
- Keep integrated heading-tape row mounted and clear content only when heading is temporarily unavailable.
- `HeadingTape` (`bomana/ui/widgets.py`) uses render-signature dedup to skip equivalent canvas redraw frames.
- Standalone nav window rows (`bomana/ui/nav_window.py`) stay mounted; update text/color only to reduce micro-flicker.

## Build & Release
Portable release uses:
- `Bomana_launcher_vX.Y.Z.exe` (universal bootstrap runtime with channel selector)
- `Bomana_app_<Variant>_vX.Y.Z.zip` (updatable application package)
- `manifest_<Variant>.json` (channel/version/package metadata + SHA256)
- `checksums_*.txt` (SHA256 checksum info)

Local build helper:
- `build_portable.bat <Variant> <all|app|launcher>`
- `build_app_package.bat <Variant>` (only app zip + manifest)
- `build_launcher.bat [version]` (only universal launcher exe)
- `build_winui_frontend.bat [Debug|Release] [x64|x86|ARM64]` (export WinUI runtime to `winui/dist`)

CI:
- `.github/workflows/build.yml` runs separate jobs for:
  - `build_app`: app package + manifest
  - `build_launcher`: launcher exe
- tag-driven release targets:
  - `vX.Y.Z`: full release (launcher + app packages)
  - `vX.Y.Z-app`: app packages only
  - `vX.Y.Z-launcher`: launcher only
- `workflow_dispatch` also supports `build_target=all|app|launcher`.

