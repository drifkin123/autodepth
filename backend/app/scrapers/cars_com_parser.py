"""Cars.com HTML parsing — pure functions, no I/O.

Cars.com renders listings as Web Components:
    <fuse-card data-listing-id="..." data-vehicle-details="{...JSON...}">

All listing data is embedded in the ``data-vehicle-details`` JSON attribute.
The page metadata (total pages, page size) is embedded in a separate JSON blob
in the page source.

data-vehicle-details fields used:
    listingId    str   UUID — used to build the vehicledetail URL
    year         str   model year e.g. "2022"
    make         str   e.g. "Porsche"
    model        str   e.g. "911"
    trim         str   e.g. "GT3 RS"
    price        str   asking price in USD (may be None/"null")
    mileage      str   odometer reading (may be None)
    stockType    str   "Used" / "New" / "Certified"
    vin          str   optional
"""
from __future__ import annotations

import html as html_module
import json
import re
from datetime import datetime, timezone

from app.scrapers.base import ScrapedListing

SOURCE = "cars_com"
BASE_URL = "https://www.cars.com"

# Matches each <fuse-card data-listing-id="..." data-vehicle-details="..."> tag.
# data-vehicle-details is HTML-entity-encoded JSON.
_FUSE_CARD_PATTERN = re.compile(
    r'<fuse-card\s[^>]*data-listing-id="(?P<lid>[^"]+)"[^>]*data-vehicle-details="(?P<vd>[^"]+)"',
    re.DOTALL,
)

# Embedded page metadata blob: {"page":1,"page_size":22,"total_pages":212,...}
_PAGE_META_PATTERN = re.compile(
    r'"page":(?P<page>\d+),"page_size":(?P<page_size>\d+),"total_pages":(?P<total_pages>\d+)'
)

# Facet option objects embedded in the page: {"name":"911","value":"porsche-911",...}
_FACET_OPTION_PATTERN = re.compile(
    r'"name":"(?P<name>[^"]+)","value":"(?P<value>[^"]+)"'
)


def extract_model_options_from_html(html: str, make_slug: str) -> list[tuple[str, str]]:
    """Extract (name, slug) model option pairs from a make-filtered results page.

    Scans embedded facet JSON for name/value pairs where the value starts with
    ``{make_slug}-``.  Deduplicates by slug (keeps first occurrence).

    Example output for make_slug="porsche":
        [("911", "porsche-911"), ("Cayman", "porsche-cayman"), ...]
    """
    prefix = f"{make_slug}-"
    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    for m in _FACET_OPTION_PATTERN.finditer(html):
        value = m.group("value")
        if value.startswith(prefix) and value not in seen:
            seen.add(value)
            results.append((m.group("name"), value))
    return results


def extract_listings_from_html(html: str) -> list[dict]:
    """Extract raw listing dicts from a Cars.com search results page.

    Returns a list of dicts with keys matching the data-vehicle-details JSON
    fields, plus a synthetic ``source_url`` key built from the listing ID.
    """
    results: list[dict] = []
    for m in _FUSE_CARD_PATTERN.finditer(html):
        listing_id = m.group("lid")
        raw_json = html_module.unescape(m.group("vd"))
        try:
            data: dict = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        data["source_url"] = f"{BASE_URL}/vehicledetail/{listing_id}/"
        results.append(data)
    return results


def extract_page_meta(html: str) -> dict[str, int]:
    """Extract pagination metadata from the page source.

    Returns a dict with keys ``page``, ``page_size``, ``total_pages``.
    Returns empty dict if not found.
    """
    m = _PAGE_META_PATTERN.search(html)
    if not m:
        return {}
    return {
        "page": int(m.group("page")),
        "page_size": int(m.group("page_size")),
        "total_pages": int(m.group("total_pages")),
    }


def has_next_page(html: str) -> bool:
    """Return True if the page metadata indicates more pages exist."""
    meta = extract_page_meta(html)
    if not meta:
        return False
    return meta["page"] < meta["total_pages"]


def parse_listing(item: dict) -> tuple[ScrapedListing | None, str]:
    """Convert a data-vehicle-details dict into a ScrapedListing.

    Returns ``(listing_or_None, skip_reason)``.  ``skip_reason`` is ``""`` on
    success.
    """
    source_url = item.get("source_url", "")
    if not source_url:
        return None, "no_url"

    year_raw = item.get("year")
    if not year_raw:
        return None, "no_year"
    try:
        year = int(year_raw)
    except (ValueError, TypeError):
        return None, "no_year"

    price_raw = item.get("price")
    if not price_raw:
        return None, "no_price"
    try:
        price = int(price_raw)
    except (ValueError, TypeError):
        return None, "no_price"
    if price <= 0:
        return None, "no_price"

    make = item.get("make") or ""
    model = item.get("model") or ""
    trim = item.get("trim") or ""
    raw_title = f"{year} {make} {model} {trim}".strip()

    mileage: int | None = None
    mileage_raw = item.get("mileage")
    if mileage_raw:
        try:
            mileage = int(mileage_raw)
        except (ValueError, TypeError):
            pass

    stock_type_map = {"Used": "used", "New": "new", "Certified": "cpo"}
    raw_stock_type = item.get("stockType")
    stock_type = stock_type_map.get(raw_stock_type) if raw_stock_type else None

    listing = ScrapedListing(
        source=SOURCE,
        source_url=source_url,
        sale_type="listing",
        raw_title=raw_title,
        year=year,
        asking_price=price,
        sold_price=None,
        is_sold=False,
        listed_at=datetime.now(timezone.utc),
        sold_at=None,
        mileage=mileage,
        color=None,
        make=make or None,
        model=model or None,
        trim=trim or None,
        vin=item.get("vin"),
        body_style=item.get("bodyStyle"),
        fuel_type=item.get("fuelType"),
        stock_type=stock_type,
        raw_data={
            "listingId": item.get("listingId"),
            "vin": item.get("vin"),
            "make": make,
            "model": model,
            "trim": trim,
            "year": year,
            "price": price,
            "mileage": mileage,
            "stockType": item.get("stockType"),
            "bodyStyle": item.get("bodyStyle"),
        },
    )
    return listing, ""
