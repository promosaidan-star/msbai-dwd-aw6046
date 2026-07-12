"""Stage 2: stage the Citibike archive to GCS.

archive (s3://tripdata) -> local (one source zip at a time) -> gzipped CSVs -> gs://BUCKET/raw/...

Cost posture: GCP-side cost is GCS storage only (deleted after load); downloads from the public
S3 bucket and all compute are local. Uploads use `gcloud storage cp` (already authenticated).

Resumable: sources already recorded in the manifest are skipped. The manifest is the audit trail:
one row per staged CSV member with region, month, era, header hash, rows, bytes.

Double-count guard: after staging, asserts every (region, month) is covered by exactly ONE source
archive (multiple part-CSVs from the same source are fine).
"""
import csv
import gzip
import io
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

BUCKET = "gs://msbai-dwd-aw6046-staging"
PROJECT = "msbai-dwd-aw6046"
S3 = "https://s3.amazonaws.com/tripdata/"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "..", "data", "staging")
MANIFEST = os.path.join(HERE, "..", "docs", "staging-manifest.csv")
GCLOUD = shutil.which("gcloud") or r"C:\Users\ajwal\gcloud-cli\google-cloud-sdk\bin\gcloud.cmd"

MONTH_RE = re.compile(r"(20\d{2})[-_ ]?(\d{2})")


def list_bucket():
    keys, marker = [], ""
    while True:
        url = S3 + "?max-keys=1000" + (f"&marker={urllib.parse.quote(marker)}" if marker else "")
        with urllib.request.urlopen(url, timeout=60) as r:
            root = ET.parse(r).getroot()
        contents = root.findall(f"{NS}Contents")
        for c in contents:
            keys.append((c.find(f"{NS}Key").text, int(c.find(f"{NS}Size").text)))
        if root.find(f"{NS}IsTruncated").text == "true" and contents:
            marker = contents[-1][0] if isinstance(contents[-1], tuple) else contents[-1].find(f"{NS}Key").text
            marker = keys[-1][0]
        else:
            break
    return keys


def month_of(name, fallback):
    m = MONTH_RE.search(os.path.basename(name)) or MONTH_RE.search(fallback)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}"


def walk_csvs(zf, source_key, depth=0):
    """Yield (member_name, fileobj) for every CSV in the zip, recursing into nested zips."""
    for info in zf.infolist():
        name = info.filename
        base = os.path.basename(name)
        if "__MACOSX" in name or base.startswith("._") or not base:
            continue
        low = base.lower()
        if low.endswith(".csv"):
            yield name, zf.open(info)
        elif low.endswith(".zip") and depth < 3:
            nested = zipfile.ZipFile(io.BytesIO(zf.read(info)))
            yield from walk_csvs(nested, source_key, depth + 1)


def load_manifest():
    done, rows = set(), []
    if os.path.exists(MANIFEST):
        with open(MANIFEST, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(r)
                if r["status"] == "source_done":
                    done.add(r["source_key"])
    return done, rows


def append_manifest(rows):
    new = not os.path.exists(MANIFEST)
    with open(MANIFEST, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "source_key", "member", "region", "yyyymm", "era", "n_cols",
            "rows", "gz_bytes", "gcs_path", "status"])
        if new:
            w.writeheader()
        w.writerows(rows)


