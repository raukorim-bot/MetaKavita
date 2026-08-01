"""
Diagnostic manuel des scrapers et préflight (Internet + Kavita).

Aucune modification des scrapers : on appelle fetch / fetch_covers tels quels,
avec URLs de reachability et queries known-good centralisées ici.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from config_manager import load_config
from kavita_api import KavitaAPI
from metadata_fetcher import throttle_provider
from scrapers import ScraperRegistry
from scrapers.base import BaseScraper
from secure_logging import safe_exc_str

# Queries known-good (alignées sur debug/debug_all.py)
TEST_CASES: Dict[str, Dict[str, Any]] = {
    "Manga": {
        "query": "Berserk",
        "context": {"authors": ["Kentaro Miura"], "isbn": None, "year": 1989},
    },
    "Comic": {
        "query": "Lanfeust de Troy",
        "context": {"authors": ["Arleston"], "isbn": None, "year": 1994},
    },
    "Book": {
        "query": "Dune",
        "context": {"authors": ["Frank Herbert"], "isbn": None, "year": 1965},
    },
}

# Overrides par scraper.
# Scrapers à scoring unifié (Google Books, Open Library, Hardcover…) : NE PAS
# tester via search+score_candidate. Health-check = lookup direct (is_id) +
# cover_url du même record.
SCRAPER_PROBE_CASES: Dict[str, Dict[str, Any]] = {
    "GOOGLEBOOKS": {
        "library_type": "Book",
        # Volume ID stable : Le petit prince (Houghton Mifflin Harcourt)
        "query": "elZSm9GK66IC",
        "is_id": True,
        "context": {},
    },
    "OPENLIBRARY": {
        "library_type": "Book",
        # Work ID stable : Le petit prince (openlibrary.org/works/OL10263W)
        "query": "OL10263W",
        "is_id": True,
        "context": {},
    },
    "HARDCOVER": {
        "library_type": "Book",
        # Slug stable : The Little Prince (hardcover.app/books/the-little-prince)
        "query": "the-little-prince",
        "is_id": True,
        "context": {},
    },
}

# Reachability endpoints (hors scrapers/)
PROBE_URLS: Dict[str, str] = {
    "ANILIST": "https://graphql.anilist.co",
    "MANGADEX": "https://api.mangadex.org",
    "KITSU": "https://kitsu.io/api/edge/manga",
    "MANGABAKA": "https://api.mangabaka.org",
    "MANGAUPDATES": "https://api.mangaupdates.com/v1/series/search",
    "MANGANEWS": "https://www.manga-news.com/",
    "SHIKIMORI": "https://shikimori.one/api/mangas",
    "MAL": "https://api.myanimelist.net/v2",
    "BEDETHEQUE": "https://www.bedetheque.com/",
    "BDTHEQUE": "https://www.bdtheque.com/",
    "COMICVINE": "https://comicvine.gamespot.com/api/",
    "GOOGLEBOOKS": "https://www.googleapis.com/books/v1/volumes",
    "OPENLIBRARY": "https://openlibrary.org/search.json",
    "HARDCOVER": "https://api.hardcover.app/v1/graphql",
    "WIKIDATA": "https://www.wikidata.org/w/api.php",
}

_EXPECTED_FIELDS = ("summary", "cover_url", "genres", "tags", "year", "staff")
_CAUSE_SEVERITY = {
    "network": 100,
    "ban": 90,
    "schema": 80,
    "covers_schema": 70,
    "partial": 40,
    "auth_missing": 10,
    "ok": 0,
}

_INTERNET_PRIMARY = "https://www.google.com/generate_204"
_INTERNET_FALLBACK = "https://www.google.com"
_UA = "MetaKavita-Diagnostics/1.0"


def _ms_since(start: float) -> int:
    return int(round((time.time() - start) * 1000))


def _classify_http_exception(exc: BaseException) -> Tuple[str, str]:
    """Retourne (cause, detail_code) pour une erreur réseau."""
    if isinstance(exc, requests.exceptions.Timeout):
        return "network", "timeout"
    if isinstance(exc, requests.exceptions.SSLError):
        return "network", "ssl"
    if isinstance(exc, requests.exceptions.ConnectionError):
        msg = safe_exc_str(exc).lower()
        if any(x in msg for x in ("name or service not known", "nodename nor servname", "getaddrinfo", "failed to resolve")):
            return "network", "dns"
        return "network", "connection"
    return "network", "unknown"


def _status_from_http_code(code: Optional[int], *, ignore_auth_bans: bool = False) -> Optional[str]:
    """
    Classifie un code HTTP pour la reachability.
    Sur les scrapers à clé API, un GET nu sans credentials renvoie souvent
    401/403 (parfois 429) alors que fetch() authentifié fonctionne — on ignore
    alors ces codes et on laisse le vrai fetch décider.
    """
    if code is None:
        return None
    if code in (401, 403, 429):
        if ignore_auth_bans:
            return None
        return "ban"
    if code >= 500:
        return "network"
    return None


def probe_internet(timeout: float = 5.0) -> Dict[str, Any]:
    """Ping Internet via generate_204, fallback google.com."""
    start = time.time()
    headers = {"User-Agent": _UA}

    def _try(url: str, expect_204: bool = False) -> Dict[str, Any]:
        try:
            res = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            latency = _ms_since(start)
            ok = (expect_204 and res.status_code == 204) or (200 <= res.status_code < 400)
            if ok:
                return {
                    "status": "ok",
                    "cause": "ok",
                    "latency_ms": latency,
                    "http_status": res.status_code,
                    "detail": "ok",
                    "url": url,
                }
            ban = _status_from_http_code(res.status_code)
            return {
                "status": "down",
                "cause": ban or "network",
                "latency_ms": latency,
                "http_status": res.status_code,
                "detail": "http_error",
                "url": url,
            }
        except Exception as e:
            cause, detail = _classify_http_exception(e)
            return {
                "status": "down",
                "cause": cause,
                "latency_ms": _ms_since(start),
                "http_status": None,
                "detail": detail,
                "url": url,
            }

    primary = _try(_INTERNET_PRIMARY, expect_204=True)
    if primary["status"] == "ok":
        return primary
    # generate_204 parfois bloqué / réécrit → fallback page d'accueil
    fallback = _try(_INTERNET_FALLBACK, expect_204=False)
    if fallback["status"] == "ok":
        fallback["detail"] = "ok_fallback"
        return fallback
    return primary if primary.get("detail") != "unknown" else fallback


def probe_kavita(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Auth Kavita + comptage des bibliothèques si OK."""
    config = config if config is not None else load_config()
    start = time.time()
    url = (config.get("KAVITA_URL") or "").strip()
    key = (config.get("KAVITA_API_KEY") or "").strip()

    if not url or not key:
        return {
            "status": "down",
            "cause": "auth_missing",
            "latency_ms": _ms_since(start),
            "detail": "missing",
            "library_count": 0,
            "kavita_url_host": "",
        }

    host = ""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""

    kavita = KavitaAPI(url, key)
    ok = kavita.authenticate()
    latency = _ms_since(start)
    if not ok:
        err = getattr(kavita, "last_auth_error", None) or "unknown"
        cause = "auth_missing" if err == "missing" else "network"
        if err in ("http_401",):
            cause = "ban"
        return {
            "status": "down",
            "cause": cause,
            "latency_ms": latency,
            "detail": err,
            "library_count": 0,
            "kavita_url_host": host,
        }

    libs = kavita.get_libraries() or []
    return {
        "status": "ok",
        "cause": "ok",
        "latency_ms": _ms_since(start),
        "detail": "ok",
        "library_count": len(libs),
        "kavita_url_host": host,
    }


