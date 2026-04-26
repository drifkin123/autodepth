"""Shared scraper data types."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ScrapedAuctionLot:
    """Raw and extracted auction data before persistence."""

    source: str
    source_auction_id: str | None
    canonical_url: str
    auction_status: str
    sold_price: int | None
    high_bid: int | None
    bid_count: int | None
    currency: str = "USD"
    listed_at: datetime | None = None
    ended_at: datetime | None = None
    year: int | None = None
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    vin: str | None = None
    mileage: int | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    transmission: str | None = None
    drivetrain: str | None = None
    engine: str | None = None
    body_style: str | None = None
    location: str | None = None
    seller: str | None = None
    title: str | None = None
    subtitle: str | None = None
    raw_summary: str | None = None
    vehicle_details: dict = field(default_factory=dict)
    list_payload: dict = field(default_factory=dict)
    detail_payload: dict = field(default_factory=dict)
    detail_html: str | None = None
    detail_scraped_at: datetime | None = None
    image_urls: list[str] = field(default_factory=list)
