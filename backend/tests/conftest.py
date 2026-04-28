"""Shared pytest fixtures for integration tests."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import (  # noqa: F401
    AuctionImage,
    AuctionLot,
    CrawlState,
    CrawlTarget,
    RawPage,
    RawPageLot,
    RawParseRun,
    ScrapeAnomaly,
    ScrapeRequestLog,
    ScrapeRun,
)

TEST_DATABASE_URL: str = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://autodepth:autodepth@localhost:5432/autodepth_test",
)


@pytest.fixture
async def integration_session() -> AsyncSession:  # type: ignore[misc]
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    except (OperationalError, Exception) as exc:
        await engine.dispose()
        pytest.skip(f"Integration test DB unavailable — start docker-compose: {exc}")

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        yield session
        await session.execute(
            text(
                "TRUNCATE TABLE scrape_request_logs, scrape_anomalies, auction_images, "
                "raw_page_lots, raw_parse_runs, raw_pages, crawl_targets, "
                "auction_lots, scrape_runs, crawl_state RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()

    await engine.dispose()
