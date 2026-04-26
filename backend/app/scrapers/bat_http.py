"""Bring a Trailer HTTP primitives."""

import httpx

from app.scrapers.bat_config import _HEADERS, BASE_URL, LISTINGS_FILTER_URL
from app.scrapers.bat_list_parser import (
    extract_completed_metadata_from_html,
    extract_items_from_html,
)


async def fetch_page(client: httpx.AsyncClient, url_path: str) -> list[dict]:
    items, _metadata = await fetch_page_result(client, url_path)
    return items


async def fetch_page_result(client: httpx.AsyncClient, url_path: str) -> tuple[list[dict], dict]:
    url = f"{BASE_URL}/{url_path}/"
    resp = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return extract_items_from_html(resp.text), extract_completed_metadata_from_html(resp.text)


def build_completed_results_params(
    base_filter: dict,
    *,
    page: int,
    per_page: int,
) -> list[tuple[str, object]]:
    params: list[tuple[str, object]] = [
        ("page", page),
        ("per_page", per_page),
        ("get_items", 1),
        ("get_stats", 0),
        ("sort", "td"),
    ]
    for key, value in base_filter.items():
        if value is None:
            continue
        if isinstance(value, list):
            params.extend((f"base_filter[{key}][]", item) for item in value)
            continue
        params.append((f"base_filter[{key}]", value))
    return params


async def fetch_completed_results_page(
    client: httpx.AsyncClient,
    *,
    base_filter: dict,
    page: int,
    per_page: int,
    referer_url: str,
) -> tuple[list[dict], dict]:
    resp = await client.get(
        LISTINGS_FILTER_URL,
        params=build_completed_results_params(base_filter, page=page, per_page=per_page),
        headers={**_HEADERS, "Referer": referer_url},
        follow_redirects=True,
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", []), {
        "items_total": data.get("items_total"),
        "items_per_page": data.get("items_per_page"),
        "page_current": data.get("page_current"),
        "pages_total": data.get("pages_total"),
    }


async def fetch_detail_html(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return resp.text
