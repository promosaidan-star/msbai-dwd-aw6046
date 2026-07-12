"""Post-load gate: BigQuery raw-table row counts must equal the staging manifest exactly.

Run AFTER staging fully completes and load_raw.ps1 finishes. Free: uses table metadata
(numRows), no query bytes. Exits nonzero on any mismatch.
"""
import csv
import json
import os
import shutil
import subprocess
import sys

PROJECT = "msbai-dwd-aw6046"
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs",
                        "staging-manifest.csv")
BQ = shutil.which("bq") or r"C:\Users\ajwal\gcloud-cli\google-cloud-sdk\bin\bq.cmd"

TABLES = {
    ("legacy", "NYC"): "citibike_raw.trips_legacy_nyc",
    ("legacy", "JC"): "citibike_raw.trips_legacy_jc",
    ("current", "NYC"): "citibike_raw.trips_current_nyc",
    ("current", "JC"): "citibike_raw.trips_current_jc",
}


def main():
    expected = {k: 0 for k in TABLES}
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["status"] == "staged":
                expected[(r["era"], r["region"])] += int(r["rows"])

    failed = False
    for key, table in TABLES.items():
        out = subprocess.run([BQ, f"--project_id={PROJECT}", "show", "--format=json", table],
                             capture_output=True, text=True, shell=False)
        got = int(json.loads(out.stdout)["numRows"]) if out.returncode == 0 else -1
        ok = got == expected[key]
        failed |= not ok
        print(f"{table:35s} manifest={expected[key]:>12,} bq={got:>12,} "
              f"{'OK' if ok else '** MISMATCH **'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
