# Pitfalls Log (Bomana)

This file keeps reusable maintenance lessons only. It is not a full incident
timeline; short-lived mistakes, already-obvious missing imports, and retired
implementation plans belong in git history, not here.

## Current Rules

- Treat the official `localhost:8111` API as the only runtime data source.
- Keep update/apply flows transactional: stage first, verify, then swap.
- Keep packaged resource lookup rooted in the app runtime, not the launcher temp directory.
- Use `bd where`, `bd status`, `bd list`, and `bd backup status` for current beads health checks.
- In embedded bd mode, `bd doctor` being unsupported is not a project failure.

## Entries

### 2026-07-11 — pystray runtime state must use callable menu properties

Symptom: after enabling Web Cockpit LAN access, “复制手机访问链接” remained disabled even though the listener and pairing URL were ready.
Root cause: `MenuItem.enabled` received the Boolean value captured while the tray was created; `update_menu()` only re-evaluates callable properties and cannot change that immutable value.
Spec: `docs/specs/web-dashboard.md` `WDB-17` (Draft 2026-07).
Pin: `tests/test_runtime_services.py` exercises the false/true/false LAN-share predicate, while `tests/contracts/test_web_dashboard_contract.py` requires the tray item to bind that callable.

### 2026-07-11 — Windows local HTTP listeners must not enable SO_REUSEADDR

Symptom: two Web Cockpit preview processes both appeared to own `127.0.0.1:8777`, so browser requests could reach a process with a different pairing token.
Root cause: `socketserver.TCPServer.allow_reuse_address=True` maps to permissive Windows `SO_REUSEADDR` behavior instead of merely providing Unix-style quick restart semantics.
Spec: `docs/specs/web-dashboard.md` `WDB-01`, `WDB-08`, `WDB-15` (Draft 2026-07).
Pin: `tests/test_web_dashboard_server.py` requires an active listener to reject a second runtime and still permits address reuse after bounded shutdown.

### 2026-07-11 — Over-conservative weapon models can be operationally useless

Symptom: AIM-120C-5 showed a roughly 15 km two-dimensional cue despite its condition tables supporting much longer high-energy launch references, while glide weapons displayed an iron-bomb trajectory that did not account for lift or guidance.
Root cause: the extractor discarded the condition-table maxima and axes, the solver substituted a one-dimensional missile path length for condition-dependent initial launch separation, failed the whole record on propulsion details even when an independent guidance table existed, and relabelled the available free-fall integration as a guided-ballistic reference.
Spec: `docs/specs/weapon-fire-control.md` `WFC-02`, `WFC-06..WFC-08`, `WFC-10`, `WFC-13` (Draft 2026-07); ADR `docs/adr/0005-datamine-conditional-weapon-envelopes.md`.
Pin: `tests/test_weapon_data_extractor.py` and `tests/contracts/test_weapon_fire_control_schema.py` retain the full conditional tables; `tests/test_weapon_envelope.py`, `tests/test_weapon_solver.py`, `tests/test_map_objects_contract.py`, and `tests/test_panel_presenter.py` require unclipped table interpolation, table-first AAM references, current `dx`/`dy` aspect only, and visibly experimental versus strict-unavailable glide policies.

### 2026-07-11 — An unavailable table condition must not poison an independent fallback

Symptom: AGM-65/RB75 records at high launch altitude returned `guidance_envelope_endpoint_unavailable` because an official `rangeMax` endpoint was zero, even though their ordinary powered point-mass fallback remained supported.
Root cause: the solver treated every non-null conditional-table result as final instead of distinguishing a usable table reference from a launch condition with no table solution.
Spec: `docs/specs/weapon-fire-control.md` `WFC-06`, `WFC-10` (Draft 2026-07).
Pin: `tests/contracts/test_weapon_fire_control_runtime.py` requires the generated AGM-65D high-altitude zero-cell case to continue through the existing glide/unsupported guards and use the supported powered fallback.