def run_preflight(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = config if config is not None else load_config()
    return {
        "internet": probe_internet(),
        "kavita": probe_kavita(config),
    }


def _resolve_probe_url(scraper: BaseScraper) -> Optional[str]:
    url = PROBE_URLS.get(scraper.id)
    if url:
        return url
    domains = getattr(scraper, "proxy_domains", None) or []
    if domains:
        d = domains[0]
        if d.startswith("http"):
            return d
        return f"https://{d}"
    return None


def _pick_library_type(scraper: BaseScraper) -> str:
    override = SCRAPER_PROBE_CASES.get(scraper.id)
    if override and override.get("library_type") in (scraper.supported_types or set()):
        return override["library_type"]
    types = getattr(scraper, "supported_types", set()) or set()
    # Book avant Comic : les scrapers Book+Comic (Google Books, OpenLibrary…)
    # doivent sonder un roman known-good, pas une BD FR mal scorée.
    for preferred in ("Manga", "Book", "Comic"):
        if preferred in types:
            return preferred
    return "Manga"


def _resolve_test_case(scraper: BaseScraper, lib_type: str) -> Dict[str, Any]:
    override = SCRAPER_PROBE_CASES.get(scraper.id)
    if override and override.get("query"):
        return {
            "query": override["query"],
            "context": dict(override.get("context") or {}),
            "is_id": bool(override.get("is_id")),
        }
    base = TEST_CASES.get(lib_type, TEST_CASES["Manga"])
    return {
        "query": base["query"],
        "context": dict(base.get("context") or {}),
        "is_id": False,
    }


def _googlebooks_smoke(config: Dict[str, Any], timeout: float = 12.0) -> Dict[str, Any]:
    """
    Smoke Google Books via volumes.get (même volume ID que le probe is_id).

    Soft only : un 5xx ponctuel ne court-circuite pas fetch()/covers.
    """
    start = time.time()
    api_key = (config.get("GOOGLEBOOKS_API_KEY") or "").strip()
    volume_id = (SCRAPER_PROBE_CASES.get("GOOGLEBOOKS") or {}).get("query") or "elZSm9GK66IC"
    # `country` contourne un bug de géolocalisation IP connu côté Google Books.
    # Voir scrapers/googlebooks.py::DEFAULT_COUNTRY.
    params: Dict[str, Any] = {"country": "US"}
    if api_key:
        params["key"] = api_key
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    try:
        res = requests.get(
            f"https://www.googleapis.com/books/v1/volumes/{volume_id}",
            params=params,
            headers=headers,
            timeout=timeout,
        )
        latency = _ms_since(start)
        code = res.status_code
        body: Dict[str, Any] = {}
        try:
            body = res.json() if res.content else {}
        except Exception:
            body = {}

        if code == 200:
            title = (body.get("volumeInfo") or {}).get("title")
            if title:
                return {
                    "ok": True,
                    "cause": "ok",
                    "http_status": code,
                    "latency_ms": latency,
                    "detail": "ok",
                }
            err = (body.get("error") or {}).get("message")
            return {
                "ok": False,
                "cause": "schema",
                "http_status": code,
                "latency_ms": latency,
                "detail": err or "missing_title",
            }

        err_msg = ""
        if isinstance(body.get("error"), dict):
            err_msg = str(body["error"].get("message") or "")[:120]

        if code in (401, 403):
            return {
                "ok": False,
                "cause": "ban",
                "http_status": code,
                "latency_ms": latency,
                "detail": err_msg or ("ban" if api_key else "auth_required"),
            }
        if code == 429:
            return {
                "ok": False,
                "cause": "ban",
                "http_status": code,
                "latency_ms": latency,
                "detail": err_msg or "ban",
            }
        if code >= 500:
            return {
                "ok": False,
                "cause": "network",
                "http_status": code,
                "latency_ms": latency,
                "detail": err_msg or "http_5xx",
            }
        return {
            "ok": False,
            "cause": "schema",
            "http_status": code,
            "latency_ms": latency,
            "detail": err_msg or f"http_{code}",
        }
    except Exception as e:
        cause, detail = _classify_http_exception(e)
        return {
            "ok": False,
            "cause": cause,
            "http_status": None,
            "latency_ms": _ms_since(start),
            "detail": detail,
        }


def _has_api_key(scraper: BaseScraper, config: Dict[str, Any]) -> bool:
    if not getattr(scraper, "needs_api_key", False):
        return True
    return bool((config.get(f"{scraper.id}_API_KEY") or "").strip())


def _supports_covers(scraper: BaseScraper) -> bool:
    return type(scraper).fetch_covers is not BaseScraper.fetch_covers


def _field_present(data: Dict[str, Any], field: str) -> bool:
    val = data.get(field)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, (list, dict)):
        return bool(val)
    if isinstance(val, bool):
        return True
    return True


