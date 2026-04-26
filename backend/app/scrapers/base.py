"""Shared interface and persistence utilities for auction scrapers."""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from inspect import isawaitable
from typing import TYPE_CHECKING

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction_image import AuctionImage
from app.models.auction_lot import AuctionLot
from app.models.crawl_state import CrawlState
from app.models.scrape_anomaly import ScrapeAnomaly
from app.models.scrape_request_log import ScrapeRequestLog
from app.models.scrape_run import ScrapeRun
from app.settings import settings

if TYPE_CHECKING:
    from app.broadcast import ScrapeBroadcaster

logger = logging.getLogger(__name__)


@dataclass
class ScrapedAuctionLot:
    """Raw and extracted auction data before persistence."""

    source: str
    source_auction_id: str | None
    canonical_url: str
    auction_status: str
    sold_price: int | None
    high_bid: int | None
    bid_count: int | None
    currency: str = "USD"
    listed_at: datetime | None = None
    ended_at: datetime | None = None
    year: int | None = None
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    vin: str | None = None
    mileage: int | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    transmission: str | None = None
    drivetrain: str | None = None
    engine: str | None = None
    body_style: str | None = None
    location: str | None = None
    seller: str | None = None
    title: str | None = None
    subtitle: str | None = None
    raw_summary: str | None = None
    vehicle_details: dict = field(default_factory=dict)
    list_payload: dict = field(default_factory=dict)
    detail_payload: dict = field(default_factory=dict)
    detail_html: str | None = None
    detail_scraped_at: datetime | None = None
    image_urls: list[str] = field(default_factory=list)


