"""
Clean_dataset.py

Turns the raw output of Extraction.py (real GDELT GKG v2.1 records) into
a clean, analysis-ready dataset -- the second stage of the
raw -> clean -> analysis pipeline.

WHAT THIS DOES
---------------
Reads the raw extraction CSV (unmodified GKG rows, real 27-column schema)
and derives analysis-ready fields from GDELT's own documented sub-fields:

    GKGRECORDID          -> Record_ID
    DATE                  -> Date, Year, Month, Year_Month
    SourceCommonName      -> Source (domain)
    DocumentIdentifier     -> Source_URL
    V2Themes (fallback: Themes) -> Themes (semicolon list, offsets stripped)
    V2Locations (first block)   -> Country, Location_Type, Latitude, Longitude
    V2Tone                -> Tone_Overall, Tone_Positive, Tone_Negative,
                              Tone_Polarity, Tone_Activity, Tone_SelfGroup

Country names are taken directly from GDELT's own human-readable
V2Locations "FullName" sub-field (documented format: a country-type
location's FullName IS the country name; city/state-type locations are
"City, State, Country" or "State, Country" -- country is the last
comma-separated segment). No separate FIPS-code lookup table is used,
to avoid introducing another source of unverified/incorrect mappings.

Rows with no usable location or no themes are dropped (logged, not
silently discarded) since they can't support the spatial/theme analysis.

USAGE
------
    python Clean_dataset.py --raw raw_gkg_extraction.csv --out gdelt_cleaned_dataset.csv
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

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


def parse_date(date_str: str):
    # GKG DATE field: YYYYMMDDHHMMSS
    try:
        return datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
    except (ValueError, TypeError):
        return None


def parse_themes(v2themes: str, themes_fallback: str) -> list[str]:
    """V2Themes entries look like 'THEME_CODE,charoffset;THEME_CODE,charoffset;...'
    Themes (v1) is just 'THEME_CODE;THEME_CODE;...' with no offsets."""
    tokens = []
    source = v2themes if v2themes else themes_fallback
    if not source:
        return tokens
    for chunk in source.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        code = chunk.split(",")[0].strip()
        if code:
            tokens.append(code)
    # de-duplicate while preserving order (a theme can appear many times with different offsets)
    seen = set()
    unique_tokens = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique_tokens.append(t)
    return unique_tokens


def parse_first_location(v2locations: str):
    """Returns (country, location_type, lat, lon) from the first location block, or all-None."""
    if not v2locations:
        return None, None, None, None

    first_block = v2locations.split(";")[0]
    parts = first_block.split("#")
    # Documented order: Type#FullName#CountryCode#ADM1Code#Lat#Long#FeatureID
    if len(parts) < 6:
        return None, None, None, None

    loc_type, fullname, country_code, adm1, lat, lon = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]

    country = None
    if fullname:
        if loc_type == "1":
            # Country-level match: FullName IS the country name
            country = fullname.strip()
        else:
            # "City, State, Country" or "State, Country" -> country is the last segment
            segments = [s.strip() for s in fullname.split(",")]
            country = segments[-1] if segments else None

    try:
        lat_f = float(lat) if lat else None
        lon_f = float(lon) if lon else None
    except ValueError:
        lat_f, lon_f = None, None

    return country, loc_type, lat_f, lon_f


def parse_tone(v2tone: str):
    """V2Tone: Tone,PositiveScore,NegativeScore,Polarity,ActivityRefDensity,SelfGroupRefDensity,WordCount"""
    if not v2tone:
        return (None,) * 6
    fields = v2tone.split(",")
    if len(fields) < 6:
        return (None,) * 6
    try:
        return tuple(float(x) if x != "" else None for x in fields[:6])
    except ValueError:
        return (None,) * 6


def clean(raw_path: Path, out_path: Path):
    print(f"Reading raw extraction from: {raw_path}")
    raw_rows = []
    with open(raw_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_rows.append(row)
    print(f"Raw rows read: {len(raw_rows)}")

    if not raw_rows:
        print("No rows to clean. Did Extraction.py find any matches?")
        return

    records = []
    dropped_no_location = 0
    dropped_no_themes = 0
    dropped_bad_date = 0

    for row in raw_rows:
        date = parse_date(row.get("DATE", ""))
        if date is None:
            dropped_bad_date += 1
            continue

        themes = parse_themes(row.get("V2Themes", ""), row.get("Themes", ""))
        if not themes:
            dropped_no_themes += 1
            continue

        country, loc_type, lat, lon = parse_first_location(row.get("V2Locations", ""))
        if lat is None or lon is None or country is None:
            dropped_no_location += 1
            continue

        tone_overall, tone_pos, tone_neg, tone_polarity, tone_activity, tone_selfgroup = parse_tone(
            row.get("V2Tone", "")
        )

        records.append({
            "Record_ID": row.get("GKGRECORDID"),
            "Date": date,
            "Year": date.year,
            "Month": date.month,
            "Year_Month": date.strftime("%Y-%m"),
            "Source": row.get("SourceCommonName"),
            "Source_URL": row.get("DocumentIdentifier"),
            "Country": country,
            "Location_Type": loc_type,
            "Latitude": lat,
            "Longitude": lon,
            "Themes": ";".join(themes),
            "Theme_Count": len(themes),
            "Tone_Overall": tone_overall,
            "Tone_Positive": tone_pos,
            "Tone_Negative": tone_neg,
            "Tone_Polarity": tone_polarity,
            "Tone_Activity": tone_activity,
            "Tone_SelfGroup": tone_selfgroup,
        })

    df = pd.DataFrame.from_records(records)

    before = len(df)
    df = df.drop_duplicates(subset=["Record_ID"])
    print(f"Deduplicated on Record_ID: removed {before - len(df)} rows")

    print(f"Dropped (bad/missing date): {dropped_bad_date}")
    print(f"Dropped (no themes found):   {dropped_no_themes}")
    print(f"Dropped (no usable location): {dropped_no_location}")
    print(f"Final cleaned dataset: {len(df)} rows")

    if len(df):
        print("\nCountries represented:", df["Country"].nunique())
        print("Date range:", df["Date"].min(), "to", df["Date"].max())
        print("\nTop themes:")
        print(df["Themes"].str.split(";").explode().value_counts().head(10))

    df.to_csv(out_path, index=False)
    print(f"\nSaved cleaned dataset to: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Clean a raw GDELT GKG extraction into an analytical dataset.")
    parser.add_argument("--raw", default="raw_gkg_extraction.csv", help="Path to raw extraction CSV from Extraction.py")
    parser.add_argument("--out", default="gdelt_cleaned_dataset.csv", help="Path to write the cleaned dataset")
    args = parser.parse_args()

    raw_path = Path(args.raw)
    if not raw_path.exists():
        print(f"ERROR: raw file not found at '{raw_path}'. Run Extraction.py first.")
        return

    clean(raw_path, Path(args.out))


if __name__ == "__main__":
    main()
