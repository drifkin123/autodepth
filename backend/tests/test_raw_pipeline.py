"""Tests for durable raw-page crawl and replay pipeline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction_lot import AuctionLot
from app.models.crawl_state import CrawlState
from app.models.crawl_target import CrawlTarget
from app.models.raw_page import RawPage
from app.models.raw_page_lot import RawPageLot
from app.models.raw_parse_run import RawParseRun
from app.models.scrape_anomaly import ScrapeAnomaly
from app.scrapers.runtime import BlockedScrapeError
from app.services.artifacts import LocalArtifactStore
from app.services.bat_raw_pipeline import (
    BAT_DETAIL_PARSER_NAME,
    BAT_LIST_PARSER_NAME,
    fetch_bat_target_to_raw_page,
    parse_bat_raw_page,
)
from app.services.crawl_targets import claim_next_crawl_target, enqueue_crawl_target
from app.services.raw_pages import create_raw_page_from_content

FIXTURES_DIR = Path(__file__).parent / "fixtures"


async def _count(session: AsyncSession, model: type) -> int:
    return (
        await session.execute(select(func.count()).select_from(model))
    ).scalar_one()


@pytest.mark.asyncio
async def test_crawl_target_enqueue_deduplicates_by_request_fingerprint(
    integration_session: AsyncSession,
) -> None:
    first = await enqueue_crawl_target(
        integration_session,
        source="bring_a_trailer",
        target_type="bat_model_page",
        url="https://bringatrailer.com/porsche/911/",
        priority=20,
    )
    second = await enqueue_crawl_target(
        integration_session,
        source="bring_a_trailer",
        target_type="bat_model_page",
        url="https://bringatrailer.com/porsche/911",
        priority=10,
    )

    assert first.id == second.id
    assert first.priority == 10
    assert await _count(integration_session, CrawlTarget) == 1


@pytest.mark.asyncio
async def test_claim_next_crawl_target_claims_each_target_once(
    integration_session: AsyncSession,
) -> None:
    await enqueue_crawl_target(
        integration_session,
        source="bring_a_trailer",
        target_type="bat_model_page",
        url="https://bringatrailer.com/porsche/911/",
    )

    claimed = await claim_next_crawl_target(
        integration_session,
        source="bring_a_trailer",
        worker_id="worker-1",
    )
    second_claim = await claim_next_crawl_target(
        integration_session,
        source="bring_a_trailer",
        worker_id="worker-2",
    )

    assert claimed is not None
    assert claimed.state == "claimed"
    assert claimed.locked_by == "worker-1"
    assert second_claim is None


@pytest.mark.asyncio
async def test_bat_list_raw_page_parse_persists_lots_and_discovers_detail_targets(
    integration_session: AsyncSession,
    tmp_path,
) -> None:
    store = LocalArtifactStore(tmp_path)
    raw_page = await create_raw_page_from_content(
        integration_session,
        artifact_store=store,
        source="bring_a_trailer",
        target_type="bat_model_page",
        url="https://bringatrailer.com/porsche/911-gt3/",
        content=(FIXTURES_DIR / "bat_porsche_911_gt3.html").read_bytes(),
        status_code=200,
        response_headers={"content-type": "text/html"},
        content_type="text/html",
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )

    outcome = await parse_bat_raw_page(
        integration_session,
        artifact_store=store,
        raw_page_id=raw_page.id,
    )

    assert outcome.lots_found > 0
    assert outcome.lots_inserted > 0
    assert outcome.targets_discovered > 0
    assert await _count(integration_session, AuctionLot) == outcome.lots_inserted
    assert await _count(integration_session, RawPageLot) == outcome.lots_found

    parse_run = (
        await integration_session.execute(select(RawParseRun))
    ).scalar_one()
    assert parse_run.parser_name == BAT_LIST_PARSER_NAME
    assert parse_run.status == "success"
    assert parse_run.records_found == outcome.lots_found

    detail_targets = (
        await integration_session.execute(
            select(CrawlTarget).where(CrawlTarget.target_type == "bat_detail_page")
        )
    ).scalars().all()
    assert detail_targets
    assert all(
        target.priority > raw_page.metadata_json["target_priority"]
        for target in detail_targets
    )


@pytest.mark.asyncio
async def test_bat_detail_replay_enriches_existing_lot_without_network(
    integration_session: AsyncSession,
    tmp_path,
) -> None:
    store = LocalArtifactStore(tmp_path)
    list_page = await create_raw_page_from_content(
        integration_session,
        artifact_store=store,
        source="bring_a_trailer",
        target_type="bat_api_completed_results",
        url="https://bringatrailer.com/wp-json/bringatrailer/1.0/data/listings-filter",
        content=(
            b'{"items":[{"active":false,"current_bid":229000,'
            b'"sold_text":"Sold for USD $229,000 <span> on 3/29/26 </span>",'
            b'"title":"2019 Porsche 911 GT3 RS Weissach",'
            b'"url":"https://bringatrailer.com/listing/'
            b'2019-porsche-911-gt3-rs-weissach-97/",'
            b'"id":108526570,"bids":42,"country":"United States",'
            b'"image":"https://bringatrailer.com/wp-content/uploads/example.jpg"}],'
            b'"pages_total":1,"items_per_page":1,"page_current":1,"items_total":1}'
        ),
        status_code=200,
        response_headers={"content-type": "application/json"},
        content_type="application/json",
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    await parse_bat_raw_page(integration_session, artifact_store=store, raw_page_id=list_page.id)
    lot = (await integration_session.execute(select(AuctionLot))).scalar_one()
    lot.mileage = None
    await integration_session.commit()

    detail_html = b"""
    <html>
      <body>
        <div class="essentials">
          <strong>Location</strong>: <a>Estero, Florida 33928</a>
          <div class="item"><strong>Listing Details</strong>
            <ul>
              <li>Chassis: WP0AF2A9XKS164665</li>
              <li>29k Miles</li>
              <li>4.0-Liter Flat-Six</li>
            </ul>
          </div>
          <div class="item"><strong>Lot</strong> #235490</div>
        </div>
      </body>
    </html>
    """
    detail_page = await create_raw_page_from_content(
        integration_session,
        artifact_store=store,
        source="bring_a_trailer",
        target_type="bat_detail_page",
        url=lot.canonical_url,
        content=detail_html,
        status_code=200,
        response_headers={"content-type": "text/html"},
        content_type="text/html",
        fetched_at=datetime(2026, 4, 28, tzinfo=UTC),
    )

    outcome = await parse_bat_raw_page(
        integration_session,
        artifact_store=store,
        raw_page_id=detail_page.id,
        parser_version="bat-detail-test-v2",
    )

    refreshed_lot = await integration_session.get(AuctionLot, lot.id)
    assert outcome.lots_updated == 1
    assert refreshed_lot is not None
    assert refreshed_lot.mileage == 29_000
    assert refreshed_lot.vin == "WP0AF2A9XKS164665"
    parse_runs = (
        await integration_session.execute(
            select(RawParseRun).order_by(RawParseRun.created_at)
        )
    ).scalars().all()
    assert parse_runs[-1].parser_name == BAT_DETAIL_PARSER_NAME
    assert parse_runs[-1].parser_version == "bat-detail-test-v2"


@pytest.mark.asyncio
async def test_bat_fetch_job_stores_raw_page_and_enqueues_parse(
    integration_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalArtifactStore(tmp_path)
    target = await enqueue_crawl_target(
        integration_session,
        source="bring_a_trailer",
        target_type="bat_detail_page",
        url="https://bringatrailer.com/listing/example/",
    )
    enqueued_parse_ids: list[uuid.UUID] = []

    async def fake_get(self, url: str, **kwargs) -> httpx.Response:  # noqa: ANN001
        return httpx.Response(
            200,
            text="<html>detail</html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    async def fake_enqueue_parse(raw_page_id: uuid.UUID) -> None:
        enqueued_parse_ids.append(raw_page_id)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    raw_page = await fetch_bat_target_to_raw_page(
        integration_session,
        artifact_store=store,
        target_id=target.id,
        enqueue_parse=fake_enqueue_parse,
    )

    assert raw_page is not None
    assert raw_page.status_code == 200
    assert raw_page.artifact_uri.startswith("local://")
    assert enqueued_parse_ids == [raw_page.id]
    refreshed_target = await integration_session.get(CrawlTarget, target.id)
    assert refreshed_target is not None
    assert refreshed_target.state == "fetched"


@pytest.mark.asyncio
async def test_bat_fetch_job_marks_target_blocked_on_rate_limit(
    integration_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalArtifactStore(tmp_path)
    target = await enqueue_crawl_target(
        integration_session,
        source="bring_a_trailer",
        target_type="bat_detail_page",
        url="https://bringatrailer.com/listing/rate-limited/",
    )

    async def fake_get(self, url: str, **kwargs) -> httpx.Response:  # noqa: ANN001
        return httpx.Response(
            429,
            text="slow down",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(BlockedScrapeError):
        await fetch_bat_target_to_raw_page(
            integration_session,
            artifact_store=store,
            target_id=target.id,
            enqueue_parse=lambda raw_page_id: None,
        )

    refreshed_target = await integration_session.get(CrawlTarget, target.id)
    assert refreshed_target is not None
    assert refreshed_target.state == "blocked"
    assert refreshed_target.last_error == "BaT returned 429"
    assert await _count(integration_session, RawPage) == 1
    assert await _count(integration_session, ScrapeAnomaly) == 1
    crawl_state = (await integration_session.execute(select(CrawlState))).scalar_one()
    assert crawl_state.state["last_status"] == "blocked"
