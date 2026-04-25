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

import re
from datetime import UTC, datetime

from app.scrapers.base import ScrapedAuctionLot
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
        return dt.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def build_source_url(auction_id: str) -> str:
    """Build the canonical listing URL from a C&B auction ID."""
    return f"{BASE_URL}/auctions/{auction_id}/"


def normalize_auction_status(status: str | None) -> str:
    if status == "sold":
        return "sold"
    if status in {"reserve_not_met", "no_sale", "unsold"}:
        return "reserve_not_met"
    if status == "withdrawn":
        return "withdrawn"
    return "unknown"


def parse_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_image_urls(item: dict) -> list[str]:
    urls: list[str] = []
    for key in ("main_photo", "photo", "image", "image_url", "thumbnail_url"):
        value = item.get(key)
        if isinstance(value, str) and value:
            urls.append(value)
        elif isinstance(value, dict):
            for nested_key in ("url", "src"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested:
                    urls.append(nested)
                    break
            else:
                base_url = value.get("base_url")
                path = value.get("path")
                if isinstance(base_url, str) and isinstance(path, str):
                    scheme = "" if base_url.startswith(("http://", "https://")) else "https://"
                    urls.append(f"{scheme}{base_url.rstrip('/')}/{path.lstrip('/')}")
    for key in ("photos", "images"):
        values = item.get(key)
        if not isinstance(values, list):
            continue
        for image in values:
            if isinstance(image, str) and image:
                urls.append(image)
            elif isinstance(image, dict):
                for nested_key in ("url", "src", "large_url", "thumbnail_url"):
                    nested = image.get(nested_key)
                    if isinstance(nested, str) and nested:
                        urls.append(nested)
                        break
    return list(dict.fromkeys(urls))


def parse_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return str(value)
    return None


def parse_seller(value: object) -> str | None:
    if isinstance(value, dict):
        for key in ("username", "name", "display_name"):
            parsed = parse_text(value.get(key))
            if parsed:
                return parsed
        return None
    return parse_text(value)


def parse_vehicle_identity(title: str) -> tuple[str | None, str | None, str | None]:
    title_without_year = re.sub(r"^\s*(?:19|20)\d{2}\s+", "", title)
    words = title_without_year.split()
    if len(words) < 2:
        return None, None, None
    make = words[0]
    model = words[1]
    trim = " ".join(words[2:]) or None
    return make, model, trim


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
