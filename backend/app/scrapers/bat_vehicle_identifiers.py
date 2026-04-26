"""Bring a Trailer vehicle identifier normalization."""

from __future__ import annotations

import re

STANDARD_VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def normalize_chassis_identifier(raw_identifier: str) -> str | None:
    identifier = raw_identifier.strip()
    prefix_pattern = re.compile(
        r"^(?:chassis|vin|serial)(?:\s*(?:no\.?|number|#))?\s*[:#]\s*",
        re.IGNORECASE,
    )
    while True:
        normalized_identifier = prefix_pattern.sub("", identifier).strip()
        if normalized_identifier == identifier:
            break
        identifier = normalized_identifier
    identifier = re.split(
        r"\s*,\s*(?:model|body|engine)\s*#?",
        identifier,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    identifier = re.sub(r"\s+", " ", identifier).strip()
    return identifier.upper() or None


def is_standard_vin(identifier: str) -> bool:
    return STANDARD_VIN_PATTERN.fullmatch(identifier) is not None


def should_persist_identifier_as_vin(identifier: str, model_year: int | None) -> bool:
    if model_year is not None and model_year >= 1981:
        return is_standard_vin(identifier)
    return True
