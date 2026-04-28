"""Durable crawl target queue helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_target import CrawlTarget
from app.services.url_utils import canonicalize_url


def build_request_fingerprint(
    *,
    source: str,
    target_type: str,
    url: str,
    method: str = "GET",
    payload: dict | None = None,
) -> str:
    parts = {
        "source": source,
        "target_type": target_type,
        "method": method.upper(),
        "url": canonicalize_url(url),
        "payload": payload or {},
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


async def enqueue_crawl_target(
    session: AsyncSession,
    *,
    source: str,
    target_type: str,
    url: str,
    priority: int = 100,
    discovered_from_raw_page_id: uuid.UUID | None = None,
    metadata_json: dict | None = None,
    request_method: str = "GET",
) -> CrawlTarget:
    canonical_url = canonicalize_url(url)
    fingerprint = build_request_fingerprint(
        source=source,
        target_type=target_type,
        url=canonical_url,
        method=request_method,
        payload=(metadata_json or {}).get("request_payload"),
    )
    existing = (
        await session.execute(
            select(CrawlTarget).where(CrawlTarget.request_fingerprint == fingerprint)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.priority = min(existing.priority, priority)
        existing.metadata_json = {**(existing.metadata_json or {}), **(metadata_json or {})}
        await session.commit()
        await session.refresh(existing)
        return existing
    target = CrawlTarget(
        source=source,
        target_type=target_type,
        url=url,
        canonical_url=canonical_url,
        request_method=request_method.upper(),
        request_fingerprint=fingerprint,
        priority=priority,
        discovered_from_raw_page_id=discovered_from_raw_page_id,
        metadata_json=metadata_json or {},
    )
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return target


async def claim_next_crawl_target(
    session: AsyncSession,
    *,
    source: str,
    worker_id: str,
) -> CrawlTarget | None:
    now = datetime.now(UTC)
    query: Select[tuple[CrawlTarget]] = (
        select(CrawlTarget)
        .where(
            CrawlTarget.source == source,
            CrawlTarget.state == "pending",
            (CrawlTarget.next_fetch_at.is_(None) | (CrawlTarget.next_fetch_at <= now)),
        )
        .order_by(CrawlTarget.priority.asc(), CrawlTarget.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    target = (await session.execute(query)).scalar_one_or_none()
    if target is None:
        return None
    target.state = "claimed"
    target.locked_by = worker_id
    target.locked_at = now
    target.attempts += 1
    await session.commit()
    await session.refresh(target)
    return target


async def mark_target_fetched(
    session: AsyncSession,
    target: CrawlTarget,
    *,
    raw_page_id: uuid.UUID,
) -> None:
    target.state = "fetched"
    target.locked_by = None
    target.locked_at = None
    target.metadata_json = {**(target.metadata_json or {}), "raw_page_id": str(raw_page_id)}
    await session.commit()


async def mark_target_failed(
    session: AsyncSession,
    target: CrawlTarget,
    *,
    error: str,
    retryable: bool = True,
) -> None:
    target.state = "pending" if retryable else "error"
    target.last_error = error
    target.locked_by = None
    target.locked_at = None
    await session.commit()
