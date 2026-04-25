"""Tests for the scraper runner service.

Mocks actual scraper classes — no network or DB calls.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import app.services.scraper as scraper_module


def _mock_scraper(source: str, result: tuple[int, int] = (0, 0)) -> MagicMock:
    """Return a pre-configured mock scraper instance."""
    instance = MagicMock()
    instance.source = source
    instance.run = AsyncMock(return_value=result)
    return instance


# ─── Tests for run_all_scrapers ─────────────────────────────────────────────

class TestRunAllScrapers:
    @patch("app.services.scraper.CarsAndBidsScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_runs_all_scrapers_in_sequence(
        self, MockBat: MagicMock, MockCab: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        MockBat.return_value = _mock_scraper("bring_a_trailer", (50, 10))
        MockCab.return_value = _mock_scraper("cars_and_bids", (20, 4))

        session = AsyncMock()
        results = await run_all_scrapers(session)

        assert results["bring_a_trailer"] == (50, 10)
        assert results["cars_and_bids"] == (20, 4)
        assert set(results) == {"bring_a_trailer", "cars_and_bids"}
        MockBat.assert_called_once()
        MockCab.assert_called_once()

    @patch("app.services.scraper.CarsAndBidsScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_bat_failure_returns_negative_one(
        self, MockBat: MagicMock, MockCab: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        mock_bat = _mock_scraper("bring_a_trailer")
        mock_bat.run = AsyncMock(side_effect=RuntimeError("Network error"))
        MockBat.return_value = mock_bat
        MockCab.return_value = _mock_scraper("cars_and_bids", (10, 2))

        session = AsyncMock()
        results = await run_all_scrapers(session)

        assert results["bring_a_trailer"] == (-1, -1)
        assert results["cars_and_bids"] == (10, 2)

    @patch("app.services.scraper.CarsAndBidsScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_cancel_event_skips_remaining_scrapers(
        self, MockBat: MagicMock, MockCab: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        cancel_event = asyncio.Event()

        mock_bat = _mock_scraper("bring_a_trailer")

        async def bat_run_and_cancel() -> tuple[int, int]:
            cancel_event.set()
            return (25, 5)

        mock_bat.run = AsyncMock(side_effect=bat_run_and_cancel)
        MockBat.return_value = mock_bat

        session = AsyncMock()
        results = await run_all_scrapers(session, cancel_event=cancel_event)

        assert results["bring_a_trailer"] == (25, 5)
        assert "cars_and_bids" not in results
        MockCab.assert_not_called()

    @patch("app.services.scraper.CarsAndBidsScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_passes_selected_keys_to_scrapers(
        self, MockBat: MagicMock, MockCab: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        MockBat.return_value = _mock_scraper("bring_a_trailer", (10, 2))
        MockCab.return_value = _mock_scraper("cars_and_bids", (3, 1))

        session = AsyncMock()
        bat_keys = {"porsche"}
        cab_keys = {"porsche"}

        await run_all_scrapers(
            session,
            bat_selected_keys=bat_keys,
            carsandbids_selected_keys=cab_keys,
        )

        assert MockBat.call_args[1]["selected_keys"] == bat_keys
        assert MockCab.call_args[1]["selected_keys"] == cab_keys

    @patch("app.services.scraper.CarsAndBidsScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_passes_scrape_mode_to_scrapers(
        self, MockBat: MagicMock, MockCab: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        MockBat.return_value = _mock_scraper("bring_a_trailer", (10, 2))
        MockCab.return_value = _mock_scraper("cars_and_bids", (3, 1))

        session = AsyncMock()
        await run_all_scrapers(session, mode="backfill")

        assert MockBat.call_args[1]["mode"] == "backfill"
        assert MockCab.call_args[1]["mode"] == "backfill"

    @patch("app.services.scraper.CarsAndBidsScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_passes_broadcaster(
        self, MockBat: MagicMock, MockCab: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        MockBat.return_value = _mock_scraper("bring_a_trailer", (1, 0))
        MockCab.return_value = _mock_scraper("cars_and_bids", (1, 0))

        session = AsyncMock()
        broadcaster = MagicMock()

        await run_all_scrapers(session, broadcaster)

        assert MockBat.call_args[0][1] is broadcaster
        assert MockCab.call_args[0][1] is broadcaster

    @patch("app.services.scraper.CarsAndBidsScraper")
    @patch("app.services.scraper.BringATrailerScraper")
    async def test_both_fail_gracefully(
        self, MockBat: MagicMock, MockCab: MagicMock
    ) -> None:
        from app.services.scraper import run_all_scrapers

        mock_bat = _mock_scraper("bring_a_trailer")
        mock_bat.run = AsyncMock(side_effect=RuntimeError("BaT down"))
        MockBat.return_value = mock_bat

        mock_cab = _mock_scraper("cars_and_bids")
        mock_cab.run = AsyncMock(side_effect=RuntimeError("C&B down"))
        MockCab.return_value = mock_cab

        session = AsyncMock()
        results = await run_all_scrapers(session)

        assert results["bring_a_trailer"] == (-1, -1)
        assert results["cars_and_bids"] == (-1, -1)


def test_scraper_service_has_no_modeling_hook() -> None:
    assert "depreciation" not in inspect.getsource(scraper_module)