### 2026-07-11 — A selected policy is not necessarily the active provider

Symptom: a non-glide AGM solved by the point-mass fallback displayed “FoxThree 兼容临时模型” merely because that was the selected glide policy.
Root cause: the presenter treated `WeaponSolution.model` as the algorithm source even though it records the cross-calculation policy; valid Datamine tables and non-glide fallbacks can run under either policy.
Spec: `docs/specs/weapon-fire-control.md` `WFC-06`, `WFC-13`, `WFC-16` (Draft 2026-07); ADR `docs/adr/0006-selectable-temporary-glide-model.md`.
Pin: `tests/test_panel_presenter.py` requires provider wording to follow the machine-readable solution reason and forbids the FoxThree label on `powered_point_mass_2d` results.

### 2026-07-10 — App helper extraction can strand lifecycle calls after `return`

Symptom: the Windows tray stops initializing even though startup otherwise succeeds and tray support is available.
Root cause: inserting a new `App` helper before the final `__init__` statements accidentally moved the existing `_init_tray()` branch into that helper after an unconditional `return`.
Spec: `docs/ARCHITECTURE.md` runtime-service/UI lifecycle boundary.
Pin: `tests/test_ui_app_config.py` requires the tray call to remain in `App.__init__` and outside `_get_weapon_catalog`.

### 2026-07-10 — A clamped glide proxy can make every weapon the same

Symptom: all 44 generated glide records return the same height-proportional envelope, so GBU-39 and GBU-53 differ in the catalog but not in the solver.
Root cause: every real `0.08 * wingAreaMult / CxK` value fell below the hardcoded 1.5 floor, while mass, caliber, and `dragCx` never entered that path; the available fields also do not establish lift-curve or induced-drag coefficients for a defensible replacement L/D.
Spec: `docs/specs/weapon-fire-control.md` `WFC-07`, `WFC-10`, `WFC-13` (Draft 2026-07).
Pin: `tests/test_weapon_solver.py` preserves this limitation explicitly: the user-selected default compatibility formula is `experimental`, while strict mode still requires `glide_envelope_unavailable`; neither path may relabel the gravity/drag trajectory as practical glide range. ADR 0006 records this deliberate temporary usability tradeoff.

### 2026-07-10 — Modern propulsion blocks are not always a flat motor schedule

Symptom: PGM, AGM-130, ALARM, Kh-31, and YJ-91-family records can show a valid range even though their conditional ignition, airflow/Mach factors, factor-indexed impulses, or instantaneous mass changes were discarded or interpolated across a burn.
Root cause: flattening `propulsionN/impulseN` retained nominal thrust and mass but omitted `propulsionAutopilot`, `propulsionFactorN`, `factorIndex`, and discrete zero-time semantics.
Spec: `docs/specs/weapon-fire-control.md` `WFC-02`, `WFC-05`, `WFC-06`, `WFC-10` (Draft 2026-07).
Pin: `tests/test_weapon_data_extractor.py`, `tests/contracts/test_weapon_fire_control_schema.py`, and `tests/test_weapon_solver.py` retain machine-readable unsupported reasons, keep a valid independent conditional-table reference available, and fail closed only when neither that table nor the fallback is usable.

### 2026-07-10 — Missile `minDistance` is not an AAM engagement minimum

Symptom: an AIM-9L target at 50 m receives a green in-envelope cue because the top-level Datamine `minDistance` is 30 m, while the same record's condition-dependent guidance tables contain minimum ranges in the hundreds or thousands of meters.
Root cause: the solver treated a general top-level field as the lower edge of an AAM envelope even though 8111 does not provide the target aspect, motion, and altitude needed to select a guidance-table cell.
Spec: `docs/specs/weapon-fire-control.md` `WFC-06`, `WFC-08`, `WFC-13` (Draft 2026-07).
Pin: schema/extractor tests retain every guidance-table axis, minimum, maximum, and time value with pointers, while `tests/test_weapon_solver.py` requires a neutral/yellow conditional-table reference and prohibits top-level `minDistance` from becoming the AAM engagement bound.