def _analyze_metadata(result: Any) -> Dict[str, Any]:
    if result is None:
        return {
            "status": "down",
            "cause": "schema",
            "sample_title": None,
            "fields_ok": [],
            "fields_missing": ["title"],
            "detail": "none",
        }
    if isinstance(result, list):
        return {
            "status": "down",
            "cause": "schema",
            "sample_title": None,
            "fields_ok": [],
            "fields_missing": ["title"],
            "detail": "list_instead_of_dict",
        }
    if not isinstance(result, dict):
        return {
            "status": "down",
            "cause": "schema",
            "sample_title": None,
            "fields_ok": [],
            "fields_missing": ["title"],
            "detail": f"unexpected_type:{type(result).__name__}",
        }

    title = result.get("title")
    fields_ok: List[str] = []
    fields_missing: List[str] = []
    if _field_present(result, "title"):
        fields_ok.append("title")
    else:
        fields_missing.append("title")

    # genres OU tags compte comme un seul « slot » attendu
    expected_hits = 0
    for field in _EXPECTED_FIELDS:
        if field == "tags":
            continue
        if field == "genres":
            present = _field_present(result, "genres") or _field_present(result, "tags")
            label = "genres" if _field_present(result, "genres") else ("tags" if _field_present(result, "tags") else "genres")
            if present:
                fields_ok.append(label)
                expected_hits += 1
            else:
                fields_missing.append("genres/tags")
            continue
        if _field_present(result, field):
            fields_ok.append(field)
            expected_hits += 1
        else:
            fields_missing.append(field)

    sample = str(title).strip() if title else None
    if "title" in fields_missing:
        return {
            "status": "down",
            "cause": "schema",
            "sample_title": sample,
            "fields_ok": fields_ok,
            "fields_missing": fields_missing,
            "detail": "missing_title",
        }
    if expected_hits >= 2:
        return {
            "status": "ok",
            "cause": "ok",
            "sample_title": sample,
            "fields_ok": fields_ok,
            "fields_missing": fields_missing,
            "detail": "ok",
        }
    return {
        "status": "degraded",
        "cause": "partial",
        "sample_title": sample,
        "fields_ok": fields_ok,
        "fields_missing": fields_missing,
        "detail": "partial_fields",
    }


