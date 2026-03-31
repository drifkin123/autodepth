"""Cars.com scraper — dealer/private listing asking prices only.

Cars.com is a listing marketplace (not an auction site). All records are
secondary market signal: ``sold_price=NULL``, ``is_sold=False``,
``sale_type="listing"``.  These are never mixed into the depreciation
curve-fitting model — only confirmed auction hammer prices feed that.

Cars.com serves server-side rendered HTML behind Cloudflare with TLS
fingerprinting.  We use ``curl_cffi`` (which impersonates a real browser's
TLS stack) instead of plain httpx/requests to avoid fingerprint-based blocks.

HTML selectors (as of early 2026):
- Listing card container: ``div.vehicle-card``
- Title:                  ``h2.title``
- Price:                  ``span.primary-price``
- Mileage:                ``.mileage``
- Dealer name:            ``.dealer-name``
- Listing link:           ``a`` tag ``href`` (relative URL)
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from curl_cffi import requests as cffi_requests

from app.scrapers.base import BaseScraper, ScrapedListing

# ---------------------------------------------------------------------------
# URL registry
# ---------------------------------------------------------------------------
# Each entry: (stable_key, human_label, make_slug, model_slug).
# The make/model slugs map to Cars.com's URL scheme:
#   https://www.cars.com/shopping/results/?makes[]={make}&models[]={make}-{model}&...
#
# Grouped by make+model (not trim) — Cars.com returns all trims for a model
# in a single search; the fuzzy matcher in BaseScraper handles trim-level
# matching against our car catalog.

CARS_COM_URLS: list[tuple[str, str, str, str]] = [
    # Porsche
    ("porsche-911", "Porsche 911", "porsche", "porsche-911"),
    ("porsche-718", "Porsche 718 Cayman", "porsche", "porsche-718_cayman"),
    ("porsche-918", "Porsche 918 Spyder", "porsche", "porsche-918_spyder"),
    # Ferrari
    ("ferrari-458", "Ferrari 458", "ferrari", "ferrari-458_italia"),
    ("ferrari-488", "Ferrari 488", "ferrari", "ferrari-488_gtb"),
    ("ferrari-f8", "Ferrari F8", "ferrari", "ferrari-f8_tributo"),
    ("ferrari-sf90", "Ferrari SF90", "ferrari", "ferrari-sf90_stradale"),
    ("ferrari-roma", "Ferrari Roma", "ferrari", "ferrari-roma"),
    # Lamborghini
    ("lamborghini-huracan", "Lamborghini Huracan", "lamborghini", "lamborghini-huracan"),
    ("lamborghini-aventador", "Lamborghini Aventador", "lamborghini", "lamborghini-aventador"),
    ("lamborghini-urus", "Lamborghini Urus", "lamborghini", "lamborghini-urus"),
    # McLaren
    ("mclaren-720s", "McLaren 720S", "mclaren", "mclaren-720s"),
    ("mclaren-570s", "McLaren 570S", "mclaren", "mclaren-570s"),
    ("mclaren-765lt", "McLaren 765LT", "mclaren", "mclaren-765lt"),
    ("mclaren-artura", "McLaren Artura", "mclaren", "mclaren-artura"),
    # Mercedes-AMG
    ("mercedes-amg-gt", "Mercedes-AMG GT", "mercedes_benz", "mercedes_benz-amg_gt"),
    # Audi
    ("audi-r8", "Audi R8", "audi", "audi-r8"),
    ("audi-rs6", "Audi RS6", "audi", "audi-rs6"),
    ("audi-rs7", "Audi RS7", "audi", "audi-rs7"),
    # Chevrolet
    ("chevrolet-corvette", "Chevrolet Corvette", "chevrolet", "chevrolet-corvette"),
    # Lotus
    ("lotus-emira", "Lotus Emira", "lotus", "lotus-emira"),
    ("lotus-evora", "Lotus Evora", "lotus", "lotus-evora"),
    ("lotus-exige", "Lotus Exige", "lotus", "lotus-exige"),
]

SOURCE = "cars_com"
BASE_URL = "https://www.cars.com"
MAX_PAGES_PER_SEARCH = 3
RESULTS_PER_PAGE = 20  # Cars.com default

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Public helpers (used by admin API)
# ---------------------------------------------------------------------------

def get_all_url_keys() -> list[str]:
    """Return every available Cars.com URL key."""
    return [key for key, _, _, _ in CARS_COM_URLS]


def get_url_entries() -> list[dict[str, str]]:
    """Return Cars.com URL entries as dicts for the admin API."""
    return [
        {"key": key, "label": label, "make": make, "model": model}
        for key, label, make, model in CARS_COM_URLS
    ]


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------

def build_search_url(make_slug: str, model_slug: str, page: int = 1) -> str:
    """Construct a Cars.com search results URL."""
    return (
        f"{BASE_URL}/shopping/results/"
        f"?stock_type=used"
        f"&makes[]={make_slug}"
        f"&models[]={model_slug}"
        f"&maximum_distance=all"
        f"&zip=60606"
        f"&page={page}"
    )


# ---------------------------------------------------------------------------
# HTML parsing — pure functions
# ---------------------------------------------------------------------------

# Pattern to extract individual vehicle-card blocks from the HTML.
# Cars.com wraps each listing in <div class="vehicle-card ..."> ... </div>
# We grab everything between the opening tag and the next vehicle-card (or EOF).
_CARD_PATTERN = re.compile(
    r'<div[^>]*class="[^"]*vehicle-card[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*vehicle-card|<div[^>]*id="pagination"|\Z)',
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
    """Extract an integer dollar amount from strings like '$142,500'.

    Returns None for non-numeric prices ('Call for Price', 'Request a Quote').
    """
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
    """Parse listing card data from a Cars.com search results page.

    Returns a list of dicts, each with keys:
    ``title``, ``price_text``, ``mileage_text``, ``url``, ``dealer``, ``stock_type``.
    """
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
            "title": title,
            "price_text": price_text,
            "mileage_text": mileage_text,
            "url": link_m.group(1),
            "dealer": dealer,
            "stock_type": stock_type,
        })

    return results


def parse_listing(item: dict) -> tuple[ScrapedListing | None, str]:
    """Convert a parsed card dict into a ScrapedListing.

    Returns ``(listing_or_None, skip_reason)``.  ``skip_reason`` is ``""`` on
    success.
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
    mileage = parse_mileage(item.get("mileage_text", ""))
    color = parse_color(title)

    listing = ScrapedListing(
        source=SOURCE,
        source_url=full_url,
        sale_type="listing",
        raw_title=title,
        year=year,
        asking_price=price,
        sold_price=None,
        is_sold=False,
        listed_at=datetime.now(timezone.utc),
        sold_at=None,
        mileage=mileage,
        color=color,
        raw_data={
            "title": title,
            "url": full_url,
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


# ---------------------------------------------------------------------------
# HTTP fetching
# ---------------------------------------------------------------------------

def fetch_page_sync(url: str) -> str:
    """Fetch a single page using curl_cffi (sync, called from thread).

    curl_cffi impersonates a Chrome TLS fingerprint to pass Cloudflare's
    TLS-based bot detection.
    """
    resp = cffi_requests.get(
        url,
        headers=_HEADERS,
        impersonate="chrome",
        timeout=30,
        allow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text


async def fetch_page(url: str) -> str:
    """Async wrapper — runs the sync curl_cffi call in a thread executor."""
    return await asyncio.to_thread(fetch_page_sync, url)


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class CarsComScraper(BaseScraper):
    source = SOURCE

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._selected_keys: set[str] | None = kwargs.pop("selected_keys", None)
        self._cancel_event: asyncio.Event | None = kwargs.pop("cancel_event", None)
        super().__init__(*args, **kwargs)

    def _is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def _get_urls(self) -> list[tuple[str, str, str, str]]:
        """Return the (possibly filtered) list of model URLs to scrape."""
        if self._selected_keys is None:
            return list(CARS_COM_URLS)
        return [(k, l, m, mo) for k, l, m, mo in CARS_COM_URLS if k in self._selected_keys]

    async def scrape(self) -> list[ScrapedListing]:
        urls = self._get_urls()
        if not urls:
            await self._emit("warning", "No Cars.com URLs selected — nothing to scrape.")
            return []

        all_listings: list[ScrapedListing] = []
        seen_urls: set[str] = set()

        await self._emit(
            "progress",
            f"Starting Cars.com scrape: {len(urls)} model searches selected",
            {"total_urls": len(urls), "selected_keys": [k for k, _, _, _ in urls]},
        )

        for i, (key, label, make_slug, model_slug) in enumerate(urls, 1):
            if self._is_cancelled():
                await self._emit(
                    "warning",
                    f"Scrape cancelled after {i - 1}/{len(urls)} models. "
                    f"Returning {len(all_listings)} listings collected so far.",
                    {"cancelled_at": i, "total_collected": len(all_listings)},
                )
                break

            model_listings = 0
            model_dupes = 0
            skip_counts: dict[str, int] = {}

            for page_num in range(1, MAX_PAGES_PER_SEARCH + 1):
                if self._is_cancelled():
                    break

                search_url = build_search_url(make_slug, model_slug, page=page_num)

                await self._emit(
                    "progress",
                    f"[{i}/{len(urls)}] {label} (page {page_num})…",
                    {
                        "label": label,
                        "key": key,
                        "page": page_num,
                        "term_index": i,
                        "total_terms": len(urls),
                    },
                )

                try:
                    html = await fetch_page(search_url)
                except Exception as exc:
                    await self._emit(
                        "error",
                        f"[{i}/{len(urls)}] {label} page {page_num}: HTTP error — {exc}",
                        {"label": label, "key": key, "page": page_num, "error": str(exc)},
                    )
                    break  # stop pagination for this model on error

                items = extract_listings_from_html(html)
                if not items:
                    break  # no results on this page — stop pagination

                for item in items:
                    listing, reason = parse_listing(item)
                    if listing is None:
                        skip_counts[reason] = skip_counts.get(reason, 0) + 1
                        continue
                    if listing.source_url in seen_urls:
                        model_dupes += 1
                        continue
                    seen_urls.add(listing.source_url)
                    all_listings.append(listing)
                    model_listings += 1

                # Stop if there's no next page
                if not has_next_page(html):
                    break

                # Be polite — longer delay for Cloudflare rate limits
                await asyncio.sleep(3.0)

            # Emit per-model summary
            page_data = {
                "label": label,
                "key": key,
                "new_listings": model_listings,
                "duplicates": model_dupes,
                "skipped": skip_counts,
                "running_total": len(all_listings),
            }

            if model_listings == 0:
                await self._emit(
                    "warning",
                    f"[{i}/{len(urls)}] {label}: 0 new listings"
                    + (f" (skipped: {skip_counts})" if skip_counts else ""),
                    page_data,
                )
            else:
                skip_summary = ""
                if skip_counts:
                    parts = [f"{v} {k}" for k, v in skip_counts.items()]
                    skip_summary = f" — skipped: {', '.join(parts)}"
                dup_summary = f", {model_dupes} dups" if model_dupes else ""
                await self._emit(
                    "progress",
                    f"[{i}/{len(urls)}] {label}: {model_listings} new{dup_summary}"
                    f"{skip_summary} (total: {len(all_listings)})",
                    page_data,
                )

            # Delay between models
            if i < len(urls) and not self._is_cancelled():
                await asyncio.sleep(3.0)

        return all_listings
