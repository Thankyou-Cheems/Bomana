#!/usr/bin/env python
"""Sample 8111 attitude capability baseline for HUD v6.8.0."""

import argparse
import json
import math
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

API_BASE = "http://127.0.0.1:8111"
ATT_ZERO_EPS_DEG = 0.35
JITTER_PITCH_RATE_DEG_S = 260.0
JITTER_ROLL_RATE_DEG_S = 420.0


def _to_float(raw, default=0.0):
    if raw is None:
        return float(default)
    if isinstance(raw, dict):
        raw = raw.get("value", default)
    elif isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else default
    try:
        return float(raw)
    except TypeError, ValueError:
        return float(default)


def _read_float(payload, keys):
    for key in keys:
        if key in payload:
            value = _to_float(payload.get(key), 0.0)
            if "rad" in key.lower():
                value = math.degrees(value)
            return value, True
    return 0.0, False


def _new_stat():
    return {
        "samples": 0,
        "ind_ok": 0,
        "state_ok": 0,
        "compass_present": 0,
        "altitude_present": 0,
        "pitch_present": 0,
        "roll_present": 0,
        "bank_present": 0,
        "attitude_available": 0,
        "airborne_samples": 0,
        "zero_like_airborne": 0,
        "jitter_events": 0,
    }


def _calc_ratios(stat):
    samples = max(1, int(stat["samples"]))
    airborne = max(1, int(stat["airborne_samples"]))
    return {
        "compass_present_rate": stat["compass_present"] / samples,
        "altitude_present_rate": stat["altitude_present"] / samples,
        "pitch_present_rate": stat["pitch_present"] / samples,
        "roll_present_rate": stat["roll_present"] / samples,
        "bank_present_rate": stat["bank_present"] / samples,
        "attitude_available_rate": stat["attitude_available"] / samples,
        "zero_like_airborne_rate": stat["zero_like_airborne"] / airborne,
        "jitter_rate": stat["jitter_events"] / samples,
    }


def main():
    parser = argparse.ArgumentParser(description="Collect 8111 attitude baseline samples.")
    parser.add_argument(
        "--duration", type=float, default=120.0, help="Sampling duration in seconds."
    )
    parser.add_argument("--interval", type=float, default=0.2, help="Sampling interval in seconds.")
    parser.add_argument("--output", type=str, default="", help="Output json path.")
    args = parser.parse_args()

    session = requests.Session()
    session.trust_env = False

    started_ts = time.time()
    end_ts = started_ts + max(1.0, float(args.duration))
    interval = max(0.05, float(args.interval))

    overall = _new_stat()
    by_aircraft = defaultdict(_new_stat)
    last_attitude = {}  # type_name -> (ts, pitch, lateral)

    while time.time() < end_ts:
        loop_ts = time.time()
        ind = None
        state = None
        ind_ok = False
        state_ok = False

        try:
            r = session.get(f"{API_BASE}/indicators", timeout=(0.15, 0.2))
            if r.ok:
                ind = r.json()
                ind_ok = isinstance(ind, dict)
        except requests.RequestException:
            pass

        try:
            r = session.get(f"{API_BASE}/state", timeout=(0.15, 0.2))
            if r.ok:
                state = r.json()
                state_ok = isinstance(state, dict)
        except requests.RequestException:
            pass

        if not ind_ok and not state_ok:
            time.sleep(interval)
            continue

        type_name = "unknown"
        if ind_ok:
            type_name = str(ind.get("type", "") or "").strip() or "unknown"

        ias = _to_float((state or {}).get("IAS, km/h"), 0.0)
        altitude = _to_float((state or {}).get("H, m"), 0.0)
        airborne = bool(ias > 120.0 or altitude > 150.0)

        pitch, pitch_present = _read_float(
            state or ind or {},
            (
                "aviahorizon_pitch",
                "aviahorizon_pitch, deg",
                "aviahorizon_pitch, rad",
                "pitch",
                "pitch, deg",
            ),
        )
        roll, roll_present = _read_float(
            state or ind or {},
            (
                "aviahorizon_roll",
                "aviahorizon_roll, deg",
                "aviahorizon_roll, rad",
                "roll",
                "roll, deg",
            ),
        )
        bank, bank_present = _read_float(
            state or ind or {},
            (
                "bank",
                "bank, deg",
                "bank, rad",
                "aviahorizon_bank",
                "aviahorizon_bank, deg",
                "aviahorizon_bank, rad",
            ),
        )
        lateral = roll if roll_present else bank
        attitude_available = bool(pitch_present and (roll_present or bank_present))

        for stat in (overall, by_aircraft[type_name]):
            stat["samples"] += 1
            stat["ind_ok"] += int(ind_ok)
            stat["state_ok"] += int(state_ok)
            if ind_ok and ("compass1" in ind or "compass" in ind):
                stat["compass_present"] += 1
            if state_ok and ("H, m" in state):
                stat["altitude_present"] += 1
            stat["pitch_present"] += int(pitch_present)
            stat["roll_present"] += int(roll_present)
            stat["bank_present"] += int(bank_present)
            stat["attitude_available"] += int(attitude_available)
            stat["airborne_samples"] += int(airborne)

            if (
                attitude_available
                and airborne
                and abs(pitch) <= ATT_ZERO_EPS_DEG
                and abs(lateral) <= ATT_ZERO_EPS_DEG
            ):
                stat["zero_like_airborne"] += 1

        if attitude_available:
            prev = last_attitude.get(type_name)
            if prev:
                dt = max(1e-3, loop_ts - prev[0])
                pitch_rate = abs(pitch - prev[1]) / dt
                roll_rate = abs(lateral - prev[2]) / dt
                if pitch_rate >= JITTER_PITCH_RATE_DEG_S or roll_rate >= JITTER_ROLL_RATE_DEG_S:
                    overall["jitter_events"] += 1
                    by_aircraft[type_name]["jitter_events"] += 1
            last_attitude[type_name] = (loop_ts, pitch, lateral)
        else:
            last_attitude.pop(type_name, None)

        elapsed = time.time() - loop_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)

    finished_ts = time.time()
    result = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "duration_requested_sec": float(args.duration),
            "duration_actual_sec": round(finished_ts - started_ts, 3),
            "interval_sec": interval,
            "api_base": API_BASE,
        },
        "overall": {
            **overall,
            "rates": _calc_ratios(overall),
        },
        "by_aircraft": {},
    }

    for aircraft, stat in sorted(by_aircraft.items(), key=lambda kv: kv[0]):
        result["by_aircraft"][aircraft] = {
            **stat,
            "rates": _calc_ratios(stat),
        }

    if args.output:
        out_path = Path(args.output)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path("tools") / "output" / f"hud_attitude_baseline_{stamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({"output": str(out_path), "samples": overall["samples"]}, ensure_ascii=False))
    if overall["samples"] == 0:
        print("warning: no 8111 samples collected. ensure WT battle session is running.")


if __name__ == "__main__":
    main()
