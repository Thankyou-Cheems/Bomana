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
- CCRP data: `ccrp_bomb_params.json`
- Portable build: `tools/build_portable.py`, `build_portable.bat`, `build_app_package.bat`, `build_launcher.bat`
- Docs: `ARCHITECTURE.md`, `PITFALLS.md`

## Guardrails
- Only use the official 8111 API; no memory reads, injection, or game file edits.
- Respect ENABLE_* feature flags (build variants share one config file).

## Header Facts (Condensed)
- Data sources: `/indicators`, `/state`, `/map_obj.json`, `/map_info.json`.
- Tech stack: Python 3.8+, `tkinter`, `requests`, `ctypes` (optional: Pillow, pystray).
- Builds: portable launcher + app package (primary), PyInstaller onefile (legacy).

## Documentation Rules
- If architecture changes (new/split modules, major data-flow changes, core directory renames), update `ARCHITECTURE.md`.
- If a task fails in a new way, add a short entry to `PITFALLS.md`.

## Expected Task Flow
1. Locate target code in `Bomana.pyw` or `bomana/` modules.
2. Make minimal, safe edits; preserve existing comments and header rules.
3. Update docs per rules above.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
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
- `beads-sync` commits are exempt from `/gc` (auto-sync/manual sync commits allowed)
- On `main` branch, do NOT bypass `/gc` by writing a direct commit message and committing immediately
Use 'bd' for task tracking


<!-- BEGIN BEADS INTEGRATION -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Auto-syncs to JSONL for version control
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
5. **Complete**: `bd close <id> --reason "Done"`

### Auto-Sync

bd automatically syncs with git:

- Exports to `.beads/issues.jsonl` after changes (5s debounce)
- Imports from JSONL when newer (e.g., after `git pull`)
- No manual export/import needed!

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
