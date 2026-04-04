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
    extract_model_options_from_html,
    extract_page_meta,
    has_next_page,
    parse_listing,
)
from app.scrapers.makes import CARS_COM_MAKES, CARS_COM_TRACKED_MODELS

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


def build_search_url(make_slug: str, model_slug: str | None = None, page: int = 1) -> str:
    model_part = f"&models[]={model_slug}" if model_slug else ""
    return (
        f"{BASE_URL}/shopping/results/"
        f"?zip=60606&maximum_distance=9999&makes[]={make_slug}{model_part}"
        f"&sort=best_match_desc&page={page}"
    )


def get_tracked_model_slugs(
    make_key: str,
    available_models: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Filter available model options to only those in CARS_COM_TRACKED_MODELS.

    Returns (name, slug) pairs where name matches any tracked substring for the
    given make_key (case-insensitive substring match).
    """
    tracked_substrings = CARS_COM_TRACKED_MODELS.get(make_key)
    if not tracked_substrings:
        return []
    results = []
    for name, slug in available_models:
        name_lower = name.lower()
        if any(sub.lower() in name_lower for sub in tracked_substrings):
            results.append((name, slug))
    return results


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

            # For tracked makes: discover model slugs then scrape each make+model combo.
            # For untracked makes: fall back to make-only scraping.
            if key in CARS_COM_TRACKED_MODELS:
                await self._emit("progress",
                    f"[{i}/{len(urls)}] {label}: discovering models…")
                try:
                    discovery_html = await fetch_page(
                        build_search_url(make_slug, page=1)
                    )
                except Exception as exc:
                    await self._emit("error",
                        f"[{i}/{len(urls)}] {label} model discovery: {exc}")
                    continue
                available = extract_model_options_from_html(discovery_html, make_slug)
                model_targets = get_tracked_model_slugs(key, available)
                if not model_targets:
                    await self._emit("warning",
                        f"[{i}/{len(urls)}] {label}: no tracked models found in facets — skipping")
                    continue
                combos: list[tuple[str, str | None]] = [
                    (model_name, model_slug)
                    for model_name, model_slug in model_targets
                ]
            else:
                combos = [(label, None)]

            for model_name, model_slug in combos:
                if self._is_cancelled():
                    break
                combo_label = f"{label} {model_name}" if model_slug else label
                new_count, dup_count, skips = 0, 0, {}

                for page_num in range(1, MAX_PAGES_PER_SEARCH + 1):
                    if self._is_cancelled():
                        break
                    search_url = build_search_url(make_slug, model_slug, page=page_num)
                    await self._emit("progress",
                        f"[{i}/{len(urls)}] {combo_label} (p{page_num})…")
                    try:
                        html = await fetch_page(search_url)
                    except Exception as exc:
                        await self._emit("error",
                            f"[{i}/{len(urls)}] {combo_label} p{page_num}: {exc}")
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
                    f"[{i}/{len(urls)}] {combo_label}: {new_count} new{dup_s}{skip_s} "
                    f"(total: {len(all_listings)})")

                if not self._is_cancelled():
                    await asyncio.sleep(3.0)

        return all_listings
