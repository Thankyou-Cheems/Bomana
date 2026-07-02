# 202607 SDD Phase 3 Delta Spec

## Core Strangler Boundary

- `CORE-STR-01`: `GameLogic.tick()`, `GameLogic.snapshot()`, timer persistence
  format, polling cadence, and public app-facing behavior remain unchanged.
- `CORE-STR-02`: Existing `GameLogic._*` compatibility helpers may remain as
  delegating facade methods while their implementation moves to focused modules.
- `CORE-STR-03`: Extracted helper modules must not import Tk/UI modules.
- `CORE-STR-04`: Module-level tests should cover extracted behavior directly in
  addition to existing `GameLogic` regression tests.

## Extracted Modules

- `bomana/core/navigation.py`: angle delta, map-axis scale, and
  bearing/distance helpers.
- `bomana/core/timing_store.py`: battle-scoped timer signature helpers.
- `bomana/core/lifecycle.py`: life/reset/transient/landing state transitions.
- `bomana/core/ccrp_scheduler.py`: CCRP input preparation, out-of-lock
  calculation, and result application.
- `bomana/core/diagnostics.py`: endpoint diagnostic counters and event throttling.

## Behavior

No runtime behavior is intentionally changed. The extraction keeps `GameLogic`
as the facade and reduces method bodies to delegation where possible.
