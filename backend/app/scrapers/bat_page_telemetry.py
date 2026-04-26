"""Bring a Trailer page telemetry helpers."""

import time

from app.scrapers.bat_config import BASE_URL


class BringATrailerPageTelemetryMixin:
    """Telemetry helpers for BaT completed-result pages."""

    async def _record_initial_page_telemetry(
        self,
        *,
        key: str,
        label: str,
        url_path: str,
        started: float,
        items: list[dict],
        new_count: int,
        dup_count: int,
        skip_counts: dict,
        page_metadata: dict,
        page_limit: int,
    ) -> None:
        pages_total = int(page_metadata.get("pages_total") or 1)
        await self.record_request_log(
            url=f"{BASE_URL}/{url_path}/",
            action="http_get",
            attempt=1,
            status_code=200,
            duration_ms=int((time.perf_counter() - started) * 1000),
            outcome="success",
            raw_item_count=len(items),
            parsed_lot_count=new_count,
            skip_counts=skip_counts,
            metadata_json={
                "label": label,
                "key": key,
                "duplicates": dup_count,
                **page_metadata,
                "page_limit": page_limit,
                "pagination_complete": page_limit >= pages_total,
            },
        )
        await self._record_pagination_warnings(
            label=label,
            url_path=url_path,
            new_count=new_count,
            items=items,
            dup_count=dup_count,
            skip_counts=skip_counts,
            page_metadata=page_metadata,
            page_limit=page_limit,
        )

    async def _record_pagination_warnings(
        self,
        *,
        label: str,
        url_path: str,
        new_count: int,
        items: list[dict],
        dup_count: int,
        skip_counts: dict,
        page_metadata: dict,
        page_limit: int,
    ) -> None:
        pages_total = int(page_metadata.get("pages_total") or 1)
        items_total = page_metadata.get("items_total")
        base_filter = page_metadata.get("base_filter") or {}
        if pages_total > 1 and page_limit < pages_total:
            await self.record_anomaly(
                severity="warning",
                code="bat_pagination_incomplete",
                message=(
                    f"BaT page {label} exposes {pages_total} completed-result "
                    f"pages; {self.mode} mode will parse {page_limit} pages."
                ),
                url=f"{BASE_URL}/{url_path}/",
                metadata_json={
                    "items_total": items_total,
                    "pages_total": pages_total,
                    "page_current": page_metadata.get("page_current"),
                    "parsed_first_page": new_count,
                    "page_limit": page_limit,
                    "mode": self.mode,
                },
            )
        if pages_total > 1 and not base_filter:
            await self.record_anomaly(
                severity="critical",
                code="bat_pagination_missing_filter",
                message=f"BaT page {label} has more pages but no base_filter metadata.",
                url=f"{BASE_URL}/{url_path}/",
                metadata_json={"pages_total": pages_total},
            )
        if len(items) > 0 and new_count == 0 and dup_count == 0:
            await self.record_anomaly(
                severity="warning",
                code="zero_parsed_lots",
                message=f"BaT page {label} returned raw items but parsed zero lots.",
                url=f"{BASE_URL}/{url_path}/",
                metadata_json={"raw_item_count": len(items), "skip_counts": skip_counts},
            )

    async def _emit_page_summary(
        self,
        *,
        label: str,
        index: int,
        total_urls: int,
        page_number: int,
        pages_total: int,
        raw_count: int,
        new_count: int,
        dup_count: int,
        skip_counts: dict,
        run_total: int,
        items_total: object | None = None,
    ) -> None:
        total_s = f" of {items_total} total" if items_total else ""
        page_s = f", page {page_number}/{pages_total}" if pages_total else ""
        dup_s = f", {dup_count} dups" if dup_count else ""
        skip_s = f" - skipped: {skip_counts}" if skip_counts else ""
        level = "warning" if new_count == 0 and raw_count > 0 else "progress"
        await self._emit(
            level,
            f"[{index}/{total_urls}] {label}: {raw_count} raw -> "
            f"{new_count} auctions{total_s}{page_s}{dup_s}{skip_s} "
            f"(run total: {run_total})",
        )
