"""Run scrapers manually for testing/backfilling.

Usage from backend/:
    # Run all scrapers
    python scripts/run_scraper.py

    # Run a specific source
    python scripts/run_scraper.py --source bring_a_trailer --mode backfill
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
from app.services.bat_backfill import run_bat_concurrent_backfill
from app.services.scraper import run_all_scrapers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

SCRAPER_MAP = {
    "bring_a_trailer": BringATrailerScraper,
    "cars_and_bids": CarsAndBidsScraper,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="Scraper source name (default: all)")
    parser.add_argument(
        "--mode",
        choices=("incremental", "backfill"),
        default="incremental",
        help="Crawl mode metadata recorded on scrape runs",
    )
    parser.add_argument(
        "--concurrent",
        action="store_true",
        help="Run supported backfills with bounded concurrent workers",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Concurrent worker count for supported backfills",
    )
    parser.add_argument(
        "--bat-target-source",
        choices=("models", "makes"),
        default="models",
        help="BaT targets to enqueue for concurrent backfill",
    )
    parser.add_argument(
        "--skip-details",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip BaT detail-page enrichment during concurrent backfill",
    )
    return parser.parse_args(argv)


async def main(
    source: str | None,
    mode: str,
    *,
    concurrent: bool = False,
    workers: int = 3,
    bat_target_source: str = "models",
    skip_details: bool = True,
) -> None:
    if concurrent:
        if source != "bring_a_trailer" or mode != "backfill":
            print("Concurrent mode currently supports only BaT backfill.")
            sys.exit(1)
        results = await run_bat_concurrent_backfill(
            async_session_factory,
            workers=workers,
            target_source=bat_target_source,
            skip_details=skip_details,
            mode=mode,
        )
        for src, (found, inserted) in results.items():
            print(f"{src}: {found} found, {inserted} inserted")
        return

    async with async_session_factory() as session:
        if source:
            cls = SCRAPER_MAP.get(source)
            if cls is None:
                print(f"Unknown source: {source}. Available: {list(SCRAPER_MAP)}")
                sys.exit(1)
            scraper = cls(session, mode=mode)
            found, inserted = await scraper.run()
            print(f"{source}: {found} found, {inserted} inserted")
        else:
            results = await run_all_scrapers(session, mode=mode)
            for src, (found, inserted) in results.items():
                status = "ERROR" if found == -1 else f"{found} found, {inserted} inserted"
                print(f"{src}: {status}")


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        main(
            args.source,
            args.mode,
            concurrent=args.concurrent,
            workers=args.workers,
            bat_target_source=args.bat_target_source,
            skip_details=args.skip_details,
        )
    )
