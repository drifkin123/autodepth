# CLAUDE.md — AutoDepth Project Brief & System Directives

## System & Agent Directives
You are an expert software engineer operating within this monorepo. You must strictly adhere to the following operational laws:
1. **Scout First:** Before writing or modifying any code, inspect the file structure, read relevant `package.json` or dependency files, and review existing shared types/utilities. Do not hallucinate dependencies or utilities.
2. **Branch Enforcement:** Never commit directly to the `main` branch. Always create a new feature branch for your current task (e.g., `feature/add-watchlist-ui` or `step/3-bat-scraper`).
3. **Pull Requests:** When a task is complete, prepare a pull request summary. Do not attempt to merge the branch yourself.
4. **Context Isolation:** Only ingest and modify the files strictly necessary for the current task. Keep your working context lean.

## Architecture & Quality Rules
- **Modularity:** Keep files and components small and focused. No file should exceed 200 lines of code without a strong justification.
- **Separation of Concerns:** - UI components must remain strictly presentational.
  - Business logic, state manipulation, and data fetching must be extracted into separate hooks, services, or utility modules.
  - API routes must delegate processing to dedicated service layers and never handle complex logic directly inside the router.
- **Single Source of Truth:** Rely on the shared types defined in the monorepo for all cross-boundary communication. Never redefine a type that already exists in the shared package.

## Testing Mandates
- **Test-Driven Mentality:** Every new feature, utility function, or API endpoint must be accompanied by a corresponding test file.
- **Definition of Done:** A task is never considered complete until the relevant test suite runs and passes locally. Do not ask for task approval if tests are failing.
- **Coverage:** Prioritize testing core business logic (e.g., the depreciation model, data parsing) and boundary layers (e.g., API inputs/outputs) over trivial UI rendering.

