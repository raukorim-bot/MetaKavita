"""Resolve catalogue volume/issue count via provider cascade + backup scrapers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from metadata_fetcher import throttle_provider
from scrapers import ScraperRegistry
from scrapers.utils import calculate_similarity
from secure_logging import safe_exc_str

from .series_identity import extract_provider_ids, merge_series_identity

# Providers that can return a volume/issue count and/or publication status.
_CATALOG_CAPABLE = frozenset({"ANILIST", "MAL", "COMICVINE"})

_ONGOING = frozenset({"RELEASING", "NOT_YET_RELEASED", "HIATUS"})
_PUB_STATUSES = frozenset(
    {"FINISHED", "RELEASING", "HIATUS", "CANCELLED", "NOT_YET_RELEASED", "UNKNOWN"}
)


def _int_or_none(val: Any) -> Optional[int]:
    try:
        n = int(val)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _norm_pub_status(raw: Any) -> str:
    if raw is None or raw == "":
        return "UNKNOWN"
    s = str(raw).strip().upper().replace(" ", "_")
    # MAL scraper mapping already uses FINISHED/RELEASING; AniList uses same enums.
    aliases = {
        "FINISHED_AIRING": "FINISHED",
        "FINISHED": "FINISHED",
        "COMPLETE": "FINISHED",
        "COMPLETED": "FINISHED",
        "RELEASING": "RELEASING",
        "CURRENTLY_PUBLISHING": "RELEASING",
        "PUBLISHING": "RELEASING",
        "ONGOING": "RELEASING",
        "NOT_YET_RELEASED": "NOT_YET_RELEASED",
        "NOT_YET_PUBLISHED": "NOT_YET_RELEASED",
        "HIATUS": "HIATUS",
        "CANCELLED": "CANCELLED",
        "CANCELED": "CANCELLED",
    }
    out = aliases.get(s, s if s in _PUB_STATUSES else "UNKNOWN")
    return out if out in _PUB_STATUSES else "UNKNOWN"


def _result(
    *,
    expected: Optional[int] = None,
    provider: Optional[str] = None,
    unit: str = "volumes",
    status: str = "unknown",
    provider_id: str = "",
    title: str = "",
    publication_status: str = "UNKNOWN",
    reason: str = "",
    source: str = "cascade",
    backup_from: str = "",
    expected_chapters: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "expected": expected,
        # C66 : attendu chapitres, seule unité exploitable pour les séries que
        # Kavita ne connaît qu'en chapitres (aucun tome numéroté sur disque).
        # AniList et MAL le renvoyaient déjà, il était simplement ignoré.
        "expected_chapters": expected_chapters,
        "provider": provider,
        "unit": unit,
        "status": status,
        "provider_id": provider_id or "",
        "title": title or "",
        "publication_status": _norm_pub_status(publication_status),
        "reason": reason or "",
        "source": source or "cascade",
        "backup_from": backup_from or "",
    }


def _throttle(scraper_id: str) -> Optional[Any]:
    scraper = ScraperRegistry.get(scraper_id)
    if scraper is None:
        return None
    try:
        throttle_provider(scraper)
    except Exception as e:
        logging.debug("throttle %s: %s", scraper_id, safe_exc_str(e))
    return scraper


def _anilist_volumes(
    media_id: Optional[str] = None, search: Optional[str] = None
) -> Dict[str, Any]:
    scraper = _throttle("ANILIST")
    if scraper is None:
        return _result(status="skipped", provider="ANILIST", reason="provider_skipped")
    if media_id and str(media_id).isdigit():
        query = """
        query ($id: Int) {
          Media(id: $id, type: MANGA) {
            id volumes chapters status
            title { romaji english }
          }
        }
        """
        variables = {"id": int(media_id)}
    elif search:
        query = """
        query ($search: String) {
          Media(search: $search, type: MANGA) {
            id volumes chapters status
            title { romaji english }
          }
        }
        """
        variables = {"search": search}
    else:
        return _result(status="unknown", provider="ANILIST", reason="no_id")
    try:
        res = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": variables},
            timeout=12,
        )
        if res.status_code != 200:
            return _result(status="error", provider="ANILIST", reason="provider_error")
        media = (res.json().get("data") or {}).get("Media") or {}
        if not media:
            return _result(status="unknown", provider="ANILIST", reason="no_id")
        title = (media.get("title") or {}).get("english") or (
            media.get("title") or {}
        ).get("romaji") or ""
        pub = _norm_pub_status(media.get("status"))
        if search and title:
            if calculate_similarity(search, title) < 0.85:
                return _result(
                    status="unknown",
                    provider="ANILIST",
                    title=title,
                    publication_status=pub,
                    reason="title_mismatch",
                )
        expected = _int_or_none(media.get("volumes"))
        expected_chapters = _int_or_none(media.get("chapters"))
        pid = str(media.get("id") or media_id or "")
        if expected is None:
            reason = "ongoing_no_count" if pub in _ONGOING else "volumes_null"
            return _result(
                status="unknown",
                provider="ANILIST",
                provider_id=pid,
                title=title,
                publication_status=pub,
                reason=reason,
                expected_chapters=expected_chapters,
            )
        return _result(
            expected=expected,
            provider="ANILIST",
            unit="volumes",
            status="ok",
            provider_id=pid,
            title=title,
            publication_status=pub,
            reason="ok",
            expected_chapters=expected_chapters,
        )
    except Exception as e:
        logging.warning("catalog AniList: %s", safe_exc_str(e))
        return _result(status="error", provider="ANILIST", reason="provider_error")


def _mal_volumes(manga_id: str) -> Dict[str, Any]:
    scraper = _throttle("MAL")
    if scraper is None:
        return _result(status="skipped", provider="MAL", reason="provider_skipped")
    client_id = None
    try:
        client_id = scraper._client_id()  # type: ignore[attr-defined]
    except Exception:
        client_id = None
    if not client_id:
        return _result(status="skipped", provider="MAL", reason="provider_skipped")
    try:
        node = scraper._get(  # type: ignore[attr-defined]
            f"/manga/{manga_id}",
            client_id,
            {"fields": "id,title,num_volumes,num_chapters,status"},
        )
        if not node:
            return _result(status="unknown", provider="MAL", reason="no_id")
        expected = _int_or_none(node.get("num_volumes"))
        expected_chapters = _int_or_none(node.get("num_chapters"))
        title = node.get("title") or ""
        # Prefer scraper mapping when available
        raw_status = node.get("status") or ""
        if hasattr(scraper, "_map_status"):
            try:
                pub = _norm_pub_status(scraper._map_status(raw_status))  # type: ignore[attr-defined]
            except Exception:
                pub = _norm_pub_status(raw_status)
        else:
            pub = _norm_pub_status(raw_status)
        pid = str(node.get("id") or manga_id)
        if expected is None:
            reason = "ongoing_no_count" if pub in _ONGOING else "volumes_null"
            return _result(
                status="unknown",
                provider="MAL",
                provider_id=pid,
                title=title,
                publication_status=pub,
                reason=reason,
                expected_chapters=expected_chapters,
            )
        return _result(
            expected=expected,
            provider="MAL",
            unit="volumes",
            status="ok",
            provider_id=pid,
            title=title,
            publication_status=pub,
            reason="ok",
            expected_chapters=expected_chapters,
        )
    except Exception as e:
        logging.warning("catalog MAL: %s", safe_exc_str(e))
        return _result(status="error", provider="MAL", reason="provider_error")


def _comicvine_issues(volume_id: str, api_key: str) -> Dict[str, Any]:
    scraper = _throttle("COMICVINE")
    if scraper is None:
        return _result(status="skipped", provider="COMICVINE", reason="provider_skipped")
    if not api_key:
        return _result(status="skipped", provider="COMICVINE", reason="provider_skipped")
    try:
        res = requests.get(
            f"https://comicvine.gamespot.com/api/volume/4050-{volume_id}/",
            params={
                "api_key": api_key,
                "format": "json",
                "field_list": "id,name,count_of_issues",
            },
            headers={"User-Agent": "MetaKavita"},
            timeout=15,
        )
        if res.status_code != 200:
            return _result(status="error", provider="COMICVINE", reason="provider_error")
        results = (res.json() or {}).get("results") or {}
        expected = _int_or_none(results.get("count_of_issues"))
        title = results.get("name") or ""
        pid = str(results.get("id") or volume_id)
        if expected is None:
            return _result(
                status="unknown",
                provider="COMICVINE",
                unit="issues",
                provider_id=pid,
                title=title,
                publication_status="UNKNOWN",
                reason="volumes_null",
            )
        return _result(
            expected=expected,
            provider="COMICVINE",
            unit="issues",
            status="ok",
            provider_id=pid,
            title=title,
            publication_status="UNKNOWN",
            reason="ok",
        )
    except Exception as e:
        logging.warning("catalog ComicVine: %s", safe_exc_str(e))
        return _result(status="error", provider="COMICVINE", reason="provider_error")


def _cascade_keys(library_type: str) -> List[str]:
    lib = (library_type or "Manga").strip()
    if lib in ("Comic", "ComicFlexible"):
        return ["COMIC_PROVIDER_1", "COMIC_PROVIDER_2", "COMIC_PROVIDER_3"]
    if lib == "Book":
        return ["BOOK_PROVIDER_1", "BOOK_PROVIDER_2", "BOOK_PROVIDER_3"]
    return ["PROVIDER_1", "PROVIDER_2", "PROVIDER_3"]


def _cascade_providers(config: dict, library_type: str) -> List[str]:
    """User cascade order (raw ids, including non-capable)."""
    raw = []
    for k in _cascade_keys(library_type):
        p = (config.get(k) or "").strip().upper()
        if p and p != "NONE":
            raw.append(p)
    # ComicFlexible: comic cascade then manga cascade (C35-aligned)
    if (library_type or "").strip() == "ComicFlexible":
        for k in ("PROVIDER_1", "PROVIDER_2", "PROVIDER_3"):
            p = (config.get(k) or "").strip().upper()
            if p and p != "NONE" and p not in raw:
                raw.append(p)
    return list(dict.fromkeys(raw))


def _backup_providers(library_type: str) -> List[str]:
    lib = (library_type or "Manga").strip()
    if lib in ("Comic", "ComicFlexible"):
        return ["COMICVINE", "ANILIST", "MAL"]
    return ["ANILIST", "MAL"]


def _call_provider(
    provider: str,
    *,
    ids: dict,
    name: str,
    config: dict,
    allow_title_search: bool,
) -> Dict[str, Any]:
    pid = provider.upper()
    if pid == "ANILIST":
        if ids.get("anilist"):
            return _anilist_volumes(media_id=ids["anilist"])
        if allow_title_search and name.strip():
            return _anilist_volumes(search=name.strip())
        return _result(status="unknown", provider="ANILIST", reason="no_id")
    if pid == "MAL":
        if ids.get("mal"):
            return _mal_volumes(ids["mal"])
        return _result(status="unknown", provider="MAL", reason="no_id")
    if pid == "COMICVINE":
        if ids.get("comicvine"):
            return _comicvine_issues(
                ids["comicvine"], config.get("COMICVINE_API_KEY") or ""
            )
        return _result(status="unknown", provider="COMICVINE", reason="no_id")
    return _result(status="skipped", provider=pid, reason="provider_skipped")


def _merge_pub(best: str, candidate: str) -> str:
    b = _norm_pub_status(best)
    c = _norm_pub_status(candidate)
    if b == "UNKNOWN" and c != "UNKNOWN":
        return c
    return b


def _finalize_unknown(
    *,
    pub: str,
    last_reason: str,
    provider: Optional[str],
    source: str,
    backup_from: str,
    expected_chapters: Optional[int] = None,
) -> Dict[str, Any]:
    pub = _norm_pub_status(pub)
    reason = last_reason or "no_id"
    if reason in ("", "ok") and pub in _ONGOING:
        reason = "ongoing_no_count"
    elif reason in ("", "ok"):
        reason = "volumes_null" if pub == "FINISHED" else (reason or "no_id")
    return _result(
        status="unknown",
        provider=provider,
        publication_status=pub,
        reason=reason,
        source=source,
        backup_from=backup_from,
        expected_chapters=expected_chapters,
    )


def resolve_catalog_expected(
    series: dict = None,
    *,
    library_type: str = "Manga",
    series_name: str = "",
    forced_id: str = "",
    forced_provider: str = "",
    config: Optional[dict] = None,
    metadata: Optional[dict] = None,
    identity: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Best-effort catalogue count following the user's enrichment cascade, then
    fixed backup scrapers if no expected count was found.
    """
    config = config or {}
    if identity is None:
        identity = merge_series_identity(
            series,
            metadata,
            forced_id=forced_id,
            forced_provider=forced_provider,
            series_name=series_name,
            library_type=library_type,
        )
    ids = identity.get("ids") or extract_provider_ids(
        series, metadata, forced_id=forced_id, forced_provider=forced_provider
    )
    lib = (identity.get("libraryType") or library_type or "Manga").strip()
    name = identity.get("name") or series_name or ""

    cascade = _cascade_providers(config, lib)
    tried: Set[str] = set()
    pub = "UNKNOWN"
    last_reason = "no_id"
    last_provider: Optional[str] = None
    # Premier compte chapitres rencontré : il survit à un attendu volumes absent,
    # c'est le seul repère des séries connues uniquement en chapitres.
    best_chapters: Optional[int] = None
    cascade_label = "→".join(cascade) if cascade else "(vide)"

    # Phase A — user cascade
    for prov in cascade:
        if prov not in _CATALOG_CAPABLE:
            logging.debug(
                "[Inventaire] skip %s (pas de compte volumes/statut)", prov
            )
            continue
        hit = _call_provider(
            prov,
            ids=ids,
            name=name,
            config=config,
            allow_title_search=(prov == "ANILIST" and not ids),
        )
        tried.add(prov)
        pub = _merge_pub(pub, hit.get("publication_status") or "UNKNOWN")
        last_reason = hit.get("reason") or last_reason
        last_provider = hit.get("provider") or prov
        if best_chapters is None:
            best_chapters = _int_or_none(hit.get("expected_chapters"))
        if hit.get("status") == "ok" and hit.get("expected"):
            out = dict(hit)
            out["publication_status"] = pub
            out["source"] = "cascade"
            out["backup_from"] = ""
            out["expected_chapters"] = _int_or_none(out.get("expected_chapters")) or best_chapters
            return out

    # Phase B — backup if still no expected
    backup_chain = [p for p in _backup_providers(lib) if p not in tried]
    if backup_chain:
        first_backup = backup_chain[0]
        logging.info(
            "[Inventaire] cascade %s (%s) n'a pas fourni d'attendu volumes "
            "pour « %s » — secours %s (chaîne: %s)",
            lib,
            cascade_label,
            name or "?",
            first_backup,
            "→".join(backup_chain),
        )
        for prov in backup_chain:
            hit = _call_provider(
                prov,
                ids=ids,
                name=name,
                config=config,
                allow_title_search=(prov == "ANILIST" and not ids),
            )
            tried.add(prov)
            pub = _merge_pub(pub, hit.get("publication_status") or "UNKNOWN")
            last_reason = hit.get("reason") or last_reason
            last_provider = hit.get("provider") or prov
            if best_chapters is None:
                best_chapters = _int_or_none(hit.get("expected_chapters"))
            if hit.get("status") == "ok" and hit.get("expected"):
                out = dict(hit)
                out["publication_status"] = pub
                out["source"] = "backup"
                out["backup_from"] = prov
                out["expected_chapters"] = (
                    _int_or_none(out.get("expected_chapters")) or best_chapters
                )
                logging.info(
                    "[Inventaire] secours %s a fourni l'attendu=%s pour « %s »",
                    prov,
                    out.get("expected"),
                    name or "?",
                )
                return out
    elif cascade:
        logging.info(
            "[Inventaire] cascade %s (%s) sans attendu pour « %s » — "
            "aucun secours restant (déjà tentés: %s)",
            lib,
            cascade_label,
            name or "?",
            "→".join(sorted(tried)) or "—",
        )

    return _finalize_unknown(
        pub=pub,
        last_reason=last_reason,
        provider=last_provider,
        source="backup" if any(p in tried for p in _backup_providers(lib)) else "cascade",
        backup_from="",
        expected_chapters=best_chapters,
    )


def apply_catalog_override(
    catalog: Optional[dict], override_expected: Optional[int]
) -> Dict[str, Any]:
    """Manual expected wins; keep scraped publication_status when present."""
    cat = dict(catalog or {})
    if override_expected is None:
        return cat
    try:
        n = int(override_expected)
    except (TypeError, ValueError):
        return cat
    if n < 1:
        return cat
    pub = cat.get("publication_status") or "UNKNOWN"
    cat.update(
        {
            "expected": n,
            "provider": "MANUAL",
            "status": "ok",
            "reason": "manual",
            "unit": cat.get("unit") or "volumes",
            "publication_status": _norm_pub_status(pub),
        }
    )
    return cat


def missing_volume_numbers(have_numbers: list, expected: Optional[int]) -> list:
    """Volumes/issues 1..expected absent from Kavita story numbers."""
    have = set()
    for n in have_numbers or []:
        try:
            i = int(float(n))
            if i > 0 and i < 100000:
                have.add(i)
        except (TypeError, ValueError):
            continue
    if not expected or expected < 1:
        return []
    return [i for i in range(1, int(expected) + 1) if i not in have]
