"""One-off script to fetch Cars & Bids auction data and save it as a test fixture.

Cars & Bids uses a signed JSON API that requires Playwright to obtain a valid
signature. This script navigates to the past-auctions page, triggers a search,
intercepts the API response, and saves the raw auction JSON as the fixture.

Run from the backend/ directory:
    uv run python scripts/fetch_cars_and_bids_fixture.py

Update the fixture periodically to catch C&B API schema changes:
    uv run python scripts/fetch_cars_and_bids_fixture.py --update

Requires Playwright browsers to be installed:
    uv run playwright install chromium
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page, Response

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
FIXTURE_FILE = FIXTURE_DIR / "cars_and_bids_porsche_911_gt3.json"

SEARCH_QUERY = "porsche 911 gt3"
MAX_PAGES = 3

_BASE_URL = "https://carsandbids.com"
_PAST_AUCTIONS_URL = f"{_BASE_URL}/past-auctions/"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _wait_for_api_response(
    page: Page,
    captured: list[dict],
    expected_count: int,
    timeout_ms: int = 8000,
) -> None:
    """Poll until we have at least expected_count captured responses or timeout."""
    elapsed = 0
    step = 200
    while len(captured) < expected_count and elapsed < timeout_ms:
        page.wait_for_timeout(step)
        elapsed += step


def main() -> None:
    from playwright.sync_api import sync_playwright  # type: ignore[import]

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    print("Launching Playwright (Chromium) …")
    print(f"Searching: {SEARCH_QUERY!r} on {_PAST_AUCTIONS_URL}")

    all_auctions: list[dict] = []
    captured_responses: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_USER_AGENT)
        page = context.new_page()

        def on_response(response: Response) -> None:
            url = response.url
            # Only capture search-filtered responses (contain &search= param)
            if "/v2/autos/auctions" in url and "search=" in url and "status=closed" in url:
                try:
                    captured_responses.append(response.json())
                except Exception:
                    pass

        page.on("response", on_response)

        # Load the past-auctions page (initial load — not captured, no search= param)
        page.goto(_PAST_AUCTIONS_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(2_000)

        # Type search query and submit
        search_input = page.query_selector("input.form-control, input[type=search]")
        if not search_input:
            print("ERROR: Search input not found — C&B may have changed their UI.")
            browser.close()
            return

        search_input.click()
        search_input.fill(SEARCH_QUERY)
        page.keyboard.press("Enter")

        # Wait for first page of search results (first response with search= in URL)
        _wait_for_api_response(page, captured_responses, expected_count=1)

        if captured_responses:
            first = captured_responses[-1]
            total = first.get("total", 0)
            count = first.get("count", 0)
            all_auctions.extend(first.get("auctions", []))
            print(f"  Page 1: {count} results (total available: {total})")
        else:
            print("WARNING: No API response captured on page 1.")

        # Paginate up to MAX_PAGES
        for page_num in range(2, MAX_PAGES + 1):
            if len(captured_responses) < page_num - 1:
                break  # previous page didn't load

            next_btn = page.query_selector(
                '[aria-label="Next"], .next, button.pagination-next, '
                '.page-next, [class*="next-page"], li.next > a'
            )
            if not next_btn:
                print(f"  No 'Next' button found — stopping at page {page_num - 1}.")
                break

            prev_count = len(captured_responses)
            next_btn.click()
            _wait_for_api_response(page, captured_responses, expected_count=prev_count + 1)

            if len(captured_responses) > prev_count:
                page_data = captured_responses[-1]
                count = page_data.get("count", 0)
                all_auctions.extend(page_data.get("auctions", []))
                print(f"  Page {page_num}: {count} results")
            else:
                print(f"  Page {page_num}: no response captured, stopping.")
                break

        browser.close()

    if not all_auctions:
        print(
            "\nWARNING: No auctions captured. C&B may have changed their search UI or API. "
            "Inspect the page manually and update this script."
        )
        return

    # Deduplicate by id
    seen: set[str] = set()
    unique: list[dict] = []
    for a in all_auctions:
        aid = a.get("id", "")
        if aid and aid not in seen:
            seen.add(aid)
            unique.append(a)

    FIXTURE_FILE.write_text(json.dumps(unique, indent=2), encoding="utf-8")
    size_kb = FIXTURE_FILE.stat().st_size / 1024
    print(f"\nSaved {len(unique)} auctions ({size_kb:.1f} KB) to {FIXTURE_FILE}")

    sold = [a for a in unique if a.get("status") == "sold"]
    not_met = [a for a in unique if a.get("status") != "sold"]
    print(f"  {len(sold)} sold, {len(not_met)} reserve-not-met / other")

    if sold:
        first = sold[0]
        print("\nSample sold auction:")
        print(f"  Title:   {first['title']}")
        print(f"  Price:   ${first.get('sale_amount', first.get('current_bid')):,}")
        print(f"  Mileage: {first.get('mileage')}")
        print(f"  Ended:   {first.get('auction_end')}")
        print(f"  URL:     {_BASE_URL}/auctions/{first['id']}/")


if __name__ == "__main__":
    main()
