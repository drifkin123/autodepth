"""Tests for raw pipeline worker primitives."""

from __future__ import annotations

import uuid

import pytest

from app.services.raw_worker import (
    RedisGlobalRateLimiter,
    enqueue_parse_job,
    redis_settings_from_url,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.enqueued: list[tuple[str, uuid.UUID]] = []

    async def eval(self, script: str, numkeys: int, key: str, now: float, delay: float) -> float:
        last_value = self.values.get(key)
        if last_value is not None:
            remaining = delay - (now - float(last_value))
            if remaining > 0:
                return remaining
        self.values[key] = str(now)
        return 0.0

    async def enqueue_job(
        self,
        function_name: str,
        raw_page_id: uuid.UUID,
        *,
        _job_id: str,
    ) -> None:
        self.enqueued.append((function_name, raw_page_id))


@pytest.mark.asyncio
async def test_redis_global_rate_limiter_waits_until_shared_delay_budget_is_available() -> None:
    redis = _FakeRedis()
    sleeps: list[float] = []
    times = iter([100.0, 101.0, 104.0])

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    limiter = RedisGlobalRateLimiter(
        redis,
        key="bat:global:list",
        delay_seconds=lambda: 3.0,
        sleep=fake_sleep,
        clock=lambda: next(times),
    )

    await limiter.wait()
    await limiter.wait()

    assert sleeps == [2.0]
    assert redis.values["bat:global:list"] == "104.0"


@pytest.mark.asyncio
async def test_enqueue_parse_job_uses_deterministic_uuid_job_id() -> None:
    redis = _FakeRedis()
    raw_page_id = uuid.uuid4()

    await enqueue_parse_job(redis, raw_page_id)

    assert redis.enqueued == [("parse_bat_raw_page_job", raw_page_id)]


def test_redis_settings_from_url_parses_database_and_credentials() -> None:
    settings = redis_settings_from_url("redis://user:secret@redis.local:6380/2")

    assert settings.host == "redis.local"
    assert settings.port == 6380
    assert settings.database == 2
    assert settings.username == "user"
    assert settings.password == "secret"
