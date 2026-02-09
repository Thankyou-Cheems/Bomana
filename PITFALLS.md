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
