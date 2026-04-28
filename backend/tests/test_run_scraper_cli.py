"""Tests for the manual scraper CLI."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from scripts import run_scraper


def test_cli_parses_concurrent_bat_backfill_options() -> None:
    args = run_scraper.parse_args(
        [
            "--source",
            "bring_a_trailer",
            "--mode",
            "backfill",
            "--concurrent",
            "--workers",
            "4",
            "--bat-target-source",
            "makes",
        ]
    )

    assert args.source == "bring_a_trailer"
    assert args.mode == "backfill"
    assert args.concurrent is True
    assert args.workers == 4
    assert args.bat_target_source == "makes"
    assert args.skip_details is True


@pytest.mark.asyncio
@patch("scripts.run_scraper.run_bat_concurrent_backfill", new_callable=AsyncMock)
async def test_cli_routes_concurrent_bat_backfill_to_runner(
    mock_run_bat_concurrent_backfill: AsyncMock,
) -> None:
    mock_run_bat_concurrent_backfill.return_value = {"bring_a_trailer": (12, 10)}

    await run_scraper.main(
        source="bring_a_trailer",
        mode="backfill",
        concurrent=True,
        workers=4,
        bat_target_source="makes",
        skip_details=True,
    )

    mock_run_bat_concurrent_backfill.assert_awaited_once_with(
        run_scraper.async_session_factory,
        workers=4,
        target_source="makes",
        skip_details=True,
        mode="backfill",
    )
