"""Admin routes and dashboard for the auction ingestion service."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.admin_schemas import (
    AuctionLotListItem,
    AuctionLotOut,
    PaginatedLots,
    ScraperStatus,
    ScrapeRunOut,
    TargetEntry,
    TriggerRequest,
)
from app.broadcast import broadcaster
from app.db import async_session_factory, get_db
from app.models.auction_lot import AuctionLot
from app.scrapers.bring_a_trailer import get_url_entries as get_bat_target_entries
from app.scrapers.cars_and_bids import get_url_entries as get_cars_and_bids_target_entries
from app.services.admin_queries import query_paginated_lots, query_scrape_runs
from app.services.scraper import run_scrape_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_DASHBOARD_HTML = (
    Path(__file__).parent / "templates" / "admin_dashboard.html"
).read_text()


@router.get("/scrapers/bat/targets", response_model=list[TargetEntry])
async def bat_target_list() -> list[TargetEntry]:
    return [TargetEntry(**entry) for entry in get_bat_target_entries()]


@router.get("/scrapers/cars_and_bids/targets", response_model=list[TargetEntry])
async def cars_and_bids_target_list() -> list[TargetEntry]:
    return [TargetEntry(**entry) for entry in get_cars_and_bids_target_entries()]


@router.post("/scrape/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    body: TriggerRequest | None = None,
) -> dict:
    if broadcaster.is_running:
        raise HTTPException(status_code=409, detail="A scrape is already running.")
    bat_keys = (
        set(body.bat_selected_keys)
        if body and body.bat_selected_keys is not None
        else None
    )
    cab_keys = (
        set(body.carsandbids_selected_keys)
        if body and body.carsandbids_selected_keys is not None
        else None
    )
    mode = body.mode if body else "incremental"
    background_tasks.add_task(
        run_scrape_job,
        broadcaster,
        async_session_factory,
        bat_selected_keys=bat_keys,
        carsandbids_selected_keys=cab_keys,
        mode=mode,
    )
    return {"message": "Scrape started. Connect to /api/admin/ws/stream to follow progress."}


@router.post("/scrape/stop", status_code=status.HTTP_200_OK)
async def stop_scrape() -> dict:
    if not broadcaster.is_running:
        raise HTTPException(status_code=409, detail="No scrape is currently running.")
    broadcaster.request_cancel()
    return {"message": "Cancel requested. The scrape will stop after the current page."}


@router.get("/status", response_model=ScraperStatus)
async def get_status() -> ScraperStatus:
    return ScraperStatus(is_running=broadcaster.is_running)


@router.get("/lots", response_model=PaginatedLots)
async def get_lots(
    source: str | None = Query(default=None),
    auction_status: str | None = Query(default=None),
    make: str | None = Query(default=None),
    model: str | None = Query(default=None),
    year: int | None = Query(default=None),
    ended_from: str | None = Query(default=None),
    ended_to: str | None = Query(default=None),
    is_sold: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> PaginatedLots:
    try:
        rows, total = await query_paginated_lots(
            db,
            source=source,
            auction_status=auction_status,
            make=make,
            model=model,
            year=year,
            ended_from=ended_from,
            ended_to=ended_to,
            is_sold=is_sold,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        logger.exception("Failed to query auction lots")
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc

    items = [
        AuctionLotListItem(
            id=lot.id,
            source=lot.source,
            source_auction_id=lot.source_auction_id,
            canonical_url=lot.canonical_url,
            auction_status=lot.auction_status,
            sold_price=lot.sold_price,
            high_bid=lot.high_bid,
            bid_count=lot.bid_count,
            currency=lot.currency,
            ended_at=lot.ended_at,
            year=lot.year,
            make=lot.make,
            model=lot.model,
            trim=lot.trim,
            mileage=lot.mileage,
            exterior_color=lot.exterior_color,
            title=lot.title,
            subtitle=lot.subtitle,
            image_count=len(lot.images),
        )
        for lot in rows
    ]
    return PaginatedLots(items=items, total=total, page=page, page_size=page_size)


@router.get("/lots/{lot_id}", response_model=AuctionLotOut)
async def get_lot(
    lot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AuctionLotOut:
    lot = await db.get(AuctionLot, lot_id, options=[selectinload(AuctionLot.images)])
    if lot is None:
        raise HTTPException(status_code=404, detail="Auction lot not found")
    return AuctionLotOut.model_validate(lot)


@router.get("/logs", response_model=list[ScrapeRunOut])
async def get_scrape_logs(
    limit: int = Query(default=50, ge=1, le=200),
    source: str | None = Query(default=None),
    errors_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[ScrapeRunOut]:
    try:
        rows = await query_scrape_runs(db, limit=limit, source=source, errors_only=errors_only)
    except Exception as exc:
        logger.exception("Failed to query scrape runs")
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc
    return [ScrapeRunOut.model_validate(row) for row in rows]


@router.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = broadcaster.subscribe()
    try:
        while True:
            event = await queue.get()
            if event is None:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "done",
                            "source": "system",
                            "message": "Stream closed.",
                            "timestamp": "",
                            "data": {},
                        }
                    )
                )
                break
            await websocket.send_text(json.dumps(event.to_dict()))
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unsubscribe(queue)


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard() -> HTMLResponse:
    return HTMLResponse(content=_DASHBOARD_HTML)
