# Schema Notes (Stage 1) — confirmed from sampled archive files, 2026-06-28

Samples: `JC-201509-citibike-tripdata.csv.zip` (earliest JC file, legacy era) and
`JC-202605-citibike-tripdata.csv.zip` (current era). NYC files re-verified during staging;
legacy-era NYC files are known to drift in header casing/date format across 2013–2016, so the
loader treats headers case-/space-insensitively and parses dates defensively.

## Legacy era (2013 → Jan 2021)
Header (as published, Title Case with spaces):
`Trip Duration, Start Time, Stop Time, Start Station ID, Start Station Name,
Start Station Latitude, Start Station Longitude, End Station ID, End Station Name,
End Station Latitude, End Station Longitude, Bike ID, User Type, Birth Year, Gender`

- **Rider-type literals:** `Subscriber`, `Customer` (confirmed) → map Subscriber→`member`,
  Customer→`casual`.
- **Timestamps:** `2015-09-21 14:53:16` — **naive local wall-clock, no timezone offset** ✔
  (decision #5 branch confirmed: parse as `DATETIME`, `trip_day = DATE(started_at)`, no conversion).
- **Station IDs:** small integers (`3185`).
- **Coordinates:** per-trip station lat/lng present. `Birth Year` may be empty; `Gender` ∈ {0,1,2}.
- **No distance column** ✔.

## Current era (Feb 2021 →)
Header: `ride_id, rideable_type, started_at, ended_at, start_station_name, start_station_id,
end_station_name, end_station_id, start_lat, start_lng, end_lat, end_lng, member_casual`

- **`rideable_type` literals (confirmed):** `electric_bike`, `classic_bike` (watch for
  `docked_bike` in earlier 2021–22 files).
- **`member_casual` literals:** `member` (and `casual`).
- **Timestamps:** `2026-05-29 09:21:48.430` — naive local **with milliseconds** ✔ (still no offset;
  parser must accept fractional seconds).
- **Station IDs are strings with mixed formats:** `HB202`, `JC002`, `JC116`, **and** numeric-decimal
  `6617.09` — confirms station_id must be `STRING` in both eras and is not comparable across eras.
- **Zip members include `__MACOSX/…` junk** — stager must skip non-CSV members.
- **No distance column** ✔.

## Cross-system note (disclosed)
JC-published files contain trips that **end** at NYC stations (e.g. `E 53 St & Lexington Ave`,
`6617.09`). Our `region` tag therefore means **"system the file was published under"** (start-side
system), which is the decision recorded in CLAUDE.md — not a geographic claim about the end point.

## Weather table (confirmed by live query, 2026-06-28)
`nyu-datasets.weather.m_weather_daily_nyc`: key `date` (NYC-local calendar date);
`tavg_f/tmax_f/tmin_f`, `prcp_inches`, `snow_inches`, `snow_depth_inches`,
`is_rainy/is_snowy/is_foggy/is_hot_day/is_freezing/is_humid/is_thunder/is_weekend`,
`season`, `day_of_week`, wind/humidity/pressure. Join key for the dashboard: `date = trip_day`.
