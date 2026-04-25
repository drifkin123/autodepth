"""Real-time event broadcaster for scraper progress streaming."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ScrapeEvent:
    type: str  # "start" | "progress" | "complete" | "error"
    source: str
    message: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "source": self.source,
            "message": self.message,
            "timestamp": self.timestamp,
            "data": self.data,
        }


class ScrapeBroadcaster:
    """In-process pub/sub for scrape events. One subscriber per WebSocket client."""

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue[ScrapeEvent | None]] = []
        self.is_running: bool = False
        self._cancel_event: asyncio.Event | None = None

    def subscribe(self) -> asyncio.Queue[ScrapeEvent | None]:
        """Return a new queue that will receive all published events."""
        q: asyncio.Queue[ScrapeEvent | None] = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[ScrapeEvent | None]) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def publish(self, event: ScrapeEvent) -> None:
        for q in self._queues:
            await q.put(event)

    async def signal_done(self) -> None:
        """Push a sentinel None to tell subscribers the stream is finished."""
        for q in self._queues:
            await q.put(None)

    def request_cancel(self) -> None:
        """Signal the running scrape to stop after the current URL."""
        if self._cancel_event is not None:
            self._cancel_event.set()

    def new_cancel_event(self) -> asyncio.Event:
        """Create a fresh cancellation event for a new scrape run."""
        self._cancel_event = asyncio.Event()
        return self._cancel_event

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()


# Module-level singleton — imported by scrapers and admin routes.
broadcaster = ScrapeBroadcaster()
