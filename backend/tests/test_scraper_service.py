"""Tests for the scraper runner service.

Mocks actual scraper classes — no network or DB calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Tests for run_all_scrapers ─────────────────────────────────────────────

class TestRunAllScrapers:
    @patch("app.services.scraper.CarsComScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_runs_both_scrapers_in_sequence(
        self, MockBat: MagicMock, MockCC: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        mock_bat_instance = MagicMock()
        mock_bat_instance.source = "bring_a_trailer"
        mock_bat_instance.run = AsyncMock(return_value=(50, 10))
        MockBat.return_value = mock_bat_instance

        mock_cc_instance = MagicMock()
        mock_cc_instance.source = "cars_com"
        mock_cc_instance.run = AsyncMock(return_value=(30, 5))
        MockCC.return_value = mock_cc_instance

        session = AsyncMock()
        results = await run_all_scrapers(session)

        assert results["bring_a_trailer"] == (50, 10)
        assert results["cars_com"] == (30, 5)
        MockBat.assert_called_once()
        MockCC.assert_called_once()

    @patch("app.services.scraper.CarsComScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_bat_failure_returns_negative_one(
        self, MockBat: MagicMock, MockCC: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        mock_bat_instance = MagicMock()
        mock_bat_instance.source = "bring_a_trailer"
        mock_bat_instance.run = AsyncMock(side_effect=RuntimeError("Network error"))
        MockBat.return_value = mock_bat_instance

        mock_cc_instance = MagicMock()
        mock_cc_instance.source = "cars_com"
        mock_cc_instance.run = AsyncMock(return_value=(20, 3))
        MockCC.return_value = mock_cc_instance

        session = AsyncMock()
        results = await run_all_scrapers(session)

        assert results["bring_a_trailer"] == (-1, -1)
        assert results["cars_com"] == (20, 3)

    @patch("app.services.scraper.CarsComScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_cars_com_failure_returns_negative_one(
        self, MockBat: MagicMock, MockCC: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        mock_bat_instance = MagicMock()
        mock_bat_instance.source = "bring_a_trailer"
        mock_bat_instance.run = AsyncMock(return_value=(40, 8))
        MockBat.return_value = mock_bat_instance

        mock_cc_instance = MagicMock()
        mock_cc_instance.source = "cars_com"
        mock_cc_instance.run = AsyncMock(side_effect=RuntimeError("Timeout"))
        MockCC.return_value = mock_cc_instance

        session = AsyncMock()
        results = await run_all_scrapers(session)

        assert results["bring_a_trailer"] == (40, 8)
        assert results["cars_com"] == (-1, -1)

    @patch("app.services.scraper.CarsComScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_cancel_event_skips_cars_com(
        self, MockBat: MagicMock, MockCC: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        cancel_event = asyncio.Event()

        mock_bat_instance = MagicMock()
        mock_bat_instance.source = "bring_a_trailer"

        async def bat_run_and_cancel() -> tuple[int, int]:
            cancel_event.set()
            return (25, 5)

        mock_bat_instance.run = AsyncMock(side_effect=bat_run_and_cancel)
        MockBat.return_value = mock_bat_instance

        session = AsyncMock()
        results = await run_all_scrapers(session, cancel_event=cancel_event)

        assert results["bring_a_trailer"] == (25, 5)
        assert "cars_com" not in results
        MockCC.assert_not_called()

    @patch("app.services.scraper.CarsComScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_passes_selected_keys_to_scrapers(
        self, MockBat: MagicMock, MockCC: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        mock_bat_instance = MagicMock()
        mock_bat_instance.source = "bring_a_trailer"
        mock_bat_instance.run = AsyncMock(return_value=(10, 2))
        MockBat.return_value = mock_bat_instance

        mock_cc_instance = MagicMock()
        mock_cc_instance.source = "cars_com"
        mock_cc_instance.run = AsyncMock(return_value=(5, 1))
        MockCC.return_value = mock_cc_instance

        session = AsyncMock()
        bat_keys = {"porsche-911-gt3"}
        cc_keys = {"porsche-911"}

        await run_all_scrapers(
            session,
            bat_selected_keys=bat_keys,
            cars_com_selected_keys=cc_keys,
        )

        bat_call_kwargs = MockBat.call_args
        assert bat_call_kwargs[1]["selected_keys"] == bat_keys

        cc_call_kwargs = MockCC.call_args
        assert cc_call_kwargs[1]["selected_keys"] == cc_keys

    @patch("app.services.scraper.CarsComScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_passes_broadcaster(
        self, MockBat: MagicMock, MockCC: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        mock_bat_instance = MagicMock()
        mock_bat_instance.source = "bring_a_trailer"
        mock_bat_instance.run = AsyncMock(return_value=(1, 0))
        MockBat.return_value = mock_bat_instance

        mock_cc_instance = MagicMock()
        mock_cc_instance.source = "cars_com"
        mock_cc_instance.run = AsyncMock(return_value=(1, 0))
        MockCC.return_value = mock_cc_instance

        session = AsyncMock()
        broadcaster = MagicMock()

        await run_all_scrapers(session, broadcaster)

        # Both scrapers should receive the broadcaster as second positional arg
        assert MockBat.call_args[0][1] is broadcaster
        assert MockCC.call_args[0][1] is broadcaster

    @patch("app.services.scraper.CarsComScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_both_fail_gracefully(
        self, MockBat: MagicMock, MockCC: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        mock_bat_instance = MagicMock()
        mock_bat_instance.source = "bring_a_trailer"
        mock_bat_instance.run = AsyncMock(side_effect=RuntimeError("BaT down"))
        MockBat.return_value = mock_bat_instance

        mock_cc_instance = MagicMock()
        mock_cc_instance.source = "cars_com"
        mock_cc_instance.run = AsyncMock(side_effect=RuntimeError("CC down"))
        MockCC.return_value = mock_cc_instance

        session = AsyncMock()
        results = await run_all_scrapers(session)

        assert results["bring_a_trailer"] == (-1, -1)
        assert results["cars_com"] == (-1, -1)
