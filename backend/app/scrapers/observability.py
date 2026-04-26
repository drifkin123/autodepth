"""Scraper telemetry, anomaly, and crawl-state helpers."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select

from app.models.auction_lot import AuctionLot
from app.models.scrape_anomaly import ScrapeAnomaly
from app.models.scrape_request_log import ScrapeRequestLog
from app.scrapers.observability_state import ScraperCrawlStateMixin
from app.settings import settings

logger = logging.getLogger(__name__)


class ScraperObservabilityMixin(ScraperCrawlStateMixin):
    """Telemetry helpers used by all scrapers."""

    def _is_cancel_requested(self) -> bool:
        cancel_event = getattr(self, "_cancel_event", None)
        return bool(cancel_event is not None and cancel_event.is_set())

    async def _emit(self, event_type: str, message: str, data: dict | None = None) -> None:
        if self.broadcaster is None:
            return
        from app.broadcast import ScrapeEvent

        event: ScrapeEvent = ScrapeEvent(
            type=event_type,
            source=self.source,
            message=message,
            data=data or {},
        )
        await self.broadcaster.publish(event)

    async def record_request_log(
        self,
        *,
        url: str,
        action: str,
        attempt: int,
        status_code: int | None = None,
        duration_ms: int | None = None,
        outcome: str,
        error_type: str | None = None,
        error_message: str | None = None,
        retry_delay_seconds: float | None = None,
        raw_item_count: int | None = None,
        parsed_lot_count: int | None = None,
        skip_counts: dict | None = None,
        metadata_json: dict | None = None,
    ) -> None:
        self.request_log_count += 1
        self.session.add(
            ScrapeRequestLog(
                scrape_run_id=self.current_run_id,
                source=self.source,
                url=url,
                action=action,
                attempt=attempt,
                status_code=status_code,
                duration_ms=duration_ms,
                outcome=outcome,
                error_type=error_type,
                error_message=error_message,
                retry_delay_seconds=retry_delay_seconds,
                raw_item_count=raw_item_count,
                parsed_lot_count=parsed_lot_count,
                skip_counts=skip_counts or {},
                metadata_json=metadata_json or {},
            )
        )
        await self.session.commit()
        logger.info(
            "scrape_request source=%s action=%s outcome=%s status=%s attempt=%s "
            "duration_ms=%s raw_items=%s parsed_lots=%s skips=%s metadata=%s url=%s",
            self.source,
            action,
            outcome,
            status_code,
            attempt,
            duration_ms,
            raw_item_count,
            parsed_lot_count,
            skip_counts or {},
            metadata_json or {},
            url,
        )

    async def record_anomaly(
        self,
        *,
        severity: str,
        code: str,
        message: str,
        url: str | None = None,
        metadata_json: dict | None = None,
    ) -> None:
        self.anomaly_count += 1
        self.session.add(
            ScrapeAnomaly(
                scrape_run_id=self.current_run_id,
                source=self.source,
                severity=severity,
                code=code,
                message=message,
                url=url,
                metadata_json=metadata_json or {},
            )
        )
        await self.session.commit()
        log_method = logger.error if severity == "critical" else logger.warning
        log_method(
            "scrape_anomaly source=%s severity=%s code=%s message=%s metadata=%s url=%s",
            self.source,
            severity,
            code,
            message,
            metadata_json or {},
            url,
        )
        await self._emit(
            "warning" if severity != "critical" else "error",
            message,
            {"severity": severity, "code": code, "url": url, **(metadata_json or {})},
        )

    async def _record_missing_detail_enrichment_anomaly(self) -> None:
        if not self.warn_missing_detail_enrichment:
            return
        source_ids = list(dict.fromkeys(self.auction_ids_discovered))
        source_urls = list(dict.fromkeys(self.auction_urls_discovered))
        if not source_ids and not source_urls:
            return
        predicates = []
        if source_ids:
            predicates.append(AuctionLot.source_auction_id.in_(source_ids))
        if source_urls:
            predicates.append(AuctionLot.canonical_url.in_(source_urls))
        result = await self.session.execute(
            select(func.count())
            .select_from(AuctionLot)
            .where(
                AuctionLot.source == self.source,
                AuctionLot.detail_scraped_at.is_(None),
                or_(*predicates),
            )
        )
        missing_detail_count = result.scalar_one()
        if missing_detail_count <= 0:
            return
        await self.record_anomaly(
            severity="warning",
            code="missing_detail_enrichment",
            message=(
                f"{self.source} has {missing_detail_count} persisted lots from this run "
                "without detail enrichment."
            ),
            metadata_json={"missing_detail_count": missing_detail_count},
        )

    async def prune_old_request_logs(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=settings.request_log_retention_days)
        await self.session.execute(
            delete(ScrapeRequestLog).where(ScrapeRequestLog.created_at < cutoff)
        )
