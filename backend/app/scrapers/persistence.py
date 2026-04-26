"""Auction lot persistence helpers for scrapers."""

import uuid
from inspect import isawaitable

from sqlalchemy import delete, or_, select

from app.models.auction_image import AuctionImage
from app.models.auction_lot import AuctionLot
from app.scrapers.types import ScrapedAuctionLot


class ScraperPersistenceMixin:
    """Database insert/update helpers used by all scrapers."""

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

        preserve_existing_detail = (
            scraped.detail_scraped_at is None and existing.detail_scraped_at is not None
        )
        preserve_when_missing = {
            "bid_count",
            "vin",
            "mileage",
            "exterior_color",
            "interior_color",
            "transmission",
            "drivetrain",
            "engine",
            "body_style",
            "location",
            "seller",
            "vehicle_details",
            "detail_payload",
            "detail_html",
            "detail_scraped_at",
        }
        for key, value in self._lot_values(scraped).items():
            if preserve_existing_detail and key in preserve_when_missing:
                if value is None or value == {}:
                    continue
                if key == "vehicle_details":
                    value = {**(existing.vehicle_details or {}), **value}
            setattr(existing, key, value)
        if not preserve_existing_detail:
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
        count_records: bool = True,
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
                    f"({records_inserted} new)...",
                    {
                        "saved": index,
                        "total": records_found,
                        "inserted": records_inserted,
                        "updated": self.records_updated,
                    },
                )

        if count_records:
            self.records_found += records_found
            self.records_inserted += records_inserted
            self.auction_ids_discovered.extend(
                lot.source_auction_id for lot in lots if lot.source_auction_id
            )
            self.auction_urls_discovered.extend(lot.canonical_url for lot in lots)
            self.ended_dates_discovered.extend(lot.ended_at for lot in lots if lot.ended_at)
        self.persisted_lot_keys.update(self._lot_key(lot) for lot in lots)
        if self.current_scrape_run is not None:
            self.current_scrape_run.records_found = self.records_found
            self.current_scrape_run.records_inserted = self.records_inserted
            self.current_scrape_run.records_updated = self.records_updated
            self.current_scrape_run.metadata_json = {
                **(self.current_scrape_run.metadata_json or {}),
                "anomaly_count": self.anomaly_count,
            }
        await self.update_crawl_state(self._crawl_state_snapshot("running", context=context))
        await self.session.commit()
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
