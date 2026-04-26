"""Cars & Bids Playwright navigation helpers."""

import time
from typing import Any

from app.scrapers.cars_and_bids_config import _PAST_AUCTIONS_URL
from app.scrapers.runtime import BlockedScrapeError, is_block_status
from app.settings import settings


class CarsAndBidsNavigationMixin:
    """Navigation and pagination helpers for C&B closed auctions."""

    async def _navigate_to_past_auctions(self, page: Any, browser: Any) -> None:
        started = time.perf_counter()
        goto_response = await page.goto(
            _PAST_AUCTIONS_URL,
            wait_until="networkidle",
            timeout=60_000,
        )
        goto_status = goto_response.status if goto_response is not None else 200
        if is_block_status(goto_status):
            await self.record_request_log(
                url=_PAST_AUCTIONS_URL,
                action="playwright_goto",
                attempt=1,
                status_code=goto_status,
                duration_ms=int((time.perf_counter() - started) * 1000),
                outcome="blocked",
                error_type="BlockedResponse",
                error_message=f"Source returned {goto_status}",
            )
            await self.record_anomaly(
                severity="critical",
                code="blocked_response",
                message="Cars & Bids blocked or rate-limited page navigation.",
                url=_PAST_AUCTIONS_URL,
                metadata_json={"status_code": goto_status},
            )
            await browser.close()
            raise BlockedScrapeError(
                f"Cars & Bids returned {goto_status}",
                status_code=goto_status,
            )
        await self.record_request_log(
            url=_PAST_AUCTIONS_URL,
            action="playwright_goto",
            attempt=1,
            status_code=goto_status,
            duration_ms=int((time.perf_counter() - started) * 1000),
            outcome="success",
        )

    async def _paginate_closed_auction_results(
        self,
        page: Any,
        browser: Any,
        captured: list[dict],
        all_auctions: list[dict],
        blocked_error: BlockedScrapeError | None,
    ) -> BlockedScrapeError | None:
        seen_response_count = len(captured)
        while True:
            prev = len(captured)
            next_btn = await page.query_selector(
                '[aria-label="Next"], .next, button.pagination-next, '
                '.page-next, [class*="next-page"], li.next > a'
            )
            if not next_btn:
                await self.record_request_log(
                    url=_PAST_AUCTIONS_URL,
                    action="pagination_next",
                    attempt=1,
                    outcome="selector_missing",
                    metadata_json={"captured_responses": len(captured)},
                )
                break
            await next_btn.click()
            for _ in range(25):
                await page.wait_for_timeout(200)
                if len(captured) > prev:
                    break
            if settings.cab_stop_on_block and blocked_error is not None:
                await browser.close()
                raise blocked_error
            if len(captured) > prev:
                auctions = captured[-1].get("auctions", [])
                if not auctions:
                    break
                all_auctions.extend(auctions)
                seen_response_count = len(captured)
            elif len(captured) == seen_response_count:
                break
        return blocked_error
