"""Cars & Bids scraper — confirmed auction sales via intercepted JSON API.

Cars & Bids uses a signed JSON API whose signature is computed client-side in the
browser. We use Playwright to render the past-auctions search page, intercept the
authenticated API responses, and extract structured auction data — no HTML parsing.

The scraper navigates to the search page once per search term, types the query,
waits for the API responses (one per page of results), and paginates by clicking
"Next" until MAX_PAGES is reached or no more results are available.

Only auctions with status == "sold" are ingested; reserve-not-met auctions are
skipped so that unconfirmed hammer prices don't contaminate the depreciation model.
"""
from __future__ import annotations

import asyncio
import logging

from app.scrapers.base import BaseScraper, ScrapedListing
from app.scrapers.cars_and_bids_parser import SOURCE, parse_auction

logger = logging.getLogger(__name__)

_BASE_URL = "https://carsandbids.com"
_PAST_AUCTIONS_URL = f"{_BASE_URL}/past-auctions/"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MAX_PAGES_PER_SEARCH = 3

# Each entry: (key, human label, search query string)
CAB_URLS: list[tuple[str, str, str]] = [
    # Porsche
    ("porsche-911-gt3", "Porsche 911 GT3", "porsche 911 gt3"),
    ("porsche-911-turbo", "Porsche 911 Turbo", "porsche 911 turbo"),
    ("porsche-cayman-gt4", "Porsche Cayman GT4", "porsche cayman gt4"),
    ("porsche-918-spyder", "Porsche 918 Spyder", "porsche 918"),
    # Ferrari
    ("ferrari-458", "Ferrari 458", "ferrari 458"),
    ("ferrari-488", "Ferrari 488", "ferrari 488"),
    ("ferrari-f8", "Ferrari F8", "ferrari f8 tributo"),
    ("ferrari-sf90", "Ferrari SF90", "ferrari sf90"),
    ("ferrari-roma", "Ferrari Roma", "ferrari roma"),
    # Lamborghini
    ("lamborghini-huracan", "Lamborghini Huracán", "lamborghini huracan"),
    ("lamborghini-aventador", "Lamborghini Aventador", "lamborghini aventador"),
    ("lamborghini-urus", "Lamborghini Urus", "lamborghini urus"),
    # McLaren
    ("mclaren-720s", "McLaren 720S", "mclaren 720s"),
    ("mclaren-765lt", "McLaren 765LT", "mclaren 765lt"),
    # Mercedes-AMG
    ("mercedes-amg-gt", "Mercedes-AMG GT", "mercedes-amg gt"),
    # Audi
    ("audi-r8", "Audi R8", "audi r8"),
    ("audi-rs6", "Audi RS6", "audi rs6"),
    ("audi-rs7", "Audi RS7", "audi rs7"),
    # Chevrolet
    ("chevrolet-corvette-c8", "Chevrolet Corvette C8", "corvette c8"),
    # Lotus
    ("lotus-emira", "Lotus Emira", "lotus emira"),
    ("lotus-evora", "Lotus Evora", "lotus evora"),
    ("lotus-exige", "Lotus Exige", "lotus exige"),
]


def get_all_url_keys() -> list[str]:
    return [key for key, _, _ in CAB_URLS]


def get_url_entries() -> list[dict[str, str]]:
    return [{"key": key, "label": label, "query": query} for key, label, query in CAB_URLS]


class CarsAndBidsScraper(BaseScraper):
    source = SOURCE

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._selected_keys: set[str] | None = kwargs.pop("selected_keys", None)
        self._cancel_event: asyncio.Event | None = kwargs.pop("cancel_event", None)
        super().__init__(*args, **kwargs)

    def _is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def _get_entries(self) -> list[tuple[str, str, str]]:
        if self._selected_keys is None:
            return list(CAB_URLS)
        return [(k, l, q) for k, l, q in CAB_URLS if k in self._selected_keys]

    async def _fetch_search_results(self, search_query: str) -> list[dict]:
        """Use Playwright to search C&B and return raw auction dicts.

        Navigates to the past-auctions page, types the search query, and intercepts
        the paginated JSON API responses. Override in tests via patch.
        """
        from playwright.async_api import async_playwright  # type: ignore[import]

        all_auctions: list[dict] = []
        captured: list[dict] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=_USER_AGENT)
            page = await context.new_page()

            async def on_response(response: "Response") -> None:  # type: ignore[name-defined]
                url = response.url
                if "/v2/autos/auctions" in url and "search=" in url and "status=closed" in url:
                    try:
                        captured.append(await response.json())
                    except Exception:
                        pass

            page.on("response", on_response)
            await page.goto(_PAST_AUCTIONS_URL, wait_until="networkidle", timeout=60_000)
            await page.wait_for_timeout(2_000)

            inp = await page.query_selector("input.form-control, input[type=search]")
            if not inp:
                logger.warning("C&B: search input not found — UI may have changed")
                await browser.close()
                return []

            await inp.click()
            await inp.fill(search_query)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(5_000)

            if captured:
                all_auctions.extend(captured[-1].get("auctions", []))

            for _ in range(MAX_PAGES_PER_SEARCH - 1):
                prev = len(captured)
                next_btn = await page.query_selector(
                    '[aria-label="Next"], .next, button.pagination-next, '
                    '.page-next, [class*="next-page"], li.next > a'
                )
                if not next_btn:
                    break
                await next_btn.click()
                for _ in range(25):  # up to 5s wait
                    await page.wait_for_timeout(200)
                    if len(captured) > prev:
                        break
                if len(captured) > prev:
                    all_auctions.extend(captured[-1].get("auctions", []))

            await browser.close()

        return all_auctions

    async def scrape(self) -> list[ScrapedListing]:
        entries = self._get_entries()
        if not entries:
            await self._emit("warning", "No C&B search terms selected — nothing to scrape.")
            return []

        all_listings: list[ScrapedListing] = []
        seen_urls: set[str] = set()
        await self._emit(
            "progress",
            f"Starting C&B scrape: {len(entries)} search terms selected",
            {"total_terms": len(entries), "selected_keys": [k for k, _, _ in entries]},
        )

        for i, (key, label, query) in enumerate(entries, 1):
            if self._is_cancelled():
                await self._emit("warning", f"Scrape cancelled after {i - 1}/{len(entries)} terms.")
                break

            await self._emit(
                "progress",
                f"[{i}/{len(entries)}] Searching: {label}…",
                {"label": label, "key": key, "term_index": i, "total_terms": len(entries)},
            )

            try:
                raw_items = await self._fetch_search_results(query)
            except Exception as exc:
                await self._emit("error", f"[{i}/{len(entries)}] {label}: error — {exc}")
                continue

            new_count, dup_count, skip_counts = 0, 0, {}
            for item in raw_items:
                listing, reason = parse_auction(item)
                if listing is None:
                    skip_counts[reason] = skip_counts.get(reason, 0) + 1
                elif listing.source_url in seen_urls:
                    dup_count += 1
                else:
                    seen_urls.add(listing.source_url)
                    all_listings.append(listing)
                    new_count += 1

            dup_s = f", {dup_count} dups" if dup_count else ""
            skip_s = f" — skipped: {skip_counts}" if skip_counts else ""
            level = "warning" if new_count == 0 and raw_items else "progress"
            await self._emit(
                level,
                f"[{i}/{len(entries)}] {label}: {len(raw_items)} raw → "
                f"{new_count} sold{dup_s}{skip_s} (total: {len(all_listings)})",
            )

            if i < len(entries):
                await asyncio.sleep(2.0)

        return all_listings
