"""Tests for the Cars.com scraper.

Fixture-based tests use real HTML saved from Cars.com to guard against
selector drift. When Cars.com changes their HTML structure, update the
fixture with:
    uv run python scripts/fetch_cars_com_fixture.py

Pure unit tests for parsing helpers use synthetic data and never need updating.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.cars_com import (
    CarsComScraper,
    build_search_url,
    get_all_url_keys,
    get_url_entries,
)
from app.scrapers.makes import CARS_COM_MAKES
from app.scrapers.cars_com_parser import (
    BASE_URL,
    extract_listings_from_html,
    extract_page_meta,
    has_next_page,
    parse_listing,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cars_com_porsche_911_p1.html"


# ─── Fixture loader ──────────────────────────────────────────────────────────

@pytest.fixture
def porsche_911_html() -> str:
    """Real Cars.com HTML for Porsche 911 search page 1."""
    return FIXTURE_PATH.read_text(encoding="utf-8")


# ─── URL helpers ─────────────────────────────────────────────────────────────

def test_build_search_url_porsche() -> None:
    url = build_search_url("porsche", page=1)
    assert "makes[]=porsche" in url
    assert "models[]" not in url
    assert "page=1" in url
    assert url.startswith("https://www.cars.com")


def test_build_search_url_page_param() -> None:
    url2 = build_search_url("ferrari", page=2)
    assert "page=2" in url2


def test_get_all_url_keys_nonempty() -> None:
    keys = get_all_url_keys()
    assert len(keys) > 0
    assert "porsche" in keys


def test_get_url_entries_structure() -> None:
    entries = get_url_entries()
    assert len(entries) > 0
    entry = entries[0]
    assert {"key", "label", "make"} == set(entry.keys())


def test_cars_com_urls_registry() -> None:
    assert len(CARS_COM_MAKES) > 0
    # Each entry is a 3-tuple
    for key, label, make in CARS_COM_MAKES:
        assert key and label and make


# ─── Fixture-based extraction tests ─────────────────────────────────────────

def test_extract_listings_returns_results(porsche_911_html: str) -> None:
    """Fixture HTML must yield at least one parsed listing."""
    listings = extract_listings_from_html(porsche_911_html)
    assert len(listings) > 0, (
        "extract_listings_from_html returned 0 results on real fixture HTML — "
        "Cars.com may have changed their HTML structure. "
        "Re-run scripts/fetch_cars_com_fixture.py to update the fixture."
    )


def test_extracted_listings_have_required_fields(porsche_911_html: str) -> None:
    listings = extract_listings_from_html(porsche_911_html)
    for item in listings:
        assert "source_url" in item, "missing source_url"
        assert "year" in item, "missing year"
        assert "price" in item, "missing price"
        assert item["source_url"].startswith("https://www.cars.com/vehicledetail/")


def test_extracted_listings_are_porsches(porsche_911_html: str) -> None:
    listings = extract_listings_from_html(porsche_911_html)
    makes = {item.get("make", "").lower() for item in listings if item.get("make")}
    assert "porsche" in makes


def test_extracted_listings_have_sane_prices(porsche_911_html: str) -> None:
    listings = extract_listings_from_html(porsche_911_html)
    prices = [int(item["price"]) for item in listings if item.get("price")]
    assert len(prices) > 0
    # Porsche 911s should be priced > $20k
    assert all(p > 20_000 for p in prices), f"Unexpectedly low prices: {prices}"


def test_parse_listing_from_fixture(porsche_911_html: str) -> None:
    listings = extract_listings_from_html(porsche_911_html)
    parsed, skipped = [], []
    for item in listings:
        result, reason = parse_listing(item)
        if result is not None:
            parsed.append(result)
        else:
            skipped.append(reason)

    assert len(parsed) > 0, f"No listings parsed. Skip reasons: {skipped}"

    first = parsed[0]
    assert first.source == "cars_com"
    assert first.sale_type == "listing"
    assert first.is_sold is False
    assert first.sold_price is None
    assert first.asking_price > 0
    assert first.year >= 1990
    assert first.source_url.startswith("https://www.cars.com/vehicledetail/")
    # New fields populated from fixture (first item: Porsche 911 Carrera T, Used)
    assert first.make == "Porsche"
    assert first.model == "911"
    assert first.trim is not None
    assert first.body_style == "Coupe"
    assert first.fuel_type == "Gasoline"
    assert first.stock_type == "used"


# ─── Pagination tests ────────────────────────────────────────────────────────

def test_extract_page_meta(porsche_911_html: str) -> None:
    meta = extract_page_meta(porsche_911_html)
    assert meta["page"] == 1
    assert meta["page_size"] > 0
    assert meta["total_pages"] > 1  # Porsche 911 has many pages


def test_has_next_page_true_for_page_1(porsche_911_html: str) -> None:
    assert has_next_page(porsche_911_html) is True


def test_has_next_page_false_when_on_last_page() -> None:
    # Synthesize a last-page HTML blob
    html = '"page":5,"page_size":20,"total_pages":5'
    assert has_next_page(html) is False


def test_has_next_page_false_when_no_meta() -> None:
    assert has_next_page("<html>no metadata here</html>") is False


# ─── parse_listing unit tests ─────────────────────────────────────────────────

def test_parse_listing_valid() -> None:
    item = {
        "source_url": "https://www.cars.com/vehicledetail/abc-123/",
        "year": "2021",
        "make": "Porsche",
        "model": "911",
        "trim": "GT3",
        "price": "175000",
        "mileage": "4200",
        "vin": "WP0AC2A99MS226301",
        "bodyStyle": "Coupe",
        "fuelType": "Gasoline",
        "stockType": "Used",
    }
    listing, reason = parse_listing(item)
    assert listing is not None
    assert reason == ""
    assert listing.year == 2021
    assert listing.asking_price == 175_000
    assert listing.mileage == 4200
    assert listing.raw_title == "2021 Porsche 911 GT3"
    assert listing.is_sold is False
    assert listing.sold_price is None
    assert listing.make == "Porsche"
    assert listing.model == "911"
    assert listing.trim == "GT3"
    assert listing.vin == "WP0AC2A99MS226301"
    assert listing.body_style == "Coupe"
    assert listing.fuel_type == "Gasoline"
    assert listing.stock_type == "used"


def test_parse_listing_missing_url() -> None:
    listing, reason = parse_listing({"year": "2021", "price": "50000"})
    assert listing is None
    assert reason == "no_url"


def test_parse_listing_missing_year() -> None:
    listing, reason = parse_listing({
        "source_url": "https://www.cars.com/vehicledetail/x/",
        "price": "50000",
    })
    assert listing is None
    assert reason == "no_year"


def test_parse_listing_missing_price() -> None:
    listing, reason = parse_listing({
        "source_url": "https://www.cars.com/vehicledetail/x/",
        "year": "2021",
        "price": None,
    })
    assert listing is None
    assert reason == "no_price"


def test_parse_listing_zero_price() -> None:
    listing, reason = parse_listing({
        "source_url": "https://www.cars.com/vehicledetail/x/",
        "year": "2021",
        "price": "0",
    })
    assert listing is None
    assert reason == "no_price"


def test_parse_listing_no_mileage_allowed() -> None:
    item = {
        "source_url": "https://www.cars.com/vehicledetail/abc/",
        "year": "2020",
        "make": "Ferrari",
        "model": "488",
        "trim": "Pista",
        "price": "280000",
    }
    listing, reason = parse_listing(item)
    assert listing is not None
    assert listing.mileage is None


def test_parse_listing_stock_type_normalization() -> None:
    base = {
        "source_url": "https://www.cars.com/vehicledetail/x/",
        "year": "2022",
        "make": "Porsche",
        "model": "911",
        "price": "150000",
    }
    for raw, expected in [("Used", "used"), ("New", "new"), ("Certified", "cpo"), ("Unknown", None)]:
        listing, _ = parse_listing({**base, "stockType": raw})
        assert listing is not None
        assert listing.stock_type == expected, f"stockType={raw!r} should map to {expected!r}"


def test_parse_listing_new_fields_none_when_absent() -> None:
    item = {
        "source_url": "https://www.cars.com/vehicledetail/x/",
        "year": "2022",
        "make": "Porsche",
        "model": "911",
        "price": "150000",
    }
    listing, _ = parse_listing(item)
    assert listing is not None
    assert listing.vin is None
    assert listing.body_style is None
    assert listing.fuel_type is None
    assert listing.stock_type is None


# ─── Scraper class tests (mocked fetch) ──────────────────────────────────────

async def _make_scraper_with_fixture(fixture_html: str) -> tuple:
    """Return (scraper, mock_session) with fetch_page patched to return fixture."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.add = MagicMock()
    session.commit = AsyncMock()

    # Car cache: one matching car
    car = MagicMock()
    car.id = "car-uuid"
    car.make = "Porsche"
    car.model = "911"
    car.trim = "GT3"
    session.execute.return_value.scalars.return_value.all.return_value = [car]

    return session, car


