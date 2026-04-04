"""Tests for the Bring a Trailer scraper.

Fixture-based tests use real HTML saved from BaT to guard against selector
drift. When BaT changes their HTML structure, update the fixture with:
    uv run python scripts/fetch_bat_fixture.py

Pure unit tests for parsing helpers use synthetic data and never need updating.
HTTP fetching is tested via a mocked httpx client.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "bat_porsche_911_gt3.html"

from app.scrapers.bat_parser import (
    extract_items_from_html,
    parse_color,
    parse_item,
    parse_mileage,
    parse_sold_text,
    parse_year,
)
from app.scrapers.bring_a_trailer import (
    BASE_URL,
    BringATrailerScraper,
    fetch_page,
    get_all_url_keys,
    get_url_entries,
)
from app.scrapers.makes import BAT_MAKES


# ─── Sample BaT JSON items (mirrors real site structure) ─────────────────────

SOLD_ITEM = {
    "active": False,
    "current_bid": 229000,
    "current_bid_formatted": "USD $229,000",
    "sold_text": "Sold for USD $229,000 <span> on 3/29/26 </span>",
    "title": "2019 Porsche 911 GT3 RS Weissach",
    "url": "https://bringatrailer.com/listing/2019-porsche-911-gt3-rs-weissach-97/",
    "id": 108526570,
    "year": None,
    "noreserve": False,
    "country": "United States",
}

SOLD_ITEM_2 = {
    "active": False,
    "current_bid": 123000,
    "sold_text": "Sold for USD $123,000 <span> on 3/26/26 </span>",
    "title": "32k-Mile 2015 Porsche 911 Turbo S Cabriolet",
    "url": "https://bringatrailer.com/listing/2015-porsche-911-turbo-s-cab/",
    "id": 999999,
}

SOLD_ITEM_WITH_MILEAGE = {
    "active": False,
    "current_bid": 189000,
    "current_bid_formatted": "USD $189,000",
    "sold_text": "Sold for USD $189,000 <span> on 3/27/26 </span>",
    "title": "11k-Mile 2016 Porsche 911 GT3 RS",
    "url": "https://bringatrailer.com/listing/2016-porsche-911-gt3-rs-103/",
    "id": 110742918,
    "year": None,
}

RESERVE_NOT_MET_ITEM = {
    "active": False,
    "current_bid": 189000,
    "sold_text": "Bid to USD $189,000 <span> on 3/27/26 </span>",
    "title": "11k-Mile 2016 Porsche 911 GT3 RS",
    "url": "https://bringatrailer.com/listing/2016-porsche-911-gt3-rs-103/",
    "id": 110742918,
}

PARTS_ITEM = {
    "active": False,
    "current_bid": 6900,
    "sold_text": "Sold for USD $6,900 <span> on 3/29/26 </span>",
    "title": "Euro Porsche 996 GT3 Recaro Seats",
    "url": "https://bringatrailer.com/listing/seats-206/",
    "id": 111121128,
}

ITEM_NO_YEAR = {
    "active": False,
    "current_bid": 5000,
    "sold_text": "Sold for USD $5,000 <span> on 3/25/26 </span>",
    "title": "Porsche GT3 Steering Wheel",
    "url": "https://bringatrailer.com/listing/steering-wheel-99/",
    "id": 99999999,
}

SOLD_ITEM_WITH_COLOR = {
    "active": False,
    "current_bid": 448000,
    "sold_text": "Sold for USD $448,000 <span> on 3/27/26 </span>",
    "title": "2k-Mile 2019 Porsche 911 GT3 RS Weissach Lava Orange",
    "url": "https://bringatrailer.com/listing/2019-gt3-rs-lava-orange/",
    "id": 112233445,
}

SOLD_ITEM_FOUR_DIGIT_YEAR = {
    "active": False,
    "current_bid": 100000,
    "sold_text": "Sold for USD $100,000 <span> on 12/15/2025 </span>",
    "title": "2022 Ferrari 488 Pista",
    "url": "https://bringatrailer.com/listing/2022-ferrari-488-pista/",
    "id": 88888888,
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _wrap_items_in_html(items: list[dict]) -> str:
    """Build a minimal HTML page embedding the auctionsCompletedInitialData JSON."""
    import json

    data = {"base_filter": {}, "items": items}
    return f"""
    <html><head></head><body>
    <script>
    var auctionsCompletedInitialData = {json.dumps(data)};
    </script>
    </body></html>
    """


def _mock_http_context(response):
    """Return patchers for httpx.AsyncClient and asyncio.sleep."""
    client_patch = patch("app.scrapers.bring_a_trailer.httpx.AsyncClient")
    sleep_patch = patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock)
    return client_patch, sleep_patch, response


def _setup_mock_client(MockClient, mock_response_or_side_effect):
    mock_client = AsyncMock()
    if callable(mock_response_or_side_effect) and not isinstance(mock_response_or_side_effect, httpx.Response):
        mock_client.get = AsyncMock(side_effect=mock_response_or_side_effect)
    else:
        mock_client.get = AsyncMock(return_value=mock_response_or_side_effect)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    MockClient.return_value = mock_client
    return mock_client


# ─── parse_year ──────────────────────────────────────────────────────────────

class TestParseYear:
    def test_standard_year(self) -> None:
        assert parse_year("2019 Porsche 911 GT3 RS Weissach") == 2019

    def test_year_after_mileage(self) -> None:
        assert parse_year("11k-Mile 2016 Porsche 911 GT3 RS") == 2016

    def test_no_year(self) -> None:
        assert parse_year("Euro Porsche 996 GT3 Recaro Seats") is None

    def test_year_1990s(self) -> None:
        assert parse_year("1997 Porsche 911 GT1") == 1997

    def test_ignores_non_year_numbers(self) -> None:
        assert parse_year("Euro Porsche 996 GT3 Seats") is None


# ─── parse_mileage ───────────────────────────────────────────────────────────

class TestParseMileage:
    def test_k_mile_shorthand(self) -> None:
        assert parse_mileage("11k-Mile 2016 Porsche 911 GT3 RS") == 11000

    def test_k_mile_decimal(self) -> None:
        assert parse_mileage("2.5k-Mile 2020 Ferrari F8") == 2500

    def test_full_number(self) -> None:
        assert parse_mileage("12,345-Mile 2019 Porsche 911") == 12345

    def test_no_mileage(self) -> None:
        assert parse_mileage("2019 Porsche 911 GT3 RS Weissach") is None

    def test_miles_with_space(self) -> None:
        assert parse_mileage("616-Mile 2018 Porsche 911 GT3") == 616


# ─── parse_sold_text ─────────────────────────────────────────────────────────

class TestParseSoldText:
    def test_sold_with_two_digit_year(self) -> None:
        is_sold, price, date = parse_sold_text(
            "Sold for USD $229,000 <span> on 3/29/26 </span>"
        )
        assert is_sold is True
        assert price == 229000
        assert date == datetime(2026, 3, 29, tzinfo=timezone.utc)

    def test_sold_with_four_digit_year(self) -> None:
        is_sold, price, date = parse_sold_text(
            "Sold for USD $100,000 <span> on 12/15/2025 </span>"
        )
        assert is_sold is True
        assert price == 100000
        assert date == datetime(2025, 12, 15, tzinfo=timezone.utc)

    def test_reserve_not_met(self) -> None:
        is_sold, price, date = parse_sold_text(
            "Bid to USD $189,000 <span> on 3/27/26 </span>"
        )
        assert is_sold is False
        assert price == 189000
        assert date == datetime(2026, 3, 27, tzinfo=timezone.utc)

    def test_empty_string(self) -> None:
        is_sold, price, date = parse_sold_text("")
        assert is_sold is False
        assert price is None
        assert date is None

    def test_low_price(self) -> None:
        is_sold, price, _ = parse_sold_text(
            "Sold for USD $6,900 <span> on 3/29/26 </span>"
        )
        assert is_sold is True
        assert price == 6900


# ─── parse_color ─────────────────────────────────────────────────────────────

class TestParseColor:
    def test_standard_color(self) -> None:
        assert parse_color("2019 Porsche 911 GT3 RS Blue") == "Blue"

    def test_compound_color(self) -> None:
        assert parse_color("Lava Orange 2019 GT3 RS") == "Lava Orange"

    def test_no_color(self) -> None:
        assert parse_color("2019 Porsche 911 GT3 RS Weissach") is None

    def test_guards_red(self) -> None:
        assert parse_color("Guards Red 2018 Porsche 911 GT3") == "Guards Red"

    def test_case_insensitive(self) -> None:
        assert parse_color("SHARK BLUE 2022 Porsche GT3") == "Shark Blue"


# ─── parse_item ──────────────────────────────────────────────────────────────

class TestParseItem:
    def test_sold_item_parsed(self) -> None:
        listing, reason = parse_item(SOLD_ITEM)
        assert listing is not None
        assert reason == ""
        assert listing.source == "bring_a_trailer"
        assert listing.sale_type == "auction"
        assert listing.year == 2019
        assert listing.sold_price == 229000
        assert listing.asking_price == 229000
        assert listing.is_sold is True
        assert listing.source_url == SOLD_ITEM["url"]
        assert listing.sold_at == datetime(2026, 3, 29, tzinfo=timezone.utc)
        assert listing.no_reserve is False
        assert listing.location == "United States"

    def test_sold_item_with_mileage(self) -> None:
        listing, _ = parse_item(SOLD_ITEM_WITH_MILEAGE)
        assert listing is not None
        assert listing.mileage == 11000
        assert listing.year == 2016

    def test_reserve_not_met_excluded(self) -> None:
        listing, reason = parse_item(RESERVE_NOT_MET_ITEM)
        assert listing is None
        assert reason == "not_sold"

    def test_no_year_excluded(self) -> None:
        listing, reason = parse_item(ITEM_NO_YEAR)
        assert listing is None
        assert reason == "no_year"

    def test_parts_item_no_year_excluded(self) -> None:
        listing, reason = parse_item(PARTS_ITEM)
        assert listing is None
        assert reason == "no_year"

    def test_color_extracted(self) -> None:
        listing, _ = parse_item(SOLD_ITEM_WITH_COLOR)
        assert listing is not None
        assert listing.color == "Lava Orange"
        assert listing.mileage == 2000

    def test_four_digit_date_year(self) -> None:
        listing, _ = parse_item(SOLD_ITEM_FOUR_DIGIT_YEAR)
        assert listing is not None
        assert listing.sold_at == datetime(2025, 12, 15, tzinfo=timezone.utc)

    def test_raw_data_preserved(self) -> None:
        listing, _ = parse_item(SOLD_ITEM)
        assert listing is not None
        assert listing.raw_data["bat_id"] == 108526570
        assert listing.raw_data["title"] == SOLD_ITEM["title"]

    def test_empty_title_excluded(self) -> None:
        listing, reason = parse_item({**SOLD_ITEM, "title": ""})
        assert listing is None
        assert reason == "no_title"

    def test_empty_url_excluded(self) -> None:
        listing, reason = parse_item({**SOLD_ITEM, "url": ""})
        assert listing is None
        assert reason == "no_url"

    def test_zero_price_excluded(self) -> None:
        listing, reason = parse_item(
            {**SOLD_ITEM, "sold_text": "Sold for USD $0 <span> on 3/29/26 </span>"}
        )
        assert listing is None
        assert reason == "no_price"

    def test_no_reserve_true(self) -> None:
        listing, _ = parse_item({**SOLD_ITEM, "noreserve": True})
        assert listing is not None
        assert listing.no_reserve is True

    def test_no_reserve_defaults_false_when_absent(self) -> None:
        item = {k: v for k, v in SOLD_ITEM.items() if k != "noreserve"}
        listing, _ = parse_item(item)
        assert listing is not None
        assert listing.no_reserve is False

    def test_location_none_when_country_absent(self) -> None:
        item = {k: v for k, v in SOLD_ITEM.items() if k != "country"}
        listing, _ = parse_item(item)
        assert listing is not None
        assert listing.location is None


# ─── get_all_url_keys / get_url_entries ──────────────────────────────────────

class TestUrlHelpers:
    def test_get_all_url_keys_matches_bat_makes(self) -> None:
        keys = get_all_url_keys()
        assert len(keys) == len(BAT_MAKES)
        assert keys[0] == BAT_MAKES[0][0]

    def test_get_url_entries_returns_dicts(self) -> None:
        entries = get_url_entries()
        assert len(entries) == len(BAT_MAKES)
        first = entries[0]
        assert "key" in first and "label" in first and "path" in first

    def test_url_keys_are_unique(self) -> None:
        keys = get_all_url_keys()
        assert len(keys) == len(set(keys))


# ─── extract_items_from_html ─────────────────────────────────────────────────

class TestExtractItemsFromHtml:
    def test_extracts_items(self) -> None:
        html = _wrap_items_in_html([SOLD_ITEM, RESERVE_NOT_MET_ITEM])
        items = extract_items_from_html(html)
        assert len(items) == 2
        assert items[0]["title"] == SOLD_ITEM["title"]

    def test_no_data_returns_empty(self) -> None:
        assert extract_items_from_html("<html></html>") == []

    def test_malformed_json_returns_empty(self) -> None:
        html = "<script>var auctionsCompletedInitialData = {not valid json};</script>"
        assert extract_items_from_html(html) == []


# ─── Fixture loader ──────────────────────────────────────────────────────────

@pytest.fixture
def porsche_911_gt3_html() -> str:
    """Real BaT HTML for the Porsche 911 GT3 completed auctions page."""
    return FIXTURE_PATH.read_text(encoding="utf-8")


# ─── Fixture-based extraction tests ─────────────────────────────────────────

class TestExtractItemsFromFixture:
    def test_returns_items(self, porsche_911_gt3_html: str) -> None:
        """Fixture HTML must yield at least one item dict."""
        items = extract_items_from_html(porsche_911_gt3_html)
        assert len(items) > 0, (
            "extract_items_from_html returned 0 items on real fixture HTML — "
            "BaT may have changed their HTML structure. "
            "Re-run scripts/fetch_bat_fixture.py to update the fixture."
        )

    def test_items_have_required_fields(self, porsche_911_gt3_html: str) -> None:
        items = extract_items_from_html(porsche_911_gt3_html)
        for item in items:
            assert "title" in item, f"missing title in {item}"
            assert "url" in item, f"missing url in {item}"
            assert "sold_text" in item, f"missing sold_text in {item}"

    def test_urls_point_to_bat(self, porsche_911_gt3_html: str) -> None:
        items = extract_items_from_html(porsche_911_gt3_html)
        for item in items:
            assert item["url"].startswith("https://bringatrailer.com/listing/"), (
                f"Unexpected URL: {item['url']}"
            )

    def test_has_sold_items(self, porsche_911_gt3_html: str) -> None:
        items = extract_items_from_html(porsche_911_gt3_html)
        sold = [i for i in items if i.get("sold_text", "").startswith("Sold")]
        assert len(sold) > 0, "No confirmed sold items found in fixture — check fixture or BaT structure."

    def test_parse_item_from_fixture(self, porsche_911_gt3_html: str) -> None:
        items = extract_items_from_html(porsche_911_gt3_html)
        parsed, skipped = [], {}
        for item in items:
            listing, reason = parse_item(item)
            if listing is not None:
                parsed.append(listing)
            else:
                skipped[reason] = skipped.get(reason, 0) + 1

        assert len(parsed) > 0, f"No listings parsed from fixture. Skip reasons: {skipped}"

        first = parsed[0]
        assert first.source == "bring_a_trailer"
        assert first.sale_type == "auction"
        assert first.is_sold is True
        assert first.sold_price is not None and first.sold_price > 0
        assert first.asking_price == first.sold_price  # BaT: asking = hammer price
        assert first.year is not None and first.year >= 2000  # GT3 is post-2000
        assert first.source_url.startswith("https://bringatrailer.com/listing/")

    def test_parsed_prices_are_sane(self, porsche_911_gt3_html: str) -> None:
        items = extract_items_from_html(porsche_911_gt3_html)
        prices = []
        for item in items:
            listing, _ = parse_item(item)
            if listing is not None:
                prices.append(listing.sold_price)
        assert len(prices) > 0
        # 911 GT3s should clear $50k
        assert all(p > 50_000 for p in prices), f"Unexpectedly low prices: {prices}"


# ─── fetch_page (mocked HTTP) ───────────────────────────────────────────────

class TestFetchPage:
    async def test_returns_items_from_response(self) -> None:
        html = _wrap_items_in_html([SOLD_ITEM])
        mock_response = httpx.Response(200, text=html, request=httpx.Request("GET", "http://test"))

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_response)

        items = await fetch_page(client, "porsche")
        assert len(items) == 1
        assert items[0]["title"] == SOLD_ITEM["title"]
        client.get.assert_called_once()
        call_url = client.get.call_args[0][0]
        assert call_url == f"{BASE_URL}/porsche/"


# ─── BringATrailerScraper.scrape ─────────────────────────────────────────────

class TestBringATrailerScraper:
    async def test_scrape_deduplicates_across_urls(self) -> None:
        """Same listing appearing in two URL paths should only appear once."""
        html = _wrap_items_in_html([SOLD_ITEM])
        mock_response = httpx.Response(200, text=html, request=httpx.Request("GET", "http://test"))

        mock_session = AsyncMock()
        scraper = BringATrailerScraper(mock_session)

        with patch("app.scrapers.bring_a_trailer.httpx.AsyncClient") as MockClient:
            _setup_mock_client(MockClient, mock_response)
            with patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        assert len(listings) == 1
        assert listings[0].source_url == SOLD_ITEM["url"]

    async def test_scrape_filters_unsold(self) -> None:
        """Reserve-not-met items should not appear in results."""
        html = _wrap_items_in_html([RESERVE_NOT_MET_ITEM, PARTS_ITEM])
        mock_response = httpx.Response(200, text=html, request=httpx.Request("GET", "http://test"))

        mock_session = AsyncMock()
        scraper = BringATrailerScraper(mock_session)

        with patch("app.scrapers.bring_a_trailer.httpx.AsyncClient") as MockClient:
            _setup_mock_client(MockClient, mock_response)
            with patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        assert len(listings) == 0

    async def test_scrape_continues_on_http_error(self) -> None:
        """A failed URL should not abort the entire scrape."""
        html = _wrap_items_in_html([SOLD_ITEM])
        ok_response = httpx.Response(200, text=html, request=httpx.Request("GET", "http://test"))

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.HTTPStatusError(
                    "Server error",
                    request=httpx.Request("GET", "http://test"),
                    response=httpx.Response(500),
                )
            return ok_response

        mock_session = AsyncMock()
        scraper = BringATrailerScraper(mock_session)

        with patch("app.scrapers.bring_a_trailer.httpx.AsyncClient") as MockClient:
            _setup_mock_client(MockClient, mock_get)
            with patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        assert len(listings) >= 1

    async def test_selected_keys_filters_urls(self) -> None:
        """Only selected URL keys should be fetched."""
        html = _wrap_items_in_html([SOLD_ITEM])
        mock_response = httpx.Response(200, text=html, request=httpx.Request("GET", "http://test"))

        mock_session = AsyncMock()
        scraper = BringATrailerScraper(
            mock_session, selected_keys={"porsche", "ferrari"}
        )

        with patch("app.scrapers.bring_a_trailer.httpx.AsyncClient") as MockClient:
            mock_client = _setup_mock_client(MockClient, mock_response)
            with patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        # Should have fetched exactly 2 URLs
        assert mock_client.get.call_count == 2

    async def test_empty_selected_keys_returns_nothing(self) -> None:
        """Passing an empty set should scrape nothing."""
        mock_session = AsyncMock()
        scraper = BringATrailerScraper(mock_session, selected_keys=set())

        with patch("app.scrapers.bring_a_trailer.httpx.AsyncClient") as MockClient:
            mock_client = _setup_mock_client(
                MockClient,
                httpx.Response(200, text="<html></html>", request=httpx.Request("GET", "http://test")),
            )
            with patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        assert len(listings) == 0
        assert mock_client.get.call_count == 0

    async def test_cancel_stops_after_current_page(self) -> None:
        """Setting the cancel event should stop the scrape early."""
        html = _wrap_items_in_html([SOLD_ITEM])
        mock_response = httpx.Response(200, text=html, request=httpx.Request("GET", "http://test"))

        cancel_event = asyncio.Event()

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Cancel after the first page is fetched
            if call_count == 1:
                cancel_event.set()
            return mock_response

        mock_session = AsyncMock()
        scraper = BringATrailerScraper(
            mock_session, cancel_event=cancel_event
        )

        with patch("app.scrapers.bring_a_trailer.httpx.AsyncClient") as MockClient:
            _setup_mock_client(MockClient, mock_get)
            with patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        # Should have fetched page 1, then stopped before page 2
        assert call_count == 1
        assert len(listings) == 1

    async def test_none_selected_keys_scrapes_all(self) -> None:
        """selected_keys=None (the default) should scrape all URLs."""
        html = _wrap_items_in_html([SOLD_ITEM])
        mock_response = httpx.Response(200, text=html, request=httpx.Request("GET", "http://test"))

        mock_session = AsyncMock()
        scraper = BringATrailerScraper(mock_session)

        with patch("app.scrapers.bring_a_trailer.httpx.AsyncClient") as MockClient:
            mock_client = _setup_mock_client(MockClient, mock_response)
            with patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock):
                await scraper.scrape()

        assert mock_client.get.call_count == len(BAT_MAKES)

    async def test_scrape_returns_multiple_unique_listings(self) -> None:
        """Different items from different pages should all be returned."""
        html = _wrap_items_in_html([SOLD_ITEM, SOLD_ITEM_2])
        mock_response = httpx.Response(200, text=html, request=httpx.Request("GET", "http://test"))

        mock_session = AsyncMock()
        # Scrape only 1 URL to avoid dedup collapsing across pages
        scraper = BringATrailerScraper(
            mock_session, selected_keys={"porsche"}
        )

        with patch("app.scrapers.bring_a_trailer.httpx.AsyncClient") as MockClient:
            _setup_mock_client(MockClient, mock_response)
            with patch("app.scrapers.bring_a_trailer.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        assert len(listings) == 2
        urls = {l.source_url for l in listings}
        assert SOLD_ITEM["url"] in urls
        assert SOLD_ITEM_2["url"] in urls