### 2026-07-10 — Weapon launch TAS is not ground-target closing speed

Symptom: the card can show “time to estimated window” while flying 45 degrees away from the target, with at least a 41 percent geometric error before wind.
Root cause: remaining ground distance was divided by weapon launch speed, which prefers TAS, before alignment was checked.
Spec: `docs/specs/weapon-fire-control.md` `WFC-09`, `WFC-10`, `WFC-13` (Draft 2026-07).
Pin: `tests/test_weapon_scheduler.py` and `tests/test_weapon_solver.py` separate launch physics from aligned positive SOG closure and suppress the countdown while off-axis or opening.

### 2026-07-10 — Fresh Datamine values still need provenance-preserving SI validation

Symptom: refreshing the 82 mm O-832 mortar payload changes its CCRP caliber from `0.082` m to raw `0.82` m, inflating reference area by 100 times even though the source filename, mesh, and physical identity all say 82 mm.
Root cause: the current Datamine record contains a decimal-shift anomaly; blindly copying a newer commit is source-faithful but not physically or dimensionally valid.
Spec: `docs/specs/weapon-fire-control.md` `WFC-01`, `WFC-02`, `WFC-05` (Draft 2026-07).
Pin: `tests/test_quality_ccrp_data.py` and `tests/test_weapon_data_extractor.py` require a narrow Datamine-identity rule, retain raw `0.82`, normalized `0.082`, rule/evidence, and the original JSON pointer, and reject hand-edited output.

### 2026-07-10 — 8111 weapon pulses and `Player` icons are not semantic identity

Symptom: a weapon helper can appear to auto-detect the selected store from `weapon2`, while navigation can silently replace the player's position when a blue squad aircraft also uses the `Player` icon.
Root cause: the real 4,281-frame JAS 39C fixture exposes `weapon2`/`weapon4` only as button/release pulses and contains both a yellow own-aircraft marker and a blue squad marker with `type=aircraft, icon=Player`; neither field name is a sufficient identity contract by itself.
Spec: `docs/specs/weapon-fire-control.md` `WFC-03..WFC-04`, `WFC-08`; `docs/specs/runtime-8111-boundary.md` `R8111-03..R8111-05` (Amended 2026-07).
Pin: `tests/test_8111_replay.py`, `tests/test_map_objects_contract.py`, and `tests/test_weapon_catalog.py` keep selection manual without a verified named field, prefer the explicit/yellow own marker, and expose only current hostile contacts to the two-dimensional estimate.

### 2026-07-10 — Legacy command-guided weapons may not have a modern seeker block

Symptom: AGM-12, AS/AA-20, X-4, Hs 293, Kh-23M, Rb 05A, and Fritz X were omitted from guided fire-control routes or classified as unguided even though their Datamine records expose control authority.
Root cause: classification required modern seeker/autopilot structures and ignored positive legacy `controlSensitivity`; accepting that scalar alone would be too broad, so it must be paired with structured guided-weapon trigger or icon evidence.
Spec: `docs/specs/weapon-fire-control.md` `WFC-01..WFC-02` (Draft 2026-07).
Pin: `tests/contracts/test_weapon_fire_control_schema.py` requires representative AAM, AGM, and bomb records to retain `/rocket/controlSensitivity` or `/bomb/controlSensitivity` and emit `legacy_command`/`command` guidance.

### 2026-07-10 — A validated catalog failure must propagate through the whole UI

Symptom: core startup caught a missing or invalid weapon catalog, but App configuration or main-window construction tried to load the singleton again and could still crash.
Root cause: the catalog validation result was not treated as one process-wide startup decision across core and UI boundaries.
Spec: `docs/specs/weapon-fire-control.md` `WFC-10`, `WFC-12`, `WFC-14` (Draft 2026-07).
Pin: `tests/contracts/test_weapon_fire_control_runtime.py` keeps App/builders on GameLogic's validated catalog result, renders an unavailable state, and disables selection without a second load attempt.

