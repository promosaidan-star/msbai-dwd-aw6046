# CLAUDE.md — Citibike + Weather Data Product

> **This file is the single source of truth** for decisions and the column contract. If any other
> doc disagrees, this file wins.

## Project
ETL pipeline loading the full public Citibike trip history into my own BigQuery project, cleaned and
unified, summarized to a daily table, served as a public Streamlit dashboard (Cloud Run) showing how
NYC weather affects ridership.

- **Course:** Dealing with Data (Python), NYU Stern — Prof. Ipeirotis.
- **GCP project:** `msbai-dwd-aw6046` (number 826867853591). Repo: `promosaidan-star/msbai-dwd-aw6046`.
- **Weather table (provided, read-only):** `nyu-datasets.weather.m_weather_daily_nyc` —
  **schema confirmed by live query (2026-06-28):** key `date` (NYC-local calendar date); temperature
  `tavg_f` / `tmax_f` / `tmin_f`; precipitation `prcp_inches`; snow `snow_inches`, `snow_depth_inches`;
  flags `is_rainy, is_snowy, is_foggy, is_hot_day, is_freezing, is_humid, is_thunder, is_weekend`;
  `season`, `day_of_week`, wind/humidity/pressure columns.
- **Fallback daily table (only if pipeline unready):** `nyu-datasets.citibike.m_daily_trips`.
- **Role:** owner acts as tech lead; changes land as reviewable commits/PRs with a one-line "why".

## COST MANDATE (hard constraint)
Minimize GCP spend everywhere. $10 budget alert must exist. Rules:
- `--dry_run` before any non-trivial query; report bytes scanned.
- `bq load` from GCS is **free** — prefer load jobs over query-based transforms.
- **Never re-scan raw repeatedly.** Materialize clean → daily **once** (~1 scan of ~50 GB = 0.05 TB,
  inside the 1 TiB/month free tier). Iterate on *samples*, not full raw.
- Dashboard reads only the tiny `citibike.daily_trips` (MBs), cached once per session.
- `SELECT` only needed columns; never `SELECT *` on raw.
- Delete GCS staging objects after successful load (keep the manifest); BQ storage ~50 GB ≈ $1/mo
  after the 10 GB free tier — acceptable; GCS staging would add ~$1–2/mo if left — don't leave it.

## Specify decisions

**1. What files exist — enumerated, not assumed (inventory committed 2026-06-28).**
Full listing of `s3.amazonaws.com/tripdata/`: **172 objects, ~29.8 GB compressed**
(`docs/archive-inventory.csv`). The shapes partition perfectly at the top level:
- NYC **annual bundles** `YYYY-citibike-tripdata.zip`: **2013–2023** (11 files, contain nested monthly zips)
- NYC **monthly** `YYYYMM-citibike-tripdata.zip`: **2024-01 → 2026-06** (30 files) — begins exactly
  where the bundles end, so **no top-level overlap**
- **JC monthly only** `JC-YYYYMM-…`: **2015-09 → 2026-06** (130 files; JC system started Sep 2015)
- `index.html` (ignore)
- **Decision:** load each month from exactly one source — annual bundles for 2013–2023, monthly files
  2024-01 onward, JC files as-is. Re-list the bucket before any load. The remaining double-count risk
  is **nested duplicates inside annual bundles** — the stager must inventory nested members and assert
  one CSV per (region, month) before anything is loaded.
- **Reason:** one canonical source per month is what prevents a silently double-counted month.

**2. NYC vs Jersey City — keep both, tag region.**
- **Decision:** load both; `region` ∈ {'NYC','JC'} derived from the `JC-` filename prefix. Dashboard
  defaults to NYC.
- **Reason:** dataset stays complete and sliceable while the NYC-weather join isn't polluted by JC
  trips (the provided weather table is NYC weather).

**3. Full history, two schema eras, reconciled in a view.**
Legacy era (≈2013 – Jan 2021): `tripduration, starttime, stoptime, start/end station …, usertype
(Subscriber/Customer), birth year, gender, bikeid`. Current era (≈Feb 2021 →): `ride_id,
rideable_type, started_at, ended_at, start/end_station_…, start/end lat/lng, member_casual`.
Exact column names / cutover / literals are **confirmed from sampled files in
`docs/schema-notes.md` before the view is written** — expect formatting drift within the legacy era.
- **Decision:** full history 2013 → present; raw loaded **untouched** per era
  (`citibike_raw.trips_legacy`, `citibike_raw.trips_current`); reconciliation lives in one clean view.
