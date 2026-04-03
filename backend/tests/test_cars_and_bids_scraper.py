"""Tests for the Cars & Bids scraper.

Fixture-based tests use real auction JSON saved from the C&B API to guard against
schema drift. When C&B changes their API response format, update the fixture with:
    uv run python scripts/fetch_cars_and_bids_fixture.py

Pure unit tests for parsing helpers use synthetic data and never need updating.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.cars_and_bids import (
    CAB_URLS,
    CarsAndBidsScraper,
    get_all_url_keys,
    get_url_entries,
)
from app.scrapers.cars_and_bids_parser import (
    SOURCE,
    build_source_url,
    parse_auction,
    parse_mileage,
    parse_sold_date,
    parse_year,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cars_and_bids_porsche_911_gt3.json"

_SOLD_ITEM = {
    "id": "abc123",
    "title": "2019 Porsche 911 GT3 RS Weissach",
    "sub_title": "~6,700 Miles, 520-hp Flat-6, Lizard Green, Unmodified",
    "status": "sold",
    "sale_amount": 155500,
    "current_bid": 155500,
    "mileage": "6,700 Miles",
    "auction_end": "2026-01-22T18:32:47.781+00:00",
    "transmission": 2,
    "location": "Los Angeles, CA 90001",
    "no_reserve": False,
}


# ─── Fixture loader ───────────────────────────────────────────────────────────

@pytest.fixture
def porsche_911_gt3_auctions() -> list[dict]:
    """Real C&B auction JSON for Porsche 911 GT3 search results."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ─── URL registry helpers ────────────────────────────────────────────────────

def test_get_all_url_keys_nonempty() -> None:
    keys = get_all_url_keys()
    assert len(keys) > 0
    assert "porsche-911-gt3" in keys


def test_get_url_entries_structure() -> None:
    entries = get_url_entries()
    assert len(entries) > 0
    entry = entries[0]
    assert set(entry.keys()) == {"key", "label", "query"}


def test_cab_urls_registry() -> None:
    assert len(CAB_URLS) > 0
    for key, label, query in CAB_URLS:
        assert key and label and query


# ─── parse_year ──────────────────────────────────────────────────────────────

class TestParseYear:
    def test_extracts_year_from_start(self) -> None:
        assert parse_year("2019 Porsche 911 GT3 RS") == 2019

    def test_extracts_year_in_title(self) -> None:
        assert parse_year("Porsche 2014 911 GT3") == 2014

    def test_returns_none_on_no_year(self) -> None:
        assert parse_year("Porsche 911 GT3") is None

    def test_returns_none_on_empty(self) -> None:
        assert parse_year("") is None

    def test_ignores_future_year(self) -> None:
        # Only 19xx/20xx match the regex
        result = parse_year("1899 Something")
        assert result is None


# ─── parse_mileage ───────────────────────────────────────────────────────────

class TestParseMileage:
    def test_comma_separated(self) -> None:
        assert parse_mileage("45,200 Miles") == 45200

    def test_no_comma(self) -> None:
        assert parse_mileage("160 Miles") == 160

    def test_none_input(self) -> None:
        assert parse_mileage(None) is None

    def test_empty_string(self) -> None:
        assert parse_mileage("") is None

    def test_single_digit(self) -> None:
        assert parse_mileage("0 Miles") == 0


# ─── parse_sold_date ─────────────────────────────────────────────────────────

