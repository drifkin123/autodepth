"""Bring a Trailer detail request retry/error helpers."""

import asyncio
import time

import httpx

from app.scrapers.bat_config import _RETRY_POLICY
from app.scrapers.runtime import (
    BlockedScrapeError,
    is_block_status,
    parse_retry_after_seconds,
)
from app.scrapers.types import ScrapedAuctionLot
from app.settings import settings


class BringATrailerDetailRetryMixin:
    """Retry and error-recording helpers for BaT detail pages."""

    async def _handle_detail_http_error(
        self,
        exc: httpx.HTTPStatusError,
        *,
        lot: ScrapedAuctionLot,
        label: str,
        page: int,
        attempt: int,
        started: float,
    ) -> bool:
        status_code = exc.response.status_code if exc.response else None
        duration_ms = int((time.perf_counter() - started) * 1000)
        if is_block_status(status_code):
            retry_after_seconds = parse_retry_after_seconds(
                exc.response.headers.get("Retry-After") if exc.response else None
            )
            await self.record_request_log(
                url=lot.canonical_url,
                action="detail_page",
                attempt=attempt,
                status_code=status_code,
                duration_ms=duration_ms,
                outcome="blocked",
                error_type=type(exc).__name__,
                error_message=str(exc),
                retry_delay_seconds=retry_after_seconds,
                metadata_json={
                    "target": label,
                    "page": page,
                    "source_auction_id": lot.source_auction_id,
                    "retry_after_seconds": retry_after_seconds,
                },
            )
            await self.record_anomaly(
                severity="critical",
                code="blocked_response",
                message=f"BaT blocked or rate-limited detail page for {label}.",
                url=lot.canonical_url,
                metadata_json={
                    "status_code": status_code,
                    "attempt": attempt,
                    "retry_after_seconds": retry_after_seconds,
                },
            )
            if retry_after_seconds is not None:
                await asyncio.sleep(retry_after_seconds)
            if settings.bat_stop_on_block:
                raise BlockedScrapeError(str(exc), status_code=status_code) from exc
            return False
        if status_code is not None and status_code >= 500 and attempt < _RETRY_POLICY.max_attempts:
            delay = _RETRY_POLICY.delay_for_attempt(attempt)
            await self.record_request_log(
                url=lot.canonical_url,
                action="detail_page",
                attempt=attempt,
                status_code=status_code,
                duration_ms=duration_ms,
                outcome="retry",
                error_type=type(exc).__name__,
                error_message=str(exc),
                retry_delay_seconds=delay,
                metadata_json={
                    "target": label,
                    "page": page,
                    "source_auction_id": lot.source_auction_id,
                },
            )
            await asyncio.sleep(delay)
            return True
        await self.record_request_log(
            url=lot.canonical_url,
            action="detail_page",
            attempt=attempt,
            status_code=status_code,
            duration_ms=duration_ms,
            outcome="error",
            error_type=type(exc).__name__,
            error_message=str(exc),
            metadata_json={
                "target": label,
                "page": page,
                "source_auction_id": lot.source_auction_id,
            },
        )
        return False

    async def _record_retryable_detail_error(
        self,
        exc: httpx.TimeoutException | httpx.TransportError,
        *,
        lot: ScrapedAuctionLot,
        label: str,
        page: int,
        attempt: int,
        started: float,
    ) -> bool:
        duration_ms = int((time.perf_counter() - started) * 1000)
        if attempt < _RETRY_POLICY.max_attempts:
            delay = _RETRY_POLICY.delay_for_attempt(attempt)
            await self.record_request_log(
                url=lot.canonical_url,
                action="detail_page",
                attempt=attempt,
                duration_ms=duration_ms,
                outcome="retry",
                error_type=type(exc).__name__,
                error_message=str(exc),
                retry_delay_seconds=delay,
                metadata_json={
                    "target": label,
                    "page": page,
                    "source_auction_id": lot.source_auction_id,
                },
            )
            await asyncio.sleep(delay)
            return True
        await self.record_request_log(
            url=lot.canonical_url,
            action="detail_page",
            attempt=attempt,
            duration_ms=duration_ms,
            outcome="error",
            error_type=type(exc).__name__,
            error_message=str(exc),
            metadata_json={
                "target": label,
                "page": page,
                "source_auction_id": lot.source_auction_id,
            },
        )
        return False
