# Pitfalls Log (Bomana)

## Format
- Date: YYYY-MM-DD
- Context: what you were trying to do
- Symptom: error message or behavior
- Cause: short root-cause guess
- Fix/Workaround: what resolved it

## Entries
- Date: 2026-01-25
  Context: editing Bomana.pyw with apply_patch
  Symptom: apply_patch panicked with 'byte index ... is not a char boundary'
  Cause: patch tool choking on non-ASCII/emoji in large file
  Fix/Workaround: use a Python script (read/replace) instead of apply_patch

- Date: 2026-01-25
  Context: after UI split, flight state stopped updating
  Symptom: UI no longer reflected live state updates
  Cause: GameLogic thread crashed on NameError (missing math import)
  Fix/Workaround: add `import math` to bomana/core/logic.py

- Date: 2026-02-06
  Context: GitHub Actions Windows packaging (`tools/build_portable.py`)
  Symptom: `UnicodeEncodeError: 'charmap' codec can't encode characters` when printing paths
  Cause: CI console encoding was cp1252, but output included Chinese file names (e.g. checksum file path)
  Fix/Workaround: route status logs through `safe_print()` with encoding fallback (`backslashreplace`)

- Date: 2026-02-06
  Context: GitHub Release asset naming in Actions
  Symptom: uploaded asset names containing Chinese were rewritten on GitHub (e.g. became underscored names)
  Cause: GitHub Release asset upload normalizes non-ASCII/special characters in file names
  Fix/Workaround: use ASCII-only artifact names (`Bomana_launcher_v*.exe`, `checksums_*.txt`) and put Chinese text in release notes, not in file names

- Date: 2026-02-06
  Context: launcher progress animation during update check
  Symptom: progress bar looked like it was finishing download during "check" stage, and window size could drift while status text kept changing
  Cause: check phase reused download-like progress behavior and did not separate indeterminate animation/layout reflow from real download progress
  Fix/Workaround: split check/download states, keep check phase indeterminate, and recalc layout/progress geometry from current canvas width instead of fixed assumptions

- Date: 2026-02-08
  Context: in-battle map toggle (`M`) caused UI flash and frame drop spikes
  Symptom: app flashed briefly when opening/closing game map; occasional CPU/load spike
  Cause: transient 8111 `/map_obj.json` jitter (player/map fields briefly invalid) triggered state/UI oscillation, plus per-frame full list relayout and full heading-tape redraw amplified cost
  Fix/Workaround: add ALIVE/LOSS_PENDING telemetry fallback for player presence, keep integrated tape row mounted, switch to incremental zone/airport label updates, deduplicate equivalent heading-tape renders, and keep standalone nav status rows mounted

- Date: 2026-02-09
  Context: users still reported severe jitter when holding scoreboard/map in battle
  Symptom: timer UI could momentarily collapse, status flickered to "加入战斗中", then quickly returned
  Cause: ALIVE state reacted to short 8111 empty frames too aggressively (transient player-loss + immediate pending hint), causing rapid panel resize oscillation
  Fix/Workaround: add `PLAYER_PRESENCE_GRACE_SEC` debounce in `GameLogic.tick`, delay `api_down_pending` hint via `API_PENDING_HINT_DELAY_SEC`, keep zone panel visible during `LOSS_PENDING`, reuse previous valid telemetry/map snapshot during short unstable windows, guard landing/on-ground logic from `/state` failed frames, throttle zone-driven `_recalc_size()` calls, and relax localhost API timeouts (`0.05/0.08`) for packaged runtime stability

- Date: 2026-02-09
  Context: launcher update interrupted/failure path hardening
  Symptom: under specific install exceptions, local app could disappear after rollback; concurrent launchers could race on install target
  Cause: rollback removed `app/` unconditionally on exception and there was no cross-process install lock or startup recovery for leftover `app_new`/`app_backup`
  Fix/Workaround: make rollback state-aware (only restore when replacement actually started), add cross-process update lock + stale-lock cleanup, add startup recovery for `app_new`/`app_backup`, and support graceful cancel-exit during running tasks

- Date: 2026-02-09
  Context: GitHub fallback when latest release is launcher-only
  Symptom: update check could fail with `未找到发布清单: manifest_<Channel>.json` even though older app releases existed
  Cause: fallback logic queried only `/releases/latest`, and launcher-only releases do not include app manifests
  Fix/Workaround: after latest-release miss, iterate recent releases and select the first one containing `manifest_<Channel>.json` and matching app asset

- Date: 2026-02-09
  Context: primary Tencent version check under unstable/filtered networks
  Symptom: launcher could report primary service unavailable too aggressively (`TimeoutError`), regardless of proxy toggle
  Cause: single short timeout attempt (`PRIMARY_TIMEOUT_SEC=4`) was sensitive to transient RTT spikes and proxy path latency
  Fix/Workaround: add multi-attempt primary check (normal timeout, longer retry, alternate network path retry) and restore user-selected proxy mode after probing

