"""Regression tests for the raw-first auction ingestion service reset."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import Base


def test_metadata_contains_only_ingestion_tables() -> None:
    table_names = set(Base.metadata.tables)

    assert {
        "auction_lots",
        "auction_images",
        "scrape_runs",
        "crawl_state",
    }.issubset(table_names)
    assert "cars" not in table_names
    assert "vehicle_sales" not in table_names
    assert "price_predictions" not in table_names
    assert "watchlist_items" not in table_names
    assert "listing_snapshots" not in table_names


def test_removed_modules_are_not_importable() -> None:
    import importlib.util

    removed_modules = [
        "app.auth",
        "app.api.cars",
        "app.api.predictions",
        "app.api.watchlist",
        "app.models.car",
        "app.models.price_prediction",
        "app.models.watchlist",
        "app.scrapers.cars_com",
        "app.scrapers.cars_com_parser",
        "app.services.depreciation",
        "app.services.depreciation_curve",
        "app.services.compare_summary",
    ]

    for module_name in removed_modules:
        assert importlib.util.find_spec(module_name) is None


def test_auction_lot_model_has_raw_archive_columns() -> None:
    from app.models.auction_lot import AuctionLot

    columns = set(AuctionLot.__table__.columns.keys())

    assert {
        "source",
        "source_auction_id",
        "canonical_url",
        "auction_status",
        "sold_price",
        "high_bid",
        "bid_count",
        "currency",
        "ended_at",
        "make",
        "model",
        "trim",
        "vehicle_details",
        "list_payload",
        "detail_payload",
        "detail_html",
    }.issubset(columns)


@pytest.mark.asyncio
async def test_base_scraper_inserts_raw_lot_and_images() -> None:
    from app.models.auction_image import AuctionImage
    from app.models.auction_lot import AuctionLot
    from app.scrapers.base import BaseScraper, ScrapedAuctionLot

    class TestScraper(BaseScraper):
        source = "test_source"

        async def scrape(self) -> list[ScrapedAuctionLot]:
            return []

    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.flush.side_effect = lambda: setattr(added_lots[0], "id", uuid.uuid4())
    session.commit = AsyncMock()

    added_lots: list[AuctionLot] = []

    def capture_added(obj: object) -> None:
        if isinstance(obj, AuctionLot):
            added_lots.append(obj)

    session.add.side_effect = capture_added
    session.execute.return_value.scalar_one_or_none.return_value = None

    lot = ScrapedAuctionLot(
        source="test_source",
        source_auction_id="lot-1",
        canonical_url="https://example.com/lot-1",
        auction_status="sold",
        sold_price=100_000,
        high_bid=100_000,
        bid_count=42,
        currency="USD",
        listed_at=datetime(2026, 4, 1, tzinfo=UTC),
        ended_at=datetime(2026, 4, 2, tzinfo=UTC),
        title="2020 Porsche 911 GT3",
        year=2020,
        make="Porsche",
        model="911",
        trim="GT3",
        list_payload={"id": "lot-1"},
        detail_payload={"stats": {"views": 1000}},
        detail_html="<html>detail</html>",
        image_urls=["https://images.example/1.jpg", "https://images.example/1.jpg"],
    )

    inserted = await TestScraper(session).save_lot(lot)

    assert inserted is True
    added_objects = [call.args[0] for call in session.add.call_args_list]
    lot_objects = [obj for obj in added_objects if isinstance(obj, AuctionLot)]
    image_objects = [obj for obj in added_objects if isinstance(obj, AuctionImage)]
    assert len(lot_objects) == 1
    assert lot_objects[0].source_auction_id == "lot-1"
    assert lot_objects[0].list_payload == {"id": "lot-1"}
    assert lot_objects[0].detail_html == "<html>detail</html>"
    assert len(image_objects) == 1
    assert image_objects[0].image_url == "https://images.example/1.jpg"


def test_admin_dashboard_has_no_removed_feature_controls() -> None:
    from app.api import admin

    html = admin._DASHBOARD_HTML

    forbidden_terms = [
        "Depreciation",
        "Watchlist",
        "Prediction",
        "Cars.com",
        "secret-input",
        "auth-gate",
    ]
    for term in forbidden_terms:
        assert term not in html
    assert "Auction Lots" in html
