"""Bring a Trailer detail-page HTML parsing."""

from __future__ import annotations

from datetime import UTC, datetime

from app.scrapers.bat_detail_extractors import (
    _classify_listing_detail,
    _clean_image_url,
    _extract_bid_count,
    _extract_detail_image_urls,
    _extract_listing_details,
    _extract_product_json_ld,
    _parse_detail_mileage,
    _strip_tags,
    extract_detail_payload_from_html,
)
from app.scrapers.bat_vehicle_identifiers import should_persist_identifier_as_vin
from app.scrapers.types import ScrapedAuctionLot

__all__ = [
    "_classify_listing_detail",
    "_clean_image_url",
    "_extract_bid_count",
    "_extract_detail_image_urls",
    "_extract_listing_details",
    "_extract_product_json_ld",
    "_parse_detail_mileage",
    "_strip_tags",
    "enrich_lot_from_detail_html",
    "extract_detail_payload_from_html",
]


def enrich_lot_from_detail_html(
    lot: ScrapedAuctionLot,
    html: str,
    *,
    scraped_at: datetime | None = None,
) -> ScrapedAuctionLot:
    detail_payload = extract_detail_payload_from_html(html)
    extracted = detail_payload.get("extracted") or {}
    enriched = lot
    chassis_identifier = extracted.get("vin")
    if chassis_identifier and should_persist_identifier_as_vin(chassis_identifier, enriched.year):
        enriched.vin = chassis_identifier
    enriched.mileage = extracted.get("mileage") or enriched.mileage
    enriched.exterior_color = extracted.get("exterior_color") or enriched.exterior_color
    enriched.interior_color = extracted.get("interior_color") or enriched.interior_color
    enriched.transmission = extracted.get("transmission") or enriched.transmission
    enriched.drivetrain = extracted.get("drivetrain") or enriched.drivetrain
    enriched.engine = extracted.get("engine") or enriched.engine
    enriched.location = detail_payload.get("location") or enriched.location
    enriched.seller = detail_payload.get("seller") or enriched.seller
    enriched.bid_count = detail_payload.get("bid_count") or enriched.bid_count
    enriched.detail_payload = detail_payload
    enriched.detail_html = html
    enriched.detail_scraped_at = scraped_at or datetime.now(UTC)
    vehicle_details = {
        **(enriched.vehicle_details or {}),
        "bat_listing_details": detail_payload.get("listing_details") or [],
        "seller_type": detail_payload.get("seller_type"),
        "lot_number": detail_payload.get("lot_number"),
    }
    if chassis_identifier and chassis_identifier != enriched.vin:
        vehicle_details["chassis_identifier"] = chassis_identifier
    enriched.vehicle_details = vehicle_details
    enriched.image_urls = list(
        dict.fromkeys([*enriched.image_urls, *(detail_payload.get("image_urls") or [])])
    )
    return enriched
