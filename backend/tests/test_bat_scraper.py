"""Tests for Bring a Trailer parsing and target discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.scrape_anomaly import ScrapeAnomaly
from app.models.scrape_request_log import ScrapeRequestLog
from app.scrapers.bat_parser import parse_item, parse_mileage, parse_sold_text, parse_year
from app.scrapers.bring_a_trailer import (
    BringATrailerScraper,
    extract_model_entries_from_html,
    get_url_entries,
)

SOLD_ITEM = {
    "active": False,
    "current_bid": 229000,
    "sold_text": "Sold for USD $229,000 <span> on 3/29/26 </span>",
    "title": "2019 Porsche 911 GT3 RS Weissach",
    "url": "https://bringatrailer.com/listing/2019-porsche-911-gt3-rs-weissach-97/",
    "id": 108526570,
    "bids": 42,
    "country": "United States",
    "image": "https://bringatrailer.com/wp-content/uploads/example.jpg",
}

RESERVE_NOT_MET_ITEM = {
    **SOLD_ITEM,
    "current_bid": 189000,
    "sold_text": "Bid to USD $189,000 <span> on 3/27/26 </span>",
    "id": 110742918,
    "image": "https://bringatrailer.com/wp-content/uploads/unsold.jpg",
}


def test_parse_year_and_mileage() -> None:
    assert parse_year("11k-Mile 2016 Porsche 911 GT3 RS") == 2016
    assert parse_mileage("11k-Mile 2016 Porsche 911 GT3 RS") == 11000


def test_parse_sold_text() -> None:
    is_sold, price, ended_at = parse_sold_text(
        "Sold for USD $229,000 <span> on 3/29/26 </span>"
    )
    assert is_sold is True
    assert price == 229000
    assert ended_at == datetime(2026, 3, 29, tzinfo=UTC)


def test_parse_sold_lot_preserves_raw_payload_and_images() -> None:
    lot, reason = parse_item(SOLD_ITEM)

    assert lot is not None
    assert reason == ""
    assert lot.source == "bring_a_trailer"
    assert lot.source_auction_id == "108526570"
    assert lot.canonical_url == SOLD_ITEM["url"]
    assert lot.auction_status == "sold"
    assert lot.sold_price == 229000
    assert lot.high_bid == 229000
    assert lot.bid_count == 42
    assert lot.year == 2019
    assert lot.make == "Porsche"
    assert lot.model == "911"
    assert lot.trim == "GT3 RS Weissach"
    assert lot.ended_at == datetime(2026, 3, 29, tzinfo=UTC)
    assert lot.image_urls == ["https://bringatrailer.com/wp-content/uploads/example.jpg"]
    assert lot.list_payload == SOLD_ITEM


def test_parse_reserve_not_met_lot_uses_high_bid_not_sold_price() -> None:
    lot, reason = parse_item(RESERVE_NOT_MET_ITEM)

    assert lot is not None
    assert reason == ""
    assert lot.auction_status == "reserve_not_met"
    assert lot.sold_price is None
    assert lot.high_bid == 189000
    assert lot.ended_at == datetime(2026, 3, 27, tzinfo=UTC)


def test_skips_non_vehicle_without_year() -> None:
    lot, reason = parse_item(
        {
            **SOLD_ITEM,
            "title": "Euro Porsche 996 GT3 Recaro Seats",
            "url": "https://bringatrailer.com/listing/seats-206/",
        }
    )

    assert lot is None
    assert reason == "no_year"


def test_model_directory_excludes_non_vehicle_paths() -> None:
    html = """
    <a class="previous-listing-image-link" href="https://bringatrailer.com/porsche/911/">
      <img alt="Porsche 911">
    </a>
    <a class="previous-listing-image-link" href="https://bringatrailer.com/trailer/camper/">
      <img alt="Camper Trailer">
    </a>
    """

    assert extract_model_entries_from_html(html) == [("porsche-911", "Porsche 911", "porsche/911")]


def test_bat_targets_are_exposed() -> None:
    entries = get_url_entries()
    assert entries
    assert {"key", "label", "path"} == set(entries[0])


@patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock)
@patch("app.scrapers.bring_a_trailer.fetch_page", new_callable=AsyncMock)
async def test_bat_records_page_request_logs_and_zero_parse_anomaly(
    mock_fetch_page: AsyncMock,
    _mock_sleep: AsyncMock,
) -> None:
    mock_fetch_page.return_value = [
        {
            **SOLD_ITEM,
            "title": "Euro Porsche 996 GT3 Recaro Seats",
            "url": "https://bringatrailer.com/listing/seats-206/",
        }
    ]
    session = AsyncMock()
    session.add = MagicMock()

    lots = await BringATrailerScraper(session, None, selected_keys={"porsche"}).scrape()

    added_objects = [call.args[0] for call in session.add.call_args_list]
    logs = [obj for obj in added_objects if isinstance(obj, ScrapeRequestLog)]
    anomalies = [obj for obj in added_objects if isinstance(obj, ScrapeAnomaly)]
    assert lots == []
    assert logs
    assert logs[0].source == "bring_a_trailer"
    assert logs[0].raw_item_count == 1
    assert logs[0].parsed_lot_count == 0
    assert logs[0].skip_counts == {"no_year": 1}
    assert any(anomaly.code == "zero_parsed_lots" for anomaly in anomalies)