### 2026-07-10 — AAM target disappearance is not ordinary throttled work

Symptom: a hostile aircraft removed from the latest `/map_obj.json` response could retain a valid launch-range cue for the remainder of the 200 ms solver interval.
Root cause: target state was updated before the generic calculation throttle, so a present-to-missing transition could return early without applying a `no_target` result.
Spec: `docs/specs/weapon-fire-control.md` `WFC-08`, `WFC-10..WFC-11`; `docs/specs/runtime-8111-boundary.md` `R8111-03` (Draft/Amended 2026-07).
Pin: `tests/contracts/test_weapon_fire_control_runtime.py` and `tests/test_weapon_scheduler.py` require the disappearance transition to bypass throttling and clear the valid cue in the current calculation cycle.

### 2026-07-10 — CCRP keys and Datamine source IDs are not always identical

Symptom: CCRP-routed bombs whose catalog ID retains a `_bomb` suffix failed lookup and silently inherited the previously selected bomb's physics; an old saved CCRP key could also fall back to the default weapon during migration.
Root cause: the legacy CCRP asset trims suffixes from some keys, while the new catalog uses the Datamine source filename stem as its stable ID, and startup initially tried only the legacy key.
Spec: `docs/specs/weapon-fire-control.md` `WFC-07`, `WFC-10` (Draft 2026-07).
Pin: `tests/contracts/test_weapon_fire_control_schema.py` requires catalog-to-CCRP ID/source-stem parity; `tests/contracts/test_weapon_fire_control_runtime.py` pins source-ID alias resolution, `tests/test_ui_app_config.py` pins legacy-key migration, and `tests/test_weapon_scheduler.py` requires unresolved physics to fail closed.

### 2026-07-10 — Artifact Attestations do not replace a UAC publisher certificate

Symptom: the protected Program Files broker design could not ship because the free project had no practical Authenticode certificate, while requiring a separate installer made the feature unusable.
Root cause: build provenance and Windows publisher identity are different trust systems; GitHub can attest which workflow produced a file, but Windows UAC does not consume that attestation as an Authenticode identity.
Spec: `docs/specs/startup-elevation.md` `ELEV-02..ELEV-12`; `docs/specs/release-signing.md` `SIGN-12..SIGN-14`; ADR `docs/adr/0003-minimal-privileged-hotkey-broker.md`.
Pin: Ordinary hotkeys start first; the bundled broker is hash-checked and locked before explicit UAC, installs nothing, and release assets receive `actions/attest@v4` provenance while the UI honestly warns that UAC shows Unknown publisher.

### 2026-07-10 — UAC handoff elevated a mutable Python App package

Symptom: game-foreground hotkeys worked after whole-App elevation, but the UAC child imported and executed the user-writable `app/` Python tree.
Root cause: the integrity workaround moved the entire application across the privilege boundary instead of isolating the one capability that required it.
Spec: `docs/specs/startup-elevation.md` `ELEV-01..ELEV-12` (Amended 2026-07); ADR `docs/adr/0003-minimal-privileged-hotkey-broker.md`.
Pin: `tests/contracts/test_startup_elevation_contract.py`, `tests/test_hotkey_broker.py`, and native broker tests prohibit elevated mutable App code and constrain the broker to fixed `RegisterHotKey` actions.

### 2026-07-10 — Separate the Windows integrity boundary from the Tk hotkey bug

