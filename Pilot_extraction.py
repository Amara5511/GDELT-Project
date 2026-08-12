"""
Pilot_extraction.py

Standalone pilot script for the GDELT misinformation analysis project.

Purpose
-------
Before running the full notebook pipeline (LDA, spatial analysis, regression),
this script performs a lightweight pilot pass over the raw dataset:
    1. Loads the raw Excel dataset
    2. Runs basic structural checks (required columns, dtypes)
    3. Cleans the data (dedupe, filter to Misinfo_Flag == 1, handle missing values)
    4. Draws a small pilot sample for quick manual inspection / QA
    5. Saves the cleaned full dataset and the pilot sample to /pilot_output

Usage
-----
    python Pilot_extraction.py
    python Pilot_extraction.py --data path/to/gdelt_analytical_dataset_v1.xlsx --sample-size 50
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = [
    "Record_ID", "Date", "Year", "Month", "Year_Month",
    "Country", "Latitude", "Longitude",
    "Themes", "Theme_Count", "Misinfo_Flag",
    "Tone_Overall", "Tone_Positive", "Tone_Negative",
    "Context_Category", "Tone_Category",
]

TONE_COLUMNS = [
    "Tone_Overall", "Tone_Positive", "Tone_Negative",
    "Tone_Polarity", "Tone_Activity", "Tone_SelfGroup",
]

# Optional country-name standardisation map — extend as needed
COUNTRY_MAP = {
    "United States": "USA",
    "United States of America": "USA",
    "U.S.": "USA",
    "UK": "United Kingdom",
    "Great Britain": "United Kingdom",
}


def load_data(path: Path) -> pd.DataFrame:
    print(f"[1/5] Loading dataset from: {path}")
    df = pd.read_excel(path)
    print(f"      Loaded {len(df)} rows, {len(df.columns)} columns")
    return df


def check_structure(df: pd.DataFrame) -> None:
    print("[2/5] Checking required columns...")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print(f"      WARNING: missing expected columns: {missing}")
    else:
        print("      All required columns present.")


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    print("[3/5] Cleaning data...")
    df = df.copy()

    before = len(df)
    df = df.drop_duplicates(subset=["Record_ID"])
    print(f"      Deduplicated on Record_ID: removed {before - len(df)} rows")

    before = len(df)
    if "Misinfo_Flag" in df.columns:
        df = df[df["Misinfo_Flag"] == 1]
    print(f"      Filtered to Misinfo_Flag == 1: {len(df)} of {before} rows retained")

    df = df.dropna(subset=["Latitude", "Longitude", "Themes"])

    for col in TONE_COLUMNS:
        if col in df.columns and df[col].isna().any():
            df[col] = df[col].fillna(df[col].median())

    if "Country" in df.columns:
        df["Country"] = df["Country"].replace(COUNTRY_MAP)

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df["Year"] = df["Date"].dt.year
        df["Month"] = df["Date"].dt.month
        df["Year_Month"] = df["Date"].dt.to_period("M").astype(str)

    print(f"      Clean dataset: {len(df)} rows")
    return df


def draw_pilot_sample(df: pd.DataFrame, sample_size: int, seed: int) -> pd.DataFrame:
    print(f"[4/5] Drawing pilot sample (n={sample_size}, seed={seed})...")
    n = min(sample_size, len(df))
    sample = df.sample(n=n, random_state=seed).sort_values("Record_ID")
    print(f"      Pilot sample size: {len(sample)}")
    return sample


def save_outputs(df_clean: pd.DataFrame, df_sample: pd.DataFrame, out_dir: Path) -> None:
    print(f"[5/5] Saving outputs to: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    clean_path = out_dir / "cleaned_full_dataset.csv"
    sample_path = out_dir / "pilot_sample.csv"

    df_clean.to_csv(clean_path, index=False)
    df_sample.to_csv(sample_path, index=False)

    print(f"      Wrote: {clean_path}")
    print(f"      Wrote: {sample_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot extraction for the GDELT misinformation dataset.")
    parser.add_argument(
        "--data",
        type=str,
        default="gdelt_analytical_dataset_v1.xlsx",
        help="Path to the raw Excel dataset (default: gdelt_analytical_dataset_v1.xlsx)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="Number of rows to draw for the pilot sample (default: 50)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling (default: 42)",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="pilot_output",
        help="Directory to write cleaned data and pilot sample to (default: pilot_output)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)

    if not data_path.exists():
        print(f"ERROR: data file not found at '{data_path}'. "
              f"Pass the correct path with --data /path/to/file.xlsx")
        sys.exit(1)

    df_raw = load_data(data_path)
    check_structure(df_raw)
    df_clean = clean_data(df_raw)
    df_sample = draw_pilot_sample(df_clean, args.sample_size, args.seed)
    save_outputs(df_clean, df_sample, Path(args.out_dir))

    print("\nPilot extraction complete.")
    print(f"Cleaned dataset: {len(df_clean)} rows")
    print(f"Pilot sample:    {len(df_sample)} rows")


if __name__ == "__main__":
    main()
