"""Citibike x NYC Weather dashboard (Dealing with Data, Part 2).

Cost posture: ONE cached BigQuery read of the small daily table + weather table
(a few MB); every interaction after that filters pandas in memory. Never a query
per widget change (Streamlit reruns this whole script on every interaction).

Fallback mode (pipeline unready): USE_FALLBACK=1 reshapes
nyu-datasets.citibike.m_daily_trips into the same frame.
"""
import os

import altair as alt
import pandas as pd
import streamlit as st
from google.cloud import bigquery

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "msbai-dwd-aw6046")
USE_FALLBACK = os.environ.get("USE_FALLBACK", "0") == "1"

# palette (validated reference palette, light mode)
BLUE, BLUE_LIGHT, AQUA = "#2a78d6", "#9ec5f4", "#1baf7a"
INK_MUTED, GRID = "#898781", "#e1e0d9"
RIDER_COLORS = alt.Scale(domain=["member", "casual"], range=[BLUE, AQUA])

st.set_page_config(page_title="Citibike x NYC Weather", page_icon=":bike:", layout="wide")

TRIPS_SQL = f"""
SELECT trip_day, region, rider_type, trip_count, ebike_trip_count
FROM `{PROJECT}.citibike.daily_trips`
WHERE rider_type IN ('member', 'casual')
"""

# Project-local snapshots (see scratchpad snapshot: weather_daily / fallback_daily_trips are
# copies of the nyu-datasets tables) so the Cloud Run runtime SA only reads our own project.
FALLBACK_SQL = f"""
SELECT date AS trip_day, 'NYC' AS region, 'member' AS rider_type,
       num_member_trips_nyc AS trip_count, num_electric_trips AS ebike_trip_count
FROM `{PROJECT}.citibike.fallback_daily_trips`
UNION ALL
SELECT date, 'NYC', 'casual', num_casual_trips_nyc, 0 FROM `{PROJECT}.citibike.fallback_daily_trips`
UNION ALL
SELECT date, 'JC', 'member', num_member_trips_jc, 0 FROM `{PROJECT}.citibike.fallback_daily_trips`
UNION ALL
SELECT date, 'JC', 'casual', num_casual_trips_jc, 0 FROM `{PROJECT}.citibike.fallback_daily_trips`
"""

WEATHER_SQL = f"""
SELECT date, tavg_f, prcp_inches, is_rainy, is_snowy, season
FROM `{PROJECT}.citibike.weather_daily`
"""


@st.cache_data(ttl=6 * 3600, show_spinner="Loading daily data from BigQuery (once)...")
def load_data():
    client = bigquery.Client(project=PROJECT)
    trips = client.query(FALLBACK_SQL if USE_FALLBACK else TRIPS_SQL).to_dataframe()
    weather = client.query(WEATHER_SQL).to_dataframe()
    trips["trip_day"] = pd.to_datetime(trips["trip_day"])
    weather["date"] = pd.to_datetime(weather["date"])
    return trips, weather


def base(chart):
    return chart.configure_axis(labelColor=INK_MUTED, titleColor=INK_MUTED,
                                gridColor=GRID, domainColor="#c3c2b7") \
                .configure_view(strokeWidth=0)


trips, weather = load_data()

st.title("How NYC weather moves Citibike ridership")
st.markdown(
    f"Full system history, **{trips.trip_day.min():%b %Y} - {trips.trip_day.max():%b %Y}**, "
    "one row per day from a materialized BigQuery table, joined to daily NYC weather. "
    "Built for a non-technical reader: every chart states its claim in plain English."
)

fcol1, fcol2, fcol3 = st.columns([2, 1, 1])
dmin, dmax = trips.trip_day.min().date(), trips.trip_day.max().date()
with fcol1:
    drange = st.slider("Date range", dmin, dmax, (dmin, dmax), format="MMM YYYY")
with fcol2:
    regions = st.multiselect("Region", ["NYC", "JC"], default=["NYC"],
                             help="JC = Jersey City system. NYC weather is joined, so NYC is the default.")
with fcol3:
    riders = st.multiselect("Rider type", ["member", "casual"], default=["member", "casual"])

