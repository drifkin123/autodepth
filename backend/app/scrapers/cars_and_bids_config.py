"""Cars & Bids scraper configuration and pacing helpers."""

from app.scrapers.runtime import BROWSER_HEADERS, RetryPolicy, polite_delay_seconds
from app.settings import settings

_BASE_URL = "https://carsandbids.com"
_PAST_AUCTIONS_URL = f"{_BASE_URL}/past-auctions/"
_USER_AGENT = BROWSER_HEADERS["User-Agent"]
_RETRY_POLICY = RetryPolicy(max_attempts=2, base_delay_seconds=3.0, max_delay_seconds=20.0)


def _configured_polite_delay(min_seconds: float, max_seconds: float) -> float:
    if max_seconds < min_seconds:
        max_seconds = min_seconds
    return polite_delay_seconds(min_seconds, max_seconds)


def _cab_interaction_delay_seconds() -> float:
    return _configured_polite_delay(
        settings.cab_interaction_delay_min,
        settings.cab_interaction_delay_max,
    )


def _cab_search_delay_seconds() -> float:
    return _configured_polite_delay(
        settings.cab_search_delay_min,
        settings.cab_search_delay_max,
    )
