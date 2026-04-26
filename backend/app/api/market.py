"""Public market analytics routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.market_mapping import depreciation_point, lot_detail, lot_list_item
from app.api.market_params import MarketFilterParams
from app.api.market_schemas import (
    DepreciationResponse,
    MarketFacets,
    MarketLotDetail,
    MarketSummary,
    NumericRange,
    PaginatedMarketLots,
    PriceHistory,
)
from app.db import get_db
from app.models.auction_lot import AuctionLot
from app.services.market import (
    date_range,
    distinct_values,
    numeric_range,
    query_filtered_lots,
    query_market_lots,
)
from app.services.market_analytics import (
    days_since_epoch,
    integer_average,
    integer_median,
    linear_trend,
    monthly_buckets,
    movement_for_window,
)

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/facets", response_model=MarketFacets)
async def get_market_facets(db: AsyncSession = Depends(get_db)) -> MarketFacets:
    price_minimum, price_maximum = await numeric_range(db, AuctionLot.sold_price)
    mileage_minimum, mileage_maximum = await numeric_range(db, AuctionLot.mileage)
    date_minimum, date_maximum = await date_range(db)
    return MarketFacets(
        sources=await distinct_values(db, AuctionLot.source),
        makes=await distinct_values(db, AuctionLot.make),
        models=await distinct_values(db, AuctionLot.model),
        years=await distinct_values(db, AuctionLot.year),
        transmissions=await distinct_values(db, AuctionLot.transmission),
        exterior_colors=await distinct_values(db, AuctionLot.exterior_color),
        auction_statuses=await distinct_values(db, AuctionLot.auction_status),
        price_range=NumericRange(minimum=price_minimum, maximum=price_maximum),
        mileage_range=NumericRange(minimum=mileage_minimum, maximum=mileage_maximum),
        date_range={"minimum": date_minimum, "maximum": date_maximum},
    )


@router.get("/lots", response_model=PaginatedMarketLots)
async def get_market_lots(
    market_filters: Annotated[MarketFilterParams, Depends()],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200, alias="pageSize"),
    sort: str = "ended_at_desc",
    db: AsyncSession = Depends(get_db),
) -> PaginatedMarketLots:
    lots, total = await query_market_lots(
        db, filters=market_filters.to_filters(), page=page, page_size=page_size, sort=sort
    )
    return PaginatedMarketLots(
        items=[lot_list_item(lot) for lot in lots],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=MarketSummary)
async def get_market_summary(
    market_filters: Annotated[MarketFilterParams, Depends()],
    db: AsyncSession = Depends(get_db),
) -> MarketSummary:
    lots = await query_filtered_lots(db, market_filters.to_filters())
    sold_prices = [lot.sold_price for lot in lots if lot.sold_price is not None]
    mileages = [lot.mileage for lot in lots if lot.mileage is not None]
    return MarketSummary(
        total_count=len(lots),
        sold_count=len(sold_prices),
        median_sale_price=integer_median(sold_prices),
        average_sale_price=integer_average(sold_prices),
        low_sale_price=min(sold_prices) if sold_prices else None,
        high_sale_price=max(sold_prices) if sold_prices else None,
        average_mileage=integer_average(mileages),
        sell_through_rate=round(len(sold_prices) / len(lots), 3) if lots else None,
        movement_30_day=movement_for_window(lots, 30),
        movement_90_day=movement_for_window(lots, 90),
        movement_365_day=movement_for_window(lots, 365),
    )


@router.get("/price-history", response_model=PriceHistory)
async def get_market_price_history(
    market_filters: Annotated[MarketFilterParams, Depends()],
    db: AsyncSession = Depends(get_db),
) -> PriceHistory:
    return PriceHistory(
        buckets=monthly_buckets(
            await query_filtered_lots(db, market_filters.to_filters(sold_only=True))
        )
    )


@router.get("/depreciation", response_model=DepreciationResponse)
async def get_market_depreciation(
    market_filters: Annotated[MarketFilterParams, Depends()],
    db: AsyncSession = Depends(get_db),
) -> DepreciationResponse:
    lots = [
        lot
        for lot in await query_filtered_lots(db, market_filters.to_filters(sold_only=True))
        if lot.ended_at and lot.sold_price
    ]
    points = [depreciation_point(lot) for lot in lots]
    trend = linear_trend([(days_since_epoch(lot.ended_at), lot.sold_price) for lot in lots])
    return DepreciationResponse(points=points, trend=trend)


@router.get("/lots/{lot_id}", response_model=MarketLotDetail)
async def get_market_lot(
    lot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MarketLotDetail:
    lot = (
        await db.execute(
            select(AuctionLot)
            .options(selectinload(AuctionLot.images))
            .where(AuctionLot.id == lot_id)
        )
    ).scalar_one_or_none()
    if lot is None:
        raise HTTPException(status_code=404, detail="Auction lot not found")
    return lot_detail(lot)
