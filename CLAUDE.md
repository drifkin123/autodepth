# CLAUDE.md — AutoDepth Project Brief

## What This App Is

**AutoDepth** is a personal car market intelligence dashboard for enthusiasts tracking performance and exotic cars. It aggregates real auction sale data, models depreciation curves, and helps users decide *when* to buy the car they want at the best possible price.

Target cars: Porsche, Ferrari, Lamborghini, McLaren, Audi (R8, RS models), Mercedes-AMG GT, Corvette C8 Z06, Lotus, and similar performance/exotic vehicles from the last 20 years.

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

```
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
│   │   │   └── bring_a_trailer.py
│   │   └── db.py
│   ├── alembic/               ← DB migrations
│   ├── pyproject.toml
│   └── .env.example
└── docker-compose.yml         ← local Postgres + TimescaleDB for dev
```

---

## Database Schema (Core Tables)

```sql
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

-- Individual auction sale records (TimescaleDB hypertable on sold_at)
auction_sales (
  id UUID PRIMARY KEY,
  car_id UUID REFERENCES cars(id),
  source TEXT,         -- "bring_a_trailer", "cars_and_bids", "rm_sotheby"
  source_url TEXT,
  year INT,            -- model year of the specific car sold
  mileage INT,
  color TEXT,
  sold_price INT,      -- in USD
  sold_at TIMESTAMPTZ, -- partition key
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
```

---

## API Routes

```
GET  /api/cars                          list all cars (filterable by make, model, year)
GET  /api/cars/:id                      car detail + metadata
GET  /api/cars/:id/sales                auction sales history (paginated, filterable)
GET  /api/cars/:id/price-history        aggregated price over time (monthly avg)
GET  /api/cars/:id/prediction           depreciation curve + buy window recommendation
GET  /api/compare?ids=id1,id2,id3       compare multiple cars (price curves, stats)
GET  /api/watchlist                     user's watchlist (auth required)
POST /api/watchlist                     add car to watchlist (auth required)
DELETE /api/watchlist/:id               remove from watchlist (auth required)
POST /api/admin/scrape/trigger          manually trigger a scrape run (admin only)
```

All responses use camelCase JSON. Errors follow `{ error: string, detail?: string }`.

---

## Key Features & Pages

### 1. Garage (Watchlist Dashboard) — `/`
- Grid of watched cars with current estimated value, delta from when added, and buy window indicator
- "Buy window" badge: 🔴 Depreciating fast / 🟡 Near floor / 🟢 At floor / ⬆️ Appreciating
- Quick-add search to add a car to the garage

### 2. Car Deep-Dive — `/cars/:id`
- Hero: make/model/trim, production count, engine type, original MSRP
- Price history chart (all auction results plotted, with trend line overlay)
- Depreciation curve with forward prediction (confidence band shaded)
- "Best time to buy" callout with plain-English explanation
- Recent auction sales table (price, mileage, color, date, link to source)
- Key insights panel: e.g. "This is a naturally aspirated Ferrari — values are rising, not falling"

### 3. Compare — `/compare`
- Select 2–4 cars from search
- Overlaid depreciation curves on a single chart (each car a different color)
- Side-by-side stats table: current avg price, 1yr change, 3yr projection, production count, rarity score
- "Which is the better buy right now?" AI-generated summary (call Claude API)

### 4. Market — `/market`
- Recent notable auction results across all tracked cars
- Trending: biggest movers this month (up and down)
- "On the radar" — cars approaching their predicted price floor

---

## Depreciation Model (Python — `services/depreciation.py`)

Use a curve-fitting approach on the auction sales data:

1. **Data prep**: filter sales by `car_id`, normalize mileage (use age if mileage unavailable), remove outliers (>2 std dev from monthly mean)
2. **Curve fitting**: fit an exponential decay curve `P(t) = P0 * e^(-λt) + C` where C is the floor price
3. **Floor detection**: C is estimated as a percentage of original MSRP, adjusted for:
   - Production scarcity (lower production count → higher floor)
   - Natural aspiration premium (add 15–25% floor multiplier for NA exotics)
   - Current market trend (trailing 6-month slope)
4. **Forward projection**: extend curve 36 months, generate confidence band (±1 std dev of residuals)
5. **Buy window**: flag the predicted date when the curve slope flattens (d²P/dt² ≈ 0) as "optimal buy"

Store predictions in `price_predictions` table. Re-run model nightly after scrape.

---

## Scraper (Python — `scrapers/bring_a_trailer.py`)

