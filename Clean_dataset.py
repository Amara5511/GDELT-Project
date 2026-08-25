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
                                   (V2Locations sub-fields 5 and 6, i.e. after
                                   the ADM2Code that V2 inserts after ADM1Code)
    V2Tone                -> Tone_Overall, Tone_Positive, Tone_Negative,
                              Tone_Polarity, Tone_Activity, Tone_SelfGroup

Country names are taken directly from GDELT's own human-readable
V2Locations "FullName" sub-field (documented format: a country-type
location's FullName IS the country name; city/state-type locations are
"City, State, Country" or "State, Country" -- country is the last
comma-separated segment). The number of segments is validated against
what each Location Type documents before the last segment is trusted as
a country; truncated/malformed FullName values (e.g. a bare state name
with no trailing country) are treated as having no usable country rather
than mislabelled. No separate FIPS-code lookup table is used, to avoid
introducing another source of unverified/incorrect mappings.

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
    """Returns (country, location_type, lat, lon) from the first location block, or all-None.

    Country extraction is validated against GDELT's documented FullName shape for
    each location type, rather than blindly taking the last comma-separated
    segment. A naive "last segment" rule is only correct when FullName has the
    number of segments that type implies; when a record is truncated or
    malformed (a bare state/province name with no trailing country, for
    example), the last segment is a state/province/city, not a country, and
    taking it anyway is what was inflating Country to 500+ distinct values.
    Records whose FullName doesn't match the expected shape for their type are
    treated as having no usable country (dropped downstream), rather than
    silently mislabelled.

    Documented FullName shapes by Location Type:
        1 (COUNTRY)     -> "Country"                      (1 segment)
        2 (USSTATE)     -> "State, United States"          (2 segments, ends in "United States")
        3 (USCITY)      -> "City, State, United States"    (3 segments, ends in "United States")
        4 (WORLDCITY)   -> "City, [ADM1,] Country"         (>=2 segments, last is the country)
        5 (WORLDSTATE)  -> "State/Province, Country"        (>=2 segments, last is the country)
    """
    if not v2locations:
        return None, None, None, None

    first_block = v2locations.split(";")[0]
    parts = first_block.split("#")
    # Documented V2Locations order: Type#FullName#CountryCode#ADM1Code#ADM2Code#Lat#Long#FeatureID
    # (V2Locations inserts an ADM2Code between ADM1Code and Lat that the older
    # V1 Locations field order did not have -- Lat/Long are sub-fields 5 and 6,
    # not 4 and 5.)
    if len(parts) < 7:
        return None, None, None, None

    loc_type, fullname, country_code, adm1, adm2, lat, lon = (
        parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
    )

    country = None
    if fullname:
        segments = [s.strip() for s in fullname.split(",") if s.strip()]
        if loc_type == "1":
            # Country-level match: FullName IS the country name -- exactly one segment.
            if len(segments) == 1:
                country = segments[0]
        elif loc_type in ("2", "3"):
            # US state/city: FullName must genuinely end in "United States".
            # If it doesn't (e.g. a bare "Texas" with no trailing country),
            # the record is truncated/malformed -- don't guess a country.
            if segments and segments[-1] == "United States":
                country = segments[-1]
        elif loc_type in ("4", "5"):
            # World city/state: needs at least "X, Country" -- a single bare
            # segment here is a state/province/city name, not a country.
            if len(segments) >= 2:
                country = segments[-1]
        # Any other/unrecognised loc_type: leave country as None rather than guess.

    try:
        lat_f = float(lat) if lat else None
        lon_f = float(lon) if lon else None
    except ValueError:
        lat_f, lon_f = None, None

    # Range guard: reject and log physically impossible coordinates instead of
    # passing them through (this is what let the earlier offset error slip
    # downstream undetected).
    if lat_f is not None and not (-90.0 <= lat_f <= 90.0):
        print(f"WARNING: rejected out-of-range latitude {lat_f!r}")
        lat_f = None
    if lon_f is not None and not (-180.0 <= lon_f <= 180.0):
        print(f"WARNING: rejected out-of-range longitude {lon_f!r}")
        lon_f = None

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