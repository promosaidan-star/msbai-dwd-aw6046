# Stage 3: load staged gzip CSVs from GCS into BigQuery raw tables.
#
# Cost: bq load jobs are FREE (no query bytes). Loads are WRITE_TRUNCATE + wildcard URIs,
# so re-running can never double-load. All columns land as STRING, untouched (cleaning
# happens in the view, per CLAUDE.md).
#
# 4 raw tables (era x region) because a load job cannot inject a constant column;
# the clean view adds `region` as a literal per table.

$ErrorActionPreference = "Stop"
$proj = "msbai-dwd-aw6046"
$bucket = "gs://msbai-dwd-aw6046-staging"

$legacySchema = "trip_duration:STRING,start_time:STRING,stop_time:STRING,start_station_id:STRING,start_station_name:STRING,start_station_lat:STRING,start_station_lng:STRING,end_station_id:STRING,end_station_name:STRING,end_station_lat:STRING,end_station_lng:STRING,bike_id:STRING,user_type:STRING,birth_year:STRING,gender:STRING"
$currentSchema = "ride_id:STRING,rideable_type:STRING,started_at:STRING,ended_at:STRING,start_station_name:STRING,start_station_id:STRING,end_station_name:STRING,end_station_id:STRING,start_lat:STRING,start_lng:STRING,end_lat:STRING,end_lng:STRING,member_casual:STRING"

bq --project_id=$proj mk --dataset --location=US --force "$($proj):citibike_raw" | Out-Null
bq --project_id=$proj mk --dataset --location=US --force "$($proj):citibike" | Out-Null

$loads = @(
    @{ table = "citibike_raw.trips_legacy_nyc";  uri = "$bucket/raw/legacy/NYC/*";  schema = $legacySchema },
    @{ table = "citibike_raw.trips_legacy_jc";   uri = "$bucket/raw/legacy/JC/*";   schema = $legacySchema },
    @{ table = "citibike_raw.trips_current_nyc"; uri = "$bucket/raw/current/NYC/*"; schema = $currentSchema },
    @{ table = "citibike_raw.trips_current_jc";  uri = "$bucket/raw/current/JC/*";  schema = $currentSchema }
)

foreach ($l in $loads) {
    Write-Host "=== loading $($l.table) from $($l.uri)"
    bq --project_id=$proj load --replace --source_format=CSV --skip_leading_rows=1 `
        --allow_quoted_newlines --max_bad_records=0 `
        $l.table $l.uri $l.schema
    if ($LASTEXITCODE -ne 0) { throw "load failed: $($l.table)" }
}

Write-Host "=== row counts (metadata only, free)"
foreach ($l in $loads) {
    bq --project_id=$proj show --format=prettyjson $l.table |
        ConvertFrom-Json | ForEach-Object { "{0}  rows={1}  bytes={2}" -f $l.table, $_.numRows, $_.numBytes }
}
