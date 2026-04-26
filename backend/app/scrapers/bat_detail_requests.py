"""Bring a Trailer detail-page request and enrichment workflow."""

import asyncio
import time
from datetime import UTC, datetime, timedelta

import httpx

from app.scrapers.bat_config import _RETRY_POLICY, _detail_page_delay_seconds
from app.scrapers.bat_detail_parser import enrich_lot_from_detail_html
from app.scrapers.bat_detail_retry import BringATrailerDetailRetryMixin
from app.scrapers.bat_http import fetch_detail_html
from app.scrapers.types import ScrapedAuctionLot
from app.settings import settings


class BringATrailerDetailRequestMixin(BringATrailerDetailRetryMixin):
    """Retry helpers for BaT detail pages."""

    async def _should_skip_detail_refresh(self, lot: ScrapedAuctionLot) -> bool:
        if not settings.bat_skip_enriched_details:
            return False
        existing = await self._existing_lot(lot)
        if existing is None or existing.detail_scraped_at is None:
            return False
        detail_scraped_at = existing.detail_scraped_at
        if detail_scraped_at.tzinfo is None:
            detail_scraped_at = detail_scraped_at.replace(tzinfo=UTC)
        refresh_cutoff = datetime.now(UTC) - timedelta(
            days=settings.bat_detail_refresh_after_days
        )
        return detail_scraped_at >= refresh_cutoff

    async def _fetch_detail_with_retries(
        self,
        client: httpx.AsyncClient,
        *,
        lot: ScrapedAuctionLot,
        label: str,
        page: int,
    ) -> str | None:
        for attempt in range(1, _RETRY_POLICY.max_attempts + 1):
            started = time.perf_counter()
            try:
                html = await fetch_detail_html(client, lot.canonical_url)
                await self.record_request_log(
                    url=lot.canonical_url,
                    action="detail_page",
                    attempt=attempt,
                    status_code=200,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    outcome="success",
                    raw_item_count=1,
                    parsed_lot_count=1,
                    metadata_json={
                        "target": label,
                        "page": page,
                        "source_auction_id": lot.source_auction_id,
                    },
                )
                return html
            except httpx.HTTPStatusError as exc:
                if await self._handle_detail_http_error(
                    exc,
                    lot=lot,
                    label=label,
                    page=page,
                    attempt=attempt,
                    started=started,
                ):
                    continue
                return None
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if await self._record_retryable_detail_error(
                    exc,
                    lot=lot,
                    label=label,
                    page=page,
                    attempt=attempt,
                    started=started,
                ):
                    continue
                return None
        return None

    async def _enrich_lots_with_details(
        self,
        client: httpx.AsyncClient,
        lots: list[ScrapedAuctionLot],
        *,
        label: str,
        page: int,
    ) -> list[ScrapedAuctionLot]:
        enriched_lots: list[ScrapedAuctionLot] = []
        for index, lot in enumerate(lots, 1):
            if self._is_cancelled():
                break
            if await self._should_skip_detail_refresh(lot):
                await self.record_request_log(
                    url=lot.canonical_url,
                    action="detail_page",
                    attempt=1,
                    outcome="skipped",
                    raw_item_count=1,
                    parsed_lot_count=0,
                    metadata_json={
                        "target": label,
                        "page": page,
                        "source_auction_id": lot.source_auction_id,
                        "reason": "recent_detail_scrape",
                    },
                )
                continue
            if index > 1:
                await asyncio.sleep(_detail_page_delay_seconds())
            html = await self._fetch_detail_with_retries(client, lot=lot, label=label, page=page)
            if html is None:
                continue
            enriched_lots.append(enrich_lot_from_detail_html(lot, html))
        return enriched_lots
