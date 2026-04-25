"""Shared interface and persistence utilities for auction scrapers."""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from inspect import isawaitable
from typing import TYPE_CHECKING

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction_image import AuctionImage
from app.models.auction_lot import AuctionLot
from app.models.scrape_run import ScrapeRun

if TYPE_CHECKING:
    from app.broadcast import ScrapeBroadcaster


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
        self.records_updated = 0

    async def _emit(
        self, event_type: str, message: str, data: dict | None = None
    ) -> None:
        if self.broadcaster is None:
            return
        from app.broadcast import ScrapeEvent

        await self.broadcaster.publish(
            ScrapeEvent(type=event_type, source=self.source, message=message, data=data or {})
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

        records_found = 0
        records_inserted = 0
        error: str | None = None
        self.records_updated = 0

        await self._emit("start", f"Starting scraper: {self.source}")
        try:
            lots = await self.scrape()
            records_found = len(lots)
            await self._emit(
                "progress",
                f"Fetched {records_found} auction lots — saving to DB…",
                {"records_found": records_found},
            )
            for index, lot in enumerate(lots, 1):
                if await self.save_lot(lot):
                    records_inserted += 1
                if index % 25 == 0:
                    await self._emit(
                        "progress",
                        f"Saved {index}/{records_found} lots ({records_inserted} new)…",
                        {
                            "saved": index,
                            "total": records_found,
                            "inserted": records_inserted,
                            "updated": self.records_updated,
                        },
                    )
            scrape_run.status = "success"
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            error = str(exc)
            scrape_run.status = "error"
            await self._emit("error", f"Scraper failed: {exc}", {"error": error})
            raise
        finally:
            scrape_run.finished_at = datetime.now(UTC)
            scrape_run.records_found = records_found
            scrape_run.records_inserted = records_inserted
            scrape_run.records_updated = self.records_updated
            scrape_run.error = error
            await self.session.merge(scrape_run)
            await self.session.commit()

        await self._emit(
            "complete",
            f"Done: {records_found} found, {records_inserted} new, "
            f"{self.records_updated} updated.",
            {
                "records_found": records_found,
                "records_inserted": records_inserted,
                "records_updated": self.records_updated,
            },
        )
        return records_found, records_inserted

    @abstractmethod
    async def scrape(self) -> list[ScrapedAuctionLot]:
        """Scrape the source and return auction lots."""
        ...
