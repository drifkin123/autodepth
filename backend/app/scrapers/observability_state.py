"""Scraper crawl-state helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from inspect import isawaitable

from sqlalchemy import select

from app.models.crawl_state import CrawlState


class ScraperCrawlStateMixin:
    """Crawl-state persistence helpers used by all scrapers."""

    async def update_crawl_state(self, state_update: dict) -> None:
        result = await self.session.execute(
            select(CrawlState).where(
                (CrawlState.source == self.source) & (CrawlState.mode == self.mode)
            )
        )
        existing = result.scalar_one_or_none()
        if isawaitable(existing):
            existing = await existing
        now = datetime.now(UTC)
        if existing is None:
            self.session.add(
                CrawlState(
                    source=self.source,
                    mode=self.mode,
                    state=state_update,
                    last_run_at=now,
                    updated_at=now,
                )
            )
            return
        existing.state = {**(existing.state or {}), **state_update}
        existing.last_run_at = now

    def _crawl_state_snapshot(self, status: str, *, context: str | None = None) -> dict:
        now = datetime.now(UTC)
        state = {
            "last_status": status,
            "last_progress_at": now.isoformat(),
            "records_found": self.records_found,
            "records_inserted": self.records_inserted,
            "records_updated": self.records_updated,
            "request_count": self.request_log_count,
            "anomaly_count": self.anomaly_count,
            "auction_ids_discovered": self.auction_ids_discovered[:5000],
            "auction_urls_discovered": self.auction_urls_discovered[:5000],
            "oldest_ended_at": (
                min(self.ended_dates_discovered).isoformat()
                if self.ended_dates_discovered
                else None
            ),
            "newest_ended_at": (
                max(self.ended_dates_discovered).isoformat()
                if self.ended_dates_discovered
                else None
            ),
        }
        if context:
            state["last_context"] = context
        if status == "success":
            state["last_success_at"] = now.isoformat()
        elif status == "cancelled":
            state["last_cancelled_at"] = now.isoformat()
        elif status == "error":
            state["last_error_at"] = now.isoformat()
        return state
