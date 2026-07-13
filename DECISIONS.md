# DECISIONS.md — build log, verification evidence, and the traps that mattered

Companion to [CLAUDE.md](CLAUDE.md) (canonical decisions/column contract). This file records what
actually happened when the plan met the data: final numbers, reconciliation evidence, and the five
failures that would have silently corrupted the dataset if the guardrails hadn't caught them.

## Final state (2026-07-12)

- **320,268,974 trips** in `citibike.daily_trips` (4,768 days, 2013-06-01 → 2026-06-30).
- Raw tables (row counts equal the staging manifest **exactly** — enforced by the free
  metadata-only post-load gate, commit `a19d31a`):
  | table | rows |
  |---|---:|
  | `citibike_raw.trips_legacy_nyc` | 91,944,421 |
  | `citibike_raw.trips_legacy_jc` | 1,702,660 |
  | `citibike_raw.trips_current_nyc` | 221,633,844 |
  | `citibike_raw.trips_current_jc` | 4,988,049 |
  | **sum = `daily_trips` total** | **320,268,974** |
- 171 archives staged (287 region-months, one source each — no month loaded twice).
- Dashboard live on Cloud Run reading the real table (`USE_FALLBACK=0` since 2026-07-12):
  <https://citibike-dashboard-826867853591.us-central1.run.app>

## Verification (independent sources)

**Primary — Citi Bike monthly operating reports** (figures read from the PDFs, never from memory;
see [docs/verification/operating_reports.md](docs/verification/operating_reports.md)):

| month | ours | report | diff |
|---|---:|---:|---:|
| 2017-07 | 1,735,599 | 1,735,637 | **−0.00%** (−38 trips) |
| 2020-01 | 1,243,390 | 1,266,838 | −1.85% |
| 2024-06 | 4,782,935 | 4,769,243 | +0.29% |
| 2024-10 | 5,150,717 | 5,133,908 | +0.33% |
| 2025-03 | 3,167,962 | 3,241,253 | −2.26% |
| 2025-12 | 2,091,749 | 2,140,234 | −2.27% |

All within ±2.3%. The reports count trips the operator's way (data-quality filtering, definitional
differences); the raw archive is the source of truth for this pipeline, so small deviations are
expected — a 2× or ±20% deviation is what would have signaled a load bug, and none appears.

**Floor — `nyu-datasets.citibike.m_daily_trips`** (156 overlapping months,
[docs/verification/reconciliation_result.csv](docs/verification/reconciliation_result.csv)):
median absolute diff **0.000%** — the two pipelines agree to the trip on most of 13 years. The two
places they disagree are both the floor's quirk, not ours:

1. **The floor double-counts 2018-04 exactly 2×** (floor 2,615,086 = 2 × 1,307,543 = 2 × ours).
   That month the archive ships both a flat monthly CSV *and* the same month split into parts
   inside the annual bundle — count both and you double the month. Our stager's intra-bundle
   duplicate guard (commit `128949b`) asserts one source per (region, month) and deduped it; the
   floor's builder evidently didn't. Our 2018-04 also matches the seasonal shape of 2017-04/2019-04.
2. **2022-12 → 2023-05 the floor runs ~3.2–3.7% above ours.** Our raw row counts for those months
   equal our daily table exactly and there are 0 unparsed timestamps, so nothing was dropped in
   our transform; the floor likely includes rows the current-era archive no longer carries.
   Documented, not "fixed" — chasing someone else's pipeline isn't verification.

## The five traps (each cost real time; each left a commit)

1. **Nested-bundle double-count** — the 2018-04 flat+parts trap above. Guard: inventory every
   nested member, assert one CSV per (region, month) *before* anything is loaded (`128949b`).
   This is the same trap the floor table itself fell into, which is as strong an argument for the
   guard as exists.
2. **Unclosed zip handles (Windows)** — extracting nested monthly zips from the annual bundles
   left file handles open, so temp-dir cleanup failed and re-runs stalled on locked files. Fix:
   strict context-manager extraction in the stager.
3. **`gcloud` parallel uploads → `HashMismatchError`** — Windows multiprocessing uploads corrupted
   checksums intermittently. Fix: serialize uploads + retry (`1f34c3b`).
4. **Stale resumable-upload trackers** — the real root cause behind "random" HashMismatch /
   empty-GcsApiError / HTTP 400: re-runs re-gzip files, producing byte-different content with the
   same size, which resumed a stale session against the old bytes. Fix: force one-shot uploads by
   setting the resumable threshold above any file size (`a1534eb`).
5. **An archive key with a literal space** — `JC-201708 citibike-tripdata.csv.zip` (space where
   every sibling has a hyphen) 404'd the naive URL. Fix: URL-quote every key (`b016281`).
   One file out of 171 — enumerate, never pattern-match.

## Part 1 decisions, in business terms

