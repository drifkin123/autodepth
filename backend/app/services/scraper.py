"""Scraper runner — runs all configured scrapers in sequence.

Also contains background job orchestration for admin-triggered scrape+depreciation runs.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.scrapers.bring_a_trailer import BringATrailerScraper
from app.scrapers.cars_and_bids import CarsAndBidsScraper
from app.scrapers.cars_com import CarsComScraper

if TYPE_CHECKING:
    from app.broadcast import ScrapeBroadcaster

logger = logging.getLogger(__name__)


async def run_all_scrapers(
    session: AsyncSession,
    broadcaster: "ScrapeBroadcaster | None" = None,
    *,
    bat_selected_keys: set[str] | None = None,
    cars_com_selected_keys: set[str] | None = None,
    carsandbids_selected_keys: set[str] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> dict[str, tuple[int, int]]:
    """
    Run every configured scraper and return a summary dict:
        { source_name: (records_found, records_inserted) }
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

    # ── Cars.com ──────────────────────────────────────────────────────────
    if not (cancel_event and cancel_event.is_set()):
        scraper_cc = CarsComScraper(
            session,
            broadcaster,
            selected_keys=cars_com_selected_keys,
            cancel_event=cancel_event,
        )
        logger.info("Starting scraper: %s", scraper_cc.source)
        try:
            found, inserted = await scraper_cc.run()
            results[scraper_cc.source] = (found, inserted)
            logger.info(
                "Scraper %s complete: %d found, %d inserted",
                scraper_cc.source,
                found,
                inserted,
            )
        except Exception:
            logger.exception("Scraper %s failed", scraper_cc.source)
            results[scraper_cc.source] = (-1, -1)

    # ── Cars & Bids ───────────────────────────────────────────────────────
    if not (cancel_event and cancel_event.is_set()):
        scraper_cab = CarsAndBidsScraper(
            session,
            broadcaster,
            selected_keys=carsandbids_selected_keys,
            cancel_event=cancel_event,
        )
        logger.info("Starting scraper: %s", scraper_cab.source)
        try:
            found, inserted = await scraper_cab.run()
            results[scraper_cab.source] = (found, inserted)
            logger.info(
                "Scraper %s complete: %d found, %d inserted",
                scraper_cab.source,
                found,
                inserted,
            )
        except Exception:
            logger.exception("Scraper %s failed", scraper_cab.source)
            results[scraper_cab.source] = (-1, -1)

    return results


async def run_scrape_job(
    broadcaster: "ScrapeBroadcaster",
    session_factory: "asyncio.coroutine",
    *,
    bat_selected_keys: set[str] | None = None,
    cars_com_selected_keys: set[str] | None = None,
    carsandbids_selected_keys: set[str] | None = None,
) -> None:
    """Run scrapers + depreciation model as a background task with event streaming."""
    from app.broadcast import ScrapeEvent
    from app.services.depreciation import run_all_depreciation_models

    broadcaster.is_running = True
    cancel_event = broadcaster.new_cancel_event()
    await broadcaster.publish(
        ScrapeEvent(type="start", source="system", message="Scrape job started.")
    )
    try:
        async with session_factory() as session:
            results = await run_all_scrapers(
                session,
                broadcaster,
                bat_selected_keys=bat_selected_keys,
                cars_com_selected_keys=cars_com_selected_keys,
                carsandbids_selected_keys=carsandbids_selected_keys,
                cancel_event=cancel_event,
            )

        if broadcaster.is_cancelled:
            await broadcaster.publish(
                ScrapeEvent(
                    type="complete",
                    source="system",
                    message="Scrape stopped by user. Skipping depreciation models.",
                    data={"scrape_results": results, "cancelled": True},
                )
            )
        else:
            summary_parts = [
                f"{src}: {f} found / {i} inserted" for src, (f, i) in results.items()
            ]
            await broadcaster.publish(
                ScrapeEvent(
                    type="progress",
                    source="system",
                    message="All scrapers done. Running depreciation models…",
                    data={"scrape_results": results},
                )
            )

            async with session_factory() as session:
                await run_all_depreciation_models(session)

            await broadcaster.publish(
                ScrapeEvent(
                    type="complete",
                    source="system",
                    message="Job complete. " + " | ".join(summary_parts),
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


async def run_depreciation_job(
    broadcaster: "ScrapeBroadcaster",
    session_factory: "asyncio.coroutine",
) -> None:
    """Re-run depreciation models without scraping, with event streaming."""
    from app.broadcast import ScrapeEvent
    from app.services.depreciation import run_all_depreciation_models

    broadcaster.is_running = True
    await broadcaster.publish(
        ScrapeEvent(type="start", source="system", message="Running depreciation models…")
    )
    try:
        async with session_factory() as session:
            statuses = await run_all_depreciation_models(session)
        await broadcaster.publish(
            ScrapeEvent(
                type="complete",
                source="system",
                message=f"Depreciation models updated for {len(statuses)} car(s).",
                data={"statuses": statuses},
            )
        )
    except Exception as exc:
        await broadcaster.publish(
            ScrapeEvent(type="error", source="system", message=str(exc))
        )
    finally:
        broadcaster.is_running = False
        await broadcaster.signal_done()
