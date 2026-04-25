"""Scraper runner and background job orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.scrapers.bring_a_trailer import BringATrailerScraper
from app.scrapers.cars_and_bids import CarsAndBidsScraper

if TYPE_CHECKING:
    from app.broadcast import ScrapeBroadcaster

logger = logging.getLogger(__name__)


async def run_all_scrapers(
    session: AsyncSession,
    broadcaster: ScrapeBroadcaster | None = None,
    *,
    bat_selected_keys: set[str] | None = None,
    carsandbids_selected_keys: set[str] | None = None,
    cancel_event: asyncio.Event | None = None,
    mode: str = "incremental",
) -> dict[str, tuple[int, int]]:
    results: dict[str, tuple[int, int]] = {}

    scraper = BringATrailerScraper(
        session,
        broadcaster,
        selected_keys=bat_selected_keys,
        cancel_event=cancel_event,
        mode=mode,
    )
    logger.info("Starting scraper: %s", scraper.source)
    try:
        results[scraper.source] = await scraper.run()
    except Exception:
        logger.exception("Scraper %s failed", scraper.source)
        results[scraper.source] = (-1, -1)

    if not (cancel_event and cancel_event.is_set()):
        cab_scraper = CarsAndBidsScraper(
            session,
            broadcaster,
            selected_keys=carsandbids_selected_keys,
            cancel_event=cancel_event,
            mode=mode,
        )
        logger.info("Starting scraper: %s", cab_scraper.source)
        try:
            results[cab_scraper.source] = await cab_scraper.run()
        except Exception:
            logger.exception("Scraper %s failed", cab_scraper.source)
            results[cab_scraper.source] = (-1, -1)

    return results


async def run_scrape_job(
    broadcaster: ScrapeBroadcaster,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    *,
    bat_selected_keys: set[str] | None = None,
    carsandbids_selected_keys: set[str] | None = None,
    mode: str = "incremental",
) -> None:
    from app.broadcast import ScrapeEvent

    broadcaster.is_running = True
    cancel_event = broadcaster.new_cancel_event()
    await broadcaster.publish(
        ScrapeEvent(type="start", source="system", message=f"Scrape job started ({mode}).")
    )
    try:
        async with session_factory() as session:
            results = await run_all_scrapers(
                session,
                broadcaster,
                bat_selected_keys=bat_selected_keys,
                carsandbids_selected_keys=carsandbids_selected_keys,
                cancel_event=cancel_event,
                mode=mode,
            )

        summary_parts = [
            f"{source}: {found} found / {inserted} inserted"
            for source, (found, inserted) in results.items()
        ]
        if broadcaster.is_cancelled:
            await broadcaster.publish(
                ScrapeEvent(
                    type="complete",
                    source="system",
                    message="Scrape stopped by user. " + " | ".join(summary_parts),
                    data={"scrape_results": results, "cancelled": True},
                )
            )
        else:
            await broadcaster.publish(
                ScrapeEvent(
                    type="complete",
                    source="system",
                    message="Scrape job complete. " + " | ".join(summary_parts),
                    data={"scrape_results": results},
                )
            )
    except Exception as exc:
        logger.exception("Background scrape job failed")
        await broadcaster.publish(
            ScrapeEvent(type="error", source="system", message=f"Job failed: {exc}")
        )
    finally:
        broadcaster.is_running = False
        await broadcaster.signal_done()