- **Reason:** raw stays auditable/re-derivable; schema logic is reviewable and fixable without
  re-loading 13 years.

**4. Distance — haversine in SQL, clearly labeled; no Maps API.**
No distance column exists in either era; both carry station coordinates (legacy under spaced names —
normalize per era first; coverage measured, not assumed).
- **Decision:** `distance_km = ST_DISTANCE(start_geog, end_geog) / 1000` (metres → km), NULL when
  coordinates are missing/zero. No routing API.
- **Reason:** a routing API cannot scale to 100M+ trips on a $10 budget; haversine is free arithmetic
  in SQL. **Disclosure:** straight-line dock-to-dock distance, not the ridden route; ~0 for round
  trips; NULL where coords are missing. Never reported as "miles ridden".

**5. What is a "day" — the local start date, no timezone conversion (pending Stage-1 confirmation).**
- **Decision:** a trip counts toward the calendar date of its **start** time as recorded. Citibike
  timestamps appear to be **naive local NY wall-clock** (no offset) — Stage 1 confirms from samples.
  If confirmed: parse as `DATETIME`, `trip_day = DATE(started_at)`, **no conversion**. If a real UTC
  offset is found instead, convert to America/New_York first — follow the evidence.
- **Reason:** riders decide on the local clock and local weather; the weather table is keyed by NYC
  local date, so the local wall-clock date is the correct join key.
- **Pitfall this guards against:** loading naive strings as `TIMESTAMP` (BigQuery assumes UTC) and
  then converting to NY would shift values ~4–5 h and re-date early-morning trips to the wrong day.

## Architecture
`archive → GCS (staging) → raw tables (per era) → clean unified view → daily summary view →
materialized daily table (partitioned by trip_day)`
- **GCS first:** download decoupled from load; loads re-runnable without re-downloading; handles
  nested zips; manifest = audit trail. Staging deleted after successful load (cost).
- **Clean in a view:** raw immutable; transformation logic reviewable in one place; fixable without
  re-loading.

## Canonical conventions
- `region` ∈ {'NYC','JC'} from filename prefix.
- `rider_type` ∈ {'member','casual'}; legacy `Subscriber`→member, `Customer`→casual — literals
  confirmed from samples before mapping; unmapped values flagged, not dropped.
- `rideable_type`: confirmed literals for 2021+; NULL for legacy. E-bike counts sanity-checked
  non-zero post-2021.
- `started_at`/`ended_at`: `DATETIME` (naive local NY); `trip_day = DATE(started_at)`.
- `station_id`: `CAST` to `STRING` both eras (legacy ints vs current decimal strings — different
  numbering schemes; never compare across eras; station joins use coordinates).
- `distance_km`: `ST_DISTANCE(...)/1000`; NULL if coords missing/zero.
- **Dedup only on evidence:** count duplicates first, report counts. Current era: one row per
  `ride_id` if it actually repeats. Legacy: only drop genuinely identical **full rows** — never dedup
  on a partial key (undercount risk).
- Loads idempotent, keyed by `source_file`.

## BigQuery objects
`citibike_raw.trips_legacy`, `citibike_raw.trips_current` (+ `region`, `source_file`) →
`citibike.v_trips_clean` → `citibike.v_daily_summary` → `citibike.daily_trips`
(real table, **partitioned by `trip_day`**, one row per trip_day × region × rider_type).

## Verification (Part 1 "done")
Counts must reconcile to an **independent** source:
- **Primary:** Citi Bike monthly operating reports —
  `https://mot-marketing-whitelabel-prod.s3.us-east-1.amazonaws.com/nyc/<Month>-<YYYY>-Citi-Bike-Monthly-Report.pdf`
  (pattern verified for recent months). **Read each figure from the PDF itself — never quote totals
  from memory.** Committed to `docs/verification/operating_reports.csv`; NYC system only → compare
  `region='NYC'`.
- **Floor:** `nyu-datasets.citibike` (assignment calls it not-ideal; backstop only).
Commit query + result: no month missing, none double-counted. Prime suspects if off: nested-bundle
duplicate, JC mixed into NYC, duplicate `ride_id`, over-aggressive dedup (undercount).

## Guardrails
- Verify external schemas/literals before building on them (weather ✔ 2026-06-28; reference tables
  and trip literals per Stage 1).
- Never load a month from two sources; assert one CSV per (region, month) pre-load.
- Never mutate raw; surface per-file row counts after every load.
- Flag any step scanning > a few GB before running it; `--dry_run` first.
