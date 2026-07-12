# Checkpoint A — Setup verified (2026-06-28)

| 0.9 check | Result |
|---|---|
| **Read provided weather table** — `SELECT * FROM nyu-datasets.weather.m_weather_daily_nyc WHERE date='2024-07-04'` billed to `msbai-dwd-aw6046` | ✅ 1 row returned (tavg 79.5 °F, prcp 0.04 in, is_rainy=1) |
| **Write to own project** — dataset `sandbox`, table `hello`, select-back | ✅ `hello from aw6046` returned |
| **Reach public Citibike bucket** | ✅ full S3 listing enumerated (172 objects, ~29.8 GB) — see [archive-inventory.md](archive-inventory.md) |

- GCP project: `msbai-dwd-aw6046` (number 826867853591), billing enabled.
- Budget alert: $10 (owner-managed in Cloud Console billing).
- Teaching-team access (repo collaborators + BigQuery Data Viewer IAM): owner-managed.
