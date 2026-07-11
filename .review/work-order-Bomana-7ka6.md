# Bomana LAN and App UX Follow-up Work Order

> Repo: `D:\Dev\Bomana`
> Tracker: `Bomana-7ka6`
> Authorized outcome: the user's 2026-07-12 ten-point follow-up
> Baseline: App 8.1.0 / Launcher 3.0.0 at commit `24456ca`

## 1. Outcome

Unify LAN access and control behind one explicit enable action, expose the LAN
startup preference in Launcher, preserve automatic adapter discovery, repair
the App's bottom-content clipping, add a dynamically zooming speed strip and
configurable timer period, replace the timer bar with a banana-outline progress
indicator, and make App wording and clickable affordances concise and clear.

## 2. Invariants

- `INV-1`: LAN listeners MUST bind every successfully discovered exact RFC1918
  IPv4 address and MUST NOT contain machine-specific `10.x`/`192.168.x`
  endpoints, bind `0.0.0.0`, edit Firewall state, probe the Internet, or add a
  generic network capability.
- `INV-2`: Enabling LAN is the sole user-facing LAN action and grants LAN
  control for that enabled interval; disabling LAN MUST revoke all LAN sessions
  and control authority immediately.
- `INV-3`: Every Web write MUST retain exact non-empty same-origin `Origin`,
  per-session CSRF, bounded schema validation, bounded per-session idempotency,
  control scope, and Tk-owner-thread authority/target rechecks.
- `INV-4`: Launcher persistence may add only the explicit boolean LAN startup
  preference alongside the existing Web autostart and local auto-open booleans;
  it MUST NOT persist ports, addresses, pairing data, sessions, CSRF, or runtime
  authorization epochs.
- `INV-5`: Timer duration MUST be a bounded explicit target state shared by App,
  tray, Web schema, persisted App config, logic, snapshots, and restore guards;
  malformed/out-of-range values fail closed.
- `INV-6`: UI compression MUST remove widgets from geometry when their text is
  intentionally absent, and dynamic wrapping MUST trigger a bounded expansion
  reflow so the bottom card never obscures the weapon panel at supported
  scale/DPI combinations.
- `INV-7`: The speed strip MUST remain progressive below the zoom threshold and
  continuously interpolate into a focused threshold view beginning at 70% of
  the first breakup threshold.
- `INV-8`: All App click targets MUST expose a coordinated border or shadow,
  pointer cursor, and hover feedback; non-clickable text MUST not mimic that
  affordance.
- `INV-9`: No new runtime dependency, keyboard synthesis, reflection, arbitrary
  callback/command, signing-key access, deploy, upload, unsigned release bypass,
  or version-validation weakening is authorized.
- `INV-10`: Tests MUST NOT be skipped/deleted/weakened to pass; automated checks
  MUST NOT be described as physical-phone, live-game, Firewall, or packaged-DPI
  evidence.

Any conflict with an invariant stops the affected phase; do not work around it.

## 3. Phase order and checkpoint

1. Capture baseline evidence, freeze this work order, then amend canonical
   specs and contract tests before production code.
2. Implement timer, presenter, clickable-affordance, speed-strip, banana widget,
   and clipping fixes without changing LAN authority.
3. **CHECKPOINT:** report the canonical LAN/Launcher contract and await the
   explicit token `APPROVED BOMANA-7KA6-LAN` before production edits that make
   LAN enablement grant control or persist the Launcher LAN startup preference.
4. Implement the approved LAN/Launcher boundary, then browser/Tk/package/full
   validation, independent read-only review, cleanup, commit, pull-rebase, push.

## 4. Exact implementation path allowlist

Recorded before the first production-code write. Only these files may be
created or edited:

