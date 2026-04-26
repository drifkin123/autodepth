"""Cars & Bids auction data parsing — pure functions, no I/O.

Cars & Bids exposes a signed JSON API at /v2/autos/auctions. Because the signature
is computed client-side in browser JS, we use Playwright to navigate the page and
intercept the API responses rather than calling the endpoint directly.

Each auction in the response is a dict with these fields used for parsing:
    id           str   Short auction ID, used to build the listing URL
    title        str   e.g. "2019 Porsche 911 GT3 RS Weissach"
    sub_title    str   e.g. "~6,700 Miles, 520-hp Flat-6, Lizard Green, Unmodified"
    status       str   "sold" | "reserve_not_met" | other
    sale_amount  int|None  Final sale price; populated only when status == "sold"
    current_bid  int   Highest bid (mirrors sale_amount when sold)
    mileage      str|None  e.g. "6,700 Miles"
    auction_end  str   ISO 8601 datetime string

Sold and reserve-not-met auctions are preserved. Only confirmed sales populate
``sold_price``; unsold lots keep ``sold_price`` null and store the high bid.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.scrapers.base import ScrapedAuctionLot
from app.scrapers.bat_parser import parse_color
from app.scrapers.cars_and_bids_fields import (
    BASE_URL,
    build_source_url,
    extract_image_urls,
    normalize_auction_status,
    parse_int,
    parse_mileage,
    parse_seller,
    parse_sold_date,
    parse_text,
    parse_vehicle_identity,
    parse_year,
)

SOURCE = "cars_and_bids"

__all__ = [
    "BASE_URL",
    "SOURCE",
    "build_source_url",
    "extract_image_urls",
    "normalize_auction_status",
    "parse_auction",
    "parse_color",
    "parse_int",
    "parse_mileage",
    "parse_seller",
    "parse_sold_date",
    "parse_text",
    "parse_vehicle_identity",
    "parse_year",
]


def parse_auction(item: dict) -> tuple[ScrapedAuctionLot | None, str]:
    """Convert a raw Cars & Bids auction dict into a ScrapedAuctionLot.

    Returns ``(listing, "")`` on success or ``(None, skip_reason)`` on failure.
    """
    auction_id = item.get("id", "")
    if not auction_id:
        return None, "no_url"

    title = item.get("title") or ""
    if not title:
        return None, "no_title"

    year = parse_year(title)
    if year is None:
        return None, "no_year"

    auction_status = normalize_auction_status(item.get("status"))
    sale_amount = parse_int(item.get("sale_amount"))
    current_bid = parse_int(item.get("current_bid"))
    if auction_status == "sold" and (sale_amount is None or sale_amount <= 0):
        return None, "no_price"
    high_bid = current_bid or sale_amount
    if high_bid is None or high_bid <= 0:
        return None, "no_price"
    sold_price = sale_amount if auction_status == "sold" else None

    mileage = parse_mileage(item.get("mileage"))
    sold_at = parse_sold_date(item.get("auction_end"))
    listed_at = sold_at or datetime.now(UTC)
    source_url = build_source_url(auction_id)

    sub_title = item.get("sub_title") or ""
    make, model, trim = parse_vehicle_identity(title)
    raw_seller = item.get("seller")
    lot = ScrapedAuctionLot(
        source=SOURCE,
        source_auction_id=auction_id,
        canonical_url=source_url,
        auction_status=auction_status,
        sold_price=sold_price,
        high_bid=high_bid,
        bid_count=parse_int(
            item.get("bid_count") or item.get("bids_count") or item.get("num_bids")
        ),
        currency="USD",
        listed_at=None,
        ended_at=listed_at,
        year=year,
        make=make,
        model=model,
        trim=trim,
        mileage=mileage,
        exterior_color=parse_color(sub_title),
        transmission=parse_text(item.get("transmission")),
        drivetrain=parse_text(item.get("drivetrain")),
        engine=parse_text(item.get("engine")),
        location=parse_text(item.get("location")),
        seller=parse_seller(raw_seller),
        title=title,
        subtitle=sub_title or None,
        raw_summary=sub_title or None,
        image_urls=extract_image_urls(item),
        vehicle_details={
            key: item[key]
            for key in (
                "engine",
                "drivetrain",
                "transmission",
                "location",
                "no_reserve",
                "seller",
            )
            if item.get(key) is not None
        },
        list_payload=item,
        detail_payload={},
    )
    return lot, ""
