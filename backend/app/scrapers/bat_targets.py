"""Bring a Trailer model-directory target discovery."""

import re
from html import unescape

import httpx

from app.scrapers.bat_config import _HEADERS, BASE_URL, MODELS_URL
from app.scrapers.makes import BAT_MAKES

_MODEL_LINK_RE = re.compile(
    r'<a[^>]+class="[^"]*previous-listing-image-link[^"]*"[^>]+href="([^"]+)"[^>]*>.*?'
    r'<img[^>]+alt="([^"]*)"',
    re.DOTALL,
)
_EXCLUDED_MODEL_PATH_PARTS = {
    "motorcycle",
    "motorcycles",
    "trailer",
    "motorhome",
    "rv",
    "tractor",
    "boat",
    "aircraft",
    "go-kart",
    "minibike",
    "scooter",
    "wheel",
    "wheels",
    "parts",
    "side-by-side",
    "atv",
    "airstream",
    "ajs",
}
_EXCLUDED_MODEL_LABEL_TERMS = {
    "motorcycle",
    "trailer",
    "motorhome",
    "rv",
    "camper",
    "tractor",
    "boat",
    "aircraft",
    "go-kart",
    "minibike",
    "scooter",
    "wheel",
    "wheels",
    "parts",
    "side-by-side",
}
_EXCLUDED_MODEL_LABELS = {"ajs", "airstream"}


def get_all_url_keys() -> list[str]:
    return [key for key, _, _ in BAT_MAKES]


def get_url_entries() -> list[dict[str, str]]:
    return [{"key": key, "label": label, "path": slug} for key, label, slug in BAT_MAKES]


def extract_model_entries_from_html(html: str) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    seen_paths: set[str] = set()
    for href, label in _MODEL_LINK_RE.findall(html):
        path = href.replace(BASE_URL, "").strip("/")
        if not path or path in seen_paths:
            continue
        lowered_path = path.lower()
        lowered_label = unescape(label).strip().lower()
        if any(part in lowered_path for part in _EXCLUDED_MODEL_PATH_PARTS):
            continue
        if lowered_label in _EXCLUDED_MODEL_LABELS:
            continue
        if any(term in lowered_label for term in _EXCLUDED_MODEL_LABEL_TERMS):
            continue
        seen_paths.add(path)
        key = lowered_path.replace("/", "-")
        entries.append((key, unescape(label).strip(), path))
    return entries


async def fetch_model_entries(client: httpx.AsyncClient) -> list[tuple[str, str, str]]:
    resp = await client.get(MODELS_URL, headers=_HEADERS, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return extract_model_entries_from_html(resp.text)
