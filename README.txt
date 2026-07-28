PROJECT 240 — HEALTH & WELLNESS SYSTEM (v1, built in Claude)
================================================================

WHAT'S IN THIS FOLDER
----------------------
Project240_Dashboard_v1.html   <- Open this in Chrome, Safari, or Edge. Everything else is backup/reference.
project240_daily_metrics.csv   <- 3,719 days of merged Apple Health data (2016-05-21 to 2026-07-27), one row/day.
project240_workouts.csv        <- 1,048 individual workouts with type, duration, energy, distance, source.

HOW TO USE IT
-------------
Double-click Project240_Dashboard_v1.html. It opens in your default browser and runs entirely
locally — nothing is uploaded anywhere. Tabs across the top:

  Overview        - weekly health score, data gap alerts, 30-day snapshot
  Project 240 Goal- 300 -> 240 lb tracker, weight/BMI/body fat history
  Nutrition       - daily check-in form (calories, protein, water) + targets + trend chart
  Training        - workout totals, weekly volume, workout mix, recent sessions
  Vitals & Glucose- glucose time-in-range, resting HR, sleep, SpO2, data-quality notes
  Full History    - pick any metric, pick a time range (90D/1Y/5Y/All), see the trend
  Check-In Log    - everything you've logged, with a CSV export button

Daily check-ins (weight, waist, calories, protein, water, alcohol, BP, strength/conditioning,
notes) now live in a Google Sheet, not this file, so they're the same no matter which device
you log from:

  Project 240 Check-Ins:
  https://docs.google.com/spreadsheets/d/1d2ZM4H6AUllHfCUfGON-q5qzgPIA5R24gkr86d39MPo/edit

Log entries directly in that Sheet (phone, browser, office desktop -- doesn't matter). The
dashboard's Nutrition and Check-In Log tabs are a snapshot of the Sheet as of the last rebuild,
not a live connection -- after logging new entries, ask Claude to "refresh the Project 240
dashboard" and it will pull the latest rows in and regenerate this file. There's a link to the
Sheet on both of those tabs.

METHODOLOGY NOTES (read before trusting a number)
--------------------------------------------------
1. STEP COUNTING: You have two overlapping step trackers — Garmin (source "Connect") and your
   iPhone ("Dougie Fresh") — both logging steps for most of the last 9 years. Summing them would
   double-count. This build takes the HIGHER of the two same-day totals rather than adding them,
   which avoids inflation but may still undercount days where the two devices captured different
   parts of the day.

2. GARMIN SYNC GAP: Garmin Connect data (resting HR, sleep, SpO2, and part of your steps) stops
   on 2026-07-19. The dashboard flags this. If you're still wearing the watch, check that it's
   syncing — if not, the last ~8 days of vitals in this report are incomplete, not necessarily bad.

3. WEIGHT: Only 190 direct scale readings exist in the entire export, and they stop on
   2024-06-23 (280 lb). Everything since is a BMI-derived ESTIMATE from your Hume scale
   (weight = BMI x height^2 / 703, height = 6'8"), not an actual weigh-in. The dashboard marks
   estimated points as hollow markers vs. solid for real readings. A 2024-01-03 reading of 146.6 lb
   was excluded as an obvious scale error (wildly inconsistent with every neighboring reading).

4. BLOOD PRESSURE: There is exactly one BP reading in the whole export (2024-11-18, 139/72).
   That's not a series that "stopped" — it's the only data point that ever existed.

5. HRV: No heart rate variability records exist in this Apple Health export at all.

6. GLUCOSE: All 4,596 readings come from Stelo (Dexcom's over-the-counter biosensor). Time-in-range
   is computed from every individual reading, not daily averages, so it reflects real variability.

7. NUTRITION TARGETS: The calorie/protein targets on the Nutrition tab are rough Mifflin-St Jeor
   estimates off your current estimated weight and height, with a ~750 kcal/day deficit assumed.
   These are starting points, not medical advice — adjust based on how your logged numbers actually
   track against your goal.

WHAT THIS IS AND ISN'T
------------------------
This is a personal, local tool — no hosting, no login, no server, no ongoing cost. It only updates
when you drop in a fresh Apple Health export and re-run the build. If you want it to stay current
without re-uploading every time, the next practical step is connecting a synced folder (iCloud
Drive/Dropbox) so new exports can be picked up automatically — not standing up a database or
web app, which would be overkill for a single-user health tracker.
