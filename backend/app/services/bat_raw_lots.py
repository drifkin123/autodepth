"""Lot persistence/provenance helpers for BaT raw parsing."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction_lot import AuctionLot
from app.models.raw_page_lot import RawPageLot
from app.scrapers.persistence import ScraperPersistenceMixin
from app.scrapers.types import ScrapedAuctionLot


class RawLotPersistence(ScraperPersistenceMixin):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records_updated = 0


async def link_raw_page_to_lot(
    session: AsyncSession,
    *,
    raw_page_id: uuid.UUID,
    lot_id: uuid.UUID,
    relationship_type: str,
) -> None:
    existing = (
        await session.execute(
            select(RawPageLot).where(
                RawPageLot.raw_page_id == raw_page_id,
                RawPageLot.auction_lot_id == lot_id,
                RawPageLot.relationship_type == relationship_type,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            RawPageLot(
                raw_page_id=raw_page_id,
                auction_lot_id=lot_id,
                relationship_type=relationship_type,
            )
        )


def scraped_lot_from_auction_lot(lot: AuctionLot) -> ScrapedAuctionLot:
    return ScrapedAuctionLot(
        source=lot.source,
        source_auction_id=lot.source_auction_id,
        canonical_url=lot.canonical_url,
        auction_status=lot.auction_status,
        sold_price=lot.sold_price,
        high_bid=lot.high_bid,
        bid_count=lot.bid_count,
        currency=lot.currency,
        listed_at=lot.listed_at,
        ended_at=lot.ended_at,
        year=lot.year,
        make=lot.make,
        model=lot.model,
        trim=lot.trim,
        vin=lot.vin,
        mileage=lot.mileage,
        exterior_color=lot.exterior_color,
        interior_color=lot.interior_color,
        transmission=lot.transmission,
        drivetrain=lot.drivetrain,
        engine=lot.engine,
        body_style=lot.body_style,
        location=lot.location,
        seller=lot.seller,
        title=lot.title,
        subtitle=lot.subtitle,
        raw_summary=lot.raw_summary,
        vehicle_details=lot.vehicle_details or {},
        list_payload=lot.list_payload or {},
        detail_payload=lot.detail_payload or {},
        detail_html=lot.detail_html,
        detail_scraped_at=lot.detail_scraped_at,
        image_urls=[image.image_url for image in lot.images],
    )
