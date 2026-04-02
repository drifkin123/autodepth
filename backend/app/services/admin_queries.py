"""Admin-specific query helpers for the admin dashboard API."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.car import Car
from app.models.scrape_log import ScrapeLog
from app.models.vehicle_sale import VehicleSale

logger = logging.getLogger(__name__)


async def query_paginated_sales(
    db: AsyncSession,
    *,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    is_sold: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[tuple], int]:
    """Return (rows_of_(VehicleSale, Car), total_count) with optional filters."""
    filters = []
    if source:
        filters.append(VehicleSale.source == source)
    if date_from:
        filters.append(func.date(VehicleSale.listed_at) >= date.fromisoformat(date_from))
    if date_to:
        filters.append(func.date(VehicleSale.listed_at) <= date.fromisoformat(date_to))
    if is_sold is not None:
        filters.append(VehicleSale.is_sold == is_sold)

    count_q = select(func.count()).select_from(VehicleSale)
    if filters:
        count_q = count_q.where(*filters)
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    data_q = (
        select(VehicleSale, Car)
        .join(Car, VehicleSale.car_id == Car.id)
        .order_by(desc(VehicleSale.listed_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        data_q = data_q.where(*filters)
    result = await db.execute(data_q)
    return result.all(), total


async def query_scrape_logs(
    db: AsyncSession,
    *,
    limit: int = 50,
    source: str | None = None,
    errors_only: bool = False,
) -> list[ScrapeLog]:
    """Return recent scrape log entries with optional filters."""
    q = select(ScrapeLog).order_by(desc(ScrapeLog.started_at)).limit(limit)
    if source:
        q = q.where(ScrapeLog.source == source)
    if errors_only:
        q = q.where(ScrapeLog.error.isnot(None))
    result = await db.execute(q)
    return list(result.scalars().all())
