"""Tests for the Cars.com scraper.

Tests the pure parsing logic (no network calls). HTTP fetching is mocked
via patching curl_cffi and asyncio.sleep.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.cars_com import (
    BASE_URL,
    CARS_COM_URLS,
    CarsComScraper,
    build_search_url,
    extract_listings_from_html,
    get_all_url_keys,
    get_url_entries,
    has_next_page,
    parse_color,
    parse_listing,
    parse_mileage,
    parse_price,
    parse_year,
)


# ─── Sample HTML fragments ──────────────────────────────────────────────────

LISTING_CARD_HTML = """
<div class="vehicle-card" data-test="vehicleCard">
  <a href="/vehicle/detail/abc-123/">
    <h2 class="title">2019 Porsche 911 GT3 RS</h2>
  </a>
  <span class="primary-price">$229,000</span>
  <div class="mileage">12,345 mi.</div>
  <div class="dealer-name">Exotic Motors</div>
  <p class="stock-type">Used</p>
</div>
"""

LISTING_CARD_NO_PRICE = """
<div class="vehicle-card" data-test="vehicleCard">
  <a href="/vehicle/detail/def-456/">
    <h2 class="title">2020 Ferrari 488 Pista</h2>
  </a>
  <span class="primary-price">Call for Price</span>
  <div class="mileage">5,000 mi.</div>
  <div class="dealer-name">Ferrari of Chicago</div>
  <p class="stock-type">Used</p>
</div>
"""

LISTING_CARD_2 = """
<div class="vehicle-card" data-test="vehicleCard">
  <a href="/vehicle/detail/ghi-789/">
    <h2 class="title">2022 Lamborghini Huracan EVO</h2>
  </a>
  <span class="primary-price">$319,900</span>
  <div class="mileage">3,200 mi.</div>
  <div class="dealer-name">Lambo Chicago</div>
  <p class="stock-type">Used</p>
