"""Admin query helpers for raw page review."""

from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_target import CrawlTarget
from app.models.raw_page import RawPage


async def query_paginated_raw_pages(
    db: AsyncSession,
    *,
    source: str | None = None,
    target_type: str | None = None,
    status_code: int | None = None,
    url: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[RawPage], int]:
    filters = []
    if source:
        filters.append(RawPage.source == source)
    if target_type:
        filters.append(RawPage.target_type == target_type)
    if status_code is not None:
        filters.append(RawPage.status_code == status_code)
    if url:
        filters.append(RawPage.url.ilike(f"%{url}%"))

    count_query = select(func.count()).select_from(RawPage)
    if filters:
        count_query = count_query.where(*filters)
    total = (await db.execute(count_query)).scalar_one()

    query = (
        select(RawPage)
        .order_by(desc(RawPage.fetched_at), desc(RawPage.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        query = query.where(*filters)
    rows = (await db.execute(query)).scalars().all()
    return list(rows), total


async def query_crawl_targets(
    db: AsyncSession,
    *,
    limit: int = 100,
    source: str | None = None,
    target_type: str | None = None,
    state: str | None = None,
) -> list[CrawlTarget]:
    query = (
        select(CrawlTarget)
        .order_by(CrawlTarget.priority.asc(), desc(CrawlTarget.created_at))
        .limit(limit)
    )
    if source:
        query = query.where(CrawlTarget.source == source)
    if target_type:
        query = query.where(CrawlTarget.target_type == target_type)
    if state:
        query = query.where(CrawlTarget.state == state)
    return list((await db.execute(query)).scalars().all())
