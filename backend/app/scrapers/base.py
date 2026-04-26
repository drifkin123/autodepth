"""Shared scraper interface and run lifecycle."""

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scrape_run import ScrapeRun
from app.scrapers.observability import ScraperObservabilityMixin
from app.scrapers.persistence import ScraperPersistenceMixin
from app.scrapers.types import ScrapedAuctionLot

if TYPE_CHECKING:
    from app.broadcast import ScrapeBroadcaster


class BaseScraper(ScraperObservabilityMixin, ScraperPersistenceMixin, ABC):
    """All source scrapers implement this interface."""

    source: str
    warn_missing_detail_enrichment = False

    def __init__(
        self,
        session: AsyncSession,
        broadcaster: "ScrapeBroadcaster | None" = None,
        *,
        mode: str = "incremental",
    ) -> None:
        self.session = session
        self.broadcaster = broadcaster
        self.mode = mode
        self.records_found = 0
        self.records_inserted = 0
        self.records_updated = 0
        self.current_run_id: uuid.UUID | None = None
        self.anomaly_count = 0
        self.request_log_count = 0
        self.auction_ids_discovered: list[str] = []
        self.auction_urls_discovered: list[str] = []
        self.ended_dates_discovered: list[datetime] = []
        self.persisted_lot_keys: set[str] = set()
        self.current_scrape_run: ScrapeRun | None = None

    async def run(self) -> tuple[int, int]:
        """Execute the scrape. Returns (records_found, records_inserted)."""
        scrape_run = ScrapeRun(
            source=self.source,
            mode=self.mode,
            status="running",
            started_at=datetime.now(UTC),
        )
        self.session.add(scrape_run)
        await self.session.flush()
        self.current_run_id = scrape_run.id
        self.current_scrape_run = scrape_run
        await self.session.commit()
        await self.prune_old_request_logs()
        await self.session.commit()

        error: str | None = None
        self.records_found = 0
        self.records_inserted = 0
        self.records_updated = 0
        self.anomaly_count = 0
        self.request_log_count = 0
        self.auction_ids_discovered = []
        self.auction_urls_discovered = []
        self.ended_dates_discovered = []
        self.persisted_lot_keys = set()

        await self._emit("start", f"Starting scraper: {self.source}")
        try:
            lots = await self.scrape()
            pending_lots = [
                lot for lot in lots if self._lot_key(lot) not in self.persisted_lot_keys
            ]
            if pending_lots:
                await self._emit(
                    "progress",
                    f"Fetched {len(pending_lots)} auction lots - saving to DB...",
                    {"records_found": len(pending_lots)},
                )
                await self.persist_lots(pending_lots, context="auction lots")
            if self.records_found == 0:
                await self.record_anomaly(
                    severity="warning",
                    code="zero_lots",
                    message=f"{self.source} returned zero auction lots.",
                    metadata_json={"mode": self.mode},
                )
            await self._record_missing_detail_enrichment_anomaly()
            final_status = "cancelled" if self._is_cancel_requested() else "success"
            await self.update_crawl_state(self._crawl_state_snapshot(final_status))
            scrape_run.status = final_status
            scrape_run.metadata_json = {
                **(scrape_run.metadata_json or {}),
                "anomaly_count": self.anomaly_count,
            }
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            error = str(exc)
            if self.current_run_id is not None:
                refreshed_run = await self.session.get(ScrapeRun, self.current_run_id)
                if refreshed_run is not None:
                    scrape_run = refreshed_run
                    self.current_scrape_run = refreshed_run
            scrape_run.status = "error"
            await self.update_crawl_state(self._crawl_state_snapshot("error"))
            await self._emit("error", f"Scraper failed: {exc}", {"error": error})
            raise
        finally:
            scrape_run.finished_at = datetime.now(UTC)
            scrape_run.records_found = self.records_found
            scrape_run.records_inserted = self.records_inserted
            scrape_run.records_updated = self.records_updated
            scrape_run.error = error
            scrape_run.metadata_json = {
                **(scrape_run.__dict__.get("metadata_json") or {}),
                "anomaly_count": self.anomaly_count,
            }
            await self.session.merge(scrape_run)
            await self.session.commit()
            self.current_run_id = None
            self.current_scrape_run = None

        await self._emit(
            "complete",
            f"Done: {self.records_found} found, {self.records_inserted} new, "
            f"{self.records_updated} updated.",
            {
                "records_found": self.records_found,
                "records_inserted": self.records_inserted,
                "records_updated": self.records_updated,
            },
        )
        return self.records_found, self.records_inserted

    @abstractmethod
    async def scrape(self) -> list[ScrapedAuctionLot]:
        """Scrape the source and return auction lots."""
        ...
