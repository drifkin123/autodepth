"""Tests for raw pipeline CLI routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from scripts import run_raw_pipeline


def test_raw_pipeline_cli_parses_seed_bat_options() -> None:
    args = run_raw_pipeline.parse_args(
        ["seed-bat", "--target-source", "makes", "--selected-key", "porsche"]
    )

    assert args.command == "seed-bat"
    assert args.target_source == "makes"
    assert args.selected_key == ["porsche"]


@pytest.mark.asyncio
@patch("scripts.run_raw_pipeline.seed_bat_raw_targets", new_callable=AsyncMock)
async def test_raw_pipeline_cli_routes_seed_bat_to_service(
    mock_seed_bat_raw_targets: AsyncMock,
) -> None:
    mock_seed_bat_raw_targets.return_value = {"enqueued": 1}

    result = await run_raw_pipeline.main(
        command="seed-bat",
        target_source="makes",
        selected_key=["porsche"],
        raw_page_id=None,
    )

    assert result == {"enqueued": 1}
    mock_seed_bat_raw_targets.assert_awaited_once()
