"""Shared BaT raw pipeline types and constants."""

from __future__ import annotations

from dataclasses import dataclass

SOURCE = "bring_a_trailer"
BAT_LIST_PARSER_NAME = "bat_completed_results"
BAT_DETAIL_PARSER_NAME = "bat_detail_page"
BAT_LIST_PARSER_VERSION = "bat-list-raw-v1"
BAT_DETAIL_PARSER_VERSION = "bat-detail-raw-v1"


@dataclass(frozen=True)
class RawParseOutcome:
    lots_found: int = 0
    lots_inserted: int = 0
    lots_updated: int = 0
    targets_discovered: int = 0
