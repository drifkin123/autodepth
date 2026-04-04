"""Integration tests: fixture files → parser → save_listing() → real PostgreSQL.

These tests exercise the full scraper persistence pipeline without making any
network requests. Each test:
  1. Reads a real fixture file from tests/fixtures/
  2. Parses it with the production parser (same code used in live scrapes)
  3. Feeds the resulting ScrapedListing objects through BaseScraper.save_listing()
     against a real test PostgreSQL database
  4. Queries the database and asserts the correct rows were written

Requires a running PostgreSQL instance. Tests are skipped automatically if the
database is unreachable. Start one with:
    docker-compose up -d

Set TEST_DATABASE_URL to use a different database (see conftest.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_sale import VehicleSale
from app.scrapers.base import BaseScraper, ScrapedListing

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Minimal concrete scraper ─────────────────────────────────────────────────
# BaseScraper is abstract; we need a concrete subclass just to call save_listing().

class _TestScraper(BaseScraper):
    source = "test"

    async def scrape(self) -> list[ScrapedListing]:  # pragma: no cover
        return []


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _count_sales(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(VehicleSale))
    return result.scalar_one()


async def _all_sales(session: AsyncSession) -> list[VehicleSale]:
    result = await session.execute(select(VehicleSale))
    return list(result.scalars().all())


async def _save_listings(
    scraper: BaseScraper, listings: list[ScrapedListing | None]
) -> tuple[int, int]:
    """Save all non-None listings. Returns (inserted, skipped)."""
    inserted = skipped = 0
    for listing in listings:
        if listing is None:
            skipped += 1
            continue
        saved = await scraper.save_listing(listing)
        if saved:
            inserted += 1
        else:
            skipped += 1
    await scraper.session.commit()
    return inserted, skipped


# ── BaT integration tests ────────────────────────────────────────────────────

class TestBatIntegration:
    async def test_bat_fixture_inserts_vehicle_sales(
        self, integration_session: AsyncSession
    ) -> None:
        """Parsing the BaT fixture produces sold auction rows in vehicle_sales."""
        from app.scrapers.bat_parser import extract_items_from_html, parse_item

        html = (FIXTURES_DIR / "bat_porsche_911_gt3.html").read_text()
        items = extract_items_from_html(html)
        assert items, "Fixture should contain auction items"

        listings = [parse_item(item)[0] for item in items]
        scraper = _TestScraper(integration_session)
        inserted, _ = await _save_listings(scraper, listings)

        assert inserted > 0, "At least one listing should have been inserted"

        sales = await _all_sales(integration_session)
        assert len(sales) == inserted

    async def test_bat_sale_fields_are_correct(
        self, integration_session: AsyncSession
    ) -> None:
        """VehicleSale rows from BaT have the expected field values."""
        from app.scrapers.bat_parser import extract_items_from_html, parse_item

        html = (FIXTURES_DIR / "bat_porsche_911_gt3.html").read_text()
        items = extract_items_from_html(html)
        listings = [parse_item(item)[0] for item in items]

        scraper = _TestScraper(integration_session)
        await _save_listings(scraper, listings)

        sales = await _all_sales(integration_session)
        sale = sales[0]

        assert sale.source == "bring_a_trailer"
        assert sale.sale_type == "auction"
        assert sale.is_sold is True
        assert sale.sold_price is not None and sale.sold_price > 0
        assert sale.asking_price == sale.sold_price  # BaT: asking == hammer price
        assert sale.year is not None and 1990 <= sale.year <= 2030
        assert sale.car_id is not None  # should fuzzy-match Porsche 911 GT3 RS
        assert sale.source_url.startswith("https://bringatrailer.com")

    async def test_bat_deduplication_prevents_double_insert(
        self, integration_session: AsyncSession
    ) -> None:
        """Saving the same BaT fixture twice inserts each listing only once."""
        from app.scrapers.bat_parser import extract_items_from_html, parse_item

        html = (FIXTURES_DIR / "bat_porsche_911_gt3.html").read_text()
        items = extract_items_from_html(html)
        listings = [parse_item(item)[0] for item in items]

        scraper = _TestScraper(integration_session)

        first_inserted, _ = await _save_listings(scraper, listings)
        assert first_inserted > 0

        # Second pass — every URL is now a duplicate
        second_inserted, _ = await _save_listings(scraper, listings)
        assert second_inserted == 0

        assert await _count_sales(integration_session) == first_inserted


# ── Cars & Bids integration tests ────────────────────────────────────────────

class TestCarsAndBidsIntegration:
    async def test_cab_fixture_inserts_vehicle_sales(
        self, integration_session: AsyncSession
    ) -> None:
        """Parsing the Cars & Bids fixture produces sold auction rows."""
        from app.scrapers.cars_and_bids_parser import parse_auction

        items = json.loads((FIXTURES_DIR / "cars_and_bids_porsche_911_gt3.json").read_text())
        assert items, "Fixture should contain auction items"

        listings = [parse_auction(item)[0] for item in items]
        scraper = _TestScraper(integration_session)
        inserted, _ = await _save_listings(scraper, listings)

        assert inserted > 0, "At least one listing should have been inserted"

        sales = await _all_sales(integration_session)
        assert len(sales) == inserted

    async def test_cab_sale_fields_are_correct(
        self, integration_session: AsyncSession
    ) -> None:
        """VehicleSale rows from Cars & Bids have the expected field values."""
        from app.scrapers.cars_and_bids_parser import parse_auction

        items = json.loads((FIXTURES_DIR / "cars_and_bids_porsche_911_gt3.json").read_text())
        listings = [parse_auction(item)[0] for item in items]

        scraper = _TestScraper(integration_session)
        await _save_listings(scraper, listings)

        sales = await _all_sales(integration_session)
        sale = sales[0]

        assert sale.source == "cars_and_bids"
        assert sale.sale_type == "auction"
        assert sale.is_sold is True
        assert sale.sold_price is not None and sale.sold_price > 0
        assert sale.year is not None and 1990 <= sale.year <= 2030
        assert sale.source_url.startswith("https://carsandbids.com")

    async def test_cab_deduplication_prevents_double_insert(
        self, integration_session: AsyncSession
    ) -> None:
        """Saving the same C&B fixture twice inserts each listing only once."""
        from app.scrapers.cars_and_bids_parser import parse_auction

        items = json.loads((FIXTURES_DIR / "cars_and_bids_porsche_911_gt3.json").read_text())
        listings = [parse_auction(item)[0] for item in items]

        scraper = _TestScraper(integration_session)
        first_inserted, _ = await _save_listings(scraper, listings)
        assert first_inserted > 0

        second_inserted, _ = await _save_listings(scraper, listings)
        assert second_inserted == 0

        assert await _count_sales(integration_session) == first_inserted


# ── Cars.com integration tests ───────────────────────────────────────────────

class TestCarsComIntegration:
    async def test_cars_com_fixture_inserts_vehicle_sales(
        self, integration_session: AsyncSession
    ) -> None:
        """Parsing the Cars.com fixture produces active listing rows."""
        from app.scrapers.cars_com_parser import extract_listings_from_html, parse_listing

        html = (FIXTURES_DIR / "cars_com_porsche_911_p1.html").read_text()
        items = extract_listings_from_html(html)
        assert items, "Fixture should contain listing items"

        listings = [parse_listing(item)[0] for item in items]
        scraper = _TestScraper(integration_session)
        inserted, _ = await _save_listings(scraper, listings)

        assert inserted > 0, "At least one listing should have been inserted"

    async def test_cars_com_sale_fields_are_correct(
        self, integration_session: AsyncSession
    ) -> None:
        """VehicleSale rows from Cars.com have the expected field values."""
        from app.scrapers.cars_com_parser import extract_listings_from_html, parse_listing

        html = (FIXTURES_DIR / "cars_com_porsche_911_p1.html").read_text()
        items = extract_listings_from_html(html)
        listings = [parse_listing(item)[0] for item in items]

        scraper = _TestScraper(integration_session)
        await _save_listings(scraper, listings)

        sales = await _all_sales(integration_session)
        sale = sales[0]

        assert sale.source == "cars_com"
        assert sale.sale_type == "listing"
        assert sale.is_sold is False
        assert sale.sold_price is None  # active listing — no confirmed sale
        assert sale.asking_price > 0
        assert sale.year is not None and 1990 <= sale.year <= 2030
        assert sale.source_url.startswith("https://www.cars.com")

    async def test_cars_com_deduplication(
        self, integration_session: AsyncSession
    ) -> None:
        """Saving the same Cars.com listing twice does not create duplicate rows."""
        from app.scrapers.cars_com_parser import extract_listings_from_html, parse_listing

        html = (FIXTURES_DIR / "cars_com_porsche_911_p1.html").read_text()
        items = extract_listings_from_html(html)
        listings = [parse_listing(item)[0] for item in items]

        scraper = _TestScraper(integration_session)
        first_inserted, _ = await _save_listings(scraper, listings)
        assert first_inserted > 0

        second_inserted, _ = await _save_listings(scraper, listings)
        assert second_inserted == 0

        assert await _count_sales(integration_session) == first_inserted


# ── Cross-source / pipeline tests ────────────────────────────────────────────

class TestPipelineBehavior:
    async def test_unmatched_car_is_skipped(
        self, integration_session: AsyncSession
    ) -> None:
        """A listing that doesn't fuzzy-match any car in the catalog is not saved."""
        from datetime import datetime, timezone

        listing = ScrapedListing(
            source="bring_a_trailer",
            source_url="https://bringatrailer.com/listing/unknown-car-99999/",
            sale_type="auction",
            raw_title="2022 Bugatti Chiron Super Sport",  # not in test catalog
            year=2022,
            asking_price=3_800_000,
            sold_price=3_800_000,
            is_sold=True,
            listed_at=datetime(2022, 6, 1, tzinfo=timezone.utc),
            sold_at=datetime(2022, 6, 1, tzinfo=timezone.utc),
        )

        scraper = _TestScraper(integration_session)
        saved = await scraper.save_listing(listing)
        await integration_session.commit()

        assert saved is False
        assert await _count_sales(integration_session) == 0

    async def test_multiple_sources_saved_independently(
        self, integration_session: AsyncSession
    ) -> None:
        """BaT and Cars.com listings for the same car coexist with different source values."""
        from app.scrapers.bat_parser import extract_items_from_html, parse_item
        from app.scrapers.cars_com_parser import extract_listings_from_html, parse_listing

        bat_html = (FIXTURES_DIR / "bat_porsche_911_gt3.html").read_text()
        bat_items = extract_items_from_html(bat_html)
        bat_listings = [parse_item(i)[0] for i in bat_items]

        cars_com_html = (FIXTURES_DIR / "cars_com_porsche_911_p1.html").read_text()
        cc_items = extract_listings_from_html(cars_com_html)
        cc_listings = [parse_listing(i)[0] for i in cc_items]

        scraper = _TestScraper(integration_session)
        bat_inserted, _ = await _save_listings(scraper, bat_listings)
        cc_inserted, _ = await _save_listings(scraper, cc_listings)

        assert bat_inserted > 0
        assert cc_inserted > 0

        sales = await _all_sales(integration_session)
        sources = {s.source for s in sales}
        assert "bring_a_trailer" in sources
        assert "cars_com" in sources
        assert len(sales) == bat_inserted + cc_inserted
