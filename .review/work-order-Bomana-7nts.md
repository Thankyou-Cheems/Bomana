# Bomana 8 Web Control And Launcher 3 Work Order

> Repo: `D:\Dev\Bomana`
> Tracker: `Bomana-7nts`
> This work order governs the current change. `AGENTS.md` and accepted specs
> remain higher-priority constraints; a real conflict requires a stop report.

## 0. Execution role

The root agent owns integration and is the only writer until implementation is
complete. Read-only exploration and the final read-only review may be delegated.
Any later concurrent writer must receive a disjoint path scope first. Every
production phase ends with an isolated read-only review and a PASS or a punch
list. Re-planning may change decomposition, but not the invariants below.

## 1. Project context

- App entry: `Bomana.pyw`; Tk coordinator: `bomana/ui/app.py`.
- Web runtime: `bomana/web/`; packaged UI: `bomana/assets/web/`.
- Launcher entry: `launcher.pyw`; launcher helpers: `launcher/`.
- App version source: `bomana/metadata.py`; launcher version source:
  `launcher/metadata.py`.
- Canonical contracts: `docs/specs/`; decisions: `docs/adr/`.
- Existing Web Cockpit is a paired, standalone, read-only projection of a frozen
  `UISnapshot`; it does not poll or proxy port 8111.
- Existing versions are App 7.0.0 and Launcher 2.1.1. This change establishes
  App 8.0.0 and Launcher 3.0.0 as a deliberate compatibility boundary.

## 2. Invariants

- **INV-1 Official boundary:** Runtime game data remains limited to official
  loopback 8111 routes `/indicators`, `/state`, `/map_obj.json`, and
  `/map_info.json`; no injection, memory, packet, log, or game-file path.
- **INV-2 Thread ownership:** HTTP workers never touch Tk, App state, or config
  persistence directly. Commands cross `TkEventDispatcher.post()` and execute
  on the Tk owner thread.
- **INV-3 Control authorization:** Every successful pairing receives a distinct
  session. Loopback may receive control scope; LAN remains view-only until the
  user explicitly enables LAN control for the current run. LAN/control state is
  never persisted. Writes require control scope, exact non-empty same-origin
  `Origin`, CSRF proof, bounded JSON matching the shared schema, and an
  idempotency key.
- **INV-4 Fixed semantic actions:** Web buttons invoke allowlisted Bomana
  actions and target states; they do not synthesize F-keys, execute arbitrary
  commands, or extend the elevated broker/network boundary.
- **INV-5 Variant authority:** `ENABLE_*` flags remain authoritative. Web or
  persisted settings cannot re-enable a build-disabled capability.
- **INV-6 Release trust:** Manifest schema/signature field sets and
  verify-before-trust ordering remain unchanged. No signing key, deployment,
  release upload, or private-key action is authorized by this work order.
- **INV-7 Compatibility:** App 8.0.0 requires Launcher 3.0.0 or newer. Launcher
  3.0.0 rejects launch, online install, local import, rollback, and recovery for
  App versions below 8.0.0 or malformed versions, before replacing or swapping
  a valid install. Online staged package metadata must exactly equal the
  already-verified signed manifest App version.
- **INV-8 Dependencies:** Use Python stdlib, tkinter, and current dependencies;
  add no new runtime package.
- **INV-9 Cleanup:** Delete only resolved, in-repo generated caches/artifacts on
  the audited whitelist. Preserve `.venv`, recordings, `.beads`, `.review`,
  runtime state/logs/downloads, and untracked source.
- **INV-10 Verification honesty:** Do not skip, delete, or weaken tests. Report
  phone/LAN, Firewall, multi-NIC, packaged UI, DPI, and live-game checks as
  manual unless actually performed.
