"""Tests for Bring a Trailer parsing and target discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.auction_lot import AuctionLot
from app.models.scrape_anomaly import ScrapeAnomaly
from app.models.scrape_request_log import ScrapeRequestLog
from app.scrapers.bat_parser import (
    enrich_lot_from_detail_html,
    extract_completed_metadata_from_html,
    parse_item,
    parse_mileage,
    parse_sold_text,
    parse_year,
)
from app.scrapers.bring_a_trailer import (
    BringATrailerScraper,
    build_completed_results_params,
    extract_model_entries_from_html,
    get_url_entries,
)
from app.scrapers.runtime import BlockedScrapeError

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


def test_parse_vehicle_identity_ignores_bat_title_prefixes() -> None:
    examples = [
        (
            "One-Owner 2015 Porsche 911 Turbo S Cabriolet",
            "Porsche",
            "911",
            "Turbo S Cabriolet",
        ),
        (
            "Modified, 31k-Mile 2001 Porsche 911 Turbo Coupe 6-Speed",
            "Porsche",
            "911",
            "Turbo Coupe 6-Speed",
        ),
        (
            "White Gold Metallic 1992 Porsche 911 Carrera 2 Coupe",
            "Porsche",
            "911",
            "Carrera 2 Coupe",
        ),
        (
            "RoW 1991 Porsche 911 Carrera 2 Coupe",
            "Porsche",
            "911",
            "Carrera 2 Coupe",
        ),
        (
            "Sequential-VIN 1965 Porsche 911 Coupes",
            "Porsche",
            "911",
            "Coupes",
        ),
    ]

    for title, make, model, trim in examples:
        lot, reason = parse_item({**SOLD_ITEM, "title": title})

        assert reason == ""
        assert lot is not None
        assert lot.make == make
        assert lot.model == model
        assert lot.trim == trim


def test_parse_vehicle_identity_handles_multi_word_and_hyphenated_makes() -> None:
    examples = [
        (
            "1997 Land Rover Defender 90 NAS",
            "Land Rover",
            "Defender",
            "90 NAS",
        ),
        (
            "2018 Mercedes-AMG GT R",
            "Mercedes-AMG",
            "GT",
            "R",
        ),
    ]

    for title, make, model, trim in examples:
        lot, reason = parse_item({**SOLD_ITEM, "title": title})

        assert reason == ""
        assert lot is not None
        assert lot.make == make
        assert lot.model == model
        assert lot.trim == trim


def test_parse_reserve_not_met_lot_uses_high_bid_not_sold_price() -> None:
    lot, reason = parse_item(RESERVE_NOT_MET_ITEM)

    assert lot is not None
    assert reason == ""
    assert lot.auction_status == "reserve_not_met"
    assert lot.sold_price is None
    assert lot.high_bid == 189000
    assert lot.ended_at == datetime(2026, 3, 27, tzinfo=UTC)


def test_skips_parts_listing_without_year() -> None:
    lot, reason = parse_item(
        {
            **SOLD_ITEM,
            "title": "Euro Porsche 996 GT3 Recaro Seats",
            "url": "https://bringatrailer.com/listing/seats-206/",
        }
    )

    assert lot is None
    assert reason == "parts_or_non_car"


def test_skips_non_car_parts_rvs_and_motorcycles() -> None:
    examples = [
        ("2002-2005 Acura NSX Wheels", "parts_or_non_car"),
        ("2019 Airstream Interstate Grand Tour", "parts_or_non_car"),
        ("1955 AJS 18CS Scrambler", "parts_or_non_car"),
        ("1962 Porsche-Diesel Junior 108L Tractor", "parts_or_non_car"),
    ]

    for title, expected_reason in examples:
        lot, reason = parse_item({**SOLD_ITEM, "title": title})

        assert lot is None
        assert reason == expected_reason


def test_model_directory_excludes_non_vehicle_paths() -> None:
    html = """
    <a class="previous-listing-image-link" href="https://bringatrailer.com/porsche/911/">
      <img alt="Porsche 911">
    </a>
    <a class="previous-listing-image-link" href="https://bringatrailer.com/ajs/18cs/">
      <img alt="AJS 18CS">
    </a>
    <a class="previous-listing-image-link" href="https://bringatrailer.com/airstream/interstate/">
      <img alt="Airstream Interstate">
    </a>
    <a class="previous-listing-image-link" href="https://bringatrailer.com/trailer/camper/">
      <img alt="Camper Trailer">
    </a>
    """

    assert extract_model_entries_from_html(html) == [("porsche-911", "Porsche 911", "porsche/911")]


def test_bat_detail_html_enriches_lot_fields_and_images() -> None:
    lot, reason = parse_item(SOLD_ITEM)
    assert lot is not None
    assert reason == ""

    html = """
    <html>
      <head>
        <script type="application/ld+json">
          {"@context":"http://schema.org","@type":"Product",
           "description":"Factory Weissach Package car.",
           "image":"https://bringatrailer.com/wp-content/uploads/hero.jpg?fit=940%2C626"}
        </script>
      </head>
      <body>
        <div class="post-excerpt">
          <p><img src="https://bringatrailer.com/wp-content/uploads/detail-1.jpg?w=620"></p>
          <p><img src="https://bringatrailer.com/wp-content/uploads/detail-2.jpg?w=620"></p>
        </div>
        <div class="essentials">
          <h2 class="title">BaT Essentials</h2>
          <div class="item item-seller"><strong>Seller</strong>:
            <a href="/member/example/">ExampleSeller</a>
          </div>
          <strong>Location</strong>:
            <a href="https://www.google.com/maps/place/Estero,%20Florida%2033928">
              Estero, Florida 33928
            </a>
          <div class="item"><strong>Listing Details</strong>
            <ul>
              <li>Chassis: WP0AF2A9XKS164665</li>
              <li>29k Miles</li>
              <li>4.0-Liter Flat-Six</li>
              <li>Seven-Speed PDK Transaxle</li>
              <li>Black Paint w/Lizard Green Accents</li>
              <li>Black &amp; Lizard Green Upholstery</li>
              <li>70-Liter Fuel Tank</li>
              <li>Owner's Manual</li>
              <li>Transmission Oil Temperature Gauge</li>
            </ul>
          </div>
          <div class="item additional"><strong>Private Party or Dealer</strong>: Private Party</div>
          <div class="item"><strong>Lot</strong> #235490</div>
        </div>
      </body>
    </html>
    """

    enrich_lot_from_detail_html(lot, html)

    assert lot.vin == "WP0AF2A9XKS164665"
    assert lot.mileage == 29000
    assert lot.engine == "4.0-Liter Flat-Six"
    assert lot.transmission == "Seven-Speed PDK Transaxle"
    assert lot.exterior_color == "Black Paint w/Lizard Green Accents"
    assert lot.interior_color == "Black & Lizard Green Upholstery"
    assert lot.location == "Estero, Florida 33928"
    assert lot.seller == "ExampleSeller"
    assert lot.detail_payload["lot_number"] == "235490"
    assert lot.detail_payload["seller_type"] == "Private Party"
    assert lot.detail_payload["description"] == "Factory Weissach Package car."
    assert "70-Liter Fuel Tank" in lot.vehicle_details["bat_listing_details"]
    assert lot.detail_html == html
    assert lot.detail_scraped_at is not None
    assert lot.image_urls[:3] == [
        SOLD_ITEM["image"],
        "https://bringatrailer.com/wp-content/uploads/hero.jpg",
        "https://bringatrailer.com/wp-content/uploads/detail-1.jpg",
    ]


def test_bat_targets_are_exposed() -> None:
    entries = get_url_entries()
    assert entries
    assert {"key", "label", "path"} == set(entries[0])


@patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock)
@patch("app.scrapers.bring_a_trailer.fetch_page_result", new_callable=AsyncMock)
async def test_bat_records_page_request_logs_and_zero_parse_anomaly(
    mock_fetch_page_result: AsyncMock,
    _mock_sleep: AsyncMock,
) -> None:
    mock_fetch_page_result.return_value = (
        [
            {
                **SOLD_ITEM,
                "title": "Euro Porsche 996 GT3 Recaro Seats",
                "url": "https://bringatrailer.com/listing/seats-206/",
            }
        ],
        {"items_total": 1, "page_current": 1, "pages_total": 1},
    )
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
    assert logs[0].skip_counts == {"parts_or_non_car": 1}
    assert any(anomaly.code == "zero_parsed_lots" for anomaly in anomalies)


@patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock)
@patch("app.scrapers.bring_a_trailer.fetch_page_result", new_callable=AsyncMock)
async def test_bat_does_not_emit_zero_parse_anomaly_for_duplicate_only_page(
    mock_fetch_page_result: AsyncMock,
    _mock_sleep: AsyncMock,
) -> None:
    mock_fetch_page_result.side_effect = [
        ([SOLD_ITEM], {"items_total": 1, "page_current": 1, "pages_total": 1}),
        ([SOLD_ITEM], {"items_total": 1, "page_current": 1, "pages_total": 1}),
    ]
    session = AsyncMock()
    session.add = MagicMock()

    class OverlappingTargetScraper(BringATrailerScraper):
        def _get_urls(self) -> list[tuple[str, str, str]]:
            return [
                ("porsche", "Porsche", "porsche"),
                ("porsche-911", "Porsche 911", "porsche/911"),
            ]

    lots = await OverlappingTargetScraper(session, None, selected_keys={"custom"}).scrape()

    added_objects = [call.args[0] for call in session.add.call_args_list]
    logs = [obj for obj in added_objects if isinstance(obj, ScrapeRequestLog)]
    anomalies = [obj for obj in added_objects if isinstance(obj, ScrapeAnomaly)]
    assert len(lots) == 1
    assert logs[1].parsed_lot_count == 0
    assert logs[1].metadata_json["duplicates"] == 1
    assert not any(anomaly.code == "zero_parsed_lots" for anomaly in anomalies)


def test_bat_extracts_completed_pagination_telemetry() -> None:
    html = """
    <script>
      var auctionsCompletedInitialData = {
        "base_filter": {"keyword_s": "Porsche", "items_type": "make"},
        "items": [],
        "items_total": 18413,
        "items_per_page": 24,
        "page_current": 1,
        "pages_total": 768
      };
    </script>
    """

    metadata = extract_completed_metadata_from_html(html)

    assert metadata == {
        "base_filter": {"keyword_s": "Porsche", "items_type": "make"},
        "items_total": 18413,
        "items_per_page": 24,
        "page_current": 1,
        "pages_total": 768,
    }


def test_bat_builds_show_more_params_from_base_filter() -> None:
    params = build_completed_results_params(
        {"keyword_s": "Porsche", "items_type": "make", "keyword_pages": [1, 2]},
        page=2,
        per_page=24,
    )

    assert params == [
        ("page", 2),
        ("per_page", 24),
        ("get_items", 1),
        ("get_stats", 0),
        ("sort", "td"),
        ("base_filter[keyword_s]", "Porsche"),
        ("base_filter[items_type]", "make"),
        ("base_filter[keyword_pages][]", 1),
        ("base_filter[keyword_pages][]", 2),
    ]


@patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock)
@patch("app.scrapers.bring_a_trailer.fetch_completed_results_page", new_callable=AsyncMock)
@patch("app.scrapers.bring_a_trailer.fetch_page_result", new_callable=AsyncMock)
async def test_bat_fetches_show_more_completed_result_pages(
    mock_fetch_page_result: AsyncMock,
    mock_fetch_completed_results_page: AsyncMock,
    _mock_sleep: AsyncMock,
) -> None:
    second_item = {
        **SOLD_ITEM,
        "id": 108526571,
        "url": "https://bringatrailer.com/listing/1987-porsche-928-s4-171/",
        "title": "1987 Porsche 928 S4",
    }
    mock_fetch_page_result.return_value = (
        [SOLD_ITEM],
        {
            "base_filter": {"keyword_s": "Porsche", "items_type": "make"},
            "items_total": 48,
            "items_per_page": 24,
            "page_current": 1,
            "pages_total": 2,
        },
    )
    mock_fetch_completed_results_page.return_value = (
        [second_item],
        {
            "items_total": 48,
            "items_per_page": 24,
            "page_current": 2,
            "pages_total": 2,
        },
    )
    session = AsyncMock()
    session.add = MagicMock()

    lots = await BringATrailerScraper(
        session,
        None,
        selected_keys={"porsche"},
        mode="backfill",
    ).scrape()

    assert [lot.source_auction_id for lot in lots] == ["108526570", "108526571"]
    mock_fetch_completed_results_page.assert_awaited_once()


@patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock)
@patch("app.scrapers.bring_a_trailer.fetch_detail_html", new_callable=AsyncMock)
async def test_bat_skips_recently_enriched_detail_pages(
    mock_fetch_detail_html: AsyncMock,
    _mock_sleep: AsyncMock,
) -> None:
    lot, reason = parse_item(SOLD_ITEM)
    assert lot is not None
    assert reason == ""

    existing = AuctionLot(
        source="bring_a_trailer",
        source_auction_id=lot.source_auction_id,
        canonical_url=lot.canonical_url,
        auction_status="sold",
        detail_scraped_at=datetime.now(UTC),
    )
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    session.execute.return_value = result
    session.add = MagicMock()

    enriched = await BringATrailerScraper(session)._enrich_lots_with_details(
        AsyncMock(),
        [lot],
        label="Porsche 911",
        page=1,
    )

    assert enriched == []
    mock_fetch_detail_html.assert_not_awaited()
    added_objects = [call.args[0] for call in session.add.call_args_list]
    logs = [obj for obj in added_objects if isinstance(obj, ScrapeRequestLog)]
    assert logs
    assert logs[0].action == "detail_page"
    assert logs[0].outcome == "skipped"


@patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock)
@patch("app.scrapers.bring_a_trailer.fetch_detail_html", new_callable=AsyncMock)
async def test_bat_logs_retry_after_when_detail_page_is_blocked(
    mock_fetch_detail_html: AsyncMock,
    _mock_sleep: AsyncMock,
) -> None:
    lot, reason = parse_item(SOLD_ITEM)
    assert lot is not None
    assert reason == ""

    request = httpx.Request("GET", lot.canonical_url)
    response = httpx.Response(429, request=request, headers={"Retry-After": "60"})
    mock_fetch_detail_html.side_effect = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=response,
    )
    session = AsyncMock()
    session.add = MagicMock()
    scraper = BringATrailerScraper(session)

    with pytest.raises(BlockedScrapeError):
        await scraper._fetch_detail_with_retries(
            AsyncMock(),
            lot=lot,
            label="Porsche 911",
            page=1,
        )

    added_objects = [call.args[0] for call in session.add.call_args_list]
    logs = [obj for obj in added_objects if isinstance(obj, ScrapeRequestLog)]
    anomalies = [obj for obj in added_objects if isinstance(obj, ScrapeAnomaly)]
    assert logs[0].outcome == "blocked"
    assert logs[0].retry_delay_seconds == 60.0
    assert logs[0].metadata_json["retry_after_seconds"] == 60.0
    assert anomalies[0].metadata_json["retry_after_seconds"] == 60.0