def _analyze_covers(raw: Any, supported: bool) -> Dict[str, Any]:
    if not supported:
        return {
            "status": "n_a",
            "cause": "ok",
            "count": 0,
            "sample_url": None,
            "detail": "not_implemented",
        }
    if raw is None or not isinstance(raw, list):
        return {
            "status": "down",
            "cause": "covers_schema",
            "count": 0,
            "sample_url": None,
            "detail": "invalid_list",
        }
    valid = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        if url:
            valid.append(url)
    if not valid:
        return {
            "status": "down",
            "cause": "covers_schema",
            "count": 0,
            "sample_url": None,
            "detail": "empty",
        }
    return {
        "status": "ok",
        "cause": "ok",
        "count": len(valid),
        "sample_url": valid[0],
        "detail": "ok",
    }


def _worse_cause(a: str, b: str) -> str:
    return a if _CAUSE_SEVERITY.get(a, 0) >= _CAUSE_SEVERITY.get(b, 0) else b


def _combine(meta: Dict[str, Any], covers: Dict[str, Any]) -> Tuple[str, str]:
    """Retourne (status global, cause dominante)."""
    m_st = meta["status"]
    c_st = covers["status"]
    m_cause = meta.get("cause") or "schema"
    c_cause = covers.get("cause") or "covers_schema"

    if c_st == "n_a":
        if m_st == "ok":
            return "ok", "ok"
        if m_st == "degraded":
            return "degraded", m_cause
        return "down", m_cause

    if m_st == "ok" and c_st == "ok":
        return "ok", "ok"
    if m_st == "down" and c_st == "down":
        return "down", _worse_cause(m_cause, c_cause)
    if m_st == "ok" and c_st == "down":
        return "degraded", c_cause
    if m_st == "down" and c_st == "ok":
        return "degraded", m_cause
    # degraded + anything
    return "degraded", _worse_cause(m_cause if m_st != "ok" else "ok", c_cause if c_st != "ok" else "ok")