- **Jersey City: kept, tagged `region='JC'`.** Dropping it would make the dataset silently
  incomplete; mixing it in would pollute the NYC-weather join (the provided weather series is
  NYC's). Tagging costs one column and keeps every count sliceable — the dashboard defaults to NYC.
- **Distance: straight-line dock-to-dock, computed free in SQL.** No distance column exists in
  either era, so `distance_km = ST_DISTANCE(start_geog, end_geog)/1000` in the clean view, NULL
  when coordinates are missing or zero. A routing API cannot price 320M trips inside a $10 budget;
  haversine is free arithmetic. **Where it falls short:** it is not the ridden route — it reads ~0
  for a round trip even though the bike moved — so it is never reported as "miles ridden".
- **A "day" is the local start date.** Riders decide on NYC wall-clock and NYC weather; the weather
  table is keyed by NYC-local date. Timestamps were confirmed from samples to be naive local
  wall-clock, so they parse as `DATETIME` with **no timezone conversion** — loading them as UTC
  `TIMESTAMP` and converting back would have re-dated every early-morning trip (~4–5 h shift).
- **Schema reconciliation lives in one view.** Legacy (2013 → Jan 2021: `starttime`,
  `usertype` Subscriber/Customer, three drifting date formats) and current (Feb 2021 →: `started_at`,
  `member_casual`, ms-precision) map to one canonical column set in
  [sql/v_trips_clean.sql](sql/v_trips_clean.sql): Subscriber→member, Customer→casual, unmapped
  values flagged `'unknown'` rather than dropped; station ids CAST to STRING both eras; legacy gets
  a deterministic synthetic `ride_id`. Raw stays immutable, so the mapping is reviewable and
  fixable without re-loading 13 years.

## Partition granularity: MONTH, not DAY

BigQuery caps a table at 4,000 partitions; the 2013–2026 history spans 4,768 days.
`PARTITION BY DATE_TRUNC(trip_day, MONTH)` → 157 partitions with years of headroom, and pruning is
irrelevant anyway for a ~20k-row summary table the dashboard reads whole ([sql/daily.sql](sql/daily.sql)).

## Part 2: why this dashboard

Built for a **non-technical visitor (journalist / city planner)** per [SPEC.md](SPEC.md): every
chart carries a one-sentence plain-English claim with a number computed from the data shown, not a
bare axis label. The filters (date range, region, rider type) are the three slices a non-analyst
actually asks for; bike type is deliberately a chart rather than a filter because the daily grain
carries `ebike_trip_count` — the dashboard reads a tiny daily table, never 320M raw trips. The
business hook is chart 4: rain cuts casual rides ~28% vs ~20% for members, and casual riders are
the higher-margin, promotable segment — that's the weather-aware-promotion lever.

## Dashboard go-live verification (2026-07-12): targets vs actuals

| Spec target | Actual |
|---|---|
| Correctness: 5 sampled dates exact vs `daily_trips` | **PASS — all 5 exact** (values below) |
| Speed: < 3 s warm to default view | **MISSED for full render: ≈ 7.6 s** warm to all five charts painted (see below) |
| Reach: opens in incognito, no login | **PASS** — `allUsers` has `roles/run.invoker`; loads with no auth prompt |
| Clarity: one-sentence claim per chart | **PASS** — all five claims computed from live data |

On the speed miss: the cached-BigQuery data path is fast (one query per 6 h, then pandas in
memory); the 7.6 s is Streamlit's frontend bundle boot plus rendering five ~9.5k-point Vega charts.
Reported as measured rather than restated to fit the target; cheapest mitigations if it matters:
thin the daily-line series or `--min-instances=1` before grading.

- Flipped `USE_FALLBACK=0` (revision `citibike-dashboard-00002-vch`); URL unchanged.
- **5-date correctness check** — values extracted from the *rendered* Vega dataset in the live page
  vs `SELECT SUM(trip_count) … WHERE region='NYC'` in BigQuery: 2014-07-15 = 22,963;
  2018-04-14 = 62,597; 2021-02-15 = 22,989; 2023-09-09 = 126,046; 2026-05-01 = 162,319 —
  **all five exact**, full 9,536-row series (2013-06-01 →) present in the browser.
- All five claims recompute from real data (growth ~6× 2014→2025; peak 65–70 °F; rain −21%;
  casual ~1.4× more rain-sensitive; e-bikes ~72%).
- Warm-load measurement method: in-page poll from navigation start until all five `.vega-embed`
  nodes exist (poll live from 1.9 s, charts complete at 7.6 s).

## Cost posture

Everything ran inside the free tier (~0.05 TB of query scans against the 1 TiB/month allowance;
loads are free). Steady state after deleting GCS staging (~30 GB, pending sign-off): ~50 GB BQ
storage ≈ **$1.1/month**. The $10 budget alert stands.
