"""Bring a Trailer completed-result/list payload parsing."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from app.scrapers.bat_list_fields import (
    EXCLUDED_TITLE_MAKES,
    EXCLUDED_TITLE_TERMS,
    KNOWN_MULTI_WORD_MAKES,
    YEAR_PATTERN,
    extract_image_urls,
    is_excluded_non_car_title,
    parse_auction_status,
    parse_bid_count,
    parse_color,
    parse_integer_value,
    parse_mileage,
    parse_sold_text,
    parse_vehicle_identity,
    parse_year,
)
from app.scrapers.types import ScrapedAuctionLot

SOURCE = "bring_a_trailer"
DATA_PATTERN = re.compile(
    r"var\s+auctionsCompletedInitialData\s*=\s*(\{.*?\})\s*;", re.DOTALL
)

__all__ = [
    "DATA_PATTERN",
    "EXCLUDED_TITLE_MAKES",
    "EXCLUDED_TITLE_TERMS",
    "KNOWN_MULTI_WORD_MAKES",
    "SOURCE",
    "YEAR_PATTERN",
    "extract_completed_data_from_html",
    "extract_completed_metadata_from_html",
    "extract_image_urls",
    "extract_items_from_html",
    "is_excluded_non_car_title",
    "parse_auction_status",
    "parse_bid_count",
    "parse_color",
    "parse_integer_value",
    "parse_item",
    "parse_mileage",
    "parse_sold_text",
    "parse_vehicle_identity",
    "parse_year",
]


def _parse_timestamp_end(value: object) -> datetime | None:
    timestamp = parse_integer_value(value)
    if timestamp is None or timestamp <= 0:
        return None
    if timestamp > 10_000_000_000:
        timestamp = int(timestamp / 1000)
    try:
        return datetime.fromtimestamp(timestamp, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def parse_item(item: dict) -> tuple[ScrapedAuctionLot | None, str]:
    title = item.get("title", "")
    if not title:
        return None, "no_title"
    if is_excluded_non_car_title(title):
        return None, "parts_or_non_car"
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

    make, model, trim = parse_vehicle_identity(title)
    high_bid = parse_integer_value(item.get("current_bid")) or price
    ended_at = _parse_timestamp_end(item.get("timestamp_end")) or sold_date
    if ended_at is None:
        return None, "no_end_date"
    return ScrapedAuctionLot(
        source=SOURCE,
        source_auction_id=str(item.get("id")) if item.get("id") is not None else None,
        canonical_url=url,
        auction_status=auction_status,
        sold_price=price if is_sold else None,
        high_bid=high_bid,
        bid_count=parse_bid_count(item),
        ended_at=ended_at,
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
    ), ""


def extract_completed_data_from_html(html: str) -> dict:
    m = DATA_PATTERN.search(html)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def extract_completed_metadata_from_html(html: str) -> dict:
    data = extract_completed_data_from_html(html)
    return {
        "base_filter": data.get("base_filter") or {},
        "items_total": data.get("items_total"),
        "items_per_page": data.get("items_per_page"),
        "page_current": data.get("page_current"),
        "pages_total": data.get("pages_total"),
    }


def extract_items_from_html(html: str) -> list[dict]:
    data = extract_completed_data_from_html(html)
    return data.get("items", [])