@patch("app.scrapers.cars_com.fetch_page")
@patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock)
async def test_scraper_calls_fetch_for_each_make(
    mock_sleep: AsyncMock,
    mock_fetch: AsyncMock,
    porsche_911_html: str,
) -> None:
    """Scraper calls fetch_page at least once and gets listings back."""
    # Return fixture on first call, empty page on second (stops pagination)
    no_next_html = '"page":1,"page_size":20,"total_pages":1'
    mock_fetch.side_effect = [porsche_911_html, no_next_html]

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    session.add = MagicMock()
    session.commit = AsyncMock()

    scraper = CarsComScraper(
        session, None,
        selected_keys=["porsche"],
    )

    listings = await scraper.scrape()
    assert mock_fetch.called
    assert len(listings) > 0


@patch("app.scrapers.cars_com.fetch_page")
@patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock)
async def test_scraper_stops_on_last_page(
    mock_sleep: AsyncMock,
    mock_fetch: AsyncMock,
    porsche_911_html: str,
) -> None:
    """Scraper stops paginating when has_next_page returns False."""
    # Both pages indicate it's the last page
    last_page_html = '"page":1,"page_size":20,"total_pages":1' + porsche_911_html
    mock_fetch.return_value = last_page_html

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    session.add = MagicMock()
    session.commit = AsyncMock()

    scraper = CarsComScraper(
        session, None,
        selected_keys=["porsche"],
    )
    await scraper.scrape()

    # Should have called fetch only once (no next page)
    assert mock_fetch.call_count == 1


