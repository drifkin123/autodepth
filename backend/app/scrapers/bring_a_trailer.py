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
    extract_completed_metadata_from_html,
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
LISTINGS_FILTER_URL = f"{BASE_URL}/wp-json/bringatrailer/1.0/data/listings-filter"

_HEADERS = BROWSER_HEADERS
_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=30.0)
_INCREMENTAL_COMPLETED_PAGE_LIMIT = 5


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
    items, _metadata = await fetch_page_result(client, url_path)
    return items


async def fetch_page_result(client: httpx.AsyncClient, url_path: str) -> tuple[list[dict], dict]:
    """Fetch one BaT model page and return raw items plus pagination telemetry."""
    url = f"{BASE_URL}/{url_path}/"
    resp = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return extract_items_from_html(resp.text), extract_completed_metadata_from_html(resp.text)


def build_completed_results_params(
    base_filter: dict,
    *,
    page: int,
    per_page: int,
) -> list[tuple[str, object]]:
    params: list[tuple[str, object]] = [
        ("page", page),
        ("per_page", per_page),
        ("get_items", 1),
        ("get_stats", 0),
        ("sort", "td"),
    ]
    for key, value in base_filter.items():
        if value is None:
            continue
        params.append((f"base_filter[{key}]", value))
    return params


async def fetch_completed_results_page(
    client: httpx.AsyncClient,
    *,
    base_filter: dict,
    page: int,
    per_page: int,
    referer_url: str,
) -> tuple[list[dict], dict]:
    resp = await client.get(
        LISTINGS_FILTER_URL,
        params=build_completed_results_params(base_filter, page=page, per_page=per_page),
        headers={**_HEADERS, "Referer": referer_url},
        follow_redirects=True,
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", []), {
        "items_total": data.get("items_total"),
        "items_per_page": data.get("items_per_page"),
        "page_current": data.get("page_current"),
        "pages_total": data.get("pages_total"),
    }


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

    def _completed_page_limit(self, pages_total: int) -> int:
        if self.mode == "backfill":
            return pages_total
        return min(pages_total, _INCREMENTAL_COMPLETED_PAGE_LIMIT)

    def _parse_page_items(
        self,
        items: list[dict],
        *,
        seen_urls: set[str],
        all_lots: list[ScrapedAuctionLot],
    ) -> tuple[int, int, dict]:
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
        return new_count, dup_count, skip_counts

    async def _fetch_page_with_retries(
        self,
        client: httpx.AsyncClient,
        *,
        label: str,
        url_path: str,
        page: int = 1,
        base_filter: dict | None = None,
        per_page: int | None = None,
    ) -> tuple[list[dict], dict] | None:
        url = f"{BASE_URL}/{url_path}/"
        for attempt in range(1, _RETRY_POLICY.max_attempts + 1):
            started = time.perf_counter()
            try:
                if page == 1:
                    return await fetch_page_result(client, url_path)
                return await fetch_completed_results_page(
                    client,
                    base_filter=base_filter or {},
                    page=page,
                    per_page=per_page or 24,
                    referer_url=url,
                )
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
                        metadata_json={"target": label, "page": page},
                    )
                    await self.record_anomaly(
                        severity="critical",
                        code="blocked_response",
                        message=f"BaT blocked or rate-limited request for {label}.",
                        url=url,
                        metadata_json={
                            "status_code": status_code,
                            "attempt": attempt,
                            "page": page,
                        },
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
                        metadata_json={"target": label, "page": page},
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
                    metadata_json={"target": label, "page": page},
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
                        metadata_json={"target": label, "page": page},
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
                    metadata_json={"target": label, "page": page},
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
                    result = await self._fetch_page_with_retries(
                        client, label=label, url_path=url_path
                    )
                except BlockedScrapeError as exc:
                    await self._emit("error", f"[{i}/{len(urls)}] {label}: blocked — {exc}")
                    break
                if result is None:
                    await self._emit("error", f"[{i}/{len(urls)}] {label}: request failed")
                    continue
                items, page_metadata = result

                new_count, dup_count, skip_counts = self._parse_page_items(
                    items,
                    seen_urls=seen_urls,
                    all_lots=all_lots,
                )
                pages_total = int(page_metadata.get("pages_total") or 1)
                items_total = page_metadata.get("items_total")
                items_per_page = int(page_metadata.get("items_per_page") or len(items) or 24)
                base_filter = page_metadata.get("base_filter") or {}
                page_limit = self._completed_page_limit(pages_total)

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
                    metadata_json={
                        "label": label,
                        "key": key,
                        "duplicates": dup_count,
                        **page_metadata,
                        "page_limit": page_limit,
                        "pagination_complete": page_limit >= pages_total,
                    },
                )
                if pages_total > 1 and page_limit < pages_total:
                    await self.record_anomaly(
                        severity="warning",
                        code="bat_pagination_incomplete",
                        message=(
                            f"BaT page {label} exposes {pages_total} completed-result "
                            f"pages; {self.mode} mode will parse {page_limit} pages."
                        ),
                        url=f"{BASE_URL}/{url_path}/",
                        metadata_json={
                            "items_total": items_total,
                            "pages_total": pages_total,
                            "page_current": page_metadata.get("page_current"),
                            "parsed_first_page": new_count,
                            "page_limit": page_limit,
                            "mode": self.mode,
                        },
                    )
                if pages_total > 1 and not base_filter:
                    await self.record_anomaly(
                        severity="critical",
                        code="bat_pagination_missing_filter",
                        message=f"BaT page {label} has more pages but no base_filter metadata.",
                        url=f"{BASE_URL}/{url_path}/",
                        metadata_json={"pages_total": pages_total},
                    )
                if len(items) > 0 and new_count == 0:
                    await self.record_anomaly(
                        severity="warning",
                        code="zero_parsed_lots",
                        message=f"BaT page {label} returned raw items but parsed zero lots.",
                        url=f"{BASE_URL}/{url_path}/",
                        metadata_json={"raw_item_count": len(items), "skip_counts": skip_counts},
                    )

                total_s = f" of {items_total} total" if items_total else ""
                page_s = f", page 1/{pages_total}" if pages_total else ""
                dup_s = f", {dup_count} dups" if dup_count else ""
                skip_s = f" — skipped: {skip_counts}" if skip_counts else ""
                level = "warning" if new_count == 0 and len(items) > 0 else "progress"
                await self._emit(level,
                    f"[{i}/{len(urls)}] {label}: {len(items)} raw → "
                    f"{new_count} auctions{total_s}{page_s}{dup_s}{skip_s} "
                    f"(run total: {len(all_lots)})")

                for page_number in range(2, page_limit + 1):
                    if self._is_cancelled():
                        await self._emit(
                            "warning",
                            f"Scrape cancelled during {label} page {page_number}/{page_limit}.",
                        )
                        break
                    if not base_filter:
                        break
                    await asyncio.sleep(polite_delay_seconds(1.5, 4.0))
                    try:
                        started = time.perf_counter()
                        page_result = await self._fetch_page_with_retries(
                            client,
                            label=label,
                            url_path=url_path,
                            page=page_number,
                            base_filter=base_filter,
                            per_page=items_per_page,
                        )
                    except BlockedScrapeError as exc:
                        await self._emit(
                            "error",
                            f"[{i}/{len(urls)}] {label} page {page_number}: blocked — {exc}",
                        )
                        raise
                    if page_result is None:
                        await self._emit(
                            "error",
                            f"[{i}/{len(urls)}] {label} page {page_number}: request failed",
                        )
                        continue

                    page_items, page_result_metadata = page_result
                    page_new_count, page_dup_count, page_skip_counts = self._parse_page_items(
                        page_items,
                        seen_urls=seen_urls,
                        all_lots=all_lots,
                    )
                    await self.record_request_log(
                        url=LISTINGS_FILTER_URL,
                        action="completed_results_page",
                        attempt=1,
                        status_code=200,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        outcome="success",
                        raw_item_count=len(page_items),
                        parsed_lot_count=page_new_count,
                        skip_counts=page_skip_counts,
                        metadata_json={
                            "label": label,
                            "key": key,
                            "duplicates": page_dup_count,
                            **page_result_metadata,
                            "pagination_complete": page_number >= pages_total,
                        },
                    )
                    page_dup_s = f", {page_dup_count} dups" if page_dup_count else ""
                    page_skip_s = f" — skipped: {page_skip_counts}" if page_skip_counts else ""
                    await self._emit(
                        "progress",
                        f"[{i}/{len(urls)}] {label}: page {page_number}/{pages_total} "
                        f"{len(page_items)} raw → {page_new_count} auctions"
                        f"{page_dup_s}{page_skip_s} (run total: {len(all_lots)})",
                    )

                if i < len(urls):
                    await asyncio.sleep(polite_delay_seconds(1.5, 4.0))

        return all_lots
