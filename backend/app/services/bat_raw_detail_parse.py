"""Parse stored BaT detail raw pages."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction_lot import AuctionLot
from app.models.raw_page import RawPage
from app.scrapers.bat_detail_parser import enrich_lot_from_detail_html
from app.services.bat_raw_lots import (
    RawLotPersistence,
    link_raw_page_to_lot,
    scraped_lot_from_auction_lot,
)
from app.services.bat_raw_types import SOURCE, RawParseOutcome


async def parse_detail_page(
    session: AsyncSession,
    raw_page: RawPage,
    html: str,
) -> RawParseOutcome:
    lot = (
        await session.execute(
            select(AuctionLot).where(
                AuctionLot.source == SOURCE,
                AuctionLot.canonical_url.in_(
                    {raw_page.url, raw_page.canonical_url, f"{raw_page.canonical_url}/"}
                ),
            )
        )
    ).scalar_one_or_none()
    if lot is None:
        return RawParseOutcome()

    enriched = enrich_lot_from_detail_html(
        scraped_lot_from_auction_lot(lot),
        html,
        scraped_at=raw_page.fetched_at,
    )
    persistence = RawLotPersistence(session)
    await persistence.save_lot(enriched)
    refreshed_lot = await persistence._existing_lot(enriched)
    if refreshed_lot is not None:
        await link_raw_page_to_lot(
            session,
            raw_page_id=raw_page.id,
            lot_id=refreshed_lot.id,
            relationship_type="detail",
        )
    await session.commit()
    return RawParseOutcome(lots_found=1, lots_updated=1)
