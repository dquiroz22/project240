#!/usr/bin/env python3
"""
Project 240 -- builds data/summary.json (KPIs, goal tracker, workout rollups,
glucose time-in-range, data-quality notes) from the output of parse_health_export.py.

Usage:
  python3 scripts/build_summary.py --today 2026-07-27 [--dir data]
"""
import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Known bad data points to exclude when computing the weight series (obvious scale errors,
# not real readings). Add new ones here as you find them.
KNOWN_BAD_WEIGHTS = {"2024-01-03"}


def num(r, field):
    v = r.get(field)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data", help="Directory with parse_health_export.py output")
    ap.add_argument("--today", required=True, help="Reference date, YYYY-MM-DD")
    args = ap.parse_args()
    d = Path(args.dir)
    TODAY = datetime.strptime(args.today, "%Y-%m-%d")

    rows = list(csv.DictReader(open(d / "project240_daily_metrics.csv")))
    rows_by_date = {r["date"]: r for r in rows}
    dates = sorted(rows_by_date.keys())
    workouts = json.load(open(d / "workouts.json"))
    meta = json.load(open(d / "meta.json"))
    height_ft = meta["height_ft"]
    height_in = height_ft * 12 if height_ft else None
    glucose_buckets = meta["glucose_buckets"]

    def period_avg(field, days):
        vals = []
        for i in range(days):
            dt = (TODAY - timedelta(days=i)).strftime("%Y-%m-%d")
            r = rows_by_date.get(dt)
            if r:
                v = num(r, field)
                if v is not None:
                    vals.append(v)
        return {"avg": round(sum(vals) / len(vals), 1), "n": len(vals)} if vals else {"avg": None, "n": 0}

    periods = [7, 30, 90]
    metrics = ["steps", "sleep_hours", "resting_hr", "spo2_avg_pct", "glucose_avg",
               "active_energy_kcal", "distance_mi", "water_floz"]
    metric_summary = {m: {f"d{p}": period_avg(m, p) for p in periods} for m in metrics}

    weight_events = [{"date": r["date"], "value": round(num(r, "weight_lb"), 1), "type": "measured"}
                      for r in rows if num(r, "weight_lb") and r["date"] not in KNOWN_BAD_WEIGHTS]
    bmi_events = [{"date": r["date"], "value": num(r, "bmi")} for r in rows if num(r, "bmi")]
    bf_events = [{"date": r["date"], "value": num(r, "body_fat_pct")} for r in rows if num(r, "body_fat_pct")]

    estimated_weight_events = []
    if height_in:
        for e in bmi_events:
            est = e["value"] * (height_in ** 2) / 703.0
            estimated_weight_events.append({"date": e["date"], "value": round(est, 1), "type": "estimated_from_bmi"})

    last_measured = weight_events[-1] if weight_events else None
    last_estimated = estimated_weight_events[-1] if estimated_weight_events else None
    first_weight = weight_events[0] if weight_events else None

    wk_by_type = defaultdict(lambda: {"count": 0, "minutes": 0.0})
    for w in workouts:
        wk_by_type[w["type"]]["count"] += 1
        wk_by_type[w["type"]]["minutes"] += w["duration_min"]

    def workouts_in_window(days):
        start = (TODAY - timedelta(days=days)).strftime("%Y-%m-%d")
        end = TODAY.strftime("%Y-%m-%d")
        return [w for w in workouts if w["date"] and start <= w["date"] <= end]

    wk_90, wk_30 = workouts_in_window(90), workouts_in_window(30)
    total_minutes_90 = sum(w["duration_min"] for w in wk_90)

    workout_summary = {
        "all_time_count": len(workouts),
        "all_time_minutes": round(sum(w["duration_min"] for w in workouts), 1),
        "by_type": {k: {"count": v["count"], "minutes": round(v["minutes"], 1)}
                    for k, v in sorted(wk_by_type.items(), key=lambda kv: -kv[1]["count"])},
        "last_90_days": {
            "count": len(wk_90), "total_minutes": round(total_minutes_90, 1),
            "weekly_avg_minutes": round(total_minutes_90 / (90 / 7), 1),
            "weekly_avg_sessions": round(len(wk_90) / (90 / 7), 2),
        },
        "last_30_days": {"count": len(wk_30), "total_minutes": round(sum(w["duration_min"] for w in wk_30), 1)},
    }

    sleep_days_30 = sum(1 for i in range(30)
                         if rows_by_date.get((TODAY - timedelta(days=i)).strftime("%Y-%m-%d"), {}).get("sleep_hours"))

    # ---- 6-month goal trajectory (311.3 -> 240 lb) ----
    # Fixed anchor -- the day the goal was actually set, NOT "today". This must stay a constant:
    # rebuilds now run daily (Health Auto Export auto-refresh), so if this were TODAY it would
    # silently re-anchor a fresh 26-week countdown on every single rebuild and the deadline would
    # never actually get closer. Update GOAL_START_DATE/goal_start_lb by hand only if Doug
    # explicitly resets the goal (as he did on 2026-08-02, correcting the anchor weight to his
    # actual last scale reading of 311.3 lb instead of the round 300 first used).
    GOAL_WEEKS = 26
    GOAL_START_DATE = "2026-08-02"
    goal_start_date = datetime.strptime(GOAL_START_DATE, "%Y-%m-%d")
    goal_target_date = goal_start_date + timedelta(weeks=GOAL_WEEKS)
    goal_start_lb = 311.3
    goal_target_lb = 240.0
    total_to_lose = goal_start_lb - goal_target_lb
    six_month_goal = {
        "start_date": goal_start_date.strftime("%Y-%m-%d"),
        "target_date": goal_target_date.strftime("%Y-%m-%d"),
        "start_lb": goal_start_lb,
        "target_lb": goal_target_lb,
        "total_lb_to_lose": round(total_to_lose, 1),
        "weeks_total": GOAL_WEEKS,
        "required_weekly_rate_lb": round(total_to_lose / GOAL_WEEKS, 2),
    }

    # ---- Workout program start date ----
    # Separate anchor from the weight-loss goal clock above -- Doug wants the training program's
    # week/phase countdown to start on a specific Monday, independent of when the weight trajectory
    # was set. Update by hand only if Doug explicitly resets the program start.
    WORKOUT_PROGRAM_START_DATE = "2026-08-03"

    gt = glucose_buckets.get("total", 0)
    summary = {
        "generated_at": TODAY.strftime("%Y-%m-%d"),
        "date_range": {"start": dates[0], "end": dates[-1]},
        "height_in": height_in,
        "metric_period_averages": metric_summary,
        "glucose_time_in_range": {
            "total_readings": gt,
            "below_70_pct": round(100 * glucose_buckets.get("below_70", 0) / gt, 1) if gt else None,
            "in_70_140_pct": round(100 * glucose_buckets.get("in_70_140", 0) / gt, 1) if gt else None,
            "in_141_180_pct": round(100 * glucose_buckets.get("in_141_180", 0) / gt, 1) if gt else None,
            "above_180_pct": round(100 * glucose_buckets.get("above_180", 0) / gt, 1) if gt else None,
        },
        "weight": {
            "first_measured": first_weight, "last_measured": last_measured,
            "last_estimated_from_bmi": last_estimated,
            "measured_events": weight_events, "bmi_events": bmi_events,
            "body_fat_events": bf_events, "estimated_events": estimated_weight_events,
            "goal_start_lb": goal_start_lb, "goal_target_lb": goal_target_lb,
        },
        "six_month_goal": six_month_goal,
        "workout_program_start_date": WORKOUT_PROGRAM_START_DATE,
        "workouts": workout_summary,
        "sleep_days_with_data_last_30": sleep_days_30,
        "data_notes": {
            "step_methodology": "Daily step total = max of same-day totals across sources (e.g. Garmin vs iPhone) to avoid double-counting overlapping trackers.",
            "weight_gap": "Weight is a direct scale reading when available; otherwise a BMI-derived estimate, clearly flagged as such.",
            "excluded_outliers": sorted(KNOWN_BAD_WEIGHTS),
            "hrv": "No HRV records found in the Apple Health export as of the last parse.",
        },
    }

    (d / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Wrote {d / 'summary.json'}")


if __name__ == "__main__":
    main()
