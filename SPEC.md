# Part 2 Spec — Citibike × NYC Weather Dashboard

> Canonical decisions live in [CLAUDE.md](CLAUDE.md); this spec covers the dashboard product.

## Product & visitor
A public, interactive dashboard for a **curious non-technical visitor — a journalist or city
planner** — exploring how NYC weather relates to Citibike ridership across the full history
(June 2013 → present). It answers operating questions, not just "pretty data": *is ridership up
because of weather, or because of something we did?* and *who should weather-targeted promotions
reach?*

## Questions answered
1. **Weather → ridership:** how do daily rides move with temperature and precipitation?
2. **Who responds:** do **casual** riders (higher-margin, promotable) react to weather more than
   members?
3. **Trend & seasonality:** growth across 13 years and the within-year shape.
4. **E-bikes:** how much of ridership is electric now (2021 →, when bike type exists)?

## Data
- Primary: `msbai-dwd-aw6046.citibike.daily_trips` (one row per `trip_day` × region × rider_type)
  joined to `nyu-datasets.weather.m_weather_daily_nyc` on `date = trip_day`.
  Weather columns (**confirmed by live query**): `tavg_f`, `tmax_f`, `tmin_f`, `prcp_inches`,
  `snow_inches`, `is_rainy`, `is_snowy`, `season`.
- Fallback if pipeline unready: `nyu-datasets.citibike.m_daily_trips` (**schema confirmed**:
  `date, num_trips, num_nyc_trips, num_jc_trips, num_member_trips_nyc, num_casual_trips_nyc,
  num_member_trips_jc, num_casual_trips_jc, num_electric_trips, …`) reshaped to the same frame —
  switch via `USE_FALLBACK=1` env var, no code change.

## Filters & slices
- **Date range** (default: full history), **Region** (NYC / JC / both, default NYC),
  **Rider type** (member / casual / both).
- Bike type is **not a filter** — the daily grain carries `ebike_trip_count`, so e-bikes appear as
  a dedicated share-over-time chart (2021 →, labeled). This is a deliberate grain trade-off:
  the dashboard reads a tiny daily table, not 100M+ trips.

## Charts — every caption is a one-sentence claim with a number, computed from the data shown
1. **Daily rides over time** (line + 7-day average) — claim states the growth multiple.
2. **Rides vs temperature** (5 °F bins) — claim states where ridership peaks.
3. **Rainy vs dry days** — claim states the % drop on rainy days.
4. **Casual vs member weather sensitivity** — claim states how much harder rain hits casual
   riders than members (the promotion-targeting fact).
5. **E-bike share since 2021** — claim states the current share.

## Verify targets (concrete, checkable by someone else)
- **Correctness:** for 5 sampled dates, dashboard daily totals **exactly equal** a direct
  `daily_trips` query (committed evidence in `docs/verification/`).
- **Speed:** **< 3 s** to render the default view **warm** (container running, cache hot).
  Cold start after scale-to-zero is separate (~5–15 s) and reported honestly; mitigations:
  keep it warm before the demo or `--min-instances=1`.
- **Reach:** the Cloud Run URL opens in incognito with no login; a second person on a different
  network confirms.
- **Clarity:** a non-analyst can restate each chart's caption in one sentence.

## Performance / cost constraints
- Streamlit reruns the script on every interaction → the app queries BigQuery **once**
  (`@st.cache_data`, TTL 6 h), then filters in pandas. Never a query per slider move.
- It reads **only** `daily_trips` + the small weather table (a few MB total) — never raw trips.
- Cloud Run: deploy from source, `--memory 1Gi` (default 512 Mi can OOM), bind `0.0.0.0:$PORT`
  via Procfile, `--allow-unauthenticated` for public reach; scales to zero when idle (≈ $0).
- Runtime service account needs `roles/bigquery.dataViewer` + `roles/bigquery.jobUser` — the
  deployed app runs as that SA, not as me (the classic works-locally-fails-deployed identity trap).