@patch("app.scrapers.cars_com.fetch_page")
@patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock)
async def test_scraper_stops_on_cancel(
    mock_sleep: AsyncMock,
    mock_fetch: AsyncMock,
    porsche_911_html: str,
) -> None:
    """Scraper respects cancel_event and returns early."""
    mock_fetch.return_value = porsche_911_html
    cancel_event = asyncio.Event()
    cancel_event.set()  # already cancelled

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    scraper = CarsComScraper(
        session, None,
        selected_keys=["porsche", "ferrari"],
        cancel_event=cancel_event,
    )
    listings = await scraper.scrape()
    # Should return immediately with no listings
    assert mock_fetch.call_count == 0
    assert listings == []


@patch("app.scrapers.cars_com.fetch_page")
@patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock)
async def test_scraper_handles_fetch_error_gracefully(
    mock_sleep: AsyncMock,
    mock_fetch: AsyncMock,
) -> None:
    """HTTP errors on a model are logged but don't crash the scraper."""
    mock_fetch.side_effect = Exception("connection refused")

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    scraper = CarsComScraper(session, None, selected_keys=["porsche"])
    listings = await scraper.scrape()
    assert listings == []


@patch("app.scrapers.cars_com.fetch_page")
@patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock)
async def test_scraper_deduplicates_within_run(
    mock_sleep: AsyncMock,
    mock_fetch: AsyncMock,
    porsche_911_html: str,
) -> None:
    """Same URL returned twice (across makes) is only added once."""
    mock_fetch.return_value = porsche_911_html

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    session.add = MagicMock()
    session.commit = AsyncMock()

    # One make key — same HTML returned for it
    scraper = CarsComScraper(
        session, None,
        selected_keys=["porsche"],
    )
    listings_1 = await scraper.scrape()

    # Run again — seen_urls resets, but DB dedup catches it at save_listing level
    assert len(listings_1) > 0
    urls = [l.source_url for l in listings_1]
    assert len(urls) == len(set(urls)), "Duplicate URLs within single scrape run"
