"""Bring a Trailer detail-page extraction helpers."""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urlsplit, urlunsplit

from app.scrapers.bat_vehicle_identifiers import normalize_chassis_identifier


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


def _extract_bid_count(html: str) -> int | None:
    patterns = (
        r"\b([\d,]+)\s+bids?\b",
        r">\s*([\d,]+)\s*</[^>]+>\s*<[^>]+>\s*bids?\s*<",
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


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
        identifier = normalize_chassis_identifier(detail)
        if identifier is not None:
            extracted.setdefault("vin", identifier)
        return
    mileage = _parse_detail_mileage(detail)
    if mileage is not None:
        extracted.setdefault("mileage", mileage)
        return
    if "paint" in lower_detail or "finished in" in lower_detail:
        extracted.setdefault("exterior_color", detail)
        return
    if "upholstery" in lower_detail or "interior" in lower_detail:
        extracted.setdefault("interior_color", detail)
        return
    transmission_terms = (
        "transmission",
        "transaxle",
        " pdk ",
        "manual trans",
        "manual gearbox",
        "manual transmission",
    )
    transmission_noise_terms = ("owner's manual", "owners manual", "temperature gauge")
    is_transmission = any(term in f" {lower_detail} " for term in transmission_terms)
    is_transmission_noise = any(term in lower_detail for term in transmission_noise_terms)
    if is_transmission and not is_transmission_noise:
        extracted.setdefault("transmission", detail)
        return
    drivetrain_terms = ("all-wheel", "rear-wheel", "front-wheel", "awd", "4wd")
    if any(term in lower_detail for term in drivetrain_terms):
        extracted.setdefault("drivetrain", detail)
        return
    engine_noise_terms = ("fuel tank", "gas tank", "oil tank")
    is_engine = re.search(r"\b(liter|litre|flat-|v\d|inline-|engine|diesel)\b", lower_detail)
    if is_engine and not any(term in lower_detail for term in engine_noise_terms):
        extracted.setdefault("engine", detail)


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
        "bid_count": _extract_bid_count(html),
        "listing_details": listing_details,
        "description": product_payload.get("description"),
        "product_payload": product_payload,
        "extracted": extracted,
        "image_urls": _extract_detail_image_urls(html, product_payload),
    }
