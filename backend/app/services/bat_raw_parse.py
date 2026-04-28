"""Orchestrate stored BaT raw-page parsing and replay."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_page import RawPage
from app.models.raw_parse_run import RawParseRun
from app.services.artifacts import ArtifactStore
from app.services.bat_raw_detail_parse import parse_detail_page
from app.services.bat_raw_list_parse import parse_list_page
from app.services.bat_raw_types import (
    BAT_DETAIL_PARSER_NAME,
    BAT_DETAIL_PARSER_VERSION,
    BAT_LIST_PARSER_NAME,
    BAT_LIST_PARSER_VERSION,
    SOURCE,
    RawParseOutcome,
)


async def parse_bat_raw_page(
    session: AsyncSession,
    *,
    artifact_store: ArtifactStore,
    raw_page_id: uuid.UUID,
    parser_version: str | None = None,
) -> RawParseOutcome:
    raw_page = await session.get(RawPage, raw_page_id)
    if raw_page is None:
        raise ValueError(f"Raw page not found: {raw_page_id}")
    if raw_page.source != SOURCE:
        raise ValueError(f"Unsupported raw page source: {raw_page.source}")

    parser_name = _parser_name_for_target(raw_page.target_type)
    parse_run = RawParseRun(
        raw_page_id=raw_page.id,
        parser_name=parser_name,
        parser_version=parser_version or _default_parser_version(parser_name),
        status="running",
    )
    session.add(parse_run)
    await session.commit()

    try:
        content = await artifact_store.load(raw_page.artifact_uri)
        if parser_name == BAT_DETAIL_PARSER_NAME:
            outcome = await parse_detail_page(
                session,
                raw_page,
                content.decode(errors="replace"),
            )
        else:
            outcome = await parse_list_page(session, raw_page, content)
    except Exception as exc:
        parse_run.status = "error"
        parse_run.error = str(exc)
        parse_run.finished_at = datetime.now(UTC)
        await session.commit()
        raise

    parse_run.status = "success"
    parse_run.records_found = outcome.lots_found
    parse_run.records_inserted = outcome.lots_inserted
    parse_run.records_updated = outcome.lots_updated
    parse_run.targets_discovered = outcome.targets_discovered
    parse_run.finished_at = datetime.now(UTC)
    await session.commit()
    return outcome


def _parser_name_for_target(target_type: str) -> str:
    if target_type == "bat_detail_page":
        return BAT_DETAIL_PARSER_NAME
    return BAT_LIST_PARSER_NAME


def _default_parser_version(parser_name: str) -> str:
    if parser_name == BAT_DETAIL_PARSER_NAME:
        return BAT_DETAIL_PARSER_VERSION
    return BAT_LIST_PARSER_VERSION