def _probe_reachability(url: str, timeout: float = 10.0, *, needs_api_key: bool = False) -> Dict[str, Any]:
    """
    Sonde HTTP légère. Pour les scrapers à clé API, un GET nu sans credentials
    (Google Books, MAL, ComicVine…) renvoie souvent 401/403 : ce n'est PAS un
    ban — le fetch() authentifié reste la source de vérité.
    """
    start = time.time()
    headers = {"User-Agent": _UA, "Accept": "*/*"}
    try:
        res = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        try:
            res.close()
        except Exception:
            pass
        latency = _ms_since(start)
        ban_or_net = _status_from_http_code(
            res.status_code,
            ignore_auth_bans=needs_api_key,
        )
        if ban_or_net == "ban":
            return {
                "ok": False,
                "status": "down",
                "cause": "ban",
                "http_status": res.status_code,
                "latency_ms": latency,
                "detail": "ban",
            }
        if ban_or_net == "network":
            return {
                "ok": False,
                "status": "down",
                "cause": "network",
                "http_status": res.status_code,
                "latency_ms": latency,
                "detail": "http_5xx",
            }
        # 2xx / 3xx / 4xx non-ban (y compris 401/403/429 si needs_api_key) → joignable
        return {
            "ok": True,
            "status": "ok",
            "cause": "ok",
            "http_status": res.status_code,
            "latency_ms": latency,
            "detail": "ok",
        }
    except Exception as e:
        cause, detail = _classify_http_exception(e)
        return {
            "ok": False,
            "status": "down",
            "cause": cause,
            "http_status": None,
            "latency_ms": _ms_since(start),
            "detail": detail,
        }


