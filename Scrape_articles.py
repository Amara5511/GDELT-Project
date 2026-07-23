"""
Scrape_articles.py

Stage 2.5 of the pipeline: collects full article text for each event in the
cleaned GDELT dataset, per the proposal's methodology ("supplementary textual
data will be collected through publicly accessible APIs or controlled web
scraping using Python libraries such as requests and BeautifulSoup").

WHAT THIS DOES
---------------
For each Record_ID / Source_URL in gdelt_cleaned_dataset.csv:
    1. Checks the site's robots.txt before fetching (skips and logs the URL
       as disallowed if the site's own rules forbid automated access -- this
       is the concrete implementation of the proposal's "responsibly, in
       line with legal and ethical guidelines" requirement).
    2. Downloads the article page with a real, identifying User-Agent.
    3. Extracts the main body text with BeautifulSoup (all <p> tags, joined).
    4. Records success/failure and word count in a manifest, so every
       scraping decision is auditable -- same reproducibility standard as
       Extraction.py's manifest.
    5. Writes the raw scraped text to a JSON-lines file (one record per
       line), keyed by Record_ID.

This does NOT do any NLP cleaning (tokenisation/lemmatisation) -- that
happens later in the notebook, using spaCy, on top of this raw text. This
script's only job is honest, logged, rate-limited collection.

USAGE
-----
    pip install requests beautifulsoup4 tqdm

    python Scrape_articles.py --input gdelt_cleaned_dataset.csv \
        --out article_text.jsonl --manifest scrape_manifest.csv

    # Test on a small sample first:
    python Scrape_articles.py --input gdelt_cleaned_dataset.csv \
        --out test_articles.jsonl --manifest test_scrape_manifest.csv --limit 20

    # Resume an interrupted run:
    python Scrape_articles.py --input gdelt_cleaned_dataset.csv \
        --out article_text.jsonl --manifest scrape_manifest.csv --resume
"""

import argparse
import csv
import json
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# Some article pages have very large HTML; keep the CSV reader consistent
# with the rest of the pipeline's oversized-field handling.
_field_limit = sys.maxsize
while True:
    try:
        csv.field_size_limit(_field_limit)
        break
    except OverflowError:
        _field_limit //= 10

USER_AGENT = "Mozilla/5.0 (compatible; AcademicResearchBot/1.0; +mailto:ezechetamaureen@gmail.com)"
REQUEST_TIMEOUT = (10, 20)  # (connect, read) seconds
REQUEST_DELAY_SECONDS = 1.0  # be polite -- one request per domain-visit at a time
MIN_WORD_COUNT = 50  # articles shorter than this are usually paywalled stubs / nav text, not real content

_robots_cache = {}  # domain -> RobotFileParser, avoids re-fetching robots.txt per article