- **INV-11 App identity:** Packaged App 8.0.0 must validate a present, strict,
  Launcher 3.0.0-or-newer identity before diagnostics, Tk, GameLogic, listener,
  or other runtime initialization. Only an explicit non-frozen source/development
  marker may bypass that requirement, and the exception must be behaviorally
  tested.

## 3. Workflow and landing rules

- Durable contract changes land in `docs/specs/` before production code.
- Architecture changes update `docs/ARCHITECTURE.md`; the read-only ADR decision
  is superseded with a new ADR rather than silently rewritten.
- Task status remains in `bd`; no Markdown TODO tracker is created.
- Root is the integration owner for `bomana/web/__init__.py`, shared schemas,
  launcher bootstrap signatures, metadata, and test registration.
- No deploy command will run. The final change is committed on `main` only after
  `/gc` (`git-commit-smart`) generates the commit message, then pulled with
  rebase and pushed as required by `AGENTS.md`.

## 4. Ownership and forbidden workarounds

- Current writer scope after approval: root may write only paths named by this
  work order and directly related tests/docs. Explorers and reviewers are
  read-only.
- Forbidden actions: deploy scripts; signing-key access/rotation; manifest
  signature-shape changes; automatic LAN/firewall/UPnP/elevation; arbitrary
  file/config paths; keyboard simulation; broker network access; permissive
  CORS; `0.0.0.0`; silent default changes; test deletion/skipping; broad
  `git clean`; deletion outside the verified workspace root.
- Narrow QA-only exception: `tools/scripts/packaged_launcher_smoke.ps1` may
  synthesize the Launcher's `Ctrl+Enter` shortcut only after its exact packaged
  process window is verified as the current foreground window, and it must
  release every pressed key in `finally`. This exception is not available to
  Web dispatch, App semantic actions, production runtime services, or broker
  paths, and a failed foreground check must emit no input.
- Any diff outside the declared implementation paths is a phase failure unless
  ownership is explicitly revised in this work order first.

### Exact implementation path allowlist (recorded before production writes)

Only the following repository files may be created or edited for this change:

