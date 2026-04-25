"""Shared interface and utilities for all vehicle scrapers."""

import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from inspect import isawaitable
from typing import TYPE_CHECKING

from rapidfuzz import fuzz, process
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction_image import AuctionImage
from app.models.car import Car
from app.models.listing_snapshot import ListingSnapshot
from app.models.scrape_log import ScrapeLog
from app.models.vehicle_sale import VehicleSale

if TYPE_CHECKING:
    from app.broadcast import ScrapeBroadcaster


@dataclass
class ScrapedListing:
    """Raw data extracted by a scraper before DB matching."""

    source: str
    source_url: str
    sale_type: str          # "auction" | "listing" | "dealer" | "private"
    raw_title: str          # e.g. "2019 Porsche 911 GT3 RS"
    year: int
    asking_price: int       # listed/opening price
    sold_price: int | None  # confirmed final price; None for active listings
    is_sold: bool
    listed_at: datetime
    # Optional extracted metadata
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    vin: str | None = None
    transmission: str | None = None
    no_reserve: bool | None = None
    body_style: str | None = None
    fuel_type: str | None = None
    location: str | None = None
    stock_type: str | None = None
    # Existing optional fields
    sold_at: datetime | None = None
    mileage: int | None = None
    color: str | None = None
    condition_notes: str | None = None
    options: dict = field(default_factory=dict)
    raw_data: dict = field(default_factory=dict)
    source_auction_id: str | None = None
    auction_status: str = "unknown"
    high_bid: int | None = None
    bid_count: int | None = None
    title: str | None = None
    subtitle: str | None = None
    detail_scraped_at: datetime | None = None
    image_urls: list[str] = field(default_factory=list)
    vehicle_details: dict = field(default_factory=dict)


