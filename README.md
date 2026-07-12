# msbai-dwd-aw6046 — Citibike + Weather Data Product

Class project for Dealing with Data (NYU Stern, Prof. Ipeirotis): an ETL pipeline that loads the
full public Citibike trip history (2013 → present) into BigQuery, reconciles two schema eras into a
clean daily table, and serves a public Streamlit dashboard (Cloud Run) showing how NYC weather
affects ridership.

- **GCP project:** `msbai-dwd-aw6046`
- **BigQuery objects:** `citibike_raw.trips_legacy`, `citibike_raw.trips_current`,
  `citibike.v_trips_clean`, `citibike.v_daily_summary`, `citibike.daily_trips` (partitioned by `trip_day`)
- **Dashboard:** _URL pending deploy_
- **Decisions:** see [CLAUDE.md](CLAUDE.md) (canonical) and [DECISIONS.md](DECISIONS.md)
- **Verification evidence:** [docs/verification/](docs/verification/)
