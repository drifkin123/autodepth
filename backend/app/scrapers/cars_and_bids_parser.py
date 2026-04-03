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

Only confirmed sales (status == "sold") are ingested; reserve-not-met auctions are
skipped so that no unconfirmed hammer prices pollute the depreciation model.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.scrapers.base import ScrapedListing
from app.scrapers.bat_parser import parse_color

SOURCE = "cars_and_bids"
BASE_URL = "https://carsandbids.com"

# Matches a 4-digit year at the start of a title, e.g. "2019 Porsche 911 …"
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# Matches mileage strings like "45,200 Miles" or "160 Miles"
_MILEAGE_DIGITS_RE = re.compile(r"^[\d,]+")


def parse_year(title: str) -> int | None:
    """Extract the model year from an auction title."""
    m = _YEAR_RE.search(title)
    if m:
        return int(m.group())
    return None


def parse_mileage(mileage_str: str | None) -> int | None:
    """Convert '45,200 Miles' → 45200.  Returns None if absent or unparseable."""
    if not mileage_str:
        return None
    m = _MILEAGE_DIGITS_RE.match(mileage_str.strip())
    if not m:
        return None
    try:
        return int(m.group().replace(",", ""))
    except ValueError:
        return None


def parse_sold_date(auction_end: str | None) -> datetime | None:
    """Parse ISO 8601 auction_end string into an aware UTC datetime."""
    if not auction_end:
        return None
    try:
        # Python 3.11+ handles timezone offsets natively; strip trailing fractions if needed
        dt = datetime.fromisoformat(auction_end.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def build_source_url(auction_id: str) -> str:
    """Build the canonical listing URL from a C&B auction ID."""
    return f"{BASE_URL}/auctions/{auction_id}/"


def parse_auction(item: dict) -> tuple[ScrapedListing | None, str]:
    """Convert a raw Cars & Bids auction dict into a ScrapedListing.

    Returns ``(listing, "")`` on success or ``(None, skip_reason)`` on failure.
    Only confirmed sales (status == "sold") are accepted.
    """
    auction_id = item.get("id", "")
    if not auction_id:
        return None, "no_url"

    title = item.get("title") or ""
    if not title:
        return None, "no_title"

    if item.get("status") != "sold":
        return None, "not_sold"

    year = parse_year(title)
    if year is None:
        return None, "no_year"

    sale_amount = item.get("sale_amount")
    if not sale_amount or int(sale_amount) <= 0:
        return None, "no_price"
    price = int(sale_amount)

    mileage = parse_mileage(item.get("mileage"))
    sold_at = parse_sold_date(item.get("auction_end"))
    listed_at = sold_at or datetime.now(timezone.utc)
    source_url = build_source_url(auction_id)

    sub_title = item.get("sub_title") or ""
    listing = ScrapedListing(
        source=SOURCE,
        source_url=source_url,
        sale_type="auction",
        raw_title=title,
        year=year,
        asking_price=price,
        sold_price=price,
        is_sold=True,
        listed_at=listed_at,
        sold_at=sold_at,
        mileage=mileage,
        color=parse_color(sub_title),
        transmission=item.get("transmission"),
        location=item.get("location"),
        no_reserve=bool(item.get("no_reserve", False)),
        condition_notes=sub_title or None,
        raw_data={
            "id": auction_id,
            "title": title,
            "sub_title": sub_title or None,
            "status": item.get("status"),
            "sale_amount": price,
            "current_bid": item.get("current_bid"),
            "mileage": item.get("mileage"),
            "transmission": item.get("transmission"),
            "location": item.get("location"),
            "no_reserve": item.get("no_reserve"),
        },
    )
    return listing, ""
