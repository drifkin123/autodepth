"""Bring a Trailer request retry and detail enrichment workflow."""

from app.scrapers.bat_detail_requests import BringATrailerDetailRequestMixin
from app.scrapers.bat_page_requests import BringATrailerPageRequestMixin


class BringATrailerRequestMixin(
    BringATrailerPageRequestMixin,
    BringATrailerDetailRequestMixin,
):
    """Composite BaT request workflow mixin."""
