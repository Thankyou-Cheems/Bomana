# Bomana Cross-Surface Cockpit Follow-up Work Order

> Repo: `D:\Dev\Bomana`
> Tracker: `Bomana-mv6j`
> Authorization: the user's direct 11-point change request and "继续任务"
> Governed baseline: App 8.0.0 / Launcher 3.0.0 at commit `6f94803`

## 1. Outcome and acceptance

This change aligns the Tk App and Web Cockpit, fixes simultaneous physical-LAN
and EasyTier access, and adds an official loopback tactical-map image with a
selected-weapon range overlay. Completion requires evidence for every one of
the user's 11 numbered outcomes; automated tests must not be described as a
physical iPhone, Firewall, packaged-DPI, or live-game smoke.

## 2. Invariants

- Official game data remains loopback-only. The only new endpoint may be the
  official read-only `/map.img`; it is fetched by an App-owned bounded image
  fetcher, never proxied from an HTTP request worker, and never generalized to
  an arbitrary URL or base address.
- Web listeners bind exact eligible RFC1918 interface addresses. They must not
  bind `0.0.0.0`, auto-edit Windows Firewall, persist LAN state, or expose a
  generic network capability.
- HTTP workers remain limited to immutable App-published projections/assets.
  Tk writes retain the established session/origin/CSRF/schema/idempotency and
  owner-thread reauthorization boundary.
- Official weapon envelopes always take precedence. The persisted internal
  model IDs remain compatibility data; public copy only explains whether an
  estimated substitute may be used when official data is absent.
- No new runtime dependency, signing change, release upload, deploy, broker
  action, keyboard synthesis, game-file access, or launcher compatibility
  change is authorized.
- Existing App 8 / Launcher 3 fail-closed boundaries remain unchanged.

## 3. Phase order

1. Freeze this path/cleanup boundary and capture baseline evidence.
2. Amend canonical 8111, Web, threading, weapon-wording, and UI contracts plus
   contract tests before production changes.
3. Implement the bounded map-image pipeline and multi-address LAN listeners.
4. Implement Web visual/copy/map/range changes.
5. Implement visible App Web pairing and compact App panel changes.
6. Run focused, browser/Tk, package, Ruff, and full-suite gates; clean only the
   whitelist; review; land through `/gc`, pull-rebase, and push.

## 4. Exact implementation path allowlist

Recorded before the first production-code write. Only these files may be
created or edited for `Bomana-mv6j`:

- `.review/work-order-Bomana-mv6j.md`
- `.review/intake.json`
- `.review/checks.json`
- `.review/ledger.json`
- `.review/report.md`
- `bomana/core/logic.py`
- `bomana/core/state.py`
- `bomana/core/telemetry.py`
- `bomana/metadata.py` (added before the App 8.1.0 release-boundary edit)
- `bomana/ui/app.py`
- `bomana/ui/dialogs.py`
- `bomana/ui/debug_support.py` (added before edit because its fixed bottom-card
  debug rows must move with the new compact Web-access row)
