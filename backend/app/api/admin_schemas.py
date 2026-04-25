"""Pydantic schemas for the ingestion admin API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class APIModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class ScraperStatus(APIModel):
    is_running: bool


class TargetEntry(APIModel):
    key: str
    label: str
    path: str | None = None
    query: str | None = None


class TriggerRequest(APIModel):
    bat_selected_keys: list[str] | None = None
    carsandbids_selected_keys: list[str] | None = None
    mode: Literal["incremental", "backfill"] = "incremental"


class AuctionImageOut(APIModel):
    id: uuid.UUID
    auction_lot_id: uuid.UUID
    source: str
    image_url: str
    position: int
    caption: str | None
    width: int | None
    height: int | None
    source_payload: dict
    created_at: datetime


class AuctionLotOut(APIModel):
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
    detail_html: str | None
    detail_scraped_at: datetime | None
    created_at: datetime
    updated_at: datetime
    images: list[AuctionImageOut] = []


class AuctionLotListItem(APIModel):
    id: uuid.UUID
    source: str
    source_auction_id: str | None
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
    title: str | None
    subtitle: str | None
    image_count: int


class PaginatedLots(APIModel):
    items: list[AuctionLotListItem]
    total: int
    page: int
    page_size: int


class ScrapeRunOut(APIModel):
    id: uuid.UUID
    source: str
    mode: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    records_found: int
    records_inserted: int
    records_updated: int
    error: str | None
    metadata_json: dict
