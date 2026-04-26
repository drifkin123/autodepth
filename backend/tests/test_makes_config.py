"""Validation tests for scrape target configuration."""

from app.scrapers.bring_a_trailer import get_url_entries as get_bat_url_entries
from app.scrapers.cars_and_bids import get_url_entries as get_cab_url_entries
from app.scrapers.makes import BAT_MAKES


def test_bat_make_targets_have_unique_keys() -> None:
    keys = [entry[0] for entry in BAT_MAKES]

    assert len(keys) == len(set(keys))


def test_bat_make_targets_are_complete_tuples() -> None:
    for key, label, slug in BAT_MAKES:
        assert key.strip()
        assert label.strip()
        assert slug.strip()


def test_bat_target_endpoint_entries_include_paths() -> None:
    entries = get_bat_url_entries()

    assert entries
    assert all(entry["key"] and entry["label"] and entry["path"] for entry in entries)


def test_cars_and_bids_uses_global_closed_auction_target() -> None:
    entries = get_cab_url_entries()

    assert entries == [{"key": "all", "label": "All closed auctions", "query": ""}]


def test_scraper_refactor_keeps_public_imports_compatible() -> None:
    from app.scrapers.bat_parser import enrich_lot_from_detail_html, parse_item
    from app.scrapers.bring_a_trailer import BringATrailerScraper, get_url_entries
    from app.scrapers.cars_and_bids import CarsAndBidsScraper

    assert BringATrailerScraper.source == "bring_a_trailer"
    assert CarsAndBidsScraper.source == "cars_and_bids"
    assert callable(get_url_entries)
    assert callable(parse_item)
    assert callable(enrich_lot_from_detail_html)