- `bomana/ui/main_window.py`
- `bomana/ui/panel_presenter.py`
- `bomana/ui/panel_renderer.py`
- `bomana/ui/runtime.py`
- `bomana/ui/runtime_services.py`
- `bomana/web/server.py`
- `bomana/web/snapshot.py`
- `bomana/assets/web/index.html`
- `bomana/assets/web/dashboard.css`
- `bomana/assets/web/dashboard.js`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md` (added before the App 8.1.0 release-boundary edit)
- `docs/PITFALLS.md`
- `docs/PRIVACY.md` (added before edit because its single-address disclosure
  conflicts with the new exact multi-address listener lifecycle)
- `docs/QUICKSTART.md`
- `docs/guides/web-cockpit-smoke.md`
- `docs/specs/runtime-8111-boundary.md`
- `docs/specs/threading-ui-contract.md`
- `docs/specs/ui-presenter-boundary.md`
- `docs/specs/weapon-fire-control.md`
- `docs/specs/web-dashboard.md`
- `docs/specs/schemas/web-dashboard-snapshot.schema.json`
- `pyproject.toml` (added before the App 8.1.0 release-boundary edit)
- `uv.lock` (added before the App 8.1.0 release-boundary edit)
- `README.md` (added before the App 8.1.0 release-boundary edit)
- `tests/contracts/test_runtime_8111_boundary.py`
- `tests/contracts/test_version_compatibility.py` (added before replacing the
  stale current-version-equals-minimum assertion for App 8.1.0)
- `tests/contracts/test_threading_ui_contract.py`
- `tests/contracts/test_ui_presenter_boundary.py`
- `tests/contracts/test_web_dashboard_contract.py`
- `tests/test_core_8111_stability.py`
- `tests/test_panel_presenter.py`
- `tests/test_panel_renderer.py`
- `tests/test_runtime_services.py`
- `tests/test_runtime_threading.py`
- `tests/test_telemetry_fetch_result.py`
- `tests/test_ui_app_config.py`
- `tests/test_ui_geometry.py`
- `tests/test_weapon_selector.py`
- `tests/test_web_dashboard_presenter.py`
- `tests/test_web_dashboard_server.py`

If another path is required, this file must be amended explicitly before that
path is edited. The project PNG is read from the existing tracked
`bomana/assets/branding/app.png`; this work order does not authorize replacing
that source asset.

## 5. Generated-artifact cleanup whitelist

Deletion is limited to these resolved directories under `D:\Dev\Bomana`:

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
- `D:\Dev\Bomana\native\hotkey_broker\target\` (added after the authorized
  package QA attempt compiled the bundled broker before signing failed closed)
- `D:\Dev\Bomana\native\hotkey_broker_setup\target\` (same exact generated
  native cache class, if present)

No broad `git clean` is permitted. Preserve `.venv`, `.beads`, `.review`,
`recordings`, App/Launcher state and logs, download caches, native binaries,
untracked source, and every path not listed above.

## 6. Required proof

- Focused contract/unit tests for the new endpoint owner, bounded image body,
  immutable image publication, exact-IP multi-listener lifecycle, host checks,
  LAN revocation, map range projection, public model wording, and App layout.
- Browser viewport checks for desktop and narrow mobile, including real project
  logo, compact controls, timer placement, tactical image/range overlay, and
  absence of the legacy provider name in public UI.
- Tk builder/presenter checks for visible pairing and compact one-line fuel,
  speed focus, timer, weapon, and elevation copy.
- `uv run --extra dev ruff check .`
- `uv run --extra dev ruff format --check .`
- `uv run --extra dev pytest`
- relevant portable/package metadata and asset checks
- `git diff --check`, `bd backup status`, clean pushed `main`

Physical iPhone access to both `192.168.31.69` and `10.126.126.2`, Windows
Firewall prompting, packaged DPI, and live War Thunder `/map.img` behavior are
manual-only unless actually exercised in this session.

## 7. Verification record

- Focused contracts/presenter/server/Tk tests passed after implementation.
- Full suite passed after the final failure-path regression test: `644`
  collected tests with no failures (plus the existing subtest coverage).
- Ruff check passed; Ruff format check reported all 142 files formatted.
- Host-local real-interface smoke bound one selected port on both
  `192.168.31.69` and `10.126.126.2`; both exact addresses returned HTTP 200.
- Chrome desktop and 390x844 responsive QA passed with the project PNG logo,
  compact action layout, countdown-adjacent progress, provider-neutral model
  copy, semi-transparent map image, weapon-range ellipse, and no console errors.
- App 8.1.0 metadata, pyproject, lockfile, App-8/Launcher-3 minimum boundary,
  docs, and compatibility tests agree. Launcher remains 3.0.0.
- A real App release build compiled the bundled native broker, then correctly
  failed closed because no authorized `BOMANA_RELEASE_ED25519_PRIVATE_KEY` was
  present. No key was generated/read and no unsigned manifest bypass was used;
  the automated three-variant package/resource metadata tests passed.
- Physical iPhone, Windows Firewall prompt, packaged DPI, and live War Thunder
  `/map.img` were not claimed. Generated `dist`, `build`, native `target`, Ruff,
  pytest, and allowlisted project bytecode caches were removed afterward.
