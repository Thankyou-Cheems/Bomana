# AGENTS.md (Bomana)

This file routes agents to the right code, docs, and workflow contracts.
Keep durable project rules in `docs/specs/`; keep this router concise.

## Quick Map
- Launcher entry: `launcher.pyw` (distribution/PyInstaller entrypoint)
- Launcher package: `launcher/` (manifest projection, download cache, install transactions, bootstrap metadata)
- App entry: `Bomana.pyw`
- Config: `bomana/config/` (package marker: `__init__.py`; feature flags: `feature_profile.py`; settings: `settings.py`; static data: `static_data.py`)
- Core: `bomana/core/` (state, telemetry, ballistics, logic)
- UI: `bomana/ui/` (app, widgets, dialogs, nav window)
- Utilities: `bomana/utils/` (system, math, file, sound)
- CCRP data: `bomana/data/ccrp_bomb_params.json`
- Portable build: `tools/build_portable.py`, `tools/scripts/build_portable.bat`, `tools/scripts/build_app_package.bat`, `tools/scripts/build_launcher.bat`
- Docs: `docs/ARCHITECTURE.md`, `docs/PITFALLS.md`, `docs/specs/`

## Guardrails
- Canonical specs live in `docs/specs/`; update them before duplicating durable rules elsewhere.
- Only use the official 8111 API; no memory reads, injection, or game file edits. See `docs/specs/runtime-8111-boundary.md`.
- Respect ENABLE_* feature flags. See `docs/specs/config-variants.md`.
- Tk UI work must cross background threads through `TkEventDispatcher` or a Tk-owned queue; background threads must not call Tk APIs directly. See `docs/specs/threading-ui-contract.md`.
- Keep the launcher and Python App at ordinary integrity; ordinary hotkeys start first, and only an explicit user-confirmed action may elevate the bundled fixed-action native broker. See `docs/specs/startup-elevation.md`.

## Release Signing Workflow
- For every release/update/deploy task, follow `docs/specs/release-signing.md` before acting.
- Verify manifests before trusting version, asset, SHA256, entrypoint, or URL fields; see `SIGN-03`.
- Keep release private keys off unapproved hosts and deploy Tencent/EdgeOne update assets locally only; see `SIGN-05` and `SIGN-07`:
  ```bash
  uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z
  ```

## Header Facts (Condensed)
- Data sources: `/indicators`, `/state`, `/map_obj.json`, `/map_info.json`.
- Tech stack: Python 3.14+, `tkinter`, `requests`, `ctypes` (optional: Pillow, pystray).
- Builds: portable launcher + app package (primary), PyInstaller onefile (legacy).

## Documentation Rules
- If architecture changes (new/split modules, major data-flow changes, core directory renames), update `docs/ARCHITECTURE.md`.
- If an invariant or cross-module contract changes, update the relevant file under `docs/specs/` and its contract test.
- If a task fails in a new way, add a short entry to `docs/PITFALLS.md`.

## Expected Task Flow
1. Locate target code in `Bomana.pyw` or `bomana/` modules.
2. Make minimal, safe edits; preserve existing comments and header rules.
3. Update docs per rules above.

## Quality Gates
- For every code-changing task, including `bd`/beads tasks, run Ruff before closing the task:
  ```bash
  uv run --extra dev ruff check .
  uv run --extra dev ruff format --check .
  ```
- When native hotkey broker code changes, also run its Cargo format check, runtime broker tests, and `uv run python tools/build_hotkey_broker.py --mode dev`; see `QG-10`.
- Run the focused tests/smoke/build checks relevant to the touched area.
- Pure documentation or issue-tracking-only tasks may mark Ruff as not applicable in the handoff.

## Landing the Plane (Session Completion)

**When ending a work session**, complete ALL steps below. Work is normally NOT complete until `git push` succeeds, unless an active ADR/bd decision explicitly sets a narrower closeout policy.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Ruff, tests, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - Mandatory except for an explicitly authorized commit-only task recorded in an active ADR/bd decision:
   ```bash
   git pull --rebase
   bd backup status
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Default work is NOT complete until `git push` succeeds
- For explicit commit-only work, do not push until the user authorizes it
- If push is required and fails, resolve and retry until it succeeds
- On `main` branch, every `git commit` MUST use `/gc` (`git-commit-smart`) to generate the commit message first
- On `main` branch, do NOT bypass `/gc` by writing a direct commit message and committing immediately

## Issue Tracking

- Use `bd` for all project task tracking; do not create Markdown TODO lists or a duplicate external tracker.
- Start with `bd ready --json`, claim work with `bd update <id> --status in_progress --json`, and close it only after verification.
- Create discovered work with a `discovered-from:<parent-id>` dependency and use `--json` for programmatic commands.
- Dolt is the issue source of truth. Verify it with `bd backup status`; do not restore retired `bd sync` or `sync-branch` workflows.
- See `docs/CONTRIBUTING.md` for the maintained command examples and contributor workflow.
