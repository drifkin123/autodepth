"""Cars & Bids auction field parsing helpers."""

from __future__ import annotations

import re
from datetime import UTC, datetime

BASE_URL = "https://carsandbids.com"
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MILEAGE_DIGITS_RE = re.compile(r"^[\d,]+")


def parse_year(title: str) -> int | None:
    """Extract the model year from an auction title."""
    m = _YEAR_RE.search(title)
    if m:
        return int(m.group())
    return None


def parse_mileage(mileage_str: str | None) -> int | None:
    """Convert '45,200 Miles' into 45200."""
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
