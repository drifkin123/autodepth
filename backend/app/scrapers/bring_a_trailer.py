"""Bring a Trailer scraper — confirmed auction sales only."""

import asyncio
import re
from datetime import datetime, timezone

from playwright.async_api import Browser, async_playwright

from app.scrapers.base import BaseScraper, ScrapedListing

# BaT search term → these map to our supported makes/models
BAT_SEARCH_TERMS = [
    "porsche 911 gt3",
    "porsche 911 turbo s",
    "porsche cayman gt4",
    "porsche 918 spyder",
    "ferrari 458",
    "ferrari 488",
    "ferrari f8",
    "ferrari sf90",
    "ferrari roma",
    "lamborghini huracan",
    "lamborghini aventador",
    "lamborghini urus",
    "mclaren 570s",
    "mclaren 600lt",
    "mclaren 720s",
    "mclaren 765lt",
    "mclaren artura",
    "mercedes-amg gt",
    "audi r8",
    "audi rs6",
    "audi rs7",
    "chevrolet corvette c8",
    "lotus emira",
    "lotus evora",
    "lotus exige",
]

# Max pages to fetch per search term (each page has ~25 results)
MAX_PAGES_PER_TERM = 4

SOURCE = "bring_a_trailer"
BASE_URL = "https://bringatrailer.com"
SEARCH_URL = BASE_URL + "/listing-results/?s={term}&sold=1&page={page}"


def _parse_price(text: str) -> int | None:
    """Extract an integer dollar amount from strings like '$142,500' or '142500'."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _parse_year(title: str) -> int | None:
    """Extract a 4-digit model year from the start of a listing title."""
    m = re.match(r"\b(19|20)\d{2}\b", title.strip())
    return int(m.group(0)) if m else None


def _parse_mileage(text: str) -> int | None:
    """Extract mileage from strings like '12,345 Miles' or '12345-mile'."""
    m = re.search(r"([\d,]+)\s*-?\s*mile", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _parse_sold_date(text: str) -> datetime | None:
    """Parse BaT's sold date strings like 'Sold on January 15, 2024'."""
    m = re.search(r"(\w+ \d{1,2},\s*\d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%B %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


async def _scrape_search_page(
    browser: Browser,
    term: str,
    page_num: int,
) -> list[ScrapedListing]:
    """Scrape one page of BaT search results and return parsed listings."""
    url = SEARCH_URL.format(term=term.replace(" ", "+"), page=page_num)
    page = await browser.new_page()
    listings: list[ScrapedListing] = []

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        # Wait for listing cards to appear (or bail if none)
        try:
            await page.wait_for_selector(".listing-card", timeout=10_000)
        except Exception:
            return listings  # empty page — no more results

        cards = await page.query_selector_all(".listing-card")

        for card in cards:
            try:
                listing = await _parse_card(card, page)
                if listing is not None:
                    listings.append(listing)
            except Exception:
                # Skip malformed cards rather than aborting the whole page
                continue

    finally:
        await page.close()

    return listings


async def _parse_card(card, page) -> ScrapedListing | None:  # type: ignore[no-untyped-def]
    """Extract a ScrapedListing from a single BaT listing card element."""
    # Title / URL
    title_el = await card.query_selector(".listing-title a, h3 a, .title a")
    if title_el is None:
        return None

    raw_title = (await title_el.inner_text()).strip()
    href = await title_el.get_attribute("href")
    if not href:
        return None
    source_url = href if href.startswith("http") else BASE_URL + href

    year = _parse_year(raw_title)
    if year is None:
        return None

    # Sold price — BaT shows "Sold for $X" on completed auctions
    price_el = await card.query_selector(".listing-available-info, .sold-price, .bid-value")
    sold_price: int | None = None
    asking_price: int = 0

    if price_el:
        price_text = await price_el.inner_text()
        parsed = _parse_price(price_text)
        if parsed and parsed > 0:
            sold_price = parsed
            asking_price = parsed  # for auctions, asking == sold (opening bid was asking)

    if sold_price is None:
        return None  # skip listings without a confirmed sale price

    # Sold date
    date_el = await card.query_selector(".listing-available-info, .sold-date, time")
    sold_at: datetime | None = None
    if date_el:
        date_text = await date_el.inner_text()
        sold_at = _parse_sold_date(date_text)

    # Use sold_at as listed_at for auctions (BaT doesn't separately surface listing date)
    listed_at = sold_at or datetime.now(timezone.utc)

    # Mileage — often in the subtitle or card metadata
    meta_el = await card.query_selector(".listing-metadata, .card-meta")
    mileage: int | None = None
    color: str | None = None
    if meta_el:
        meta_text = await meta_el.inner_text()
        mileage = _parse_mileage(meta_text)

    # Color — look for color info in the title itself (BaT often includes it)
    color_match = re.search(
        r"\b(white|black|silver|grey|gray|blue|red|yellow|green|orange|brown|"
        r"purple|gold|tan|beige|guards red|chalk|python green|miami blue|"
        r"racing yellow|shark blue|jet black)\b",
        raw_title,
        re.IGNORECASE,
    )
    if color_match:
        color = color_match.group(0).title()

    return ScrapedListing(
        source=SOURCE,
        source_url=source_url,
        sale_type="auction",
        raw_title=raw_title,
        year=year,
        asking_price=asking_price,
        sold_price=sold_price,
        is_sold=True,
        listed_at=listed_at,
        sold_at=sold_at,
        mileage=mileage,
        color=color,
        raw_data={"title": raw_title, "url": source_url},
    )


class BringATrailerScraper(BaseScraper):
    source = SOURCE

    async def scrape(self) -> list[ScrapedListing]:
        all_listings: list[ScrapedListing] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                for term in BAT_SEARCH_TERMS:
                    for page_num in range(1, MAX_PAGES_PER_TERM + 1):
                        page_listings = await _scrape_search_page(browser, term, page_num)
                        all_listings.extend(page_listings)

                        # If we got fewer results than expected, no more pages
                        if len(page_listings) < 10:
                            break

                        # Be polite — brief delay between pages
                        await asyncio.sleep(1.5)

            finally:
                await browser.close()

        return all_listings
