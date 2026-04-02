"""One-off script to fetch a real Cars.com search page and save it as a test fixture.

Run from the backend/ directory:
    uv run python scripts/fetch_cars_com_fixture.py

The saved HTML file is used as ground truth for parser tests. Update it
periodically to catch Cars.com HTML structure changes:
    uv run python scripts/fetch_cars_com_fixture.py --update
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure app modules are importable when run from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.scrapers.cars_com import build_search_url, fetch_page_sync

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
FIXTURE_FILE = FIXTURE_DIR / "cars_com_porsche_911_p1.html"


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    url = build_search_url("porsche", "porsche-911", page=1)
    print(f"Fetching: {url}")

    html = fetch_page_sync(url)
    FIXTURE_FILE.write_text(html, encoding="utf-8")

    size_kb = len(html) / 1024
    print(f"Saved {size_kb:.1f} KB to {FIXTURE_FILE}")

    # Quick sanity check
    listing_hints = ["vehicle-card", "listing-row", "result-tile", "vehicle-item"]
    for hint in listing_hints:
        count = html.count(hint)
        if count:
            print(f"  Found '{hint}' x{count} — likely the listing container class")


if __name__ == "__main__":
    main()