class BaseScraper(ABC):
    """All scrapers implement this interface."""

    source: str  # must be set by subclass

    def __init__(
        self,
        session: AsyncSession,
        broadcaster: "ScrapeBroadcaster | None" = None,
    ) -> None:
        self.session = session
        self.broadcaster = broadcaster
        self._car_cache: list[Car] | None = None

    async def _emit(
        self, event_type: str, message: str, data: dict | None = None
    ) -> None:
        """Publish a scrape event if a broadcaster is attached."""
        if self.broadcaster is None:
            return
        from app.broadcast import ScrapeEvent
        await self.broadcaster.publish(
            ScrapeEvent(type=event_type, source=self.source, message=message, data=data or {})
        )

    async def _load_cars(self) -> list[Car]:
        if self._car_cache is None:
            result = await self.session.execute(select(Car))
            self._car_cache = list(result.scalars().all())
        return self._car_cache

    async def match_car(self, raw_title: str) -> Car | None:
        """Fuzzy-match a raw listing title to a Car in the catalog."""
        cars = await self._load_cars()
        if not cars:
            return None

        # Build a search string per car: "Make Model Trim"
        candidates = {f"{c.make} {c.model} {c.trim}": c for c in cars}

        # Normalize: collapse whitespace, strip punctuation noise
        normalized = re.sub(r"[^\w\s]", " ", raw_title).strip()

        match = process.extractOne(
            normalized,
            candidates.keys(),
            scorer=fuzz.token_set_ratio,
            score_cutoff=60,
        )
        if match is None:
            return None

        matched_key, score, _ = match
        return candidates[matched_key]

    async def deduplicate(self, source_url: str) -> bool:
        """Return True if this source_url already exists in the DB."""
        result = await self.session.execute(
            select(VehicleSale.id).where(VehicleSale.source_url == source_url)
        )
        return result.scalar_one_or_none() is not None

    def _build_vehicle_sale(self, listing: ScrapedListing, car: Car | None) -> VehicleSale:
        """Construct a VehicleSale from a scraped listing and optional catalog match."""
        return VehicleSale(
            id=uuid.uuid4(),
            car_id=car.id if car else None,
            make=listing.make or (car.make if car else None),
            model=listing.model or (car.model if car else None),
            trim=listing.trim or (car.trim if car else None),
            source=listing.source,
            source_url=listing.source_url,
            sale_type=listing.sale_type,
            year=listing.year,
            mileage=listing.mileage,
            color=listing.color,
            asking_price=listing.asking_price,
            sold_price=listing.sold_price,
            is_sold=listing.is_sold,
            listed_at=listing.listed_at,
            sold_at=listing.sold_at,
            condition_notes=listing.condition_notes,
            options=listing.options,
            raw_data=listing.raw_data,
            vin=listing.vin,
            transmission=listing.transmission,
            no_reserve=listing.no_reserve,
            body_style=listing.body_style,
            fuel_type=listing.fuel_type,
            location=listing.location,
            stock_type=listing.stock_type,
            source_auction_id=listing.source_auction_id,
            auction_status=listing.auction_status,
            high_bid=listing.high_bid,
            bid_count=listing.bid_count,
            title=listing.title or listing.raw_title,
            subtitle=listing.subtitle,
            detail_scraped_at=listing.detail_scraped_at,
            image_count=len(listing.image_urls),
            vehicle_details=listing.vehicle_details,
        )

    def _build_auction_images(
        self, sale: VehicleSale, listing: ScrapedListing
    ) -> list[AuctionImage]:
        """Construct image URL records for a scraped auction."""
        unique_urls = list(dict.fromkeys(url for url in listing.image_urls if url))
        return [
            AuctionImage(
                vehicle_sale_id=sale.id,
                source=listing.source,
                source_url=listing.source_url,
                image_url=image_url,
                position=index,
            )
            for index, image_url in enumerate(unique_urls)
        ]

    async def _update_existing_auction(self, listing: ScrapedListing) -> None:
        values = {
            "asking_price": listing.asking_price,
            "sold_price": listing.sold_price,
            "is_sold": listing.is_sold,
            "sold_at": listing.sold_at,
            "mileage": listing.mileage,
            "color": listing.color,
            "condition_notes": listing.condition_notes,
            "source_auction_id": listing.source_auction_id,
            "auction_status": listing.auction_status,
            "high_bid": listing.high_bid,
            "bid_count": listing.bid_count,
            "title": listing.title or listing.raw_title,
            "subtitle": listing.subtitle,
            "detail_scraped_at": listing.detail_scraped_at,
            "image_count": len(listing.image_urls),
            "vehicle_details": listing.vehicle_details,
            "raw_data": listing.raw_data,
            "options": listing.options,
        }
        where_clause = VehicleSale.source_url == listing.source_url
        if listing.source_auction_id:
            where_clause = where_clause | (
                (VehicleSale.source == listing.source)
                & (VehicleSale.source_auction_id == listing.source_auction_id)
            )
        id_result = await self.session.execute(
            select(VehicleSale.id).where(where_clause).limit(1)
        )
        maybe_existing_sale_id = id_result.scalar_one_or_none()
        if isawaitable(maybe_existing_sale_id):
            maybe_existing_sale_id = await maybe_existing_sale_id
        existing_sale_id = maybe_existing_sale_id or uuid.uuid4()
        await self.session.execute(update(VehicleSale).where(where_clause).values(**values))
        await self.session.execute(
            delete(AuctionImage).where(AuctionImage.source_url == listing.source_url)
        )
        placeholder_sale = VehicleSale(id=existing_sale_id, listed_at=listing.listed_at)
        for image in self._build_auction_images(placeholder_sale, listing):
            self.session.add(image)

    async def save_listing(self, listing: ScrapedListing) -> bool:
        """Match, deduplicate, and persist a listing. Returns True if inserted."""
        if listing.sale_type == "auction":
            # Closed auction records can be enriched over time: insert new rows,
            # update existing rows, and keep sold_price limited to confirmed sales.
            if await self.deduplicate(listing.source_url):
                await self._update_existing_auction(listing)
                return False
            car = await self.match_car(listing.raw_title)
            sale = self._build_vehicle_sale(listing, car)
            self.session.add(sale)
            for image in self._build_auction_images(sale, listing):
                self.session.add(image)
            return True
        else:
            # Active listing: upsert — update price/mileage/last_seen_at if
            # already known, or insert fresh. Always record a snapshot.
            car = await self.match_car(listing.raw_title)
            scraped_at = datetime.now(UTC)
            is_duplicate = await self.deduplicate(listing.source_url)

            snapshot = ListingSnapshot(
                source_url=listing.source_url,
                scraped_at=scraped_at,
                asking_price=listing.asking_price,
                mileage=listing.mileage,
            )
            self.session.add(snapshot)

            if is_duplicate:
                await self.session.execute(
                    update(VehicleSale)
                    .where(VehicleSale.source_url == listing.source_url)
                    .values(
                        last_seen_at=scraped_at,
                        asking_price=listing.asking_price,
                        mileage=listing.mileage,
                    )
                )
                return False
            else:
                self.session.add(self._build_vehicle_sale(listing, car))
                return True

    async def run(self) -> tuple[int, int]:
        """
        Execute the scrape. Returns (records_found, records_inserted).
        Logs the run to scrape_logs.
        """
        log = ScrapeLog(source=self.source, started_at=datetime.utcnow())
        self.session.add(log)
        await self.session.flush()

        records_found = 0
        records_inserted = 0
        error: str | None = None

        await self._emit("start", f"Starting scraper: {self.source}")

        try:
            listings = await self.scrape()
            records_found = len(listings)
            await self._emit(
                "progress",
                f"Fetched {records_found} listings — saving to DB…",
                {"records_found": records_found},
            )
            for i, listing in enumerate(listings, 1):
                inserted = await self.save_listing(listing)
                if inserted:
                    records_inserted += 1
                # Emit progress every 25 saves so the dashboard feels alive
                if i % 25 == 0:
                    await self._emit(
                        "progress",
                        f"Saved {i}/{records_found} listings ({records_inserted} new)…",
                        {"saved": i, "total": records_found, "inserted": records_inserted},
                    )
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            error = str(exc)
            await self._emit("error", f"Scraper failed: {exc}", {"error": error})
            raise
        finally:
            log.finished_at = datetime.utcnow()
            log.records_found = records_found
            log.records_inserted = records_inserted
            log.error = error
            await self.session.merge(log)
            await self.session.commit()

        await self._emit(
            "complete",
            f"Done: {records_found} found, {records_inserted} new records inserted.",
            {"records_found": records_found, "records_inserted": records_inserted},
        )
        return records_found, records_inserted

    @abstractmethod
    async def scrape(self) -> list[ScrapedListing]:
        """Scrape the source and return raw listings. Must be implemented by each scraper."""
        ...
