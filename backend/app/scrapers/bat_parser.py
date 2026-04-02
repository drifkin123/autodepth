"""Bring a Trailer HTML/JSON parsing — pure functions, no I/O."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.scrapers.base import ScrapedListing

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
                sold_date = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

    return is_sold, price, sold_date


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


def parse_item(item: dict) -> tuple[ScrapedListing | None, str]:
    """Convert a single BaT JSON item dict into a ScrapedListing.

    Returns (listing_or_None, skip_reason).
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

    if not is_sold:
        return None, "not_sold"
    if not price or price <= 0:
        return None, "no_price"

    listing = ScrapedListing(
        source=SOURCE, source_url=url, sale_type="auction",
        raw_title=title, year=year, asking_price=price,
        sold_price=price, is_sold=True,
        listed_at=sold_date or datetime.now(timezone.utc),
        sold_at=sold_date,
        mileage=parse_mileage(title),
        color=parse_color(title),
        raw_data={"title": title, "url": url, "sold_text": sold_text, "bat_id": item.get("id")},
    )
    return listing, ""


def extract_items_from_html(html: str) -> list[dict]:
    """Extract item dicts from BaT's embedded auctionsCompletedInitialData JSON."""
    m = DATA_PATTERN.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    return data.get("items", [])