Symptom: F7-F11 registered successfully but were silent only while a higher-integrity War Thunder window had focus; Explorer focus restored delivery.
Root cause: same-session tests of current HEAD and an exact `fa1899cf^` worktree both failed in the game, and the relevant pre/post-spec hotkey sources were identical. `RegisterHotKey`, raw input, and a low-level probe all stopped receiving physical keys at the same higher-integrity foreground boundary, so the spec migration was not the cause. Separately, the old worker listener really did call `root.after(...)` across threads and could die with `RuntimeError`; the Tk-owned message-only window remains a valid lifecycle fix even though it cannot cross Windows integrity levels.
Spec: `docs/specs/startup-elevation.md` `ELEV-01..ELEV-12`; `docs/specs/threading-ui-contract.md` `THREAD-02`, `THREAD-04`, `THREAD-08`, `THREAD-09`, `HOTKEY-01..HOTKEY-04`; `docs/specs/runtime-8111-boundary.md` `R8111-08`.
Pin: Keep one `RegisterHotKey` registration per enabled action per lifecycle, with Tk-owned local delivery or fixed-action broker delivery through `TkEventDispatcher`. Do not add hooks, raw-input fallback, key polling, automatic re-registration, broad process scans, or memory access. The only game query is the visible-window executable/elevation allowlist used to decide whether an optional UAC action is useful.

### Launcher Update Safety

