"""Bring a Trailer scraper orchestration."""

import asyncio
import time

import httpx

from app.scrapers.base import BaseScraper
from app.scrapers.bat_config import (
    _INCREMENTAL_COMPLETED_PAGE_LIMIT,
    _target_delay_seconds,
)
from app.scrapers.bat_http import (
    build_completed_results_params,
    fetch_completed_results_page,
    fetch_detail_html,
    fetch_page_result,
)
from app.scrapers.bat_list_fields import parse_integer_value
from app.scrapers.bat_list_parser import SOURCE
from app.scrapers.bat_model_loading import BringATrailerModelLoadingMixin
from app.scrapers.bat_page_processing import BringATrailerPageProcessingMixin
from app.scrapers.bat_requests import BringATrailerRequestMixin
from app.scrapers.bat_targets import (
    extract_model_entries_from_html,
    get_all_url_keys,
    get_url_entries,
)
from app.scrapers.makes import BAT_MAKES
from app.scrapers.runtime import BlockedScrapeError
from app.scrapers.types import ScrapedAuctionLot

__all__ = [
    "BringATrailerScraper",
    "build_completed_results_params",
    "extract_model_entries_from_html",
    "fetch_completed_results_page",
    "fetch_detail_html",
    "fetch_page_result",
    "get_all_url_keys",
    "get_url_entries",
]


class BringATrailerScraper(
    BringATrailerRequestMixin,
    BringATrailerModelLoadingMixin,
    BringATrailerPageProcessingMixin,
    BaseScraper,
):
    source = SOURCE
    warn_missing_detail_enrichment = True

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

    async def scrape(self) -> list[ScrapedAuctionLot]:
        all_lots: list[ScrapedAuctionLot] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient() as client:
            urls = await self._load_urls(client)
            if not urls:
                await self._emit("warning", "No BaT URLs selected - nothing to scrape.")
                return []

            await self._emit(
                "progress",
                f"Starting BaT scrape: {len(urls)} car pages selected",
                {"total_urls": len(urls), "selected_keys": [k for k, _, _ in urls]},
            )

            for i, (key, label, url_path) in enumerate(urls, 1):
                if self._is_cancelled():
                    await self._emit(
                        "warning",
                        f"Scrape cancelled after {i - 1}/{len(urls)} pages.",
                    )
                    break

                await self._emit(
                    "progress",
                    f"[{i}/{len(urls)}] Fetching: {label}...",
                    {"label": label, "key": key, "term_index": i, "total_terms": len(urls)},
                )

                try:
                    started = time.perf_counter()
                    result = await self._fetch_page_with_retries(
                        client,
                        label=label,
                        url_path=url_path,
                    )
                except BlockedScrapeError as exc:
                    await self._emit("error", f"[{i}/{len(urls)}] {label}: blocked - {exc}")
                    break
                if result is None:
                    await self._emit("error", f"[{i}/{len(urls)}] {label}: request failed")
                    continue

                items, page_metadata = result
                new_count, dup_count, skip_counts, page_lots = self._parse_page_items(
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
                    index=i,
                    total_urls=len(urls),
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
                        index=i,
                        total_urls=len(urls),
                    )
                    if not should_continue:
                        break

                if i < len(urls):
                    await asyncio.sleep(_target_delay_seconds())

        return all_lots
