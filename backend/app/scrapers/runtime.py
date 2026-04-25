"""Shared reliability helpers for source scrapers."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
}

BLOCK_STATUS_CODES = {401, 403, 407, 429}


class TransientScrapeError(Exception):
    """A temporary scraper failure that may succeed after retrying."""


class BlockedScrapeError(Exception):
    """A source response indicates access is blocked or rate-limited."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter: float = 0.25

    def delay_for_attempt(self, attempt: int) -> float:
        base_delay = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** max(attempt - 1, 0)),
        )
        if self.jitter <= 0:
            return base_delay
        jitter_amount = base_delay * self.jitter
        return random.uniform(base_delay - jitter_amount, base_delay + jitter_amount)


def is_block_status(status_code: int | None) -> bool:
    return status_code in BLOCK_STATUS_CODES


def polite_delay_seconds(min_seconds: float = 1.5, max_seconds: float = 4.0) -> float:
    return random.uniform(min_seconds, max_seconds)


async def _maybe_sleep(
    sleep: Callable[[float], Awaitable[object] | object],
    delay: float,
) -> None:
    result = sleep(delay)
    if hasattr(result, "__await__"):
        await result  # type: ignore[misc]


async def run_with_retries(
    operation: Callable[[int], Awaitable[T]],
    policy: RetryPolicy,
    *,
    on_retry: Callable[[int, Exception, float], object] | None = None,
    sleep: Callable[[float], Awaitable[object] | object] = asyncio.sleep,
) -> T:
    """Run an async operation with bounded retries for transient failures."""
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await operation(attempt)
        except BlockedScrapeError:
            raise
        except TransientScrapeError as exc:
            if attempt >= policy.max_attempts:
                raise
            delay = policy.delay_for_attempt(attempt)
            if on_retry:
                on_retry(attempt, exc, delay)
            await _maybe_sleep(sleep, delay)
    raise RuntimeError("retry loop exited unexpectedly")
