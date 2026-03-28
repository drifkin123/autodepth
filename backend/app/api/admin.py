"""Admin-only routes (requires authentication)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.db import get_db
from app.services.depreciation import run_all_depreciation_models
from app.services.scraper import run_all_scrapers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class ScrapeResult(BaseModel):
    results: dict[str, tuple[int, int]]
    message: str


@router.post("/scrape/trigger", response_model=ScrapeResult)
async def trigger_scrape(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ScrapeResult:
    """Manually trigger a full scrape run then refresh all depreciation models."""
    logger.info("Manual scrape triggered by user %s", user_id)
    scrape_results = await run_all_scrapers(db)
    await run_all_depreciation_models(db)
    return ScrapeResult(
        results=scrape_results,
        message=f"Scrape complete. {len(scrape_results)} source(s) processed.",
    )
