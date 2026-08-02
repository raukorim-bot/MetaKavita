"""
Client Magasin : fetch `store/catalog.json` + install allowlisté (sha256).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from scrapers import ScraperRegistry
from services.scraper_manager import (
    delete_scraper_file,
    file_sha256,
    is_core_filename,
    normalize_scopes,
    read_file_bytes,
    resolve_origin,
    safe_scraper_path,
    sha256_matches,
    write_scraper_bytes,
)

CATALOG_URL = (
    "https://raw.githubusercontent.com/raukorim-bot/community-scraper-metakavita/"
    "main/store/catalog.json"
)
DEFAULT_RAW_BASE = (
    "https://raw.githubusercontent.com/raukorim-bot/community-scraper-metakavita/main"
)
ALLOWED_HOST = "raw.githubusercontent.com"
ALLOWED_REPO_PREFIX = "/raukorim-bot/community-scraper-metakavita/"

_RETIRED_STATUSES = frozenset({"retired", "deprecated", "archived", "dead", "unmaintained"})
_RETIRED_TAGS = frozenset({"retired", "deprecated", "archived", "dead", "unmaintained", "hors-usage"})

_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"fetched_at": 0.0, "catalog": None, "error": None}
_CACHE_TTL_SEC = 600  # 10 min


class StoreError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def is_entry_retired(entry: Dict[str, Any]) -> bool:
    """True si le catalogue marque le scraper hors d'usage (mort / non maintenu)."""
    if not isinstance(entry, dict):
        return False
    if entry.get("retired") is True:
        return True
    lifecycle = str(entry.get("lifecycle") or "").strip().lower()
    if lifecycle in _RETIRED_STATUSES:
        return True
    status = str(entry.get("status") or "").strip().lower()
    if status in _RETIRED_STATUSES:
        return True
    for tag in entry.get("tags") or []:
        if str(tag).strip().lower() in _RETIRED_TAGS:
            return True
    return False


def catalog_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Index catalogue : ids, fichiers, entrées retirées.
    Si catalog=None, tente le cache (sans lever si offline).
    """
    if catalog is None:
        try:
            catalog = fetch_catalog(force=False)
        except StoreError:
            return {"available": False, "ids": set(), "files": set(), "retired_ids": set(), "by_id": {}}

    ids: set = set()
    files: set = set()
    retired_ids: set = set()
    by_id: Dict[str, Dict[str, Any]] = {}
    for entry in (catalog or {}).get("scrapers") or []:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("id") or "").strip().upper()
        if not sid:
            continue
        file_name = os.path.basename(str(entry.get("file") or entry.get("install", {}).get("path") or ""))
        ids.add(sid)
        if file_name:
            files.add(file_name)
        by_id[sid] = entry
        if is_entry_retired(entry):
            retired_ids.add(sid)
    return {
        "available": True,
        "ids": ids,
        "files": files,
        "retired_ids": retired_ids,
        "by_id": by_id,
    }


def clear_catalog_cache() -> None:
    with _CACHE_LOCK:
        _CACHE["fetched_at"] = 0.0
        _CACHE["catalog"] = None
        _CACHE["error"] = None


def _validate_install_url(url: str, raw_base: str, expected_file: str) -> str:
    if not url or not isinstance(url, str):
        raise StoreError("missing install.url")
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() != ALLOWED_HOST:
        raise StoreError("install.url host not allowed")
    path = parsed.path or ""
    if not path.startswith(ALLOWED_REPO_PREFIX):
        raise StoreError("install.url repo not allowed")
    # Must be under /main/ (or the branch segment of raw_base)
    base = (raw_base or DEFAULT_RAW_BASE).rstrip("/")
    if not url.strip().startswith(base + "/"):
        raise StoreError("install.url outside catalog raw_base")
    basename = os.path.basename(path)
    if basename != os.path.basename(expected_file):
        raise StoreError("install.url filename mismatch")
    if not basename.endswith(".py") or basename.startswith("."):
        raise StoreError("invalid scraper file")
    return url.strip()


def fetch_catalog(*, force: bool = False) -> Dict[str, Any]:
    now = time.time()
    with _CACHE_LOCK:
        if (
            not force
            and _CACHE["catalog"] is not None
            and (now - float(_CACHE["fetched_at"] or 0)) < _CACHE_TTL_SEC
        ):
            return _CACHE["catalog"]

    try:
        res = requests.get(CATALOG_URL, timeout=20)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        logging.warning("[Store] Impossible de charger le catalogue : %s", e)
        with _CACHE_LOCK:
            _CACHE["error"] = str(e)
            if _CACHE["catalog"] is not None:
                return _CACHE["catalog"]
        raise StoreError("catalog unreachable", status_code=502)

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise StoreError("unsupported catalog schema_version", status_code=502)

    with _CACHE_LOCK:
        _CACHE["catalog"] = data
        _CACHE["fetched_at"] = now
        _CACHE["error"] = None
    return data


def _localize(obj: Any, lang: str) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        key = (lang or "fr").lower()[:2]
        return str(obj.get(key) or obj.get("en") or obj.get("fr") or "")
    return str(obj)


def _core_ids_from_registry() -> set:
    ids = set()
    for s in ScraperRegistry.get_all(include_disabled=True):
        src = ScraperRegistry.get_source_file(s.id)
        if src and is_core_filename(src):
            ids.add(s.id)
    return ids


def _installed_index() -> Dict[str, Dict[str, Any]]:
    """Index des scrapers installés par filename et par id."""
    by_file: Dict[str, Dict[str, Any]] = {}
    by_id: Dict[str, Dict[str, Any]] = {}

    for s in ScraperRegistry.get_all(include_disabled=True):
        src = ScraperRegistry.get_source_file(s.id) or ""
        if not src:
            continue
        path = safe_scraper_path(src)
        content = read_file_bytes(path) if path and os.path.isfile(path) else None
        row = {
            "id": s.id,
            "file": src,
            "origin": resolve_origin(src),
            "sha256": file_sha256(path) if path and os.path.isfile(path) else None,
            "content": content,
            "enabled": ScraperRegistry.get(s.id) is not None,
        }
        by_file[src] = row
        by_id[s.id] = row

    return {"by_file": by_file, "by_id": by_id}


def _resolve_local(installed: Dict[str, Dict[str, Any]], file_name: str, sid: str) -> Optional[Dict[str, Any]]:
    """Trouve l'install locale par fichier, par id, ou fichier présent hors registre."""
    by_file = installed["by_file"]
    by_id = installed["by_id"]
    if file_name and file_name in by_file:
        return by_file[file_name]
    if sid and sid in by_id:
        return by_id[sid]
    # Fichier présent sur disque mais pas (encore) chargé dans le registre
    if file_name:
        path = safe_scraper_path(file_name)
        if path and os.path.isfile(path):
            content = read_file_bytes(path)
            return {
                "id": sid,
                "file": file_name,
                "origin": resolve_origin(file_name),
                "sha256": file_sha256(path),
                "content": content,
                "enabled": False,
            }
    return None