def is_allowed(url: str) -> bool:
    """Check robots.txt for this domain before fetching. Fails open (allows)
    only if robots.txt itself can't be fetched -- most sites without one are
    fine with polite bots; genuinely disallowed paths are still respected."""
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    if domain not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(domain + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp = None  # couldn't fetch robots.txt at all -- treat as unknown, not blocking
        _robots_cache[domain] = rp

    rp = _robots_cache[domain]
    if rp is None:
        return True
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def scrape_article(url: str) -> dict:
    """Returns {'status': 'ok'|'disallowed'|'error', 'text': str, 'word_count': int, 'reason': str}"""
    if not is_allowed(url):
        return {"status": "disallowed", "text": "", "word_count": 0, "reason": "robots.txt disallows this path"}

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        return {"status": "error", "text": "", "word_count": 0, "reason": str(e)}

    if resp.status_code != 200:
        return {"status": "error", "text": "", "word_count": 0, "reason": f"HTTP {resp.status_code}"}

    content_type = resp.headers.get("Content-Type", "")
    if "html" not in content_type:
        return {"status": "error", "text": "", "word_count": 0, "reason": f"non-HTML content-type: {content_type}"}

    try:
        soup = BeautifulSoup(resp.content, "html.parser")
    except Exception as e:
        return {"status": "error", "text": "", "word_count": 0, "reason": f"parse failed: {e}"}

    paragraphs = soup.find_all("p")
    text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
    word_count = len(text.split())

    if word_count < MIN_WORD_COUNT:
        return {"status": "error", "text": text, "word_count": word_count,
                "reason": f"only {word_count} words extracted (likely paywall/stub/non-article page)"}

    return {"status": "ok", "text": text, "word_count": word_count, "reason": ""}


def load_input(input_path: Path):
    with open(input_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_completed_ids(manifest_path: Path) -> set:
    if not manifest_path.exists():
        return set()
    completed = set()
    with open(manifest_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            completed.add(row["Record_ID"])
    return completed


def main():
    parser = argparse.ArgumentParser(description="Scrape full article text for events in the cleaned GDELT dataset.")
    parser.add_argument("--input", default="gdelt_cleaned_dataset.csv", help="Path to Clean_dataset.py's output")
    parser.add_argument("--out", default="article_text.jsonl", help="Output JSON-lines file of scraped text")
    parser.add_argument("--manifest", default="scrape_manifest.csv", help="Output manifest CSV")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N rows (for testing)")
    parser.add_argument("--resume", action="store_true", help="Skip Record_IDs already in --manifest and append")
    args = parser.parse_args()

    input_path = Path(args.input)
    out_path = Path(args.out)
    manifest_path = Path(args.manifest)

    if not input_path.exists():
        print(f"ERROR: {input_path} not found. Run Clean_dataset.py first.")
        return

    rows = load_input(input_path)
    if args.limit:
        rows = rows[: args.limit]

    completed_ids = load_completed_ids(manifest_path) if args.resume else set()
    if args.resume and completed_ids:
        print(f"Resuming: {len(completed_ids)} record(s) already scraped per {manifest_path}, will be skipped.")

    rows_to_do = [r for r in rows if r["Record_ID"] not in completed_ids]

    out_mode = "a" if args.resume and out_path.exists() else "w"
    manifest_mode = "a" if args.resume and manifest_path.exists() else "w"

    out_f = open(out_path, out_mode, encoding="utf-8")
    mf = open(manifest_path, manifest_mode, newline="", encoding="utf-8")
    manifest_writer = csv.DictWriter(mf, fieldnames=["Record_ID", "url", "status", "word_count", "reason"])
    if manifest_mode == "w":
        manifest_writer.writeheader()

    n_ok, n_disallowed, n_error = 0, 0, 0

    try:
        for row in tqdm(rows_to_do, desc="Scraping articles", unit="article"):
            record_id = row["Record_ID"]
            url = row.get("Source_URL", "")

            if not url:
                result = {"status": "error", "text": "", "word_count": 0, "reason": "no Source_URL in input row"}
            else:
                result = scrape_article(url)
                time.sleep(REQUEST_DELAY_SECONDS)

            if result["status"] == "ok":
                n_ok += 1
                out_f.write(json.dumps({"Record_ID": record_id, "text": result["text"]}) + "\n")
                out_f.flush()
            elif result["status"] == "disallowed":
                n_disallowed += 1
            else:
                n_error += 1

            manifest_writer.writerow({
                "Record_ID": record_id,
                "url": url,
                "status": result["status"],
                "word_count": result["word_count"],
                "reason": result["reason"],
            })
            mf.flush()
    finally:
        out_f.close()
        mf.close()

    print(f"\nDone (this run). ok={n_ok}  disallowed={n_disallowed}  error={n_error}")
    print(f"Article text written to: {out_path}")
    print(f"Manifest written to: {manifest_path}")
    print("If interrupted, re-run the same command with --resume to continue.")
    print("\nIMPORTANT: edit USER_AGENT at the top of this script to include your real "
          "contact email before running at scale -- this is standard scraping etiquette "
          "and lets site owners reach you if there's an issue, rather than just blocking you.")


if __name__ == "__main__":
    main()
