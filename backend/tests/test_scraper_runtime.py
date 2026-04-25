"""Tests for shared scraper reliability/runtime behavior."""

from __future__ import annotations

import pytest

from app.scrapers.runtime import (
    BlockedScrapeError,
    RetryPolicy,
    TransientScrapeError,
    is_block_status,
    polite_delay_seconds,
    run_with_retries,
)


@pytest.mark.asyncio
async def test_retries_transient_errors_with_bounded_backoff() -> None:
    attempts: list[int] = []
    retry_delays: list[float] = []

    async def operation(attempt: int) -> str:
        attempts.append(attempt)
        if attempt < 3:
            raise TransientScrapeError("temporary upstream failure")
        return "ok"

    result = await run_with_retries(
        operation,
        RetryPolicy(max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=10.0, jitter=0),
        on_retry=lambda attempt, exc, delay: retry_delays.append(delay),
        sleep=lambda delay: None,
    )

    assert result == "ok"
    assert attempts == [1, 2, 3]
    assert retry_delays == [1.0, 2.0]


@pytest.mark.asyncio
async def test_blocked_errors_are_not_retried() -> None:
    attempts: list[int] = []

    async def operation(attempt: int) -> str:
        attempts.append(attempt)
        raise BlockedScrapeError("blocked", status_code=429)

    with pytest.raises(BlockedScrapeError):
        await run_with_retries(
            operation,
            RetryPolicy(max_attempts=3, base_delay_seconds=0, jitter=0),
            sleep=lambda delay: None,
        )

    assert attempts == [1]


def test_block_status_detection_and_polite_delay_bounds() -> None:
    assert is_block_status(403) is True
    assert is_block_status(429) is True
    assert is_block_status(500) is False

    delay = polite_delay_seconds(1.5, 3.5)
    assert 1.5 <= delay <= 3.5
