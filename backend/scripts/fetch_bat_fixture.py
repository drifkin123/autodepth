"""One-off script to fetch a real Bring a Trailer page and save it as a test fixture.

Run from the backend/ directory:
    uv run python scripts/fetch_bat_fixture.py

The saved HTML file is used as ground truth for parser tests. Update it
periodically to catch BaT HTML structure changes:
    uv run python scripts/fetch_bat_fixture.py --update

BaT embeds completed auction data as ``auctionsCompletedInitialData`` JSON in
the page source — no JS rendering required, plain httpx works.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.scrapers.bat_parser import extract_items_from_html

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
FIXTURE_FILE = FIXTURE_DIR / "bat_porsche_911_gt3.html"

BAT_URL = "https://bringatrailer.com/porsche/911-gt3/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching: {BAT_URL}")
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        resp = client.get(BAT_URL, headers=_HEADERS)
    resp.raise_for_status()
    html = resp.text

    FIXTURE_FILE.write_text(html, encoding="utf-8")
    size_kb = len(html) / 1024
    print(f"Saved {size_kb:.1f} KB to {FIXTURE_FILE}")

    items = extract_items_from_html(html)
    sold = [i for i in items if i.get("sold_text", "").startswith("Sold")]
    print(f"Extracted {len(items)} items, {len(sold)} confirmed sold.")

    if len(items) == 0:
        print(
            "WARNING: No items extracted — BaT may have changed their HTML structure. "
            "Check that auctionsCompletedInitialData is still present in the page source."
        )


if __name__ == "__main__":
    main()
