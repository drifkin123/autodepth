"""Fixture-to-database tests for the raw auction ingestion pipeline."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction_lot import AuctionLot
from app.models.crawl_state import CrawlState
from app.models.scrape_anomaly import ScrapeAnomaly
from app.models.scrape_run import ScrapeRun
from app.scrapers.base import BaseScraper, ScrapedAuctionLot

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class _TestScraper(BaseScraper):
    source = "test"

    async def scrape(self) -> list[ScrapedAuctionLot]:  # pragma: no cover
        return []


async def _count_lots(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(AuctionLot))
    return result.scalar_one()


async def _all_lots(session: AsyncSession) -> list[AuctionLot]:
    result = await session.execute(select(AuctionLot).order_by(AuctionLot.source))
    return list(result.scalars().all())


async def _save_lots(
    scraper: BaseScraper, lots: list[ScrapedAuctionLot | None]
) -> tuple[int, int]:
    inserted = updated = 0
    for lot in lots:
        if lot is None:
            continue
        if await scraper.save_lot(lot):
            inserted += 1
        else:
            updated += 1
    await scraper.session.commit()
    return inserted, updated


class TestBatIntegration:
    async def test_bat_fixture_inserts_auction_lots(
        self, integration_session: AsyncSession
    ) -> None:
        from app.scrapers.bat_parser import extract_items_from_html, parse_item

        html = (FIXTURES_DIR / "bat_porsche_911_gt3.html").read_text()
        parsed_lots = [parse_item(item)[0] for item in extract_items_from_html(html)]

        scraper = _TestScraper(integration_session)
        inserted, updated = await _save_lots(scraper, parsed_lots)

        assert inserted > 0
        assert updated == 0
        assert await _count_lots(integration_session) == inserted

    async def test_bat_raw_fields_are_persisted(
        self, integration_session: AsyncSession
    ) -> None:
        from app.scrapers.bat_parser import extract_items_from_html, parse_item

        html = (FIXTURES_DIR / "bat_porsche_911_gt3.html").read_text()
        parsed_lots = [parse_item(item)[0] for item in extract_items_from_html(html)]

        scraper = _TestScraper(integration_session)
        await _save_lots(scraper, parsed_lots)

        lot = (await _all_lots(integration_session))[0]

        assert lot.source == "bring_a_trailer"
        assert lot.auction_status in {"sold", "reserve_not_met", "unknown"}
        assert lot.canonical_url.startswith("https://bringatrailer.com")
        assert lot.title
        assert lot.list_payload
        if lot.auction_status == "sold":
            assert lot.sold_price is not None
            assert lot.high_bid == lot.sold_price

    async def test_bat_duplicate_updates_existing_lots(
        self, integration_session: AsyncSession
    ) -> None:
        from app.scrapers.bat_parser import extract_items_from_html, parse_item

        html = (FIXTURES_DIR / "bat_porsche_911_gt3.html").read_text()
        parsed_lots = [parse_item(item)[0] for item in extract_items_from_html(html)]

        scraper = _TestScraper(integration_session)
        first_inserted, _ = await _save_lots(scraper, parsed_lots)
        second_inserted, second_updated = await _save_lots(scraper, parsed_lots)

        assert first_inserted > 0
        assert second_inserted == 0
        assert second_updated == first_inserted
        assert await _count_lots(integration_session) == first_inserted


class TestCarsAndBidsIntegration:
    async def test_cab_fixture_inserts_auction_lots(
        self, integration_session: AsyncSession
    ) -> None:
        from app.scrapers.cars_and_bids_parser import parse_auction

        items = json.loads((FIXTURES_DIR / "cars_and_bids_porsche_911_gt3.json").read_text())
        parsed_lots = [parse_auction(item)[0] for item in items]

        scraper = _TestScraper(integration_session)
        inserted, updated = await _save_lots(scraper, parsed_lots)

        assert inserted > 0
        assert updated == 0
        assert await _count_lots(integration_session) == inserted

    async def test_cab_raw_fields_are_persisted(
        self, integration_session: AsyncSession
    ) -> None:
        from app.scrapers.cars_and_bids_parser import parse_auction

        items = json.loads((FIXTURES_DIR / "cars_and_bids_porsche_911_gt3.json").read_text())
        parsed_lots = [parse_auction(item)[0] for item in items]

        scraper = _TestScraper(integration_session)
        await _save_lots(scraper, parsed_lots)

        lot = (await _all_lots(integration_session))[0]

        assert lot.source == "cars_and_bids"
        assert lot.auction_status in {"sold", "reserve_not_met", "unknown"}
        assert lot.canonical_url.startswith("https://carsandbids.com")
        assert lot.source_auction_id
        assert lot.list_payload
        if lot.auction_status == "sold":
            assert lot.sold_price is not None
            assert lot.high_bid == lot.sold_price


class TestPipelineBehavior:
    async def test_cancelled_run_marks_status_and_checkpoints_partial_progress(
        self, integration_session: AsyncSession
    ) -> None:
        lot = ScrapedAuctionLot(
            source="test",
            source_auction_id="cancelled-1",
            canonical_url="https://example.com/cancelled-1",
            auction_status="sold",
            sold_price=100_000,
            high_bid=100_000,
            bid_count=10,
        )

        class CancelledScraper(BaseScraper):
            source = "test"

            def __init__(self, session: AsyncSession) -> None:
                super().__init__(session)
                self._cancel_event = asyncio.Event()

            async def scrape(self) -> list[ScrapedAuctionLot]:
                await self.persist_lots([lot], context="page 1")
                self._cancel_event.set()
                return []

        found, inserted = await CancelledScraper(integration_session).run()

        assert (found, inserted) == (1, 1)
        run = (await integration_session.execute(select(ScrapeRun))).scalar_one()
        state = (await integration_session.execute(select(CrawlState))).scalar_one()
        assert run.status == "cancelled"
        assert run.finished_at is not None
        assert state.source == "test"
        assert state.state["last_status"] == "cancelled"
        assert state.state["records_found"] == 1
        assert state.state["last_context"] == "page 1"

    async def test_missing_detail_enrichment_emits_warning_anomaly(
        self, integration_session: AsyncSession
    ) -> None:
        lot = ScrapedAuctionLot(
            source="test",
            source_auction_id="missing-detail-1",
            canonical_url="https://example.com/missing-detail-1",
            auction_status="sold",
            sold_price=100_000,
            high_bid=100_000,
            bid_count=10,
        )

        class DetailAwareScraper(BaseScraper):
            source = "test"
            warn_missing_detail_enrichment = True

            async def scrape(self) -> list[ScrapedAuctionLot]:
                return [lot]

        await DetailAwareScraper(integration_session).run()

        anomaly = (await integration_session.execute(select(ScrapeAnomaly))).scalar_one()
        assert anomaly.code == "missing_detail_enrichment"
        assert anomaly.severity == "warning"
        assert anomaly.metadata_json["missing_detail_count"] == 1

    async def test_list_only_update_preserves_existing_detail_enrichment(
        self, integration_session: AsyncSession
    ) -> None:
        detailed_lot = ScrapedAuctionLot(
            source="bring_a_trailer",
            source_auction_id="detail-preserve-1",
            canonical_url="https://bringatrailer.com/listing/detail-preserve-1/",
            auction_status="sold",
            sold_price=100_000,
            high_bid=100_000,
            bid_count=10,
            vin="WP0EXAMPLE",
            mileage=12_000,
            detail_payload={"lot_number": "12345"},
            detail_html="<html>detail</html>",
            detail_scraped_at=datetime.now(UTC),
            image_urls=[
                "https://bringatrailer.com/wp-content/uploads/detail-1.jpg",
                "https://bringatrailer.com/wp-content/uploads/detail-2.jpg",
            ],
        )
        list_lot = ScrapedAuctionLot(
            source="bring_a_trailer",
            source_auction_id="detail-preserve-1",
            canonical_url="https://bringatrailer.com/listing/detail-preserve-1/",
            auction_status="sold",
            sold_price=101_000,
            high_bid=101_000,
            bid_count=None,
            image_urls=["https://bringatrailer.com/wp-content/uploads/thumb.jpg"],
        )

        scraper = _TestScraper(integration_session)
        assert await scraper.save_lot(detailed_lot) is True
        assert await scraper.save_lot(list_lot) is False
        await integration_session.commit()

        lot = (await _all_lots(integration_session))[0]
        assert lot.sold_price == 101_000
        assert lot.bid_count == 10
        assert lot.vin == "WP0EXAMPLE"
        assert lot.mileage == 12_000
        assert lot.detail_payload == {"lot_number": "12345"}
        assert lot.detail_html == "<html>detail</html>"
        assert lot.detail_scraped_at is not None
        assert [image.image_url for image in lot.images] == detailed_lot.image_urls

    async def test_run_preserves_page_persisted_lots_when_later_request_fails(
        self, integration_session: AsyncSession
    ) -> None:
        page_lot = ScrapedAuctionLot(
            source="test",
            source_auction_id="page-1",
            canonical_url="https://example.com/page-1",
            auction_status="sold",
            sold_price=100_000,
            high_bid=100_000,
            bid_count=10,
            title="2020 Porsche 911 GT3",
        )

        class PagePersistingScraper(BaseScraper):
            source = "test"

            async def scrape(self) -> list[ScrapedAuctionLot]:
                await self.persist_lots([page_lot], context="page 1")
                run_result = await self.session.execute(
                    select(ScrapeRun).where(ScrapeRun.id == self.current_run_id)
                )
                active_run = run_result.scalar_one()
                assert active_run.status == "running"
                assert active_run.records_found == 1
                assert active_run.records_inserted == 1
                raise RuntimeError("rate limited after page 1")

        scraper = PagePersistingScraper(integration_session)

        try:
            await scraper.run()
        except RuntimeError:
            pass

        assert await _count_lots(integration_session) == 1
        run_result = await integration_session.execute(select(ScrapeRun))
        scrape_run = run_result.scalar_one()
        assert scrape_run.status == "error"
        assert scrape_run.records_found == 1
        assert scrape_run.records_inserted == 1
        assert scrape_run.error == "rate limited after page 1"

    async def test_uncatalogued_vehicle_is_still_saved(
        self, integration_session: AsyncSession
    ) -> None:
        lot = ScrapedAuctionLot(
            source="bring_a_trailer",
            source_auction_id="unknown-car-99999",
            canonical_url="https://bringatrailer.com/listing/unknown-car-99999/",
            auction_status="sold",
            sold_price=3_800_000,
            high_bid=3_800_000,
            bid_count=72,
            year=2022,
            make="Bugatti",
            model="Chiron",
            trim="Super Sport",
            title="2022 Bugatti Chiron Super Sport",
            list_payload={"fixture": True},
        )

        scraper = _TestScraper(integration_session)
        inserted = await scraper.save_lot(lot)
        await integration_session.commit()

        assert inserted is True
        assert await _count_lots(integration_session) == 1

    async def test_target_sources_saved_independently(
        self, integration_session: AsyncSession
    ) -> None:
        bat_lot = ScrapedAuctionLot(
            source="bring_a_trailer",
            source_auction_id="bat-1",
            canonical_url="https://bringatrailer.com/listing/example-car/",
            auction_status="sold",
            sold_price=100_000,
            high_bid=100_000,
            bid_count=10,
        )
        cab_lot = ScrapedAuctionLot(
            source="cars_and_bids",
            source_auction_id="cab-1",
            canonical_url="https://carsandbids.com/auctions/example-car",
            auction_status="reserve_not_met",
            sold_price=None,
            high_bid=90_000,
            bid_count=8,
        )

        scraper = _TestScraper(integration_session)
        inserted, _ = await _save_lots(scraper, [bat_lot, cab_lot])

        lots = await _all_lots(integration_session)
        assert inserted == 2
        assert {lot.source for lot in lots} == {"bring_a_trailer", "cars_and_bids"}
