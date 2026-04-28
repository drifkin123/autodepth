"""Bring a Trailer target-level crawl workflow."""

import time

from app.scrapers.bat_list_fields import parse_integer_value
from app.scrapers.runtime import BlockedScrapeError
from app.scrapers.types import ScrapedAuctionLot

BatTarget = tuple[str, str, str]


class BringATrailerTargetProcessingMixin:
    """Process a single BaT make/model target."""

    async def _process_target(
        self,
        client,
        *,
        target: BatTarget,
        index: int,
        total_urls: int,
        seen_urls: set[str],
        all_lots: list[ScrapedAuctionLot],
    ) -> None:
        key, label, url_path = target
        await self._emit(
            "progress",
            f"[{index}/{total_urls}] Fetching: {label}...",
            {"label": label, "key": key, "term_index": index, "total_terms": total_urls},
        )

        try:
            started = time.perf_counter()
            result = await self._fetch_page_with_retries(
                client,
                label=label,
                url_path=url_path,
            )
        except BlockedScrapeError as exc:
            await self._emit("error", f"[{index}/{total_urls}] {label}: blocked - {exc}")
            raise
        if result is None:
            await self._emit("error", f"[{index}/{total_urls}] {label}: request failed")
            return

        items, page_metadata = result
        new_count, dup_count, skip_counts, page_lots = await self._parse_page_items(
            items,
            seen_urls=seen_urls,
            all_lots=all_lots,
        )
        pages_total = parse_integer_value(page_metadata.get("pages_total")) or 1
        items_total = page_metadata.get("items_total")
        items_per_page = (
            parse_integer_value(page_metadata.get("items_per_page")) or len(items) or 24
        )
        base_filter = page_metadata.get("base_filter") or {}
        page_limit = self._completed_page_limit(pages_total)

        await self._record_initial_page_telemetry(
            key=key,
            label=label,
            url_path=url_path,
            started=started,
            items=items,
            new_count=new_count,
            dup_count=dup_count,
            skip_counts=skip_counts,
            page_metadata=page_metadata,
            page_limit=page_limit,
        )
        await self._emit_page_summary(
            label=label,
            index=index,
            total_urls=total_urls,
            page_number=1,
            pages_total=pages_total,
            raw_count=len(items),
            new_count=new_count,
            dup_count=dup_count,
            skip_counts=skip_counts,
            run_total=len(all_lots),
            items_total=items_total,
        )
        await self._persist_page_and_details(
            client,
            page_lots,
            label=label,
            page_number=1,
        )

        for page_number in range(2, page_limit + 1):
            should_continue = await self._process_completed_results_page(
                client,
                key=key,
                label=label,
                url_path=url_path,
                page_number=page_number,
                page_limit=page_limit,
                pages_total=pages_total,
                base_filter=base_filter,
                items_per_page=items_per_page,
                seen_urls=seen_urls,
                all_lots=all_lots,
                index=index,
                total_urls=total_urls,
            )
            if not should_continue:
                break
