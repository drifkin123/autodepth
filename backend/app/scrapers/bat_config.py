"""Bring a Trailer scraper configuration and pacing helpers."""

from app.scrapers.runtime import BROWSER_HEADERS, RetryPolicy, polite_delay_seconds
from app.settings import settings

BASE_URL = "https://bringatrailer.com"
MODELS_URL = f"{BASE_URL}/models/"
LISTINGS_FILTER_URL = f"{BASE_URL}/wp-json/bringatrailer/1.0/data/listings-filter"

_HEADERS = BROWSER_HEADERS
_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=30.0)
_INCREMENTAL_COMPLETED_PAGE_LIMIT = 5


def _configured_polite_delay(min_seconds: float, max_seconds: float) -> float:
    if max_seconds < min_seconds:
        max_seconds = min_seconds
    return polite_delay_seconds(min_seconds, max_seconds)


def _list_page_delay_seconds() -> float:
    return _configured_polite_delay(
        settings.bat_list_page_delay_min,
        settings.bat_list_page_delay_max,
    )


def _detail_page_delay_seconds() -> float:
    return _configured_polite_delay(
        settings.bat_detail_delay_min,
        settings.bat_detail_delay_max,
    )


def _target_delay_seconds() -> float:
    return _configured_polite_delay(
        settings.bat_target_delay_min,
        settings.bat_target_delay_max,
    )
