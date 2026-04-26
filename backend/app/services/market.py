"""Query helpers for public market analytics."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Select, and_, asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.sqltypes import String

from app.models.auction_lot import AuctionLot

TextFilters = list[str] | None


def _clean_values(values: TextFilters) -> list[str]:
    if not values:
        return []
    cleaned: list[str] = []
    for value in values:
        cleaned.extend(part.strip() for part in value.split(",") if part.strip())
    return cleaned


def build_market_filters(
    *,
    source: TextFilters = None,
    auction_status: TextFilters = None,
    make: TextFilters = None,
    model: TextFilters = None,
    year_min: int | None = None,
    year_max: int | None = None,
    transmission: TextFilters = None,
    exterior_color: TextFilters = None,
    price_min: int | None = None,
    price_max: int | None = None,
    mileage_min: int | None = None,
    mileage_max: int | None = None,
    ended_from: date | None = None,
    ended_to: date | None = None,
    sold_only: bool = False,
    search: str | None = None,
) -> list:
    filters = []
    text_fields = (
        (AuctionLot.source, source),
        (AuctionLot.auction_status, auction_status),
        (AuctionLot.make, make),
        (AuctionLot.model, model),
        (AuctionLot.transmission, transmission),
        (AuctionLot.exterior_color, exterior_color),
    )
    for column, values in text_fields:
        cleaned = _clean_values(values)
        if cleaned:
            filters.append(column.in_(cleaned))

    if year_min is not None:
        filters.append(AuctionLot.year >= year_min)
    if year_max is not None:
        filters.append(AuctionLot.year <= year_max)
    if mileage_min is not None:
        filters.append(AuctionLot.mileage >= mileage_min)
    if mileage_max is not None:
        filters.append(AuctionLot.mileage <= mileage_max)
    if ended_from is not None:
        filters.append(func.date(AuctionLot.ended_at) >= ended_from)
    if ended_to is not None:
        filters.append(func.date(AuctionLot.ended_at) <= ended_to)
    if sold_only:
        filters.append(and_(AuctionLot.auction_status == "sold", AuctionLot.sold_price.isnot(None)))
    if price_min is not None:
        filters.append(AuctionLot.sold_price >= price_min)
    if price_max is not None:
        filters.append(AuctionLot.sold_price <= price_max)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                AuctionLot.title.ilike(pattern),
                AuctionLot.make.ilike(pattern),
                AuctionLot.model.ilike(pattern),
                AuctionLot.trim.ilike(pattern),
            )
        )
    return filters


def apply_market_filters(query: Select, filters: list) -> Select:
    if filters:
        return query.where(*filters)
    return query


async def distinct_values(db: AsyncSession, column) -> list:
    predicates = [column.isnot(None)]
    if isinstance(column.type, String):
        predicates.append(column != "")
    rows = (
        await db.execute(
            select(column).where(*predicates).distinct().order_by(asc(column))
        )
    ).scalars().all()
    return list(rows)


async def numeric_range(db: AsyncSession, column):
    row = (await db.execute(select(func.min(column), func.max(column)))).one()
    return row[0], row[1]


async def date_range(db: AsyncSession):
    row = (
        await db.execute(
            select(
                func.min(func.date(AuctionLot.ended_at)),
                func.max(func.date(AuctionLot.ended_at)),
            )
        )
    ).one()
    return row[0], row[1]


def sorted_lots_query(sort: str) -> Select:
    query = select(AuctionLot).options(selectinload(AuctionLot.images))
    sort_map = {
        "ended_at_asc": asc(AuctionLot.ended_at),
        "price_desc": desc(AuctionLot.sold_price),
        "price_asc": asc(AuctionLot.sold_price),
        "mileage_desc": desc(AuctionLot.mileage),
        "mileage_asc": asc(AuctionLot.mileage),
    }
    return query.order_by(
        sort_map.get(sort, desc(AuctionLot.ended_at)), desc(AuctionLot.created_at)
    )


async def query_market_lots(
    db: AsyncSession,
    *,
    filters: list,
    page: int,
    page_size: int,
    sort: str,
) -> tuple[list[AuctionLot], int]:
    count_query = apply_market_filters(select(func.count()).select_from(AuctionLot), filters)
    total = (await db.execute(count_query)).scalar_one()
    data_query = (
        apply_market_filters(sorted_lots_query(sort), filters)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(data_query)).scalars().all()
    return list(rows), total


async def query_filtered_lots(db: AsyncSession, filters: list) -> list[AuctionLot]:
    query = apply_market_filters(
        select(AuctionLot).options(selectinload(AuctionLot.images)).order_by(asc(AuctionLot.ended_at)),
        filters,
    )
    return list((await db.execute(query)).scalars().all())
