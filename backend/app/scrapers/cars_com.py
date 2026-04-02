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

# ---------------------------------------------------------------------------
# URL registry
# ---------------------------------------------------------------------------

CARS_COM_URLS: list[tuple[str, str, str, str]] = [
    # Porsche
    ("porsche-911", "Porsche 911", "porsche", "porsche-911"),
    ("porsche-718", "Porsche 718 Cayman", "porsche", "porsche-718_cayman"),
    ("porsche-918", "Porsche 918 Spyder", "porsche", "porsche-918_spyder"),
    # Ferrari
    ("ferrari-458", "Ferrari 458", "ferrari", "ferrari-458_italia"),
    ("ferrari-488", "Ferrari 488", "ferrari", "ferrari-488_gtb"),
    ("ferrari-f8", "Ferrari F8", "ferrari", "ferrari-f8_tributo"),
    ("ferrari-sf90", "Ferrari SF90", "ferrari", "ferrari-sf90_stradale"),
    ("ferrari-roma", "Ferrari Roma", "ferrari", "ferrari-roma"),
    # Lamborghini
    ("lamborghini-huracan", "Lamborghini Huracan", "lamborghini", "lamborghini-huracan"),
    ("lamborghini-aventador", "Lamborghini Aventador", "lamborghini", "lamborghini-aventador"),
    ("lamborghini-urus", "Lamborghini Urus", "lamborghini", "lamborghini-urus"),
    # McLaren
    ("mclaren-720s", "McLaren 720S", "mclaren", "mclaren-720s"),
    ("mclaren-570s", "McLaren 570S", "mclaren", "mclaren-570s"),
    ("mclaren-765lt", "McLaren 765LT", "mclaren", "mclaren-765lt"),
    ("mclaren-artura", "McLaren Artura", "mclaren", "mclaren-artura"),
    # Mercedes-AMG
    ("mercedes-amg-gt", "Mercedes-AMG GT", "mercedes_benz", "mercedes_benz-amg_gt"),
    # Audi
    ("audi-r8", "Audi R8", "audi", "audi-r8"),
    ("audi-rs6", "Audi RS6", "audi", "audi-rs6"),
    ("audi-rs7", "Audi RS7", "audi", "audi-rs7"),
    # Chevrolet
    ("chevrolet-corvette", "Chevrolet Corvette", "chevrolet", "chevrolet-corvette"),
    # Lotus
    ("lotus-emira", "Lotus Emira", "lotus", "lotus-emira"),
    ("lotus-evora", "Lotus Evora", "lotus", "lotus-evora"),
    ("lotus-exige", "Lotus Exige", "lotus", "lotus-exige"),
]

MAX_PAGES_PER_SEARCH = 3

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_all_url_keys() -> list[str]:
    return [key for key, _, _, _ in CARS_COM_URLS]


def get_url_entries() -> list[dict[str, str]]:
    return [
        {"key": key, "label": label, "make": make, "model": model}
        for key, label, make, model in CARS_COM_URLS
    ]


def build_search_url(make_slug: str, model_slug: str, page: int = 1) -> str:
    return (
        f"{BASE_URL}/shopping/results/"
        f"?stock_type=used&makes[]={make_slug}&models[]={model_slug}"
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

    def _get_urls(self) -> list[tuple[str, str, str, str]]:
        if self._selected_keys is None:
            return list(CARS_COM_URLS)
        return [(k, l, m, mo) for k, l, m, mo in CARS_COM_URLS if k in self._selected_keys]

    async def scrape(self) -> list[ScrapedListing]:
        urls = self._get_urls()
        if not urls:
            await self._emit("warning", "No Cars.com URLs selected — nothing to scrape.")
            return []

        all_listings: list[ScrapedListing] = []
        seen_urls: set[str] = set()
        await self._emit("progress", f"Starting Cars.com scrape: {len(urls)} models",
            {"total_urls": len(urls), "selected_keys": [k for k, _, _, _ in urls]})

        for i, (key, label, make_slug, model_slug) in enumerate(urls, 1):
            if self._is_cancelled():
                await self._emit("warning",
                    f"Scrape cancelled after {i - 1}/{len(urls)} models.")
                break

            new_count, dup_count, skips = 0, 0, {}
            for page_num in range(1, MAX_PAGES_PER_SEARCH + 1):
                if self._is_cancelled():
                    break
                search_url = build_search_url(make_slug, model_slug, page=page_num)
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
