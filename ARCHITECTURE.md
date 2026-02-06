# Project Architecture (Bomana)

## Overview
- Entry point: `Bomana.pyw` (single-file app that currently contains UI, logic, and polling)
- Portable launcher: `launcher.pyw` (checks Tencent update API first, falls back to GitHub Release, updates app package, launches app)
- Central config: `bomana/config.py` (metadata, feature flags, config classes)
- Core logic: `bomana/core/` (state, telemetry, ballistics, game logic)
- UI components: `bomana/ui/` (app, widgets, dialogs, nav window)
- Utilities: `bomana/utils/` (system, math, file, sound helpers)
- External data: `ccrp_bomb_params.json` (CCRP bomb parameters)
- Tools: `tools/blkx_extractor.py` (generate CCRP bomb parameters from .blkx)
- Assets: `app.png`, `sponsor_wechat.png`, `app.ico`

## Repository Layout
```
.
├─ Bomana.pyw                # Main program (GUI + logic + polling)
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
│  │  ├─ nav_window.py        # Standalone navigation window
│  │  └─ widgets.py           # Pill/HeadingTape widgets
│  └─ utils/
│     ├─ file_utils.py        # Config/state/resource helpers
│     ├─ math_utils.py        # Navigation/math helpers
│     ├─ sound.py             # Sound manager
│     └─ system.py            # Windows/system helpers
├─ ccrp_bomb_params.json       # Bomb parameters (CCRP)
├─ tools/
│  ├─ blkx_extractor.py      # .blkx -> ccrp_bomb_params.json generator
│  └─ update_service/        # Optional self-hosted update + DAU stats service
├─ tools/build_portable.py   # Build launcher/app package/manifest
├─ assets (root files)       # Icons/sponsor image, etc.
├─ build.bat / build.sh      # Legacy onefile packaging scripts
├─ build_portable.bat        # Portable packaging helper (Windows)
└─ *.md                      # Docs, changelog, contribution guide
```

## Runtime Data Flow
1. 8111 API polling via `requests` to `localhost:8111`.
2. State judgement using config classes (Game/Zone/Fuel/etc.).
3. UI render with `tkinter` (timer, panels, hints, debug text).
4. Alerts and sounds via `SoundConfig` + Windows Beep.
5. Launcher update flow: Tencent API first (`BOMANA_UPDATE_BASE_URL`), GitHub fallback on failure.
6. Launcher telemetry flow: `version_check` / `launcher_start` / `app_launch` events to Tencent API (best effort).

Important constraint: only use the official 8111 API. No memory reads, injection, or game file modifications (see `Bomana.pyw` header rules).

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

## Build & Release
Portable release uses:
- `Bomana香焦_vX.Y.Z.exe` (universal bootstrap runtime with channel selector)
- `Bomana_app_<Variant>_vX.Y.Z.zip` (updatable application package)
- `manifest_<Variant>.json` (channel/version/package metadata + SHA256)

Local build helper:
- `build_portable.bat <Variant> <all|app|launcher>`
- `build_app_package.bat <Variant>` (only app zip + manifest)
- `build_launcher.bat [version]` (only universal launcher exe)

CI:
- `.github/workflows/build.yml` runs separate jobs for:
  - `build_app`: app package + manifest
  - `build_launcher`: launcher exe
- pushing tag `vX.Y.Z` triggers cloud build and release automatically.

