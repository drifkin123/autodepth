"""Bring a Trailer HTML/JSON parsing — pure functions, no I/O."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import urlsplit, urlunsplit

from app.scrapers.base import ScrapedAuctionLot

SOURCE = "bring_a_trailer"

# Regex to extract the embedded JSON payload from the page source
DATA_PATTERN = re.compile(
    r"var\s+auctionsCompletedInitialData\s*=\s*(\{.*?\})\s*;", re.DOTALL
)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
KNOWN_MULTI_WORD_MAKES = (
    "Alfa Romeo",
    "Aston Martin",
    "De Tomaso",
    "Land Rover",
    "Mercedes-AMG",
    "Mercedes-Benz",
    "Porsche-Diesel",
    "Rolls-Royce",
)
EXCLUDED_TITLE_TERMS = (
    r"\bwheels?\b",
    r"\btires?\b",
    r"\bseats?\b",
    r"\bengine\b",
    r"\btransmission\b",
    r"\bparts?\b",
    r"\btrailer\b",
    r"\bcamper\b",
    r"\bmotorhome\b",
    r"\brv conversion\b",
    r"\btractor\b",
    r"\bgo-?kart\b",
    r"\bside-?by-?side\b",
    r"\bsidecar\b",
    r"\bscrambler\b",
    r"\bminibike\b",
    r"\bscooter\b",
    r"\bboat\b",
    r"\baircraft\b",
)
EXCLUDED_TITLE_MAKES = (
    "Airstream",
    "AJS",
    "Porsche-Diesel",
    "Harley-Davidson",
    "Ducati",
    "Moto Guzzi",
    "BSA",
)


def parse_year(title: str) -> int | None:
    """Extract a 4-digit model year from a listing title."""
    m = YEAR_PATTERN.search(title.strip())
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


def is_excluded_non_car_title(title: str) -> bool:
    normalized = unescape(title).strip()
    lower_title = normalized.lower()
    year_match = YEAR_PATTERN.search(normalized)
    title_after_year = normalized[year_match.end() :].strip(" ,:-").lower() if year_match else ""
    if any(
        lower_title.startswith(make.lower() + " ")
        or title_after_year.startswith(make.lower() + " ")
        for make in EXCLUDED_TITLE_MAKES
    ):
        return True
    return any(re.search(pattern, lower_title, re.IGNORECASE) for pattern in EXCLUDED_TITLE_TERMS)


def parse_vehicle_identity(title: str) -> tuple[str | None, str | None, str | None]:
    year_match = YEAR_PATTERN.search(title)
    if year_match is None:
        return None, None, None
    title_after_year = title[year_match.end() :].strip(" ,:-")
    for make in KNOWN_MULTI_WORD_MAKES:
        if title_after_year.lower().startswith(make.lower() + " "):
            remainder = title_after_year[len(make) :].strip()
            words = remainder.split()
            if not words:
                return make, None, None
            model = words[0]
            trim = " ".join(words[1:]) or None
            return make, model, trim

    words = title_after_year.split()
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


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_image_url(url: str) -> str:
    parsed = urlsplit(unescape(url))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _extract_product_json_ld(html: str) -> dict:
    for payload in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(unescape(payload).strip())
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "Product":
                return candidate
    return {}


def _extract_detail_image_urls(html: str, product_payload: dict) -> list[str]:
    urls: list[str] = []
    product_image = product_payload.get("image")
    if isinstance(product_image, str):
        urls.append(product_image)

    blocks = []
    intro_image = re.search(
        r'<div class="listing-intro-image[^"]*"[^>]*>(.*?)</div>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if intro_image:
        blocks.append(intro_image.group(1))
    post_excerpt = re.search(
        r'<div class="post-excerpt"[^>]*>(.*?)(?:</div>\s*<script|</div>\s*</div>)',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if post_excerpt:
        blocks.append(post_excerpt.group(1))

    for block in blocks:
        for image_url in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', block, re.IGNORECASE):
            if "wp-content/uploads" in image_url:
                urls.append(image_url)
    return list(dict.fromkeys(_clean_image_url(url) for url in urls if url))


def _extract_listing_details(html: str) -> list[str]:
    match = re.search(
        r"<strong>\s*Listing Details\s*</strong>\s*<ul>(.*?)</ul>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return []
    return [
        _strip_tags(item)
        for item in re.findall(r"<li[^>]*>(.*?)</li>", match.group(1), re.DOTALL)
    ]


def _parse_detail_mileage(detail: str) -> int | None:
    match = re.search(r"([\d,.]+)\s*k\s*Miles?\b", detail, re.IGNORECASE)
    if match:
        return int(float(match.group(1).replace(",", "")) * 1000)
    match = re.search(r"([\d,]+)\s*Miles?\b", detail, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _classify_listing_detail(detail: str, extracted: dict) -> None:
    lower_detail = detail.lower()
    if lower_detail.startswith("chassis:"):
        extracted["vin"] = detail.split(":", 1)[1].strip()
        return
    mileage = _parse_detail_mileage(detail)
    if mileage is not None:
        extracted["mileage"] = mileage
        return
    if "paint" in lower_detail or "finished in" in lower_detail:
        extracted["exterior_color"] = detail
        return
    if "upholstery" in lower_detail or "interior" in lower_detail:
        extracted["interior_color"] = detail
        return
    if any(term in lower_detail for term in ("transmission", "transaxle", "pdk", "manual")):
        extracted["transmission"] = detail
        return
    drivetrain_terms = ("all-wheel", "rear-wheel", "front-wheel", "awd", "4wd")
    if any(term in lower_detail for term in drivetrain_terms):
        extracted["drivetrain"] = detail
        return
    if re.search(r"\b(liter|litre|flat-|v\d|inline-|engine|diesel)\b", lower_detail):
        extracted["engine"] = detail


def extract_detail_payload_from_html(html: str) -> dict:
    product_payload = _extract_product_json_ld(html)
    listing_details = _extract_listing_details(html)
    extracted: dict = {}
    for detail in listing_details:
        _classify_listing_detail(detail, extracted)

    seller_match = re.search(
        r'<div class="item item-seller"[^>]*>\s*<strong>\s*Seller\s*</strong>\s*:?\s*(.*?)</div>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    location_match = re.search(
        r"<strong>\s*Location\s*</strong>\s*:?\s*<a[^>]*>(.*?)</a>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    seller_type_match = re.search(
        r"<strong>\s*Private Party or Dealer\s*</strong>\s*:?\s*([^<]+)",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    lot_match = re.search(r"<strong>\s*Lot\s*</strong>\s*#?\s*([\d,]+)", html, re.IGNORECASE)

    return {
        "seller": _strip_tags(seller_match.group(1)) if seller_match else None,
        "location": _strip_tags(location_match.group(1)) if location_match else None,
        "seller_type": _strip_tags(seller_type_match.group(1)) if seller_type_match else None,
        "lot_number": lot_match.group(1).replace(",", "") if lot_match else None,
        "listing_details": listing_details,
        "description": product_payload.get("description"),
        "product_payload": product_payload,
        "extracted": extracted,
        "image_urls": _extract_detail_image_urls(html, product_payload),
    }


def enrich_lot_from_detail_html(
    lot: ScrapedAuctionLot,
    html: str,
    *,
    scraped_at: datetime | None = None,
) -> ScrapedAuctionLot:
    detail_payload = extract_detail_payload_from_html(html)
    extracted = detail_payload.get("extracted") or {}

    enriched = lot
    enriched.vin = extracted.get("vin") or enriched.vin
    enriched.mileage = extracted.get("mileage") or enriched.mileage
    enriched.exterior_color = extracted.get("exterior_color") or enriched.exterior_color
    enriched.interior_color = extracted.get("interior_color") or enriched.interior_color
    enriched.transmission = extracted.get("transmission") or enriched.transmission
    enriched.drivetrain = extracted.get("drivetrain") or enriched.drivetrain
    enriched.engine = extracted.get("engine") or enriched.engine
    enriched.location = detail_payload.get("location") or enriched.location
    enriched.seller = detail_payload.get("seller") or enriched.seller
    enriched.detail_payload = detail_payload
    enriched.detail_html = html
    enriched.detail_scraped_at = scraped_at or datetime.now(UTC)
    enriched.vehicle_details = {
        **(enriched.vehicle_details or {}),
        "bat_listing_details": detail_payload.get("listing_details") or [],
        "seller_type": detail_payload.get("seller_type"),
        "lot_number": detail_payload.get("lot_number"),
    }
    enriched.image_urls = list(
        dict.fromkeys([*enriched.image_urls, *(detail_payload.get("image_urls") or [])])
    )
    return enriched


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
