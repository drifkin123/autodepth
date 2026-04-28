"""Public facade for BaT raw-page fetch, parse, and replay workflow."""

from app.services.bat_raw_fetch import fetch_bat_target_to_raw_page
from app.services.bat_raw_parse import parse_bat_raw_page
from app.services.bat_raw_types import (
    BAT_DETAIL_PARSER_NAME,
    BAT_DETAIL_PARSER_VERSION,
    BAT_LIST_PARSER_NAME,
    BAT_LIST_PARSER_VERSION,
    SOURCE,
    RawParseOutcome,
)

__all__ = [
    "BAT_DETAIL_PARSER_NAME",
    "BAT_DETAIL_PARSER_VERSION",
    "BAT_LIST_PARSER_NAME",
    "BAT_LIST_PARSER_VERSION",
    "SOURCE",
    "RawParseOutcome",
    "fetch_bat_target_to_raw_page",
    "parse_bat_raw_page",
]