class TestParseSoldDate:
    def test_iso_with_offset(self) -> None:
        dt = parse_sold_date("2026-01-22T18:32:47.781+00:00")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 22

    def test_returns_none_on_none(self) -> None:
        assert parse_sold_date(None) is None

    def test_returns_none_on_invalid(self) -> None:
        assert parse_sold_date("not-a-date") is None

    def test_utc_conversion(self) -> None:
        dt = parse_sold_date("2026-03-15T12:00:00.000+00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc


# ─── build_source_url ────────────────────────────────────────────────────────

def test_build_source_url() -> None:
    url = build_source_url("abc123")
    assert url == "https://carsandbids.com/auctions/abc123/"


# ─── parse_auction ───────────────────────────────────────────────────────────

class TestParseAuction:
    def test_valid_sold_auction(self) -> None:
        listing, reason = parse_auction(_SOLD_ITEM)
        assert listing is not None
        assert reason == ""
        assert listing.source == SOURCE
        assert listing.sale_type == "auction"
        assert listing.is_sold is True
        assert listing.year == 2019
        assert listing.sold_price == 155500
        assert listing.asking_price == 155500
        assert listing.mileage == 6700
        assert listing.source_url == "https://carsandbids.com/auctions/abc123/"
        assert listing.transmission == 2
        assert listing.location == "Los Angeles, CA 90001"
        assert listing.no_reserve is False
        assert listing.color == "Lizard Green"

    def test_skips_reserve_not_met(self) -> None:
        item = {**_SOLD_ITEM, "status": "reserve_not_met", "sale_amount": None}
        listing, reason = parse_auction(item)
        assert listing is None
        assert reason == "not_sold"

    def test_skips_no_id(self) -> None:
        item = {**_SOLD_ITEM, "id": ""}
        listing, reason = parse_auction(item)
        assert listing is None
        assert reason == "no_url"

    def test_skips_no_title(self) -> None:
        item = {**_SOLD_ITEM, "title": ""}
        listing, reason = parse_auction(item)
        assert listing is None
        assert reason == "no_title"

    def test_skips_no_year(self) -> None:
        item = {**_SOLD_ITEM, "title": "Porsche 911 GT3"}
        listing, reason = parse_auction(item)
        assert listing is None
        assert reason == "no_year"

    def test_skips_no_price(self) -> None:
        item = {**_SOLD_ITEM, "sale_amount": None}
        listing, reason = parse_auction(item)
        assert listing is None
        assert reason == "no_price"

    def test_skips_zero_price(self) -> None:
        item = {**_SOLD_ITEM, "sale_amount": 0}
        listing, reason = parse_auction(item)
        assert listing is None
        assert reason == "no_price"

    def test_no_mileage_allowed(self) -> None:
        item = {**_SOLD_ITEM, "mileage": None}
        listing, reason = parse_auction(item)
        assert listing is not None
        assert listing.mileage is None

    def test_raw_data_populated(self) -> None:
        listing, _ = parse_auction(_SOLD_ITEM)
        assert listing is not None
        assert listing.raw_data["id"] == "abc123"
        assert listing.raw_data["sale_amount"] == 155500

    def test_no_reserve_true(self) -> None:
        item = {**_SOLD_ITEM, "no_reserve": True}
        listing, _ = parse_auction(item)
        assert listing is not None
        assert listing.no_reserve is True

    def test_no_reserve_defaults_false_when_absent(self) -> None:
        item = {k: v for k, v in _SOLD_ITEM.items() if k != "no_reserve"}
        listing, _ = parse_auction(item)
        assert listing is not None
        assert listing.no_reserve is False

    def test_color_none_when_no_color_in_sub_title(self) -> None:
        item = {**_SOLD_ITEM, "sub_title": "~6,700 Miles, 520-hp Flat-6, Unmodified"}
        listing, _ = parse_auction(item)
        assert listing is not None
        assert listing.color is None

    def test_location_none_when_absent(self) -> None:
        item = {k: v for k, v in _SOLD_ITEM.items() if k != "location"}
        listing, _ = parse_auction(item)
        assert listing is not None
        assert listing.location is None


# ─── Fixture-based tests ──────────────────────────────────────────────────────

class TestExtractFromFixture:
    def test_fixture_has_items(self, porsche_911_gt3_auctions: list[dict]) -> None:
        assert len(porsche_911_gt3_auctions) > 0, (
            "Fixture JSON is empty — re-run scripts/fetch_cars_and_bids_fixture.py"
        )

    def test_fixture_has_sold_items(self, porsche_911_gt3_auctions: list[dict]) -> None:
        sold = [a for a in porsche_911_gt3_auctions if a.get("status") == "sold"]
        assert len(sold) > 0, "No sold auctions in fixture — re-run fixture script"

    def test_fixture_items_have_required_fields(
        self, porsche_911_gt3_auctions: list[dict]
    ) -> None:
        for item in porsche_911_gt3_auctions:
            assert "id" in item
            assert "title" in item
            assert "status" in item

    def test_parse_auction_from_fixture(self, porsche_911_gt3_auctions: list[dict]) -> None:
        parsed, skipped = [], {}
        for item in porsche_911_gt3_auctions:
            listing, reason = parse_auction(item)
            if listing is not None:
                parsed.append(listing)
            else:
                skipped[reason] = skipped.get(reason, 0) + 1

        assert len(parsed) > 0, f"No listings parsed. Skip reasons: {skipped}"
        first = parsed[0]
        assert first.source == SOURCE
        assert first.sale_type == "auction"
        assert first.is_sold is True
        assert first.sold_price is not None and first.sold_price > 0
        assert first.year >= 2010
        assert first.source_url.startswith("https://carsandbids.com/auctions/")
        # New fields extracted from fixture (first sold item: id=9eNla8xk)
        assert first.transmission == 1
        assert first.location == "Elmwood Park, IL 60707"
        assert first.no_reserve is False

    def test_parsed_prices_are_sane(self, porsche_911_gt3_auctions: list[dict]) -> None:
        prices = [
            parse_auction(a)[0].sold_price
            for a in porsche_911_gt3_auctions
            if parse_auction(a)[0] is not None
        ]
        assert len(prices) > 0
        # 911 GT3s should all be > $50k
        assert all(p > 50_000 for p in prices), f"Unexpectedly low prices: {prices}"

    def test_urls_point_to_carsandbids(self, porsche_911_gt3_auctions: list[dict]) -> None:
        for item in porsche_911_gt3_auctions:
            listing, _ = parse_auction(item)
            if listing is not None:
                assert listing.source_url.startswith("https://carsandbids.com/auctions/")


# ─── Scraper class tests (mocked _fetch_search_results) ──────────────────────

def _make_session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


@patch.object(CarsAndBidsScraper, "_fetch_search_results", new_callable=AsyncMock)
async def test_scraper_returns_listings(
    mock_fetch: AsyncMock,
    porsche_911_gt3_auctions: list[dict],
) -> None:
    """Scraper returns parsed listings from fixture data."""
    mock_fetch.return_value = porsche_911_gt3_auctions
    scraper = CarsAndBidsScraper(_make_session(), None, selected_keys=["porsche-911-gt3"])
    listings = await scraper.scrape()
    assert mock_fetch.called
    assert len(listings) > 0


@patch.object(CarsAndBidsScraper, "_fetch_search_results", new_callable=AsyncMock)
async def test_scraper_stops_on_cancel(mock_fetch: AsyncMock) -> None:
    """Scraper respects cancel_event and returns early."""
    cancel_event = asyncio.Event()
    cancel_event.set()
    scraper = CarsAndBidsScraper(
        _make_session(), None,
        selected_keys=["porsche-911-gt3", "ferrari-458"],
        cancel_event=cancel_event,
    )
    listings = await scraper.scrape()
    assert mock_fetch.call_count == 0
    assert listings == []


@patch.object(CarsAndBidsScraper, "_fetch_search_results", new_callable=AsyncMock)
async def test_scraper_handles_fetch_error(mock_fetch: AsyncMock) -> None:
    """Errors from _fetch_search_results are caught and don't crash the scraper."""
    mock_fetch.side_effect = Exception("playwright error")
    scraper = CarsAndBidsScraper(_make_session(), None, selected_keys=["porsche-911-gt3"])
    listings = await scraper.scrape()
    assert listings == []


@patch.object(CarsAndBidsScraper, "_fetch_search_results", new_callable=AsyncMock)
async def test_scraper_deduplicates_within_run(
    mock_fetch: AsyncMock,
    porsche_911_gt3_auctions: list[dict],
) -> None:
    """Duplicate auction IDs across calls are deduplicated within a scrape run."""
    mock_fetch.return_value = porsche_911_gt3_auctions
    scraper = CarsAndBidsScraper(_make_session(), None, selected_keys=["porsche-911-gt3"])
    listings = await scraper.scrape()
    urls = [l.source_url for l in listings]
    assert len(urls) == len(set(urls)), "Duplicate source URLs in a single scrape run"


@patch.object(CarsAndBidsScraper, "_fetch_search_results", new_callable=AsyncMock)
async def test_scraper_skips_unsold(mock_fetch: AsyncMock) -> None:
    """Only sold auctions are returned; reserve-not-met auctions are excluded."""
    items = [
        {**_SOLD_ITEM, "id": "sold1", "status": "sold", "sale_amount": 100000},
        {**_SOLD_ITEM, "id": "unsold1", "status": "reserve_not_met", "sale_amount": None},
    ]
    mock_fetch.return_value = items
    scraper = CarsAndBidsScraper(_make_session(), None, selected_keys=["porsche-911-gt3"])
    listings = await scraper.scrape()
    assert len(listings) == 1
    assert listings[0].source_url == "https://carsandbids.com/auctions/sold1/"
