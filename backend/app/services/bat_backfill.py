"""Concurrent Bring a Trailer backfill runner."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.scrapers.bat_backfill_worker import (
    BaTConcurrentBackfillWorker,
    SharedDelayRateLimiter,
)
from app.scrapers.bat_config import _list_page_delay_seconds
from app.scrapers.bat_target_processing import BatTarget
from app.scrapers.bat_targets import fetch_model_entries
from app.scrapers.makes import BAT_MAKES


async def _load_target_entries(target_source: str) -> list[BatTarget]:
    if target_source == "makes":
        return list(BAT_MAKES)
    if target_source != "models":
        raise ValueError("target_source must be 'models' or 'makes'")
    async with httpx.AsyncClient() as client:
        return await fetch_model_entries(client)


async def run_bat_concurrent_backfill(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    *,
    workers: int = 3,
    target_source: str = "models",
    target_entries: list[BatTarget] | None = None,
    selected_keys: set[str] | None = None,
    skip_details: bool = True,
    mode: str = "backfill",
    rate_limiter: SharedDelayRateLimiter | None = None,
) -> dict[str, tuple[int, int]]:
    """Run BaT backfill targets concurrently through one shared request limiter."""
    if workers < 1:
        raise ValueError("workers must be at least 1")

    targets = (
        target_entries
        if target_entries is not None
        else await _load_target_entries(target_source)
    )
    if selected_keys is not None:
        targets = [target for target in targets if target[0] in selected_keys]

    target_queue: asyncio.Queue[BatTarget] = asyncio.Queue()
    for target in targets:
        target_queue.put_nowait(target)

    limiter = rate_limiter or SharedDelayRateLimiter(_list_page_delay_seconds)
    cancel_event = asyncio.Event()

    async def run_worker(worker_number: int) -> tuple[int, int]:
        async with session_factory() as session:
            scraper = BaTConcurrentBackfillWorker(
                session,
                mode=mode,
                skip_details=skip_details,
                list_rate_limiter=limiter,
                cancel_event=cancel_event,
                target_queue=target_queue,
                target_total=len(targets),
                worker_id=f"bat-worker-{worker_number}",
            )
            return await scraper.run()

    tasks = [
        asyncio.create_task(run_worker(worker_number))
        for worker_number in range(1, min(workers, len(targets) or 1) + 1)
    ]
    if not tasks:
        return {"bring_a_trailer": (0, 0)}

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    first_error: BaseException | None = None
    for task in done:
        error = task.exception()
        if error is not None:
            first_error = error
            break

    if first_error is not None:
        cancel_event.set()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        raise first_error

    results = list(await asyncio.gather(*pending, *done))
    return {
        "bring_a_trailer": (
            sum(found for found, _inserted in results),
            sum(inserted for _found, inserted in results),
        )
    }
