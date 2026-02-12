# HUD MVP Baseline (v6.8.0)

Date: 2026-02-12

## First-principles Success Metrics

- `T_acq` (target acquisition): from spawn/readiness to the first correct HUD target pick.
  - Target: `T_acq <= 2.0s`
- `T_correct` (course correction): from first pick to stable heading correction (within `+/-5deg` for >=1s).
  - Target: `T_correct <= 3.0s`
- `T_reacq` (reacquire after loss): from intentional/accidental loss to target reacquisition.
  - Target: `T_reacq <= 2.0s`

## 8111 Capability Baseline Scope

Required fields for HUD 2.5D:
- `/state`: `aviahorizon_pitch`, `aviahorizon_roll` or `bank`, `H, m`
- `/indicators`: `compass1` or `compass`

Quality checks:
- Field presence rate by aircraft (`pitch/roll/bank/compass/altitude`)
- Long zero-like attitude rate while airborne
- Jitter event rate (high angular-rate spikes)
- Fallback reason mix (`missing` / `stuck_zero` / `jitter`) from app diagnostics

## Sampling Tool

Command:

```bash
python tools/sample_8111_attitude.py --duration 180 --interval 0.2
```

Output:
- JSON baseline report under `tools/output/`
- Per-aircraft availability/jitter/zero-like rates

## First-principles Timing Scoring Tool

Command:

```bash
python tools/score_hud_mvp_metrics.py --input tools/hud_mvp_metric_template.json
```

Input fields per trial:
- `acq_start_s`: spawn/readiness start timestamp
- `acq_done_s`: first correct HUD target pick timestamp
- `correct_done_s`: stable heading correction timestamp (within `+/-5deg` for `>=1s`)
- `loss_s` / `reacq_done_s`: optional pair for target-loss recovery timing

Output:
- JSON score report under `tools/output/`
- Per-trial pass/fail for `T_acq` / `T_correct` / `T_reacq`
- Aggregate mean/median/p90 and pass rates

## Aircraft Baseline Table (Template)

| Aircraft | Samples | Pitch | Roll | Bank | Attitude Available | Compass | Altitude | Zero-like (airborne) | Jitter | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| TBD | 0 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | pending live sampling |

## Current Session Status

- On `2026-02-12`, local probe to `http://127.0.0.1:8111/indicators` and `/state` timed out.
- Current environment has no active 8111 feed, so live aircraft baseline rows remain pending.
- The metric definitions and repeatable sampler are now in place; fill the table after in-battle capture.
