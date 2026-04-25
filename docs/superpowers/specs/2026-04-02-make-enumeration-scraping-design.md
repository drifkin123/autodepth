# Design: Make-Based Scraper Enumeration

**Date:** 2026-04-02  
**Status:** Draft

## Context

The current scrapers navigate to ~18–21 hardcoded make/model-specific URLs per platform (e.g., `bringatrailer.com/porsche/911-gt3/`). This means only the ~21 pre-selected exotic configurations are ever scraped.

The previous design decision to save all listings (car_id nullable) has no effect unless the scrapers actually *visit* pages outside the curated list. To collect all vehicles on each platform — including common makes like Honda or Toyota — the navigation strategy must change from model-specific lookups to make-level enumeration.

The constraint: paginating a flat "all listings" view hits instability problems (sort order shifts between runs, page limits, overlap). Enumerating by make solves this — each make has a bounded, stable result set.

---

## Approach: Enumerate All Makes Per Platform

Replace the hardcoded make/model URL lists in each scraper with a centralized makes configuration file. Each scraper iterates over its full makes list, fetching all pages per make.

---

## 1. Centralized Makes Configuration

**New file:** `backend/app/scrapers/makes.py`

Contains per-platform make slug/search-term mappings — one entry per make (~50 major makes). Scrapers import from here instead of maintaining their own hardcoded URL tuples.

Structure:
```python
# List of (key, human_label, platform_slug) per platform

BAT_MAKES: list[tuple[str, str, str]] = [
    ("acura",          "Acura",          "acura"),
    ("alfa-romeo",     "Alfa Romeo",     "alfa-romeo"),
    ("aston-martin",   "Aston Martin",   "aston-martin"),
    ("audi",           "Audi",           "audi"),
    ("bentley",        "Bentley",        "bentley"),
    ("bmw",            "BMW",            "bmw"),
    ("bugatti",        "Bugatti",        "bugatti"),
    ("buick",          "Buick",          "buick"),
    ("cadillac",       "Cadillac",       "cadillac"),
    ("chevrolet",      "Chevrolet",      "chevrolet"),
    ("chrysler",       "Chrysler",       "chrysler"),
    ("dodge",          "Dodge",          "dodge"),
    ("ferrari",        "Ferrari",        "ferrari"),
    ("fiat",           "Fiat",           "fiat"),
    ("ford",           "Ford",           "ford"),
    ("genesis",        "Genesis",        "genesis"),
    ("gmc",            "GMC",            "gmc"),
    ("honda",          "Honda",          "honda"),
    ("hyundai",        "Hyundai",        "hyundai"),
    ("infiniti",       "Infiniti",       "infiniti"),
    ("jaguar",         "Jaguar",         "jaguar"),
    ("jeep",           "Jeep",           "jeep"),
    ("kia",            "Kia",            "kia"),
    ("lamborghini",    "Lamborghini",    "lamborghini"),
    ("land-rover",     "Land Rover",     "land-rover"),
    ("lexus",          "Lexus",          "lexus"),
    ("lincoln",        "Lincoln",        "lincoln"),
    ("lotus",          "Lotus",          "lotus"),
    ("maserati",       "Maserati",       "maserati"),
    ("mazda",          "Mazda",          "mazda"),
    ("mclaren",        "McLaren",        "mclaren"),
    ("mercedes-benz",  "Mercedes-Benz",  "mercedes-benz"),
    ("mini",           "MINI",           "mini"),
    ("mitsubishi",     "Mitsubishi",     "mitsubishi"),
    ("nissan",         "Nissan",         "nissan"),
    ("pagani",         "Pagani",         "pagani"),
    ("porsche",        "Porsche",        "porsche"),
    ("ram",            "Ram",            "ram"),
    ("rolls-royce",    "Rolls-Royce",    "rolls-royce"),
    ("subaru",         "Subaru",         "subaru"),
    ("tesla",          "Tesla",          "tesla"),
    ("toyota",         "Toyota",         "toyota"),
    ("volkswagen",     "Volkswagen",     "volkswagen"),
    ("volvo",          "Volvo",          "volvo"),
    # ... extend as needed
]

# C&B and Cars.com variants follow same pattern with platform-specific slugs
CAB_MAKES: list[tuple[str, str, str]] = [...]
CARS_COM_MAKES: list[tuple[str, str, str]] = [...]
```

The `selected_keys` optional filter (already supported in all three scrapers) continues to work — useful for targeted re-scrapes or testing a single make.

---

## 2. BaT Scraper Changes

**Current navigation:** `bringatrailer.com/porsche/911-gt3/` (model-specific)  
**New navigation:** `bringatrailer.com/{make}/` (all models for that make)