def stage_source(key, size):
    region = "JC" if key.startswith("JC-") else "NYC"
    src_dir = os.path.join(WORK, "raw")
    if os.path.exists(src_dir):
        shutil.rmtree(src_dir)
    os.makedirs(src_dir, exist_ok=True)
    zpath = os.path.join(WORK, "src.zip")

    print(f"[{key}] downloading {size/1e6:.0f} MB ...", flush=True)
    with urllib.request.urlopen(S3 + key, timeout=600) as r, open(zpath, "wb") as out:
        shutil.copyfileobj(r, out, length=1 << 20)

    entries, seen_members = [], set()
    with zipfile.ZipFile(zpath) as zf:
        for member, fh in walk_csvs(zf, key):
            base = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(member))
            if base in seen_members:          # identical member reachable twice in a bundle
                fh.close()
                continue
            seen_members.add(base)
            ym = month_of(member, key)
            if ym is None:
                print(f"  !! cannot infer month for {member}; skipping", flush=True)
                fh.close()
                continue
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            header = text.readline().rstrip("\r\n")
            n_cols = len(next(csv.reader([header])))
            era = "current" if "ride_id" in header.lower() else "legacy"
            rel = os.path.join(era, region, ym)
            os.makedirs(os.path.join(src_dir, rel), exist_ok=True)
            gz_path = os.path.join(src_dir, rel, base + ".gz")
            rows = 0
            with gzip.open(gz_path, "wt", encoding="utf-8", newline="", compresslevel=6) as gz:
                gz.write(header + "\n")
                for line in text:
                    gz.write(line if line.endswith("\n") else line + "\n")
                    rows += 1
            text.close()
            entries.append({
                "source_key": key, "member": member, "region": region, "yyyymm": ym,
                "era": era, "n_cols": n_cols, "rows": rows,
                "gz_bytes": os.path.getsize(gz_path),
                "gcs_path": f"{BUCKET}/raw/{rel.replace(os.sep, '/')}/{base}.gz",
                "status": "staged",
            })
            print(f"  {member} -> {era}/{region}/{ym} rows={rows:,} cols={n_cols}", flush=True)

    # --- intra-source duplicate guard -------------------------------------------------
    # Annual bundles ship the same month TWICE: a flat root CSV (YYYYMM-citibike-tripdata.csv)
    # AND month-folder part files (..._1.csv, _2.csv). Keep ONE canonical representation:
    # the flat file when both exist and row counts agree; hard-error if they disagree.
    by_month = {}
    for e in entries:
        by_month.setdefault((e["region"], e["yyyymm"]), []).append(e)
    for (region_, ym), es in by_month.items():
        flats = [e for e in es if not re.search(r"_\d+\.csv$", os.path.basename(e["member"]))]
        parts = [e for e in es if re.search(r"_\d+\.csv$", os.path.basename(e["member"]))]
        if flats and parts:
            flat_rows = sum(e["rows"] for e in flats)
            part_rows = sum(e["rows"] for e in parts)
            if flat_rows != part_rows:
                raise RuntimeError(
                    f"{key} {region_}/{ym}: flat rows {flat_rows:,} != parts rows {part_rows:,} "
                    "— representations are NOT duplicates; needs human review")
            for e in parts:
                gz_local = os.path.join(src_dir, e["era"], region_, ym,
                                        re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(e["member"])) + ".gz")
                if os.path.exists(gz_local):
                    os.remove(gz_local)
                e["status"] = "skipped_duplicate"
                e["gcs_path"] = ""
            print(f"  dedup {region_}/{ym}: kept flat ({flat_rows:,} rows), "
                  f"skipped {len(parts)} duplicate part file(s)", flush=True)

    n_up = sum(1 for e in entries if e["status"] == "staged")
    print(f"[{key}] uploading {n_up} files ...", flush=True)
    subprocess.run(
        [GCLOUD, "storage", "cp", "-r", os.path.join(src_dir, "*"), BUCKET + "/raw/",
         "--project", PROJECT, "--quiet"],
        check=True, shell=False)
    entries.append({"source_key": key, "member": "", "region": region, "yyyymm": "", "era": "",
                    "n_cols": "", "rows": "", "gz_bytes": "", "gcs_path": "",
                    "status": "source_done"})
    append_manifest(entries)
    try:
        os.remove(zpath)
    except OSError:
        pass  # Windows can hold a transient lock; next source overwrites it anyway
    shutil.rmtree(src_dir, ignore_errors=True)


def assert_coverage():
    _, rows = load_manifest()
    cover = {}
    for r in rows:
        if r["status"] != "staged":
            continue
        cover.setdefault((r["region"], r["yyyymm"]), set()).add(r["source_key"])
    bad = {k: v for k, v in cover.items() if len(v) > 1}
    if bad:
        print("!! DOUBLE-COUNT RISK — months covered by more than one source:")
        for k, v in sorted(bad.items()):
            print("  ", k, "<-", sorted(v))
        sys.exit(2)
    print(f"coverage OK: {len(cover)} (region, month) pairs, each from exactly one source")


def main():
    os.makedirs(WORK, exist_ok=True)
    keys = [(k, s) for k, s in list_bucket() if k.lower().endswith(".zip")]
    done, _ = load_manifest()
    todo = [(k, s) for k, s in keys if k not in done]
    print(f"{len(keys)} archives; {len(done)} already staged; {len(todo)} to do", flush=True)
    for i, (k, s) in enumerate(sorted(todo), 1):
        print(f"=== {i}/{len(todo)} ===", flush=True)
        stage_source(k, s)
    assert_coverage()


if __name__ == "__main__":
    main()
