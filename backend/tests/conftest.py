"""Shared pytest fixtures for integration tests.

The ``integration_session`` fixture connects to a real PostgreSQL test database,
creates the schema on first use, seeds the car catalog, and truncates all data
after each test. Tests that use it are automatically skipped if the test database
is unreachable.

Set TEST_DATABASE_URL to override the default:
    export TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models.car import Car  # noqa: F401 — registers with Base.metadata
from app.models.price_prediction import PricePrediction  # noqa: F401
from app.models.scrape_log import ScrapeLog  # noqa: F401
from app.models.vehicle_sale import VehicleSale  # noqa: F401
from app.models.watchlist import WatchlistItem  # noqa: F401

TEST_DATABASE_URL: str = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://autodepth:autodepth@localhost:5432/autodepth_test",
)

# Cars that match the fixture files — fuzzy-matched by title during scraping.
_SEED_CARS: list[dict] = [
    {
        "id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "make": "Porsche",
        "model": "911",
        "trim": "GT3 RS",
        "year_start": 2016,
        "year_end": None,
        "production_count": None,
        "engine": "4.0L NA Flat-6",
        "is_naturally_aspirated": True,
        "msrp_original": 187500,
        "notes": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
        "make": "Porsche",
        "model": "911",
        "trim": "GT3",
        "year_start": 2018,
        "year_end": None,
        "production_count": None,
        "engine": "4.0L NA Flat-6",
        "is_naturally_aspirated": True,
        "msrp_original": 143600,
        "notes": None,
    },
]


@pytest.fixture
async def integration_session() -> AsyncSession:  # type: ignore[misc]
    """
    Async DB session against the test database.

    - Creates all tables (idempotent — uses checkfirst=True).
    - Seeds a minimal car catalog matching the fixture files.
    - Yields the session for use in the test.
    - Truncates all data tables after the test completes.
    - Automatically skips if the test database is unreachable.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    except (OperationalError, Exception) as exc:
        await engine.dispose()
        pytest.skip(f"Integration test DB unavailable — start docker-compose: {exc}")

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        # Seed catalog
        for car_data in _SEED_CARS:
            session.add(Car(**car_data))
        await session.commit()

        yield session

        # Teardown: wipe all data (not schema)
        await session.execute(
            text("TRUNCATE TABLE vehicle_sales, cars, scrape_logs RESTART IDENTITY CASCADE")
        )
        await session.commit()

    await engine.dispose()
