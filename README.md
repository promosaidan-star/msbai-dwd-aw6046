# msbai-dwd-aw6046 — Citibike + Weather Data Product

Class project for Dealing with Data (NYU Stern, Prof. Ipeirotis): an ETL pipeline that loads the
full public Citibike trip history (2013 → present) into BigQuery, reconciles two schema eras into a
clean daily table, and serves a public Streamlit dashboard (Cloud Run) showing how NYC weather
affects ridership.

- **GCP project:** `msbai-dwd-aw6046`
- **BigQuery objects:** raw `citibike_raw.trips_legacy_nyc` / `trips_legacy_jc` /
  `trips_current_nyc` / `trips_current_jc`; clean view `citibike.v_trips_clean`; daily summary view
  `citibike.v_daily_summary`; materialized table `citibike.daily_trips` (partitioned by month of `trip_day`)
- **Dashboard (public, no login):** https://citibike-dashboard-826867853591.us-central1.run.app
- **Decisions:** see [CLAUDE.md](CLAUDE.md) (canonical) and [DECISIONS.md](DECISIONS.md)
- **Verification evidence:** [docs/verification/](docs/verification/)
