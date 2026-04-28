"""Bring a Trailer scraper orchestration."""

import asyncio

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
from app.scrapers.bat_list_parser import SOURCE
from app.scrapers.bat_model_loading import BringATrailerModelLoadingMixin
from app.scrapers.bat_page_processing import BringATrailerPageProcessingMixin
from app.scrapers.bat_requests import BringATrailerRequestMixin
from app.scrapers.bat_target_processing import BringATrailerTargetProcessingMixin
from app.scrapers.bat_targets import (
    extract_model_entries_from_html,
    get_all_url_keys,
    get_url_entries,
)
from app.scrapers.makes import BAT_MAKES
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
    BringATrailerTargetProcessingMixin,
    BringATrailerPageProcessingMixin,
    BaseScraper,
):
    source = SOURCE
    warn_missing_detail_enrichment = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._selected_keys: set[str] | None = kwargs.pop("selected_keys", None)
        self._cancel_event: asyncio.Event | None = kwargs.pop("cancel_event", None)
        self._skip_details: bool = kwargs.pop("skip_details", False)
        self._list_rate_limiter = kwargs.pop("list_rate_limiter", None)
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

            for i, target in enumerate(urls, 1):
                if self._is_cancelled():
                    await self._emit(
                        "warning",
                        f"Scrape cancelled after {i - 1}/{len(urls)} pages.",
                    )
                    break

                await self._process_target(
                    client,
                    target=target,
                    index=i,
                    total_urls=len(urls),
                    seen_urls=seen_urls,
                    all_lots=all_lots,
                )

                if i < len(urls):
                    await asyncio.sleep(_target_delay_seconds())

        return all_lots