- `.review/work-order-Bomana-7nts.md`
- `.review/intake.json`
- `.review/checks.json`
- `.review/ledger.json`
- `.review/report.md`
- `.gitignore`
- `AGENTS.md`
- `Bomana.pyw`
- `bomana_version.py` (new shared strict version boundary)
- `bomana/metadata.py`
- `bomana/ui/app.py`
- `bomana/ui/dialogs.py`
- `bomana/ui/runtime_services.py`
- `bomana/web/__init__.py`
- `bomana/web/control.py` (new)
- `bomana/web/server.py`
- `bomana/assets/web/index.html`
- `bomana/assets/web/dashboard.css`
- `bomana/assets/web/dashboard.js`
- `launcher.pyw`
- `launcher/bootstrap.py`
- `launcher/install_txn.py`
- `launcher/metadata.py`
- `tools/build_portable.py`
- `tools/scripts/packaged_launcher_smoke.ps1`
- `pyproject.toml`
- `uv.lock`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`
- `docs/CONTRIBUTING.md`
- `docs/PRIVACY.md`
- `docs/QUICKSTART.md`
- `docs/PITFALLS.md` (added after final review confirmed a new recovery
  prevalidation failure mode; required by `AGENTS.md` before resolving it)
- `docs/adr/0008-authenticated-web-control-and-v8-boundary.md` (new)
- `docs/guides/web-cockpit-smoke.md`
- `docs/specs/config-variants.md`
- `docs/specs/threading-ui-contract.md`
- `docs/specs/version-compatibility.md` (new)
- `docs/specs/web-dashboard.md`
- `docs/specs/schemas/web-dashboard-command.schema.json` (new)
- `docs/specs/schemas/web-dashboard-command-response.schema.json` (new)
- `docs/specs/schemas/web-dashboard-control-state.schema.json` (new)
- `tests/contracts/test_config_variants.py`
- `tests/contracts/test_launcher_package_boundaries.py`
- `tests/contracts/test_version_compatibility.py` (new)
- `tests/contracts/test_web_dashboard_contract.py`
- `tests/test_build_metadata.py`
- `tests/test_launcher_core.py`
- `tests/test_launcher_launch_flow.py`
- `tests/test_launcher_update_service.py`
- `tests/test_quality_packaged_launcher_smoke.py`
- `tests/test_runtime_services.py`
- `tests/test_ui_app_config.py`
- `tests/test_version_boundary.py` (new)
- `tests/test_weapon_selector.py`
- `tests/test_web_dashboard_control.py` (new)
- `tests/test_web_dashboard_server.py`

If implementation proves that any other file is required, work must stop for
an explicit allowlist amendment before that file is edited.

### Generated-artifact cleanup whitelist (recorded before deletion)

Deletion is limited to these resolved paths under `D:\Dev\Bomana` when they
exist; no wildcard may escape the named directories:

- `D:\Dev\Bomana\dist\`
- `D:\Dev\Bomana\build\`
- `D:\Dev\Bomana\.pytest_cache\`
- `D:\Dev\Bomana\.ruff_cache\`
- `D:\Dev\Bomana\__pycache__\`
- `D:\Dev\Bomana\bomana\__pycache__\`
- `D:\Dev\Bomana\bomana\config\__pycache__\`
- `D:\Dev\Bomana\bomana\core\__pycache__\`
- `D:\Dev\Bomana\bomana\ui\__pycache__\`
- `D:\Dev\Bomana\bomana\utils\__pycache__\`
- `D:\Dev\Bomana\bomana\web\__pycache__\`
- `D:\Dev\Bomana\launcher\__pycache__\`
- `D:\Dev\Bomana\tests\__pycache__\`
- `D:\Dev\Bomana\tests\contracts\__pycache__\`
- `D:\Dev\Bomana\tools\__pycache__\`
- `D:\Dev\Bomana\native\hotkey_broker\target\`
- `D:\Dev\Bomana\native\hotkey_broker_setup\target\`
- `C:\Users\cheb2\AppData\Local\Temp\Bomana packaged QA July11\`
  (exact packaged-smoke workspace created during this work order; this does
  not authorize deleting any parent or sibling under the system Temp root)
- `C:\Users\cheb2\AppData\Local\Temp\tmpq8anydnd\`
  (exact empty probe directory left by the denied dangling-link test; this
  does not authorize deleting any parent or sibling under the system Temp root)

Explicitly preserved: `.venv`, `recordings`, `.beads`, `.review`,
`launcher_state.json`, `.bomana_install_id`, launcher logs/downloads,
`bomana/bin`, and all untracked source directories.

### Active ownership log

- `contract_writer` owns only: `docs/specs/web-dashboard.md`,
  `docs/specs/threading-ui-contract.md`, `docs/specs/config-variants.md`,
  `docs/specs/version-compatibility.md`,
  `docs/adr/0008-authenticated-web-control-and-v8-boundary.md`, the three new
  `docs/specs/schemas/web-dashboard-*.schema.json` files,
  `tests/contracts/test_web_dashboard_contract.py`,
  `tests/contracts/test_config_variants.py`,
  `tests/contracts/test_launcher_package_boundaries.py`, and
  `tests/contracts/test_version_compatibility.py`.
- Root remains integration owner and, during the contract-writing turn, may
  edit only this work order. Production-code ownership will be recorded after
  the contract phase passes self-check and meta-traceability.
- Contract phase completed after schema self-check, meta-traceability, Ruff,
  and `git diff --check`; `contract_writer` is now read-only and owns no active
  production path.
- `web_protocol` owns only: `bomana/web/__init__.py`,
  `bomana/web/control.py`, `bomana/web/server.py`,
  `tests/test_web_dashboard_control.py`, and
  `tests/test_web_dashboard_server.py`; this scope is complete and ownership
  has returned to root for integration-only corrections.
- `launcher_compat` owns only: `bomana_version.py`, `Bomana.pyw`,
  `launcher.pyw`, `launcher/bootstrap.py`, `launcher/install_txn.py`,
  `launcher/metadata.py`, `tools/scripts/packaged_launcher_smoke.ps1`,
  `tests/test_launcher_core.py`, `tests/test_launcher_launch_flow.py`,
  `tests/test_launcher_update_service.py`,
  `tests/test_quality_packaged_launcher_smoke.py`, and
  `tests/test_version_boundary.py`; this scope is complete and ownership has
  returned to root for integration-only corrections.
- `web_frontend` owns only: `bomana/assets/web/index.html`,
  `bomana/assets/web/dashboard.css`, and
  `bomana/assets/web/dashboard.js`; this scope is complete and now read-only.
- `release_docs` owns only: `AGENTS.md`, `README.md`,
  `docs/ARCHITECTURE.md`, `docs/CHANGELOG.md`, `docs/CONTRIBUTING.md`,
  `docs/PRIVACY.md`, `docs/QUICKSTART.md`, and
  `docs/guides/web-cockpit-smoke.md`; this scope is complete and ownership has
  returned to root for integration-only corrections.
- Root owns the remaining allowlisted production, integration-test, metadata,
  build, documentation, cleanup, review, and landing paths. No writer may edit
  another owner's paths without this log being amended first.

## 5. Fixed phase order

1. **Baseline and evidence (complete):** restore prior task history, run intake,
   verify the clean baseline (`535 passed`, `12 subtests`), audit Web, launcher,
   versions, signing, and generated artifacts.
2. **Contracts:** amend Web/thread/config contracts, add a superseding ADR,
   command/control-state schemas, contract tests, and manual smoke cases.
3. **Web control plane:** add scoped sessions, CSRF/origin/body/idempotency
   validation, immutable control state, dispatcher bridge, App-owned commands,
   shared weapon/model persistence, mobile action buttons, and settings UI.
4. **Launcher UX and launch preferences:** modernize tkinter hierarchy; add
   persisted loopback Web autostart and optional local-page auto-open; preserve
   proxy fallback, updates, rollback retention, ordinary integrity, and signing.
5. **Compatibility and version boundary:** enforce App minimum on launch/import/
   rollback; bump App 8.0.0, Launcher 3.0.0, package metadata, lockfile, docs,
   and build constants while keeping release manifest schema v1.
6. **Cleanup and verification:** remove only audited generated artifacts; run
   focused tests, full pytest, Ruff check/format, metadata/package smoke,
   `git diff --check`, meta-traceability, and isolated read-only review.
7. **Landing:** resolve the review ledger, close `Bomana-7nts`, verify `bd`
   backup status, `/gc`, commit, pull --rebase, push, prune, and prove `main` is
   clean and up to date.

## 6. Required commands

```powershell
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest
uv run --extra dev pytest tests/test_web_dashboard_server.py tests/test_runtime_services.py
uv run --extra dev pytest tests/test_launcher_update_service.py tests/test_build_metadata.py
git diff --check
bd backup status
```

Manual-only gates remain the physical phone/LAN/control revoke test, Windows
Firewall and multi-NIC behavior, packaged Launcher DPI/keyboard pass, and live
War Thunder hotkey/weapon-selection synchronization.

## 7. Checkpoint and escalation

Production/spec implementation must not begin until the user sends:

`APPROVED BOMANA-7NTS`

Checkpoint satisfied by the user on 2026-07-11 with the exact token above and
seven normative clarifications now incorporated into INV-3, INV-4, INV-7,
INV-11, the path allowlist, and the cleanup allowlist.

Stop and report if an invariant conflicts with current source, if a new runtime
dependency or signed manifest field is required, if compatibility cannot fail
closed before replacement, or if an accepted test contradicts the revised
canonical contract.
