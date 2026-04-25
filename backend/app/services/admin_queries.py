"""Admin query helpers for the auction ingestion service."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auction_lot import AuctionLot
from app.models.scrape_anomaly import ScrapeAnomaly
from app.models.scrape_request_log import ScrapeRequestLog
from app.models.scrape_run import ScrapeRun

ACTIVE_SOURCES = ("bring_a_trailer", "cars_and_bids")


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


async def query_request_logs(
    db: AsyncSession,
    *,
    limit: int = 100,
    source: str | None = None,
    run_id: uuid.UUID | None = None,
    outcome: str | None = None,
    status_code: int | None = None,
    errors_only: bool = False,
) -> list[ScrapeRequestLog]:
    query = select(ScrapeRequestLog).order_by(desc(ScrapeRequestLog.created_at)).limit(limit)
    if source:
        query = query.where(ScrapeRequestLog.source == source)
    if run_id:
        query = query.where(ScrapeRequestLog.scrape_run_id == run_id)
    if outcome:
        query = query.where(ScrapeRequestLog.outcome == outcome)
    if status_code:
        query = query.where(ScrapeRequestLog.status_code == status_code)
    if errors_only:
        query = query.where(
            ScrapeRequestLog.outcome.in_(("error", "retry", "blocked", "selector_missing"))
        )
    return list((await db.execute(query)).scalars().all())


async def query_anomalies(
    db: AsyncSession,
    *,
    limit: int = 100,
    source: str | None = None,
    severity: str | None = None,
    run_id: uuid.UUID | None = None,
) -> list[ScrapeAnomaly]:
    query = select(ScrapeAnomaly).order_by(desc(ScrapeAnomaly.created_at)).limit(limit)
    if source:
        query = query.where(ScrapeAnomaly.source == source)
    if severity:
        query = query.where(ScrapeAnomaly.severity == severity)
    if run_id:
        query = query.where(ScrapeAnomaly.scrape_run_id == run_id)
    return list((await db.execute(query)).scalars().all())


async def query_source_health(db: AsyncSession) -> list[dict]:
    health_rows: list[dict] = []
    stale_cutoff = datetime.now(UTC) - timedelta(hours=36)
    for source in ACTIVE_SOURCES:
        latest_run = (
            await db.execute(
                select(ScrapeRun)
                .where(ScrapeRun.source == source)
                .order_by(desc(ScrapeRun.started_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        latest_success = (
            await db.execute(
                select(ScrapeRun)
                .where(ScrapeRun.source == source, ScrapeRun.status == "success")
                .order_by(desc(ScrapeRun.started_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        latest_anomaly = (
            await db.execute(
                select(ScrapeAnomaly)
                .where(ScrapeAnomaly.source == source)
                .order_by(desc(ScrapeAnomaly.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        last_success_at = latest_success.finished_at if latest_success else None
        state = "idle"
        if latest_run and latest_run.status == "running":
            state = "running"
        elif latest_run and latest_run.status == "error":
            state = "error"
        elif last_success_at is None or last_success_at < stale_cutoff:
            state = "stale"
        health_rows.append(
            {
                "source": source,
                "state": state,
                "last_run_at": latest_run.started_at if latest_run else None,
                "last_success_at": last_success_at,
                "latest_status": latest_run.status if latest_run else None,
                "records_found": latest_run.records_found if latest_run else 0,
                "records_inserted": latest_run.records_inserted if latest_run else 0,
                "records_updated": latest_run.records_updated if latest_run else 0,
                "latest_anomaly_severity": latest_anomaly.severity if latest_anomaly else None,
                "latest_anomaly_message": latest_anomaly.message if latest_anomaly else None,
                "is_stale": last_success_at is None or last_success_at < stale_cutoff,
            }
        )
    return health_rows
