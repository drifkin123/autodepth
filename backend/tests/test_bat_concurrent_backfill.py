"""Tests for the concurrent BaT backfill runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.scrape_run import ScrapeRun
from app.services.bat_backfill import (
    BaTConcurrentBackfillWorker,
    run_bat_concurrent_backfill,
)


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.add = MagicMock(side_effect=self.added.append)
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.merge = AsyncMock()
        self.get = AsyncMock(return_value=None)
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        self.execute = AsyncMock(return_value=result)


class _FakeSessionContext:
    def __init__(self, sessions: list[_FakeSession]) -> None:
        self._sessions = sessions
        self.session = _FakeSession()

    async def __aenter__(self) -> _FakeSession:
        self._sessions.append(self.session)
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _CountingLimiter:
    def __init__(self) -> None:
        self.wait_count = 0

    async def wait(self) -> None:
        self.wait_count += 1


@pytest.mark.asyncio
async def test_concurrent_runner_processes_each_target_once_and_records_worker_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processed_keys: list[str] = []
    limiter = _CountingLimiter()
    sessions: list[_FakeSession] = []

    async def fake_process_target(
        self: BaTConcurrentBackfillWorker,
        client: object,
        *,
        target: tuple[str, str, str],
        index: int,
        total_urls: int,
        seen_urls: set[str],
        all_lots: list[object],
    ) -> None:
        await self._wait_for_list_rate_limit()
        processed_keys.append(target[0])
        self.records_found += 1
        self.records_inserted += 1

    monkeypatch.setattr(
        BaTConcurrentBackfillWorker,
        "_process_target",
        fake_process_target,
    )

    targets = [
        ("acura", "Acura", "acura"),
        ("audi", "Audi", "audi"),
        ("bmw", "BMW", "bmw"),
        ("porsche", "Porsche", "porsche"),
    ]

    results = await run_bat_concurrent_backfill(
        lambda: _FakeSessionContext(sessions),
        target_entries=targets,
        workers=2,
        rate_limiter=limiter,
    )

    assert results == {"bring_a_trailer": (4, 4)}
    assert sorted(processed_keys) == ["acura", "audi", "bmw", "porsche"]
    assert len(processed_keys) == len(set(processed_keys))
    assert limiter.wait_count == len(targets)

    scrape_runs = [
        obj for session in sessions for obj in session.added if isinstance(obj, ScrapeRun)
    ]
    assert len(scrape_runs) == 2
    assert all(run.metadata_json["worker_id"].startswith("bat-worker-") for run in scrape_runs)
    assert sorted(
        key
        for run in scrape_runs
        for key in run.metadata_json["targets_completed"]
    ) == ["acura", "audi", "bmw", "porsche"]
