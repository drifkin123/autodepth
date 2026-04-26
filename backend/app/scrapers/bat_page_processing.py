"""Bring a Trailer page parsing and persistence helpers."""

import asyncio
import time

from app.scrapers.bat_config import LISTINGS_FILTER_URL, _list_page_delay_seconds
from app.scrapers.bat_list_parser import parse_item
from app.scrapers.bat_page_telemetry import BringATrailerPageTelemetryMixin
from app.scrapers.runtime import BlockedScrapeError
from app.scrapers.types import ScrapedAuctionLot


class BringATrailerPageProcessingMixin(BringATrailerPageTelemetryMixin):
    """Helpers for processing BaT completed-result pages."""

    def _parse_page_items(
        self,
        items: list[dict],
        *,
        seen_urls: set[str],
        all_lots: list[ScrapedAuctionLot],
    ) -> tuple[int, int, dict, list[ScrapedAuctionLot]]:
        new_count, dup_count, skip_counts = 0, 0, {}
        page_lots: list[ScrapedAuctionLot] = []
        for item in items:
            listing, reason = parse_item(item)
            if listing is None:
                skip_counts[reason] = skip_counts.get(reason, 0) + 1
            elif listing.canonical_url in seen_urls:
                dup_count += 1
            else:
                seen_urls.add(listing.canonical_url)
                all_lots.append(listing)
                page_lots.append(listing)
                new_count += 1
        return new_count, dup_count, skip_counts, page_lots

    async def _persist_page_and_details(
        self,
        client,
        page_lots: list[ScrapedAuctionLot],
        *,
        label: str,
        page_number: int,
    ) -> None:
        if self.current_run_id is None:
            return
        await self.persist_lots(page_lots, context=f"{label} page {page_number}")
        enriched_lots = await self._enrich_lots_with_details(
            client,
            page_lots,
            label=label,
            page=page_number,
        )
        await self.persist_lots(
            enriched_lots,
            context=f"{label} page {page_number} details",
            count_records=False,
        )

    async def _process_completed_results_page(
        self,
        client,
        *,
        key: str,
        label: str,
        url_path: str,
        page_number: int,
        page_limit: int,
        pages_total: int,
        base_filter: dict,
        items_per_page: int,
        seen_urls: set[str],
        all_lots: list[ScrapedAuctionLot],
        index: int,
        total_urls: int,
    ) -> bool:
        if self._is_cancelled():
            await self._emit(
                "warning",
                f"Scrape cancelled during {label} page {page_number}/{page_limit}.",
            )
            return False
        if not base_filter:
            return False
        await asyncio.sleep(_list_page_delay_seconds())
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
                f"[{index}/{total_urls}] {label} page {page_number}: blocked - {exc}",
            )
            raise
        if page_result is None:
            await self._emit(
                "error",
                f"[{index}/{total_urls}] {label} page {page_number}: request failed",
            )
            return True

        page_items, page_result_metadata = page_result
        page_new_count, page_dup_count, page_skip_counts, page_lots = self._parse_page_items(
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
        await self._emit_page_summary(
            label=label,
            index=index,
            total_urls=total_urls,
            page_number=page_number,
            pages_total=pages_total,
            raw_count=len(page_items),
            new_count=page_new_count,
            dup_count=page_dup_count,
            skip_counts=page_skip_counts,
            run_total=len(all_lots),
        )
        await self._persist_page_and_details(
            client,
            page_lots,
            label=label,
            page_number=page_number,
        )
        return True
