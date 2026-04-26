"""Cars & Bids Playwright navigation and API interception."""

import logging
import time
from typing import Any

from app.scrapers.cars_and_bids_config import (
    _USER_AGENT,
    _cab_interaction_delay_seconds,
)
from app.scrapers.cars_and_bids_navigation import CarsAndBidsNavigationMixin
from app.scrapers.runtime import (
    BROWSER_HEADERS,
    BlockedScrapeError,
    is_block_status,
    parse_retry_after_seconds,
)
from app.settings import settings

logger = logging.getLogger(__name__)


class CarsAndBidsBrowserMixin(CarsAndBidsNavigationMixin):
    """Playwright browser/API interception workflow for C&B."""

    async def _record_blocked_api_response(
        self,
        response: Any,
        *,
        url: str,
        duration_ms: int,
    ) -> BlockedScrapeError:
        retry_after_seconds = parse_retry_after_seconds(
            response.headers.get("retry-after") if hasattr(response, "headers") else None
        )
        await self.record_request_log(
            url=url,
            action="api_response",
            attempt=1,
            status_code=response.status,
            duration_ms=duration_ms,
            outcome="blocked",
            error_type="BlockedResponse",
            error_message=f"Source returned {response.status}",
            retry_delay_seconds=retry_after_seconds,
            metadata_json={"retry_after_seconds": retry_after_seconds},
        )
        await self.record_anomaly(
            severity="critical",
            code="blocked_response",
            message="Cars & Bids blocked or rate-limited an API response.",
            url=url,
            metadata_json={
                "status_code": response.status,
                "retry_after_seconds": retry_after_seconds,
            },
        )
        return BlockedScrapeError(
            f"Cars & Bids returned {response.status}",
            status_code=response.status,
        )

    async def _handle_closed_auction_response(
        self,
        response: Any,
        captured: list[dict],
    ) -> BlockedScrapeError | None:
        url = response.url
        if "/v2/autos/auctions" not in url or "status=closed" not in url:
            return None
        started = time.perf_counter()
        if is_block_status(response.status):
            return await self._record_blocked_api_response(
                response,
                url=url,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
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
        return None

    async def _fetch_search_results(self, search_query: str) -> list[dict]:
        from playwright.async_api import async_playwright  # type: ignore[import]

        all_auctions: list[dict] = []
        captured: list[dict] = []
        blocked_error: BlockedScrapeError | None = None

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
                nonlocal blocked_error
                maybe_blocked = await self._handle_closed_auction_response(response, captured)
                if maybe_blocked is not None:
                    blocked_error = maybe_blocked

            page.on("response", on_response)
            await self._navigate_to_past_auctions(page, browser)
            await page.wait_for_timeout(2_000)
            if settings.cab_stop_on_block and blocked_error is not None:
                await browser.close()
                raise blocked_error

            if search_query:
                inp = await page.query_selector("input.form-control, input[type=search]")
                if not inp:
                    logger.warning("C&B: search input not found - UI may have changed")
                    await browser.close()
                    return []
                await inp.click()
                await inp.fill(search_query)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(int(_cab_interaction_delay_seconds() * 1000))
                if settings.cab_stop_on_block and blocked_error is not None:
                    await browser.close()
                    raise blocked_error

            if captured:
                all_auctions.extend(captured[-1].get("auctions", []))

            await self._paginate_closed_auction_results(
                page,
                browser,
                captured,
                all_auctions,
                blocked_error,
            )
            await browser.close()

        return all_auctions