</div>
"""

NEXT_PAGE_HTML = '<a class="next-page" href="/shopping/results/?page=2">Next</a>'
NO_NEXT_PAGE_HTML = '<div class="pagination"><!-- no next --></div>'


def _wrap_cards(*cards: str, has_next: bool = False) -> str:
    """Wrap listing card fragments in a minimal page HTML."""
    pagination = NEXT_PAGE_HTML if has_next else NO_NEXT_PAGE_HTML
    return f"""
    <html><body>
    {''.join(cards)}
    <div id="pagination">{pagination}</div>
    </body></html>
    """


# ─── parse_price ─────────────────────────────────────────────────────────────

class TestParsePrice:
    def test_standard_price(self) -> None:
        assert parse_price("$229,000") == 229000

    def test_no_dollar_sign(self) -> None:
        assert parse_price("229000") == 229000

    def test_call_for_price(self) -> None:
        assert parse_price("Call for Price") is None

    def test_request_a_quote(self) -> None:
        assert parse_price("Request a Quote") is None

    def test_empty_string(self) -> None:
        assert parse_price("") is None

    def test_price_with_spaces(self) -> None:
        assert parse_price(" $ 99,500 ") == 99500


# ─── parse_year ──────────────────────────────────────────────────────────────

class TestParseYear:
    def test_standard_year(self) -> None:
        assert parse_year("2019 Porsche 911 GT3 RS") == 2019

    def test_no_year(self) -> None:
        assert parse_year("Porsche 911 GT3 Parts") is None

    def test_year_1990s(self) -> None:
        assert parse_year("1997 Porsche 911 GT1") == 1997


# ─── parse_mileage ───────────────────────────────────────────────────────────

class TestParseMileage:
    def test_standard_mileage(self) -> None:
        assert parse_mileage("12,345 mi.") == 12345

    def test_mileage_no_comma(self) -> None:
        assert parse_mileage("500 mi") == 500

    def test_mileage_miles_word(self) -> None:
        assert parse_mileage("12345 miles") == 12345

    def test_no_mileage(self) -> None:
        assert parse_mileage("New vehicle") is None


# ─── parse_color ─────────────────────────────────────────────────────────────

class TestParseColor:
    def test_standard_color(self) -> None:
        assert parse_color("2019 Porsche 911 GT3 RS Blue") == "Blue"

    def test_nardo_gray(self) -> None:
        assert parse_color("Nardo Gray 2021 Audi R8") == "Nardo Gray"

    def test_no_color(self) -> None:
        assert parse_color("2019 Porsche 911 GT3 RS Weissach") is None


# ─── build_search_url ────────────────────────────────────────────────────────

class TestBuildSearchUrl:
    def test_default_page(self) -> None:
        url = build_search_url("porsche", "porsche-911")
        assert "makes[]=porsche" in url
        assert "models[]=porsche-911" in url
        assert "page=1" in url
        assert "stock_type=used" in url
        assert "maximum_distance=all" in url

    def test_page_number(self) -> None:
        url = build_search_url("ferrari", "ferrari-488_gtb", page=3)
        assert "page=3" in url
        assert "models[]=ferrari-488_gtb" in url


# ─── extract_listings_from_html ──────────────────────────────────────────────

class TestExtractListingsFromHtml:
    def test_extracts_single_card(self) -> None:
        html = _wrap_cards(LISTING_CARD_HTML)
        items = extract_listings_from_html(html)
        assert len(items) == 1
        assert items[0]["title"] == "2019 Porsche 911 GT3 RS"
        assert items[0]["price_text"] == "$229,000"
        assert items[0]["mileage_text"] == "12,345 mi."
        assert items[0]["url"] == "/vehicle/detail/abc-123/"
        assert items[0]["dealer"] == "Exotic Motors"

    def test_extracts_multiple_cards(self) -> None:
        html = _wrap_cards(LISTING_CARD_HTML, LISTING_CARD_2)
        items = extract_listings_from_html(html)
        assert len(items) == 2

    def test_empty_page(self) -> None:
        html = "<html><body>No results found</body></html>"
        assert extract_listings_from_html(html) == []

    def test_card_without_link_skipped(self) -> None:
        bad_card = '<div class="vehicle-card"><h2 class="title">No Link Car</h2></div>'
        html = _wrap_cards(bad_card, LISTING_CARD_HTML)
        items = extract_listings_from_html(html)
        assert len(items) == 1  # only the good card


# ─── has_next_page ───────────────────────────────────────────────────────────

class TestHasNextPage:
    def test_with_next_page(self) -> None:
        html = _wrap_cards(LISTING_CARD_HTML, has_next=True)
        assert has_next_page(html) is True

    def test_without_next_page(self) -> None:
        html = _wrap_cards(LISTING_CARD_HTML, has_next=False)
        assert has_next_page(html) is False


# ─── parse_listing ───────────────────────────────────────────────────────────

class TestParseListing:
    def test_valid_listing(self) -> None:
        item = {
            "title": "2019 Porsche 911 GT3 RS",
            "price_text": "$229,000",
            "mileage_text": "12,345 mi.",
            "url": "/vehicle/detail/abc-123/",
            "dealer": "Exotic Motors",
            "stock_type": "used",
        }
        listing, reason = parse_listing(item)
        assert listing is not None
        assert reason == ""
        assert listing.source == "cars_com"
        assert listing.sale_type == "listing"
        assert listing.year == 2019
        assert listing.asking_price == 229000
        assert listing.sold_price is None
        assert listing.is_sold is False
        assert listing.sold_at is None
        assert listing.mileage == 12345
        assert listing.source_url == f"{BASE_URL}/vehicle/detail/abc-123/"

    def test_no_price_skipped(self) -> None:
        item = {
            "title": "2020 Ferrari 488 Pista",
            "price_text": "Call for Price",
            "mileage_text": "5,000 mi.",
            "url": "/vehicle/detail/def-456/",
            "dealer": "",
            "stock_type": "used",
        }
        listing, reason = parse_listing(item)
        assert listing is None
        assert reason == "no_price"

    def test_no_title_skipped(self) -> None:
        listing, reason = parse_listing({"title": "", "url": "/v/1/", "price_text": "$100"})
        assert listing is None
        assert reason == "no_title"

    def test_no_url_skipped(self) -> None:
        listing, reason = parse_listing({"title": "2020 Car", "url": "", "price_text": "$100"})
        assert listing is None
        assert reason == "no_url"

    def test_no_year_skipped(self) -> None:
        listing, reason = parse_listing({
            "title": "Porsche Parts Kit",
            "url": "/vehicle/detail/xyz/",
            "price_text": "$500",
        })
        assert listing is None
        assert reason == "no_year"

    def test_raw_data_preserved(self) -> None:
        item = {
            "title": "2022 McLaren 720S",
            "price_text": "$289,000",
            "mileage_text": "1,000 mi.",
            "url": "/vehicle/detail/mcl-720/",
            "dealer": "McLaren Chicago",
            "stock_type": "used",
        }
        listing, _ = parse_listing(item)
        assert listing is not None
        assert listing.raw_data["dealer"] == "McLaren Chicago"
        assert listing.raw_data["price_text"] == "$289,000"

    def test_color_extracted_from_title(self) -> None:
        item = {
            "title": "2019 Porsche 911 GT3 RS Lava Orange",
            "price_text": "$350,000",
            "url": "/vehicle/detail/lava/",
            "mileage_text": "",
            "dealer": "",
            "stock_type": "",
        }
        listing, _ = parse_listing(item)
        assert listing is not None
        assert listing.color == "Lava Orange"


# ─── URL helpers ─────────────────────────────────────────────────────────────

class TestUrlHelpers:
    def test_get_all_url_keys_matches(self) -> None:
        keys = get_all_url_keys()
        assert len(keys) == len(CARS_COM_URLS)
        assert keys[0] == CARS_COM_URLS[0][0]

    def test_get_url_entries_structure(self) -> None:
        entries = get_url_entries()
        assert len(entries) == len(CARS_COM_URLS)
        first = entries[0]
        assert "key" in first and "label" in first and "make" in first and "model" in first

    def test_url_keys_are_unique(self) -> None:
        keys = get_all_url_keys()
        assert len(keys) == len(set(keys))


# ─── CarsComScraper.scrape (mocked HTTP) ────────────────────────────────────

def _mock_fetch(html: str):
    """Return a patched fetch_page that always returns the given HTML."""
    async def _fetch(url: str) -> str:
        return html
    return _fetch


def _mock_fetch_side_effect(pages: dict[int, str]):
    """Return a fetch mock that returns different HTML per page number."""
    call_count = 0

    async def _fetch(url: str) -> str:
        nonlocal call_count
        call_count += 1
        # Extract page number from URL
        import re
        m = re.search(r"page=(\d+)", url)
        page = int(m.group(1)) if m else 1
        return pages.get(page, "<html></html>")

    return _fetch


class TestCarsComScraper:
    async def test_selected_keys_filters(self) -> None:
        """Only selected model searches should be fetched."""
        html = _wrap_cards(LISTING_CARD_HTML)
        fetch_calls = []

        async def mock_fetch(url: str) -> str:
            fetch_calls.append(url)
            return html

        mock_session = AsyncMock()
        scraper = CarsComScraper(
            mock_session,
            selected_keys={"porsche-911", "ferrari-488"},
        )

        with patch("app.scrapers.cars_com.fetch_page", side_effect=mock_fetch):
            with patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        # 2 models, each 1 page (no next page in our HTML)
        assert len(fetch_calls) == 2
        assert any("porsche" in url for url in fetch_calls)
        assert any("ferrari" in url for url in fetch_calls)

    async def test_empty_selected_keys_scrapes_nothing(self) -> None:
        mock_session = AsyncMock()
        scraper = CarsComScraper(mock_session, selected_keys=set())
        listings = await scraper.scrape()
        assert len(listings) == 0

    async def test_cancel_stops_early(self) -> None:
        html = _wrap_cards(LISTING_CARD_HTML)
        cancel_event = asyncio.Event()
        fetch_count = 0

        async def mock_fetch(url: str) -> str:
            nonlocal fetch_count
            fetch_count += 1
            if fetch_count == 1:
                cancel_event.set()
            return html

        mock_session = AsyncMock()
        scraper = CarsComScraper(
            mock_session,
            cancel_event=cancel_event,
        )

        with patch("app.scrapers.cars_com.fetch_page", side_effect=mock_fetch):
            with patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        # Should have fetched 1 page then stopped
        assert fetch_count == 1
        assert len(listings) == 1

    async def test_pagination_stops_on_empty(self) -> None:
        """If a page returns no listings, stop pagination for that model."""
        page1_html = _wrap_cards(LISTING_CARD_HTML, has_next=True)
        page2_html = _wrap_cards()  # empty
        fetch_calls = []

        async def mock_fetch(url: str) -> str:
            fetch_calls.append(url)
            if "page=2" in url:
                return page2_html
            return page1_html

        mock_session = AsyncMock()
        scraper = CarsComScraper(
            mock_session,
            selected_keys={"porsche-911"},
        )

        with patch("app.scrapers.cars_com.fetch_page", side_effect=mock_fetch):
            with patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        # Page 1 fetched, page 2 fetched (empty → stop), no page 3
        assert len(fetch_calls) == 2
        assert len(listings) == 1

    async def test_continues_on_http_error(self) -> None:
        """HTTP error on one model should not abort the entire scrape."""
        html = _wrap_cards(LISTING_CARD_HTML)
        call_count = 0

        async def mock_fetch(url: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection refused")
            return html

        mock_session = AsyncMock()
        scraper = CarsComScraper(
            mock_session,
            selected_keys={"porsche-911", "ferrari-488"},
        )

        with patch("app.scrapers.cars_com.fetch_page", side_effect=mock_fetch):
            with patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        # First model errors, second succeeds
        assert len(listings) == 1

    async def test_deduplication_within_scrape(self) -> None:
        """Same listing URL across models should only appear once."""
        html = _wrap_cards(LISTING_CARD_HTML)

        mock_session = AsyncMock()
        scraper = CarsComScraper(
            mock_session,
            selected_keys={"porsche-911", "porsche-718"},
        )

        with patch("app.scrapers.cars_com.fetch_page", return_value=html):
            with patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        # Same card HTML → same URL → deduplicated to 1
        assert len(listings) == 1

    async def test_listing_fields_are_correct(self) -> None:
        """All Cars.com listings must have sold_price=None, is_sold=False, sale_type=listing."""
        html = _wrap_cards(LISTING_CARD_HTML, LISTING_CARD_2)

        mock_session = AsyncMock()
        scraper = CarsComScraper(
            mock_session,
            selected_keys={"porsche-911"},
        )

        with patch("app.scrapers.cars_com.fetch_page", return_value=html):
            with patch("app.scrapers.cars_com.asyncio.sleep", new_callable=AsyncMock):
                listings = await scraper.scrape()

        for listing in listings:
            assert listing.sold_price is None
            assert listing.is_sold is False
            assert listing.sale_type == "listing"
            assert listing.source == "cars_com"
            assert listing.sold_at is None
