"""Tests for seeding BaT raw crawl targets."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_target import CrawlTarget
from app.services.bat_raw_seed import seed_bat_raw_targets


@pytest.mark.asyncio
async def test_seed_bat_raw_targets_enqueues_static_make_targets(
    integration_session: AsyncSession,
) -> None:
    result = await seed_bat_raw_targets(
        integration_session,
        target_source="makes",
        target_entries=[("porsche", "Porsche", "porsche"), ("ferrari", "Ferrari", "ferrari")],
    )

    targets = (
        await integration_session.execute(select(CrawlTarget).order_by(CrawlTarget.url))
    ).scalars().all()

    assert result == {"enqueued": 2}
    assert [target.target_type for target in targets] == ["bat_model_page", "bat_model_page"]
    assert {target.metadata_json["label"] for target in targets} == {"Porsche", "Ferrari"}
