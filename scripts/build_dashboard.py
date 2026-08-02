#!/usr/bin/env python3
"""
Project 240 -- injects data/*.json + a check-ins CSV into dashboard/template.html
to produce the final, self-contained dashboard HTML file.

Usage:
  python3 scripts/build_dashboard.py \
      --template dashboard/template.html \
      --dir data \
      --checkins data/checkins.csv \
      --sheet-url "https://docs.google.com/spreadsheets/d/XXXX/edit" \
      --out Project240_Dashboard_v1.html

If --checkins is omitted or the file doesn't exist, an empty check-in log is embedded.
"""
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

# Google Sheets auto-formats typed dates in whatever locale/format the cell picks up
# (8/2/26, 8/2/2026, 2026-08-02, etc.) -- normalize everything to ISO YYYY-MM-DD so it
# matches the dates used everywhere else in the dashboard (SUMMARY, DAILY, calendar cards).
# Without this, a check-in row silently never matches any day and looks like "not logged".
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y"]


def normalize_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return raw
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw  # unrecognized format -- leave as-is rather than silently dropping the row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="dashboard/template.html")
    ap.add_argument("--dir", default="data")
    ap.add_argument("--checkins", default="data/checkins.csv")
    ap.add_argument("--sheet-url", default="", help="Google Sheet URL for the check-in log")
    ap.add_argument("--out", default="Project240_Dashboard_v1.html")
    args = ap.parse_args()

    d = Path(args.dir)
    tpl = Path(args.template).read_text()
    daily = (d / "daily_rows.json").read_text()
    workouts = (d / "workouts.json").read_text()
    summary = (d / "summary.json").read_text()
    meta = json.loads((d / "meta.json").read_text())

    checkins_path = Path(args.checkins)
    if checkins_path.exists():
        rows = list(csv.DictReader(open(checkins_path)))
        for r in rows:
            if "date" in r:
                r["date"] = normalize_date(r["date"])
    else:
        rows = []
    checkins_json = json.dumps(rows)

    tpl = tpl.replace("/*__DAILY_JSON__*/", daily)
    tpl = tpl.replace("/*__WORKOUTS_JSON__*/", workouts)
    tpl = tpl.replace("/*__SUMMARY_JSON__*/", summary)
    tpl = tpl.replace("/*__CHECKINS_JSON__*/", checkins_json)
    tpl = tpl.replace("{{HEIGHT_FT}}", str(round(meta["height_ft"], 2)) if meta.get("height_ft") else "")
    tpl = tpl.replace("{{SHEET_URL}}", args.sheet_url)

    Path(args.out).write_text(tpl)
    print(f"Wrote {args.out} ({len(tpl):,} bytes) with {len(rows)} check-in rows")


if __name__ == "__main__":
    main()