def list_scrapers_inventory(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Inventaire léger pour peupler le tableau sans sonder."""
    config = config if config is not None else load_config()
    rows = []
    for scraper in ScraperRegistry.get_all():
        rows.append({
            "id": scraper.id,
            "display_name": scraper.localized_display_name,
            "supported_types": sorted(scraper.supported_types or []),
            "needs_api_key": bool(getattr(scraper, "needs_api_key", False)),
            "has_api_key": _has_api_key(scraper, config),
            "supports_covers": _supports_covers(scraper),
            "rate_limit": float(getattr(scraper, "rate_limit", 1.0) or 1.0),
        })
    rows.sort(key=lambda r: (r["display_name"] or r["id"]).lower())
    return rows


def probe_scraper(scraper_or_id: Any, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Probe un scraper : reachability + fetch + fetch_covers."""
    config = config if config is not None else load_config()
    if isinstance(scraper_or_id, str):
        scraper = ScraperRegistry.get(scraper_or_id)
        if scraper is None:
            return {
                "id": scraper_or_id,
                "display_name": scraper_or_id,
                "status": "down",
                "cause": "schema",
                "latency_ms": 0,
                "http_status": None,
                "detail": "unknown_scraper",
                "library_type": None,
                "metadata": {"status": "down", "sample_title": None, "fields_ok": [], "fields_missing": []},
                "covers": {"status": "n_a", "count": 0, "sample_url": None},
            }
    else:
        scraper = scraper_or_id

    start = time.time()
    lib_type = _pick_library_type(scraper)
    test_case = _resolve_test_case(scraper, lib_type)
    base = {
        "id": scraper.id,
        "display_name": scraper.localized_display_name,
        "library_type": lib_type,
        "supported_types": sorted(scraper.supported_types or []),
    }

    if not _has_api_key(scraper, config):
        return {
            **base,
            "status": "skipped",
            "cause": "auth_missing",
            "latency_ms": _ms_since(start),
            "http_status": None,
            "detail": "api_key_missing",
            "metadata": {
                "status": "skipped",
                "sample_title": None,
                "fields_ok": [],
                "fields_missing": [],
                "detail": "api_key_missing",
            },
            "covers": {"status": "n_a", "count": 0, "sample_url": None, "detail": "skipped"},
        }

    http_status = None
    soft_reach: Optional[Dict[str, Any]] = None

    if scraper.id == "GOOGLEBOOKS":
        # Smoke soft uniquement : un 5xx Google ne doit PAS empêcher fetch()/covers,
        # qui sont le même chemin que l'enrichissement réel.
        soft_reach = _googlebooks_smoke(config)
        http_status = soft_reach.get("http_status")
        # Ban clair avec clé (401/403/429) → down immédiat, inutile d'insister.
        if (
            not soft_reach.get("ok")
            and soft_reach.get("cause") == "ban"
            and bool((config.get("GOOGLEBOOKS_API_KEY") or "").strip())
        ):
            return {
                **base,
                "status": "down",
                "cause": "ban",
                "latency_ms": _ms_since(start),
                "http_status": http_status,
                "detail": soft_reach.get("detail") or "ban",
                "metadata": {
                    "status": "down",
                    "sample_title": None,
                    "fields_ok": [],
                    "fields_missing": ["title"],
                    "detail": soft_reach.get("detail"),
                },
                "covers": {
                    "status": "down" if _supports_covers(scraper) else "n_a",
                    "count": 0,
                    "sample_url": None,
                    "detail": soft_reach.get("detail"),
                },
            }
    else:
        probe_url = _resolve_probe_url(scraper)
        if probe_url:
            reach = _probe_reachability(
                probe_url,
                needs_api_key=bool(getattr(scraper, "needs_api_key", False)),
            )
            http_status = reach.get("http_status")
            if not reach.get("ok"):
                return {
                    **base,
                    "status": "down",
                    "cause": reach["cause"],
                    "latency_ms": _ms_since(start),
                    "http_status": http_status,
                    "detail": reach.get("detail") or reach["cause"],
                    "metadata": {
                        "status": "down",
                        "sample_title": None,
                        "fields_ok": [],
                        "fields_missing": ["title"],
                        "detail": reach.get("detail"),
                    },
                    "covers": {
                        "status": "down" if _supports_covers(scraper) else "n_a",
                        "count": 0,
                        "sample_url": None,
                        "detail": reach.get("detail"),
                    },
                }

    # --- fetch metadata ---
    meta_info: Dict[str, Any]
    meta_raw: Any = None
    try:
        throttle_provider(scraper)
        fetch_ctx = dict(test_case.get("context") or {})
        meta_raw = scraper.fetch(
            query=test_case["query"],
            library_type=lib_type,
            is_id=bool(test_case.get("is_id")),
            existing_metadata=fetch_ctx,
        )
        meta_info = _analyze_metadata(meta_raw)
    except Exception as e:
        if isinstance(e, requests.exceptions.RequestException):
            cause, detail = _classify_http_exception(e)
        else:
            cause, detail = "schema", safe_exc_str(e)[:120]
        meta_info = {
            "status": "down",
            "cause": cause,
            "sample_title": None,
            "fields_ok": [],
            "fields_missing": ["title"],
            "detail": detail,
        }

    # --- fetch covers ---
    supports = _supports_covers(scraper)
    covers_info: Dict[str, Any]
    if not supports:
        covers_info = _analyze_covers([], False)
    else:
        try:
            # Probe is_id : cover depuis le même record (cover_url).
            # fetch_covers(title) repasse par search — hors sujet pour un health-check.
            if test_case.get("is_id"):
                cover_url = (meta_raw or {}).get("cover_url") if isinstance(meta_raw, dict) else None
                if cover_url:
                    covers_raw = [{
                        "provider": scraper.localized_display_name or scraper.id,
                        "title": (meta_raw or {}).get("title") or "",
                        "url": cover_url,
                    }]
                else:
                    covers_raw = []
            else:
                throttle_provider(scraper)
                covers_raw = scraper.fetch_covers(test_case["query"], library_type=lib_type)
            covers_info = _analyze_covers(covers_raw, True)
        except Exception as e:
            if isinstance(e, requests.exceptions.RequestException):
                cause, detail = _classify_http_exception(e)
            else:
                cause, detail = "covers_schema", safe_exc_str(e)[:120]
            covers_info = {
                "status": "down",
                "cause": cause if cause in ("network", "ban") else "covers_schema",
                "count": 0,
                "sample_url": None,
                "detail": detail,
            }

    # Si metadata a crashé en network/ban, propager
    if meta_info.get("cause") == "network":
        global_status, global_cause = "down", "network"
    elif meta_info.get("cause") == "ban":
        global_status, global_cause = "down", "ban"
    else:
        global_status, global_cause = _combine(meta_info, covers_info)

    # Google Books : si fetch+covers ont échoué mais le smoke avait une cause claire,
    # préférer cette cause (ex. network 5xx) plutôt qu'un faux « schema ».
    if (
        scraper.id == "GOOGLEBOOKS"
        and global_status == "down"
        and global_cause == "schema"
        and soft_reach
        and not soft_reach.get("ok")
        and soft_reach.get("cause") in ("network", "ban")
    ):
        global_cause = soft_reach["cause"]

    detail_parts = []
    if meta_info.get("detail") and meta_info["detail"] not in ("ok",):
        detail_parts.append(f"meta:{meta_info['detail']}")
    if covers_info.get("detail") and covers_info["detail"] not in ("ok", "not_implemented"):
        detail_parts.append(f"covers:{covers_info['detail']}")
    if soft_reach and not soft_reach.get("ok") and soft_reach.get("detail"):
        detail_parts.append(f"smoke:{soft_reach['detail']}")
    detail = "; ".join(detail_parts) if detail_parts else "ok"

    return {
        **base,
        "status": global_status,
        "cause": global_cause,
        "latency_ms": _ms_since(start),
        "http_status": http_status,
        "detail": detail,
        "metadata": {
            "status": meta_info["status"],
            "sample_title": meta_info.get("sample_title"),
            "fields_ok": meta_info.get("fields_ok") or [],
            "fields_missing": meta_info.get("fields_missing") or [],
            "detail": meta_info.get("detail"),
        },
        "covers": {
            "status": covers_info["status"],
            "count": covers_info.get("count") or 0,
            "sample_url": covers_info.get("sample_url"),
            "detail": covers_info.get("detail"),
        },
    }


def probe_all(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Probe séquentiel de tous les scrapers enregistrés."""
    config = config if config is not None else load_config()
    results = []
    for scraper in ScraperRegistry.get_all():
        try:
            results.append(probe_scraper(scraper, config))
        except Exception as e:
            logging.error("[Diagnostics] Échec probe %s : %s", scraper.id, safe_exc_str(e))
            results.append({
                "id": scraper.id,
                "display_name": scraper.localized_display_name,
                "status": "down",
                "cause": "schema",
                "latency_ms": 0,
                "http_status": None,
                "detail": safe_exc_str(e)[:160],
                "library_type": _pick_library_type(scraper),
                "supported_types": sorted(scraper.supported_types or []),
                "metadata": {
                    "status": "down",
                    "sample_title": None,
                    "fields_ok": [],
                    "fields_missing": [],
                },
                "covers": {"status": "n_a", "count": 0, "sample_url": None},
            })
    results.sort(key=lambda r: (r.get("display_name") or r.get("id") or "").lower())
    return results
