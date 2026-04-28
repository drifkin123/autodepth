"""Redis/arq worker primitives for raw page ingestion."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol
from urllib.parse import unquote, urlsplit

from arq.connections import RedisSettings

from app.db import async_session_factory
from app.scrapers.bat_config import _list_page_delay_seconds
from app.services.artifacts import get_artifact_store
from app.services.bat_raw_pipeline import fetch_bat_target_to_raw_page, parse_bat_raw_page
from app.settings import settings

_RATE_LIMIT_SCRIPT = """
local last = redis.call('GET', KEYS[1])
local now = tonumber(ARGV[1])
local delay = tonumber(ARGV[2])
if last then
  local remaining = delay - (now - tonumber(last))
  if remaining > 0 then
    return remaining
  end
end
redis.call('SET', KEYS[1], tostring(now), 'EX', 300)
return 0
"""


class RedisLike(Protocol):
    async def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        now: float,
        delay: float,
    ) -> float:
        """Evaluate a Redis script."""

    async def enqueue_job(
        self,
        function_name: str,
        raw_page_id: uuid.UUID,
        *,
        _job_id: str,
    ) -> None:
        """Enqueue an arq job."""


class RedisGlobalRateLimiter:
    """Cross-process rate limiter using one Redis timestamp key."""

    def __init__(
        self,
        redis: RedisLike,
        *,
        key: str,
        delay_seconds: Callable[[], float],
        sleep: Callable[[float], Awaitable[object] | object] = asyncio.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.redis = redis
        self.key = key
        self.delay_seconds = delay_seconds
        self.sleep = sleep
        self.clock = clock

    async def wait(self) -> None:
        while True:
            remaining = float(
                await self.redis.eval(
                    _RATE_LIMIT_SCRIPT,
                    1,
                    self.key,
                    self.clock(),
                    self.delay_seconds(),
                )
            )
            if remaining <= 0:
                return
            result = self.sleep(remaining)
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]


async def enqueue_parse_job(redis: RedisLike, raw_page_id: uuid.UUID) -> None:
    await redis.enqueue_job(
        "parse_bat_raw_page_job",
        raw_page_id,
        _job_id=f"parse-bat-raw-page:{raw_page_id}",
    )


async def fetch_bat_raw_target_job(ctx: dict, target_id: uuid.UUID | str) -> None:
    artifact_store = ctx.get("artifact_store") or get_artifact_store()
    session_factory = ctx.get("session_factory") or async_session_factory
    rate_limiter = ctx.get("bat_rate_limiter")
    async with session_factory() as session:
        await fetch_bat_target_to_raw_page(
            session,
            artifact_store=artifact_store,
            target_id=uuid.UUID(str(target_id)),
            enqueue_parse=lambda raw_page_id: enqueue_parse_job(ctx["redis"], raw_page_id),
            rate_limiter=rate_limiter,
        )


async def parse_bat_raw_page_job(ctx: dict, raw_page_id: uuid.UUID | str) -> None:
    artifact_store = ctx.get("artifact_store") or get_artifact_store()
    session_factory = ctx.get("session_factory") or async_session_factory
    async with session_factory() as session:
        await parse_bat_raw_page(
            session,
            artifact_store=artifact_store,
            raw_page_id=uuid.UUID(str(raw_page_id)),
        )


async def startup(ctx: dict) -> None:
    ctx["artifact_store"] = get_artifact_store()
    ctx["session_factory"] = async_session_factory
    ctx["bat_rate_limiter"] = RedisGlobalRateLimiter(
        ctx["redis"],
        key="autodepth:bat:global_rate_limit",
        delay_seconds=_list_page_delay_seconds,
    )


def redis_settings_from_url(redis_url: str) -> RedisSettings:
    parsed = urlsplit(redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").strip("/") or "0"),
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
        ssl=parsed.scheme == "rediss",
    )


class WorkerSettings:
    functions = [fetch_bat_raw_target_job, parse_bat_raw_page_job]
    on_startup = startup
    redis_settings = redis_settings_from_url(settings.redis_url)
