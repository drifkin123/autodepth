# Design: Richer Listing Data Collection & Listing History Tracking

**Date:** 2026-04-02  
**Status:** Approved

## Context

The current scraper pipeline collects ~8–12 fields per listing but leaves significant data on the table:
- Make/model/trim are parsed from titles but never stored as columns — filtering requires a JOIN to the `cars` catalog
- Cars.com listings seen on repeat scrapes are silently skipped — no days-on-market tracking, no price-reduction history
- Several high-value fields (VIN, transmission, no-reserve flag, body style, fuel type, location) are available in raw source data but discarded
- Listings for cars not in the `cars` catalog are dropped entirely, even though price/mileage data is fully scraped

This design promotes all available structured fields to typed columns, adds listing snapshot history, and decouples listing storage from the car catalog.

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Make/model/trim storage | Denormalized columns on `vehicle_sales` | Faster filtering, no JOIN required, works for unmatched listings |
| Unmatched listings | Save with `car_id = NULL` | Collect everything; catalog stays hand-curated for depreciation modeling |
| Re-scraped listings | Upsert + snapshot | Enables days-on-market and price reduction tracking |
| Catalog scope | Remains hand-curated | Catalog entries drive depreciation model, watchlist, deep-dive pages |

---

## 1. Schema Changes

### 1a. `vehicle_sales` — new columns

| Column | Type | Nullable | Source | Notes |
|---|---|---|---|---|
| `make` | TEXT | YES | All sources | Denormalized from matched Car or parsed from raw data |
| `model` | TEXT | YES | All sources | Denormalized from matched Car or parsed from raw data |
| `trim` | TEXT | YES | All sources | Denormalized from matched Car or parsed from raw data |
| `vin` | TEXT | YES | Cars.com | Vehicle Identification Number |
| `transmission` | TEXT | YES | C&B, Cars.com | e.g. "Manual", "PDK", "Automatic" |
| `no_reserve` | BOOLEAN | YES | BaT, C&B | True = no reserve auction |
| `body_style` | TEXT | YES | Cars.com | e.g. "Coupe", "Convertible" |
| `fuel_type` | TEXT | YES | Cars.com | e.g. "Gasoline", "Electric" |
| `location` | TEXT | YES | BaT (country), C&B (city) | Seller/auction location |
| `stock_type` | TEXT | YES | Cars.com | "used" / "new" / "cpo" |
| `last_seen_at` | TIMESTAMPTZ | YES | Listing sources | Updated each time the listing is re-scraped |

### 1b. `vehicle_sales` — column modifications

- `car_id` → make nullable (currently `NOT NULL`). Listings for uncatalogued cars are saved with `car_id = NULL`.

### 1c. New table: `listing_snapshots`

Tracks each observation of an active (unsold) listing across scrape runs. Enables:
- Days on market: `MAX(scraped_at) - MIN(scraped_at)` per `source_url`
- Price reduction history: see asking_price over time per listing

```sql
listing_snapshots (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_url    TEXT NOT NULL,
  scraped_at    TIMESTAMPTZ NOT NULL,
  asking_price  INT,
  mileage       INT
)
-- Index: (source_url, scraped_at)
```

Only listing-type sources write snapshots (Cars.com). Auction sources are immutable once sold.

---

## 2. `ScrapedListing` Dataclass

**File:** `backend/app/scrapers/base.py`

Add fields:
```python
make: str | None = None
model: str | None = None
trim: str | None = None
vin: str | None = None
transmission: str | None = None
no_reserve: bool | None = None
body_style: str | None = None
fuel_type: str | None = None
location: str | None = None
stock_type: str | None = None
```

---

## 3. Parser Updates

### `bat_parser.py`
Extract from JSON item:
- `no_reserve` ← `item.get("noreserve", False)`
- `location` ← `item.get("country")` (e.g. "United States")

Make/model/trim sourced from the matched `Car` object in `save_listing()` (not parsed from title).

### `cars_and_bids_parser.py`
Extract from API response item:
- `transmission` ← `item.get("transmission")`
- `location` ← `item.get("location")`
- `no_reserve` ← `item.get("no_reserve", False)`
- `color` ← regex parse from `sub_title` (same approach as BaT)

Make/model/trim sourced from the matched `Car` object in `save_listing()`.

