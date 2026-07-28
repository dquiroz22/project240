#!/usr/bin/env python3
"""
Project 240 -- Apple Health export parser.

Reads an Apple Health `export.xml` and produces:
  data/project240_daily_metrics.csv  -- one row per day across ~15 metrics
  data/project240_workouts.csv       -- one row per workout
  data/daily_rows.json               -- same as the CSV, JSON form (used by build_dashboard.py)
  data/workouts.json                 -- same as the workouts CSV, JSON form
  data/meta.json                     -- height, glucose time-in-range buckets, etc.

Usage:
  python3 scripts/parse_health_export.py /path/to/export.xml [--out data] [--today 2026-07-27]

Notes on methodology (see README.md for the full writeup):
  - Step/distance/energy/water/flights are "cumulative" metrics. When two sources
    (e.g. a Garmin watch and an iPhone) both log the same metric on the same day,
    we take the MAX of the two daily totals rather than summing them, to avoid
    double-counting overlapping trackers.
  - Heart rate, SpO2, and glucose are averaged per day across all readings.
  - Sleep intervals are merged (union) across sources before summing duration,
    so overlapping "asleep" periods from two devices aren't double-counted.
    Nights are bucketed to the "wake day" (a sleep session starting after noon
    belongs to the following calendar date).
"""
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

attr_re = re.compile(r'(\w+)="([^"]*)"')

CUM_TYPES = {
    "HKQuantityTypeIdentifierStepCount": "steps",
    "HKQuantityTypeIdentifierDistanceWalkingRunning": "distance_mi",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy_kcal",
    "HKQuantityTypeIdentifierBasalEnergyBurned": "basal_energy_kcal",
    "HKQuantityTypeIdentifierFlightsClimbed": "flights",
    "HKQuantityTypeIdentifierDietaryWater": "water_floz",
}
AVG_TYPES = {
    "HKQuantityTypeIdentifierHeartRate": "hr",
    "HKQuantityTypeIdentifierOxygenSaturation": "spo2",
    "HKQuantityTypeIdentifierBloodGlucose": "glucose",
}
SPARSE_TYPES = {
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_hr",
    "HKQuantityTypeIdentifierBodyMass": "weight_lb",
    "HKQuantityTypeIdentifierBodyMassIndex": "bmi",
    "HKQuantityTypeIdentifierBodyFatPercentage": "body_fat_pct",
    "HKQuantityTypeIdentifierBloodPressureSystolic": "bp_systolic",
    "HKQuantityTypeIdentifierBloodPressureDiastolic": "bp_diastolic",
}
WORKOUT_NAME_MAP = {
    "HKWorkoutActivityTypeWalking": "Walking",
    "HKWorkoutActivityTypeRunning": "Running",
    "HKWorkoutActivityTypeCycling": "Cycling",
    "HKWorkoutActivityTypeTraditionalStrengthTraining": "Strength Training",
    "HKWorkoutActivityTypeFunctionalStrengthTraining": "Functional Strength",
    "HKWorkoutActivityTypePickleball": "Pickleball",
    "HKWorkoutActivityTypeTennis": "Tennis",
    "HKWorkoutActivityTypeYoga": "Yoga",
    "HKWorkoutActivityTypeCoreTraining": "Core Training",
    "HKWorkoutActivityTypeHighIntensityIntervalTraining": "HIIT",
    "HKWorkoutActivityTypeSwimming": "Swimming",
    "HKWorkoutActivityTypeElliptical": "Elliptical",
    "HKWorkoutActivityTypeHiking": "Hiking",
    "HKWorkoutActivityTypeStairClimbing": "Stair Climbing",
    "HKWorkoutActivityTypeMixedCardio": "Mixed Cardio",
    "HKWorkoutActivityTypeKickboxing": "Kickboxing",
    "HKWorkoutActivityTypeGolf": "Golf",
    "HKWorkoutActivityTypeDance": "Dance",
    "HKWorkoutActivityTypeOther": "Other",
}
KNOWN_BAD_DATES = set()  # add dates here (e.g. a bad scale reading) to exclude from weight parsing


