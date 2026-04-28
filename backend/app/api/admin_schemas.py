"""Pydantic schemas for the ingestion admin API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from app.api.schemas import APIModel


class SourceHealthOut(APIModel):
    source: str
    state: str
    last_run_at: datetime | None
    last_success_at: datetime | None
    latest_status: str | None
    records_found: int
    records_inserted: int
    records_updated: int
    latest_anomaly_severity: str | None
    latest_anomaly_message: str | None
    is_stale: bool


class ScraperStatus(APIModel):
    is_running: bool
    sources: list[SourceHealthOut] = []


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


class RawPageListItem(APIModel):
    id: uuid.UUID
    source: str
    target_type: str
    url: str
    status_code: int | None
    content_type: str
    size_bytes: int
    content_sha256: str
    artifact_uri: str
    fetched_at: datetime
    fetch_error: str | None
    metadata_json: dict


class RawPageOut(RawPageListItem):
    canonical_url: str
    response_headers: dict
    crawl_target_id: uuid.UUID | None
    created_at: datetime


class PaginatedRawPages(APIModel):
    items: list[RawPageListItem]
    total: int
    page: int
    page_size: int


class CrawlTargetOut(APIModel):
    id: uuid.UUID
    source: str
    target_type: str
    url: str
    canonical_url: str
    state: str
    priority: int
    attempts: int
    next_fetch_at: datetime | None
    locked_by: str | None
    locked_at: datetime | None
    last_error: str | None
    discovered_from_raw_page_id: uuid.UUID | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


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


class ScrapeRequestLogOut(APIModel):
    id: uuid.UUID
    scrape_run_id: uuid.UUID | None
    source: str
    url: str
    action: str
    attempt: int
    status_code: int | None
    duration_ms: int | None
    outcome: str
    error_type: str | None
    error_message: str | None
    retry_delay_seconds: float | None
    raw_item_count: int | None
    parsed_lot_count: int | None
    skip_counts: dict
    metadata_json: dict
    created_at: datetime


class ScrapeAnomalyOut(APIModel):
    id: uuid.UUID
    scrape_run_id: uuid.UUID | None
    source: str
    severity: str
    code: str
    message: str
    url: str | None
    metadata_json: dict
    created_at: datetime