### `cars_com_parser.py`
Extract from structured JSON:
- `make` ← `item["make"]` (already present, just not in ScrapedListing)
- `model` ← `item["model"]`
- `trim` ← `item["trim"]`
- `vin` ← `item.get("vin")`
- `body_style` ← `item.get("bodyStyle")`
- `fuel_type` ← `item.get("fuelType")`
- `stock_type` ← normalize `item.get("stockType")`: `"Used"→"used"`, `"New"→"new"`, `"Certified"→"cpo"`

---

## 4. `BaseScraper` Logic Changes

**File:** `backend/app/scrapers/base.py`

### `save_listing()` — populate make/model/trim

After car match:
```python
# Prefer listing's own parsed make/model/trim (Cars.com structured data)
# Fall back to matched Car's values
sale.make = listing.make or (car.make if car else None)
sale.model = listing.model or (car.model if car else None)
sale.trim = listing.trim or (car.trim if car else None)
```

`car_id` is set if matched, `NULL` otherwise. No longer a hard gate.

### New: `upsert_listing()` — replaces dedup check for active listings

For `is_sold=False` (listing-type sources):
1. Query `vehicle_sales` by `source_url`
2. **If exists:** update `last_seen_at = now`, `asking_price`, `mileage`; insert a `listing_snapshots` row
3. **If not exists:** insert new `vehicle_sales` row + first `listing_snapshots` row

For `is_sold=True` (auction sources): keep existing dedup behavior (skip if source_url exists).

---

## 5. Alembic Migrations

Two migrations in sequence:

**Migration 1 — Enrich `vehicle_sales`:**
- Add `make`, `model`, `trim`, `vin`, `transmission`, `no_reserve`, `body_style`, `fuel_type`, `location`, `stock_type`, `last_seen_at` columns
- Alter `car_id` to be nullable
- Add index on `(make, model, trim)` for filtering

**Migration 2 — Create `listing_snapshots`:**
- Create table with `id`, `source_url`, `scraped_at`, `asking_price`, `mileage`
- Add index on `(source_url, scraped_at)`

---

## 6. Test Updates

- Update `test_bat_scraper.py`: assert `no_reserve` and `location` are populated from fixture
- Update `test_cars_and_bids_scraper.py`: assert `transmission`, `location`, `no_reserve` populated
- Update `test_cars_com_scraper.py`: assert `make`, `model`, `trim`, `vin`, `body_style`, `fuel_type`, `stock_type` populated
- Add test in `test_base_scraper.py`: upsert behavior — second call with same `source_url` (is_sold=False) updates the row and writes a snapshot

---

## Files to Modify

| File | Change |
|---|---|
| `backend/app/scrapers/base.py` | Add fields to `ScrapedListing`; update `save_listing()`; add `upsert_listing()` |
| `backend/app/scrapers/bat_parser.py` | Extract `no_reserve`, `location` |
| `backend/app/scrapers/cars_and_bids_parser.py` | Extract `transmission`, `location`, `no_reserve`, `color` |
| `backend/app/scrapers/cars_com_parser.py` | Extract `make`, `model`, `trim`, `vin`, `body_style`, `fuel_type`, `stock_type` |
| `backend/app/models/vehicle_sale.py` | Add new columns; make `car_id` nullable |
| `backend/alembic/versions/` | Two new migration files |
| `backend/tests/test_bat_scraper.py` | Assert new fields |
| `backend/tests/test_cars_and_bids_scraper.py` | Assert new fields |
| `backend/tests/test_cars_com_scraper.py` | Assert new fields |
| `backend/tests/test_base_scraper.py` | Add upsert behavior test |

## New Files

| File | Purpose |
|---|---|
| `backend/app/models/listing_snapshot.py` | SQLAlchemy model for `listing_snapshots` |
| `backend/alembic/versions/<hash>_enrich_vehicle_sales.py` | Migration 1 |
| `backend/alembic/versions/<hash>_create_listing_snapshots.py` | Migration 2 |

---

## Verification

1. Run migrations: `alembic upgrade head` — confirm both apply without error
2. Run test suite: `pytest backend/tests/` — all scraper tests pass
3. Trigger a test scrape and inspect DB:
   - `SELECT make, model, trim, vin, transmission, no_reserve FROM vehicle_sales LIMIT 10;`
   - Re-run scraper for Cars.com, check `listing_snapshots` has rows and `last_seen_at` updated
   - Check a listing with no catalog match has `car_id = NULL` and make/model/trim populated