def enrich_catalog_for_ui(catalog: Dict[str, Any], *, lang: str = "fr") -> Dict[str, Any]:
    installed = _installed_index()
    core_ids = _core_ids_from_registry()
    scrapers_out = []
    for entry in catalog.get("scrapers") or []:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("id") or "").strip().upper()
        file_name = os.path.basename(str(entry.get("file") or entry.get("install", {}).get("path") or ""))
        scopes = sorted(normalize_scopes(entry.get("scopes")))
        install = entry.get("install") or {}
        local = _resolve_local(installed, file_name, sid)
        is_core = bool(file_name and is_core_filename(file_name)) or sid in core_ids
        catalog_sha = (install.get("sha256") or "").strip().lower()
        local_content = (local or {}).get("content")
        # sha catalogue ≠ contenu local (EOL normalisés) → update disponible
        update_available = bool(
            local
            and not is_core
            and catalog_sha
            and local_content is not None
            and not sha256_matches(local_content, catalog_sha)
        )
        state = "available"
        if is_core:
            state = "core"
        elif local:
            state = "update" if update_available else "installed"

        quality = entry.get("quality") or {}
        retired = is_entry_retired(entry)
        raw_status = str(entry.get("status") or "untested").strip().lower() or "untested"
        status = "retired" if retired else raw_status
        scrapers_out.append({
            "id": sid,
            "file": file_name,
            "display_name": entry.get("display_name") or sid,
            "version": entry.get("version") or "",
            "supported_types": list(entry.get("supported_types") or []),
            "scopes": scopes,
            "status": status,
            "retired": retired,
            "needs_api_key": bool(entry.get("needs_api_key")),
            "auth": entry.get("auth") or {},
            "summary": _localize(entry.get("summary"), lang),
            "setup": _localize(entry.get("setup"), lang),
            "warnings": list(entry.get("warnings") or []),
            "tags": list(entry.get("tags") or []),
            "homepage": entry.get("homepage") or "",
            "docs": entry.get("docs") or "",
            "quality": {
                "grade": quality.get("grade"),
                "note": quality.get("note"),
                "covers_ok": quality.get("covers_ok"),
                "pick": _localize((quality.get("pick") or {}), lang),
                "audit_status": quality.get("audit_status"),
            },
            "install": {
                "path": install.get("path") or file_name,
                "url": install.get("url") or "",
                "sha256": catalog_sha,
                "bytes": install.get("bytes"),
            },
            "state": state,
            "update_available": update_available,
            "installed_file": (local or {}).get("file") or "",
            "installed_origin": (local or {}).get("origin"),
        })

    # Updates d'abord, puis grade A→E, puis nom (retirés en fin de bande)
    grade_rank = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    state_rank = {"update": 0, "available": 1, "installed": 2, "core": 3}

    def sort_key(row):
        g = (row.get("quality") or {}).get("grade") or "Z"
        note = (row.get("quality") or {}).get("note")
        try:
            note_v = -float(note)
        except (TypeError, ValueError):
            note_v = 0
        return (
            1 if row.get("retired") else 0,
            state_rank.get(row.get("state") or "", 9),
            grade_rank.get(g, 9),
            note_v,
            (row.get("display_name") or "").lower(),
        )

    scrapers_out.sort(key=sort_key)

    return {
        "schema_version": catalog.get("schema_version"),
        "name": catalog.get("name"),
        "description": _localize(catalog.get("description"), lang),
        "repo": catalog.get("repo") or "https://github.com/raukorim-bot/community-scraper-metakavita",
        "raw_base": catalog.get("raw_base") or DEFAULT_RAW_BASE,
        "generated_at": catalog.get("generated_at"),
        "install_notes": _localize(catalog.get("install_notes"), lang),
        "security": _localize(catalog.get("security"), lang),
        "scrapers": scrapers_out,
    }