## Style & Syntax Guidelines
- **Strict Typing:** Strict type-checking is enforced. Do not use generic, loose, or wildcard types (e.g., `any`). If a type is unknown, define it accurately.
- **Naming Conventions:** Use descriptive, unabbreviated variable and function names. A function name must clearly describe its action (e.g., `calculateDepreciationCurve` instead of `calcCurve`).
- **Error Handling:** All external calls, database queries, and data parsing must be wrapped in appropriate `try/catch` or error-handling blocks. Fail gracefully and surface readable error messages.
- **Commits:** Use conventional commit messages (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`).

---

## What This App Is
**AutoDepth** is a personal car market intelligence dashboard for enthusiasts tracking performance and exotic cars. It aggregates real vehicle sales data from auctions, dealerships, and listing platforms, models depreciation curves, and helps users decide when to buy the targeted vehicle at the optimal price.

Target vehicles include: Porsche, Ferrari, Lamborghini, McLaren, Audi (R8, RS models), Mercedes-AMG GT, Corvette C8 Z06, Lotus, and similar performance/exotic vehicles from the last 20 years.

This is a solo developer project. Prioritize clarity, maintainability, and shipping over abstraction and over-engineering.

---

## Stack
| Layer | Choice |
|---|---|
| Frontend (web) | React 18 + Vite |
| Frontend (mobile) | Expo (React Native) with Expo Router |
| Shared logic | React hooks + Zustand for state |
| Charts (web) | Recharts |
| Charts (mobile) | Victory Native |
| Backend | FastAPI (Python 3.11+) |
| Database | PostgreSQL 15 with TimescaleDB extension |
| ORM | SQLAlchemy 2.0 (async) with Alembic migrations |
| Scraping | Playwright (async, scheduled) |
| Auth | Clerk (JWT passed to FastAPI) |
| Hosting | Railway (backend + DB), Vercel (web frontend), Expo EAS (mobile) |
| Package manager | pnpm (frontend), uv (Python backend) |

---

## Monorepo Structure
```text
autodepth/
├── CLAUDE.md                  ← you are here
├── apps/
│   ├── web/                   ← React + Vite web app
│   │   ├── src/
│   │   │   ├── components/
│   │   │   ├── pages/
│   │   │   ├── hooks/
│   │   │   ├── store/         ← Zustand stores
│   │   │   └── lib/           ← API client, utils
│   │   └── vite.config.ts
│   └── mobile/                ← Expo app
│       ├── app/               ← Expo Router file-based routes
│       ├── components/
│       └── hooks/
├── packages/
│   └── shared/                ← shared TypeScript types, constants, helpers
│       └── src/
│           ├── types.ts       ← Car, Auction, PricePoint, WatchlistItem, etc.
│           └── constants.ts   ← supported makes/models, trim lists
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/               ← route handlers
│   │   │   ├── cars.py
│   │   │   ├── auctions.py
│   │   │   ├── watchlist.py
│   │   │   └── predictions.py
│   │   ├── models/            ← SQLAlchemy models
│   │   ├── services/          ← business logic (depreciation model, etc.)
│   │   │   ├── depreciation.py
│   │   │   └── scraper.py
│   │   ├── scrapers/          ← per-source scrapers
│   │   │   ├── base.py        ← shared scraper interface
│   │   │   ├── bring_a_trailer.py
│   │   │   ├── cars_and_bids.py
│   │   │   ├── cars_com.py
│   │   │   └── rm_sothebys.py
│   │   └── db.py
│   ├── alembic/               ← DB migrations
│   ├── pyproject.toml
│   └── .env.example
└── docker-compose.yml         ← local Postgres + TimescaleDB for dev
Database Schema (Core Tables)
SQL
-- Static catalog of supported cars
cars (
  id UUID PRIMARY KEY,
  make TEXT,           -- e.g. "Porsche"
  model TEXT,          -- e.g. "911"
  trim TEXT,           -- e.g. "GT3 RS"
  year_start INT,
  year_end INT,        -- NULL if still in production
  production_count INT,-- total units made (NULL if unknown)
  engine TEXT,         -- e.g. "4.0L NA Flat-6"
  is_naturally_aspirated BOOLEAN,
  msrp_original INT,   -- original MSRP in USD
  notes TEXT,          -- e.g. "Last NA GT3 before PDK-only mandate"
  created_at TIMESTAMPTZ
)

-- Individual vehicle sale/listing records (TimescaleDB hypertable on listed_at)
vehicle_sales (
  id UUID PRIMARY KEY,
  car_id UUID REFERENCES cars(id),
  source TEXT,         -- "bring_a_trailer", "cars_and_bids", "rm_sotheby",
                       --   "cars_com", "dealer" (generic dealership), "private_seller"
  source_url TEXT,
  sale_type TEXT,      -- "auction", "listing", "dealer", "private"
  year INT,            -- model year of the specific car sold/listed
  mileage INT,
  color TEXT,
  asking_price INT,    -- original listed/asking price in USD (always present)
  sold_price INT,      -- final confirmed sale price in USD (NULL if not sold)
                       -- NOTE: asking vs sold can diverge significantly —
                       -- use sold_price for depreciation modeling,
                       -- asking_price only as a secondary market signal
  is_sold BOOLEAN,     -- true = confirmed sale, false = active/expired listing
  listed_at TIMESTAMPTZ,  -- partition key; when the listing appeared
  sold_at TIMESTAMPTZ,    -- NULL if not a confirmed sale
  condition_notes TEXT,
  options JSONB,       -- e.g. {"pdk": true, "sport_chrono": true}
  raw_data JSONB       -- full scraped payload for reprocessing
)

-- Forward-looking price predictions per car
price_predictions (
  id UUID PRIMARY KEY,
  car_id UUID REFERENCES cars(id),
  model_version TEXT,
  predicted_for DATE,
  predicted_price INT,
  confidence_low INT,
  confidence_high INT,
  generated_at TIMESTAMPTZ
)

-- User watchlists (requires Clerk user_id)
watchlist_items (
  id UUID PRIMARY KEY,
  user_id TEXT,        -- Clerk user_id
  car_id UUID REFERENCES cars(id),
  target_price INT,    -- user's budget / target buy price
  notes TEXT,
  added_at TIMESTAMPTZ
)
API Routes
Plaintext
GET  /api/cars                          list all cars (filterable by make, model, year)
GET  /api/cars/:id                      car detail + metadata
GET  /api/cars/:id/sales                vehicle sales/listings history (paginated, filterable by source, sale_type, is_sold)
GET  /api/cars/:id/price-history        aggregated price over time (monthly avg)
GET  /api/cars/:id/prediction           depreciation curve + buy window recommendation
GET  /api/compare?ids=id1,id2,id3       compare multiple cars (price curves, stats)
GET  /api/watchlist                     user's watchlist (auth required)
POST /api/watchlist                     add car to watchlist (auth required)
DELETE /api/watchlist/:id               remove from watchlist (auth required)
POST /api/admin/scrape/trigger          manually trigger a scrape run (admin only)
All responses use camelCase JSON. Errors follow { error: string, detail?: string }.

Key Features & Pages
1. Garage (Watchlist Dashboard) — /
Grid of watched cars with current estimated value, delta from when added, and buy window indicator.

"Buy window" badge designations: Depreciating fast / Near floor / At floor / Appreciating.

Quick-add search to add a car to the garage.

2. Car Deep-Dive — /cars/:id
Hero: make/model/trim, production count, engine type, original MSRP.

Price history chart (all auction results plotted, with trend line overlay).

Depreciation curve with forward prediction (confidence band shaded).

"Best time to buy" callout with plain-English explanation.

Recent sales/listings table (price, mileage, color, source type, date, link to source).

Key insights panel: e.g., "This is a naturally aspirated Ferrari — values are rising, not falling".

3. Compare — /compare
Select 2–4 cars from search.

Overlaid depreciation curves on a single chart (each car a different color).

Side-by-side stats table: current avg price, 1yr change, 3yr projection, production count, rarity score.

"Which is the better buy right now?" AI-generated summary (via Claude API).

4. Market — /market
Recent notable auction results across all tracked cars.

Trending: biggest movers this month (up and down).

"On the radar" — cars approaching their predicted price floor.

Depreciation Model (Python — services/depreciation.py)
Use a curve-fitting approach on the auction sales data:

Data prep: filter vehicle_sales by car_id; use sold_price (confirmed sales only) as the primary input for curve fitting; asking_price from listing sources can inform a separate "market ask" overlay but must never be mixed into the depreciation model directly — asking and sold prices diverge significantly and conflating them will skew the curve. Normalize mileage (use age if mileage unavailable), remove outliers (>2 std dev from monthly mean).

Curve fitting: fit an exponential decay curve P(t) = P0 * e^(-λt) + C where C is the floor price.

Floor detection: C is estimated as a percentage of original MSRP, adjusted for:

Production scarcity (lower production count → higher floor).

Natural aspiration premium (add 15–25% floor multiplier for NA exotics).

Current market trend (trailing 6-month slope).

Forward projection: extend curve 36 months, generate confidence band (±1 std dev of residuals).

Buy window: flag the predicted date when the curve slope flattens (d²P/dt² ≈ 0) as "optimal buy".

Store predictions in price_predictions table. Re-run model nightly after scrape.

Scrapers (Python — scrapers/)
All scrapers use Playwright (async), share a common base interface, and write into vehicle_sales. Each scraper is its own file under scrapers/.

Data hierarchy — important:
Confirmed auction sale prices are ground truth for the depreciation model. Dealer/listing asking prices are secondary signal only (never mixed into curve fitting). Prioritize auction sources.

Why no AutoTrader: AutoTrader runs behind Cloudflare with aggressive bot detection. Scraping it reliably requires paid residential proxies and is not worth the fragility for data that is secondary signal anyway. MarketCheck API was also evaluated and rejected — it does not cover BaT/C&B/RM auction data at all, its "sold" data is just dealer listings going dark (no confirmed prices), and the free tier is limited to a 100-mile radius. Not suitable for national exotic car market tracking.

Common contract for all scrapers:

Deduplicate on source_url before inserting.

Set sale_type and is_sold appropriately per source.

Match to cars table via fuzzy make/model/trim matching.

Log all scrape runs to a scrape_logs table (start time, source, records found, records inserted, errors).

Run on a schedule: nightly at 2am UTC via Railway cron job.

Sources (priority order):
| File | Source | Type | Data value |
|---|---|---|---|
| bring_a_trailer.py | Bring a Trailer | auction | Primary Signal: Confirmed hammer prices — primary model input |
| cars_and_bids.py | Cars & Bids | auction | Primary Signal: Confirmed hammer prices — primary model input |
| rm_sothebys.py | RM Sotheby's | auction | Primary Signal: High-end confirmed sales — primary model input |
| cars_com.py | Cars.com | listing | Secondary Signal: Asking prices only; sold_price=NULL, is_sold=false |

Extract fields (all sources): price/bid, year, mileage, title (parse make/model/trim), date, listing URL, color (if available), condition notes (if available).

Design Direction
Aesthetic: Dark, refined, automotive. Think car configurator meets Bloomberg terminal.

Background: near-black #0A0A0A

Surface: #141414 cards

Accent: warm gold #E8D5A3 for highlights, CTAs, and key data points

Text: #F5F5F5 primary, #888 secondary

Charts: multi-color with high contrast against dark background

Typography: something with character — not Inter. Consider Geist, DM Sans, or a sharp grotesque.

Motion: subtle. Chart lines animate in on load. Cards fade up on entry. No gratuitous animation.

The app should feel like it was built by someone who actually loves cars, not a generic SaaS dashboard.

Environment Variables
Bash
# backend/.env.example
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/autodepth
CLERK_SECRET_KEY=
ANTHROPIC_API_KEY=        # for compare page AI summary
SCRAPE_SCHEDULE=0 2 * * * # nightly 2am UTC

# apps/web/.env.example
VITE_API_BASE_URL=http://localhost:8000
VITE_CLERK_PUBLISHABLE_KEY=
Build Order (Strict Execution Sequence)
Repo + tooling setup: monorepo scaffold, pnpm workspaces, shared types package, docker-compose for local Postgres+TimescaleDB.

Database + migrations: all core tables, Alembic setup, seed the cars catalog.

BaT scraper: Playwright scraper → parse → insert into auction_sales. Verify real data flowing.

Depreciation model: curve fitting service, populate price_predictions, write unit tests.

FastAPI backend: all API routes, Clerk JWT middleware, connect to DB.

Web frontend: Vite + React scaffold, Tailwind dark theme, Clerk auth, API client.

Garage page: watchlist UI, buy window badges.

Car deep-dive page: price history chart, depreciation curve, recent sales table.

Compare page: multi-car chart overlay, stats table, Claude API summary.

Market page: recent auctions feed, trending movers.

Expo mobile app: port core pages using Expo Router, Victory Native charts.

Deploy: Railway (backend), Vercel (web), Expo EAS (mobile).

What Success Looks Like (MVP)
A logged-in user can:

Search for any tracked car and add it to their garage.

See a real price history chart backed by actual BaT auction data.

See a depreciation curve with a projected buy window.

Compare 2–4 cars side by side on overlaid curves.

View recent auction results with links to the original listings.

Get a plain-English "should I buy now or wait?" summary on the compare page.