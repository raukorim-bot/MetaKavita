"""Merge Kavita series DTO + metadata + Meta overrides into one identity for hygiene."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .external_ids import _links_have_external, _truthy_id

_ANILIST_RE = re.compile(r"anilist\.co/(?:manga|anime)/(\d+)", re.I)
_MAL_RE = re.compile(r"myanimelist\.net/(?:manga|anime)/(\d+)", re.I)
_CV_RE = re.compile(r"comicvine\.gamespot\.com/.*?/(\d+)-(\d+)", re.I)
_MB_RE = re.compile(r"mangabaka\.(?:org|dev)/(?:series|manga)/([^/\s?#]+)", re.I)


def _weblinks_blob(obj: dict) -> str:
    links = obj.get("webLinks") or obj.get("WebLinks") or ""
    if isinstance(links, list):
        return " ".join(str(x) for x in links)
    return str(links or "")


def _collect_id_fields(obj: Optional[dict]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not obj or not isinstance(obj, dict):
        return out
    mapping = (
        ("aniListId", "anilist"),
        ("anilistId", "anilist"),
        ("malId", "mal"),
        ("mangaBakaId", "mangabaka"),
        ("googleBooksId", "googlebooks"),
        ("hardcoverId", "hardcover"),
        ("comicVineId", "comicvine"),
        ("openLibraryId", "openlibrary"),
    )
    for key, dest in mapping:
        if _truthy_id(obj.get(key)):
            out[dest] = str(obj.get(key)).strip()
    return out


def _ids_from_links(blob: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not blob:
        return out
    m = _ANILIST_RE.search(blob)
    if m:
        out["anilist"] = m.group(1)
    m = _MAL_RE.search(blob)
    if m:
        out["mal"] = m.group(1)
    m = _CV_RE.search(blob)
    if m:
        out["comicvine"] = m.group(2)
    m = _MB_RE.search(blob)
    if m:
        out["mangabaka"] = m.group(1)
    return out


def extract_provider_ids(
    *blobs: Optional[dict],
    forced_id: str = "",
    forced_provider: str = "",
) -> Dict[str, str]:
    """Collect provider ids from one or more series/metadata dicts + forced override."""
    out: Dict[str, str] = {}
    for obj in blobs:
        if not obj:
            continue
        for k, v in _collect_id_fields(obj).items():
            out.setdefault(k, v)
        for nest in ("metadata", "Metadata", "seriesMetadata", "SeriesMetadata"):
            nested = obj.get(nest) if isinstance(obj, dict) else None
            if isinstance(nested, dict):
                for k, v in _collect_id_fields(nested).items():
                    out.setdefault(k, v)
                for k, v in _ids_from_links(_weblinks_blob(nested)).items():
                    out.setdefault(k, v)
        for k, v in _ids_from_links(_weblinks_blob(obj)).items():
            out.setdefault(k, v)

    fp = (forced_provider or "").upper()
    fid = (forced_id or "").strip()
    if fid:
        if fp in ("ANILIST", "AL", "AUTO") and fid.isdigit():
            out.setdefault("anilist", fid)
        elif fp in ("MAL", "MYANIMELIST") and fid.isdigit():
            out.setdefault("mal", fid)
        elif fp in ("COMICVINE", "CV"):
            digits = re.sub(r"\D", "", fid)
            if digits:
                out.setdefault("comicvine", digits)
        elif fp in ("MANGABAKA", "MB"):
            out.setdefault("mangabaka", fid)
        elif fid.isdigit() and "anilist" not in out:
            out.setdefault("anilist", fid)
    return out


def _staff_from_metadata(meta: dict) -> List[dict]:
    """Best-effort staff list for score_candidate author checks."""
    staff: List[dict] = []
    people = meta.get("people") or meta.get("People") or []
    if isinstance(people, list):
        for p in people:
            if not isinstance(p, dict):
                continue
            name = (
                p.get("name")
                or p.get("Name")
                or (p.get("person") or {}).get("name")
                or ""
            )
            role = p.get("role") or p.get("Role") or "Writer"
            if name:
                staff.append({"role": str(role), "node": {"name": {"full": str(name)}}})
    writers = meta.get("writers") or meta.get("Writers") or []
    if isinstance(writers, list):
        for w in writers:
            name = w.get("name") if isinstance(w, dict) else str(w)
            if name:
                staff.append({"role": "Writer", "node": {"name": {"full": str(name)}}})
    return staff


def series_folder_path(series: Optional[dict]) -> str:
    """Chemin dossier Kavita (`folderPath`, sinon `lowestFolderPath`).

    `POST /api/Series/all-v2` le porte déjà : le scan Inventaire n'a pas d'appel
    en plus. Vide si Kavita n'a rien renseigné, ou si l'on n'a qu'un id.
    """
    if not isinstance(series, dict):
        return ""
    raw = series.get("raw_series") if isinstance(series.get("raw_series"), dict) else series
    for blob in (raw, series):
        if not isinstance(blob, dict):
            continue
        for key in (
            "folder_path",
            "folderPath",
            "FolderPath",
            "lowestFolderPath",
            "LowestFolderPath",
        ):
            val = blob.get(key)
            if val:
                path = str(val).strip()
                if path:
                    return path
    return ""


def merge_series_identity(
    series: Optional[dict] = None,
    metadata: Optional[dict] = None,
    *,
    forced_id: str = "",
    forced_provider: str = "",
    series_name: str = "",
    library_type: str = "Manga",
) -> Dict[str, Any]:
    """
    Single dict used by catalog count, external-id flags, and duplicate scoring.
    """
    series = series if isinstance(series, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    name = (
        series_name
        or series.get("name")
        or series.get("Name")
        or metadata.get("title")
        or metadata.get("Title")
        or ""
    )
    localized = (
        series.get("localizedName")
        or series.get("LocalizedName")
        or metadata.get("localizedName")
        or ""
    )
    ids = extract_provider_ids(
        series, metadata, forced_id=forced_id, forced_provider=forced_provider
    )
    web_blob = " ".join(
        filter(None, [_weblinks_blob(series), _weblinks_blob(metadata)])
    )
    genres = metadata.get("genres") or metadata.get("Genres") or []
    genre_names: List[str] = []
    if isinstance(genres, list):
        for g in genres:
            if isinstance(g, dict):
                label = g.get("title") or g.get("name") or ""
            else:
                label = g
            if label:
                genre_names.append(str(label))

    publishers = metadata.get("publishers") or metadata.get("Publishers") or []
    pub_name = ""
    if isinstance(publishers, list) and publishers:
        p0 = publishers[0]
        pub_name = p0.get("name") if isinstance(p0, dict) else str(p0)

    year = metadata.get("releaseYear") or metadata.get("ReleaseYear") or series.get("year")
    isbn = metadata.get("isbn") or series.get("isbn") or ""

    return {
        "id": series.get("id") or series.get("Id"),
        "name": name,
        "localizedName": localized or "",
        "libraryId": series.get("libraryId") or series.get("LibraryId"),
        "libraryType": library_type or series.get("libraryType") or "Manga",
        "folder_path": series_folder_path(series),
        "ids": ids,
        "webLinks": web_blob,
        "has_external_id": bool(ids) or _links_have_external(web_blob),
        # Flat id keys for legacy helpers
        "aniListId": ids.get("anilist"),
        "malId": ids.get("mal"),
        "mangaBakaId": ids.get("mangabaka"),
        "comicVineId": ids.get("comicvine"),
        "googleBooksId": ids.get("googlebooks"),
        "hardcoverId": ids.get("hardcover"),
        "openLibraryId": ids.get("openlibrary"),
        "publisher": pub_name,
        "year": year,
        "genres": genre_names,
        "isbn": str(isbn).strip() if isbn else "",
        "staff": _staff_from_metadata(metadata),
        "raw_series": series,
        "raw_metadata": metadata,
    }


def build_score_candidate_from_identity(identity: dict) -> dict:
    """Pseudo-candidate for score_candidate()."""
    alts = []
    loc = identity.get("localizedName") or ""
    if loc and loc != identity.get("name"):
        alts.append(loc)
    return {
        "title": identity.get("name") or "",
        "alternative_titles": alts,
        "staff": identity.get("staff") or [],
        "publisher": identity.get("publisher") or "",
        "year": identity.get("year"),
        "genres": identity.get("genres") or [],
        "tags": [],
        "isbn": identity.get("isbn") or "",
    }


def identity_has_external_id(identity: Optional[dict]) -> bool:
    if not identity:
        return False
    if identity.get("has_external_id"):
        return True
    return bool(identity.get("ids")) or _links_have_external(identity.get("webLinks") or "")