def parse_dt(s):
    return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xml_path", help="Path to Apple Health export.xml")
    ap.add_argument("--out", default="data", help="Output directory (default: data)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cum_data = {v: defaultdict(float) for v in CUM_TYPES.values()}
    avg_data = {v: defaultdict(list) for v in AVG_TYPES.values()}
    sparse_data = {v: [] for v in SPARSE_TYPES.values()}
    sleep_intervals = []
    workouts = []
    height_ft = None
    current_workout = None
    glucose_buckets = defaultdict(int)

    record_count = 0
    workout_count = 0

    with open(args.xml_path, "r", encoding="utf-8") as f:
        for line in f:
            is_record = line[1:9] == "<Record "
            is_workout = (not is_record) and line[1:10] == "<Workout "
            is_wkstat = (not is_record) and (not is_workout) and line.lstrip().startswith("<WorkoutStatistics")

            if is_record:
                record_count += 1
                d = dict(attr_re.findall(line))
                rtype = d.get("type")
                source = d.get("sourceName", "unknown")
                start = d.get("startDate", "")
                value = d.get("value")

                if rtype in CUM_TYPES:
                    date = start[:10]
                    try:
                        v = float(value)
                    except (TypeError, ValueError):
                        v = 0.0
                    cum_data[CUM_TYPES[rtype]][(date, source)] += v

                elif rtype in AVG_TYPES:
                    key_name = AVG_TYPES[rtype]
                    date = start[:10]
                    try:
                        v = float(value)
                    except (TypeError, ValueError):
                        v = None
                    if v is not None:
                        avg_data[key_name][date].append(v)
                        if key_name == "glucose":
                            if v < 70:
                                glucose_buckets["below_70"] += 1
                            elif v <= 140:
                                glucose_buckets["in_70_140"] += 1
                            elif v <= 180:
                                glucose_buckets["in_141_180"] += 1
                            else:
                                glucose_buckets["above_180"] += 1
                            glucose_buckets["total"] += 1

                elif rtype in SPARSE_TYPES:
                    date = start[:10]
                    if date in KNOWN_BAD_DATES:
                        pass
                    else:
                        try:
                            v = float(value)
                        except (TypeError, ValueError):
                            v = None
                        if v is not None:
                            sparse_data[SPARSE_TYPES[rtype]].append((date, v, source))

                elif rtype == "HKQuantityTypeIdentifierHeight":
                    try:
                        height_ft = float(value)
                    except (TypeError, ValueError):
                        pass

                elif rtype == "HKCategoryTypeIdentifierSleepAnalysis":
                    if value and value.startswith("HKCategoryValueSleepAnalysisAsleep"):
                        try:
                            sleep_intervals.append((parse_dt(d.get("startDate")), parse_dt(d.get("endDate"))))
                        except Exception:
                            pass

            elif is_workout:
                workout_count += 1
                d = dict(attr_re.findall(line))
                wtype = d.get("workoutActivityType", "Other")
                wname = WORKOUT_NAME_MAP.get(wtype, wtype.replace("HKWorkoutActivityType", ""))
                start = d.get("startDate", "")
                duration = d.get("duration")
                duration_unit = d.get("durationUnit", "min")
                source = d.get("sourceName", "unknown")
                try:
                    dur_min = float(duration) if duration else 0.0
                    if duration_unit == "sec":
                        dur_min = dur_min / 60.0
                except (TypeError, ValueError):
                    dur_min = 0.0
                wk = {
                    "date": start[:10] if start else None, "type": wname,
                    "duration_min": round(dur_min, 1), "energy_kcal": 0.0, "distance_mi": 0.0,
                    "source": source, "_start": start, "_end": d.get("endDate", ""),
                }
                workouts.append(wk)
                current_workout = wk

            elif is_wkstat and current_workout is not None:
                d = dict(attr_re.findall(line))
                if d.get("startDate") == current_workout["_start"] and d.get("endDate") == current_workout["_end"]:
                    t, s = d.get("type"), d.get("sum")
                    if s is not None:
                        try:
                            sv = float(s)
                        except ValueError:
                            sv = 0.0
                        if t == "HKQuantityTypeIdentifierActiveEnergyBurned":
                            current_workout["energy_kcal"] = round(sv, 1)
                        elif t in ("HKQuantityTypeIdentifierDistanceWalkingRunning", "HKQuantityTypeIdentifierDistanceCycling"):
                            current_workout["distance_mi"] = round(sv, 2)

    for wk in workouts:
        wk.pop("_start", None)
        wk.pop("_end", None)

    print(f"Parsed {record_count:,} records, {workout_count:,} workouts", file=sys.stderr)

    # merge sleep intervals across sources, bucket to wake-day
    sleep_intervals.sort(key=lambda x: x[0])
    merged = []
    for s, e in sleep_intervals:
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    sleep_by_date = defaultdict(float)
    for s, e in merged:
        dur_hours = (e - s).total_seconds() / 3600.0
        d = (s + timedelta(days=1)).date() if s.hour >= 12 else s.date()
        sleep_by_date[d.isoformat()] += dur_hours

    cum_by_date = {v: {} for v in CUM_TYPES.values()}
    for key_name, dct in cum_data.items():
        per_date = defaultdict(dict)
        for (date, source), total in dct.items():
            per_date[date][source] = total
        for date, sources in per_date.items():
            cum_by_date[key_name][date] = max(sources.values())

    avg_by_date = {}
    for key_name, dct in avg_data.items():
        avg_by_date[key_name] = {date: {"avg": sum(v) / len(v), "min": min(v), "max": max(v), "count": len(v)}
                                  for date, v in dct.items()}

    for key_name in sparse_data:
        sparse_data[key_name].sort(key=lambda x: x[0])
    sparse_by_date = {k: {} for k in sparse_data}
    for key_name, rows in sparse_data.items():
        for date, val, source in rows:
            sparse_by_date[key_name][date] = val

    all_dates = set()
    for dct in cum_by_date.values():
        all_dates.update(dct.keys())
    for dct in avg_by_date.values():
        all_dates.update(dct.keys())
    all_dates.update(sleep_by_date.keys())
    for rows in sparse_data.values():
        all_dates.update(r[0] for r in rows)
    all_dates = sorted(all_dates)

    daily_rows = []
    for date in all_dates:
        row = {"date": date}
        for k in CUM_TYPES.values():
            row[k] = cum_by_date[k].get(date)
        hr = avg_by_date["hr"].get(date)
        row["avg_hr"], row["min_hr"], row["max_hr"] = (hr["avg"], hr["min"], hr["max"]) if hr else (None, None, None)
        spo2 = avg_by_date["spo2"].get(date)
        row["spo2_avg_pct"] = round(spo2["avg"] * 100, 1) if spo2 else None
        glu = avg_by_date["glucose"].get(date)
        row["glucose_avg"] = round(glu["avg"], 1) if glu else None
        row["glucose_min"] = glu["min"] if glu else None
        row["glucose_max"] = glu["max"] if glu else None
        row["glucose_count"] = glu["count"] if glu else None
        row["resting_hr"] = sparse_by_date["resting_hr"].get(date)
        row["weight_lb"] = sparse_by_date["weight_lb"].get(date)
        row["bmi"] = sparse_by_date["bmi"].get(date)
        row["body_fat_pct"] = round(sparse_by_date["body_fat_pct"][date] * 100, 1) if date in sparse_by_date["body_fat_pct"] else None
        row["bp_systolic"] = sparse_by_date["bp_systolic"].get(date)
        row["bp_diastolic"] = sparse_by_date["bp_diastolic"].get(date)
        row["sleep_hours"] = round(sleep_by_date.get(date, 0), 2) if date in sleep_by_date else None
        daily_rows.append(row)

    fieldnames = ["date", "steps", "distance_mi", "active_energy_kcal", "basal_energy_kcal", "flights", "water_floz",
                  "avg_hr", "min_hr", "max_hr", "resting_hr", "spo2_avg_pct",
                  "glucose_avg", "glucose_min", "glucose_max", "glucose_count",
                  "weight_lb", "bmi", "body_fat_pct", "bp_systolic", "bp_diastolic", "sleep_hours"]
    with open(out_dir / "project240_daily_metrics.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(daily_rows)

    with open(out_dir / "project240_workouts.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "type", "duration_min", "energy_kcal", "distance_mi", "source"])
        w.writeheader()
        w.writerows(sorted(workouts, key=lambda x: x["date"] or ""))

    (out_dir / "daily_rows.json").write_text(json.dumps(daily_rows))
    (out_dir / "workouts.json").write_text(json.dumps(workouts))
    (out_dir / "meta.json").write_text(json.dumps({"height_ft": height_ft, "glucose_buckets": dict(glucose_buckets)}))

    print(f"Wrote {len(daily_rows):,} daily rows and {len(workouts):,} workouts to {out_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
