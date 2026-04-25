"""Tests for raw auction lot persistence in BaseScraper."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.auction_image import AuctionImage
from app.models.auction_lot import AuctionLot
from app.models.scrape_anomaly import ScrapeAnomaly
from app.models.scrape_request_log import ScrapeRequestLog
from app.scrapers.base import BaseScraper, ScrapedAuctionLot


class ConcreteTestScraper(BaseScraper):
    source = "test_source"

    async def scrape(self) -> list[ScrapedAuctionLot]:
        return []


def _make_lot(**overrides: object) -> ScrapedAuctionLot:
    values = {
        "source": "test_source",
        "source_auction_id": "auction-123",
        "canonical_url": "https://example.com/auction-123",
        "auction_status": "sold",
        "sold_price": 118_000,
        "high_bid": 118_000,
        "bid_count": 12,
        "currency": "USD",
        "ended_at": datetime(2024, 1, 15, tzinfo=UTC),
        "year": 2020,
        "make": "Porsche",
        "model": "911",
        "trim": "GT3",
        "mileage": 5000,
        "exterior_color": "Blue",
        "title": "2020 Porsche 911 GT3",
        "subtitle": "5,000 miles, manual",
        "vehicle_details": {"transmission": "Manual"},
        "list_payload": {"id": "auction-123"},
        "detail_payload": {"views": 2000},
        "detail_html": "<html>detail</html>",
        "image_urls": ["https://images.example.com/1.jpg"],
    }
    values.update(overrides)
    return ScrapedAuctionLot(**values)


def _make_session(existing: AuctionLot | None = None) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_new_raw_lot_inserts_lot_and_images() -> None:
    session = _make_session()
    lot_ids: list[uuid.UUID] = []

    async def flush() -> None:
        for call in session.add.call_args_list:
            obj = call.args[0]
            if isinstance(obj, AuctionLot):
                lot_ids.append(obj.id)

    session.flush.side_effect = flush

    inserted = await ConcreteTestScraper(session).save_lot(_make_lot())

    assert inserted is True
    added_objects = [call.args[0] for call in session.add.call_args_list]
    lots = [obj for obj in added_objects if isinstance(obj, AuctionLot)]
    images = [obj for obj in added_objects if isinstance(obj, AuctionImage)]
    assert len(lots) == 1
    assert lots[0].source_auction_id == "auction-123"
    assert lots[0].canonical_url == "https://example.com/auction-123"
    assert lots[0].vehicle_details == {"transmission": "Manual"}
    assert lots[0].list_payload == {"id": "auction-123"}
    assert lots[0].detail_html == "<html>detail</html>"
    assert len(images) == 1
    assert images[0].auction_lot_id == lot_ids[0]
    assert images[0].image_url == "https://images.example.com/1.jpg"


@pytest.mark.asyncio
async def test_duplicate_raw_lot_updates_existing_and_replaces_images() -> None:
    existing = AuctionLot(
        id=uuid.uuid4(),
        source="test_source",
        source_auction_id="auction-123",
        canonical_url="https://example.com/auction-123",
        auction_status="unknown",
    )
    session = _make_session(existing)
    lot = _make_lot(
        auction_status="reserve_not_met",
        sold_price=None,
        high_bid=90_000,
        image_urls=["https://images.example.com/new.jpg"],
    )

    inserted = await ConcreteTestScraper(session).save_lot(lot)

    assert inserted is False
    assert existing.auction_status == "reserve_not_met"
    assert existing.sold_price is None
    assert existing.high_bid == 90_000
    added_images = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], AuctionImage)
    ]
    assert len(added_images) == 1
    assert added_images[0].auction_lot_id == existing.id
    session.execute.assert_called()


@pytest.mark.asyncio
async def test_duplicate_detection_falls_back_to_canonical_url_when_id_missing() -> None:
    existing = AuctionLot(
        id=uuid.uuid4(),
        source="test_source",
        canonical_url="https://example.com/no-id",
        auction_status="sold",
    )
    session = _make_session(existing)

    inserted = await ConcreteTestScraper(session).save_lot(
        _make_lot(source_auction_id=None, canonical_url="https://example.com/no-id")
    )

    assert inserted is False
    assert existing.title == "2020 Porsche 911 GT3"


@pytest.mark.asyncio
async def test_base_scraper_records_request_logs_and_anomalies() -> None:
    session = _make_session()
    scraper = ConcreteTestScraper(session)
    scraper.current_run_id = uuid.uuid4()

    await scraper.record_request_log(
        url="https://example.com/page",
        action="http_get",
        attempt=2,
        status_code=500,
        duration_ms=75,
        outcome="retry",
        error_type="HTTPStatusError",
        error_message="server error",
        retry_delay_seconds=2.0,
        raw_item_count=10,
        parsed_lot_count=0,
        skip_counts={"no_price": 10},
        metadata_json={"target": "Example"},
    )
    await scraper.record_anomaly(
        severity="warning",
        code="zero_lots",
        message="No lots parsed",
        url="https://example.com/page",
        metadata_json={"raw_item_count": 10},
    )

    added_objects = [call.args[0] for call in session.add.call_args_list]
    logs = [obj for obj in added_objects if isinstance(obj, ScrapeRequestLog)]
    anomalies = [obj for obj in added_objects if isinstance(obj, ScrapeAnomaly)]
    assert len(logs) == 1
    assert logs[0].scrape_run_id == scraper.current_run_id
    assert logs[0].outcome == "retry"
    assert logs[0].skip_counts == {"no_price": 10}
    assert len(anomalies) == 1
    assert anomalies[0].severity == "warning"
    assert anomalies[0].code == "zero_lots"