mask = (trips.trip_day.dt.date >= drange[0]) & (trips.trip_day.dt.date <= drange[1]) \
       & trips.region.isin(regions or ["NYC"])
sel = trips[mask & trips.rider_type.isin(riders or ["member", "casual"])]
sel_all_riders = trips[mask]  # rider-complete slice for the sensitivity chart

daily = sel.groupby("trip_day", as_index=False).trip_count.sum()
daily = daily.merge(weather, left_on="trip_day", right_on="date", how="left")
daily["rides_7d"] = daily.trip_count.rolling(7, center=True).mean()

# ---- 1. Daily rides over time -------------------------------------------------------
years = daily.assign(y=daily.trip_day.dt.year).groupby("y").agg(
    n=("trip_count", "sum"), days=("trip_count", "size"))
full_years = years[years.days >= 360]
growth = (full_years.n.iloc[-1] / full_years.n.iloc[0]) if len(full_years) >= 2 else None
claim1 = (f"Ridership grew ~{growth:.0f}x from {full_years.index[0]} to {full_years.index[-1]}, "
          "peaking every summer and dipping every winter."
          if growth else "Ridership shows strong summer peaks and winter troughs.")

st.subheader("Daily rides over time")
st.markdown(f"**{claim1}**")
long = pd.concat([
    daily[["trip_day", "trip_count"]].rename(columns={"trip_count": "rides"}).assign(series="daily"),
    daily[["trip_day", "rides_7d"]].rename(columns={"rides_7d": "rides"}).assign(series="7-day average"),
])
c1 = alt.Chart(long).mark_line(strokeWidth=2).encode(
    x=alt.X("trip_day:T", title=None),
    y=alt.Y("rides:Q", title="rides / day"),
    color=alt.Color("series:N", title=None,
                    scale=alt.Scale(domain=["daily", "7-day average"], range=[BLUE_LIGHT, BLUE])),
    tooltip=[alt.Tooltip("trip_day:T", title="day"), alt.Tooltip("rides:Q", format=",.0f"),
             "series:N"],
).properties(height=280)
st.altair_chart(base(c1), use_container_width=True)

# ---- 2. Rides vs temperature --------------------------------------------------------
tw = daily.dropna(subset=["tavg_f"]).copy()
tw["temp_bin"] = (tw.tavg_f // 5 * 5).astype(int)
bins = tw.groupby("temp_bin", as_index=False).agg(avg_rides=("trip_count", "mean"),
                                                  days=("trip_count", "size"))
bins = bins[bins.days >= 5]
peak = bins.loc[bins.avg_rides.idxmax()]
claim2 = (f"Rides climb steadily with temperature and peak around "
          f"{int(peak.temp_bin)}-{int(peak.temp_bin) + 5} degF - beyond that, heat wins.")

st.subheader("Rides vs temperature")
st.markdown(f"**{claim2}**")
c2 = alt.Chart(bins).mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
    x=alt.X("temp_bin:O", title="average day temperature (degF, 5-degree bins)"),
    y=alt.Y("avg_rides:Q", title="avg rides / day"),
    tooltip=[alt.Tooltip("temp_bin:O", title="temp bin"),
             alt.Tooltip("avg_rides:Q", format=",.0f"), alt.Tooltip("days:Q", title="# days")],
).properties(height=260)
st.altair_chart(base(c2), use_container_width=True)

# ---- 3. Rainy vs dry ----------------------------------------------------------------
rain = daily.dropna(subset=["is_rainy"]).copy()
rain["condition"] = rain.is_rainy.astype(int).map({0: "dry day", 1: "rainy day"})
rd = rain.groupby("condition", as_index=False).agg(avg_rides=("trip_count", "mean"),
                                                   days=("trip_count", "size"))
if {"dry day", "rainy day"} <= set(rd.condition):
    dry = rd.loc[rd.condition == "dry day", "avg_rides"].iloc[0]
    wet = rd.loc[rd.condition == "rainy day", "avg_rides"].iloc[0]
    drop = (1 - wet / dry) * 100
    claim3 = f"A rainy day cuts ridership by ~{drop:.0f}% versus a dry day."
else:
    claim3 = "Not enough rainy/dry days in this selection to compare."

