"""Tests for BaseScraper.save_listing() logic.

Covers the 5 key scenarios:
1. is_sold=False, new source_url → VehicleSale inserted, ListingSnapshot inserted, returns True
2. is_sold=False, duplicate source_url → VehicleSale updated, new ListingSnapshot inserted, returns False
3. is_sold=True, new source_url → VehicleSale inserted, no ListingSnapshot, returns True
4. is_sold=True, duplicate source_url → skipped, returns False
5. No car match → listing saved with car_id=None, make/model/trim from listing fields
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.car import Car
from app.models.listing_snapshot import ListingSnapshot
from app.models.vehicle_sale import VehicleSale
from app.scrapers.base import BaseScraper, ScrapedListing


# ─── Concrete subclass for testing ───────────────────────────────────────────

class ConcreteTestScraper(BaseScraper):
    source = "test_source"

    async def scrape(self) -> list[ScrapedListing]:
        return []


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_listing(
    *,
    is_sold: bool,
    source_url: str = "https://example.com/listing/123",
    make: str | None = None,
    model: str | None = None,
    trim: str | None = None,
) -> ScrapedListing:
    return ScrapedListing(
        source="test_source",
        source_url=source_url,
        sale_type="auction" if is_sold else "listing",
        raw_title="2020 Porsche 911 GT3",
        year=2020,
        asking_price=120_000,
        sold_price=118_000 if is_sold else None,
        is_sold=is_sold,
        listed_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        sold_at=datetime(2024, 1, 15, tzinfo=timezone.utc) if is_sold else None,
        mileage=5000,
        make=make,
        model=model,
        trim=trim,
    )


def _make_car(
    make: str = "Porsche",
    model: str = "911",
    trim: str = "GT3",
) -> Car:
    car = MagicMock(spec=Car)
    car.id = uuid.uuid4()
    car.make = make
    car.model = model
    car.trim = trim
    return car


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    return session


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestSaveListingActiveListing:
    """is_sold=False cases."""

    @pytest.mark.asyncio
    async def test_new_active_listing_inserts_sale_and_snapshot_and_returns_true(self) -> None:
        """Case 1: new source_url + is_sold=False → insert VehicleSale + ListingSnapshot, return True."""
        session = _make_session()
        car = _make_car()

        scraper = ConcreteTestScraper(session)
        # No existing record in DB (deduplicate returns False)
        scraper.deduplicate = AsyncMock(return_value=False)
        scraper.match_car = AsyncMock(return_value=car)

        listing = _make_listing(is_sold=False)
        result = await scraper.save_listing(listing)

        assert result is True

        # session.add must have been called with both a VehicleSale and a ListingSnapshot
        added_objects = [call_args.args[0] for call_args in session.add.call_args_list]
        sale_objects = [o for o in added_objects if isinstance(o, VehicleSale)]
        snapshot_objects = [o for o in added_objects if isinstance(o, ListingSnapshot)]

        assert len(sale_objects) == 1, "Expected exactly one VehicleSale to be added"
        assert len(snapshot_objects) == 1, "Expected exactly one ListingSnapshot to be added"

        inserted_sale = sale_objects[0]
        assert inserted_sale.car_id == car.id
        assert inserted_sale.source_url == listing.source_url
        assert inserted_sale.is_sold is False

        inserted_snapshot = snapshot_objects[0]
        assert inserted_snapshot.source_url == listing.source_url
        assert inserted_snapshot.asking_price == listing.asking_price
        assert inserted_snapshot.mileage == listing.mileage

    @pytest.mark.asyncio
    async def test_duplicate_active_listing_updates_sale_and_inserts_snapshot_returns_false(self) -> None:
        """Case 2: duplicate source_url + is_sold=False → UPDATE existing + new snapshot, return False."""
        session = _make_session()
        car = _make_car()

        scraper = ConcreteTestScraper(session)
        # Already exists in DB
        scraper.deduplicate = AsyncMock(return_value=True)
        scraper.match_car = AsyncMock(return_value=car)

        listing = _make_listing(is_sold=False)
        result = await scraper.save_listing(listing)

        assert result is False

        # A snapshot should still be added
        added_objects = [call_args.args[0] for call_args in session.add.call_args_list]
        snapshot_objects = [o for o in added_objects if isinstance(o, ListingSnapshot)]
        sale_objects = [o for o in added_objects if isinstance(o, VehicleSale)]

        assert len(snapshot_objects) == 1, "Expected one ListingSnapshot added for duplicate active listing"
        assert len(sale_objects) == 0, "No new VehicleSale should be inserted for a duplicate"

        # An UPDATE should have been executed
        session.execute.assert_called_once()
        executed_stmt = session.execute.call_args.args[0]
        # The compiled SQL should reference the UPDATE keyword
        compiled = str(executed_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "UPDATE" in compiled.upper()
        assert "vehicle_sales" in compiled.lower()


class TestSaveListingSoldAuction:
    """is_sold=True cases."""

    @pytest.mark.asyncio
    async def test_new_sold_auction_inserts_sale_only_and_returns_true(self) -> None:
        """Case 3: new source_url + is_sold=True → insert VehicleSale, no snapshot, return True."""
        session = _make_session()
        car = _make_car()

        scraper = ConcreteTestScraper(session)
        scraper.deduplicate = AsyncMock(return_value=False)
        scraper.match_car = AsyncMock(return_value=car)

        listing = _make_listing(is_sold=True)
        result = await scraper.save_listing(listing)

        assert result is True

        added_objects = [call_args.args[0] for call_args in session.add.call_args_list]
        sale_objects = [o for o in added_objects if isinstance(o, VehicleSale)]
        snapshot_objects = [o for o in added_objects if isinstance(o, ListingSnapshot)]

        assert len(sale_objects) == 1, "Expected exactly one VehicleSale"
        assert len(snapshot_objects) == 0, "No snapshot should be created for sold auctions"

        assert sale_objects[0].car_id == car.id
        assert sale_objects[0].is_sold is True

    @pytest.mark.asyncio
    async def test_duplicate_sold_auction_skips_and_returns_false(self) -> None:
        """Case 4: duplicate source_url + is_sold=True → skip entirely, return False."""
        session = _make_session()
        car = _make_car()

        scraper = ConcreteTestScraper(session)
        scraper.deduplicate = AsyncMock(return_value=True)
        scraper.match_car = AsyncMock(return_value=car)

        listing = _make_listing(is_sold=True)
        result = await scraper.save_listing(listing)

        assert result is False

        # Nothing should be added or executed beyond the deduplicate check
        session.add.assert_not_called()
        session.execute.assert_not_called()


class TestSaveListingNoCarMatch:
    """Case 5: no match in cars catalog."""

    @pytest.mark.asyncio
    async def test_no_car_match_saves_with_null_car_id_and_listing_make_model_trim(self) -> None:
        """Listing fields populate make/model/trim when car catalog match fails."""
        session = _make_session()

        scraper = ConcreteTestScraper(session)
        scraper.deduplicate = AsyncMock(return_value=False)
        scraper.match_car = AsyncMock(return_value=None)

        listing = _make_listing(
            is_sold=True,
            make="Porsche",
            model="911",
            trim="GT3 RS",
        )
        result = await scraper.save_listing(listing)

        assert result is True

        added_objects = [call_args.args[0] for call_args in session.add.call_args_list]
        sale_objects = [o for o in added_objects if isinstance(o, VehicleSale)]

        assert len(sale_objects) == 1
        inserted_sale = sale_objects[0]
        assert inserted_sale.car_id is None
        assert inserted_sale.make == "Porsche"
        assert inserted_sale.model == "911"
        assert inserted_sale.trim == "GT3 RS"

    @pytest.mark.asyncio
    async def test_no_car_match_active_listing_saves_with_null_car_id(self) -> None:
        """Active listing with no car match still gets inserted with car_id=None."""
        session = _make_session()

        scraper = ConcreteTestScraper(session)
        scraper.deduplicate = AsyncMock(return_value=False)
        scraper.match_car = AsyncMock(return_value=None)

        listing = _make_listing(
            is_sold=False,
            make="Ferrari",
            model="488",
            trim="Pista",
        )
        result = await scraper.save_listing(listing)

        assert result is True

        added_objects = [call_args.args[0] for call_args in session.add.call_args_list]
        sale_objects = [o for o in added_objects if isinstance(o, VehicleSale)]
        snapshot_objects = [o for o in added_objects if isinstance(o, ListingSnapshot)]

        assert len(sale_objects) == 1
        assert len(snapshot_objects) == 1
        assert sale_objects[0].car_id is None
        assert sale_objects[0].make == "Ferrari"
        assert sale_objects[0].model == "488"
        assert sale_objects[0].trim == "Pista"

    @pytest.mark.asyncio
    async def test_car_match_overrides_listing_make_when_listing_make_is_none(self) -> None:
        """Car catalog values fill in when listing make/model/trim are None."""
        session = _make_session()
        car = _make_car(make="Porsche", model="911", trim="GT3")

        scraper = ConcreteTestScraper(session)
        scraper.deduplicate = AsyncMock(return_value=False)
        scraper.match_car = AsyncMock(return_value=car)

        # listing has no explicit make/model/trim
        listing = _make_listing(is_sold=True)
        assert listing.make is None
        assert listing.model is None
        assert listing.trim is None

        await scraper.save_listing(listing)

        added_objects = [call_args.args[0] for call_args in session.add.call_args_list]
        sale_objects = [o for o in added_objects if isinstance(o, VehicleSale)]
        assert sale_objects[0].make == "Porsche"
        assert sale_objects[0].model == "911"
        assert sale_objects[0].trim == "GT3"
