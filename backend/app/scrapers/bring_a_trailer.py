"""Bring a Trailer scraper — confirmed auction sales via embedded JSON data.

BaT embeds completed auction data as `auctionsCompletedInitialData` JSON in each
model page's HTML source. A simple HTTP GET + regex extraction gives us structured
listing data including sold prices, dates, and titles.
"""
import asyncio

import httpx

from app.scrapers.base import BaseScraper, ScrapedListing
from app.scrapers.bat_parser import (
    SOURCE,
    extract_items_from_html,
    parse_color,
    parse_item,
    parse_mileage,
    parse_sold_text,
    parse_year,
)

BASE_URL = "https://bringatrailer.com"

# Each entry: (url_path_key, human label, BaT URL path segment).
BAT_URLS: list[tuple[str, str, str]] = [
    # Porsche
    ("porsche-911-gt3", "Porsche 911 GT3", "porsche/911-gt3"),
    ("porsche-911-turbo", "Porsche 911 Turbo", "porsche/911-turbo"),
    ("porsche-cayman-gt4", "Porsche Cayman GT4", "porsche/cayman-gt4"),
    ("porsche-918-spyder", "Porsche 918 Spyder", "porsche/918-spyder"),
    # Ferrari
    ("ferrari-458", "Ferrari 458", "ferrari/458"),
    ("ferrari-488", "Ferrari 488", "ferrari/488"),
    ("ferrari-f8", "Ferrari F8", "ferrari/f8"),
    ("ferrari-sf90", "Ferrari SF90", "ferrari/sf90"),
    ("ferrari-roma", "Ferrari Roma", "ferrari/roma"),
    # Lamborghini
    ("lamborghini-huracan", "Lamborghini Huracán", "lamborghini/huaracan"),
    ("lamborghini-aventador", "Lamborghini Aventador", "lamborghini/aventador"),
    ("lamborghini-urus", "Lamborghini Urus", "lamborghini/urus"),
    # McLaren
    ("mclaren-super-series", "McLaren Super Series (720S/765LT)", "mclaren/super-series"),
    # Mercedes-AMG
    ("mercedes-amg-gt", "Mercedes-AMG GT", "mercedes-benz/amg-gt"),
    # Audi
    ("audi-r8", "Audi R8", "audi/r8"),
    ("audi-rs6", "Audi RS6", "audi/rs6"),
    ("audi-rs7", "Audi RS7", "audi/rs7"),
    # Chevrolet
    ("chevrolet-corvette", "Chevrolet Corvette", "chevrolet/corvette"),
    # Lotus
    ("lotus-emira", "Lotus Emira", "lotus/emira"),
    ("lotus-evora", "Lotus Evora", "lotus/evora"),
    ("lotus-exige", "Lotus Exige", "lotus/exige"),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_all_url_keys() -> list[str]:
    return [key for key, _, _ in BAT_URLS]


def get_url_entries() -> list[dict[str, str]]:
    return [{"key": key, "label": label, "path": path} for key, label, path in BAT_URLS]


async def fetch_page(client: httpx.AsyncClient, url_path: str) -> list[dict]:
    """Fetch one BaT model page and return the raw item dicts."""
    url = f"{BASE_URL}/{url_path}/"
    resp = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return extract_items_from_html(resp.text)


class BringATrailerScraper(BaseScraper):
    source = SOURCE

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._selected_keys: set[str] | None = kwargs.pop("selected_keys", None)
        self._cancel_event: asyncio.Event | None = kwargs.pop("cancel_event", None)
        super().__init__(*args, **kwargs)

    def _is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def _get_urls(self) -> list[tuple[str, str, str]]:
        if self._selected_keys is None:
            return list(BAT_URLS)
        return [(k, l, p) for k, l, p in BAT_URLS if k in self._selected_keys]

    async def scrape(self) -> list[ScrapedListing]:
        urls = self._get_urls()
        if not urls:
            await self._emit("warning", "No BaT URLs selected — nothing to scrape.")
            return []

        all_listings: list[ScrapedListing] = []
        seen_urls: set[str] = set()
        await self._emit("progress", f"Starting BaT scrape: {len(urls)} car pages selected",
            {"total_urls": len(urls), "selected_keys": [k for k, _, _ in urls]})

        async with httpx.AsyncClient() as client:
            for i, (key, label, url_path) in enumerate(urls, 1):
                if self._is_cancelled():
                    await self._emit("warning",
                        f"Scrape cancelled after {i - 1}/{len(urls)} pages.")
                    break

                await self._emit("progress", f"[{i}/{len(urls)}] Fetching: {label}…",
                    {"label": label, "key": key, "term_index": i, "total_terms": len(urls)})

                try:
                    items = await fetch_page(client, url_path)
                except httpx.HTTPError as exc:
                    await self._emit("error", f"[{i}/{len(urls)}] {label}: HTTP error — {exc}")
                    continue

                new_count, dup_count, skip_counts = 0, 0, {}
                for item in items:
                    listing, reason = parse_item(item)
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
                level = "warning" if new_count == 0 and len(items) > 0 else "progress"
                await self._emit(level,
                    f"[{i}/{len(urls)}] {label}: {len(items)} raw → "
                    f"{new_count} sold{dup_s}{skip_s} (total: {len(all_listings)})")

                if i < len(urls):
                    await asyncio.sleep(1.0)

        return all_listings
