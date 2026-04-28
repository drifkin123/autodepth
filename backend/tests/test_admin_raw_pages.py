"""Tests for raw-page admin review endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_raw_pages import (
    admin_raw_pages_dashboard,
    enqueue_missing_detail_targets,
    get_raw_page,
    get_raw_page_content,
    get_raw_pages,
    reparse_raw_page,
)
from app.models.auction_lot import AuctionLot
from app.models.crawl_target import CrawlTarget
from app.models.raw_parse_run import RawParseRun
from app.services.artifacts import LocalArtifactStore
from app.services.raw_pages import create_raw_page_from_content


@pytest.mark.asyncio
async def test_admin_lists_raw_pages_and_loads_raw_content(
    integration_session: AsyncSession,
    tmp_path,
) -> None:
    store = LocalArtifactStore(tmp_path)
    raw_page = await create_raw_page_from_content(
        integration_session,
        artifact_store=store,
        source="bring_a_trailer",
        target_type="bat_model_page",
        url="https://bringatrailer.com/porsche/911/",
        content=b"<html>raw review</html>",
        status_code=200,
        response_headers={"content-type": "text/html"},
        content_type="text/html",
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )

    listing = await get_raw_pages(
        source="bring_a_trailer",
        target_type=None,
        status_code=None,
        url=None,
        page=1,
        page_size=50,
        db=integration_session,
    )
    detail = await get_raw_page(raw_page.id, db=integration_session)
    content = await get_raw_page_content(raw_page.id, db=integration_session, artifact_store=store)

    assert listing.total == 1
    assert listing.items[0].id == raw_page.id
    assert detail.artifact_uri == raw_page.artifact_uri
    assert content.media_type == "text/html"
    assert content.body == b"<html>raw review</html>"


@pytest.mark.asyncio
async def test_admin_reparse_raw_page_runs_parser_from_stored_content(
    integration_session: AsyncSession,
    tmp_path,
) -> None:
    store = LocalArtifactStore(tmp_path)
    raw_page = await create_raw_page_from_content(
        integration_session,
        artifact_store=store,
        source="bring_a_trailer",
        target_type="bat_api_completed_results",
        url="https://bringatrailer.com/wp-json/bringatrailer/1.0/data/listings-filter",
        content=b'{"items":[],"pages_total":1}',
        status_code=200,
        response_headers={"content-type": "application/json"},
        content_type="application/json",
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )

    result = await reparse_raw_page(
        raw_page.id,
        db=integration_session,
        artifact_store=store,
    )

    assert result["status"] == "success"
    assert result["rawPageId"] == str(raw_page.id)
    parse_run = (await integration_session.execute(RawParseRun.__table__.select())).first()
    assert parse_run is not None


@pytest.mark.asyncio
async def test_admin_raw_pages_dashboard_is_dedicated_review_surface() -> None:
    response = await admin_raw_pages_dashboard()
    html = response.body.decode()

    assert "Raw Page Review" in html
    assert "/api/admin/raw-pages" in html
    assert "loadRawPages" in html


@pytest.mark.asyncio
async def test_admin_enqueue_missing_detail_targets_creates_low_priority_targets(
    integration_session: AsyncSession,
) -> None:
    integration_session.add(
        AuctionLot(
            source="bring_a_trailer",
            source_auction_id="missing-detail-1",
            canonical_url="https://bringatrailer.com/listing/missing-detail-1/",
            auction_status="sold",
            sold_price=100_000,
            high_bid=100_000,
            bid_count=10,
        )
    )
    await integration_session.commit()

    result = await enqueue_missing_detail_targets(db=integration_session)

    targets = (await integration_session.execute(CrawlTarget.__table__.select())).all()
    assert result == {"enqueued": 1}
    assert len(targets) == 1
