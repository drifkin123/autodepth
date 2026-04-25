"""Bring a Trailer scraper — confirmed auction sales via embedded JSON data.

BaT embeds completed auction data as `auctionsCompletedInitialData` JSON in each
model page's HTML source. A simple HTTP GET + regex extraction gives us structured
listing data including sold prices, dates, and titles.
"""
import asyncio
import re
from html import unescape

import httpx

from app.scrapers.base import BaseScraper, ScrapedListing
from app.scrapers.bat_parser import (
    SOURCE,
    extract_items_from_html,
    parse_item,
)
from app.scrapers.makes import BAT_MAKES

BASE_URL = "https://bringatrailer.com"
MODELS_URL = f"{BASE_URL}/models/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_all_url_keys() -> list[str]:
    return [key for key, _, _ in BAT_MAKES]


def get_url_entries() -> list[dict[str, str]]:
    return [{"key": key, "label": label, "path": slug} for key, label, slug in BAT_MAKES]


_MODEL_LINK_RE = re.compile(
    r'<a[^>]+class="[^"]*previous-listing-image-link[^"]*"[^>]+href="([^"]+)"[^>]*>.*?'
    r'<img[^>]+alt="([^"]*)"',
    re.DOTALL,
)
_EXCLUDED_MODEL_PATH_PARTS = {
    "motorcycle",
    "motorcycles",
    "trailer",
    "motorhome",
    "rv",
    "tractor",
    "boat",
    "aircraft",
    "go-kart",
    "minibike",
    "scooter",
    "wheel",
    "wheels",
    "parts",
    "side-by-side",
    "atv",
}


def extract_model_entries_from_html(html: str) -> list[tuple[str, str, str]]:
    """Extract car/SUV/truck/van model page entries from BaT's models directory."""
    entries: list[tuple[str, str, str]] = []
    seen_paths: set[str] = set()
    for href, label in _MODEL_LINK_RE.findall(html):
        path = href.replace(BASE_URL, "").strip("/")
        if not path or path in seen_paths:
            continue
        lowered_path = path.lower()
        if any(part in lowered_path for part in _EXCLUDED_MODEL_PATH_PARTS):
            continue
        seen_paths.add(path)
        key = lowered_path.replace("/", "-")
        entries.append((key, unescape(label).strip(), path))
    return entries


async def fetch_model_entries(client: httpx.AsyncClient) -> list[tuple[str, str, str]]:
    resp = await client.get(MODELS_URL, headers=_HEADERS, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return extract_model_entries_from_html(resp.text)


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
            return list(BAT_MAKES)
        return [
            (key, label, slug)
            for key, label, slug in BAT_MAKES
            if key in self._selected_keys
        ]

    async def scrape(self) -> list[ScrapedListing]:
        all_listings: list[ScrapedListing] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient() as client:
            if self._selected_keys is None:
                try:
                    urls = await fetch_model_entries(client)
                except httpx.HTTPError as exc:
                    await self._emit("error", f"Could not load BaT models directory — {exc}")
                    urls = self._get_urls()
                if not urls:
                    urls = self._get_urls()
            else:
                urls = self._get_urls()

            if not urls:
                await self._emit("warning", "No BaT URLs selected — nothing to scrape.")
                return []

            await self._emit("progress", f"Starting BaT scrape: {len(urls)} car pages selected",
                {"total_urls": len(urls), "selected_keys": [k for k, _, _ in urls]})

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
                    f"{new_count} auctions{dup_s}{skip_s} (total: {len(all_listings)})")

                if i < len(urls):
                    await asyncio.sleep(1.0)

        return all_listings
