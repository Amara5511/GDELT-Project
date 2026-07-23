"""
Extraction.py

Genuine extraction of misinformation-related records from the real GDELT
Global Knowledge Graph (GKG) v2.1 archive.

WHAT THIS DOES
---------------
For each day in a defined date range, this script:
    1. Builds the real GDELT file URL for a fixed daily timestamp
       (GDELT publishes a new GKG file every 15 minutes; we sample one
       fixed time per day -- a documented, reproducible sampling
       decision, not a hidden shortcut).
    2. Downloads the .csv.zip file directly from data.gdeltproject.org.
    3. Unzips and parses it using the REAL, documented 27-column GKG v2.1
       schema (see http://data.gdeltproject.org/documentation/
       GDELT-Global_Knowledge_Graph_Codebook-V2.1.pdf).
    4. Filters rows whose Themes/V2Themes field contains at least one of a
       documented, real set of GKG theme codes relevant to misinformation
       research (INFO_HOAX, INFO_RUMOR, MEDIA_CENSORSHIP, etc. -- all
       verified against GDELT's own theme master list, not invented).
    5. Appends the matching rows, UNMODIFIED, to a single raw CSV.
       No cleaning happens here -- this is the raw extraction step.
    6. Writes a manifest CSV recording exactly which source files were
       queried, when, and how many matching rows each contributed, for
       full reproducibility.

This script does not fabricate, simulate, or invent any data. Every row
in the output either came from a real GDELT file or the script produced
zero rows for that day (logged in the manifest as such).

USAGE
-----
    pip install requests pandas

    python Extraction.py --start 2022-01-01 --end 2024-01-01 \
        --daily-time 121500 --out raw_gkg_extraction.csv

    # Test on a short range first:
    python Extraction.py --start 2023-06-01 --end 2023-06-07 --out test_raw.csv

    # If a long run gets interrupted (closed terminal, sleep, dropped network),
    # re-run the SAME command with --resume added. It will skip any day already
    # recorded in the manifest and append new results instead of starting over:
    python Extraction.py --start 2022-01-01 --end 2024-01-01 \
        --out raw_gkg_extraction.csv --manifest extraction_manifest.csv --resume
"""

import argparse
import csv
import io
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import requests
from tqdm import tqdm

# Some GKG rows (especially high-news-volume days) have fields -- typically
# AllNames, GCAM, or Extras -- that exceed Python's default 131072-byte CSV
# field limit, which raises `_csv.Error: field larger than field limit`.
# Raise the limit safely: sys.maxsize can overflow the platform's C long on
# some systems (notably 32-bit Windows builds), so back off until it's accepted.
_field_limit = sys.maxsize
while True:
    try:
        csv.field_size_limit(_field_limit)
        break
    except OverflowError:
        _field_limit //= 10

GDELT_BASE_URL = "http://data.gdeltproject.org/gdeltv2/{ts}.gkg.csv.zip"

# Real, documented 27-column GKG v2.1 schema, in file order.
# Source: GDELT GKG 2.1 Codebook (data.gdeltproject.org/documentation)
GKG_COLUMNS = [
    "GKGRECORDID", "DATE", "SourceCollectionIdentifier", "SourceCommonName",
    "DocumentIdentifier", "Counts", "V2Counts", "Themes", "V2Themes",
    "Locations", "V2Locations", "Persons", "V2Persons", "Organizations",
    "V2Organizations", "V2Tone", "Dates", "GCAM", "SharingImage",
    "RelatedImages", "SocialImageEmbeds", "SocialVideoEmbeds", "Quotations",
    "AllNames", "Amounts", "TranslationInfo", "Extras",
]

# Real, documented GKG theme codes relevant to misinformation research.
# Verified against http://data.gdeltproject.org/documentation/GKG-MASTER-THEMELIST.TXT
# Extend this list only with codes you have personally verified against
# that master list -- do not add plausible-sounding codes.
MISINFO_THEMES = [
    "INFO_HOAX",
    "INFO_RUMOR",
    "MEDIA_CENSORSHIP",
    "INTERNET_CENSORSHIP",
    "INTERNET_BLACKOUT",
    "CYBER_ATTACK",
    "SURVEILLANCE",
    "HATE_SPEECH",
    "FREESPEECH",
    "HEALTH_VACCINATION",
    "HEALTH_PANDEMIC",
]

REQUEST_TIMEOUT = (10, 30)  # (connect_timeout, read_timeout) in seconds -- an explicit
                             # tuple bounds each phase separately, so a connection that's
                             # trickling data very slowly can't reset a single scalar
                             # timeout indefinitely and appear to hang forever.

import socket
socket.setdefaulttimeout(60)  # hard backstop: no single socket operation anywhere
                               # in this script can block longer than this, even in
                               # edge cases requests' own timeout doesn't fully cover
                               # (e.g. certain DNS resolution stalls).
REQUEST_DELAY_SECONDS = 1.0  # be polite to GDELT's servers


