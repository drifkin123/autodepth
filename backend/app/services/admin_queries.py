"""Admin query helpers for the auction ingestion service."""

from __future__ import annotations

from datetime import date

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auction_lot import AuctionLot
from app.models.scrape_run import ScrapeRun


async def query_paginated_lots(
    db: AsyncSession,
    *,
    source: str | None = None,
    auction_status: str | None = None,
    make: str | None = None,
    model: str | None = None,
    year: int | None = None,
    ended_from: str | None = None,
    ended_to: str | None = None,
    is_sold: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuctionLot], int]:
    filters = []
    if source:
        filters.append(AuctionLot.source == source)
    if auction_status:
        filters.append(AuctionLot.auction_status == auction_status)
    if make:
        filters.append(AuctionLot.make.ilike(f"%{make}%"))
    if model:
        filters.append(AuctionLot.model.ilike(f"%{model}%"))
    if year is not None:
        filters.append(AuctionLot.year == year)
    if ended_from:
        filters.append(func.date(AuctionLot.ended_at) >= date.fromisoformat(ended_from))
    if ended_to:
        filters.append(func.date(AuctionLot.ended_at) <= date.fromisoformat(ended_to))
    if is_sold is True:
        filters.append(AuctionLot.auction_status == "sold")
    elif is_sold is False:
        filters.append(AuctionLot.auction_status != "sold")

    count_query = select(func.count()).select_from(AuctionLot)
    if filters:
        count_query = count_query.where(*filters)
    total = (await db.execute(count_query)).scalar_one()

    data_query = (
        select(AuctionLot)
        .options(selectinload(AuctionLot.images))
        .order_by(desc(AuctionLot.ended_at), desc(AuctionLot.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        data_query = data_query.where(*filters)
    rows = (await db.execute(data_query)).scalars().all()
    return list(rows), total


async def query_scrape_runs(
    db: AsyncSession,
    *,
    limit: int = 50,
    source: str | None = None,
    errors_only: bool = False,
) -> list[ScrapeRun]:
    query = select(ScrapeRun).order_by(desc(ScrapeRun.started_at)).limit(limit)
    if source:
        query = query.where(ScrapeRun.source == source)
    if errors_only:
        query = query.where(ScrapeRun.error.isnot(None))
    return list((await db.execute(query)).scalars().all())
