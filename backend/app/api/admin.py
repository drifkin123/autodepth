"""Admin-only routes and dashboard (requires ADMIN_SECRET)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import (
    APIRouter, BackgroundTasks, Depends, HTTPException,
    Query, WebSocket, WebSocketDisconnect, status,
)
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    BatUrlEntry, CarsAndBidsUrlEntry, CarsComUrlEntry, PaginatedSales, SaleOut,
    ScrapeLogOut, ScraperStatus, TriggerRequest,
)
from app.broadcast import broadcaster
from app.db import async_session_factory, get_db
from app.scrapers.bring_a_trailer import get_url_entries as get_bat_url_entries
from app.scrapers.cars_and_bids import get_url_entries as get_cars_and_bids_url_entries
from app.scrapers.cars_com import get_url_entries as get_cars_com_url_entries
from app.services.admin_queries import query_paginated_sales, query_scrape_logs
from app.services.scraper import run_depreciation_job, run_scrape_job
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_EFFECTIVE_SECRET = settings.admin_secret or "dev"

_DASHBOARD_HTML = (
    Path(__file__).parent / "templates" / "admin_dashboard.html"
).read_text()


def require_admin(token: str = Query(default="")) -> str:
    if token != _EFFECTIVE_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    return token


@router.get("/scrapers/bat/urls", response_model=list[BatUrlEntry])
async def bat_url_list(_token: str = Depends(require_admin)) -> list[BatUrlEntry]:
    return [BatUrlEntry(**e) for e in get_bat_url_entries()]


@router.get("/scrapers/cars_com/urls", response_model=list[CarsComUrlEntry])
async def cars_com_url_list(_token: str = Depends(require_admin)) -> list[CarsComUrlEntry]:
    return [CarsComUrlEntry(**e) for e in get_cars_com_url_entries()]


@router.get("/scrapers/cars_and_bids/urls", response_model=list[CarsAndBidsUrlEntry])
async def cars_and_bids_url_list(
    _token: str = Depends(require_admin),
) -> list[CarsAndBidsUrlEntry]:
    return [CarsAndBidsUrlEntry(**e) for e in get_cars_and_bids_url_entries()]


@router.post("/scrape/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    body: TriggerRequest | None = None,
    _token: str = Depends(require_admin),
) -> dict:
    if broadcaster.is_running:
        raise HTTPException(status_code=409, detail="A scrape is already running.")
    bat_keys = set(body.bat_selected_keys) if body and body.bat_selected_keys is not None else None
    cc_keys = set(body.cars_com_selected_keys) if body and body.cars_com_selected_keys is not None else None
    cab_keys = set(body.carsandbids_selected_keys) if body and body.carsandbids_selected_keys is not None else None
    background_tasks.add_task(
        run_scrape_job, broadcaster, async_session_factory,
        bat_selected_keys=bat_keys,
        cars_com_selected_keys=cc_keys,
        carsandbids_selected_keys=cab_keys,
    )
    return {"message": "Scrape started. Connect to /api/admin/ws/stream to follow progress."}


@router.post("/scrape/stop", status_code=status.HTTP_200_OK)
async def stop_scrape(_token: str = Depends(require_admin)) -> dict:
    if not broadcaster.is_running:
        raise HTTPException(status_code=409, detail="No scrape is currently running.")
    broadcaster.request_cancel()
    return {"message": "Cancel requested. The scrape will stop after the current page."}


@router.post("/depreciation/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_depreciation(
    background_tasks: BackgroundTasks,
    _token: str = Depends(require_admin),
) -> dict:
    background_tasks.add_task(run_depreciation_job, broadcaster, async_session_factory)
    return {"message": "Depreciation refresh started."}


@router.get("/status", response_model=ScraperStatus)
async def get_status(_token: str = Depends(require_admin)) -> ScraperStatus:
    hint = _EFFECTIVE_SECRET[:4] + "…" if len(_EFFECTIVE_SECRET) > 4 else _EFFECTIVE_SECRET
    return ScraperStatus(is_running=broadcaster.is_running, effective_secret_hint=hint)


@router.get("/sales", response_model=PaginatedSales)
async def get_sales(
    source: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    is_sold: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_admin),
) -> PaginatedSales:
    try:
        rows, total = await query_paginated_sales(
            db, source=source, date_from=date_from, date_to=date_to,
            is_sold=is_sold, page=page, page_size=page_size,
        )
    except Exception as exc:
        logger.exception("Failed to query sales")
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc

    items = [
        SaleOut(
            id=sale.id, car_make=car.make, car_model=car.model, car_trim=car.trim,
            source=sale.source, source_url=sale.source_url, sale_type=sale.sale_type,
            year=sale.year, mileage=sale.mileage, color=sale.color,
            asking_price=sale.asking_price, sold_price=sale.sold_price,
            is_sold=sale.is_sold, listed_at=sale.listed_at, sold_at=sale.sold_at,
        )
        for sale, car in rows
    ]
    return PaginatedSales(items=items, total=total, page=page, page_size=page_size)


@router.get("/logs", response_model=list[ScrapeLogOut])
async def get_scrape_logs(
    limit: int = Query(default=50, le=200),
    source: str | None = Query(default=None),
    errors_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_admin),
) -> list[ScrapeLogOut]:
    try:
        rows = await query_scrape_logs(db, limit=limit, source=source, errors_only=errors_only)
    except Exception as exc:
        logger.exception("Failed to query scrape logs")
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc
    return [ScrapeLogOut.model_validate(r) for r in rows]


@router.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket, token: str = Query(default="")) -> None:
    if token != _EFFECTIVE_SECRET:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    q = broadcaster.subscribe()
    try:
        while True:
            event = await q.get()
            if event is None:
                await websocket.send_text(
                    json.dumps({"type": "done", "source": "system", "message": "Stream closed.", "timestamp": "", "data": {}})
                )
                break
            await websocket.send_text(json.dumps(event.to_dict()))
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unsubscribe(q)


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard() -> HTMLResponse:
    return HTMLResponse(content=_DASHBOARD_HTML)
