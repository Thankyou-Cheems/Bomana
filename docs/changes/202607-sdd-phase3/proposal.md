# 202607 SDD Phase 3 Proposal

## Problem

`bomana/core/logic.py` still owns polling orchestration, map/navigation math,
timer persistence helpers, lifecycle transitions, endpoint diagnostics, and CCRP
calculation scheduling. Rewriting the class at once is too risky because the
polling model and `GameLogic` private methods have existing regression tests.

## Scope

- Move low-coupling helper responsibilities into focused core modules.
- Keep `GameLogic.tick()`, `snapshot()`, persistence format, and existing private
  method names compatible.
- Add module-level tests for each extracted responsibility.

## Out Of Scope

- Changing 8111 endpoint semantics or polling cadence.
- Removing `GameLogic` facade methods that current tests or UI code still use.
- Rewriting navigation target selection behavior.
- Changing saved timer state shape.
- Pushing the branch to remote.

## Acceptance

- Extracted modules have focused tests.
- Existing core and full test suites pass.
- `GameLogic` remains the public orchestrator while helper logic is strangled
  into smaller modules.
- Any real 8111/manual smoke requirements are recorded in review.
