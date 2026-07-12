# Timer Cycle Spec

Status: Draft
Owner: Bomana maintainers
Prefix: `TIMER-`

## Scope

This spec governs the configurable Bomana mission timer period across App
config, core calculations, persisted timer restore, tray commands, Web control
state, Web commands, and the main-window progress presentation.

## Non-goals

- It does not infer a period from game mode or add a new 8111 endpoint.
- It does not change life/spawn detection or warning-sound thresholds.
- It does not authorize arbitrary timer expressions or unbounded values.

## Normative Clauses

- `TIMER-01`: The timer period MUST be an integer minute target from 1 through
  180 inclusive and MUST default to 15 minutes.
- `TIMER-02`: Missing, boolean, non-integer, or out-of-range persisted/App/Web
  values MUST fail closed to the current valid value or the 15-minute default.
- `TIMER-03`: App, tray, and Web changes MUST use one explicit
  `set_timer_cycle_minutes` semantic path that persists the target before
  reporting success and restores the prior effective value if persistence
  fails.
- `TIMER-04`: A successful period change during an active life MUST retain the
  existing spawn timestamp and immediately recompute cycle number, remaining
  time, and progress against the new period.
- `TIMER-05`: Timer state saves MUST include the exact `cycle_seconds`; restore
  MUST reject a mismatched period, while a legacy missing field MAY restore only
  when the effective period is the legacy 900 seconds.
- `TIMER-06`: Dashboard snapshot and control-state projections MUST expose the
  effective `cycle_minutes`, and the exhaustive Web command matrix MAY change it
  only through a bounded integer `config.set_timer_cycle_minutes` command.
- `TIMER-07`: The App timer MUST render normalized progress as a continuous
  circular ring around one banana emoji, place the integer percentage in a
  separate lower visual band without overlapping the emoji, and MUST remove
  both the legacy horizontal timer strip and the banana silhouette outline.
- `TIMER-08`: `FINAL_WARNING_SEC` and the existing warning-sound seconds MUST
  remain absolute seconds independent of the configured period.

## Contract Coverage

- [static] `tests/contracts/test_timer_cycle_contract.py` enforces
  `TIMER-01..TIMER-03` and `TIMER-05..TIMER-08` across config constants,
  schemas, command allowlists, restore fields, and timer widget ownership.
- [behavioral] `tests/test_timer_cycle.py` enforces `TIMER-01..TIMER-04`,
  `TIMER-06`, and `TIMER-08` with valid/hostile values, rollback, active-life
  recomputation, tray targets, and Web execution.
- [behavioral] `tests/test_file_utils_persistence.py` and
  `tests/test_timer_restore_guard.py` enforce `TIMER-05` with matching,
  mismatching, legacy-default, and legacy-custom restore cases.
- [behavioral] `tests/test_ui_geometry.py` enforces `TIMER-07` with normalized
  outline progress and timer-row geometry checks.
