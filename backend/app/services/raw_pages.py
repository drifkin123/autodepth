"""Raw page persistence helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_page import RawPage
from app.services.artifacts import ArtifactStore
from app.services.url_utils import canonicalize_url

_TARGET_PRIORITIES = {
    "bat_models_directory": 10,
    "bat_model_page": 20,
    "bat_api_completed_results": 30,
    "bat_detail_page": 80,
}


async def create_raw_page_from_content(
    session: AsyncSession,
    *,
    artifact_store: ArtifactStore,
    source: str,
    target_type: str,
    url: str,
    content: bytes,
    status_code: int | None,
    response_headers: dict,
    content_type: str,
    fetched_at: datetime | None = None,
    crawl_target_id: uuid.UUID | None = None,
    fetch_error: str | None = None,
    metadata_json: dict | None = None,
) -> RawPage:
    fetched_at = fetched_at or datetime.now(UTC)
    stored = await artifact_store.save(
        source=source,
        content=content,
        content_type=content_type,
        fetched_at=fetched_at,
    )
    metadata = {
        "target_priority": _TARGET_PRIORITIES.get(target_type, 100),
        **(metadata_json or {}),
    }
    raw_page = RawPage(
        source=source,
        target_type=target_type,
        crawl_target_id=crawl_target_id,
        url=url,
        canonical_url=canonicalize_url(url),
        status_code=status_code,
        response_headers=dict(response_headers),
        content_sha256=stored.content_sha256,
        artifact_uri=stored.artifact_uri,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        fetched_at=fetched_at,
        fetch_error=fetch_error,
        metadata_json=metadata,
    )
    session.add(raw_page)
    await session.commit()
    await session.refresh(raw_page)
    return raw_page
