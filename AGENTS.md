# AGENTS.md (Bomana)

This file is the single place for agent guidance and project rules.
Keep it concise and update when workflows or boundaries change.

## Quick Map
- Launcher: `launcher.pyw`
- App entry: `Bomana.pyw`
- Config: `bomana/config.py`
- Core: `bomana/core/` (state, telemetry, ballistics, logic)
- UI: `bomana/ui/` (app, widgets, dialogs, nav window)
- Utilities: `bomana/utils/` (system, math, file, sound)
- CCRP data: `bomana/data/ccrp_bomb_params.json`
- Portable build: `tools/build_portable.py`, `tools/scripts/build_portable.bat`, `tools/scripts/build_app_package.bat`, `tools/scripts/build_launcher.bat`
- Docs: `docs/ARCHITECTURE.md`, `docs/PITFALLS.md`

## Guardrails
- Only use the official 8111 API; no memory reads, injection, or game file edits.
- Respect ENABLE_* feature flags (build variants share one config file).

## Release Signing Workflow
- Treat this workflow as mandatory for every release/update/deploy task, even if the user does not mention signing.
- Release manifests must never be empty-signed or unsigned. `manifest_<Variant>.json` and `launcher_manifest.json` must contain `manifest_signature.algorithm == "ed25519"`, non-empty `key_id`, and non-empty `signature`.
- Required build/CI secrets and env vars: `BOMANA_RELEASE_ED25519_PRIVATE_KEY`, `BOMANA_RELEASE_ED25519_PUBLIC_KEY`, and `BOMANA_RELEASE_SIGNING_KEY_ID` (default `bomana-release-2026-06`). `tools/build_portable.py` must fail if the public key is absent or does not match the private key.
- Do not generate, rotate, overwrite, or upload release signing keys unless the user explicitly asks and confirms the private-key retention plan. Never print private keys in logs or handoffs.
- The release signature covers release-owned core fields only:
  - App: `schema_version`, `channel`, `app_version`, `min_launcher_version`, `entrypoint`, `package_asset`, `package_sha256`.
  - Launcher: `schema_version`, `launcher_version`, `launcher_asset`, `launcher_sha256`, `launcher_size_bytes`.
- TencentCloudPublic / `bomana-update` must not hold the release private key. It only forwards `manifest_signature` from deployed manifests and may add derived fields such as `package_url`, `source_name`, `package_size`, and launcher compatibility `package_sha256`.
- Clients must verify `manifest_signature` before trusting versions, assets, or SHA256. For launcher updates, prefer signed `launcher_sha256` over the service-derived `package_sha256` alias.
- Tencent/EdgeOne update deployment is local-only from the maintainer workstation. Do not deploy update assets from GitHub-hosted Actions to TencentCloudPublic/CVM via SSH, rsync, or scp; that path is intentionally absent because the network is too slow and unreliable.
- If a release session needs deployment, GitHub Actions may build and publish the signed GitHub Release, but the Tencent update deploy command must be run locally:
  ```bash
  uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z
  ```
- Do not add COS/CDN paid artifact storage or switch update assets to paid object storage unless the user explicitly approves the cost.
- Before publishing or deploying update assets, verify:
  ```bash
  gh secret list --repo Thankyou-Cheems/Bomana
  uv run python tools/build_portable.py --target app|launcher|all ...
  uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z
  ```
  Public endpoint verification must call `verify_release_manifest_signature`, not just check that a signature field exists.
- Release signing secrets are provisioned for `bomana-release-2026-06`; if they ever appear missing again, check `gh secret list --repo Thankyou-Cheems/Bomana` and bd issue history for `Bomana-xkf`.

## Header Facts (Condensed)
- Data sources: `/indicators`, `/state`, `/map_obj.json`, `/map_info.json`.
- Tech stack: Python 3.14+, `tkinter`, `requests`, `ctypes` (optional: Pillow, pystray).
- Builds: portable launcher + app package (primary), PyInstaller onefile (legacy).

## Documentation Rules
- If architecture changes (new/split modules, major data-flow changes, core directory renames), update `docs/ARCHITECTURE.md`.
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
- Run the focused tests/smoke/build checks relevant to the touched area.
- Pure documentation or issue-tracking-only tasks may mark Ruff as not applicable in the handoff.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Ruff, tests, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
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
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
- On `main` branch, every `git commit` MUST use `/gc` (`git-commit-smart`) to generate the commit message first
- On `main` branch, do NOT bypass `/gc` by writing a direct commit message and committing immediately
Use 'bd' for task tracking


<!-- BEGIN BEADS INTEGRATION -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Dolt-backed: Issue state lives in beads' local Dolt database, not in git history
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update bd-42 --status in_progress --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task**: `bd update <id> --status in_progress`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: run required quality gates, then `bd close <id> --reason "Done"`

### Storage Model

Bomana uses beads' default project mode:

- Dolt is the source of truth for issue data
- `bd backup status` verifies the local backup state; configure a remote before using `bd backup sync`
- Do not rely on old `bd sync` / `sync-branch` workflows in this repo

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

<!-- END BEADS INTEGRATION -->
