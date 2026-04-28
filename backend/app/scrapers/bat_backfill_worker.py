"""Concurrent Bring a Trailer backfill worker."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.scrapers.bat_target_processing import BatTarget
from app.scrapers.bring_a_trailer import BringATrailerScraper
from app.scrapers.runtime import BlockedScrapeError
from app.scrapers.types import ScrapedAuctionLot


@dataclass
class SharedDelayRateLimiter:
    """Serialize BaT list requests through one polite delay budget."""

    delay_factory: Callable[[], float]
    sleep: Callable[[float], Awaitable[object] | object] = asyncio.sleep

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_request_at: float | None = None

    async def wait(self) -> None:
        async with self._lock:
            if self._last_request_at is not None:
                elapsed = time.monotonic() - self._last_request_at
                delay = max(self.delay_factory() - elapsed, 0.0)
                if delay > 0:
                    result = self.sleep(delay)
                    if hasattr(result, "__await__"):
                        await result  # type: ignore[misc]
            self._last_request_at = time.monotonic()


class BaTConcurrentBackfillWorker(BringATrailerScraper):
    """A BaT scraper worker that pulls targets from a shared queue."""

    def __init__(
        self,
        *args,
        target_queue: asyncio.Queue[BatTarget],
        target_total: int,
        worker_id: str,
        **kwargs,
    ) -> None:  # type: ignore[no-untyped-def]
        self._target_queue = target_queue
        self._target_total = target_total
        self._worker_id = worker_id
        self._targets_started: list[str] = []
        self._targets_completed: list[str] = []
        self._targets_failed: list[str] = []
        super().__init__(*args, **kwargs)

    async def _update_worker_metadata(
        self,
        status: str,
        *,
        current_target: BatTarget | None = None,
        error: str | None = None,
    ) -> None:
        if self.current_scrape_run is None:
            return
        metadata = {
            **(self.current_scrape_run.metadata_json or {}),
            "worker_id": self._worker_id,
            "worker_status": status,
            "target_total": self._target_total,
            "targets_started": self._targets_started,
            "targets_completed": self._targets_completed,
            "targets_failed": self._targets_failed,
            "targets_remaining": self._target_queue.qsize(),
            "skip_details": self._skip_details,
        }
        if current_target is not None:
            metadata["current_target"] = {
                "key": current_target[0],
                "label": current_target[1],
                "path": current_target[2],
            }
        if error is not None:
            metadata["worker_error"] = error
        self.current_scrape_run.metadata_json = metadata
        await self.session.commit()

    async def scrape(self) -> list[ScrapedAuctionLot]:
        all_lots: list[ScrapedAuctionLot] = []
        seen_urls: set[str] = set()
        await self._update_worker_metadata("running")

        async with httpx.AsyncClient() as client:
            while not self._is_cancelled():
                try:
                    target = self._target_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self._targets_started.append(target[0])
                await self._update_worker_metadata("running", current_target=target)
                try:
                    await self._process_target(
                        client,
                        target=target,
                        index=len(self._targets_started),
                        total_urls=self._target_total,
                        seen_urls=seen_urls,
                        all_lots=all_lots,
                    )
                except BlockedScrapeError as exc:
                    self._targets_failed.append(target[0])
                    if self._cancel_event is not None:
                        self._cancel_event.set()
                    await self._update_worker_metadata(
                        "blocked",
                        current_target=target,
                        error=str(exc),
                    )
                    raise
                except Exception as exc:
                    self._targets_failed.append(target[0])
                    await self._update_worker_metadata(
                        "error",
                        current_target=target,
                        error=str(exc),
                    )
                    raise
                else:
                    self._targets_completed.append(target[0])
                    await self._update_worker_metadata("running", current_target=target)
                finally:
                    self._target_queue.task_done()

        await self._update_worker_metadata("cancelled" if self._is_cancelled() else "complete")
        return all_lots
