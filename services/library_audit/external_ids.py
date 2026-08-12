"""Detect Kavita / Meta external id presence (AniList, MAL, …)."""

from __future__ import annotations

from typing import Any, Dict, Optional

# SeriesDto / metadata fields Kavita may expose
_ID_KEYS = (
    "aniListId",
    "anilistId",
    "malId",
    "mangaBakaId",
    "googleBooksId",
    "hardcoverId",
    "comicVineId",
    "openLibraryId",
)


def _truthy_id(val: Any) -> bool:
    if val is None or val is False:
        return False
    if isinstance(val, (int, float)):
        return int(val) != 0
    s = str(val).strip()
    return bool(s) and s not in ("0", "None", "null")


def _links_have_external(links: Any) -> bool:
    if isinstance(links, list):
        links = ",".join(str(x) for x in links)
    links_l = str(links or "").lower()
    markers = (
        "anilist.co",
        "myanimelist.net",
        "mangaupdates.com",
        "comicvine.gamespot.com",
        "mangadex.org",
        "hardcover.app",
        "openlibrary.org",
        "books.google",
        "manga-news.com",
        "bedetheque.com",
    )
    return any(m in links_l for m in markers)


def _scan_id_blob(obj: Optional[Dict[str, Any]]) -> bool:
    if not obj or not isinstance(obj, dict):
        return False
    # Prefer merged identity if present
    if "ids" in obj or "has_external_id" in obj:
        if obj.get("has_external_id"):
            return True
        if obj.get("ids"):
            return True
    for key in _ID_KEYS:
        if _truthy_id(obj.get(key)):
            return True
    for nest in ("metadata", "Metadata", "seriesMetadata", "SeriesMetadata"):
        nested = obj.get(nest)
        if isinstance(nested, dict):
            for key in _ID_KEYS:
                if _truthy_id(nested.get(key)):
                    return True
            links = nested.get("webLinks") or nested.get("WebLinks") or ""
            if _links_have_external(links):
                return True
    links = obj.get("webLinks") or obj.get("WebLinks") or ""
    return _links_have_external(links)


def series_has_external_id(series: Optional[Dict[str, Any]]) -> bool:
    """True if the series dict (or merged identity) carries at least one usable external id."""
    return _scan_id_blob(series)
