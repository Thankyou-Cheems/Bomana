#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Score first-principles HUD MVP timing metrics from manual trial data."""

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TARGET_T_ACQ_SEC = 2.0
TARGET_T_CORRECT_SEC = 3.0
TARGET_T_REACQ_SEC = 2.0


def _to_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Optional[float], digits: int = 3) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    seq = sorted(float(v) for v in values)
    if len(seq) == 1:
        return seq[0]
    rank = (len(seq) - 1) * (float(pct) / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(seq) - 1)
    frac = rank - lo
    return seq[lo] + (seq[hi] - seq[lo]) * frac


def _metric_summary(values: List[float], target: float) -> Dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "target_sec": target,
            "pass_rate": None,
            "mean_sec": None,
            "median_sec": None,
            "p90_sec": None,
            "min_sec": None,
            "max_sec": None,
        }

    pass_count = sum(1 for v in values if float(v) <= float(target))
    return {
        "count": len(values),
        "target_sec": target,
        "pass_rate": _round_or_none(pass_count / len(values)),
        "mean_sec": _round_or_none(statistics.mean(values)),
        "median_sec": _round_or_none(statistics.median(values)),
        "p90_sec": _round_or_none(_percentile(values, 90.0)),
        "min_sec": _round_or_none(min(values)),
        "max_sec": _round_or_none(max(values)),
    }


def _score_trial(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    trial_id = str(raw.get("id") or f"trial-{index:02d}")
    aircraft = str(raw.get("aircraft") or "unknown")
    scenario = str(raw.get("scenario") or "")

    acq_start = _to_float(raw.get("acq_start_s"))
    acq_done = _to_float(raw.get("acq_done_s"))
    correct_done = _to_float(raw.get("correct_done_s"))
    loss = _to_float(raw.get("loss_s"))
    reacq_done = _to_float(raw.get("reacq_done_s"))

    errors: List[str] = []

    if acq_start is None:
        errors.append("missing acq_start_s")
    if acq_done is None:
        errors.append("missing acq_done_s")
    if correct_done is None:
        errors.append("missing correct_done_s")
    if (loss is None) ^ (reacq_done is None):
        errors.append("loss_s and reacq_done_s must both be provided or both omitted")

    t_acq: Optional[float] = None
    t_correct: Optional[float] = None
    t_reacq: Optional[float] = None

    if not errors:
        t_acq = acq_done - acq_start
        t_correct = correct_done - acq_done
        if t_acq < 0:
            errors.append("acq_done_s must be >= acq_start_s")
        if t_correct < 0:
            errors.append("correct_done_s must be >= acq_done_s")
        if (loss is not None) and (reacq_done is not None):
            t_reacq = reacq_done - loss
            if t_reacq < 0:
                errors.append("reacq_done_s must be >= loss_s")

    scored = not errors
    t_acq_pass = bool(scored and (t_acq is not None) and (t_acq <= TARGET_T_ACQ_SEC))
    t_correct_pass = bool(scored and (t_correct is not None) and (t_correct <= TARGET_T_CORRECT_SEC))
    t_reacq_pass: Optional[bool]
    if t_reacq is None:
        t_reacq_pass = None
    else:
        t_reacq_pass = bool(scored and (t_reacq <= TARGET_T_REACQ_SEC))

    overall_pass = bool(
        scored
        and t_acq_pass
        and t_correct_pass
        and (t_reacq_pass in (True, None))
    )

    return {
        "id": trial_id,
        "aircraft": aircraft,
        "scenario": scenario,
        "scored": scored,
        "errors": errors,
        "t_acq_s": _round_or_none(t_acq),
        "t_correct_s": _round_or_none(t_correct),
        "t_reacq_s": _round_or_none(t_reacq),
        "t_acq_pass": t_acq_pass if scored else False,
        "t_correct_pass": t_correct_pass if scored else False,
        "t_reacq_pass": t_reacq_pass if scored else None,
        "overall_pass": overall_pass,
        "notes": str(raw.get("notes") or ""),
    }


def _load_trials(input_path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    meta: Dict[str, Any] = {}

    if isinstance(payload, list):
        trials = payload
    elif isinstance(payload, dict):
        trials = payload.get("trials", [])
        if not isinstance(trials, list):
            raise ValueError("input.trials must be a list")
        maybe_meta = payload.get("meta", {})
        if isinstance(maybe_meta, dict):
            meta = maybe_meta
    else:
        raise ValueError("input must be a JSON object or a JSON array")

    for idx, trial in enumerate(trials):
        if not isinstance(trial, dict):
            raise ValueError(f"trial at index {idx} is not an object")

    return trials, meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Score HUD MVP timing metrics from manual trial timestamps.")
    parser.add_argument("--input", required=True, help="Input JSON path (contains 'trials').")
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    args = parser.parse_args()

    input_path = Path(args.input)
    trials_raw, source_meta = _load_trials(input_path)
    trials = [_score_trial(trial, idx + 1) for idx, trial in enumerate(trials_raw)]

    scored_trials = [t for t in trials if t["scored"]]
    t_acq_values = [float(t["t_acq_s"]) for t in scored_trials if t["t_acq_s"] is not None]
    t_correct_values = [float(t["t_correct_s"]) for t in scored_trials if t["t_correct_s"] is not None]
    t_reacq_values = [float(t["t_reacq_s"]) for t in scored_trials if t["t_reacq_s"] is not None]

    overall_pass_count = sum(1 for t in scored_trials if t["overall_pass"])
    overall_pass_rate = None
    if scored_trials:
        overall_pass_rate = _round_or_none(overall_pass_count / len(scored_trials))

    result: Dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input": str(input_path),
            "targets_sec": {
                "t_acq": TARGET_T_ACQ_SEC,
                "t_correct": TARGET_T_CORRECT_SEC,
                "t_reacq": TARGET_T_REACQ_SEC,
            },
            "source_meta": source_meta,
        },
        "summary": {
            "trials_total": len(trials),
            "trials_scored": len(scored_trials),
            "overall_pass_count": overall_pass_count,
            "overall_pass_rate": overall_pass_rate,
            "metrics": {
                "t_acq": _metric_summary(t_acq_values, TARGET_T_ACQ_SEC),
                "t_correct": _metric_summary(t_correct_values, TARGET_T_CORRECT_SEC),
                "t_reacq": _metric_summary(t_reacq_values, TARGET_T_REACQ_SEC),
            },
        },
        "trials": trials,
    }

    if args.output:
        output_path = Path(args.output)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path("tools") / "output" / f"hud_mvp_metrics_{stamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(output_path),
                "trials_scored": len(scored_trials),
                "overall_pass_rate": overall_pass_rate,
            },
            ensure_ascii=False,
        )
    )
    if not scored_trials:
        print("warning: no valid trials were scored. check input timestamps.")


if __name__ == "__main__":
    main()