- Date: 2026-02-09
  Context: primary Tencent API occasionally returned `HTTP 5xx` while launcher only logged generic failure
  Symptom: users reported "cannot fetch version from Tencent" even with proxy toggle; root cause detail was hidden
  Cause: `urllib` raised `HTTPError` without surfacing response JSON detail, and identity-bound request path could intermittently fail
  Fix/Workaround: parse and propagate HTTP error body detail (e.g. upstream timeout reason), and add one-shot anonymous retry (drop `device_id/install_id`) before falling back

- Date: 2026-02-09
  Context: Actions deploy-manifests workflow (`scp` to server manifests directory)
  Symptom: upload failed with `Permission denied` on `/opt/stacks/bomana-update/data/manifests/manifest_*.json`
  Cause: CI SSH user lacked direct write permission to target directory (owner/ACL drift after manual ops or container writes)
  Fix/Workaround: upload manifests to remote `/tmp` staging first, then sync into target dir with direct-write check and passwordless-`sudo` fallback; keep verify step with same permission fallback and actionable remediation hints

- Date: 2026-02-12
  Context: running v6.8.0 HUD baseline sampling (`tools/sample_8111_attitude.py`) in local dev environment
  Symptom: `/indicators` and `/state` requests timed out; collected sample count stayed 0
  Cause: no active War Thunder battle session exposing local 8111 API
  Fix/Workaround: run sampler only while in battle with 8111 enabled; keep `duration>=120s` and collect per-aircraft runs before closing baseline task

- Date: 2026-02-12
  Context: running `tools/build_portable.py` builds concurrently in separate terminals
  Symptom: sporadic `RuntimeError: Failed to find __version__ in bomana/config.py` and occasional `config.py` dirty/needs-update state after build
  Cause: script patches `bomana/config.py` for variant app packaging; parallel runs race on read/write timing
  Fix/Workaround: do not run build variants in parallel; script now restores `config.py` only when patched and preserves original timestamps to avoid launcher-only false dirty status

- Date: 2026-02-12
  Context: HUD overlay transparency refactor (trying to remove tinted background layer)
  Symptom: HUD window became opaque black on some systems instead of transparent overlay
  Cause: relying on Tk `-transparentcolor` plus Win32 `LWA_ALPHA` only is not stable across environments; when color-key transparency is not actually applied, canvas background is rendered as a full black layer
  Fix/Workaround: pass Win32 color key explicitly via `SetLayeredWindowAttributes(..., LWA_COLORKEY | LWA_ALPHA)` and keep HUD background/canvas on the same key color

- Date: 2026-02-12
  Context: HUD warzone target reticle position deviates significantly from actual game position
  Symptom: target marker appeared too close to screen center, especially at larger angles (20-45°), with up to 51% position error at 45°
  Cause: `_project_point()` used linear mapping `rel / 90 * width * 0.42` instead of perspective `tan(rel) / tan(fov/2)` projection — game uses perspective rendering where screen position ∝ tan(angle), not angle
  Fix/Workaround: replaced horizontal projection with `tan(rel_rad) / tan(fov_half_rad) * (width * 0.5)`, added configurable FOV (default 73° horizontal, 55° vertical) to `HUDConfig`, and harmonised vertical `pixels_per_deg` calculation

- Date: 2026-02-12
  Context: after horizontal tan() fix, HUD target goes above horizon during dives and aggressive maneuvers
  Symptom: target marker flew into the sky during dives; roll caused misaligned offsets
  Cause: pitch_offset and geometry_offset (lookdown) were separate additive terms with different scales (ppd vs ppd×0.78); ppd increase from previous fix amplified the imbalance; roll was Y-only approximation
  Fix/Workaround: merged pitch+lookdown into single `vertical_angle = lookdown + pitch`, applied tan() projection to vertical axis, replaced roll with full 2D rotation matrix `(cos/sin)`, removed `_ROLL_COUPLING_RATIO` and `_LOOKDOWN_COUPLING_RATIO`

- Date: 2026-02-12
  Context: HUD projection after vertical-axis merge still had large far-range error during steep dives
  Symptom: targets were acceptable around 3-4km, but far targets drifted heavily in vertical position when nose-down
  Cause: direct `vertical_angle = lookdown + pitch` over-weighted body pitch for far targets (small lookdown + large negative pitch), amplifying vertical error without camera-input telemetry
  Fix/Workaround: introduced distance-adaptive pitch gain in HUD projection (full pitch near 4km, linearly reduced by 14km, plus extra damp in far dives) and use `vertical_angle = lookdown + effective_pitch`

- Date: 2026-02-12
  Context: HUD/nav still showed large far-range mismatch after pitch-gain tuning
  Symptom: near-range looked acceptable, but far targets and dive scenarios still drifted; distance/bearing felt map-dependent
  Cause: navigation geometry used normalized map coordinates with fixed `DISTANCE_SCALE=100` and ignored `map_info` axis scales (`map_min/map_max`), introducing distance and bearing distortion on non-square/variable-size maps
  Fix/Workaround: switched nav geometry to map_info-based meter scaling for bearing/distance/ground-speed (while preserving existing `distance * DISTANCE_SCALE` UI compatibility)


