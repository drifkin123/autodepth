"""Tests for Cars & Bids parsing and scraper behavior."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock, patch

from app.scrapers.cars_and_bids import CarsAndBidsScraper, get_url_entries
from app.scrapers.cars_and_bids_parser import (
    build_source_url,
    parse_auction,
    parse_mileage,
    parse_sold_date,
    parse_year,
)

SOLD_ITEM = {
    "id": "abc123",
    "title": "2019 Porsche 911 GT3 RS Weissach",
    "sub_title": "~6,700 Miles, 520-hp Flat-6, Lizard Green, Unmodified",
    "status": "sold",
    "sale_amount": 155500,
    "current_bid": 155500,
    "bid_count": 18,
    "mileage": "6,700 Miles",
    "auction_end": "2026-01-22T18:32:47.781+00:00",
    "transmission": "Manual",
    "engine": "4.0L Flat-6",
    "drivetrain": "Rear-wheel drive",
    "location": "Los Angeles, CA 90001",
    "no_reserve": False,
    "main_photo": "https://media.carsandbids.com/example.jpg",
}


def test_parse_helpers() -> None:
    assert parse_year("2019 Porsche 911 GT3 RS") == 2019
    assert parse_mileage("45,200 Miles") == 45200
    assert parse_sold_date("2026-01-22T18:32:47.781+00:00").tzinfo == UTC
    assert build_source_url("abc123") == "https://carsandbids.com/auctions/abc123/"


def test_parse_sold_lot_preserves_raw_payload_and_images() -> None:
    lot, reason = parse_auction(SOLD_ITEM)

    assert lot is not None
    assert reason == ""
    assert lot.source == "cars_and_bids"
    assert lot.source_auction_id == "abc123"
    assert lot.canonical_url == "https://carsandbids.com/auctions/abc123/"
    assert lot.auction_status == "sold"
    assert lot.sold_price == 155500
    assert lot.high_bid == 155500
    assert lot.bid_count == 18
    assert lot.year == 2019
    assert lot.make == "Porsche"
    assert lot.model == "911"
    assert lot.trim == "GT3 RS Weissach"
    assert lot.mileage == 6700
    assert lot.exterior_color == "Lizard Green"
    assert lot.engine == "4.0L Flat-6"
    assert lot.drivetrain == "Rear-wheel drive"
    assert lot.image_urls == ["https://media.carsandbids.com/example.jpg"]
    assert lot.list_payload == SOLD_ITEM


def test_parse_reserve_not_met_lot_uses_high_bid_not_sold_price() -> None:
    item = {
        **SOLD_ITEM,
        "id": "unsold1",
        "status": "reserve_not_met",
        "sale_amount": None,
        "current_bid": 141000,
    }

    lot, reason = parse_auction(item)

    assert lot is not None
    assert reason == ""
    assert lot.auction_status == "reserve_not_met"
    assert lot.sold_price is None
    assert lot.high_bid == 141000
    assert lot.canonical_url == "https://carsandbids.com/auctions/unsold1/"


def test_parse_lot_normalizes_structured_seller_and_photo() -> None:
    item = {
        **SOLD_ITEM,
        "seller": {"username": "dryhurst", "photo": None},
        "main_photo": {
            "base_url": "media.carsandbids.com",
            "path": "abc123/hero.jpg",
        },
    }

    lot, reason = parse_auction(item)

    assert lot is not None
    assert reason == ""
    assert lot.seller == "dryhurst"
    assert lot.image_urls == ["https://media.carsandbids.com/abc123/hero.jpg"]
    assert lot.vehicle_details["seller"] == {"username": "dryhurst", "photo": None}


def test_skips_lot_without_price_or_bid() -> None:
    lot, reason = parse_auction({**SOLD_ITEM, "sale_amount": None, "current_bid": None})

    assert lot is None
    assert reason == "no_price"


def test_cab_targets_are_global_closed_auctions() -> None:
    assert get_url_entries() == [{"key": "all", "label": "All closed auctions", "query": ""}]


@patch.object(CarsAndBidsScraper, "_fetch_search_results", new_callable=AsyncMock)
async def test_scraper_deduplicates_closed_auction_urls(mock_fetch: AsyncMock) -> None:
    mock_fetch.return_value = [SOLD_ITEM, SOLD_ITEM]
    scraper = CarsAndBidsScraper(AsyncMock(), None, selected_keys=["all"])

    lots = await scraper.scrape()

    assert len(lots) == 1
    assert lots[0].canonical_url == "https://carsandbids.com/auctions/abc123/"
