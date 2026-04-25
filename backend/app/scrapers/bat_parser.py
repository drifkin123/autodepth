"""Bring a Trailer HTML/JSON parsing — pure functions, no I/O."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from app.scrapers.base import ScrapedAuctionLot

SOURCE = "bring_a_trailer"

# Regex to extract the embedded JSON payload from the page source
DATA_PATTERN = re.compile(
    r"var\s+auctionsCompletedInitialData\s*=\s*(\{.*?\})\s*;", re.DOTALL
)


def parse_year(title: str) -> int | None:
    """Extract a 4-digit model year from a listing title."""
    m = re.search(r"\b(19|20)\d{2}\b", title.strip())
    return int(m.group(0)) if m else None


def parse_mileage(title: str) -> int | None:
    """Extract mileage from titles like '11k-Mile 2016 Porsche' or '12,345-Mile'."""
    m = re.search(r"([\d,.]+)k-?[Mm]ile", title)
    if m:
        return int(float(m.group(1).replace(",", "")) * 1000)
    m = re.search(r"([\d,]+)\s*-?\s*[Mm]ile", title)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def parse_sold_text(sold_text: str) -> tuple[bool, int | None, datetime | None]:
    """Parse the `sold_text` field from BaT's embedded JSON.

    Returns (is_sold, price, sold_date).
    """
    if not sold_text:
        return False, None, None

    is_sold = sold_text.startswith("Sold")
    price_match = re.search(r"\$([\d,]+)", sold_text)
    price = int(price_match.group(1).replace(",", "")) if price_match else None

    date_match = re.search(r"on\s+(\d{1,2}/\d{1,2}/\d{2,4})", sold_text)
    sold_date = None
    if date_match:
        date_str = date_match.group(1)
        for fmt in ("%m/%d/%y", "%m/%d/%Y"):
            try:
                sold_date = datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
                break
            except ValueError:
                continue

    return is_sold, price, sold_date


def parse_auction_status(sold_text: str) -> str:
    if sold_text.startswith("Sold"):
        return "sold"
    if sold_text.startswith("Bid to") or "Reserve not met" in sold_text:
        return "reserve_not_met"
    if "withdrawn" in sold_text.lower():
        return "withdrawn"
    return "unknown"


def parse_bid_count(item: dict) -> int | None:
    for key in ("bid_count", "bids", "num_bids"):
        value = item.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def extract_image_urls(item: dict) -> list[str]:
    urls: list[str] = []
    for key in ("image", "image_url", "thumbnail", "thumbnail_url"):
        value = item.get(key)
        if isinstance(value, str) and value:
            urls.append(value)
    images = item.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image:
                urls.append(image)
            elif isinstance(image, dict):
                for key in ("url", "src", "large_url", "thumbnail_url"):
                    value = image.get(key)
                    if isinstance(value, str) and value:
                        urls.append(value)
                        break
    return list(dict.fromkeys(urls))


def parse_color(title: str) -> str | None:
    """Extract a color from common terms in the listing title."""
    m = re.search(
        r"\b(white|black|silver|grey|gray|blue|red|yellow|green|orange|brown|"
        r"purple|gold|tan|beige|guards red|chalk|python green|miami blue|"
        r"racing yellow|shark blue|jet black|gulf blue|dark sea blue|"
        r"lava orange|lizard green|riviera blue|signal green|voodoo blue|"
        r"pts|arena red|gentian blue|crayon|gt silver|carrara white|"
        r"nardo gray|sepang blue|mythos black|navarra blue)\b",
        title,
        re.IGNORECASE,
    )
    return m.group(0).title() if m else None


def parse_vehicle_identity(title: str) -> tuple[str | None, str | None, str | None]:
    title_without_year = re.sub(r"^\s*(?:[\d,.]+k?-?[Mm]ile\s+)?(?:19|20)\d{2}\s+", "", title)
    words = title_without_year.split()
    if len(words) < 2:
        return None, None, None
    make = words[0]
    model = words[1]
    trim = " ".join(words[2:]) or None
    return make, model, trim


def parse_item(item: dict) -> tuple[ScrapedAuctionLot | None, str]:
    """Convert a single BaT JSON item dict into a ScrapedAuctionLot.

    Returns (lot_or_None, skip_reason).
    """
    title = item.get("title", "")
    if not title:
        return None, "no_title"
    url = item.get("url", "")
    if not url:
        return None, "no_url"
    year = parse_year(title)
    if year is None:
        return None, "no_year"

    sold_text = item.get("sold_text", "")
    is_sold, price, sold_date = parse_sold_text(sold_text)
    auction_status = parse_auction_status(sold_text)

    if not price or price <= 0:
        return None, "no_price"
    high_bid = int(item.get("current_bid") or price)
    sold_price = price if is_sold else None

    make, model, trim = parse_vehicle_identity(title)
    lot = ScrapedAuctionLot(
        source=SOURCE,
        source_auction_id=str(item.get("id")) if item.get("id") is not None else None,
        canonical_url=url,
        auction_status=auction_status,
        sold_price=sold_price,
        high_bid=high_bid,
        bid_count=parse_bid_count(item),
        currency="USD",
        listed_at=None,
        ended_at=sold_date or datetime.now(UTC),
        year=year,
        make=make,
        model=model,
        trim=trim,
        mileage=parse_mileage(title),
        exterior_color=parse_color(title),
        location=item.get("country"),
        title=title,
        raw_summary=item.get("excerpt"),
        image_urls=extract_image_urls(item),
        vehicle_details={
            "country": item.get("country"),
            "no_reserve": bool(item.get("noreserve", False)),
        },
        list_payload=item,
        detail_payload={},
    )
    return lot, ""


def extract_completed_data_from_html(html: str) -> dict:
    """Extract BaT's embedded auctionsCompletedInitialData payload."""
    m = DATA_PATTERN.search(html)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def extract_completed_metadata_from_html(html: str) -> dict:
    """Extract pagination/count telemetry from BaT completed-auction payloads."""
    data = extract_completed_data_from_html(html)
    return {
        "base_filter": data.get("base_filter") or {},
        "items_total": data.get("items_total"),
        "items_per_page": data.get("items_per_page"),
        "page_current": data.get("page_current"),
        "pages_total": data.get("pages_total"),
    }


def extract_items_from_html(html: str) -> list[dict]:
    """Extract item dicts from BaT's embedded auctionsCompletedInitialData JSON."""
    data = extract_completed_data_from_html(html)
    return data.get("items", [])