- Context: launcher self-update from protected or unusual install paths such as `Desktop\[Bomana]\`
  Symptom: update failed before restart with `WinError 5`, or replacement failed when paths contained wildcard characters like `[]`
  Cause: self-update staged a fixed temp exe inside the install directory and the apply script used non-literal PowerShell paths
  Fix/Workaround: stage self-update files in a unique OS temp workspace, keep only the result marker in the install dir, and use literal-path PowerShell operations for every file move/remove

- Context: interrupted app update or concurrent launchers
  Symptom: `app/` could disappear after rollback, or two launchers could race on the install target
  Cause: rollback deleted `app/` too early and there was no cross-process install lock or startup recovery for leftover staging directories
  Fix/Workaround: make rollback state-aware, add a cross-process update lock with stale-lock cleanup, and recover `app_new` / `app_backup` on startup

- Context: launcher checking GitHub releases after a launcher-only latest release
  Symptom: app update check failed with `未找到发布清单: manifest_<Channel>.json` even though older app releases existed
  Cause: fallback queried only `/releases/latest`, but launcher-only releases do not include app manifests
  Fix/Workaround: after a latest-release miss, inspect recent releases and pick the first one containing the app manifest and matching asset

### Update Service Networking

- Context: Tencent update source under unstable networks or proxy modes
  Symptom: launcher reported primary service unavailable too aggressively, hid useful `HTTP 5xx` details, or showed generic TLS errors such as `UNEXPECTED_EOF_WHILE_READING`
  Cause: single short timeout attempts, swallowed HTTP error bodies, identity-bound request failures, and local fake-ip DNS modes all looked like the same endpoint failure
  Fix/Workaround: use multi-attempt checks, surface HTTP error body detail, retry once anonymously before fallback, and detect fake-ip resolution so users get a targeted proxy/DNS hint

- Context: Actions deploy-manifests workflow uploading to the update server
  Symptom: `scp` failed with `Permission denied` on `/opt/stacks/bomana-update/data/manifests/manifest_*.json`
  Cause: CI SSH user lacked direct write permission after ownership/ACL drift
  Fix/Workaround: upload to remote `/tmp` staging first, then sync into the target directory with a direct-write check and passwordless-`sudo` fallback

- Context: GitHub-hosted Actions uploading release assets to TencentCloudPublic/CVM
  Symptom: SSH/rsync upload of app packages or launcher exe ran at roughly 10 KB/s and could stall release deployment for tens of minutes
  Cause: the GitHub-hosted runner to Tencent network path is slow/unreliable, while the Tencent host also cannot reliably pull from GitHub directly
  Fix/Workaround: keep GitHub Actions limited to signed Release builds; deploy Tencent/EdgeOne update assets only from the maintainer workstation with `tools/deploy_update_assets.py`

### Packaging And Release Hygiene

- Context: automated quality gates after adding pytest-style test functions
  Symptom: local `pytest` ran more tests than `tools/scripts/check_smoke.bat`, or new tests did not appear in `git status`
  Cause: smoke used `unittest discover` while part of the suite used pytest function tests, and `.gitignore` ignored `tests/` / `test_*.py`
  Fix/Workaround: keep smoke on `uv run --extra dev pytest`, keep tests trackable in git, and use `tests/README.md` naming boundaries as the suite grows

- Context: running pytest from WSL with temp files rooted in Windows `%TEMP%`
  Symptom: `uv run --extra dev pytest` failed before running tests with `FileNotFoundError` from pytest fd capture cleanup
  Cause: `tempfile.TemporaryFile().truncate()` can fail when Python resolves temp files under `/mnt/c/Users/.../AppData/Local/Temp`
  Fix/Workaround: run with `TMPDIR=/tmp`, or configure the smoke command/pytest capture mode to avoid fd capture in that environment

- Context: Windows CI packaging or release asset upload
  Symptom: `UnicodeEncodeError` when printing paths, or GitHub rewrote Chinese asset names into underscored names
  Cause: Windows CI console encoding can be cp1252, and GitHub normalizes non-ASCII/special characters in release asset names
  Fix/Workaround: log through encoding-safe output and keep release asset names ASCII-only; put localized text in release notes

- Context: Windows PowerShell 5.1 parser checks for release smoke scripts
  Symptom: GitHub Actions failed while parsing a `.ps1` file with errors far from the real source line, such as unexpected `\System32` or broken here-strings
  Cause: Windows PowerShell 5.1 can decode UTF-8-without-BOM scripts through the runner's ANSI code page, so non-ASCII literals can corrupt later string parsing
  Fix/Workaround: keep committed `.ps1` source ASCII-safe and construct required localized path/button text at runtime with explicit Unicode code points; keep a parser test that runs under Windows PowerShell

- Context: running `tools/build_portable.py` builds concurrently
  Symptom: `feature_profile.py` remained dirty after build, or older build scripts failed while reading version literals from config files
  Cause: variant packaging temporarily patches `bomana/config/feature_profile.py`; version metadata lives in `bomana/metadata.py`
  Fix/Workaround: do not run build variants in parallel; keep version reads pointed at `metadata.py`; preserve/restore the original feature profile only when the build script actually patched it

- Context: portable app launched from the PyInstaller onefile launcher
  Symptom: app code resolved assets under the launcher's `_MEI...` temp path, causing missing aircraft limits or data files
  Cause: launcher and app ran in one process, so `sys._MEIPASS` and cached `bomana.*` modules could point at the launcher bundle instead of the extracted app runtime
  Fix/Workaround: export a stable app runtime root such as `BOMANA_RUNTIME_ROOT`, prefer app/module paths over `_MEIPASS`, clear cached `bomana` modules, and install an app-package-first `bomana.*` finder before handing off to the app package

- Context: source-mode launch after changing the Windows `.pyw` association
  Symptom: launcher opened, but app launch failed with `No module named 'requests'`
  Cause: source mode used the current interpreter while dependencies existed only in the repo `.venv`
  Fix/Workaround: prepend repo `.venv` `site-packages` during source-mode launch; if missing, run `uv sync --python 3.14 --extra build`

- Context: Windows `uv run` after a partial or broken virtualenv creation
  Symptom: `uv run ...` failed before the command with `failed to remove file ...\.venv\lib64: Access is denied`
  Cause: `.venv\lib64` was a self-referential reparse point and the virtualenv lacked the normal Windows `Scripts` directory, so uv could not repair it in place
  Fix/Workaround: recreate the repo virtualenv with `uv sync --python 3.14 --extra dev` after removing the broken `.venv`; for stdlib-only maintainer scripts, use the system Python only as a temporary workaround and still repair uv before quality gates

### 8111 Runtime Stability

- Context: opening map/scoreboard in battle
  Symptom: UI flashed, timer briefly collapsed to `加入战斗中`, or CPU/frame time spiked
  Cause: short `/map_obj.json` and `/state` empty frames were treated as real player loss, while full panel relayout/redraw amplified the visual jitter
  Fix/Workaround: debounce player loss in `ALIVE`, delay pending API hints, reuse the last valid telemetry/map snapshot during short unstable windows, keep nav rows mounted, and avoid full relayout/redraw when data is equivalent

- Context: in-game 8111 field naming drift
  Symptom: speed monitoring stopped showing IAS/Mach or failed to match aircraft limits while the feature remained enabled
  Cause: telemetry parsing accepted only a narrow set of `/state` and `/indicators` keys
  Fix/Workaround: parse compatible aliases for IAS/TAS/Mach/type and keep future payload parsing tolerant

- Context: Bomana starts in hangar, then the player enters battle without restarting the app
  Symptom: heading could stay wrong/unavailable and zone geometry could use the wrong battle scale
  Cause: battle setup could reuse hangar-period `map_info` cache, and a missing compass key was interpreted as a valid `0°` heading instead of falling back to the map velocity vector
  Fix/Workaround: clear battle-scoped map/navigation cache when arming a new battle, refetch `map_info` in battle context, and track whether the compass field was actually present before preferring it

- Context: Bomana resumes after quitting a live sortie, then the player later enters a different battle
  Symptom: the saved 15-minute countdown could leak into the new battle and continue from an unrelated remaining time
  Cause: timer restore used only persisted remaining time and did not verify whether the next observed battle context matched the saved one
  Fix/Workaround: persist a battle signature derived from current 8111 map metadata/object layout, hold restore in a pending state on startup, and apply it only after the next live battle context matches; otherwise discard the stale timer state

### HUD And Navigation Geometry

- Context: transparent HUD overlay on Windows
  Symptom: HUD became an opaque black window on some systems
  Cause: Tk `-transparentcolor` plus alpha alone is not reliable; if color-key transparency is not applied, the canvas background renders as black
  Fix/Workaround: set the Win32 color key explicitly with `SetLayeredWindowAttributes(..., LWA_COLORKEY | LWA_ALPHA)` and keep HUD background/canvas colors identical to that key

- Context: HUD target projection
  Symptom: target marker was too close to screen center at larger angles, went above the horizon during dives, or drifted heavily at long range
  Cause: projection mixed linear angle mapping, separate pitch/lookdown scales, Y-only roll approximation, and normalized map-distance assumptions
  Fix/Workaround: use perspective `tan(angle) / tan(fov/2)` projection, merge lookdown and pitch into one vertical angle with distance-adaptive pitch gain, rotate offsets with a full 2D matrix, and use `map_info` axis scaling for bearing/distance/ground-speed

- Context: integrated or standalone heading tape on maps where no zone enters the heading gate
  Symptom: zone rows populated, but the tape looked blank or stayed near `无目标`
  Cause: core navigation can leave every zone with `is_target=False`; the tape previously rendered overflow cues only for active targets
  Fix/Workaround: for tape rendering only, fall back to the smallest-angle zone as display-primary without changing core target-lock semantics

- Context: closing the standalone navigation window
  Symptom: the window disappeared, but integrated navigation did not return and the saved mode remained `standalone`
  Cause: the title-bar X reused temporary `hide()` lifecycle behavior instead of performing a presentation-mode transition
  Fix/Workaround: route X/WM close through the idempotent navigation mode service; reserve `hide()` for temporary history-mode suspension

- Context: deriving an ownship Trace back point through short 8111 instability
  Symptom: a failed/empty map response could freeze a stale or false crash location
  Cause: cached map fallback is suitable for UI continuity but is not fresh evidence of player presence or loss
  Fix/Workaround: sample and invalidate Trace back candidates only from raw successful map responses, then promote a point only at the existing confirmed loss transition

### UI And Dialog Layout

- Context: settings dialog opened on taller tabs such as overspeed
  Symptom: Save/Cancel buttons could be pushed below the visible area
  Cause: fixed-height dialog content without a scroll body
  Fix/Workaround: make settings content scrollable and keep the footer action row fixed

- Context: launcher progress during update check
  Symptom: progress looked like a download was finishing during the check phase, and status text changes could resize the window
  Cause: check phase reused download-like progress behavior and allowed layout reflow from changing status text
  Fix/Workaround: split check/download states, keep check progress indeterminate, and calculate geometry from the current canvas width

- Context: launcher or dialogs resized after opening
  Symptom: text and controls visibly changed size while dragging the window, making the interface feel unstable and occasionally shifting layout more than the resize itself
  Cause: legacy UI code treated window width/height deltas as a font scaling signal on top of DPI and user text scaling
  Fix/Workaround: keep font sizing DPI/config driven, allow only wrap-length/layout reflow on resize, and avoid resize-triggered recursive font replacement

- Context: optional administrator hotkeys while the overlay is locked/click-through
  Symptom: the App displayed an authorization action that could not be clicked in-game, and users did not know they had to switch out and unlock first
  Cause: the privilege recovery path existed only inside the click-through overlay and looked like ordinary text
  Fix/Workaround: use persistent styled buttons, explain the lock-key step, and expose the same consent action dynamically in the tray through the Tk dispatcher

### Data Files

- Context: CCRP bomb selector in packaged/runtime environments
  Symptom: bomb selector showed `0/0` bombs with no clear reason even though `ccrp_bomb_params.json` was shipped
  Cause: bomb database loading used separate path resolution and swallowed load failures into an empty in-memory database
  Fix/Workaround: resolve bomb JSON through the shared runtime-aware resource search, preserve a visible `load_error`, and surface it in the selector/settings UI

### 2026-07-11 — 清单项目不要把标记与正文放进固定宽度 Label

- 症状：提高 UI/文本缩放后，出击检查清单的 `○` 会独占一行，短中文指令也被拆成两三行，面板留下大量无效纵向空间。
- 原因：项目使用 `○ + 正文` 的单个 Label，并把 `wraplength` 固定为 `180 * scale`，没有使用卡片已经获得的实际宽度。
- 约束：重复的清单/步骤 UI 应将标记放在固定列、正文放在弹性列；正文换行宽度必须跟随实时容器宽度，换行后还要触发窗口高度回收。

### Beads Maintenance

- Context: cleanup after upgrading Bomana to `bd 1.0.4`
  Symptom: old issues and notes still described pre-1.0 migration failures, external Dolt server setup, and legacy sync commands
  Cause: historical upgrade work remained after the project moved to the current embedded Dolt backend
  Fix/Workaround: retire old `bd sync`, manual `.beads/dolt/**/LOCK` cleanup, raw Dolt SQL schema commits, and hand-started `127.0.0.1:3307` server recipes. If auto-export warns because `.beads/` is ignored, prefer `bd config set export.git-add false` over changing repo ignore policy.

- Context: mixing WSL dev `bd 1.0.5` with Windows release `bd 1.0.4`
  Symptom: Windows `bd create ... --json` failed with `Field 'id' doesn't have a default value`, and `bd status --json` failed with `column "depends_on_id" could not be found`; WSL `/home/cheems/dev/Beads/bd` 1.0.5 could still read the same database
  Cause: the dev 1.0.5 binary wrote a forward embedded Dolt schema (`depends_on_issue_id`, non-default event IDs) while Windows remained on release 1.0.4, whose command paths expect `depends_on_id` and `events.id DEFAULT uuid()`
  Fix/Workaround: keep Bomana on Windows `bd 1.0.4` until 1.0.5 is officially installed everywhere. If the forward schema is already present, export with the 1.0.5 binary, back up `.beads`, rebuild with Windows `bd init --from-jsonl -p Bomana --database beads_Bomana`, restore the original `project_id`, then verify `bd status`, `bd create`, and `bd close`.