def get_store_payload(*, lang: str = "fr", force: bool = False) -> Dict[str, Any]:
    catalog = fetch_catalog(force=force)
    return enrich_catalog_for_ui(catalog, lang=lang)


def install_from_catalog(scraper_id: str, *, force: bool = False) -> Dict[str, Any]:
    """
    Télécharge et installe un scraper du catalogue.
    force=True autorise l'overwrite d'un fichier community/custom existant.
    """
    sid = (scraper_id or "").strip().upper()
    if not sid:
        raise StoreError("missing scraper id")

    # Toujours recharger le catalogue avant install : le sha peut avoir changé.
    catalog = fetch_catalog(force=True)
    raw_base = catalog.get("raw_base") or DEFAULT_RAW_BASE
    entry = None
    for item in catalog.get("scrapers") or []:
        if isinstance(item, dict) and str(item.get("id") or "").strip().upper() == sid:
            entry = item
            break
    if entry is None:
        raise StoreError("scraper not in catalog", status_code=404)

    if is_entry_retired(entry):
        raise StoreError("scraper is retired (out of service)", status_code=403)

    install = entry.get("install") or {}
    file_name = os.path.basename(str(entry.get("file") or install.get("path") or ""))
    if not file_name.endswith(".py"):
        raise StoreError("invalid catalog file")
    if is_core_filename(file_name):
        raise StoreError("scraper is already core", status_code=403)

    dest = safe_scraper_path(file_name)
    if dest is None:
        raise StoreError("invalid scraper filename")

    # État local avant écriture (même id / même fichier)
    installed = _installed_index()
    local = _resolve_local(installed, file_name, sid)
    local_content = (local or {}).get("content")
    local_file = (local or {}).get("file") or ""
    dest_exists = os.path.isfile(dest)

    if dest_exists and not force:
        raise StoreError("already installed; pass force to reinstall", status_code=409)
    # Même id installé sous un autre nom → force requis pour éviter un doublon silencieux
    if local and local_file and local_file != file_name and not force:
        raise StoreError("already installed under another filename; pass force to update", status_code=409)

    url = _validate_install_url(install.get("url") or "", raw_base, file_name)
    expected_sha = (install.get("sha256") or "").strip().lower()
    if not expected_sha or len(expected_sha) != 64:
        raise StoreError("catalog entry missing install.sha256")

    was_update = bool(
        local
        and local_content is not None
        and expected_sha
        and not sha256_matches(local_content, expected_sha)
    )

    try:
        res = requests.get(url, timeout=45)
        res.raise_for_status()
        content = res.content
        ctype = (res.headers.get("Content-Type") or "").lower()
    except StoreError:
        raise
    except Exception as e:
        raise StoreError(f"download failed: {e}", status_code=502)

    # Refuse HTML / pages d'erreur GitHub déguisées
    if "text/html" in ctype or content.lstrip().startswith((b"<!DOCTYPE", b"<!doctype", b"<html")):
        raise StoreError("download did not return a Python file", status_code=502)

    if not sha256_matches(content, expected_sha):
        logging.warning(
            "[Store] sha256 mismatch for %s (got %s bytes, catalog expects %s)",
            sid,
            len(content),
            expected_sha[:12] + "…",
        )
        raise StoreError("sha256 mismatch", status_code=400)

    # Remplace le .py catalogue dans data/scrapers/
    write_scraper_bytes(file_name, content, origin="community")

    # Si l'ancien fichier avait un autre nom (même id), le retirer pour éviter un doublon
    if local_file and local_file != file_name and not is_core_filename(local_file):
        try:
            delete_scraper_file(local_file)
            logging.info("[Store] Ancien fichier %s retiré après update vers %s", local_file, file_name)
        except (PermissionError, ValueError, OSError) as e:
            logging.warning("[Store] Impossible de retirer l'ancien fichier %s : %s", local_file, e)

    ScraperRegistry.reload()

    scraper = ScraperRegistry.get(sid, include_disabled=True)
    action = "updated" if was_update else ("reinstalled" if (dest_exists or local) else "installed")
    return {
        "id": sid,
        "file": file_name,
        "sha256": expected_sha,
        "loaded": scraper is not None,
        "updated": action == "updated",
        "action": action,
        "scopes": sorted(scraper.normalized_scopes()) if scraper else sorted(normalize_scopes(entry.get("scopes"))),
    }