- `.review/work-order-Bomana-7ka6.md`
- `.review/audit-Bomana-7ka6/intake.json` (added before audit generation)
- `.review/audit-Bomana-7ka6/checks.json` (added before audit generation)
- `.review/audit-Bomana-7ka6/ledger.json` (added before audit generation)
- `.review/audit-Bomana-7ka6/findings.json` (reserved before audit generation)
- `.review/audit-Bomana-7ka6/report.md` (added before audit generation)
- `launcher.pyw`
- `launcher/bootstrap.py`
- `launcher/metadata.py`
- `bomana_version.py`
- `bomana/metadata.py`
- `bomana/config/settings.py`
- `bomana/core/logic.py`
- `bomana/core/state.py`
- `bomana/utils/file_utils.py`
- `bomana/ui/app.py`
- `bomana/ui/dialogs.py`
- `bomana/ui/main_window.py`
- `bomana/ui/nav_window.py`
- `bomana/ui/panel_presenter.py`
- `bomana/ui/panel_renderer.py`
- `bomana/ui/runtime_services.py`
- `bomana/ui/tk_style.py`
- `bomana/ui/widgets.py`
- `bomana/web/control.py`
- `bomana/web/server.py`
- `bomana/web/snapshot.py`
- `bomana/assets/web/index.html`
- `bomana/assets/web/dashboard.css`
- `bomana/assets/web/dashboard.js`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`
- `docs/PITFALLS.md`
- `docs/PRIVACY.md`
- `docs/QUICKSTART.md`
- `docs/guides/web-cockpit-smoke.md`
- `docs/specs/config-variants.md`
- `docs/specs/timer-cycle.md` (new)
- `docs/specs/ui-presenter-boundary.md`
- `docs/specs/web-dashboard.md`
- `docs/specs/schemas/web-dashboard-command.schema.json`
- `docs/specs/schemas/web-dashboard-control-state.schema.json`
- `docs/specs/schemas/web-dashboard-snapshot.schema.json`
- `pyproject.toml`
- `uv.lock`
- `README.md`
- `tools/scripts/packaged_launcher_smoke.ps1` (added before edit because the
  packaged Launcher handoff fixture must carry the new explicit LAN boolean)
- `tests/contracts/test_config_variants.py`
- `tests/contracts/test_timer_cycle_contract.py` (new)
- `tests/contracts/test_ui_presenter_boundaries.py`
- `tests/contracts/test_version_compatibility.py`
- `tests/contracts/test_web_dashboard_contract.py`
- `tests/test_build_metadata.py`
- `tests/test_file_utils_persistence.py`
- `tests/test_launcher_launch_flow.py`
- `tests/test_launcher_update_service.py` (added before edit because the
  Launcher 3.1.0 version bump changes an update-available fixture baseline)
- `tests/test_panel_presenter.py`
- `tests/test_panel_renderer.py`
- `tests/test_quality_packaged_launcher_smoke.py`
- `tests/test_runtime_services.py`
- `tests/test_timer_cycle.py` (new)
- `tests/test_timer_restore_guard.py`
- `tests/test_tk_style.py`
- `tests/test_ui_app_config.py`
- `tests/test_ui_geometry.py`
- `tests/test_weapon_selector.py` (added before edit because the shared App
  weapon-selection label no longer exposes `手选`)
- `tests/test_web_dashboard_control.py`
- `tests/test_web_dashboard_presenter.py`
- `tests/test_web_dashboard_server.py`

Any additional path MUST be added here explicitly before editing it.

## 5. Generated-artifact cleanup whitelist

Deletion is limited to these resolved directories under `D:\Dev\Bomana`:

- `dist/`
- `build/`
- `.pytest_cache/`
- `.ruff_cache/`
- `__pycache__/`
- `bomana/__pycache__/`
- `bomana/config/__pycache__/`
- `bomana/core/__pycache__/`
- `bomana/ui/__pycache__/`
- `bomana/utils/__pycache__/`
- `bomana/web/__pycache__/`
- `launcher/__pycache__/`
- `tests/__pycache__/`
- `tests/contracts/__pycache__/`
- `tools/__pycache__/`
- `native/hotkey_broker/target/`
- `native/hotkey_broker_setup/target/`

No broad `git clean`; preserve `.venv`, `.beads`, `.review`, recordings,
runtime state/logs, download caches, tracked assets, and untracked source.

## 6. Required proof

- Behavioral tests for auto-discovered multi-address listeners, one-action LAN
  control grant/revocation, Launcher preference handoff and persistence filter.
- Schema/adversarial tests for bounded timer duration and shared control state.
- Tk geometry regression proving wrapped weapon content remains above the bottom
  card after reflow at narrow widths and supported scale settings.
- Headless speed projection tests proving monotonic fill below the trigger,
  continuous zoom, and dynamic marker stretching.
- Tk widget tests for banana outline progress and clickable borders/hover state.
- Browser desktop/mobile QA for timer setting and control completion semantics.
- Ruff check/format, focused tests, full pytest, package metadata/assets, build
  attempt under the signing contract, `git diff --check`, `bd backup status`.
- Physical phone, Firewall, live-game and packaged-DPI remain manual unless
  actually exercised.

## 7. Forbidden workarounds

Do not skip/delete tests, mock away Web authorization or version checks, persist
runtime LAN secrets, hard-code local addresses, bind wildcard interfaces,
synthesize keys, access signing secrets, run deployment, or publish artifacts.

## 8. Checkpoint evidence (pre-LAN production phase)

- Canonical contracts were amended before production writes for the unified LAN
  target, the third Launcher boolean, timer-cycle ownership, dynamic speed
  projection, clickable surfaces, and expansion-only geometry reflow.
- Focused non-LAN behavioral/contract suite passed on 2026-07-12 (169 tests):
  timer bounds and restore, UI presenter/geometry, speed projection, weapon copy,
  clickable styles, App config, and Web command/presenter paths.
- Focused Ruff check and format check passed for all non-LAN production/test
  paths touched in this phase.
- Local Web QA passed in the Codex in-app browser at the normal desktop viewport
  and 390 x 844: the 60-minute cycle was consistent in summary/control state,
  the input exposed bounds 1..180, mobile controls remained visible without
  horizontal overflow, and the console contained no errors.
- The temporary QA listener on 127.0.0.1:8878 was stopped after inspection.
- No production write has crossed the LAN grant/persistence checkpoint. The
  exact approval token remains `APPROVED BOMANA-7KA6-LAN`.

## 9. LAN checkpoint release

- The user supplied the exact token `APPROVED BOMANA-7KA6-LAN` on 2026-07-12.
- Production implementation after that token may cross only the already frozen
  LAN grant and Launcher preference boundary in Sections 1..7; every invariant,
  forbidden workaround, path allowlist, and cleanup restriction remains active.

## 10. Final verification record

- Unified LAN implementation binds every successfully discovered exact RFC1918
  address, then grants control before returning. A control-grant failure removes
  all newly added Hosts/listeners; disabling LAN advances authorization and
  invalidates every LAN session before listener teardown.
- Launcher persists exactly three strict booleans and hands them to the App as
  strict `0`/`1` environment values. Selecting LAN forces Web autostart; clearing
  Web autostart clears LAN. Real Tk probing confirmed the third checkbox and
  dependency behavior at a 675 px required window height on a 1080 px display.
- App `8.2.0` and Launcher `3.1.0` metadata, lockfile, changelog, compatibility
  tests, and public documentation agree. Compatibility floors remain App 8.0.0
  and Launcher 3.0.0 because the optional third preference safely defaults off.
- Real browser QA submitted a 45-minute target, observed queued-to-succeeded
  completion, and saw both summary and control state update to 45 on desktop and
  390 x 844 layouts with no console errors. The temporary listener was stopped.
- Full pytest, full Ruff check, full Ruff format check, and `git diff --check`
  pass after the independent-review fixes. A real `App(root)` startup/automatic
  shutdown probe also passes.
- A real Enhanced `--target all` release build compiled the bundled native
  broker and then failed closed at the required missing
  `BOMANA_RELEASE_ED25519_PRIVATE_KEY`; no key was generated/read, no signing
  bypass was used, and no deploy/upload action ran.
- First independent Audit found and registered two issues: a real-Tk membership
  crash in clickable styling and stale English LAN security copy. Both were
  fixed, pinned by real-Tk/contract tests, resolved against passing check
  `C-0243dab0`, and recorded in `docs/PITFALLS.md`; the audit ledger now has no
  open findings. Final independent re-review remains the last review gate.
- A second fresh reviewer found stale English Quickstart preference count and a
  system-emoji dependency in the banana silhouette. The fixes now document all
  three booleans and draw the silhouette from the existing Canvas geometry;
  focused contracts, real-Tk geometry, and full gates pass. The same reviewer
  returned final `PASS` after a read-only re-review of both fixes.
