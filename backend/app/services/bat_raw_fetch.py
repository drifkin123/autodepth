"""Fetch BaT crawl targets into immutable raw pages."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_state import CrawlState
from app.models.crawl_target import CrawlTarget
from app.models.raw_page import RawPage
from app.models.scrape_anomaly import ScrapeAnomaly
from app.scrapers.bat_config import _HEADERS, BASE_URL, LISTINGS_FILTER_URL
from app.scrapers.bat_http import build_completed_results_params
from app.scrapers.runtime import BlockedScrapeError, is_block_status
from app.services.artifacts import ArtifactStore
from app.services.bat_raw_types import SOURCE
from app.services.crawl_targets import mark_target_fetched
from app.services.raw_pages import create_raw_page_from_content


async def fetch_bat_target_to_raw_page(
    session: AsyncSession,
    *,
    artifact_store: ArtifactStore,
    target_id: uuid.UUID,
    enqueue_parse,
    rate_limiter=None,
) -> RawPage | None:
    target = await session.get(CrawlTarget, target_id)
    if target is None:
        return None
    if rate_limiter is not None:
        await rate_limiter.wait()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            _target_request_url(target),
            params=_target_request_params(target),
            headers=_HEADERS,
            follow_redirects=True,
            timeout=30.0,
        )
    content_type = response.headers.get("content-type", "application/octet-stream").split(";")[0]
    raw_page = await create_raw_page_from_content(
        session,
        artifact_store=artifact_store,
        source=SOURCE,
        target_type=target.target_type,
        url=str(response.url),
        content=response.content,
        status_code=response.status_code,
        response_headers=dict(response.headers),
        content_type=content_type,
        fetched_at=datetime.now(UTC),
        crawl_target_id=target.id,
        metadata_json={"target_priority": target.priority},
    )
    if is_block_status(response.status_code):
        target.state = "blocked"
        target.last_error = f"BaT returned {response.status_code}"
        await _record_blocked_source(
            session,
            status_code=response.status_code,
            url=str(response.url),
        )
        await session.commit()
        raise BlockedScrapeError(target.last_error, status_code=response.status_code)
    response.raise_for_status()
    await mark_target_fetched(session, target, raw_page_id=raw_page.id)
    await enqueue_parse(raw_page.id)
    return raw_page


async def _record_blocked_source(
    session: AsyncSession,
    *,
    status_code: int,
    url: str,
) -> None:
    now = datetime.now(UTC)
    session.add(
        ScrapeAnomaly(
            source=SOURCE,
            severity="critical",
            code="blocked_response",
            message="BaT raw fetch stopped after a blocked or rate-limited response.",
            url=url,
            metadata_json={"status_code": status_code},
        )
    )
    state = (
        await session.execute(
            select(CrawlState).where(
                CrawlState.source == SOURCE,
                CrawlState.mode == "raw_pipeline",
            )
        )
    ).scalar_one_or_none()
    state_update = {
        "last_status": "blocked",
        "last_blocked_at": now.isoformat(),
        "status_code": status_code,
        "url": url,
    }
    if state is None:
        session.add(
            CrawlState(
                source=SOURCE,
                mode="raw_pipeline",
                state=state_update,
                last_run_at=now,
            )
        )
        return
    state.state = {**(state.state or {}), **state_update}
    state.last_run_at = now


def _target_request_url(target: CrawlTarget) -> str:
    if target.target_type == "bat_api_completed_results":
        return LISTINGS_FILTER_URL
    if target.canonical_url.startswith("http"):
        return target.canonical_url
    return f"{BASE_URL}/{target.canonical_url.strip('/')}/"


def _target_request_params(target: CrawlTarget) -> list[tuple[str, object]] | None:
    payload = (target.metadata_json or {}).get("request_payload") or {}
    if target.target_type != "bat_api_completed_results":
        return None
    return build_completed_results_params(
        payload.get("base_filter") or {},
        page=int(payload.get("page") or 1),
        per_page=int(payload.get("per_page") or 24),
    )
