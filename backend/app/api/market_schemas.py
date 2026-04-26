"""Pydantic schemas for public market analytics APIs."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.api.schemas import APIModel


class NumericRange(APIModel):
    minimum: int | None
    maximum: int | None


class DateRange(APIModel):
    minimum: date | None
    maximum: date | None


class MarketFacets(APIModel):
    sources: list[str]
    makes: list[str]
    models: list[str]
    years: list[int]
    transmissions: list[str]
    exterior_colors: list[str]
    auction_statuses: list[str]
    price_range: NumericRange
    mileage_range: NumericRange
    date_range: DateRange


class MarketLotListItem(APIModel):
    id: uuid.UUID
    source: str
    canonical_url: str
    auction_status: str
    sold_price: int | None
    high_bid: int | None
    bid_count: int | None
    currency: str
    ended_at: datetime | None
    year: int | None
    make: str | None
    model: str | None
    trim: str | None
    mileage: int | None
    exterior_color: str | None
    transmission: str | None
    title: str | None
    subtitle: str | None
    image_count: int


class PaginatedMarketLots(APIModel):
    items: list[MarketLotListItem]
    total: int
    page: int
    page_size: int


class MarketSummary(APIModel):
    total_count: int
    sold_count: int
    median_sale_price: int | None
    average_sale_price: int | None
    low_sale_price: int | None
    high_sale_price: int | None
    average_mileage: int | None
    sell_through_rate: float | None
    movement_30_day: float | None
    movement_90_day: float | None
    movement_365_day: float | None


class PriceHistoryBucket(APIModel):
    month: date
    average_price: int
    median_price: int
    minimum_price: int
    maximum_price: int
    count: int


class PriceHistory(APIModel):
    buckets: list[PriceHistoryBucket]


class DepreciationPoint(APIModel):
    id: uuid.UUID
    ended_at: datetime
    year: int | None
    make: str | None
    model: str | None
    trim: str | None
    mileage: int | None
    exterior_color: str | None
    transmission: str | None
    sold_price: int
    high_bid: int | None
    auction_status: str
    source: str
    canonical_url: str
    title: str | None


class TrendPoint(APIModel):
    x: float
    y: float


class DepreciationTrend(APIModel):
    slope: float
    intercept: float
    points: list[TrendPoint]


class DepreciationResponse(APIModel):
    points: list[DepreciationPoint]
    trend: DepreciationTrend | None


class MarketImage(APIModel):
    id: uuid.UUID
    image_url: str
    position: int
    caption: str | None


class MarketLotDetail(APIModel):
    id: uuid.UUID
    source: str
    source_auction_id: str | None
    canonical_url: str
    auction_status: str
    sold_price: int | None
    high_bid: int | None
    bid_count: int | None
    currency: str
    listed_at: datetime | None
    ended_at: datetime | None
    year: int | None
    make: str | None
    model: str | None
    trim: str | None
    vin: str | None
    mileage: int | None
    exterior_color: str | None
    interior_color: str | None
    transmission: str | None
    drivetrain: str | None
    engine: str | None
    body_style: str | None
    location: str | None
    seller: str | None
    title: str | None
    subtitle: str | None
    raw_summary: str | None
    vehicle_details: dict
    list_payload: dict
    detail_payload: dict
    images: list[MarketImage]
