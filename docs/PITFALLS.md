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

- Context: running `tools/build_portable.py` builds concurrently
  Symptom: `config.py` remained dirty after build, or older build scripts failed while reading version literals from `config.py`
  Cause: variant packaging temporarily patches `bomana/config.py`; version metadata now lives in `bomana/metadata.py`
  Fix/Workaround: do not run build variants in parallel; keep version reads pointed at `metadata.py`; preserve/restore the original config file only when the build script actually patched it

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

### Data Files

- Context: CCRP bomb selector in packaged/runtime environments
  Symptom: bomb selector showed `0/0` bombs with no clear reason even though `ccrp_bomb_params.json` was shipped
  Cause: bomb database loading used separate path resolution and swallowed load failures into an empty in-memory database
  Fix/Workaround: resolve bomb JSON through the shared runtime-aware resource search, preserve a visible `load_error`, and surface it in the selector/settings UI

### Beads Maintenance

- Context: cleanup after upgrading Bomana to `bd 1.0.4`
  Symptom: old issues and notes still described pre-1.0 migration failures, external Dolt server setup, and legacy sync commands
  Cause: historical upgrade work remained after the project moved to the current embedded Dolt backend
  Fix/Workaround: retire old `bd sync`, manual `.beads/dolt/**/LOCK` cleanup, raw Dolt SQL schema commits, and hand-started `127.0.0.1:3307` server recipes. If auto-export warns because `.beads/` is ignored, prefer `bd config set export.git-add false` over changing repo ignore policy.

- Context: mixing WSL dev `bd 1.0.5` with Windows release `bd 1.0.4`
  Symptom: Windows `bd create ... --json` failed with `Field 'id' doesn't have a default value`, and `bd status --json` failed with `column "depends_on_id" could not be found`; WSL `/home/cheems/dev/Beads/bd` 1.0.5 could still read the same database
  Cause: the dev 1.0.5 binary wrote a forward embedded Dolt schema (`depends_on_issue_id`, non-default event IDs) while Windows remained on release 1.0.4, whose command paths expect `depends_on_id` and `events.id DEFAULT uuid()`
  Fix/Workaround: keep Bomana on Windows `bd 1.0.4` until 1.0.5 is officially installed everywhere. If the forward schema is already present, export with the 1.0.5 binary, back up `.beads`, rebuild with Windows `bd init --from-jsonl -p Bomana --database beads_Bomana`, restore the original `project_id`, then verify `bd status`, `bd create`, and `bd close`.
