# Archive Inventory — s3.amazonaws.com/tripdata (Stage 0)

Enumerated programmatically on **2026-06-28** via the S3 XML key listing (full listing in
[archive-inventory.csv](archive-inventory.csv)). **172 objects, 29,780,931,366 bytes (~29.8 GB) compressed.**

| Pattern | Count | Coverage | Notes |
|---|---|---|---|
| `YYYY-citibike-tripdata.zip` (NYC annual) | 11 | **2013–2023** | contain nested monthly zips |
| `YYYYMM-citibike-tripdata.zip` (NYC monthly) | 30 | **2024-01 → 2026-06** | begins exactly where bundles end |
| `JC-YYYYMM-citibike-tripdata[.csv].zip` (Jersey City) | 130 | **2015-09 → 2026-06** | monthly only; JC started Sep 2015 |
| `index.html` | 1 | — | ignored |

## Double-count analysis
- **Top level: no overlap.** NYC annual (2013–2023) and NYC monthly (2024-01→) partition the timeline
  exactly; JC is a disjoint file family.
- **Residual risk: nested members inside annual bundles.** The stager must inventory every nested
  member and **assert exactly one CSV per (region, month)** before loading; the assertion result is
  committed with the staging manifest.

## Load plan implied
- One canonical source per month: bundles for 2013–2023, monthly files thereafter, JC as-is.
- Latest month available at inventory time: **2026-06** (both NYC and JC).
