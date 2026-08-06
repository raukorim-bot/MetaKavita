"""
Magic Input helpers: URL → provider detection and cover-query resolution.

Import rules (acyclic): may use ScraperRegistry + stdlib only.
Must NOT import enrichment_engine, cover_search, metadata_fetcher, routes, sockets, or app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from scrapers import ScraperRegistry


def is_http_url(value: Any) -> bool:
    s = str(value or "").strip()
    return s.startswith("http://") or s.startswith("https://")


def detect_provider_from_url(url: str) -> Optional[str]:
    """
    First series scraper whose extract_id_from_url accepts *url* wins.
    Same order as enrichment_engine AUTO URL detection.
    """
    raw = str(url or "").strip()
    if not is_http_url(raw):
        return None
    for scraper in ScraperRegistry.get_all(scope="series"):
        try:
            if scraper.extract_id_from_url(raw):
                return scraper.id
        except Exception:
            continue
    return None


def extract_id_for_provider(provider_id: str, raw: str) -> Optional[str]:
    """Extract ID for a specific provider; for non-URLs return the raw string."""
    scraper = ScraperRegistry.get(provider_id)
    if not scraper:
        return None
    text = str(raw or "").strip()
    if not text:
        return None
    if is_http_url(text):
        try:
            return scraper.extract_id_from_url(text) or None
        except Exception:
            return None
    return text


@dataclass(frozen=True)
class MagicCoverQuery:
    magic_active: bool
    forced_id: Optional[str]
    resolved_provider: Optional[str]
    id_query: Optional[str]
    title_query: str
    is_url: bool
    raw_id_auto: bool


def resolve_magic_cover_query(
    cache_data: Optional[Dict[str, Any]],
    series_name: str,
) -> MagicCoverQuery:
    """
    Resolve Magic Input fields for cover search.

    title_query is never the forced_id / URL — only alternative_title || series_name.
    """
    cache = cache_data or {}
    forced_id = (cache.get("forced_id") or "").strip() or None
    forced_provider = (cache.get("forced_provider") or "AUTO").strip() or "AUTO"
    alt = (cache.get("alternative_title") or "").strip()
    name = (series_name or "").strip()
    title_query = alt or name

    if not forced_id:
        return MagicCoverQuery(
            magic_active=False,
            forced_id=None,
            resolved_provider=None,
            id_query=None,
            title_query=title_query,
            is_url=False,
            raw_id_auto=False,
        )

    url = is_http_url(forced_id)
    resolved = forced_provider if forced_provider != "AUTO" else None
    id_query: Optional[str] = None
    raw_id_auto = False

    if url:
        if resolved:
            id_query = extract_id_for_provider(resolved, forced_id)
            if not id_query:
                resolved = None
        else:
            detected = detect_provider_from_url(forced_id)
            if detected:
                resolved = detected
                id_query = extract_id_for_provider(detected, forced_id)
    else:
        if resolved:
            id_query = forced_id
        else:
            # Raw ID + AUTO → Smart ID style on ID-capable scrapers
            raw_id_auto = True
            id_query = forced_id

    return MagicCoverQuery(
        magic_active=True,
        forced_id=forced_id,
        resolved_provider=resolved,
        id_query=id_query,
        title_query=title_query,
        is_url=url,
        raw_id_auto=raw_id_auto,
    )
