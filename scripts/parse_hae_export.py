#!/usr/bin/env python3
"""
Project 240 -- Health Auto Export adapter.

Reads the daily HealthAutoExport-YYYY-MM-DD.json files produced by the Health Auto Export
iOS app's iCloud Drive automation, and MERGES them into the existing data/project240_daily_metrics.csv
+ data/workouts.json (produced originally by parse_health_export.py from a one-time Apple Health
export.xml backfill). Dates present in the HAE files overwrite/extend the existing rows; dates only
covered by the historical export.xml backfill are left untouched.

Usage:
  python3 scripts/parse_hae_export.py --hae-dir "<HAE iCloud folder>/Project 240" --dir data

Key schema differences vs. the raw Apple export.xml (handled here):
  - SpO2 and body fat % arrive as plain percentages (e.g. 96.7, 23.9), NOT fractions (0.967, 0.239)
    like export.xml -- so no *100 conversion here.
  - heart_rate arrives pre-aggregated per source per day as {Min, Max, Avg} rather than raw readings.
  - blood_glucose arrives as ONE aggregated daily average (exportAggregation=Days), not individual
    readings -- so per-day min/max/count and the all-time time-in-range bucket counts (in meta.json,
    computed from the original export.xml's individual readings) can NOT be extended from this source.
    glucose_avg is still populated daily; glucose_min/max/count are left blank for HAE-sourced days,
    and meta.json's glucose_buckets stays frozen at the export.xml backfill period -- flagged in
    data_notes so this doesn't look like silently-missing data.
  - sleep_analysis already comes as one merged interval per source per day (totalSleep, in hours) --
    no need to re-merge raw intervals; still take max(totalSleep) across sources per day as the
    cross-source dedupe (consistent with the "don't double count overlapping trackers" methodology).
"""
import argparse
import csv
import glob
import json
import re
import sys
from pathlib import Path

CUM_METRICS = {
    "step_count": "steps",
    "walking_running_distance": "distance_mi",
    "active_energy": "active_energy_kcal",
    "basal_energy_burned": "basal_energy_kcal",
    "flights_climbed": "flights",
    "dietary_water": "water_floz",
}
SPARSE_METRICS = {
    "resting_heart_rate": "resting_hr",
    "weight_body_mass": "weight_lb",
    "body_mass_index": "bmi",
    "body_fat_percentage": "body_fat_pct",  # already a percent, not a fraction
}

FIELDNAMES = ["date", "steps", "distance_mi", "active_energy_kcal", "basal_energy_kcal", "flights", "water_floz",
              "avg_hr", "min_hr", "max_hr", "resting_hr", "spo2_avg_pct",
              "glucose_avg", "glucose_min", "glucose_max", "glucose_count",
              "weight_lb", "bmi", "body_fat_pct", "bp_systolic", "bp_diastolic", "sleep_hours"]

WORKOUT_NAME_MAP = {
    "walking": "Walking", "running": "Running", "cycling": "Cycling",
    "traditionalStrengthTraining": "Strength Training", "functionalStrengthTraining": "Functional Strength",
    "pickleball": "Pickleball", "tennis": "Tennis", "yoga": "Yoga", "coreTraining": "Core Training",
    "highIntensityIntervalTraining": "HIIT", "swimming": "Swimming", "elliptical": "Elliptical",
    "hiking": "Hiking", "stairClimbing": "Stair Climbing", "mixedCardio": "Mixed Cardio",
    "kickboxing": "Kickboxing", "golf": "Golf", "dance": "Dance", "taiChi": "Tai Chi",
    "coolDown": "Cool Down", "other": "Other",
}


