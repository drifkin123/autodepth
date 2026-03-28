"""Scraper runner — runs all configured scrapers in sequence."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.scrapers.bring_a_trailer import BringATrailerScraper

logger = logging.getLogger(__name__)

# Ordered list of scrapers to run. Add new scrapers here as they're built.
SCRAPERS = [
    BringATrailerScraper,
]


async def run_all_scrapers(session: AsyncSession) -> dict[str, tuple[int, int]]:
    """
    Run every configured scraper and return a summary dict:
        { source_name: (records_found, records_inserted) }
    """
    results: dict[str, tuple[int, int]] = {}

    for ScraperClass in SCRAPERS:
        scraper = ScraperClass(session)
        logger.info("Starting scraper: %s", scraper.source)
        try:
            found, inserted = await scraper.run()
            results[scraper.source] = (found, inserted)
            logger.info(
                "Scraper %s complete: %d found, %d inserted",
                scraper.source,
                found,
                inserted,
            )
        except Exception:
            logger.exception("Scraper %s failed", scraper.source)
            results[scraper.source] = (-1, -1)

    return results
