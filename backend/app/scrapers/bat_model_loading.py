"""Bring a Trailer model-directory loading helpers."""

import time

import httpx

from app.scrapers.bat_config import MODELS_URL
from app.scrapers.bat_targets import fetch_model_entries


class BringATrailerModelLoadingMixin:
    """Load BaT model targets with fallback to configured makes."""

    async def _load_urls(self, client: httpx.AsyncClient) -> list[tuple[str, str, str]]:
        if self._selected_keys is not None:
            return self._get_urls()
        try:
            started = time.perf_counter()
            urls = await fetch_model_entries(client)
            await self.record_request_log(
                url=MODELS_URL,
                action="models_directory",
                attempt=1,
                status_code=200,
                duration_ms=int((time.perf_counter() - started) * 1000),
                outcome="success",
                raw_item_count=len(urls),
                parsed_lot_count=len(urls),
            )
        except httpx.HTTPError as exc:
            await self.record_request_log(
                url=MODELS_URL,
                action="models_directory",
                attempt=1,
                outcome="error",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            await self._emit("error", f"Could not load BaT models directory - {exc}")
            urls = self._get_urls()
        if not urls:
            await self.record_anomaly(
                severity="critical",
                code="models_directory_empty",
                message="BaT models directory returned no crawl targets.",
                url=MODELS_URL,
            )
            urls = self._get_urls()
        return urls
