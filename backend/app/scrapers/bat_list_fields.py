"""Bring a Trailer list payload field parsing helpers."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape

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
    m = YEAR_PATTERN.search(title.strip())
    return int(m.group(0)) if m else None


def parse_integer_value(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    if not normalized_value:
        return None
    match = re.search(r"\d[\d,]*", normalized_value)
    if match is None:
        return None
    return int(match.group(0).replace(",", ""))


def parse_mileage(title: str) -> int | None:
    m = re.search(r"([\d,.]+)k-?[Mm]ile", title)
    if m:
        return int(float(m.group(1).replace(",", "")) * 1000)
    m = re.search(r"([\d,]+)\s*-?\s*[Mm]ile", title)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def parse_sold_text(sold_text: str) -> tuple[bool, int | None, datetime | None]:
    if not sold_text:
        return False, None, None
    is_sold = sold_text.startswith("Sold")
    price_match = re.search(r"\$([\d,]+)", sold_text)
    price = int(price_match.group(1).replace(",", "")) if price_match else None
    date_match = re.search(r"on\s+(\d{1,2}/\d{1,2}/\d{2,4})", sold_text)
    sold_date = None
    if date_match:
        for fmt in ("%m/%d/%y", "%m/%d/%Y"):
            try:
                sold_date = datetime.strptime(date_match.group(1), fmt).replace(tzinfo=UTC)
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
        parsed_value = parse_integer_value(value)
        if parsed_value is not None:
            return parsed_value
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
            return make, words[0], " ".join(words[1:]) or None
    words = title_after_year.split()
    if len(words) < 2:
        return None, None, None
    return words[0], words[1], " ".join(words[2:]) or None
