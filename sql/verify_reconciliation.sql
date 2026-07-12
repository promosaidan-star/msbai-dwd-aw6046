-- Stage 6 verification: our monthly NYC counts vs (a) published operating reports (primary,
-- independent) and (b) nyu-datasets.citibike.m_daily_trips (floor/backstop).
-- Cost: scans only daily_trips (a few MB) + the 568 KB floor table.

WITH ours AS (
  SELECT FORMAT_DATE('%Y-%m', trip_day) AS ym,
         SUM(trip_count)                 AS our_total,
         SUM(IF(rider_type = 'member', trip_count, 0)) AS our_member,
         SUM(IF(rider_type = 'casual', trip_count, 0)) AS our_casual
  FROM `msbai-dwd-aw6046.citibike.daily_trips`
  WHERE region = 'NYC'
  GROUP BY ym
),
floor_ref AS (
  SELECT FORMAT_DATE('%Y-%m', date) AS ym,
         SUM(num_nyc_trips)         AS floor_total
  FROM `nyu-datasets.citibike.m_daily_trips`
  GROUP BY ym
),
-- figures READ from the published PDFs (docs/verification/operating_reports.csv)
reports AS (
  SELECT '2017-07' AS ym, 1735637 AS rpt_total UNION ALL
  SELECT '2020-01', 1266838 UNION ALL
  SELECT '2024-06', 4769243 UNION ALL
  SELECT '2024-10', 5133908 UNION ALL
  SELECT '2025-03', 3241253 UNION ALL
  SELECT '2025-12', 2140234
)
SELECT
  ym,
  our_total,
  floor_total,
  rpt_total,
  ROUND(SAFE_DIVIDE(our_total - floor_total, floor_total) * 100, 2) AS pct_vs_floor,
  ROUND(SAFE_DIVIDE(our_total - rpt_total,  rpt_total)  * 100, 2)   AS pct_vs_report
FROM ours
FULL OUTER JOIN floor_ref USING (ym)
LEFT JOIN reports USING (ym)
ORDER BY ym;
