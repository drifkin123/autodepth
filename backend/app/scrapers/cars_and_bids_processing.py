"""Cars & Bids search retry, parse, and telemetry helpers."""

import asyncio
import time

from app.scrapers.cars_and_bids_config import _PAST_AUCTIONS_URL, _RETRY_POLICY
from app.scrapers.cars_and_bids_parser import parse_auction
from app.scrapers.runtime import BlockedScrapeError
from app.scrapers.types import ScrapedAuctionLot


class CarsAndBidsProcessingMixin:
    """Search processing helpers for C&B closed auction results."""

    async def _fetch_raw_items_with_retries(
        self,
        *,
        query: str,
        label: str,
        key: str,
        index: int,
        total_entries: int,
    ) -> list[dict] | None:
        search_started = time.perf_counter()
        for attempt in range(1, _RETRY_POLICY.max_attempts + 1):
            try:
                return await self._fetch_search_results(query)
            except BlockedScrapeError as exc:
                await self.record_request_log(
                    url=_PAST_AUCTIONS_URL,
                    action="closed_auction_search",
                    attempt=attempt,
                    status_code=exc.status_code,
                    duration_ms=int((time.perf_counter() - search_started) * 1000),
                    outcome="blocked",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    metadata_json={"label": label, "key": key},
                )
                await self.record_anomaly(
                    severity="critical",
                    code="blocked_response",
                    message="Cars & Bids search stopped after a blocked response.",
                    url=_PAST_AUCTIONS_URL,
                    metadata_json={
                        "label": label,
                        "key": key,
                        "status_code": exc.status_code,
                    },
                )
                await self._emit(
                    "error",
                    f"[{index}/{total_entries}] {label}: blocked - {exc}",
                )
                return None
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
                await self._emit(
                    "error",
                    f"[{index}/{total_entries}] {label}: error - {exc}",
                )
        return None

    def _parse_raw_items(
        self,
        raw_items: list[dict],
        *,
        seen_urls: set[str],
        all_lots: list[ScrapedAuctionLot],
    ) -> tuple[int, int, dict, list[ScrapedAuctionLot]]:
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
        return new_count, dup_count, skip_counts, term_lots

    async def _record_search_result(
        self,
        *,
        label: str,
        key: str,
        raw_items: list[dict],
        new_count: int,
        dup_count: int,
        skip_counts: dict,
        search_started: float,
    ) -> None:
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