st.subheader("Rain is the strongest brake")
st.markdown(f"**{claim3}**")
c3 = alt.Chart(rd).mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
    x=alt.X("condition:N", title=None),
    y=alt.Y("avg_rides:Q", title="avg rides / day"),
    tooltip=[alt.Tooltip("condition:N"), alt.Tooltip("avg_rides:Q", format=",.0f"),
             alt.Tooltip("days:Q", title="# days")],
).properties(height=240)
st.altair_chart(base(c3), use_container_width=True)

# ---- 4. Casual vs member sensitivity ------------------------------------------------
sens = (sel_all_riders.groupby(["trip_day", "rider_type"], as_index=False).trip_count.sum()
        .merge(weather[["date", "is_rainy"]], left_on="trip_day", right_on="date"))
sens = sens.dropna(subset=["is_rainy"])
sens["condition"] = sens.is_rainy.astype(int).map({0: "dry day", 1: "rainy day"})
sr = sens.groupby(["rider_type", "condition"], as_index=False).agg(avg_rides=("trip_count", "mean"))
try:
    p = sr.pivot(index="rider_type", columns="condition", values="avg_rides")
    drop_m = (1 - p.loc["member", "rainy day"] / p.loc["member", "dry day"]) * 100
    drop_c = (1 - p.loc["casual", "rainy day"] / p.loc["casual", "dry day"]) * 100
    claim4 = (f"Rain hits casual riders ~{drop_c / drop_m:.1f}x harder: rainy days cut casual rides "
              f"{drop_c:.0f}% but member rides only {drop_m:.0f}% - casual riders (the higher-margin "
              "segment) are the ones to target with weather-aware promotions.")
except (KeyError, ZeroDivisionError):
    claim4 = "Not enough data in this selection to split rain sensitivity by rider type."

st.subheader("Who actually reacts to weather")
st.markdown(f"**{claim4}**")
c4 = alt.Chart(sr).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
    x=alt.X("condition:N", title=None),
    xOffset=alt.XOffset("rider_type:N"),
    y=alt.Y("avg_rides:Q", title="avg rides / day"),
    color=alt.Color("rider_type:N", title=None, scale=RIDER_COLORS),
    tooltip=["rider_type:N", "condition:N", alt.Tooltip("avg_rides:Q", format=",.0f")],
).properties(height=260)
st.altair_chart(base(c4), use_container_width=True)

# ---- 5. E-bike share (2021 ->) ------------------------------------------------------
eb = sel[sel.trip_day >= "2021-02-01"].groupby("trip_day", as_index=False).agg(
    rides=("trip_count", "sum"), ebikes=("ebike_trip_count", "sum"))
if len(eb) and eb.ebikes.sum() > 0:
    eb["share"] = eb.ebikes / eb.rides
    eb["share_30d"] = eb.share.rolling(30, center=True).mean()
    latest = eb.dropna(subset=["share_30d"]).iloc[-1]
    claim5 = (f"E-bikes went from a novelty to ~{latest.share_30d * 100:.0f}% of all rides "
              "(bike type is only recorded from Feb 2021 onward).")
    st.subheader("The e-bike takeover (2021 onward)")
    st.markdown(f"**{claim5}**")
    c5 = alt.Chart(eb.dropna(subset=["share_30d"])).mark_area(
        color=BLUE, opacity=0.25, line={"color": BLUE, "strokeWidth": 2}).encode(
        x=alt.X("trip_day:T", title=None),
        y=alt.Y("share_30d:Q", title="e-bike share of rides (30-day avg)",
                axis=alt.Axis(format="%")),
        tooltip=[alt.Tooltip("trip_day:T", title="day"),
                 alt.Tooltip("share_30d:Q", format=".0%", title="e-bike share")],
    ).properties(height=240)
    st.altair_chart(base(c5), use_container_width=True)

st.caption(
    "Data: public Citibike trip archive (s3://tripdata), loaded raw to BigQuery and summarized to "
    "one row per day x region x rider type; weather from nyu-datasets.weather.m_weather_daily_nyc "
    "(NYC). A trip counts toward the local calendar date it started. 'Rainy day' uses the weather "
    "table's is_rainy flag. Jersey City trips are excluded unless selected, since the weather "
    "series is NYC's.")
