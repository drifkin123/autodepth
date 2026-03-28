"""Depreciation prediction and car comparison routes."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import Float, case, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cars import APIModel, CarOut
from app.db import get_db
from app.models.car import Car
from app.models.vehicle_sale import VehicleSale
from app.services.depreciation import compute_depreciation_result

logger = logging.getLogger(__name__)

router = APIRouter(tags=["predictions"])


class PricePredictionOut(APIModel):
    id: uuid.UUID
    car_id: uuid.UUID
    model_version: str
    predicted_for: date
    predicted_price: int
    confidence_low: int
    confidence_high: int
    generated_at: datetime


class PredictionResponse(APIModel):
    car: CarOut
    predictions: list[PricePredictionOut]
    buy_window_status: str
    buy_window_date: date | None
    summary: str


class CompareResponse(APIModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    cars: list[CarOut]
    price_histories: dict[str, list[dict]]
    predictions: dict[str, list[PricePredictionOut]]
    ai_summary: str


@router.get("/cars/{car_id}/prediction", response_model=PredictionResponse)
async def get_prediction(
    car_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PredictionResponse:
    car = await db.get(Car, car_id)
    if car is None:
        raise HTTPException(status_code=404, detail="Car not found")

    result = await compute_depreciation_result(db, car)

    return PredictionResponse(
        car=CarOut.model_validate(car),
        predictions=[PricePredictionOut.model_validate(p) for p in result.predictions],
        buy_window_status=result.buy_window_status,
        buy_window_date=result.buy_window_date,
        summary=result.summary,
    )


@router.get("/compare", response_model=CompareResponse)
async def compare_cars(
    ids: str = Query(..., description="Comma-separated car UUIDs (2–4)"),
    db: AsyncSession = Depends(get_db),
) -> CompareResponse:
    try:
        car_ids = [uuid.UUID(i.strip()) for i in ids.split(",")]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid UUID in ids parameter") from exc

    if not 2 <= len(car_ids) <= 4:
        raise HTTPException(status_code=422, detail="Provide between 2 and 4 car IDs")

    cars: list[Car] = []
    for cid in car_ids:
        car = await db.get(Car, cid)
        if car is None:
            raise HTTPException(status_code=404, detail=f"Car not found: {cid}")
        cars.append(car)

    # Compute depreciation for each car
    dep_results = {str(car.id): await compute_depreciation_result(db, car) for car in cars}

    # Monthly price history for each car
    price_histories: dict[str, list[dict]] = {}
    for car in cars:
        rows = (
            await db.execute(
                select(
                    extract("year", VehicleSale.listed_at).label("yr"),
                    extract("month", VehicleSale.listed_at).label("mo"),
                    func.avg(
                        case(
                            (VehicleSale.is_sold.is_(True), VehicleSale.sold_price.cast(Float)),
                            else_=None,
                        )
                    ).label("avg_sold"),
                    func.avg(VehicleSale.asking_price.cast(Float)).label("avg_asking"),
                    func.count(case((VehicleSale.is_sold.is_(True), 1), else_=None)).label("sold_count"),
                    func.count().label("listing_count"),
                )
                .where(VehicleSale.car_id == car.id)
                .group_by("yr", "mo")
                .order_by("yr", "mo")
            )
        ).all()

        price_histories[str(car.id)] = [
            {
                "date": f"{int(r.yr)}-{int(r.mo):02d}",
                "avgSoldPrice": float(r.avg_sold) if r.avg_sold is not None else None,
                "avgAskingPrice": float(r.avg_asking) if r.avg_asking is not None else None,
                "soldCount": int(r.sold_count),
                "listingCount": int(r.listing_count),
            }
            for r in rows
        ]

    ai_summary = await _generate_compare_summary(cars, dep_results)

    return CompareResponse(
        cars=[CarOut.model_validate(c) for c in cars],
        price_histories=price_histories,
        predictions={
            cid: [PricePredictionOut.model_validate(p) for p in dep.predictions]
            for cid, dep in dep_results.items()
        },
        ai_summary=ai_summary,
    )


async def _generate_compare_summary(cars: list[Car], dep_results: dict) -> str:
    from app.settings import settings

    if not settings.anthropic_api_key:
        return "AI summary unavailable (Anthropic API key not configured)."

    lines = ["Compare the following cars from a buy-timing perspective:\n"]
    for car in cars:
        dep = dep_results.get(str(car.id))
        status = dep.buy_window_status if dep else "unknown"
        floor = f"~${dep.fit.floor / 1000:.0f}k" if dep and dep.fit else "unknown"
        lines.append(
            f"- {car.make} {car.model} {car.trim}: "
            f"buy window = {status}, predicted floor = {floor}, "
            f"MSRP = ${car.msrp_original:,}, "
            f"production = {car.production_count or 'unknown'}, "
            f"{'naturally aspirated' if car.is_naturally_aspirated else 'turbocharged'}"
        )
    lines.append(
        "\nWhich is the better buy right now and why? "
        "Answer in 2–3 sentences, be direct and specific."
    )

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": "\n".join(lines)}],
        )
        return str(message.content[0].text)  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("Anthropic API call failed: %s", exc)
        return "AI summary temporarily unavailable."
