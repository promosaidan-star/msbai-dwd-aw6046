# Independent verification source: Citi Bike monthly operating reports

Figures in [operating_reports.csv](operating_reports.csv) were **read directly from the published
PDFs** (downloaded 2026-06-28 from
`https://mot-marketing-whitelabel-prod.s3.us-east-1.amazonaws.com/nyc/<Month>-<YYYY>-Citi-Bike-Monthly-Report.pdf`),
from each report's Ridership paragraph ("There were N trips in <Month>… Annual members completed
N trips, compared to N trips by casual members").

- **Internal consistency check:** member + casual = total in every sampled report ✔
- **Sample spread:** 2017-07, 2020-01, 2024-06, 2024-10, 2025-03, 2025-12 — covers legacy era,
  COVID-era, current era, summer peak and winter trough.
- **Gaps:** reports around 2022 (e.g. Feb/Aug 2022) are scanned images with no extractable text —
  skipped rather than guessed. Reports before ~2017 are not on this bucket. `2026` months were not
  yet published at sampling time.
- **Scope:** the reports cover the **NYC system** → reconcile against `region='NYC'` only.
- **Rider-type mapping caveat:** the reports say "annual members" vs "casual"; our `member` maps
  from legacy `Subscriber` / current `member`. Definitional gaps (e.g. day-pass handling in older
  eras) may cause small member/casual splits deltas even when totals match — totals are the primary
  reconciliation target.
