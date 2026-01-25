# AGENTS.md (Bomana)

This file is the single place for agent guidance and project rules.
Keep it concise and update when workflows or boundaries change.

## Quick Map
- Entry: `Bomana.pyw`
- Config: `bomana/config.py`
- Core: `bomana/core/` (state, telemetry, ballistics, logic)
- UI: `bomana/ui/` (widgets, dialogs, nav window)
- Utilities: `bomana/utils/` (system, math, file, sound)
- CCRP data: `ccrp_bomb_params.py`
- Docs: `ARCHITECTURE.md`, `PITFALLS.md`

## Guardrails
- Only use the official 8111 API; no memory reads, injection, or game file edits.
- Respect ENABLE_* feature flags (build variants share one config file).

## Header Facts (Condensed)
- Data sources: `/indicators`, `/state`, `/map_obj.json`, `/map_info.json`.
- Tech stack: Python 3.8+, `tkinter`, `requests`, `ctypes` (optional: Pillow, pystray).
- Builds: PyInstaller; variants driven by ENABLE_* (Enhanced/Standard/Lite).

## Documentation Rules
- If architecture changes (new/split modules, major data-flow changes, core directory renames), update `ARCHITECTURE.md`.
- If a task fails in a new way, add a short entry to `PITFALLS.md`.

## Expected Task Flow
1. Locate target code in `Bomana.pyw` or `bomana/` modules.
2. Make minimal, safe edits; preserve existing comments and header rules.
3. Update docs per rules above.
