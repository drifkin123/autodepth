"""Cars.com HTML parsing — pure functions, no I/O.

All regex patterns and parsing helpers for extracting listing data from
Cars.com search result HTML pages.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.scrapers.base import ScrapedListing

SOURCE = "cars_com"
BASE_URL = "https://www.cars.com"

# Pattern to extract individual vehicle-card blocks from the HTML.
_CARD_PATTERN = re.compile(
    r'<div[^>]*class="[^"]*vehicle-card[^"]*"[^>]*>(.*?)</div>\s*'
    r'(?=<div[^>]*class="[^"]*vehicle-card|<div[^>]*id="pagination"|\Z)',
    re.DOTALL,
)

_TITLE_PATTERN = re.compile(r'<h2[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h2>', re.DOTALL)
_PRICE_PATTERN = re.compile(
    r'<span[^>]*class="[^"]*primary-price[^"]*"[^>]*>(.*?)</span>', re.DOTALL
)
_MILEAGE_PATTERN = re.compile(
    r'<div[^>]*class="[^"]*mileage[^"]*"[^>]*>(.*?)</div>', re.DOTALL
)
_LINK_PATTERN = re.compile(r'<a[^>]*href="(/vehicle/[^"]*)"', re.DOTALL)
_DEALER_PATTERN = re.compile(
    r'<div[^>]*class="[^"]*dealer-name[^"]*"[^>]*>(.*?)</div>', re.DOTALL
)
_STOCK_TYPE_PATTERN = re.compile(
    r'<p[^>]*class="[^"]*stock-type[^"]*"[^>]*>(.*?)</p>', re.DOTALL
)


def _strip_tags(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\s+", " ", text).strip()


def parse_price(text: str) -> int | None:
    """Extract an integer dollar amount from strings like '$142,500'."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_year(title: str) -> int | None:
    """Extract a 4-digit model year from a listing title."""
    m = re.search(r"\b(19|20)\d{2}\b", title.strip())
    return int(m.group(0)) if m else None


def parse_mileage(text: str) -> int | None:
    """Extract mileage from text like '12,345 mi.' or '12345 miles'."""
    m = re.search(r"([\d,]+)\s*mi", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def parse_color(title: str) -> str | None:
    """Extract a color from common terms in the listing title."""
    m = re.search(
        r"\b(white|black|silver|grey|gray|blue|red|yellow|green|orange|brown|"
        r"purple|gold|tan|beige|guards red|chalk|miami blue|racing yellow|"
        r"shark blue|jet black|gulf blue|lava orange|riviera blue|"
        r"nardo gray|sepang blue|mythos black|navarra blue|gentian blue|"
        r"crayon|gt silver|carrara white|arctic white|torch red|"
        r"rapid blue|elkhart lake blue|hypersonic gray|caffeine|"
        r"sebring orange|amplify orange|accelerate yellow)\b",
        title,
        re.IGNORECASE,
    )
    return m.group(0).title() if m else None


def extract_listings_from_html(html: str) -> list[dict]:
    """Parse listing card data from a Cars.com search results page."""
    cards = _CARD_PATTERN.findall(html)
    results: list[dict] = []

    for card_html in cards:
        title_m = _TITLE_PATTERN.search(card_html)
        price_m = _PRICE_PATTERN.search(card_html)
        link_m = _LINK_PATTERN.search(card_html)

        if not title_m or not link_m:
            continue

        title = _strip_tags(title_m.group(1))
        price_text = _strip_tags(price_m.group(1)) if price_m else ""
        mileage_m = _MILEAGE_PATTERN.search(card_html)
        mileage_text = _strip_tags(mileage_m.group(1)) if mileage_m else ""
        dealer_m = _DEALER_PATTERN.search(card_html)
        dealer = _strip_tags(dealer_m.group(1)) if dealer_m else ""
        stock_m = _STOCK_TYPE_PATTERN.search(card_html)
        stock_type = _strip_tags(stock_m.group(1)).lower() if stock_m else ""

        results.append({
            "title": title, "price_text": price_text,
            "mileage_text": mileage_text, "url": link_m.group(1),
            "dealer": dealer, "stock_type": stock_type,
        })

    return results


def parse_listing(item: dict) -> tuple[ScrapedListing | None, str]:
    """Convert a parsed card dict into a ScrapedListing.

    Returns ``(listing_or_None, skip_reason)``.
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
    price = parse_price(item.get("price_text", ""))
    if price is None or price <= 0:
        return None, "no_price"

    full_url = f"{BASE_URL}{url}" if url.startswith("/") else url

    listing = ScrapedListing(
        source=SOURCE, source_url=full_url, sale_type="listing",
        raw_title=title, year=year, asking_price=price,
        sold_price=None, is_sold=False,
        listed_at=datetime.now(timezone.utc), sold_at=None,
        mileage=parse_mileage(item.get("mileage_text", "")),
        color=parse_color(title),
        raw_data={
            "title": title, "url": full_url,
            "price_text": item.get("price_text", ""),
            "mileage_text": item.get("mileage_text", ""),
            "dealer": item.get("dealer", ""),
            "stock_type": item.get("stock_type", ""),
        },
    )
    return listing, ""


def has_next_page(html: str) -> bool:
    """Check if the search results page has a 'next page' link."""
    return bool(re.search(r'<a[^>]*class="[^"]*next-page[^"]*"', html))
