# Project 240 — Health & Wellness System

A personal health dashboard built from Apple Health exports (Garmin, Hume smart scale,
Stelo glucose biosensor, iPhone). Single self-contained HTML file, no server, no hosting.
Daily check-ins (weight, nutrition, training) live in a linked Google Sheet so logging
works from any device.

See `README.txt` for the end-user guide (how to open the dashboard, what each tab shows,
data-quality caveats). This file is the developer/rebuild guide.

## Layout

```
Project240_Dashboard_v1.html   <- the built dashboard (open this in a browser)
project240_daily_metrics.csv   <- built daily metrics, also at data/ for the pipeline
project240_workouts.csv        <- built workouts table
README.txt                     <- end-user guide
exports/                       <- drop new Apple Health export.xml files here (gitignored)
data/                          <- pipeline working directory (intermediate + output data)
dashboard/template.html        <- dashboard source (HTML/CSS/JS with placeholder tokens)
scripts/
  parse_health_export.py       <- export.xml -> data/*.csv, data/*.json
  build_summary.py             <- data/*.json -> data/summary.json (KPIs, goal tracker, etc.)
  build_dashboard.py           <- dashboard/template.html + data/*.json -> final HTML
```

## Rebuilding after a new Apple Health export

1. Drop the new `export.xml` (or the whole `export.zip`, then unzip it) into `exports/`.
2. Run the three-stage pipeline from the repo root:

```bash
python3 scripts/parse_health_export.py exports/export.xml --out data
python3 scripts/build_summary.py --dir data --today $(date +%F)
python3 scripts/build_dashboard.py \
  --template dashboard/template.html \
  --dir data \
  --checkins data/checkins.csv \
  --sheet-url "https://docs.google.com/spreadsheets/d/1d2ZM4H6AUllHfCUfGON-q5qzgPIA5R24gkr86d39MPo/edit" \
  --out Project240_Dashboard_v1.html
```

Normally you'd just ask Claude to "refresh the Project 240 dashboard" and it runs this for you.

## Methodology notes (why the numbers are computed the way they are)

- **Steps/distance/energy/water/flights** are cumulative metrics. When two sources (e.g. a
  Garmin watch and an iPhone) both log the same metric on the same day, the pipeline takes the
  **max** of the two daily totals rather than summing them — summing double-counts overlapping
  trackers.
- **Heart rate, SpO2, glucose** are averaged per day across all readings, regardless of source.
- **Sleep** intervals are merged (union) across sources before summing duration, so overlapping
  "asleep" periods from two devices aren't double-counted. A sleep session is bucketed to the
  "wake day" (starts after noon -> belongs to the following calendar date).
- **Weight** is a direct scale reading when available; otherwise a BMI-derived estimate
  (`weight = BMI x height^2 / 703`), and the dashboard visually distinguishes the two.
- Obviously bad data points (e.g. a scale misread) can be excluded by adding the date to
  `KNOWN_BAD_WEIGHTS` in `scripts/build_summary.py`.

## Check-ins (Google Sheet)

Daily check-ins (weight, waist, calories, protein, water, alcohol, BP, strength/conditioning,
notes) are logged directly in a Google Sheet, not in the dashboard itself — a static HTML file
can't write back to a live data source. `build_dashboard.py` downloads the Sheet's current rows
and embeds them at build time, so the dashboard is a snapshot as of the last rebuild.

## Where this can go next

This is deliberately a static, no-hosting build. If it ever needs to become a real running
application — multiple pages, a database, other life domains beyond health — that's a genuine
software project and belongs in a proper dev environment (Claude Code) with real deploys, not
chat-generated files. Don't move it there until the requirements actually demand it.
