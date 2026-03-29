"""Shared interface and utilities for all vehicle scrapers."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.car import Car
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
    sold_at: datetime | None = None
    mileage: int | None = None
    color: str | None = None
    condition_notes: str | None = None
    options: dict = field(default_factory=dict)
    raw_data: dict = field(default_factory=dict)


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

    async def save_listing(self, listing: ScrapedListing) -> bool:
        """Match, deduplicate, and persist a listing. Returns True if inserted."""
        if await self.deduplicate(listing.source_url):
            return False

        car = await self.match_car(listing.raw_title)
        if car is None:
            return False

        sale = VehicleSale(
            car_id=car.id,
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
        )
        self.session.add(sale)
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
