"""Cars & Bids scraper — confirmed auction sales via intercepted JSON API.

Cars & Bids uses a signed JSON API whose signature is computed client-side in the
browser. We use Playwright to render the past-auctions search page, intercept the
authenticated API responses, and extract structured auction data — no HTML parsing.

The scraper navigates to the past-auctions page, captures closed-auction API
responses, and paginates by clicking "Next" until no more results are available.

Sold and reserve-not-met auctions are ingested. Only confirmed sold auctions
populate ``sold_price``; reserve-not-met lots preserve ``high_bid``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.scrapers.base import BaseScraper, ScrapedAuctionLot
from app.scrapers.cars_and_bids_parser import SOURCE, parse_auction
from app.scrapers.runtime import BROWSER_HEADERS, RetryPolicy, is_block_status, polite_delay_seconds

logger = logging.getLogger(__name__)

_BASE_URL = "https://carsandbids.com"
_PAST_AUCTIONS_URL = f"{_BASE_URL}/past-auctions/"
_USER_AGENT = BROWSER_HEADERS["User-Agent"]
_RETRY_POLICY = RetryPolicy(max_attempts=2, base_delay_seconds=3.0, max_delay_seconds=20.0)

GLOBAL_CAB_ENTRY: tuple[str, str, str] = ("all", "All closed auctions", "")


def get_all_url_keys() -> list[str]:
    return [GLOBAL_CAB_ENTRY[0]]


def get_url_entries() -> list[dict[str, str]]:
    key, label, query = GLOBAL_CAB_ENTRY
    return [{"key": key, "label": label, "query": query}]


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
            return [GLOBAL_CAB_ENTRY]
        if "all" in self._selected_keys:
            return [GLOBAL_CAB_ENTRY]
        return []

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
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                extra_http_headers={
                    key: value for key, value in BROWSER_HEADERS.items() if key != "User-Agent"
                },
                locale="en-US",
            )
            page = await context.new_page()

            async def on_response(response: Any) -> None:
                url = response.url
                if "/v2/autos/auctions" in url and "status=closed" in url:
                    started = time.perf_counter()
                    if is_block_status(response.status):
                        await self.record_request_log(
                            url=url,
                            action="api_response",
                            attempt=1,
                            status_code=response.status,
                            duration_ms=int((time.perf_counter() - started) * 1000),
                            outcome="blocked",
                            error_type="BlockedResponse",
                            error_message=f"Source returned {response.status}",
                        )
                        await self.record_anomaly(
                            severity="critical",
                            code="blocked_response",
                            message="Cars & Bids blocked or rate-limited an API response.",
                            url=url,
                            metadata_json={"status_code": response.status},
                        )
                        return
                    try:
                        payload = await response.json()
                        captured.append(payload)
                        await self.record_request_log(
                            url=url,
                            action="api_response",
                            attempt=1,
                            status_code=response.status,
                            duration_ms=int((time.perf_counter() - started) * 1000),
                            outcome="success",
                            raw_item_count=len(payload.get("auctions", [])),
                            metadata_json={
                                "count": payload.get("count"),
                                "total": payload.get("total"),
                            },
                        )
                    except Exception as exc:
                        await self.record_request_log(
                            url=url,
                            action="api_response",
                            attempt=1,
                            status_code=response.status,
                            duration_ms=int((time.perf_counter() - started) * 1000),
                            outcome="error",
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )

            page.on("response", on_response)
            started = time.perf_counter()
            await page.goto(_PAST_AUCTIONS_URL, wait_until="networkidle", timeout=60_000)
            await self.record_request_log(
                url=_PAST_AUCTIONS_URL,
                action="playwright_goto",
                attempt=1,
                status_code=200,
                duration_ms=int((time.perf_counter() - started) * 1000),
                outcome="success",
            )
            await page.wait_for_timeout(2_000)

            if search_query:
                inp = await page.query_selector("input.form-control, input[type=search]")
                if not inp:
                    logger.warning("C&B: search input not found — UI may have changed")
                    await browser.close()
                    return []

                await inp.click()
                await inp.fill(search_query)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(int(polite_delay_seconds(4.0, 7.0) * 1000))

            if captured:
                all_auctions.extend(captured[-1].get("auctions", []))

            seen_response_count = len(captured)
            while True:
                prev = len(captured)
                next_btn = await page.query_selector(
                    '[aria-label="Next"], .next, button.pagination-next, '
                    '.page-next, [class*="next-page"], li.next > a'
                )
                if not next_btn:
                    await self.record_request_log(
                        url=_PAST_AUCTIONS_URL,
                        action="pagination_next",
                        attempt=1,
                        outcome="selector_missing",
                        metadata_json={"captured_responses": len(captured)},
                    )
                    break
                await next_btn.click()
                for _ in range(25):  # up to 5s wait
                    await page.wait_for_timeout(200)
                    if len(captured) > prev:
                        break
                if len(captured) > prev:
                    auctions = captured[-1].get("auctions", [])
                    if not auctions:
                        break
                    all_auctions.extend(auctions)
                    seen_response_count = len(captured)
                elif len(captured) == seen_response_count:
                    break

            await browser.close()

        return all_auctions

    async def scrape(self) -> list[ScrapedAuctionLot]:
        entries = self._get_entries()
        if not entries:
            await self._emit("warning", "No C&B search terms selected — nothing to scrape.")
            return []

        all_lots: list[ScrapedAuctionLot] = []
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

            raw_items: list[dict] | None = None
            search_started = time.perf_counter()
            for attempt in range(1, _RETRY_POLICY.max_attempts + 1):
                try:
                    raw_items = await self._fetch_search_results(query)
                    break
                except Exception as exc:
                    if attempt < _RETRY_POLICY.max_attempts:
                        delay = _RETRY_POLICY.delay_for_attempt(attempt)
                        await self.record_request_log(
                            url=_PAST_AUCTIONS_URL,
                            action="closed_auction_search",
                            attempt=attempt,
                            duration_ms=int((time.perf_counter() - search_started) * 1000),
                            outcome="retry",
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                            retry_delay_seconds=delay,
                            metadata_json={"label": label, "key": key},
                        )
                        await asyncio.sleep(delay)
                        continue
                    await self.record_request_log(
                        url=_PAST_AUCTIONS_URL,
                        action="closed_auction_search",
                        attempt=attempt,
                        duration_ms=int((time.perf_counter() - search_started) * 1000),
                        outcome="error",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        metadata_json={"label": label, "key": key},
                    )
                    await self._emit("error", f"[{i}/{len(entries)}] {label}: error — {exc}")
            if raw_items is None:
                continue

            new_count, dup_count, skip_counts = 0, 0, {}
            term_lots: list[ScrapedAuctionLot] = []
            for item in raw_items:
                listing, reason = parse_auction(item)
                if listing is None:
                    skip_counts[reason] = skip_counts.get(reason, 0) + 1
                elif listing.canonical_url in seen_urls:
                    dup_count += 1
                else:
                    seen_urls.add(listing.canonical_url)
                    all_lots.append(listing)
                    term_lots.append(listing)
                    new_count += 1

            await self.record_request_log(
                url=_PAST_AUCTIONS_URL,
                action="closed_auction_search",
                attempt=1,
                duration_ms=int((time.perf_counter() - search_started) * 1000),
                outcome="success",
                raw_item_count=len(raw_items),
                parsed_lot_count=new_count,
                skip_counts=skip_counts,
                metadata_json={"label": label, "key": key, "duplicates": dup_count},
            )
            if not raw_items:
                await self.record_anomaly(
                    severity="critical",
                    code="no_closed_auction_response",
                    message="Cars & Bids returned no closed-auction API results.",
                    url=_PAST_AUCTIONS_URL,
                    metadata_json={"label": label, "key": key},
                )
            elif new_count == 0:
                await self.record_anomaly(
                    severity="warning",
                    code="zero_parsed_lots",
                    message="Cars & Bids returned raw auctions but parsed zero lots.",
                    url=_PAST_AUCTIONS_URL,
                    metadata_json={"raw_item_count": len(raw_items), "skip_counts": skip_counts},
                )

            dup_s = f", {dup_count} dups" if dup_count else ""
            skip_s = f" — skipped: {skip_counts}" if skip_counts else ""
            level = "warning" if new_count == 0 and raw_items else "progress"
            await self._emit(
                level,
                f"[{i}/{len(entries)}] {label}: {len(raw_items)} raw → "
                f"{new_count} lots{dup_s}{skip_s} (total: {len(all_lots)})",
            )
            if self.current_run_id is not None:
                await self.persist_lots(term_lots, context=label)

            if i < len(entries):
                await asyncio.sleep(polite_delay_seconds(2.0, 5.0))

        return all_lots