class BaseScraper(ABC):
    """All source scrapers implement this interface."""

    source: str

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
        self.ended_dates_discovered: list[datetime] = []
        self.persisted_lot_keys: set[str] = set()

    async def _emit(
        self, event_type: str, message: str, data: dict | None = None
    ) -> None:
        if self.broadcaster is None:
            return
        from app.broadcast import ScrapeEvent

        await self.broadcaster.publish(
            ScrapeEvent(type=event_type, source=self.source, message=message, data=data or {})
        )

    async def record_request_log(
        self,
        *,
        url: str,
        action: str,
        attempt: int,
        status_code: int | None = None,
        duration_ms: int | None = None,
        outcome: str,
        error_type: str | None = None,
        error_message: str | None = None,
        retry_delay_seconds: float | None = None,
        raw_item_count: int | None = None,
        parsed_lot_count: int | None = None,
        skip_counts: dict | None = None,
        metadata_json: dict | None = None,
    ) -> None:
        self.request_log_count += 1
        self.session.add(
            ScrapeRequestLog(
                scrape_run_id=self.current_run_id,
                source=self.source,
                url=url,
                action=action,
                attempt=attempt,
                status_code=status_code,
                duration_ms=duration_ms,
                outcome=outcome,
                error_type=error_type,
                error_message=error_message,
                retry_delay_seconds=retry_delay_seconds,
                raw_item_count=raw_item_count,
                parsed_lot_count=parsed_lot_count,
                skip_counts=skip_counts or {},
                metadata_json=metadata_json or {},
            )
        )
        await self.session.commit()
        logger.info(
            "scrape_request source=%s action=%s outcome=%s status=%s attempt=%s "
            "duration_ms=%s raw_items=%s parsed_lots=%s skips=%s metadata=%s url=%s",
            self.source,
            action,
            outcome,
            status_code,
            attempt,
            duration_ms,
            raw_item_count,
            parsed_lot_count,
            skip_counts or {},
            metadata_json or {},
            url,
        )

    async def record_anomaly(
        self,
        *,
        severity: str,
        code: str,
        message: str,
        url: str | None = None,
        metadata_json: dict | None = None,
    ) -> None:
        self.anomaly_count += 1
        self.session.add(
            ScrapeAnomaly(
                scrape_run_id=self.current_run_id,
                source=self.source,
                severity=severity,
                code=code,
                message=message,
                url=url,
                metadata_json=metadata_json or {},
            )
        )
        await self.session.commit()
        log_method = logger.error if severity == "critical" else logger.warning
        log_method(
            "scrape_anomaly source=%s severity=%s code=%s message=%s metadata=%s url=%s",
            self.source,
            severity,
            code,
            message,
            metadata_json or {},
            url,
        )
        await self._emit(
            "warning" if severity != "critical" else "error",
            message,
            {"severity": severity, "code": code, "url": url, **(metadata_json or {})},
        )

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

    async def prune_old_request_logs(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=settings.request_log_retention_days)
        await self.session.execute(
            delete(ScrapeRequestLog).where(ScrapeRequestLog.created_at < cutoff)
        )

    def _lot_values(self, scraped: ScrapedAuctionLot) -> dict:
        return {
            "source": scraped.source,
            "source_auction_id": scraped.source_auction_id,
            "canonical_url": scraped.canonical_url,
            "auction_status": scraped.auction_status,
            "sold_price": scraped.sold_price,
            "high_bid": scraped.high_bid,
            "bid_count": scraped.bid_count,
            "currency": scraped.currency,
            "listed_at": scraped.listed_at,
            "ended_at": scraped.ended_at,
            "year": scraped.year,
            "make": scraped.make,
            "model": scraped.model,
            "trim": scraped.trim,
            "vin": scraped.vin,
            "mileage": scraped.mileage,
            "exterior_color": scraped.exterior_color,
            "interior_color": scraped.interior_color,
            "transmission": scraped.transmission,
            "drivetrain": scraped.drivetrain,
            "engine": scraped.engine,
            "body_style": scraped.body_style,
            "location": scraped.location,
            "seller": scraped.seller,
            "title": scraped.title,
            "subtitle": scraped.subtitle,
            "raw_summary": scraped.raw_summary,
            "vehicle_details": scraped.vehicle_details,
            "list_payload": scraped.list_payload,
            "detail_payload": scraped.detail_payload,
            "detail_html": scraped.detail_html,
            "detail_scraped_at": scraped.detail_scraped_at,
        }

    def _build_lot(self, scraped: ScrapedAuctionLot) -> AuctionLot:
        return AuctionLot(id=uuid.uuid4(), **self._lot_values(scraped))

    def _build_images(self, lot_id: uuid.UUID, scraped: ScrapedAuctionLot) -> list[AuctionImage]:
        unique_urls = list(dict.fromkeys(url for url in scraped.image_urls if url))
        return [
            AuctionImage(
                auction_lot_id=lot_id,
                source=scraped.source,
                image_url=image_url,
                position=index,
                source_payload={"image_url": image_url},
            )
            for index, image_url in enumerate(unique_urls)
        ]

    async def _existing_lot(self, scraped: ScrapedAuctionLot) -> AuctionLot | None:
        predicates = [
            (AuctionLot.source == scraped.source)
            & (AuctionLot.canonical_url == scraped.canonical_url)
        ]
        if scraped.source_auction_id:
            predicates.insert(
                0,
                (AuctionLot.source == scraped.source)
                & (AuctionLot.source_auction_id == scraped.source_auction_id),
            )
        result = await self.session.execute(select(AuctionLot).where(or_(*predicates)).limit(1))
        existing = result.scalar_one_or_none()
        if isawaitable(existing):
            existing = await existing
        return existing

    async def save_lot(self, scraped: ScrapedAuctionLot) -> bool:
        """Insert or update an auction lot. Returns True for a newly inserted lot."""
        existing = await self._existing_lot(scraped)
        if existing is None:
            lot = self._build_lot(scraped)
            self.session.add(lot)
            await self.session.flush()
            for image in self._build_images(lot.id, scraped):
                self.session.add(image)
            return True

        for key, value in self._lot_values(scraped).items():
            setattr(existing, key, value)
        await self.session.execute(
            delete(AuctionImage).where(AuctionImage.auction_lot_id == existing.id)
        )
        for image in self._build_images(existing.id, scraped):
            self.session.add(image)
        self.records_updated += 1
        return False

    def _lot_key(self, scraped: ScrapedAuctionLot) -> str:
        if scraped.source_auction_id:
            return f"{scraped.source}:id:{scraped.source_auction_id}"
        return f"{scraped.source}:url:{scraped.canonical_url}"

    async def persist_lots(
        self,
        lots: list[ScrapedAuctionLot],
        *,
        context: str = "auction lots",
    ) -> tuple[int, int]:
        """Persist a page/batch immediately and update run counters."""
        if not lots:
            return 0, 0

        records_inserted = 0
        records_found = len(lots)
        for index, lot in enumerate(lots, 1):
            if await self.save_lot(lot):
                records_inserted += 1
            if index % 25 == 0:
                await self._emit(
                    "progress",
                    f"Saved {index}/{records_found} {context} "
                    f"({records_inserted} new)…",
                    {
                        "saved": index,
                        "total": records_found,
                        "inserted": records_inserted,
                        "updated": self.records_updated,
                    },
                )

        await self.session.commit()
        self.records_found += records_found
        self.records_inserted += records_inserted
        self.auction_ids_discovered.extend(
            lot.source_auction_id for lot in lots if lot.source_auction_id
        )
        self.ended_dates_discovered.extend(lot.ended_at for lot in lots if lot.ended_at)
        self.persisted_lot_keys.update(self._lot_key(lot) for lot in lots)
        await self._emit(
            "progress",
            f"Persisted {records_found} {context} "
            f"({records_inserted} new, {self.records_updated} updated).",
            {
                "records_found": self.records_found,
                "records_inserted": self.records_inserted,
                "records_updated": self.records_updated,
            },
        )
        return records_found, records_inserted

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
                    f"Fetched {len(pending_lots)} auction lots — saving to DB…",
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
            await self.update_crawl_state(
                {
                    "last_success_at": datetime.now(UTC).isoformat(),
                    "records_found": self.records_found,
                    "records_inserted": self.records_inserted,
                    "records_updated": self.records_updated,
                    "request_count": self.request_log_count,
                    "anomaly_count": self.anomaly_count,
                    "auction_ids_discovered": self.auction_ids_discovered[:5000],
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
            )
            scrape_run.status = "success"
            scrape_run.metadata_json = {
                **(scrape_run.metadata_json or {}),
                "anomaly_count": self.anomaly_count,
            }
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            error = str(exc)
            scrape_run.status = "error"
            await self._emit("error", f"Scraper failed: {exc}", {"error": error})
            raise
        finally:
            scrape_run.finished_at = datetime.now(UTC)
            scrape_run.records_found = self.records_found
            scrape_run.records_inserted = self.records_inserted
            scrape_run.records_updated = self.records_updated
            scrape_run.error = error
            scrape_run.metadata_json = {
                **(scrape_run.metadata_json or {}),
                "anomaly_count": self.anomaly_count,
            }
            await self.session.merge(scrape_run)
            await self.session.commit()
            self.current_run_id = None

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
