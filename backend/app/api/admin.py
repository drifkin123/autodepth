"""Admin-only routes and dashboard (requires ADMIN_SECRET)."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broadcast import ScrapeEvent, broadcaster
from app.db import async_session_factory, get_db
from app.models.scrape_log import ScrapeLog
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
# Response schemas
# ---------------------------------------------------------------------------

class ScrapeResult(BaseModel):
    results: dict[str, tuple[int, int]]
    message: str


class ScrapeLogOut(BaseModel):
    id: str
    source: str
    started_at: datetime
    finished_at: datetime | None
    records_found: int
    records_inserted: int
    error: str | None

    model_config = {"from_attributes": True}


class ScraperStatus(BaseModel):
    is_running: bool
    effective_secret_hint: str  # first 4 chars of the active secret (for confirmation)


# ---------------------------------------------------------------------------
# Background task: full scrape + depreciation refresh
# ---------------------------------------------------------------------------

async def _run_scrape_job() -> None:
    """Run scrapers + depreciation model as a background task with event streaming."""
    broadcaster.is_running = True
    await broadcaster.publish(
        ScrapeEvent(type="start", source="system", message="Scrape job started.")
    )
    try:
        async with async_session_factory() as session:
            results = await run_all_scrapers(session, broadcaster)

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

@router.post("/scrape/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    _token: str = Depends(require_admin),
) -> dict:
    """Kick off a scrape + depreciation refresh in the background. Stream progress via WebSocket."""
    if broadcaster.is_running:
        raise HTTPException(status_code=409, detail="A scrape is already running.")
    background_tasks.add_task(_run_scrape_job)
    return {"message": "Scrape started. Connect to /api/admin/ws/stream to follow progress."}


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
                # Sentinel: job finished
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

_DASHBOARD_HTML = """<!DOCTYPE html>
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

    main { padding: 24px; max-width: 1200px; margin: 0 auto; }

    /* ── Action bar ── */
    .actions { display: flex; gap: 10px; margin-bottom: 24px; }
    button {
      padding: 8px 18px; border-radius: 6px; font-size: 13px; font-weight: 500;
      cursor: pointer; border: none; transition: opacity .15s;
    }
    button:hover { opacity: .85; }
    button:disabled { opacity: .4; cursor: not-allowed; }
    .btn-primary { background: var(--accent); color: #0A0A0A; }
    .btn-secondary { background: #1e1e1e; color: var(--text); border: 1px solid var(--border); }
    .btn-danger { background: #2a1a1a; color: var(--red); border: 1px solid #4a2a2a; }

    /* ── Stats row ── */
    .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
    .stat-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 8px; padding: 16px;
    }
    .stat-card .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
    .stat-card .value { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
    .stat-card .value.accent { color: var(--accent); }
    .stat-card .value.red { color: var(--red); }
    .stat-card .value.green { color: var(--green); }

    /* ── Two-column layout ── */
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

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

    /* ── Log feed ── */
    #log-feed {
      height: 360px; overflow-y: auto; padding: 12px 16px;
      font-family: 'Menlo', 'Consolas', monospace; font-size: 12px; line-height: 1.7;
      background: #0d0d0d;
    }
    #log-feed::-webkit-scrollbar { width: 4px; }
    #log-feed::-webkit-scrollbar-track { background: transparent; }
    #log-feed::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
    .log-line { display: flex; gap: 10px; }
    .log-ts { color: var(--muted); flex-shrink: 0; }
    .log-source { color: var(--accent); flex-shrink: 0; min-width: 120px; }
    .log-msg { }
    .log-start .log-msg { color: var(--blue); }
    .log-complete .log-msg { color: var(--green); }
    .log-error .log-msg { color: var(--red); }
    .log-done .log-msg { color: var(--muted); font-style: italic; }
    #log-empty { color: var(--muted); font-style: italic; font-size: 12px; padding: 4px 0; }

    /* ── History table ── */
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 9px 14px; text-align: left; white-space: nowrap; }
    th { font-size: 11px; font-weight: 600; text-transform: uppercase;
         letter-spacing: .05em; color: var(--muted); border-bottom: 1px solid var(--border); }
    td { border-bottom: 1px solid #1a1a1a; font-size: 12px; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #171717; }
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
      <span id="running-pill" class="status-pill pill-idle">● Idle</span>
    </div>
  </header>

  <main>
    <div class="actions">
      <button id="btn-scrape" class="btn-primary" onclick="triggerScrape()">▶ Trigger Scrape</button>
      <button id="btn-depreciation" class="btn-secondary" onclick="triggerDepreciation()">↻ Run Depreciation Model</button>
      <button class="btn-secondary" onclick="loadLogs()">⟳ Refresh Logs</button>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="label">Total Scrape Runs</div>
        <div class="value accent" id="stat-total">—</div>
      </div>
      <div class="stat-card">
        <div class="label">Last Run</div>
        <div class="value" id="stat-last" style="font-size:13px;padding-top:4px">—</div>
      </div>
      <div class="stat-card">
        <div class="label">Records Inserted (last run)</div>
        <div class="value green" id="stat-inserted">—</div>
      </div>
      <div class="stat-card">
        <div class="label">Errors (last 50 runs)</div>
        <div class="value" id="stat-errors">—</div>
      </div>
    </div>

    <div class="grid-2">
      <!-- Live log feed -->
      <div class="panel">
        <div class="panel-header">
          <h2>Live Log Feed</h2>
          <span class="hint">Real-time events from active scrape</span>
        </div>
        <div id="log-feed">
          <div id="log-empty">Waiting for scrape events…</div>
        </div>
      </div>

      <!-- Scrape history -->
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
  </main>
</div>

<script>
  let TOKEN = '';
  let ws = null;
  let logEmpty = true;

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
    await loadLogs();
    connectWebSocket();
    // Poll running status every 3s
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
    const btnDepr = document.getElementById('btn-depreciation');
    if (running) {
      pill.textContent = '● Running';
      pill.className = 'status-pill pill-running';
      btnScrape.disabled = true;
      btnDepr.disabled = true;
    } else {
      pill.textContent = '● Idle';
      pill.className = 'status-pill pill-idle';
      btnScrape.disabled = false;
      btnDepr.disabled = false;
    }
  }

  // ── WebSocket ──────────────────────────────────────────────────────────────
  function connectWebSocket() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/api/admin/ws/stream?token=${encodeURIComponent(TOKEN)}`;
    ws = new WebSocket(url);

    ws.onopen = () => setWsStatus(true);
    ws.onclose = () => {
      setWsStatus(false);
      // Reconnect after 5s
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
    if (evt.type === 'done' || evt.type === 'complete' || evt.type === 'error') {
      setRunningState(false);
      // Refresh logs after job ends
      setTimeout(loadLogs, 800);
    }
    if (evt.type === 'start') setRunningState(true);
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
      `<span class="log-source">${evt.source}</span>` +
      `<span class="log-msg">${escHtml(evt.message)}</span>`;
    feed.appendChild(line);
    feed.scrollTop = feed.scrollHeight;
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
    logEmpty = true;
    document.getElementById('log-feed').innerHTML = '<div id="log-empty" style="color:var(--muted);font-style:italic">Starting…</div>';
    try {
      const res = await fetch(`/api/admin/scrape/trigger?token=${encodeURIComponent(TOKEN)}`, { method: 'POST' });
      if (res.status === 409) { alert('A scrape is already running.'); return; }
      if (!res.ok) { alert('Failed to start scrape.'); return; }
      setRunningState(true);
      // Reconnect WebSocket if not already connected
      if (!ws || ws.readyState !== WebSocket.OPEN) connectWebSocket();
    } catch (e) { alert('Error: ' + e.message); }
  }

  async function triggerDepreciation() {
    try {
      const res = await fetch(`/api/admin/depreciation/trigger?token=${encodeURIComponent(TOKEN)}`, { method: 'POST' });
      if (!res.ok) { alert('Failed to start depreciation run.'); return; }
      setRunningState(true);
    } catch (e) { alert('Error: ' + e.message); }
  }
</script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard() -> HTMLResponse:
    """Serve the admin dashboard HTML page (auth handled client-side)."""
    return HTMLResponse(content=_DASHBOARD_HTML)
