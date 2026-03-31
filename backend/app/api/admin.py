"""Admin-only routes and dashboard (requires ADMIN_SECRET)."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broadcast import ScrapeEvent, broadcaster
from app.db import async_session_factory, get_db
from app.models.car import Car
from app.models.scrape_log import ScrapeLog
from app.models.vehicle_sale import VehicleSale
from app.scrapers.bring_a_trailer import get_url_entries
from app.services.depreciation import run_all_depreciation_models
from app.services.scraper import run_all_scrapers
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_EFFECTIVE_SECRET = settings.admin_secret or "dev"


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def require_admin(token: str = Query(default="")) -> str:
    """Accept ?token=<ADMIN_SECRET> on all admin endpoints."""
    if token != _EFFECTIVE_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    return token


# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------

class ScrapeResult(BaseModel):
    results: dict[str, tuple[int, int]]
    message: str


class ScrapeLogOut(BaseModel):
    id: uuid.UUID
    source: str
    started_at: datetime
    finished_at: datetime | None
    records_found: int
    records_inserted: int
    error: str | None

    model_config = {"from_attributes": True}


class ScraperStatus(BaseModel):
    is_running: bool
    effective_secret_hint: str


class BatUrlEntry(BaseModel):
    key: str
    label: str
    path: str


class TriggerRequest(BaseModel):
    bat_selected_keys: list[str] | None = None


class SaleOut(BaseModel):
    id: uuid.UUID
    car_make: str
    car_model: str
    car_trim: str
    source: str
    source_url: str
    sale_type: str
    year: int
    mileage: int | None
    color: str | None
    asking_price: int
    sold_price: int | None
    is_sold: bool
    listed_at: datetime
    sold_at: datetime | None

    model_config = {"from_attributes": True}


class PaginatedSales(BaseModel):
    items: list[SaleOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Background task: full scrape + depreciation refresh
# ---------------------------------------------------------------------------

async def _run_scrape_job(bat_selected_keys: set[str] | None = None) -> None:
    """Run scrapers + depreciation model as a background task with event streaming."""
    broadcaster.is_running = True
    cancel_event = broadcaster.new_cancel_event()
    await broadcaster.publish(
        ScrapeEvent(type="start", source="system", message="Scrape job started.")
    )
    try:
        async with async_session_factory() as session:
            results = await run_all_scrapers(
                session,
                broadcaster,
                bat_selected_keys=bat_selected_keys,
                cancel_event=cancel_event,
            )

        if broadcaster.is_cancelled:
            await broadcaster.publish(
                ScrapeEvent(
                    type="complete",
                    source="system",
                    message="Scrape stopped by user. Skipping depreciation models.",
                    data={"scrape_results": results, "cancelled": True},
                )
            )
        else:
            summary_parts = [
                f"{src}: {f} found / {i} inserted" for src, (f, i) in results.items()
            ]
            await broadcaster.publish(
                ScrapeEvent(
                    type="progress",
                    source="system",
                    message="All scrapers done. Running depreciation models…",
                    data={"scrape_results": results},
                )
            )

            async with async_session_factory() as session:
                await run_all_depreciation_models(session)

            await broadcaster.publish(
                ScrapeEvent(
                    type="complete",
                    source="system",
                    message="Job complete. " + " | ".join(summary_parts),
                    data={"scrape_results": results},
                )
            )
    except Exception as exc:
        logger.exception("Background scrape job failed")
        await broadcaster.publish(
            ScrapeEvent(type="error", source="system", message=f"Job failed: {exc}")
        )
    finally:
        broadcaster.is_running = False
        await broadcaster.signal_done()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/scrapers/bat/urls", response_model=list[BatUrlEntry])
async def bat_url_list(_token: str = Depends(require_admin)) -> list[BatUrlEntry]:
    """Return the full list of Bring a Trailer car URL entries."""
    return [BatUrlEntry(**e) for e in get_url_entries()]


@router.post("/scrape/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    body: TriggerRequest | None = None,
    _token: str = Depends(require_admin),
) -> dict:
    """Kick off a scrape + depreciation refresh in the background."""
    if broadcaster.is_running:
        raise HTTPException(status_code=409, detail="A scrape is already running.")
    selected = set(body.bat_selected_keys) if body and body.bat_selected_keys else None
    background_tasks.add_task(_run_scrape_job, bat_selected_keys=selected)
    return {"message": "Scrape started. Connect to /api/admin/ws/stream to follow progress."}


@router.post("/scrape/stop", status_code=status.HTTP_200_OK)
async def stop_scrape(_token: str = Depends(require_admin)) -> dict:
    """Cancel a running scrape after the current page finishes."""
    if not broadcaster.is_running:
        raise HTTPException(status_code=409, detail="No scrape is currently running.")
    broadcaster.request_cancel()
    return {"message": "Cancel requested. The scrape will stop after the current page."}


@router.post("/depreciation/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_depreciation(
    background_tasks: BackgroundTasks,
    _token: str = Depends(require_admin),
) -> dict:
    """Re-run the depreciation model on all cars without scraping."""
    async def _job() -> None:
        broadcaster.is_running = True
        await broadcaster.publish(ScrapeEvent(type="start", source="system", message="Running depreciation models…"))
        try:
            async with async_session_factory() as session:
                statuses = await run_all_depreciation_models(session)
            await broadcaster.publish(
                ScrapeEvent(
                    type="complete",
                    source="system",
                    message=f"Depreciation models updated for {len(statuses)} car(s).",
                    data={"statuses": statuses},
                )
            )
        except Exception as exc:
            await broadcaster.publish(ScrapeEvent(type="error", source="system", message=str(exc)))
        finally:
            broadcaster.is_running = False
            await broadcaster.signal_done()

    background_tasks.add_task(_job)
    return {"message": "Depreciation refresh started."}


@router.get("/status", response_model=ScraperStatus)
async def get_status(_token: str = Depends(require_admin)) -> ScraperStatus:
    """Return whether a scrape is currently running."""
    hint = _EFFECTIVE_SECRET[:4] + "…" if len(_EFFECTIVE_SECRET) > 4 else _EFFECTIVE_SECRET
    return ScraperStatus(is_running=broadcaster.is_running, effective_secret_hint=hint)


@router.get("/sales", response_model=PaginatedSales)
async def get_sales(
    source: str | None = Query(default=None, description="Filter by scraper source"),
    date_from: date | None = Query(default=None, description="Listed at or after this date (YYYY-MM-DD)"),
    date_to: date | None = Query(default=None, description="Listed before or on this date (YYYY-MM-DD)"),
    is_sold: bool | None = Query(default=None, description="Filter confirmed sales only"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_admin),
) -> PaginatedSales:
    """Return paginated vehicle sales with optional source/date filters."""
    # Build reusable filter conditions
    filters = []
    if source:
        filters.append(VehicleSale.source == source)
    if date_from:
        filters.append(func.date(VehicleSale.listed_at) >= date_from)
    if date_to:
        filters.append(func.date(VehicleSale.listed_at) <= date_to)
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
    rows = result.all()

    items = [
        SaleOut(
            id=sale.id,
            car_make=car.make,
            car_model=car.model,
            car_trim=car.trim,
            source=sale.source,
            source_url=sale.source_url,
            sale_type=sale.sale_type,
            year=sale.year,
            mileage=sale.mileage,
            color=sale.color,
            asking_price=sale.asking_price,
            sold_price=sale.sold_price,
            is_sold=sale.is_sold,
            listed_at=sale.listed_at,
            sold_at=sale.sold_at,
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
    """Return recent scrape run history."""
    q = select(ScrapeLog).order_by(desc(ScrapeLog.started_at)).limit(limit)
    if source:
        q = q.where(ScrapeLog.source == source)
    if errors_only:
        q = q.where(ScrapeLog.error.isnot(None))
    result = await db.execute(q)
    rows = result.scalars().all()
    return [ScrapeLogOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# WebSocket: real-time scrape event stream
# ---------------------------------------------------------------------------

@router.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Stream real-time scrape events to connected admin clients."""
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


