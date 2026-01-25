# Project Architecture (Bomana)

## Overview
- Entry point: `Bomana.pyw` (single-file app that currently contains UI, logic, and polling)
- Central config: `bomana/config.py` (metadata, feature flags, config classes)
- Core logic: `bomana/core/` (state, telemetry, ballistics, game logic)
- Utilities: `bomana/utils/` (system, math, file, sound helpers)
- External data: `ccrp_bomb_params.py` (CCRP bomb parameters)
- Assets: `app.png`, `sponsor_wechat.png`, `app.ico`

## Repository Layout
```
.
├─ Bomana.pyw                # Main program (GUI + logic + polling)
├─ bomana/
│  ├─ config.py              # Metadata/flags/config classes
│  ├─ core/
│  │  ├─ ballistics.py        # Bombing ballistics
│  │  ├─ logic.py             # GameLogic core loop
│  │  ├─ state.py             # Dataclasses/enums
│  │  └─ telemetry.py         # 8111 fetchers
│  └─ utils/
│     ├─ file_utils.py        # Config/state/resource helpers
│     ├─ math_utils.py        # Navigation/math helpers
│     ├─ sound.py             # Sound manager
│     └─ system.py            # Windows/system helpers
├─ ccrp_bomb_params.py       # Bomb parameters (CCRP)
├─ assets (root files)       # Icons/sponsor image, etc.
├─ build.bat / build.sh      # PyInstaller packaging scripts
└─ *.md                      # Docs, changelog, contribution guide
```

## Runtime Data Flow
1. 8111 API polling via `requests` to `localhost:8111`.
2. State judgement using config classes (Game/Zone/Fuel/etc.).
3. UI render with `tkinter` (timer, panels, hints, debug text).
4. Alerts and sounds via `SoundConfig` + Windows Beep.

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
Use `build.bat` / `build.sh` (PyInstaller) with `ENABLE_*` combinations to generate Enhanced/Standard/Lite.

