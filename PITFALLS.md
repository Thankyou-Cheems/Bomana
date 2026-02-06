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