# ---------------------------------------------------------------------------
# Admin dashboard HTML page
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AutoDepth — Admin</title>
  <style>
    :root {
      --bg: #0A0A0A;
      --surface: #141414;
      --border: #222;
      --accent: #E8D5A3;
      --text: #F5F5F5;
      --muted: #666;
      --red: #ef4444;
      --green: #4ade80;
      --yellow: #facc15;
      --blue: #60a5fa;
      --orange: #fb923c;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
      font-size: 13px;
      min-height: 100vh;
    }

    /* ── Auth gate ── */
    #auth-gate {
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh;
    }
    .auth-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 40px;
      width: 340px;
      text-align: center;
    }
    .auth-card h1 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
    .auth-card .sub { color: var(--muted); margin-bottom: 24px; font-size: 12px; }
    .auth-card input {
      width: 100%; padding: 10px 14px;
      background: var(--bg); border: 1px solid var(--border);
      border-radius: 6px; color: var(--text); font-size: 13px;
      margin-bottom: 12px; outline: none;
    }
    .auth-card input:focus { border-color: var(--accent); }
    .auth-card .err { color: var(--red); font-size: 12px; margin-bottom: 10px; min-height: 16px; }

    /* ── Dashboard ── */
    #dashboard { display: none; }
    header {
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex; align-items: center; justify-content: space-between;
    }
    header .brand { font-size: 15px; font-weight: 600; }
    header .brand span { color: var(--accent); }
    header .status-pill {
      font-size: 11px; padding: 3px 10px; border-radius: 999px;
      font-weight: 500; letter-spacing: 0.03em;
    }
    .pill-idle { background: #1a1a1a; color: var(--muted); border: 1px solid var(--border); }
    .pill-running { background: #1a2a1a; color: var(--green); border: 1px solid #2a4a2a; animation: pulse 1.5s ease-in-out infinite; }
    @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.6; } }

    main { padding: 24px; max-width: 1400px; margin: 0 auto; }

    /* ── Action bar ── */
    .actions { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
    button {
      padding: 8px 18px; border-radius: 6px; font-size: 13px; font-weight: 500;
      cursor: pointer; border: none; transition: opacity .15s;
    }
    button:hover { opacity: .85; }
    button:disabled { opacity: .4; cursor: not-allowed; }
    .btn-primary { background: var(--accent); color: #0A0A0A; }
    .btn-secondary { background: #1e1e1e; color: var(--text); border: 1px solid var(--border); }
    .btn-danger { background: #2a1a1a; color: var(--red); border: 1px solid #4a2a2a; }

    /* ── Tabs ── */
    .tabs {
      display: flex; gap: 0; margin-bottom: 20px;
      border-bottom: 1px solid var(--border);
    }
    .tab {
      padding: 10px 20px; font-size: 13px; font-weight: 500;
      cursor: pointer; color: var(--muted); border-bottom: 2px solid transparent;
      margin-bottom: -1px; transition: color .15s;
      background: none; border-top: none; border-left: none; border-right: none;
      border-radius: 0;
    }
    .tab:hover { color: var(--text); opacity: 1; }
    .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    /* ── Stats row ── */
    .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
    .stat-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 8px; padding: 16px;
    }
    .stat-card .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
    .stat-card .value { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
    .stat-card .value.accent { color: var(--accent); }
    .stat-card .value.red { color: var(--red); }
    .stat-card .value.green { color: var(--green); }

    /* ── Layout ── */
    .grid-main { display: grid; grid-template-columns: 280px 1fr; gap: 16px; margin-bottom: 16px; }
    @media (max-width: 900px) { .grid-main { grid-template-columns: 1fr; } }

    /* ── Panel ── */
    .panel {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 8px; overflow: hidden;
    }
    .panel-header {
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      display: flex; align-items: center; justify-content: space-between;
    }
    .panel-header h2 { font-size: 13px; font-weight: 600; }
    .panel-header .hint { font-size: 11px; color: var(--muted); }

    /* ── Car selector ── */
    .car-selector { max-height: 520px; overflow-y: auto; }
    .car-selector-controls {
      padding: 10px 16px; border-bottom: 1px solid var(--border);
      display: flex; gap: 8px; align-items: center;
    }
    .car-selector-controls button {
      padding: 4px 10px; font-size: 11px; border-radius: 4px;
    }
    .car-selector-controls .count { font-size: 11px; color: var(--muted); margin-left: auto; }
    .car-list { padding: 6px 0; }
    .car-item {
      display: flex; align-items: center; gap: 10px;
      padding: 6px 16px; cursor: pointer; user-select: none;
      transition: background .1s;
    }
    .car-item:hover { background: #1a1a1a; }
    .car-item input[type=checkbox] {
      accent-color: var(--accent); width: 14px; height: 14px; cursor: pointer;
    }
    .car-item label { font-size: 12px; cursor: pointer; flex: 1; }
    .car-item .car-key { font-size: 10px; color: var(--muted); font-family: monospace; }
    .car-group-label {
      font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em;
      color: var(--accent); padding: 10px 16px 4px; opacity: .7;
    }

    /* ── Log feed ── */
    #log-feed {
      height: 480px; overflow-y: auto; padding: 12px 16px;
      font-family: 'Menlo', 'Consolas', monospace; font-size: 11.5px; line-height: 1.8;
      background: #0d0d0d;
    }
    #log-feed::-webkit-scrollbar { width: 4px; }
    #log-feed::-webkit-scrollbar-track { background: transparent; }
    #log-feed::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
    .log-line { display: flex; gap: 8px; }
    .log-ts { color: var(--muted); flex-shrink: 0; min-width: 72px; }
    .log-source { color: var(--accent); flex-shrink: 0; min-width: 110px; }
    .log-msg { white-space: pre-wrap; word-break: break-word; }
    .log-start .log-msg { color: var(--blue); }
    .log-complete .log-msg { color: var(--green); }
    .log-error .log-msg { color: var(--red); }
    .log-warning .log-msg { color: var(--orange); }
    .log-done .log-msg { color: var(--muted); font-style: italic; }
    .log-detail { color: var(--muted); font-size: 10.5px; padding-left: 190px; line-height: 1.6; }
    #log-empty { color: var(--muted); font-style: italic; font-size: 12px; padding: 4px 0; }

    /* ── Progress bar ── */
    .progress-bar-wrap {
      height: 3px; background: #1a1a1a; margin: 0;
    }
    .progress-bar-fill {
      height: 100%; background: var(--accent); transition: width .4s ease;
      width: 0%;
    }

    /* ── Listings filters ── */
    .filter-bar {
      display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
      padding: 14px 16px; border-bottom: 1px solid var(--border);
    }
    .filter-bar label { font-size: 11px; color: var(--muted); }
    .filter-bar select, .filter-bar input[type=date] {
      background: var(--bg); border: 1px solid var(--border);
      color: var(--text); font-size: 12px; padding: 5px 10px;
      border-radius: 5px; outline: none;
    }
    .filter-bar select:focus, .filter-bar input[type=date]:focus { border-color: var(--accent); }
    .filter-bar .filter-group { display: flex; align-items: center; gap: 6px; }
    #listings-count { font-size: 11px; color: var(--muted); margin-left: auto; }

    /* ── Pagination ── */
    .pagination {
      display: flex; align-items: center; justify-content: space-between;
      padding: 12px 16px; border-top: 1px solid var(--border); font-size: 12px;
    }
    .pagination .page-info { color: var(--muted); }
    .pagination-btns { display: flex; gap: 8px; }
    .pagination-btns button { padding: 5px 14px; font-size: 12px; }

    /* ── History table ── */
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 9px 14px; text-align: left; white-space: nowrap; }
    th { font-size: 11px; font-weight: 600; text-transform: uppercase;
         letter-spacing: .05em; color: var(--muted); border-bottom: 1px solid var(--border); }
    td { border-bottom: 1px solid #1a1a1a; font-size: 12px; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #171717; }
    td a { color: var(--accent); text-decoration: none; }
    td a:hover { text-decoration: underline; }
    .badge {
      display: inline-block; padding: 2px 8px; border-radius: 999px;
      font-size: 10px; font-weight: 600; letter-spacing: .04em;
    }
    .badge-ok { background: #1a2a1a; color: var(--green); }
    .badge-err { background: #2a1a1a; color: var(--red); }
    .badge-running { background: #1a1a2a; color: var(--blue); }

    #no-logs { color: var(--muted); padding: 20px 14px; font-style: italic; font-size: 12px; }

    .ws-indicator {
      display: inline-block; width: 7px; height: 7px; border-radius: 50%;
      margin-right: 6px; background: var(--muted);
    }
    .ws-connected { background: var(--green); }
    .ws-disconnected { background: var(--red); }
  </style>
</head>
<body>

<!-- Auth gate -->
<div id="auth-gate">
  <div class="auth-card">
    <h1>AutoDepth</h1>
    <p class="sub">Admin Dashboard</p>
    <input id="secret-input" type="password" placeholder="Admin secret" autofocus
           onkeydown="if(event.key==='Enter') doLogin()">
    <div class="err" id="auth-err"></div>
    <button class="btn-primary" style="width:100%" onclick="doLogin()">Sign in</button>
  </div>
</div>

<!-- Dashboard -->
<div id="dashboard">
  <header>
    <div class="brand">Auto<span>Depth</span> <span style="color:var(--muted);font-weight:400;font-size:12px;margin-left:6px">Admin</span></div>
    <div style="display:flex;align-items:center;gap:12px">
      <span id="ws-dot" class="ws-indicator"></span>
      <span id="ws-label" style="font-size:11px;color:var(--muted)">WebSocket disconnected</span>
      <span id="running-pill" class="status-pill pill-idle">Idle</span>
    </div>
  </header>

  <main>
    <div class="tabs">
      <button class="tab active" onclick="switchTab('scraper')">Scraper</button>
      <button class="tab" onclick="switchTab('listings')">Listings</button>
    </div>

    <!-- ── Scraper tab ── -->
    <div id="tab-scraper" class="tab-panel active">
      <div class="actions">
        <button id="btn-scrape" class="btn-primary" onclick="triggerScrape()">Run Scrape</button>
        <button id="btn-stop" class="btn-danger" onclick="stopScrape()" disabled>Stop Scrape</button>
        <button id="btn-depreciation" class="btn-secondary" onclick="triggerDepreciation()">Run Depreciation Model</button>
        <button class="btn-secondary" onclick="loadLogs()">Refresh Logs</button>
        <button class="btn-secondary" onclick="clearFeed()">Clear Feed</button>
      </div>

      <div class="stats-row">
        <div class="stat-card">
          <div class="label">Total Scrape Runs</div>
          <div class="value accent" id="stat-total">&mdash;</div>
        </div>
        <div class="stat-card">
          <div class="label">Last Run</div>
          <div class="value" id="stat-last" style="font-size:13px;padding-top:4px">&mdash;</div>
        </div>
        <div class="stat-card">
          <div class="label">Records Inserted (last run)</div>
          <div class="value green" id="stat-inserted">&mdash;</div>
        </div>
        <div class="stat-card">
          <div class="label">Errors (last 50 runs)</div>
          <div class="value" id="stat-errors">&mdash;</div>
        </div>
      </div>

      <div class="grid-main">
        <div class="panel">
          <div class="panel-header">
            <h2>Bring a Trailer</h2>
            <span class="hint">Car pages</span>
          </div>
          <div class="car-selector-controls">
            <button class="btn-secondary" onclick="toggleAll(true)">All</button>
            <button class="btn-secondary" onclick="toggleAll(false)">None</button>
            <span class="count" id="car-count">0 / 0</span>
          </div>
          <div class="car-selector" id="car-selector">
            <div style="padding:16px;color:var(--muted);font-style:italic">Loading…</div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <h2>Live Log Feed</h2>
            <span class="hint" id="log-hint">Real-time events from active scrape</span>
          </div>
          <div class="progress-bar-wrap"><div class="progress-bar-fill" id="progress-bar"></div></div>
          <div id="log-feed">
            <div id="log-empty">Waiting for scrape events…</div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <h2>Scrape History</h2>
          <span class="hint">Last 50 runs</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Found</th>
                <th>Inserted</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody id="logs-tbody">
              <tr><td colspan="6" id="no-logs">Loading…</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ── Listings tab ── -->
    <div id="tab-listings" class="tab-panel">
      <div class="panel">
        <div class="filter-bar">
          <div class="filter-group">
            <label>Source</label>
            <select id="filter-source" onchange="loadListings(1)">
              <option value="">All sources</option>
              <option value="bring_a_trailer">Bring a Trailer</option>
              <option value="cars_and_bids">Cars &amp; Bids</option>
              <option value="rm_sotheby">RM Sotheby's</option>
              <option value="cars_com">Cars.com</option>
            </select>
          </div>
          <div class="filter-group">
            <label>From</label>
            <input type="date" id="filter-date-from" onchange="loadListings(1)">
          </div>
          <div class="filter-group">
            <label>To</label>
            <input type="date" id="filter-date-to" onchange="loadListings(1)">
          </div>
          <div class="filter-group">
            <label>Status</label>
            <select id="filter-sold" onchange="loadListings(1)">
              <option value="">All</option>
              <option value="true">Sold</option>
              <option value="false">Unsold</option>
            </select>
          </div>
          <button class="btn-secondary" onclick="clearListingFilters()">Clear</button>
          <span id="listings-count"></span>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Car</th>
                <th>Year</th>
                <th>Source</th>
                <th>Sold Price</th>
                <th>Asking Price</th>
                <th>Mileage</th>
                <th>Color</th>
                <th>Status</th>
                <th>Listed</th>
                <th>Link</th>
              </tr>
            </thead>
            <tbody id="listings-tbody">
              <tr><td colspan="10" style="padding:20px 14px;color:var(--muted);font-style:italic">Switch to this tab to load listings.</td></tr>
            </tbody>
          </table>
        </div>

        <div class="pagination">
          <span class="page-info" id="listings-page-info"></span>
          <div class="pagination-btns">
            <button class="btn-secondary" id="btn-prev" onclick="listingsPage(-1)" disabled>← Prev</button>
            <button class="btn-secondary" id="btn-next" onclick="listingsPage(+1)" disabled>Next →</button>
          </div>
        </div>
      </div>
    </div>
  </main>
</div>

<script>
  let TOKEN = '';
  let ws = null;
  let logEmpty = true;
  let batUrls = [];
  let listingsCurrentPage = 1;
  let listingsTotal = 0;
  const LISTINGS_PAGE_SIZE = 50;

  // ── Tabs ──────────────────────────────────────────────────────────────────
  function switchTab(name) {
    document.querySelectorAll('.tab').forEach((t, i) => {
      const panels = ['scraper', 'listings'];
      t.classList.toggle('active', panels[i] === name);
    });
    document.querySelectorAll('.tab-panel').forEach(p => {
      p.classList.toggle('active', p.id === 'tab-' + name);
    });
    if (name === 'listings' && listingsTotal === 0) loadListings(1);
  }

  // ── Auth ──────────────────────────────────────────────────────────────────
  async function doLogin() {
    const val = document.getElementById('secret-input').value.trim();
    const errEl = document.getElementById('auth-err');
    errEl.textContent = '';
    try {
      const res = await fetch(`/api/admin/status?token=${encodeURIComponent(val)}`);
      if (res.status === 401) { errEl.textContent = 'Invalid secret.'; return; }
      if (!res.ok) { errEl.textContent = 'Server error. Is the backend running?'; return; }
      TOKEN = val;
      document.getElementById('auth-gate').style.display = 'none';
      document.getElementById('dashboard').style.display = 'block';
      initDashboard();
    } catch (e) {
      errEl.textContent = 'Could not reach server.';
    }
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  async function initDashboard() {
    await Promise.all([loadLogs(), loadBatUrls()]);
    connectWebSocket();
    setInterval(pollStatus, 3000);
    pollStatus();
  }

  async function pollStatus() {
    try {
      const res = await fetch(`/api/admin/status?token=${encodeURIComponent(TOKEN)}`);
      if (!res.ok) return;
      const data = await res.json();
      setRunningState(data.is_running);
    } catch (_) {}
  }

  function setRunningState(running) {
    const pill = document.getElementById('running-pill');
    const btnScrape = document.getElementById('btn-scrape');
    const btnStop = document.getElementById('btn-stop');
    const btnDepr = document.getElementById('btn-depreciation');
    if (running) {
      pill.textContent = 'Running';
      pill.className = 'status-pill pill-running';
      btnScrape.disabled = true;
      btnStop.disabled = false;
      btnDepr.disabled = true;
    } else {
      pill.textContent = 'Idle';
      pill.className = 'status-pill pill-idle';
      btnScrape.disabled = false;
      btnStop.disabled = true;
      btnDepr.disabled = false;
    }
  }

  // ── Car selector ─────────────────────────────────────────────────────────
  async function loadBatUrls() {
    try {
      const res = await fetch(`/api/admin/scrapers/bat/urls?token=${encodeURIComponent(TOKEN)}`);
      if (!res.ok) return;
      batUrls = await res.json();
      renderCarSelector();
    } catch (_) {}
  }

  function renderCarSelector() {
    const container = document.getElementById('car-selector');
    let currentMake = '';
    let html = '<div class="car-list">';
    for (const entry of batUrls) {
      const make = entry.label.split(' ')[0];
      if (make !== currentMake) {
        currentMake = make;
        html += `<div class="car-group-label">${escHtml(make)}</div>`;
      }
      html += `<div class="car-item" onclick="toggleCar('${entry.key}')">
        <input type="checkbox" id="car-${entry.key}" checked data-key="${entry.key}">
        <label for="car-${entry.key}">${escHtml(entry.label)}</label>
      </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
    updateCarCount();
  }

  function toggleCar(key) {
    const cb = document.getElementById('car-' + key);
    cb.checked = !cb.checked;
    updateCarCount();
  }

  function toggleAll(state) {
    document.querySelectorAll('.car-selector input[type=checkbox]').forEach(cb => cb.checked = state);
    updateCarCount();
  }

  function updateCarCount() {
    const all = document.querySelectorAll('.car-selector input[type=checkbox]');
    const checked = document.querySelectorAll('.car-selector input[type=checkbox]:checked');
    document.getElementById('car-count').textContent = `${checked.length} / ${all.length}`;
  }

  function getSelectedKeys() {
    const checked = document.querySelectorAll('.car-selector input[type=checkbox]:checked');
    return Array.from(checked).map(cb => cb.dataset.key);
  }

  // ── WebSocket ──────────────────────────────────────────────────────────────
  function connectWebSocket() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/api/admin/ws/stream?token=${encodeURIComponent(TOKEN)}`;
    ws = new WebSocket(url);

    ws.onopen = () => setWsStatus(true);
    ws.onclose = () => {
      setWsStatus(false);
      setTimeout(connectWebSocket, 5000);
    };
    ws.onerror = () => setWsStatus(false);
    ws.onmessage = (e) => {
      try { handleEvent(JSON.parse(e.data)); } catch (_) {}
    };
  }

  function setWsStatus(connected) {
    const dot = document.getElementById('ws-dot');
    const label = document.getElementById('ws-label');
    dot.className = 'ws-indicator ' + (connected ? 'ws-connected' : 'ws-disconnected');
    label.textContent = connected ? 'WebSocket connected' : 'WebSocket disconnected';
  }

  function handleEvent(evt) {
    appendLog(evt);
    updateProgressBar(evt);
    if (evt.type === 'done' || evt.type === 'complete' || evt.type === 'error') {
      setRunningState(false);
      setProgressBar(0);
      setTimeout(loadLogs, 800);
    }
    if (evt.type === 'start') setRunningState(true);
  }

  function updateProgressBar(evt) {
    const d = evt.data || {};
    if (d.term_index && d.total_terms) {
      setProgressBar((d.term_index / d.total_terms) * 100);
    }
  }

  function setProgressBar(pct) {
    document.getElementById('progress-bar').style.width = pct + '%';
  }

  function appendLog(evt) {
    const feed = document.getElementById('log-feed');
    if (logEmpty) {
      document.getElementById('log-empty')?.remove();
      logEmpty = false;
    }
    const ts = evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : '';
    const line = document.createElement('div');
    line.className = `log-line log-${evt.type}`;
    line.innerHTML =
      `<span class="log-ts">${ts}</span>` +
      `<span class="log-source">${escHtml(evt.source)}</span>` +
      `<span class="log-msg">${escHtml(evt.message)}</span>`;
    feed.appendChild(line);

    // Add detail line for pages with skip/dup data
    const d = evt.data || {};
    if (d.raw_items !== undefined) {
      const detail = document.createElement('div');
      detail.className = 'log-detail';
      const parts = [`${d.raw_items} raw`];
      if (d.sold_parsed !== undefined) parts.push(`${d.sold_parsed} sold`);
      if (d.duplicates) parts.push(`${d.duplicates} dups`);
      if (d.skipped && Object.keys(d.skipped).length) {
        const skipParts = Object.entries(d.skipped).map(([k,v]) => `${v} ${k}`);
        parts.push(`skipped: ${skipParts.join(', ')}`);
      }
      detail.textContent = parts.join('  ·  ');
      feed.appendChild(detail);
    }

    feed.scrollTop = feed.scrollHeight;
  }

  function clearFeed() {
    const feed = document.getElementById('log-feed');
    feed.innerHTML = '<div id="log-empty" style="color:var(--muted);font-style:italic">Waiting for scrape events…</div>';
    logEmpty = true;
    setProgressBar(0);
  }

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Logs table ──────────────────────────────────────────────────────────────
  async function loadLogs() {
    try {
      const res = await fetch(`/api/admin/logs?limit=50&token=${encodeURIComponent(TOKEN)}`);
      if (!res.ok) return;
      const logs = await res.json();
      renderLogs(logs);
      updateStats(logs);
    } catch (_) {}
  }

  function renderLogs(logs) {
    const tbody = document.getElementById('logs-tbody');
    if (!logs.length) {
      tbody.innerHTML = '<tr><td colspan="6" id="no-logs">No scrape runs yet.</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(l => {
      const started = new Date(l.started_at).toLocaleString();
      let duration = '—';
      if (l.finished_at) {
        const ms = new Date(l.finished_at) - new Date(l.started_at);
        duration = ms < 60000 ? `${Math.round(ms/1000)}s` : `${Math.round(ms/60000)}m`;
      }
      const status = l.error
        ? `<span class="badge badge-err">Error</span>`
        : !l.finished_at
          ? `<span class="badge badge-running">Running</span>`
          : `<span class="badge badge-ok">OK</span>`;
      return `<tr>
        <td>${escHtml(l.source)}</td>
        <td>${started}</td>
        <td>${duration}</td>
        <td>${l.records_found}</td>
        <td>${l.records_inserted}</td>
        <td>${status}</td>
      </tr>`;
    }).join('');
  }

  function updateStats(logs) {
    document.getElementById('stat-total').textContent = logs.length;
    if (logs.length) {
      const last = logs[0];
      document.getElementById('stat-last').textContent =
        new Date(last.started_at).toLocaleString();
      document.getElementById('stat-inserted').textContent = last.records_inserted;
    }
    const errors = logs.filter(l => l.error).length;
    const errEl = document.getElementById('stat-errors');
    errEl.textContent = errors;
    errEl.className = 'value ' + (errors > 0 ? 'red' : 'green');
  }

  // ── Actions ──────────────────────────────────────────────────────────────────
  async function triggerScrape() {
    const selectedKeys = getSelectedKeys();
    if (selectedKeys.length === 0) {
      alert('Select at least one car page to scrape.');
      return;
    }
    clearFeed();
    // If all are selected, pass null (scrape all) — otherwise pass the subset
    const allSelected = selectedKeys.length === batUrls.length;
    const body = allSelected ? {} : { bat_selected_keys: selectedKeys };
    try {
      const res = await fetch(`/api/admin/scrape/trigger?token=${encodeURIComponent(TOKEN)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.status === 409) { alert('A scrape is already running.'); return; }
      if (!res.ok) { alert('Failed to start scrape.'); return; }
      setRunningState(true);
      if (!ws || ws.readyState !== WebSocket.OPEN) connectWebSocket();
    } catch (e) { alert('Error: ' + e.message); }
  }

  async function stopScrape() {
    try {
      const res = await fetch(`/api/admin/scrape/stop?token=${encodeURIComponent(TOKEN)}`, { method: 'POST' });
      if (res.status === 409) { alert('No scrape is currently running.'); return; }
      if (!res.ok) { alert('Failed to stop scrape.'); return; }
      document.getElementById('btn-stop').disabled = true;
    } catch (e) { alert('Error: ' + e.message); }
  }

  async function triggerDepreciation() {
    try {
      const res = await fetch(`/api/admin/depreciation/trigger?token=${encodeURIComponent(TOKEN)}`, { method: 'POST' });
      if (!res.ok) { alert('Failed to start depreciation run.'); return; }
      setRunningState(true);
    } catch (e) { alert('Error: ' + e.message); }
  }

  // ── Listings tab ──────────────────────────────────────────────────────────
  async function loadListings(page) {
    listingsCurrentPage = page;
    const source = document.getElementById('filter-source').value;
    const dateFrom = document.getElementById('filter-date-from').value;
    const dateTo = document.getElementById('filter-date-to').value;
    const sold = document.getElementById('filter-sold').value;

    const params = new URLSearchParams({
      token: TOKEN,
      page,
      page_size: LISTINGS_PAGE_SIZE,
    });
    if (source) params.set('source', source);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    if (sold !== '') params.set('is_sold', sold);

    const tbody = document.getElementById('listings-tbody');
    tbody.innerHTML = '<tr><td colspan="10" style="padding:16px 14px;color:var(--muted)">Loading…</td></tr>';

    try {
      const res = await fetch(`/api/admin/sales?${params}`);
      if (!res.ok) { tbody.innerHTML = '<tr><td colspan="10" style="color:var(--red);padding:14px">Failed to load.</td></tr>'; return; }
      const data = await res.json();
      listingsTotal = data.total;
      renderListings(data);
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="10" style="color:var(--red);padding:14px">${escHtml(e.message)}</td></tr>`;
    }
  }

  function renderListings(data) {
    const tbody = document.getElementById('listings-tbody');
    const { items, total, page, page_size } = data;

    document.getElementById('listings-count').textContent =
      total === 0 ? 'No results' : `${total.toLocaleString()} total`;

    const start = (page - 1) * page_size + 1;
    const end = Math.min(page * page_size, total);
    document.getElementById('listings-page-info').textContent =
      total > 0 ? `${start}–${end} of ${total.toLocaleString()}` : '';

    document.getElementById('btn-prev').disabled = page <= 1;
    document.getElementById('btn-next').disabled = end >= total;

    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="10" style="padding:20px 14px;color:var(--muted);font-style:italic">No listings match the current filters.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(s => {
      const car = `${escHtml(s.car_make)} ${escHtml(s.car_model)} ${escHtml(s.car_trim)}`;
      const soldPrice = s.sold_price ? '$' + s.sold_price.toLocaleString() : '—';
      const askPrice = '$' + s.asking_price.toLocaleString();
      const mileage = s.mileage ? s.mileage.toLocaleString() + ' mi' : '—';
      const color = s.color || '—';
      const status = s.is_sold
        ? '<span class="badge badge-ok">Sold</span>'
        : '<span class="badge" style="background:#1a1a2a;color:var(--muted)">Unsold</span>';
      const listed = new Date(s.listed_at).toLocaleDateString();
      const source = escHtml(s.source.replace(/_/g, ' '));
      const link = `<a href="${escHtml(s.source_url)}" target="_blank" rel="noopener">↗</a>`;
      return `<tr>
        <td>${car}</td>
        <td>${s.year}</td>
        <td>${source}</td>
        <td>${soldPrice}</td>
        <td>${askPrice}</td>
        <td>${mileage}</td>
        <td>${color}</td>
        <td>${status}</td>
        <td>${listed}</td>
        <td>${link}</td>
      </tr>`;
    }).join('');
  }

  function listingsPage(delta) {
    loadListings(listingsCurrentPage + delta);
  }

  function clearListingFilters() {
    document.getElementById('filter-source').value = '';
    document.getElementById('filter-date-from').value = '';
    document.getElementById('filter-date-to').value = '';
    document.getElementById('filter-sold').value = '';
    loadListings(1);
  }
</script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard() -> HTMLResponse:
    """Serve the admin dashboard HTML page (auth handled client-side)."""
    return HTMLResponse(content=_DASHBOARD_HTML)
