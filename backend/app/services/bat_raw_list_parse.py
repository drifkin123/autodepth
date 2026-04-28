"""Parse stored BaT list/API raw pages."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_page import RawPage
from app.scrapers.bat_config import LISTINGS_FILTER_URL
from app.scrapers.bat_list_parser import (
    extract_completed_metadata_from_html,
    extract_items_from_html,
    parse_item,
)
from app.services.bat_raw_lots import RawLotPersistence, link_raw_page_to_lot
from app.services.bat_raw_types import SOURCE, RawParseOutcome
from app.services.crawl_targets import enqueue_crawl_target


async def parse_list_page(
    session: AsyncSession,
    raw_page: RawPage,
    content: bytes,
) -> RawParseOutcome:
    items, metadata = _extract_list_items(raw_page, content)
    persistence = RawLotPersistence(session)
    lots_found = lots_inserted = targets_discovered = 0
    for item in items:
        lot, _reason = parse_item(item)
        if lot is None:
            continue
        lots_found += 1
        inserted = await persistence.save_lot(lot)
        lots_inserted += 1 if inserted else 0
        persisted_lot = await persistence._existing_lot(lot)
        if persisted_lot is not None:
            await link_raw_page_to_lot(
                session,
                raw_page_id=raw_page.id,
                lot_id=persisted_lot.id,
                relationship_type="list",
            )
        targets_discovered += await _enqueue_detail_target(session, raw_page, lot)
    targets_discovered += await _enqueue_completed_result_pages(session, raw_page, metadata)
    await session.commit()
    return RawParseOutcome(
        lots_found=lots_found,
        lots_inserted=lots_inserted,
        lots_updated=persistence.records_updated,
        targets_discovered=targets_discovered,
    )


def _extract_list_items(raw_page: RawPage, content: bytes) -> tuple[list[dict], dict]:
    if "json" in raw_page.content_type or raw_page.target_type == "bat_api_completed_results":
        data = json.loads(content.decode())
        return data.get("items", []), {
            "items_total": data.get("items_total"),
            "items_per_page": data.get("items_per_page"),
            "page_current": data.get("page_current"),
            "pages_total": data.get("pages_total"),
        }
    html = content.decode(errors="replace")
    return extract_items_from_html(html), extract_completed_metadata_from_html(html)


async def _enqueue_detail_target(session: AsyncSession, raw_page: RawPage, lot) -> int:
    target = await enqueue_crawl_target(
        session,
        source=SOURCE,
        target_type="bat_detail_page",
        url=lot.canonical_url,
        priority=80,
        discovered_from_raw_page_id=raw_page.id,
        metadata_json={"source_auction_id": lot.source_auction_id, "title": lot.title},
    )
    return 1 if target.created_at == target.updated_at else 0


async def _enqueue_completed_result_pages(
    session: AsyncSession,
    raw_page: RawPage,
    metadata: dict,
) -> int:
    base_filter = metadata.get("base_filter") or {}
    pages_total = _as_int(metadata.get("pages_total")) or 1
    items_per_page = _as_int(metadata.get("items_per_page")) or 24
    if not base_filter or pages_total <= 1:
        return 0
    discovered = 0
    for page in range(2, pages_total + 1):
        target = await enqueue_crawl_target(
            session,
            source=SOURCE,
            target_type="bat_api_completed_results",
            url=LISTINGS_FILTER_URL,
            priority=30,
            discovered_from_raw_page_id=raw_page.id,
            metadata_json={
                "request_payload": {
                    "base_filter": base_filter,
                    "page": page,
                    "per_page": items_per_page,
                    "referer_url": raw_page.url,
                }
            },
        )
        if target.created_at == target.updated_at:
            discovered += 1
    return discovered


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
