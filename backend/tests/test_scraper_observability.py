"""Tests for durable scraper observability data and admin APIs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base
from app.models.scrape_run import ScrapeRun


def test_metadata_contains_request_logs_and_anomalies() -> None:
    table_names = set(Base.metadata.tables)

    assert "scrape_request_logs" in table_names
    assert "scrape_anomalies" in table_names


@pytest.mark.asyncio
async def test_request_log_and_anomaly_persist_with_run(
    integration_session: AsyncSession,
) -> None:
    from app.models.scrape_anomaly import ScrapeAnomaly
    from app.models.scrape_request_log import ScrapeRequestLog

    run = ScrapeRun(
        id=uuid.uuid4(),
        source="bring_a_trailer",
        mode="incremental",
        status="running",
        started_at=datetime.now(UTC),
    )
    integration_session.add(run)
    await integration_session.flush()

    request_log = ScrapeRequestLog(
        scrape_run_id=run.id,
        source="bring_a_trailer",
        url="https://bringatrailer.com/porsche/911/",
        action="http_get",
        attempt=1,
        status_code=500,
        duration_ms=125,
        outcome="retry",
        error_type="HTTPStatusError",
        error_message="500 Server Error",
        retry_delay_seconds=1.5,
        raw_item_count=0,
        parsed_lot_count=0,
        skip_counts={"no_price": 3},
        metadata_json={"target": "Porsche 911"},
    )
    anomaly = ScrapeAnomaly(
        scrape_run_id=run.id,
        source="bring_a_trailer",
        severity="warning",
        code="zero_lots",
        message="No auction lots were parsed",
        url="https://bringatrailer.com/porsche/911/",
        metadata_json={"raw_item_count": 12},
    )
    integration_session.add(request_log)
    integration_session.add(anomaly)
    await integration_session.commit()

    logs = (await integration_session.execute(select(ScrapeRequestLog))).scalars().all()
    anomalies = (await integration_session.execute(select(ScrapeAnomaly))).scalars().all()
    assert logs[0].scrape_run_id == run.id
    assert logs[0].outcome == "retry"
    assert logs[0].skip_counts == {"no_price": 3}
    assert anomalies[0].severity == "warning"
    assert anomalies[0].code == "zero_lots"


@pytest.mark.asyncio
async def test_admin_request_logs_and_anomaly_queries(integration_session: AsyncSession) -> None:
    from app.api.admin import get_anomalies, get_request_logs
    from app.models.scrape_anomaly import ScrapeAnomaly
    from app.models.scrape_request_log import ScrapeRequestLog

    run = ScrapeRun(source="cars_and_bids", mode="incremental", status="error")
    integration_session.add(run)
    await integration_session.flush()
    integration_session.add(
        ScrapeRequestLog(
            scrape_run_id=run.id,
            source="cars_and_bids",
            url="https://carsandbids.com/past-auctions/",
            action="playwright_goto",
            attempt=1,
            status_code=429,
            duration_ms=600,
            outcome="blocked",
            error_type="BlockedScrapeError",
            error_message="blocked",
        )
    )
    integration_session.add(
        ScrapeAnomaly(
            scrape_run_id=run.id,
            source="cars_and_bids",
            severity="critical",
            code="blocked_response",
            message="Blocked response from source",
        )
    )
    await integration_session.commit()

    logs = await get_request_logs(
        limit=20,
        source="cars_and_bids",
        run_id=None,
        outcome="blocked",
        status_code=None,
        errors_only=True,
        db=integration_session,
    )
    anomalies = await get_anomalies(
        limit=20,
        source="cars_and_bids",
        severity="critical",
        run_id=None,
        db=integration_session,
    )

    assert logs[0].outcome == "blocked"
    assert logs[0].status_code == 429
    assert anomalies[0].code == "blocked_response"
    assert anomalies[0].severity == "critical"


@pytest.mark.asyncio
async def test_admin_status_includes_per_source_health(integration_session: AsyncSession) -> None:
    from app.api.admin import get_status
    from app.models.scrape_anomaly import ScrapeAnomaly

    run = ScrapeRun(
        source="bring_a_trailer",
        mode="incremental",
        status="success",
        records_found=12,
        records_inserted=4,
        records_updated=8,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    integration_session.add(run)
    await integration_session.flush()
    integration_session.add(
        ScrapeAnomaly(
            scrape_run_id=run.id,
            source="bring_a_trailer",
            severity="warning",
            code="high_skip_rate",
            message="High parser skip rate",
        )
    )
    await integration_session.commit()

    status = await get_status(db=integration_session)

    bat_status = next(source for source in status.sources if source.source == "bring_a_trailer")
    assert bat_status.state == "idle"
    assert bat_status.records_found == 12
    assert bat_status.latest_anomaly_severity == "warning"
