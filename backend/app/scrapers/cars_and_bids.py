"""Cars & Bids scraper orchestration."""

from __future__ import annotations

import asyncio
import time

from app.scrapers.base import BaseScraper
from app.scrapers.cars_and_bids_browser import CarsAndBidsBrowserMixin
from app.scrapers.cars_and_bids_config import _cab_search_delay_seconds
from app.scrapers.cars_and_bids_parser import SOURCE
from app.scrapers.cars_and_bids_processing import CarsAndBidsProcessingMixin
from app.scrapers.cars_and_bids_targets import (
    get_all_url_keys,
    get_url_entries,
    select_entries,
)
from app.scrapers.types import ScrapedAuctionLot

__all__ = [
    "CarsAndBidsScraper",
    "get_all_url_keys",
    "get_url_entries",
]


class CarsAndBidsScraper(CarsAndBidsBrowserMixin, CarsAndBidsProcessingMixin, BaseScraper):
    source = SOURCE

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._selected_keys: set[str] | None = kwargs.pop("selected_keys", None)
        self._cancel_event: asyncio.Event | None = kwargs.pop("cancel_event", None)
        super().__init__(*args, **kwargs)

    def _is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def _get_entries(self) -> list[tuple[str, str, str]]:
        return select_entries(self._selected_keys)

    async def scrape(self) -> list[ScrapedAuctionLot]:
        entries = self._get_entries()
        if not entries:
            await self._emit("warning", "No C&B search terms selected - nothing to scrape.")
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
                f"[{i}/{len(entries)}] Searching: {label}...",
                {"label": label, "key": key, "term_index": i, "total_terms": len(entries)},
            )

            search_started = time.perf_counter()
            raw_items = await self._fetch_raw_items_with_retries(
                query=query,
                label=label,
                key=key,
                index=i,
                total_entries=len(entries),
            )
            if raw_items is None:
                continue

            new_count, dup_count, skip_counts, term_lots = self._parse_raw_items(
                raw_items,
                seen_urls=seen_urls,
                all_lots=all_lots,
            )
            await self._record_search_result(
                label=label,
                key=key,
                raw_items=raw_items,
                new_count=new_count,
                dup_count=dup_count,
                skip_counts=skip_counts,
                search_started=search_started,
            )

            dup_s = f", {dup_count} dups" if dup_count else ""
            skip_s = f" - skipped: {skip_counts}" if skip_counts else ""
            level = "warning" if new_count == 0 and raw_items else "progress"
            await self._emit(
                level,
                f"[{i}/{len(entries)}] {label}: {len(raw_items)} raw -> "
                f"{new_count} lots{dup_s}{skip_s} (total: {len(all_lots)})",
            )
            if self.current_run_id is not None:
                await self.persist_lots(term_lots, context=label)

            if i < len(entries):
                await asyncio.sleep(_cab_search_delay_seconds())

        return all_lots
