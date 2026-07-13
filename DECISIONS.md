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

## Partition granularity: MONTH, not DAY

BigQuery caps a table at 4,000 partitions; the 2013–2026 history spans 4,768 days.
`PARTITION BY DATE_TRUNC(trip_day, MONTH)` → 157 partitions with years of headroom, and pruning is
irrelevant anyway for a ~20k-row summary table the dashboard reads whole ([sql/daily.sql](sql/daily.sql)).

## Dashboard go-live verification (2026-07-12)

- Flipped `USE_FALLBACK=0` (revision `citibike-dashboard-00002-vch`); URL unchanged.
- **5-date correctness check** — values extracted from the *rendered* Vega dataset in the live page
  vs `SELECT SUM(trip_count) … WHERE region='NYC'` in BigQuery: 2014-07-15 = 22,963;
  2018-04-14 = 62,597; 2021-02-15 = 22,989; 2023-09-09 = 126,046; 2026-05-01 = 162,319 —
  **all five exact**, full 9,536-row series (2013-06-01 →) present in the browser.
- All five claims recompute from real data (growth ~6× 2014→2025; peak 65–70 °F; rain −21%;
  casual ~1.4× more rain-sensitive; e-bikes ~72%).
- **Warm load honesty:** all five charts fully rendered ≈ 7.6 s after navigation on a warm
  instance — the cached-BigQuery data path is fast, but Streamlit's frontend boot + rendering
  five ~9.5k-point Vega charts dominates. The <3 s spec target holds for data readiness, not for
  full first paint; noted rather than hidden.

## Cost posture

Everything ran inside the free tier (~0.05 TB of query scans against the 1 TiB/month allowance;
loads are free). Steady state after deleting GCS staging (~30 GB, pending sign-off): ~50 GB BQ
storage ≈ **$1.1/month**. The $10 budget alert stands.
