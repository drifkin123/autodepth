"""Tests for public market analytics APIs."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.market_params import MarketFilterParams
from app.models.auction_image import AuctionImage
from app.models.auction_lot import AuctionLot


def _ended_at(year: int, month: int, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


async def _seed_market_lots(session: AsyncSession) -> list[AuctionLot]:
    lots = [
        AuctionLot(
            source="bring_a_trailer",
            source_auction_id="bat-gt3-manual",
            canonical_url="https://bringatrailer.com/listing/2018-porsche-911-gt3/",
            auction_status="sold",
            sold_price=182000,
            high_bid=182000,
            bid_count=24,
            ended_at=_ended_at(2025, 1, 15),
            year=2018,
            make="Porsche",
            model="911",
            trim="GT3",
            mileage=9300,
            exterior_color="White",
            transmission="Manual",
            title="9k-Mile 2018 Porsche 911 GT3 6-Speed",
        ),
        AuctionLot(
            source="cars_and_bids",
            source_auction_id="cab-r8-auto",
            canonical_url="https://carsandbids.com/auctions/r8/",
            auction_status="sold",
            sold_price=121000,
            high_bid=121000,
            bid_count=42,
            ended_at=_ended_at(2025, 2, 20),
            year=2017,
            make="Audi",
            model="R8",
            trim="V10 Plus",
            mileage=18400,
            exterior_color="Blue",
            transmission="Automatic",
            title="2017 Audi R8 V10 Plus",
        ),
        AuctionLot(
            source="bring_a_trailer",
            source_auction_id="bat-gt3-rnm",
            canonical_url="https://bringatrailer.com/listing/2018-porsche-911-gt3-rnm/",
            auction_status="reserve_not_met",
            sold_price=None,
            high_bid=175000,
            bid_count=18,
            ended_at=_ended_at(2025, 3, 10),
            year=2018,
            make="Porsche",
            model="911",
            trim="GT3",
            mileage=12800,
            exterior_color="White",
            transmission="Manual",
            title="2018 Porsche 911 GT3",
        ),
    ]
    session.add_all(lots)
    await session.flush()
    session.add(
        AuctionImage(
            auction_lot_id=lots[0].id,
            source="bring_a_trailer",
            image_url="https://example.com/gt3.jpg",
            position=0,
            caption="front three-quarter",
            source_payload={},
        )
    )
    await session.commit()
    return lots


@pytest.mark.asyncio
async def test_market_facets_return_normalized_values_and_ranges(
    integration_session: AsyncSession,
) -> None:
    from app.api.market import get_market_facets

    await _seed_market_lots(integration_session)

    facets = await get_market_facets(db=integration_session)

    assert facets.sources == ["bring_a_trailer", "cars_and_bids"]
    assert facets.makes == ["Audi", "Porsche"]
    assert facets.models == ["911", "R8"]
    assert facets.years == [2017, 2018]
    assert facets.transmissions == ["Automatic", "Manual"]
    assert facets.exterior_colors == ["Blue", "White"]
    assert facets.auction_statuses == ["reserve_not_met", "sold"]
    assert facets.price_range.minimum == 121000
    assert facets.price_range.maximum == 182000
    assert facets.mileage_range.minimum == 9300
    assert facets.mileage_range.maximum == 18400


@pytest.mark.asyncio
async def test_market_lots_combine_make_model_year_transmission_and_color_filters(
    integration_session: AsyncSession,
) -> None:
    from app.api.market import get_market_lots

    await _seed_market_lots(integration_session)

    page = await get_market_lots(
        market_filters=MarketFilterParams(
            make=["Porsche"],
            model=["911"],
            year_min=2018,
            year_max=2018,
            transmission=["Manual"],
            exterior_color=["White"],
        ),
        page=1,
        page_size=20,
        db=integration_session,
    )

    assert page.total == 2
    assert {item.auction_status for item in page.items} == {"sold", "reserve_not_met"}
    assert all(item.make == "Porsche" for item in page.items)


@pytest.mark.asyncio
async def test_market_depreciation_uses_only_confirmed_sold_prices(
    integration_session: AsyncSession,
) -> None:
    from app.api.market import get_market_depreciation

    await _seed_market_lots(integration_session)

    depreciation = await get_market_depreciation(
        market_filters=MarketFilterParams(make=["Porsche"], model=["911"]),
        db=integration_session,
    )

    assert [point.sold_price for point in depreciation.points] == [182000]
    assert depreciation.points[0].high_bid == 182000
    assert depreciation.points[0].auction_status == "sold"
    assert depreciation.trend is not None


@pytest.mark.asyncio
async def test_market_summary_respects_active_filters(
    integration_session: AsyncSession,
) -> None:
    from app.api.market import get_market_summary

    await _seed_market_lots(integration_session)

    summary = await get_market_summary(
        market_filters=MarketFilterParams(
            make=["Porsche"],
            model=["911"],
            transmission=["Manual"],
            exterior_color=["White"],
            sold_only=True,
        ),
        db=integration_session,
    )

    assert summary.total_count == 1
    assert summary.sold_count == 1
    assert summary.median_sale_price == 182000


@pytest.mark.asyncio
async def test_market_lot_detail_and_camel_case_response(
    integration_session: AsyncSession,
) -> None:
    from app.api.market import get_market_lot

    lots = await _seed_market_lots(integration_session)

    detail = await get_market_lot(lot_id=lots[0].id, db=integration_session)
    payload = detail.model_dump(by_alias=True)

    assert payload["canonicalUrl"] == lots[0].canonical_url
    assert payload["soldPrice"] == 182000
    assert payload["exteriorColor"] == "White"
    assert payload["images"][0]["imageUrl"] == "https://example.com/gt3.jpg"
