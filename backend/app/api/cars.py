"""Car catalog routes."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import Float, case, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.car import Car
from app.models.vehicle_sale import VehicleSale

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cars", tags=["cars"])


class APIModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class CarOut(APIModel):
    id: uuid.UUID
    make: str
    model: str
    trim: str
    year_start: int
    year_end: int | None
    production_count: int | None
    engine: str
    is_naturally_aspirated: bool
    msrp_original: int
    notes: str | None
    created_at: datetime


class VehicleSaleOut(APIModel):
    id: uuid.UUID
    car_id: uuid.UUID | None
    source: str
    source_url: str
    sale_type: str
    source_auction_id: str | None = None
    auction_status: str | None = None
    year: int
    mileage: int | None
    color: str | None
    asking_price: int
    sold_price: int | None
    high_bid: int | None = None
    bid_count: int | None = None
    title: str | None = None
    subtitle: str | None = None
    image_count: int = 0
    vehicle_details: dict = Field(default_factory=dict)
    is_sold: bool
    listed_at: datetime
    sold_at: datetime | None
    condition_notes: str | None


class PaginatedSales(APIModel):
    items: list[VehicleSaleOut]
    total: int
    page: int
    page_size: int


class CarSalesResponse(APIModel):
    car: CarOut
    sales: PaginatedSales


class PricePoint(APIModel):
    date: str  # "YYYY-MM"
    avg_sold_price: float | None
    avg_asking_price: float | None
    sold_count: int
    listing_count: int


class PriceHistoryResponse(APIModel):
    car: CarOut
    price_history: list[PricePoint]


@router.get("", response_model=list[CarOut])
async def list_cars(
    make: str | None = Query(None),
    model: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[CarOut]:
    try:
        stmt = select(Car)
        if make:
            stmt = stmt.where(Car.make.ilike(f"%{make}%"))
        if model:
            stmt = stmt.where(Car.model.ilike(f"%{model}%"))
        stmt = stmt.order_by(Car.make, Car.model, Car.trim, Car.year_start)
        result = await db.execute(stmt)
        return [CarOut.model_validate(c) for c in result.scalars().all()]
    except Exception as exc:
        logger.exception("Failed to list cars")
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc


@router.get("/{car_id}", response_model=CarOut)
async def get_car(car_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> CarOut:
    car = await db.get(Car, car_id)
    if car is None:
        raise HTTPException(status_code=404, detail="Car not found")
    return CarOut.model_validate(car)


@router.get("/{car_id}/sales", response_model=CarSalesResponse)
async def get_car_sales(
    car_id: uuid.UUID,
    source: str | None = Query(None),
    sale_type: str | None = Query(None),
    is_sold: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> CarSalesResponse:
    car = await db.get(Car, car_id)
    if car is None:
        raise HTTPException(status_code=404, detail="Car not found")

    try:
        stmt = select(VehicleSale).where(VehicleSale.car_id == car_id)
        if source:
            stmt = stmt.where(VehicleSale.source == source)
        if sale_type:
            stmt = stmt.where(VehicleSale.sale_type == sale_type)
        if is_sold is not None:
            stmt = stmt.where(VehicleSale.is_sold == is_sold)

        count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
        total = count_result.scalar_one()

        stmt = (
            stmt.order_by(VehicleSale.listed_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        sales = (await db.execute(stmt)).scalars().all()
    except Exception as exc:
        logger.exception("Failed to query car sales")
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc

    return CarSalesResponse(
        car=CarOut.model_validate(car),
        sales=PaginatedSales(
            items=[VehicleSaleOut.model_validate(s) for s in sales],
            total=total,
            page=page,
            page_size=page_size,
        ),
    )


@router.get("/{car_id}/price-history", response_model=PriceHistoryResponse)
async def get_price_history(
    car_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PriceHistoryResponse:
    car = await db.get(Car, car_id)
    if car is None:
        raise HTTPException(status_code=404, detail="Car not found")

    sold_price_avg = func.avg(case(
        (VehicleSale.is_sold.is_(True), VehicleSale.sold_price.cast(Float)), else_=None,
    ))
    sold_count_expr = func.count(case((VehicleSale.is_sold.is_(True), 1), else_=None))
    try:
        rows = (await db.execute(
            select(
                extract("year", VehicleSale.listed_at).label("yr"),
                extract("month", VehicleSale.listed_at).label("mo"),
                sold_price_avg.label("avg_sold"),
                func.avg(VehicleSale.asking_price.cast(Float)).label("avg_asking"),
                sold_count_expr.label("sold_count"),
                func.count().label("listing_count"),
            ).where(VehicleSale.car_id == car_id).group_by("yr", "mo").order_by("yr", "mo")
        )).all()
    except Exception as exc:
        logger.exception("Failed to query price history")
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc

    price_history = [
        PricePoint(
            date=f"{int(r.yr)}-{int(r.mo):02d}",
            avg_sold_price=float(r.avg_sold) if r.avg_sold is not None else None,
            avg_asking_price=float(r.avg_asking) if r.avg_asking is not None else None,
            sold_count=int(r.sold_count), listing_count=int(r.listing_count),
        ) for r in rows
    ]
    return PriceHistoryResponse(car=CarOut.model_validate(car), price_history=price_history)
