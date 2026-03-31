"""Bring a Trailer scraper — confirmed auction sales via embedded JSON data.

BaT embeds completed auction data as `auctionsCompletedInitialData` JSON in each
model page's HTML source. This avoids needing Playwright/JS execution entirely —
a simple HTTP GET + regex extraction gives us structured listing data including
sold prices, dates, and titles.

Each model page returns ~24 of the most recent completed auctions.
"""

import asyncio
import json
import re
from datetime import datetime, timezone

import httpx

from app.scrapers.base import BaseScraper, ScrapedListing

# Each entry: (url_path_key, human label, BaT URL path segment).
# url_path_key is a stable identifier used for filtering — it never changes even
# if the label is updated.  Different scraper sources will have their own key
# schemes; this list is BaT-specific.
# Note: BaT spells "Huracán" as "huaracan" on their site — not our typo.
BAT_URLS: list[tuple[str, str, str]] = [
    # Porsche
    ("porsche-911-gt3", "Porsche 911 GT3", "porsche/911-gt3"),
    ("porsche-911-turbo", "Porsche 911 Turbo", "porsche/911-turbo"),
    ("porsche-cayman-gt4", "Porsche Cayman GT4", "porsche/cayman-gt4"),
    ("porsche-918-spyder", "Porsche 918 Spyder", "porsche/918-spyder"),
    # Ferrari
    ("ferrari-458", "Ferrari 458", "ferrari/458"),
    ("ferrari-488", "Ferrari 488", "ferrari/488"),
    ("ferrari-f8", "Ferrari F8", "ferrari/f8"),
    ("ferrari-sf90", "Ferrari SF90", "ferrari/sf90"),
    ("ferrari-roma", "Ferrari Roma", "ferrari/roma"),
    # Lamborghini
    ("lamborghini-huracan", "Lamborghini Huracán", "lamborghini/huaracan"),
    ("lamborghini-aventador", "Lamborghini Aventador", "lamborghini/aventador"),
    ("lamborghini-urus", "Lamborghini Urus", "lamborghini/urus"),
    # McLaren
    ("mclaren-super-series", "McLaren Super Series (720S/765LT)", "mclaren/super-series"),
    # Mercedes-AMG
    ("mercedes-amg-gt", "Mercedes-AMG GT", "mercedes-benz/amg-gt"),
    # Audi
    ("audi-r8", "Audi R8", "audi/r8"),
    ("audi-rs6", "Audi RS6", "audi/rs6"),
    ("audi-rs7", "Audi RS7", "audi/rs7"),
    # Chevrolet
    ("chevrolet-corvette", "Chevrolet Corvette", "chevrolet/corvette"),
    # Lotus
    ("lotus-emira", "Lotus Emira", "lotus/emira"),
    ("lotus-evora", "Lotus Evora", "lotus/evora"),
    ("lotus-exige", "Lotus Exige", "lotus/exige"),
]

SOURCE = "bring_a_trailer"
BASE_URL = "https://bringatrailer.com"

# Shared HTTP headers to look like a regular browser
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Regex to extract the embedded JSON payload from the page source
_DATA_PATTERN = re.compile(
    r"var\s+auctionsCompletedInitialData\s*=\s*(\{.*?\})\s*;", re.DOTALL
)


def get_all_url_keys() -> list[str]:
    """Return every available BaT URL key (stable identifiers for the admin UI)."""
    return [key for key, _, _ in BAT_URLS]


def get_url_entries() -> list[dict[str, str]]:
    """Return BaT URL entries as dicts for the admin API."""
    return [{"key": key, "label": label, "path": path} for key, label, path in BAT_URLS]


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

    Examples:
        "Sold for USD $229,000 <span> on 3/29/26 </span>"  → (True, 229000, datetime)
        "Bid to USD $189,000 <span> on 3/27/26 </span>"    → (False, 189000, datetime)
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

    Returns (listing_or_None, skip_reason).  skip_reason is "" on success.
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

    listed_at = sold_date or datetime.now(timezone.utc)
    mileage = parse_mileage(title)
    color = parse_color(title)

    listing = ScrapedListing(
        source=SOURCE,
        source_url=url,
        sale_type="auction",
        raw_title=title,
        year=year,
        asking_price=price,
        sold_price=price,
        is_sold=True,
        listed_at=listed_at,
        sold_at=sold_date,
        mileage=mileage,
        color=color,
        raw_data={"title": title, "url": url, "sold_text": sold_text, "bat_id": item.get("id")},
    )
    return listing, ""


