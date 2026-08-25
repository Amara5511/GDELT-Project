"""
commit_data_sample.py

Use this only if gdelt_cleaned_dataset.csv or scrape_manifest.csv is too
large to commit in full. It writes:
  1. A documented random sample of the file (same header, --n rows, fixed
     seed for reproducibility).
  2. A .sha256 checksum of the FULL original file, so anyone can verify a
     locally-regenerated copy matches what was actually used for the
     assessed analysis, even though the full file itself isn't in git.

Commit the sample and the .sha256 file; keep the full file itself
.gitignore'd if it's too large.

USAGE
------
    python commit_data_sample.py --in gdelt_cleaned_dataset.csv --n 2000
    python commit_data_sample.py --in scrape_manifest.csv --n 2000
"""

import argparse
import csv
import hashlib
import random
from pathlib import Path


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sample(in_path: Path, n: int, seed: int) -> Path:
    with open(in_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    rng = random.Random(seed)
    sample_rows = rows if len(rows) <= n else rng.sample(rows, n)

    sample_path = in_path.with_name(f"{in_path.stem}_SAMPLE{in_path.suffix}")
    with open(sample_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(sample_rows)

    return sample_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", required=True, help="Full data file (e.g. gdelt_cleaned_dataset.csv)")
    parser.add_argument("--n", type=int, default=2000, help="Sample size (default 2000 rows)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed, for a reproducible sample")
    args = parser.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        print(f"ERROR: '{in_path}' not found.")
        return

    checksum = sha256_of_file(in_path)
    checksum_path = in_path.with_suffix(in_path.suffix + ".sha256")
    checksum_path.write_text(f"{checksum}  {in_path.name}\n")
    print(f"SHA-256 of full file written to: {checksum_path}\n  {checksum}")

    sample_path = write_sample(in_path, args.n, args.seed)
    print(f"Random sample ({args.n} rows, seed={args.seed}) written to: {sample_path}")
    print("\nCommit the sample and the .sha256 file. Keep the full file .gitignore'd if it's too large for git.")


if __name__ == "__main__":
    main()