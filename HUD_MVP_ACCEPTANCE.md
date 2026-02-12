# HUD MVP Manual Matrix (v6.8.0 P1-6)

Date:
Operator:
Build:
Map/Mode:

## 1. Environment Matrix

| Case ID | Scenario | Expected | Result (Pass/Fail) | Notes |
|---|---|---|---|---|
| ENV-01 | Fullscreen exclusive + single monitor + locked | HUD target and standby states render stably; no flashing loops |  |  |
| ENV-02 | Borderless + single monitor + unlocked/locked toggle | Click-through and alpha keep expected behavior after lock toggle |  |  |
| ENV-03 | Fullscreen exclusive + dual monitor | Overlay stays on main-window monitor; no cross-screen drift |  |  |
| ENV-04 | Borderless + dual monitor + focus changes | HUD remains responsive during alt-tab/focus switch |  |  |
| ENV-05 | 8111 short jitter (scoreboard/map) | Last valid target hold and standby states work without crash |  |  |
| ENV-06 | 8111 disconnect -> recover | Shows delay/pending state, then recovers target rendering cleanly |  |  |

## 2. A/B Timing Trials (HUD ON vs OFF)

1. Fill each trial's raw timestamps in `tools/hud_mvp_metric_template.json` (or another JSON with the same schema).
2. Run:

```bash
python tools/score_hud_mvp_metrics.py --input tools/hud_mvp_metric_template.json
```

3. Paste the generated `T_acq/T_correct/T_reacq` results below.

| Trial ID | Aircraft | HUD Mode | Attitude Mode | T_acq (s) | T_correct (s) | T_reacq (s) | Target Pass | Notes |
|---|---|---|---|---:|---:|---:|---|---|
| RUN-01 |  | ON | 2.5D/2D |  |  |  |  |  |
| RUN-02 |  | OFF | N/A |  |  |  |  |  |
| RUN-03 |  | ON | 2.5D/2D |  |  |  |  |  |
| RUN-04 |  | OFF | N/A |  |  |  |  |  |

## 3. Spatial Feedback Consistency Checklist

| Check ID | Checkpoint | Result (Pass/Fail) | Evidence/Notes |
|---|---|---|---|
| SP-01 | Turn left/right: reticle X movement matches relative bearing sign |  |  |
| SP-02 | Pitch up/down (2.5D): reticle Y responds consistently with pitch changes |  |  |
| SP-03 | Roll coupling (2.5D): opposite roll signs produce opposite Y bias at same relative angle |  |  |
| SP-04 | Distance cue: nearer target appears larger/brighter than farther target |  |  |
| SP-05 | 2D fallback: mode tag switches to `2D`, vertical drift is suppressed |  |  |

## 4. Legacy Aircraft Fallback Coverage

| Aircraft | 8111 Attitude Fields | HUD Mode Seen | Can Reacquire Target | Notes |
|---|---|---|---|---|
|  | missing/partial/full | 2D/2.5D | yes/no |  |
|  | missing/partial/full | 2D/2.5D | yes/no |  |

## 5. Acceptance Decision

- Target metrics:
  - `T_acq <= 2.0s`
  - `T_correct <= 3.0s`
  - `T_reacq <= 2.0s`
- Environment matrix completed: YES / NO
- Spatial checklist completed: YES / NO
- Legacy fallback coverage completed: YES / NO

Conclusion: PASS / FAIL / PENDING
