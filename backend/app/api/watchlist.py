"""Watchlist routes — all require authentication."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cars import APIModel, CarOut
from app.auth import get_current_user_id
from app.db import get_db
from app.models.car import Car
from app.models.watchlist import WatchlistItem
from app.services.depreciation import compute_depreciation_result

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistItemOut(APIModel):
    id: uuid.UUID
    user_id: str
    car_id: uuid.UUID
    target_price: int | None
    notes: str | None
    added_at: datetime


class WatchlistItemWithStatusOut(APIModel):
    id: uuid.UUID
    user_id: str
    car_id: uuid.UUID
    target_price: int | None
    notes: str | None
    added_at: datetime
    car: CarOut
    current_estimated_value: int | None
    value_delta_since_added: float | None
    buy_window_status: str | None


class WatchlistAddRequest(BaseModel):
    car_id: uuid.UUID
    target_price: int | None = None
    notes: str | None = None


@router.get("", response_model=list[WatchlistItemWithStatusOut])
async def get_watchlist(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> list[WatchlistItemWithStatusOut]:
    items = (
        await db.execute(
            select(WatchlistItem)
            .where(WatchlistItem.user_id == user_id)
            .order_by(WatchlistItem.added_at.desc())
        )
    ).scalars().all()

    enriched: list[WatchlistItemWithStatusOut] = []
    today = date.today()

    for item in items:
        car = await db.get(Car, item.car_id)
        if car is None:
            continue

        dep = await compute_depreciation_result(db, car)
        buy_status: str | None = dep.buy_window_status if dep.fit else None

        current_value: int | None = None
        if dep.predictions:
            nearest = min(dep.predictions, key=lambda p: abs((p.predicted_for - today).days))
            current_value = nearest.predicted_price

        enriched.append(
            WatchlistItemWithStatusOut(
                id=item.id,
                user_id=item.user_id,
                car_id=item.car_id,
                target_price=item.target_price,
                notes=item.notes,
                added_at=item.added_at,
                car=CarOut.model_validate(car),
                current_estimated_value=current_value,
                value_delta_since_added=None,
                buy_window_status=buy_status,
            )
        )

    return enriched


@router.post("", response_model=WatchlistItemOut, status_code=201)
async def add_to_watchlist(
    body: WatchlistAddRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> WatchlistItemOut:
    car = await db.get(Car, body.car_id)
    if car is None:
        raise HTTPException(status_code=404, detail="Car not found")

    existing = (
        await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user_id,
                WatchlistItem.car_id == body.car_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Car already in watchlist")

    try:
        item = WatchlistItem(
            id=uuid.uuid4(),
            user_id=user_id,
            car_id=body.car_id,
            target_price=body.target_price,
            notes=body.notes,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
    except Exception as exc:
        logger.exception("Failed to add watchlist item")
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    return WatchlistItemOut.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def remove_from_watchlist(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> None:
    item = await db.get(WatchlistItem, item_id)
    if item is None or item.user_id != user_id:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    try:
        await db.delete(item)
        await db.commit()
    except Exception as exc:
        logger.exception("Failed to delete watchlist item")
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
