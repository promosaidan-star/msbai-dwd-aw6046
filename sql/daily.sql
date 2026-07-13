-- citibike.v_daily_summary: one row per trip_day x region x rider_type.
-- citibike.daily_trips: the materialized real table, partitioned by trip_day.
--
-- COST: materialization is the ONE full scan of raw (~0.05 TB, inside the free tier).
-- Everything downstream (dashboard, verification) reads only daily_trips (a few MB).

CREATE OR REPLACE VIEW `msbai-dwd-aw6046.citibike.v_daily_summary` AS
SELECT
  trip_day,
  region,
  rider_type,
  COUNT(*)                                   AS trip_count,
  ROUND(AVG(duration_seconds) / 60, 2)       AS avg_duration_min,
  ROUND(AVG(distance_km), 3)                 AS avg_distance_km,
  COUNTIF(rideable_type = 'electric_bike')   AS ebike_trip_count,
  COUNTIF(distance_km IS NULL)               AS trips_missing_distance
FROM `msbai-dwd-aw6046.citibike.v_trips_clean`
WHERE trip_day IS NOT NULL
GROUP BY trip_day, region, rider_type;

-- Partition granularity is MONTH: BigQuery caps a table at 4,000 partitions and the
-- 2013-2026 history spans ~4,768 days; 157 monthly partitions fit with headroom and
-- prune just as well for a ~20k-row summary table.
CREATE OR REPLACE TABLE `msbai-dwd-aw6046.citibike.daily_trips`
PARTITION BY DATE_TRUNC(trip_day, MONTH)
AS
SELECT * FROM `msbai-dwd-aw6046.citibike.v_daily_summary`;
