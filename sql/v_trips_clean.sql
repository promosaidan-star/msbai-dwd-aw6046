-- citibike.v_trips_clean: both eras reconciled into one canonical column set.
-- Raw is untouched; every transform lives here (CLAUDE.md decisions #2-#5).
-- Timestamps are naive local NY wall-clock (confirmed Stage 1): parsed as DATETIME,
-- trip_day = DATE(started_at), NO timezone conversion.

CREATE OR REPLACE VIEW `msbai-dwd-aw6046.citibike.v_trips_clean` AS
WITH legacy AS (
  SELECT 'NYC' AS region, t.* FROM `msbai-dwd-aw6046.citibike_raw.trips_legacy_nyc` t
  UNION ALL
  SELECT 'JC' AS region, t.* FROM `msbai-dwd-aw6046.citibike_raw.trips_legacy_jc` t
),
current_era AS (
  SELECT 'NYC' AS region, t.* FROM `msbai-dwd-aw6046.citibike_raw.trips_current_nyc` t
  UNION ALL
  SELECT 'JC' AS region, t.* FROM `msbai-dwd-aw6046.citibike_raw.trips_current_jc` t
),
legacy_parsed AS (
  SELECT
    region,
    -- deterministic synthetic id (legacy has none)
    CONCAT('L-', TO_HEX(MD5(CONCAT(region, '|', start_time, '|', stop_time, '|',
                                   IFNULL(bike_id,''), '|', IFNULL(start_station_id,''))))) AS ride_id,
    CAST(NULL AS STRING) AS rideable_type,
    -- legacy date formats drift across years: ISO, M/D/YYYY H:M:S, M/D/YYYY H:M
    COALESCE(SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%E*S', start_time),
             SAFE.PARSE_DATETIME('%m/%d/%Y %H:%M:%E*S', start_time),
             SAFE.PARSE_DATETIME('%m/%d/%Y %H:%M',      start_time)) AS started_at,
    COALESCE(SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%E*S', stop_time),
             SAFE.PARSE_DATETIME('%m/%d/%Y %H:%M:%E*S', stop_time),
             SAFE.PARSE_DATETIME('%m/%d/%Y %H:%M',      stop_time)) AS ended_at,
    CAST(start_station_id AS STRING) AS start_station_id,
    start_station_name,
    SAFE_CAST(start_station_lat AS FLOAT64) AS start_lat,
    SAFE_CAST(start_station_lng AS FLOAT64) AS start_lng,
    CAST(end_station_id AS STRING) AS end_station_id,
    end_station_name,
    SAFE_CAST(end_station_lat AS FLOAT64) AS end_lat,
    SAFE_CAST(end_station_lng AS FLOAT64) AS end_lng,
    CASE user_type WHEN 'Subscriber' THEN 'member'
                   WHEN 'Customer'  THEN 'casual'
                   ELSE 'unknown' END AS rider_type,
    SAFE_CAST(trip_duration AS INT64) AS duration_seconds
  FROM legacy
),
current_parsed AS (
  SELECT
    region,
    ride_id,
    rideable_type,
    SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%E*S', started_at) AS started_at,
    SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%E*S', ended_at)   AS ended_at,
    start_station_id,
    start_station_name,
    SAFE_CAST(start_lat AS FLOAT64) AS start_lat,
    SAFE_CAST(start_lng AS FLOAT64) AS start_lng,
    end_station_id,
    end_station_name,
    SAFE_CAST(end_lat AS FLOAT64) AS end_lat,
    SAFE_CAST(end_lng AS FLOAT64) AS end_lng,
    CASE LOWER(member_casual) WHEN 'member' THEN 'member'
                              WHEN 'casual' THEN 'casual'
                              ELSE 'unknown' END AS rider_type,
    DATETIME_DIFF(SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%E*S', ended_at),
                  SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%E*S', started_at), SECOND) AS duration_seconds
  FROM current_era
),
unified AS (
  SELECT * FROM legacy_parsed
  UNION ALL
  SELECT * FROM current_parsed
)
SELECT
  region, ride_id, rideable_type, started_at, ended_at,
  DATE(started_at) AS trip_day,          -- local start date, no tz conversion (decision #5)
  start_station_id, start_station_name, start_lat, start_lng,
  end_station_id, end_station_name, end_lat, end_lng,
  rider_type, duration_seconds,
  -- straight-line dock-to-dock distance; ST_DISTANCE returns metres -> /1000 (decision #4)
  CASE
    WHEN start_lat IS NULL OR start_lng IS NULL OR end_lat IS NULL OR end_lng IS NULL THEN NULL
    WHEN start_lat = 0 OR start_lng = 0 OR end_lat = 0 OR end_lng = 0 THEN NULL
    ELSE ST_DISTANCE(ST_GEOGPOINT(start_lng, start_lat), ST_GEOGPOINT(end_lng, end_lat)) / 1000
  END AS distance_km
FROM unified;
