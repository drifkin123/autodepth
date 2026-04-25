"""Run scrapers manually for testing/backfilling.

Usage from backend/:
    # Run all scrapers
    python scripts/run_scraper.py

    # Run a specific source
    python scripts/run_scraper.py --source bring_a_trailer
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse

from app.db import async_session_factory
from app.scrapers.bring_a_trailer import BringATrailerScraper
from app.scrapers.cars_and_bids import CarsAndBidsScraper
from app.services.scraper import run_all_scrapers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

SCRAPER_MAP = {
    "bring_a_trailer": BringATrailerScraper,
    "cars_and_bids": CarsAndBidsScraper,
}


async def main(source: str | None) -> None:
    async with async_session_factory() as session:
        if source:
            cls = SCRAPER_MAP.get(source)
            if cls is None:
                print(f"Unknown source: {source}. Available: {list(SCRAPER_MAP)}")
                sys.exit(1)
            scraper = cls(session)
            found, inserted = await scraper.run()
            print(f"{source}: {found} found, {inserted} inserted")
        else:
            results = await run_all_scrapers(session)
            for src, (found, inserted) in results.items():
                status = "ERROR" if found == -1 else f"{found} found, {inserted} inserted"
                print(f"{src}: {status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="Scraper source name (default: all)")
    args = parser.parse_args()
    asyncio.run(main(args.source))
