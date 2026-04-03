"""Validation tests for the centralized makes configuration in scrapers/makes.py."""

import pytest
from app.scrapers.makes import BAT_MAKES, CAB_MAKES, CARS_COM_MAKES


ALL_LISTS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("BAT_MAKES", BAT_MAKES),
    ("CAB_MAKES", CAB_MAKES),
    ("CARS_COM_MAKES", CARS_COM_MAKES),
]


@pytest.mark.parametrize("list_name,makes_list", ALL_LISTS)
def test_no_duplicate_keys(list_name: str, makes_list: list[tuple[str, str, str]]) -> None:
    """Each list must not contain duplicate keys (first element of each tuple)."""
    keys = [entry[0] for entry in makes_list]
    duplicate_keys = [key for key in keys if keys.count(key) > 1]
    assert duplicate_keys == [], (
        f"{list_name} contains duplicate keys: {sorted(set(duplicate_keys))}"
    )


@pytest.mark.parametrize("list_name,makes_list", ALL_LISTS)
def test_all_tuples_have_three_non_empty_strings(
    list_name: str, makes_list: list[tuple[str, str, str]]
) -> None:
    """Every tuple must contain exactly three non-empty strings."""
    for entry in makes_list:
        assert len(entry) == 3, (
            f"{list_name}: tuple {entry!r} does not have exactly 3 elements"
        )
        for field in entry:
            assert isinstance(field, str) and field.strip() != "", (
                f"{list_name}: tuple {entry!r} contains an empty or non-string field"
            )


def test_cars_com_slugs_contain_no_hyphens() -> None:
    """Cars.com slugs (third element) must use underscores, not hyphens, for multi-word names."""
    slugs_with_hyphens = [
        entry[2] for entry in CARS_COM_MAKES if "-" in entry[2]
    ]
    assert slugs_with_hyphens == [], (
        f"CARS_COM_MAKES slugs must not contain hyphens; found: {slugs_with_hyphens}"
    )


def test_all_lists_have_same_keys() -> None:
    """BAT_MAKES, CAB_MAKES, and CARS_COM_MAKES must cover the same set of keys."""
    bat_keys = {entry[0] for entry in BAT_MAKES}
    cab_keys = {entry[0] for entry in CAB_MAKES}
    cars_com_keys = {entry[0] for entry in CARS_COM_MAKES}

    bat_vs_cab = bat_keys.symmetric_difference(cab_keys)
    assert bat_vs_cab == set(), (
        f"BAT_MAKES and CAB_MAKES differ in keys: {sorted(bat_vs_cab)}"
    )

    bat_vs_cars_com = bat_keys.symmetric_difference(cars_com_keys)
    assert bat_vs_cars_com == set(), (
        f"BAT_MAKES and CARS_COM_MAKES differ in keys: {sorted(bat_vs_cars_com)}"
    )