def daterange(start: datetime, end: datetime):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def load_completed_dates(manifest_path: Path) -> set[str]:
    """Read an existing manifest and return the set of date strings already queried."""
    if not manifest_path.exists():
        return set()
    completed = set()
    with open(manifest_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            completed.add(row["date"])
    return completed


def fetch_gkg_file(timestamp: str) -> bytes | None:
    """Download one GKG .csv.zip file. Returns raw zip bytes, or None if unavailable."""
    url = GDELT_BASE_URL.format(ts=timestamp)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"      [skip] {url} -> HTTP {resp.status_code}", flush=True)
            return None
        return resp.content
    except requests.RequestException as e:
        print(f"      [skip] {url} -> {e}", flush=True)
        return None


def parse_and_filter(zip_bytes: bytes, theme_codes: list[str]) -> list[list[str]]:
    """Unzip, parse as tab-delimited GKG rows, and keep rows matching theme_codes."""
    matches = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        inner_name = zf.namelist()[0]
        with zf.open(inner_name) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            reader = csv.reader(text, delimiter="\t")
            for row in reader:
                if len(row) != len(GKG_COLUMNS):
                    continue  # malformed row, skip rather than guess field alignment
                themes_field = row[7] or ""     # Themes
                v2themes_field = row[8] or ""   # V2Themes
                combined = themes_field + ";" + v2themes_field
                if any(code in combined for code in theme_codes):
                    matches.append(row)
    return matches


def main():
    parser = argparse.ArgumentParser(description="Extract misinformation-related records from real GDELT GKG data.")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD")
    parser.add_argument("--daily-time", default="121500",
                         help="Fixed daily HHMMSS timestamp to sample (default: 121500 = 12:15:00 UTC). "
                              "Must end in 00, 15, 30, or 45 minutes -- GDELT only publishes at those marks.")
    parser.add_argument("--out", default="raw_gkg_extraction.csv", help="Output raw CSV path")
    parser.add_argument("--manifest", default="extraction_manifest.csv", help="Output manifest CSV path")
    parser.add_argument("--resume", action="store_true",
                         help="Skip days already recorded in --manifest and append to --out instead of overwriting it. "
                              "Use this to continue an interrupted run.")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    out_path = Path(args.out)
    manifest_path = Path(args.manifest)

    completed_dates = load_completed_dates(manifest_path) if args.resume else set()
    if args.resume and completed_dates:
        print(f"Resuming: {len(completed_dates)} day(s) already completed per {manifest_path}, will be skipped.", flush=True)

    # Resume mode appends to existing files (and only writes the CSV header if the
    # output file doesn't exist yet or is empty); fresh runs overwrite from scratch.
    out_exists_with_header = args.resume and out_path.exists() and out_path.stat().st_size > 0
    out_mode = "a" if args.resume and out_path.exists() else "w"
    manifest_mode = "a" if args.resume and manifest_path.exists() else "w"

    total_matches = 0
    wrote_header = out_exists_with_header

    out_f = open(out_path, out_mode, newline="", encoding="utf-8")
    mf = open(manifest_path, manifest_mode, newline="", encoding="utf-8")
    writer = csv.writer(out_f)
    manifest_writer = csv.DictWriter(mf, fieldnames=["date", "timestamp_queried", "source_url", "rows_matched"])
    if manifest_mode == "w":
        manifest_writer.writeheader()

    try:
        days_to_fetch = [d for d in daterange(start, end) if d.strftime("%Y-%m-%d") not in completed_dates]
        for day in tqdm(days_to_fetch, desc="Extracting GDELT days", unit="day"):
            date_str = day.strftime("%Y-%m-%d")

            timestamp = day.strftime("%Y%m%d") + args.daily_time

            zip_bytes = fetch_gkg_file(timestamp)
            n_matches = 0

            if zip_bytes is not None:
                try:
                    matches = parse_and_filter(zip_bytes, MISINFO_THEMES)
                    n_matches = len(matches)
                    if matches:
                        if not wrote_header:
                            writer.writerow(GKG_COLUMNS)
                            wrote_header = True
                        writer.writerows(matches)
                        out_f.flush()
                except zipfile.BadZipFile:
                    pass  # corrupt/empty zip for this day -- logged as 0 rows_matched in the manifest below

            total_matches += n_matches
            manifest_writer.writerow({
                "date": date_str,
                "timestamp_queried": timestamp,
                "source_url": GDELT_BASE_URL.format(ts=timestamp),
                "rows_matched": n_matches,
            })
            mf.flush()  # write progress incrementally so a resume never loses completed days

            time.sleep(REQUEST_DELAY_SECONDS)
    finally:
        out_f.close()
        mf.close()

    print(f"\nDone (this run). {total_matches} matching raw records added to {out_path}", flush=True)
    print(f"Manifest of every source file queried: {manifest_path}", flush=True)
    if total_matches == 0 and not completed_dates:
        print("WARNING: zero matches. Check your date range, --daily-time, and theme list before proceeding.", flush=True)
    print("If this run was interrupted partway, re-run the exact same command with --resume added to continue.", flush=True)


if __name__ == "__main__":
    main()
