"""Cars.com scraper — dealer/private listing asking prices only.

All records are secondary market signal: ``sold_price=NULL``, ``is_sold=False``,
``sale_type="listing"``.  These are never mixed into the depreciation model.
Uses ``curl_cffi`` for TLS-fingerprint bypass of Cloudflare.
"""
from __future__ import annotations

import asyncio

from curl_cffi import requests as cffi_requests

from app.scrapers.base import BaseScraper, ScrapedListing
from app.scrapers.cars_com_parser import (
    BASE_URL,
    SOURCE,
    extract_listings_from_html,
    extract_page_meta,
    has_next_page,
    parse_listing,
)
from app.scrapers.makes import CARS_COM_MAKES

MAX_PAGES_PER_SEARCH = 50

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_all_url_keys() -> list[str]:
    return [key for key, _, _ in CARS_COM_MAKES]


def get_url_entries() -> list[dict[str, str]]:
    return [
        {"key": key, "label": label, "make": slug}
        for key, label, slug in CARS_COM_MAKES
    ]


def build_search_url(make_slug: str, page: int = 1) -> str:
    return (
        f"{BASE_URL}/shopping/results/"
        f"?stock_type=used&makes[]={make_slug}"
        f"&maximum_distance=all&zip=60606&page={page}"
    )


def fetch_page_sync(url: str) -> str:
    """Fetch a page using curl_cffi (sync, called from thread)."""
    resp = cffi_requests.get(
        url, headers=_HEADERS, impersonate="chrome",
        timeout=30, allow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text


async def fetch_page(url: str) -> str:
    """Async wrapper — runs the sync curl_cffi call in a thread executor."""
    return await asyncio.to_thread(fetch_page_sync, url)


class CarsComScraper(BaseScraper):
    source = SOURCE

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._selected_keys: set[str] | None = kwargs.pop("selected_keys", None)
        self._cancel_event: asyncio.Event | None = kwargs.pop("cancel_event", None)
        super().__init__(*args, **kwargs)

    def _is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def _get_urls(self) -> list[tuple[str, str, str]]:
        if self._selected_keys is None:
            return list(CARS_COM_MAKES)
        return [(k, l, s) for k, l, s in CARS_COM_MAKES if k in self._selected_keys]

    async def scrape(self) -> list[ScrapedListing]:
        urls = self._get_urls()
        if not urls:
            await self._emit("warning", "No Cars.com URLs selected — nothing to scrape.")
            return []

        all_listings: list[ScrapedListing] = []
        seen_urls: set[str] = set()
        await self._emit("progress", f"Starting Cars.com scrape: {len(urls)} makes",
            {"total_urls": len(urls), "selected_keys": [k for k, _, _ in urls]})

        for i, (key, label, make_slug) in enumerate(urls, 1):
            if self._is_cancelled():
                await self._emit("warning",
                    f"Scrape cancelled after {i - 1}/{len(urls)} makes.")
                break

            new_count, dup_count, skips = 0, 0, {}
            for page_num in range(1, MAX_PAGES_PER_SEARCH + 1):
                if self._is_cancelled():
                    break
                search_url = build_search_url(make_slug, page=page_num)
                await self._emit("progress", f"[{i}/{len(urls)}] {label} (p{page_num})…")
                try:
                    html = await fetch_page(search_url)
                except Exception as exc:
                    await self._emit("error", f"[{i}/{len(urls)}] {label} p{page_num}: {exc}")
                    break
                items = extract_listings_from_html(html)
                if not items:
                    break
                for item in items:
                    listing, reason = parse_listing(item)
                    if listing is None:
                        skips[reason] = skips.get(reason, 0) + 1
                    elif listing.source_url in seen_urls:
                        dup_count += 1
                    else:
                        seen_urls.add(listing.source_url)
                        all_listings.append(listing)
                        new_count += 1
                if not has_next_page(html):
                    break
                await asyncio.sleep(3.0)

            dup_s = f", {dup_count} dups" if dup_count else ""
            skip_s = f" — skipped: {skips}" if skips else ""
            level = "warning" if new_count == 0 else "progress"
            await self._emit(level,
                f"[{i}/{len(urls)}] {label}: {new_count} new{dup_s}{skip_s} "
                f"(total: {len(all_listings)})")

            if i < len(urls) and not self._is_cancelled():
                await asyncio.sleep(3.0)

        return all_listings
