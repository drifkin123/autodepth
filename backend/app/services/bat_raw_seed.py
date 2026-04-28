"""Seed BaT raw crawl targets."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.scrapers.bat_config import BASE_URL
from app.scrapers.bat_targets import fetch_model_entries
from app.scrapers.makes import BAT_MAKES
from app.services.crawl_targets import enqueue_crawl_target

BatTargetEntry = tuple[str, str, str]


async def seed_bat_raw_targets(
    session: AsyncSession,
    *,
    target_source: str = "models",
    selected_keys: set[str] | None = None,
    target_entries: list[BatTargetEntry] | None = None,
) -> dict[str, int]:
    entries = target_entries if target_entries is not None else await _load_entries(target_source)
    enqueued = 0
    for key, label, path in entries:
        if selected_keys is not None and key not in selected_keys:
            continue
        await enqueue_crawl_target(
            session,
            source="bring_a_trailer",
            target_type="bat_model_page",
            url=f"{BASE_URL}/{path.strip('/')}/",
            priority=20,
            metadata_json={"key": key, "label": label, "path": path},
        )
        enqueued += 1
    return {"enqueued": enqueued}


async def _load_entries(target_source: str) -> list[BatTargetEntry]:
    if target_source == "makes":
        return list(BAT_MAKES)
    if target_source != "models":
        raise ValueError("target_source must be 'models' or 'makes'")
    async with httpx.AsyncClient() as client:
        return await fetch_model_entries(client)
