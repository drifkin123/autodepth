# AutoDepth

AutoDepth is now a Python-only auction ingestion service. Its job is narrow:
scrape closed auction lots from Bring a Trailer and Cars & Bids, persist raw
source payloads, extract searchable vehicle fields, and expose an operational
admin console for running and inspecting scrapes.

It intentionally does not include analytics, depreciation modeling,
predictions, watchlists, auth, Cars.com listings, or a TypeScript frontend.

## Service Surface

- `GET /health`
- `GET /api/admin`
- `GET /api/admin/status`
- `GET /api/admin/logs`
- `GET /api/admin/request-logs`
- `GET /api/admin/anomalies`
- `GET /api/admin/lots`
- `GET /api/admin/lots/{id}`
- `GET /api/admin/scrapers/bat/targets`
- `GET /api/admin/scrapers/cars_and_bids/targets`
- `POST /api/admin/scrape/trigger`
- `POST /api/admin/scrape/stop`
- `WS /api/admin/ws/stream`

## Data Model

The initial schema is destructive and raw-first:

- `auction_lots`: one row per source auction lot, keyed by source auction ID
  when available and canonical source URL otherwise. It stores auction status,
  sold price, high bid, bid count, extracted vehicle fields, raw JSON payloads,
  and optional detail HTML.
- `auction_images`: source image URLs for each lot. Image files are not
  downloaded.
- `scrape_runs`: audit trail for scraper executions.
- `scrape_request_logs`: request/navigation/API-attempt audit trail with
  status, timing, retry, parse-count, and error details.
- `scrape_anomalies`: warning and critical events for blocked responses, zero
  parsed lots, selector/API shape changes, and unusual scraper output.
- `crawl_state`: checkpoint state for backfill and incremental crawling.

Existing environments should reset the database before applying the new initial
migration:

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
```

Then run:

```bash
cd backend
uv run alembic upgrade head
```

## Local Setup

```bash
docker-compose up -d
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Open the admin console at `http://localhost:8000/api/admin`.

## Running Scrapers

From `backend/`:

```bash
uv run python scripts/run_scraper.py --source bring_a_trailer --mode incremental
uv run python scripts/run_scraper.py --source cars_and_bids --mode backfill
uv run python scripts/run_scraper.py --mode incremental

# Concurrent BaT backfill, list/API results only by default
uv run python scripts/run_scraper.py \
  --source bring_a_trailer \
  --mode backfill \
  --concurrent \
  --workers 3 \
  --bat-target-source models
```

CLI runs emit one structured line per request/page with outcome, status,
duration, raw item count, parsed lot count, skip counts, and source metadata.
The same data is committed immediately to `scrape_request_logs`, so the admin
console can show progress while a run is still active. BaT model pages also
record source-reported `items_total`, `page_current`, and `pages_total`; if a
model has more completed-result pages than the scraper fetched, the run records
a `bat_pagination_incomplete` anomaly.

Supported modes are `incremental` and `backfill`. The mode is recorded on each
scrape run and can be used by scrapers/checkpoint logic.

Concurrent BaT backfills use a single in-process queue, one database session per
worker, and one shared polite request limiter. Proxy/VPN fan-out is intentionally
not implemented; future proxy support should route through an approved outbound
proxy while preserving the same global limiter rather than bypassing source
rate limits or block responses.

Default schedule settings are nightly incremental at `15 3 * * *` and weekly
reconciliation at `30 4 * * 0`. Request logs are retained for 90 days by
default. Production-scale recurring runs should remain permission-first and stop
on block/rate-limit signals rather than trying to bypass them.

## Verification

```bash
cd backend
uv run ruff check app tests scripts alembic/versions
uv run pytest -q
uv run python -m compileall app scripts alembic/versions
uv run alembic upgrade head
git diff --check
```
