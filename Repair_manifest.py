"""
Repair_manifest.py

Rebuilds extraction_manifest.csv from what's ACTUALLY in raw_gkg_extraction.csv,
for cases where the two got out of sync (e.g. a short test run and a full run
both wrote to the default filenames, overwriting each other's manifest).

Run this ONCE before using --resume, whenever raw_gkg_extraction.csv contains
days that aren't correctly reflected in extraction_manifest.csv. It's safe to
run multiple times.

USAGE
-----
    python Repair_manifest.py --raw raw_gkg_extraction.csv --manifest extraction_manifest.csv
"""

import argparse
import csv
import sys
from pathlib import Path

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


def main():
    parser = argparse.ArgumentParser(description="Rebuild the extraction manifest from an existing raw CSV.")
    parser.add_argument("--raw", default="raw_gkg_extraction.csv")
    parser.add_argument("--manifest", default="extraction_manifest.csv")
    parser.add_argument("--daily-time", default="121500",
                         help="The --daily-time value used for the extraction (default: 121500)")
    args = parser.parse_args()

    raw_path = Path(args.raw)
    manifest_path = Path(args.manifest)

    if not raw_path.exists():
        print(f"ERROR: {raw_path} not found.")
        return

    # Count rows per day actually present in the raw file
    counts_by_day = {}
    with open(raw_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        date_idx = header.index("DATE")
        for row in reader:
            if not row:
                continue
            day = row[date_idx][:8]  # YYYYMMDD
            counts_by_day[day] = counts_by_day.get(day, 0) + 1

    print(f"Days found in {raw_path}: {len(counts_by_day)}")

    # Load whatever manifest entries already exist and are correct (don't touch days
    # not present in the raw file at all -- those may be genuine zero-match days)
    existing = {}
    if manifest_path.exists():
        with open(manifest_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing[row["date"]] = row

    # Overwrite/add entries for every day actually present in the raw file,
    # using the real row count from the raw file (the source of truth)
    for day8, n in counts_by_day.items():
        date_str = f"{day8[0:4]}-{day8[4:6]}-{day8[6:8]}"
        timestamp = day8 + args.daily_time
        existing[date_str] = {
            "date": date_str,
            "timestamp_queried": timestamp,
            "source_url": GDELT_BASE_URL.format(ts=timestamp),
            "rows_matched": n,
        }

    rows_sorted = sorted(existing.values(), key=lambda r: r["date"])

    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "timestamp_queried", "source_url", "rows_matched"])
        writer.writeheader()
        writer.writerows(rows_sorted)

    print(f"Repaired manifest written to {manifest_path}: {len(rows_sorted)} total day(s) recorded.")
    print("You can now safely run Extraction.py with --resume.")


if __name__ == "__main__":
    main()