"""Query parameter dependencies for public market analytics."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Query

from app.services.market import build_market_filters


class MarketFilterParams:
    """Shared public market filters used by lot and analytics endpoints."""

    def __init__(
        self,
        source: Annotated[list[str] | None, Query()] = None,
        auction_status: Annotated[list[str] | None, Query(alias="auctionStatus")] = None,
        make: Annotated[list[str] | None, Query()] = None,
        model: Annotated[list[str] | None, Query()] = None,
        year_min: Annotated[int | None, Query(alias="yearMin")] = None,
        year_max: Annotated[int | None, Query(alias="yearMax")] = None,
        transmission: Annotated[list[str] | None, Query()] = None,
        exterior_color: Annotated[list[str] | None, Query(alias="exteriorColor")] = None,
        price_min: Annotated[int | None, Query(alias="priceMin")] = None,
        price_max: Annotated[int | None, Query(alias="priceMax")] = None,
        mileage_min: Annotated[int | None, Query(alias="mileageMin")] = None,
        mileage_max: Annotated[int | None, Query(alias="mileageMax")] = None,
        ended_from: Annotated[date | None, Query(alias="endedFrom")] = None,
        ended_to: Annotated[date | None, Query(alias="endedTo")] = None,
        sold_only: Annotated[bool, Query(alias="soldOnly")] = False,
        search: str | None = None,
    ) -> None:
        self.source = source
        self.auction_status = auction_status
        self.make = make
        self.model = model
        self.year_min = year_min
        self.year_max = year_max
        self.transmission = transmission
        self.exterior_color = exterior_color
        self.price_min = price_min
        self.price_max = price_max
        self.mileage_min = mileage_min
        self.mileage_max = mileage_max
        self.ended_from = ended_from
        self.ended_to = ended_to
        self.sold_only = sold_only
        self.search = search

    def to_filters(self, *, sold_only: bool | None = None) -> list:
        return build_market_filters(
            source=self.source,
            auction_status=self.auction_status,
            make=self.make,
            model=self.model,
            year_min=self.year_min,
            year_max=self.year_max,
            transmission=self.transmission,
            exterior_color=self.exterior_color,
            price_min=self.price_min,
            price_max=self.price_max,
            mileage_min=self.mileage_min,
            mileage_max=self.mileage_max,
            ended_from=self.ended_from,
            ended_to=self.ended_to,
            sold_only=self.sold_only if sold_only is None else sold_only,
            search=self.search,
        )
