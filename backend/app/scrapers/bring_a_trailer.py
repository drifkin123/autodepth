"""Bring a Trailer scraper — confirmed auction sales via embedded JSON data.

BaT embeds completed auction data as `auctionsCompletedInitialData` JSON in each
model page's HTML source. A simple HTTP GET + regex extraction gives us structured
listing data including sold prices, dates, and titles.
"""
import asyncio
import re
import time
from html import unescape

import httpx

from app.scrapers.base import BaseScraper, ScrapedAuctionLot
from app.scrapers.bat_parser import (
    SOURCE,
    extract_items_from_html,
    parse_item,
)
from app.scrapers.makes import BAT_MAKES
from app.scrapers.runtime import (
    BROWSER_HEADERS,
    BlockedScrapeError,
    RetryPolicy,
    TransientScrapeError,
    is_block_status,
    polite_delay_seconds,
)

BASE_URL = "https://bringatrailer.com"
MODELS_URL = f"{BASE_URL}/models/"

_HEADERS = BROWSER_HEADERS
_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=30.0)


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

    async def _fetch_page_with_retries(
        self,
        client: httpx.AsyncClient,
        *,
        label: str,
        url_path: str,
    ) -> list[dict] | None:
        url = f"{BASE_URL}/{url_path}/"
        for attempt in range(1, _RETRY_POLICY.max_attempts + 1):
            started = time.perf_counter()
            try:
                return await fetch_page(client, url_path)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response else None
                duration_ms = int((time.perf_counter() - started) * 1000)
                if is_block_status(status_code):
                    await self.record_request_log(
                        url=url,
                        action="http_get",
                        attempt=attempt,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        outcome="blocked",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        metadata_json={"target": label},
                    )
                    await self.record_anomaly(
                        severity="critical",
                        code="blocked_response",
                        message=f"BaT blocked or rate-limited request for {label}.",
                        url=url,
                        metadata_json={"status_code": status_code, "attempt": attempt},
                    )
                    raise BlockedScrapeError(str(exc), status_code=status_code) from exc
                if status_code is not None and status_code >= 500:
                    error = TransientScrapeError(str(exc))
                else:
                    error = exc
                if isinstance(error, TransientScrapeError) and attempt < _RETRY_POLICY.max_attempts:
                    delay = _RETRY_POLICY.delay_for_attempt(attempt)
                    await self.record_request_log(
                        url=url,
                        action="http_get",
                        attempt=attempt,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        outcome="retry",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        retry_delay_seconds=delay,
                        metadata_json={"target": label},
                    )
                    await asyncio.sleep(delay)
                    continue
                await self.record_request_log(
                    url=url,
                    action="http_get",
                    attempt=attempt,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    outcome="error",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    metadata_json={"target": label},
                )
                return None
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                if attempt < _RETRY_POLICY.max_attempts:
                    delay = _RETRY_POLICY.delay_for_attempt(attempt)
                    await self.record_request_log(
                        url=url,
                        action="http_get",
                        attempt=attempt,
                        duration_ms=duration_ms,
                        outcome="retry",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        retry_delay_seconds=delay,
                        metadata_json={"target": label},
                    )
                    await asyncio.sleep(delay)
                    continue
                await self.record_request_log(
                    url=url,
                    action="http_get",
                    attempt=attempt,
                    duration_ms=duration_ms,
                    outcome="error",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    metadata_json={"target": label},
                )
                return None
        return None

    async def scrape(self) -> list[ScrapedAuctionLot]:
        all_lots: list[ScrapedAuctionLot] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient() as client:
            if self._selected_keys is None:
                try:
                    started = time.perf_counter()
                    urls = await fetch_model_entries(client)
                    await self.record_request_log(
                        url=MODELS_URL,
                        action="models_directory",
                        attempt=1,
                        status_code=200,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        outcome="success",
                        raw_item_count=len(urls),
                        parsed_lot_count=len(urls),
                    )
                except httpx.HTTPError as exc:
                    await self.record_request_log(
                        url=MODELS_URL,
                        action="models_directory",
                        attempt=1,
                        outcome="error",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                    await self._emit("error", f"Could not load BaT models directory — {exc}")
                    urls = self._get_urls()
                if not urls:
                    await self.record_anomaly(
                        severity="critical",
                        code="models_directory_empty",
                        message="BaT models directory returned no crawl targets.",
                        url=MODELS_URL,
                    )
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
                    started = time.perf_counter()
                    items = await self._fetch_page_with_retries(
                        client, label=label, url_path=url_path
                    )
                except BlockedScrapeError as exc:
                    await self._emit("error", f"[{i}/{len(urls)}] {label}: blocked — {exc}")
                    break
                if items is None:
                    await self._emit("error", f"[{i}/{len(urls)}] {label}: request failed")
                    continue

                new_count, dup_count, skip_counts = 0, 0, {}
                for item in items:
                    listing, reason = parse_item(item)
                    if listing is None:
                        skip_counts[reason] = skip_counts.get(reason, 0) + 1
                    elif listing.canonical_url in seen_urls:
                        dup_count += 1
                    else:
                        seen_urls.add(listing.canonical_url)
                        all_lots.append(listing)
                        new_count += 1

                await self.record_request_log(
                    url=f"{BASE_URL}/{url_path}/",
                    action="http_get",
                    attempt=1,
                    status_code=200,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    outcome="success",
                    raw_item_count=len(items),
                    parsed_lot_count=new_count,
                    skip_counts=skip_counts,
                    metadata_json={"label": label, "key": key, "duplicates": dup_count},
                )
                if len(items) > 0 and new_count == 0:
                    await self.record_anomaly(
                        severity="warning",
                        code="zero_parsed_lots",
                        message=f"BaT page {label} returned raw items but parsed zero lots.",
                        url=f"{BASE_URL}/{url_path}/",
                        metadata_json={"raw_item_count": len(items), "skip_counts": skip_counts},
                    )

                dup_s = f", {dup_count} dups" if dup_count else ""
                skip_s = f" — skipped: {skip_counts}" if skip_counts else ""
                level = "warning" if new_count == 0 and len(items) > 0 else "progress"
                await self._emit(level,
                    f"[{i}/{len(urls)}] {label}: {len(items)} raw → "
                    f"{new_count} auctions{dup_s}{skip_s} (total: {len(all_lots)})")

                if i < len(urls):
                    await asyncio.sleep(polite_delay_seconds(1.5, 4.0))

        return all_lots
