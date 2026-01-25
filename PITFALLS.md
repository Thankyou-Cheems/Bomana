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

