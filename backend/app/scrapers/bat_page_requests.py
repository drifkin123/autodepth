"""Bring a Trailer completed-page request retry workflow."""

import asyncio
import time

import httpx

from app.scrapers.bat_config import _RETRY_POLICY, BASE_URL
from app.scrapers.bat_http import fetch_completed_results_page, fetch_page_result
from app.scrapers.runtime import (
    BlockedScrapeError,
    is_block_status,
    parse_retry_after_seconds,
)
from app.settings import settings


class BringATrailerPageRequestMixin:
    """Retry helpers for BaT model/completed-results pages."""

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
                result = await self._handle_page_http_error(
                    exc,
                    url=url,
                    label=label,
                    page=page,
                    attempt=attempt,
                    started=started,
                )
                if result == "retry":
                    continue
                return None
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if await self._record_retryable_page_error(
                    exc,
                    url=url,
                    label=label,
                    page=page,
                    attempt=attempt,
                    started=started,
                ):
                    continue
                return None
        return None

    async def _handle_page_http_error(
        self,
        exc: httpx.HTTPStatusError,
        *,
        url: str,
        label: str,
        page: int,
        attempt: int,
        started: float,
    ) -> str | None:
        status_code = exc.response.status_code if exc.response else None
        duration_ms = int((time.perf_counter() - started) * 1000)
        if is_block_status(status_code):
            retry_after_seconds = parse_retry_after_seconds(
                exc.response.headers.get("Retry-After") if exc.response else None
            )
            await self.record_request_log(
                url=url,
                action="http_get",
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
                    "retry_after_seconds": retry_after_seconds,
                },
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
                    "retry_after_seconds": retry_after_seconds,
                },
            )
            if retry_after_seconds is not None:
                await asyncio.sleep(retry_after_seconds)
            if settings.bat_stop_on_block:
                raise BlockedScrapeError(str(exc), status_code=status_code) from exc
            return None
        if status_code is not None and status_code >= 500 and attempt < _RETRY_POLICY.max_attempts:
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
            return "retry"
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

    async def _record_retryable_page_error(
        self,
        exc: httpx.TimeoutException | httpx.TransportError,
        *,
        url: str,
        label: str,
        page: int,
        attempt: int,
        started: float,
    ) -> bool:
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
            return True
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
        return False
