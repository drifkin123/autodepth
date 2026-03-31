"""Scraper runner — runs all configured scrapers in sequence."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.scrapers.bring_a_trailer import BringATrailerScraper

if TYPE_CHECKING:
    from app.broadcast import ScrapeBroadcaster

logger = logging.getLogger(__name__)


async def run_all_scrapers(
    session: AsyncSession,
    broadcaster: "ScrapeBroadcaster | None" = None,
    *,
    bat_selected_keys: set[str] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> dict[str, tuple[int, int]]:
    """
    Run every configured scraper and return a summary dict:
        { source_name: (records_found, records_inserted) }

    Parameters:
        bat_selected_keys: If provided, only scrape these BaT URL keys.
                           None means scrape all.
        cancel_event: If set, scrapers check this to stop early.
    """
    results: dict[str, tuple[int, int]] = {}

    # ── Bring a Trailer ──────────────────────────────────────────────────
    scraper = BringATrailerScraper(
        session,
        broadcaster,
        selected_keys=bat_selected_keys,
        cancel_event=cancel_event,
    )
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

    # Add future scrapers here with their own source-specific options.

    return results
