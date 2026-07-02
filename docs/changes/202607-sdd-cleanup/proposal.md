# 202607 SDD Cleanup Proposal

## Problem

The SDD migration deliberately kept temporary compatibility bridges so each
phase could land safely. After Phase 5 and bd adaptation, those bridges would
make the new spec ambiguous if left in place.

## Scope

- Remove config package symbol re-exports and require explicit submodule imports.
- Remove legacy `bomana/config.py` package-marker acceptance.
- Move launcher install transactions fully under `launcher/install_txn.py`.
- Remove GameLogic private delegator wrappers after call sites target extracted
  core modules directly.
- Remove display-oriented `UISnapshot` fields and compute UI strings/colors in
  presenter modules.
- Remove migrated App/dialog wrapper helpers while preserving Tk production
  entrypoints.

## Non-goals

- No remote push during the active SDD refactor.
- No new runtime features.
- No changes to official 8111-only data boundary.

## Acceptance

- Current docs describe only the new module boundaries.
- Focused launcher/config/core/UI tests pass.
- Ruff and full pytest pass before closing bd cleanup issues.