def parse_one_day(day_json):
    """Parse one HealthAutoExport-*.json's data.metrics[] into a partial daily row dict."""
    metrics = day_json.get("data", {}).get("metrics", [])
    row = {k: None for k in FIELDNAMES}
    date = None

    cum_by_source = {v: {} for v in CUM_METRICS.values()}
    hr_entries = []
    spo2_vals = []
    glucose_vals = []
    sparse_by_source = {v: {} for v in SPARSE_METRICS.values()}
    sleep_by_source = {}
    bp_sys, bp_dia = [], []

    for m in metrics:
        name = m.get("name")
        entries = m.get("data", [])
        for e in entries:
            d = (e.get("date") or "")[:10]
            if d:
                date = d
            source = e.get("source", "unknown")

            if name in CUM_METRICS:
                key = CUM_METRICS[name]
                qty = e.get("qty")
                if qty is not None:
                    cum_by_source[key][source] = cum_by_source[key].get(source, 0.0) + float(qty)

            elif name in SPARSE_METRICS:
                key = SPARSE_METRICS[name]
                qty = e.get("qty")
                if qty is not None:
                    sparse_by_source[key][source] = float(qty)

            elif name == "heart_rate":
                if all(k in e for k in ("Min", "Max", "Avg")):
                    hr_entries.append((float(e["Min"]), float(e["Max"]), float(e["Avg"])))

            elif name == "blood_oxygen_saturation":
                qty = e.get("qty")
                if qty is not None:
                    spo2_vals.append(float(qty))  # already a percent

            elif name == "blood_glucose":
                qty = e.get("qty")
                if qty is not None:
                    glucose_vals.append(float(qty))

            elif name == "sleep_analysis":
                total = e.get("totalSleep")
                if total is not None:
                    sleep_by_source[source] = max(sleep_by_source.get(source, 0.0), float(total))

            elif name == "blood_pressure":
                # defensive: exact key names unconfirmed (no sample seen yet)
                sys_v = e.get("systolic") or e.get("Systolic")
                dia_v = e.get("diastolic") or e.get("Diastolic")
                if sys_v is not None:
                    bp_sys.append(float(sys_v))
                if dia_v is not None:
                    bp_dia.append(float(dia_v))

    if date is None:
        return None

    row["date"] = date
    for key, sources in cum_by_source.items():
        row[key] = round(max(sources.values()), 2) if sources else None

    if hr_entries:
        row["min_hr"] = round(min(e[0] for e in hr_entries), 1)
        row["max_hr"] = round(max(e[1] for e in hr_entries), 1)
        row["avg_hr"] = round(sum(e[2] for e in hr_entries) / len(hr_entries), 1)

    if spo2_vals:
        row["spo2_avg_pct"] = round(sum(spo2_vals) / len(spo2_vals), 1)

    if glucose_vals:
        row["glucose_avg"] = round(sum(glucose_vals) / len(glucose_vals), 1)
        # min/max/count intentionally left None -- HAE gives one pre-aggregated daily value,
        # not individual readings, so per-day spread and the all-time time-in-range buckets
        # (meta.json) can't be extended from this source. See module docstring.

    for key, sources in sparse_by_source.items():
        if sources:
            row[key] = round(sum(sources.values()) / len(sources), 1)

    if sleep_by_source:
        row["sleep_hours"] = round(max(sleep_by_source.values()), 2)

    if bp_sys:
        row["bp_systolic"] = round(sum(bp_sys) / len(bp_sys), 1)
    if bp_dia:
        row["bp_diastolic"] = round(sum(bp_dia) / len(bp_dia), 1)

    return row


def parse_workouts(day_json, date_fallback):
    """Best-effort workout extraction -- schema unconfirmed (no sample with workouts seen yet)."""
    out = []
    workouts = day_json.get("data", {}).get("workouts", [])
    for w in workouts:
        try:
            wtype = w.get("name") or w.get("type") or "Other"
            wname = WORKOUT_NAME_MAP.get(wtype, wtype)
            start = w.get("start") or w.get("startDate") or ""
            duration_min = w.get("duration")
            duration_min = round(float(duration_min) / 60.0, 1) if duration_min else 0.0
            energy = w.get("activeEnergyBurned", {})
            energy_kcal = round(float(energy.get("qty", 0)), 1) if isinstance(energy, dict) else 0.0
            dist = w.get("distance", {})
            distance_mi = round(float(dist.get("qty", 0)), 2) if isinstance(dist, dict) else 0.0
            out.append({
                "date": start[:10] if start else date_fallback,
                "type": wname, "duration_min": duration_min,
                "energy_kcal": energy_kcal, "distance_mi": distance_mi,
                "source": "HealthAutoExport",
            })
        except Exception as ex:
            print(f"  ! skipped one workout, unrecognized shape: {ex}", file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hae-dir", required=True, help="Folder containing HealthAutoExport-*.json files")
    ap.add_argument("--dir", default="data", help="Pipeline data directory to merge into (default: data)")
    args = ap.parse_args()

    d = Path(args.dir)
    files = sorted(glob.glob(str(Path(args.hae_dir) / "HealthAutoExport-*.json")))
    if not files:
        print(f"No HealthAutoExport-*.json files found in {args.hae_dir}", file=sys.stderr)
        sys.exit(1)

    daily_rows = json.loads((d / "daily_rows.json").read_text())
    rows_by_date = {r["date"]: r for r in daily_rows}
    workouts = json.loads((d / "workouts.json").read_text())

    updated_dates = []
    new_workout_count = 0
    for fp in files:
        day_json = json.loads(Path(fp).read_text())
        row = parse_one_day(day_json)
        if row:
            rows_by_date[row["date"]] = row
            updated_dates.append(row["date"])
            new_ws = parse_workouts(day_json, row["date"])
            if new_ws:
                # replace any existing HAE-sourced workouts for this date, keep historical ones
                workouts = [w for w in workouts if not (w["date"] == row["date"] and w.get("source") == "HealthAutoExport")]
                workouts.extend(new_ws)
                new_workout_count += len(new_ws)

    all_dates = sorted(rows_by_date.keys())
    merged_rows = [rows_by_date[dt] for dt in all_dates]

    with open(d / "project240_daily_metrics.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(merged_rows)

    with open(d / "project240_workouts.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "type", "duration_min", "energy_kcal", "distance_mi", "source"])
        w.writeheader()
        w.writerows(sorted(workouts, key=lambda x: x["date"] or ""))

    (d / "daily_rows.json").write_text(json.dumps(merged_rows))
    (d / "workouts.json").write_text(json.dumps(workouts))

    print(f"Merged {len(updated_dates)} day(s) from Health Auto Export: {updated_dates}", file=sys.stderr)
    print(f"Added {new_workout_count} workout(s) from Health Auto Export", file=sys.stderr)
    print(f"Total: {len(merged_rows)} daily rows, {len(workouts)} workouts in {d}/", file=sys.stderr)


if __name__ == "__main__":
    main()