BaT's make-level pages (e.g., `bringatrailer.com/porsche/`) embed the same `auctionsCompletedInitialData` JSON as model pages — the existing `extract_items_from_html()` parser already handles this structure. No parser changes needed.

Changes to `bring_a_trailer.py`:
- Replace `BAT_URLS` with `from app.scrapers.makes import BAT_MAKES`
- URL construction changes from `{make}/{model}` to `{make}` only
- No pagination change needed (make pages embed all auctions as JSON without pagination)

**Note:** BaT make-level URL behavior should be validated before implementation (a quick fetch of `bringatrailer.com/porsche/` to confirm the JSON structure is present).

---

## 3. Cars & Bids Scraper Changes

**Current navigation:** Search query = specific model string (e.g., "porsche 911 gt3")  
**New navigation:** Search query = make name only (e.g., "porsche")

This returns all C&B past auctions for that make across all models.

Changes to `cars_and_bids.py`:
- Replace `CAB_URLS` with `from app.scrapers.makes import CAB_MAKES`
- Search query = make name
- Increase `MAX_PAGES_PER_SEARCH` from `3` to `20` (C&B is a curated platform; 20 pages per make covers the catalog depth without excessive requests)

---

## 4. Cars.com Scraper Changes

**Current navigation:** `?makes[]=porsche&models[]=porsche-911&...` (make + model filter)  
**New navigation:** `?makes[]=porsche&...` (make-only filter, no model)

Dropping the model filter returns all listings for that make. Cars.com listings for common makes (Honda, Toyota) can number in the thousands — 50 pages × 20 results = 1,000 listings per make captures the most recent listings without runaway request volume.

Changes to `cars_com.py`:
- Replace `CARS_COM_URLS` with `from app.scrapers.makes import CARS_COM_MAKES`
- `build_search_url()` signature simplifies: takes `(make_slug, page)` instead of `(make_slug, model_slug, page)`
- Increase `MAX_PAGES_PER_SEARCH` from `3` to `50`
- `CARS_COM_MAKES` uses Cars.com-specific make slugs (e.g., `"mercedes-benz"` for Mercedes, `"land-rover"` for Land Rover)

---

## 5. Scrape Duration Impact

| Platform | Before | After | Estimated time |
|---|---|---|---|
| BaT | 21 models × 1 req = 21 req | ~50 makes × 1 req = 50 req | ~1 min |
| C&B | 21 queries × 3 pages = 63 req | ~50 queries × 20 pages = 1,000 req | ~35 min |
| Cars.com | 18 models × 3 pages = 54 req | ~50 makes × 50 pages = 2,500 req | ~2.5 hrs |

Cars.com becomes the bottleneck. If full nightly scrapes take too long, the `selected_keys` filter can be used to rotate makes across nights (e.g., exotics every night, common makes weekly).

---

## 6. Test Updates

- Update `test_bat_scraper.py`: mock a make-level URL response (not model-level)
- Update `test_cars_and_bids_scraper.py`: search query = make name
- Update `test_cars_com_scraper.py`: URL has no `models[]` param; page limit = 50

---

## Files to Modify

| File | Change |
|---|---|
| `backend/app/scrapers/bring_a_trailer.py` | Replace `BAT_URLS` with `BAT_MAKES` import; change URL to make-level |
| `backend/app/scrapers/cars_and_bids.py` | Replace `CAB_URLS`; search by make name; raise page limit to 20 |
| `backend/app/scrapers/cars_com.py` | Replace `CARS_COM_URLS`; drop model slug from URL; raise page limit to 50 |
| `backend/tests/test_bat_scraper.py` | Update mocked URL |
| `backend/tests/test_cars_and_bids_scraper.py` | Update search query assertions |
| `backend/tests/test_cars_com_scraper.py` | Update URL assertions, page limit |

## New Files

| File | Purpose |
|---|---|
| `backend/app/scrapers/makes.py` | Centralized per-platform makes configuration |

---

## Open Question: BaT Make-Page Structure

Before implementation, validate that `bringatrailer.com/{make}/` returns the same `auctionsCompletedInitialData` JSON structure as model-specific pages. If it does not, BaT may need a different approach (e.g., search endpoint or model-discovery step). This validation should be the first implementation step.

---

## Verification

1. Run `pytest backend/tests/` — all scraper tests pass with updated URL/query patterns
2. Run a single-make test scrape: trigger BaT for "porsche" and confirm listings cover multiple models (not just 911 GT3)
3. Confirm Cars.com URL has no `models[]` param in scrape logs
4. Confirm `listing_snapshots` rows grow on re-scrape (from previous design)
