"""Cars & Bids scraper target selection."""

GLOBAL_CAB_ENTRY: tuple[str, str, str] = ("all", "All closed auctions", "")


def get_all_url_keys() -> list[str]:
    return [GLOBAL_CAB_ENTRY[0]]


def get_url_entries() -> list[dict[str, str]]:
    key, label, query = GLOBAL_CAB_ENTRY
    return [{"key": key, "label": label, "query": query}]


def select_entries(selected_keys: set[str] | None) -> list[tuple[str, str, str]]:
    if selected_keys is None:
        return [GLOBAL_CAB_ENTRY]
    if "all" in selected_keys:
        return [GLOBAL_CAB_ENTRY]
    return []