def extract_items_from_html(html: str) -> list[dict]:
    """Extract the list of item dicts from BaT's embedded auctionsCompletedInitialData JSON."""
    m = _DATA_PATTERN.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    return data.get("items", [])


async def fetch_page(client: httpx.AsyncClient, url_path: str) -> list[dict]:
    """Fetch one BaT model page and return the raw item dicts."""
    url = f"{BASE_URL}/{url_path}/"
    resp = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return extract_items_from_html(resp.text)


class BringATrailerScraper(BaseScraper):
    source = SOURCE

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._selected_keys: set[str] | None = kwargs.pop("selected_keys", None)
        self._cancel_event: asyncio.Event | None = kwargs.pop("cancel_event", None)
        super().__init__(*args, **kwargs)

    def _is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def _get_urls(self) -> list[tuple[str, str, str]]:
        """Return the (possibly filtered) list of URLs to scrape."""
        if self._selected_keys is None:
            return list(BAT_URLS)
        return [(k, l, p) for k, l, p in BAT_URLS if k in self._selected_keys]

    async def scrape(self) -> list[ScrapedListing]:
        urls = self._get_urls()
        if not urls:
            await self._emit("warning", "No BaT URLs selected — nothing to scrape.")
            return []

        all_listings: list[ScrapedListing] = []
        seen_urls: set[str] = set()

        await self._emit(
            "progress",
            f"Starting BaT scrape: {len(urls)} car pages selected",
            {"total_urls": len(urls), "selected_keys": [k for k, _, _ in urls]},
        )

        async with httpx.AsyncClient() as client:
            for i, (key, label, url_path) in enumerate(urls, 1):
                if self._is_cancelled():
                    await self._emit(
                        "warning",
                        f"Scrape cancelled after {i - 1}/{len(urls)} pages. "
                        f"Returning {len(all_listings)} listings collected so far.",
                        {"cancelled_at": i, "total_collected": len(all_listings)},
                    )
                    break

                await self._emit(
                    "progress",
                    f"[{i}/{len(urls)}] Fetching: {label}…",
                    {"label": label, "key": key, "term_index": i, "total_terms": len(urls)},
                )

                try:
                    items = await fetch_page(client, url_path)
                except httpx.HTTPError as exc:
                    await self._emit(
                        "error",
                        f"[{i}/{len(urls)}] {label}: HTTP error — {exc}",
                        {"label": label, "key": key, "error": str(exc)},
                    )
                    continue

                # Detailed per-page stats
                skip_counts: dict[str, int] = {}
                term_count = 0
                dup_count = 0

                for item in items:
                    listing, reason = parse_item(item)
                    if listing is None:
                        skip_counts[reason] = skip_counts.get(reason, 0) + 1
                        continue
                    if listing.source_url in seen_urls:
                        dup_count += 1
                        continue
                    seen_urls.add(listing.source_url)
                    all_listings.append(listing)
                    term_count += 1

                page_data = {
                    "label": label,
                    "key": key,
                    "raw_items": len(items),
                    "sold_parsed": term_count,
                    "duplicates": dup_count,
                    "skipped": skip_counts,
                    "running_total": len(all_listings),
                }

                if term_count == 0 and len(items) > 0:
                    await self._emit(
                        "warning",
                        f"[{i}/{len(urls)}] {label}: 0 sold listings from {len(items)} raw items "
                        f"(skipped: {skip_counts})",
                        page_data,
                    )
                else:
                    skip_summary = ""
                    if skip_counts:
                        parts = [f"{v} {k}" for k, v in skip_counts.items()]
                        skip_summary = f" — skipped: {', '.join(parts)}"
                    dup_summary = f", {dup_count} dups" if dup_count else ""
                    await self._emit(
                        "progress",
                        f"[{i}/{len(urls)}] {label}: {len(items)} raw → "
                        f"{term_count} sold{dup_summary}{skip_summary} "
                        f"(total: {len(all_listings)})",
                        page_data,
                    )

                # Be polite — small delay between requests
                if i < len(urls):
                    await asyncio.sleep(1.0)

        return all_listings
