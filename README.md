# AutoDepth

Personal car market intelligence dashboard for tracking depreciation curves and buy windows on performance and exotic cars.

---

## Table of Contents

- [Stack](#stack)
- [Prerequisites](#prerequisites)
- [Local Development Setup](#local-development-setup)
- [Running the Backend](#running-the-backend)
- [Populating Data](#populating-data)
- [API Reference](#api-reference)
- [Admin Dashboard](#admin-dashboard)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.11+), SQLAlchemy 2.0 async, Alembic |
| Database | PostgreSQL 15 + TimescaleDB |
| Scraping | Playwright (async) |
| Auth | Clerk JWT |
| Frontend (web) | React 18 + Vite + Tailwind |
| Frontend (mobile) | Expo (React Native) |
| Package managers | `uv` (Python), `pnpm` (frontend) |

---

## Prerequisites

- **Docker** (for local Postgres + TimescaleDB)
- **Python 3.11+** with [`uv`](https://docs.astral.sh/uv/) installed
- **Node.js 20+** with [`pnpm`](https://pnpm.io/) installed (for frontend, when you get there)

---

## Local Development Setup

### 1. Clone and navigate

```sh
git clone <repo-url>
cd autodepth
```

### 2. Start the database

```sh
docker compose up -d
```

This starts a TimescaleDB-enabled Postgres instance on port `5432` with credentials `autodepth / autodepth`.

### 3. Install Python dependencies

```sh
cd backend
uv sync
```

### 4. Configure environment variables

```sh
cp .env.example .env
```

The defaults work for local dev with no Clerk or Anthropic keys. Edit `.env` if you have them:

```sh
# backend/.env
DATABASE_URL=postgresql+asyncpg://autodepth:autodepth@localhost:5432/autodepth
CLERK_SECRET_KEY=        # optional for local dev
CLERK_JWKS_URL=          # optional for local dev
ANTHROPIC_API_KEY=       # optional — needed for compare page AI summary
ADMIN_SECRET=            # optional — defaults to "dev" if unset
```

> **Auth in local dev:** If `CLERK_JWKS_URL` is not set, all auth-protected endpoints accept any request and return `user_id = "dev_user"`. No Clerk account needed locally.

> **Admin secret in local dev:** If `ADMIN_SECRET` is not set, the password for the admin dashboard is just `dev`.

### 5. Run database migrations

```sh
# from backend/
uv run alembic upgrade head
```

### 6. Install Playwright browsers

```sh
uv run playwright install chromium
```

---

## Running the Backend

```sh
# from backend/
uv run uvicorn app.main:app --reload
```

Server starts at `http://localhost:8000`.

- **API docs (Swagger):** `http://localhost:8000/docs`
- **Health check:** `http://localhost:8000/health`

---

## Populating Data

Data must be populated in order: seed the car catalog first, then scrape, then run the depreciation model.

### Step 1 — Seed the car catalog

Inserts the ~43 supported cars (Porsche, Ferrari, Lamborghini, McLaren, etc.) into the `cars` table.

```sh
# from backend/
uv run python scripts/seed_cars.py
```

This is idempotent — re-running it skips cars that already exist.

### Step 2 — Run the scrapers

Scrapes confirmed sale data from Bring a Trailer (and other sources as they're added) and inserts records into `vehicle_sales`.

**Option A — via script (no server needed, recommended for first-time setup):**

```sh
# Run all configured scrapers
uv run python scripts/run_scraper.py

# Run a specific source only
uv run python scripts/run_scraper.py --source bring_a_trailer
```

**Option B — via API (server must be running):**

```sh
curl -X POST "http://localhost:8000/api/admin/scrape/trigger?token=dev"
```

The API option runs the scrape as a background job and returns immediately (`202 Accepted`). Follow progress in the [admin dashboard](#admin-dashboard) or via the WebSocket stream.

Each run logs to the `scrape_logs` table (start time, records found/inserted, any errors).

### Step 3 — Run the depreciation model

Fits exponential decay curves to the scraped auction data and writes 36-month forward predictions into `price_predictions`.

**Option A — via script:**

```sh
# Run for all cars
uv run python scripts/run_depreciation.py

# Run for a single car (use the UUID from the cars table)
uv run python scripts/run_depreciation.py --car-id <uuid>
```

**Option B — via API:**

```sh
curl -X POST "http://localhost:8000/api/admin/depreciation/trigger?token=dev"
```

The depreciation model runs automatically after every scrape triggered via the admin trigger endpoint.

---

## API Reference

All responses use camelCase JSON. Error responses: `{ "error": "...", "detail": "..." }`.

Interactive docs are available at `http://localhost:8000/docs` when the server is running.

### Cars

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/cars` | List all cars. Filter by `?make=Porsche`, `?model=911` |
| `GET` | `/api/cars/{id}` | Car detail and metadata |
| `GET` | `/api/cars/{id}/sales` | Vehicle sales/listing history. Paginated. Filter by `?source=bring_a_trailer`, `?sale_type=auction`, `?is_sold=true`. |
| `GET` | `/api/cars/{id}/price-history` | Monthly aggregated price history (avg sold price, avg asking price, counts) |

### Predictions & Comparison

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/cars/{id}/prediction` | Depreciation curve, 36-month forward predictions, and buy window status |
| `GET` | `/api/compare?ids=id1,id2` | Compare 2–4 cars: overlaid price histories, stats, and AI-generated buy recommendation |

### Watchlist (auth required)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/watchlist` | Get current user's watchlist with enriched buy window status |
| `POST` | `/api/watchlist` | Add a car. Body: `{ "carId": "uuid", "targetPrice": 80000, "notes": "..." }` |
| `DELETE` | `/api/watchlist/{id}` | Remove an item from the watchlist |

### Admin

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/admin` | Admin dashboard HTML page |
| `GET` | `/api/admin/status` | Whether a scrape is currently running |
| `GET` | `/api/admin/logs` | Scrape run history. Filter by `?source=`, `?errors_only=true` |
| `POST` | `/api/admin/scrape/trigger` | Trigger a full scrape + depreciation refresh (background) |
| `POST` | `/api/admin/depreciation/trigger` | Re-run depreciation model only (background) |
| `WS` | `/api/admin/ws/stream` | WebSocket — stream real-time scrape events |

All admin endpoints require `?token=<ADMIN_SECRET>` (default: `dev` locally).

#### Buy window status values

| Status | Meaning |
|---|---|
| `depreciating_fast` | Curve is still dropping sharply; optimal buy date is in the future |
| `near_floor` | Within 30 days of predicted price floor |
| `at_floor` | At or below predicted floor — good time to buy |
| `appreciating` | Price is rising; values trending up |

---

## Admin Dashboard

Open `http://localhost:8000/api/admin` in a browser. Enter `dev` (or your `ADMIN_SECRET`) to sign in.

**Features:**
- **Live log feed** — real-time WebSocket stream showing scraper progress as it runs
- **Scrape history table** — last 50 runs with source, duration, records found/inserted, and status
- **Stats row** — total runs, last run time, records inserted, and error count
- **Trigger Scrape** — fires a full scrape + depreciation refresh; streams events live
- **Run Depreciation Model** — re-fits curves without re-scraping
- **WebSocket indicator** — shows connection state; auto-reconnects if dropped

To set a production secret:

```sh
# backend/.env
ADMIN_SECRET=your-strong-secret-here
```

---

## Running Tests

```sh
# from backend/
uv run pytest

# With coverage report
uv run pytest --cov=app tests/
```

Current test coverage: depreciation model unit tests (`tests/test_depreciation.py`). No database required — all tests use mocked models.

---

## Project Structure

```
autodepth/
├── docker-compose.yml          — local Postgres + TimescaleDB
├── apps/
│   ├── web/                    — React + Vite frontend (step 6+)
│   └── mobile/                 — Expo app (step 11+)
├── packages/
│   └── shared/                 — shared TypeScript types
└── backend/
    ├── .env.example
    ├── pyproject.toml
    ├── alembic/                 — database migrations
    │   └── versions/
    ├── scripts/
    │   ├── seed_cars.py         — populate the cars catalog
    │   ├── run_scraper.py       — manually run scrapers
    │   └── run_depreciation.py  — manually run the depreciation model
    ├── tests/
    │   └── test_depreciation.py
    └── app/
        ├── main.py              — FastAPI app + router registration
        ├── settings.py          — environment variable config
        ├── db.py                — SQLAlchemy engine + session factory
        ├── auth.py              — Clerk JWT middleware
        ├── broadcast.py         — async event broadcaster (scraper → WebSocket)
        ├── api/
        │   ├── cars.py          — car catalog + price history routes
        │   ├── predictions.py   — depreciation predictions + compare
        │   ├── watchlist.py     — user watchlist routes
        │   └── admin.py         — admin routes + dashboard
        ├── models/              — SQLAlchemy ORM models
        │   ├── car.py
        │   ├── vehicle_sale.py
        │   ├── price_prediction.py
        │   ├── watchlist.py
        │   └── scrape_log.py
        ├── services/
        │   ├── depreciation.py  — curve fitting + buy window logic
        │   └── scraper.py       — scraper orchestration
        └── scrapers/
            ├── base.py          — shared interface + DB persistence
            └── bring_a_trailer.py
```
