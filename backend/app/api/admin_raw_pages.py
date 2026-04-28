"""Admin routes for raw page review and replay."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    CrawlTargetOut,
    PaginatedRawPages,
    RawPageListItem,
    RawPageOut,
)
from app.db import get_db
from app.models.auction_lot import AuctionLot
from app.models.raw_page import RawPage
from app.services.admin_raw_queries import query_crawl_targets, query_paginated_raw_pages
from app.services.artifacts import ArtifactStore, get_artifact_store
from app.services.bat_raw_pipeline import parse_bat_raw_page
from app.services.crawl_targets import enqueue_crawl_target

router = APIRouter(prefix="/admin", tags=["admin"])

_RAW_PAGES_HTML = (
    Path(__file__).parent / "templates" / "admin_raw_pages.html"
).read_text()


@router.get("/raw-pages", response_model=PaginatedRawPages)
async def get_raw_pages(
    source: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    status_code: int | None = Query(default=None),
    url: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> PaginatedRawPages:
    rows, total = await query_paginated_raw_pages(
        db,
        source=source,
        target_type=target_type,
        status_code=status_code,
        url=url,
        page=page,
        page_size=page_size,
    )
    return PaginatedRawPages(
        items=[RawPageListItem.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/raw-pages/enqueue-missing-details")
async def enqueue_missing_detail_targets(
    source: str = "bring_a_trailer",
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
) -> dict:
    lots = (
        await db.execute(
            select(AuctionLot)
            .where(AuctionLot.source == source, AuctionLot.detail_scraped_at.is_(None))
            .order_by(AuctionLot.ended_at.desc().nullslast(), AuctionLot.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    enqueued = 0
    for lot in lots:
        await enqueue_crawl_target(
            db,
            source=source,
            target_type="bat_detail_page",
            url=lot.canonical_url,
            priority=80,
            metadata_json={"source_auction_id": lot.source_auction_id, "title": lot.title},
        )
        enqueued += 1
    return {"enqueued": enqueued}


@router.get("/raw-pages/{raw_page_id}", response_model=RawPageOut)
async def get_raw_page(
    raw_page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> RawPageOut:
    raw_page = await db.get(RawPage, raw_page_id)
    if raw_page is None:
        raise HTTPException(status_code=404, detail="Raw page not found")
    return RawPageOut.model_validate(raw_page)


@router.get("/raw-pages/{raw_page_id}/content")
async def get_raw_page_content(
    raw_page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    raw_page = await db.get(RawPage, raw_page_id)
    if raw_page is None:
        raise HTTPException(status_code=404, detail="Raw page not found")
    content = await artifact_store.load(raw_page.artifact_uri)
    return Response(content=content, media_type=raw_page.content_type)


@router.post("/raw-pages/{raw_page_id}/reparse")
async def reparse_raw_page(
    raw_page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
) -> dict:
    outcome = await parse_bat_raw_page(db, artifact_store=artifact_store, raw_page_id=raw_page_id)
    return {
        "status": "success",
        "rawPageId": str(raw_page_id),
        "lotsFound": outcome.lots_found,
        "lotsInserted": outcome.lots_inserted,
        "lotsUpdated": outcome.lots_updated,
        "targetsDiscovered": outcome.targets_discovered,
    }


@router.get("/crawl-targets", response_model=list[CrawlTargetOut])
async def get_crawl_targets(
    limit: int = Query(default=100, ge=1, le=500),
    source: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[CrawlTargetOut]:
    rows = await query_crawl_targets(
        db,
        limit=limit,
        source=source,
        target_type=target_type,
        state=state,
    )
    return [CrawlTargetOut.model_validate(row) for row in rows]


@router.get("/raw-review", response_class=HTMLResponse, include_in_schema=False)
async def admin_raw_pages_dashboard() -> HTMLResponse:
    return HTMLResponse(content=_RAW_PAGES_HTML)