- Use Playwright (async) to scrape completed auction results from Bring a Trailer
- Target URL pattern: `bringatrailer.com/listing-results/?s={search_term}&sold=1`
- Extract: final bid, year, mileage, title (parse make/model/trim), sold date, listing URL
- Match to `cars` table via fuzzy make/model/trim matching
- Deduplicate on `source_url` before inserting
- Run on a schedule: nightly at 2am UTC via Railway cron job
- Log all scrape runs to a `scrape_logs` table (start time, records found, records inserted, errors)

---

## Seed Data

Populate `cars` table with these to start. Add more as needed.

**Porsche**
- 911 GT3 (996, 997, 991, 992 generations)
- 911 GT3 RS (997, 991, 992)
- 911 Turbo S (991, 992)
- Cayman GT4 (981, 982)
- 918 Spyder

**Ferrari**
- 458 Italia / Spider / Speciale
- 488 GTB / Pista
- F8 Tributo / Spider
- SF90 Stradale
- Roma

**Lamborghini**
- Huracán LP610-4 / EVO / STO
- Huracán Performante
- Urus (S, Performante)
- Aventador S / SVJ

**McLaren**
- 570S / 600LT
- 720S
- 765LT
- Artura

**Mercedes-AMG**
- AMG GT / GT S / GT R
- AMG GT 63 S (4-door)

**Audi**
- R8 V10 (gen 1, gen 2)
- R8 V10 Performance
- RS6 Avant (C8)
- RS7

**Chevrolet**
- Corvette C8 Stingray
- Corvette C8 Z06
- Corvette C8 E-Ray

**Lotus**
- Emira V6
- Evora GT
- Exige S / Cup 430

---

## Code Conventions

- **Python**: type hints everywhere, async/await throughout, Pydantic v2 for request/response schemas
- **TypeScript**: strict mode on, no `any`, all API responses typed via `packages/shared/types.ts`
- **Components**: functional only, no class components
- **Styling (web)**: Tailwind CSS — dark theme by default, accent color `#E8D5A3` (warm gold)
- **Error handling**: all API calls wrapped in try/catch, errors surfaced to user via toast notifications
- **Env vars**: never hardcode secrets. All secrets via `.env` (backend) and Vite's `VITE_` prefix (frontend). See `.env.example`.
- **Git**: conventional commits (`feat:`, `fix:`, `chore:`, `data:` for seed/migration changes)

---

## Design Direction

**Aesthetic**: Dark, refined, automotive. Think car configurator meets Bloomberg terminal.
- Background: near-black `#0A0A0A`
- Surface: `#141414` cards
- Accent: warm gold `#E8D5A3` for highlights, CTAs, and key data points
- Text: `#F5F5F5` primary, `#888` secondary
- Charts: multi-color with high contrast against dark background
- Typography: something with character — not Inter. Consider Geist, DM Sans, or a sharp grotesque.
- Motion: subtle. Chart lines animate in on load. Cards fade up on entry. No gratuitous animation.

The app should feel like it was built by someone who actually loves cars, not a generic SaaS dashboard.

---

## Environment Variables

```bash
# backend/.env.example
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/autodepth
CLERK_SECRET_KEY=
ANTHROPIC_API_KEY=        # for compare page AI summary
SCRAPE_SCHEDULE=0 2 * * * # nightly 2am UTC

# apps/web/.env.example
VITE_API_BASE_URL=http://localhost:8000
VITE_CLERK_PUBLISHABLE_KEY=
```

---

## Build Order (Follow This Sequence)

1. **Repo + tooling setup**: monorepo scaffold, pnpm workspaces, shared types package, docker-compose for local Postgres+TimescaleDB
2. **Database + migrations**: all core tables, Alembic setup, seed the `cars` catalog
3. **BaT scraper**: Playwright scraper → parse → insert into `auction_sales`. Verify real data flowing.
4. **Depreciation model**: curve fitting service, populate `price_predictions`, write unit tests
5. **FastAPI backend**: all API routes, Clerk JWT middleware, connect to DB
6. **Web frontend**: Vite + React scaffold, Tailwind dark theme, Clerk auth, API client
7. **Garage page**: watchlist UI, buy window badges
8. **Car deep-dive page**: price history chart, depreciation curve, recent sales table
9. **Compare page**: multi-car chart overlay, stats table, Claude API summary
10. **Market page**: recent auctions feed, trending movers
11. **Expo mobile app**: port core pages using Expo Router, Victory Native charts
12. **Deploy**: Railway (backend), Vercel (web), Expo EAS (mobile)

---

## What Success Looks Like (MVP)

A logged-in user can:
- Search for any tracked car and add it to their garage
- See a real price history chart backed by actual BaT auction data
- See a depreciation curve with a projected buy window
- Compare 2–4 cars side by side on overlaid curves
- View recent auction results with links to the original listings
- Get a plain-English "should I buy now or wait?" summary on the compare page
