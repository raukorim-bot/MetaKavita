"""Atelier des tomes : hydratation Kavita/Meta, envoi, Magic, journal, reset.

À l'ouverture : aucun scrape. Les cartes sont les unités de `units_from_volumes`.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from config_manager import get_disabled_library_ids, load_config
from db_manager import (
    clear_volume_unit_overrides,
    clear_volume_unit_states,
    clear_workshop_history,
    clear_workshop_series_override,
    delete_pending_by_series,
    get_all_cached_data,
    get_volume_unit_overrides,
    get_volume_unit_states,
    get_workshop_series_override,
    list_workshop_history,
    record_lifetime_event,
    record_run_origin,
    record_workshop_history,
    save_volume_unit_override,
    save_volume_unit_state,
    update_status,
)
from kavita_api import KavitaAPI
from services.kavita_payload import mark_cover_manual
from services.magic_input import (
    detect_volume_provider_from_url,
    extract_id_for_provider,
    is_http_url,
)
from services.volume_enrichment.apply import apply_entry
from services.volume_enrichment.index_cache import forget_series
from services.volume_enrichment.matching import (
    CHAPTER_KEY_PREFIX,
    INDEX_FIELDS,
    unmatchable_reason,
    unit_key,
    units_from_volumes,
)
from services.workshop_form import (
    apply_series_edits,
    chapter_extra_inscribed,
    lookups as workshop_lookups,
    series_form,
    unwrap_metadata,
)
from translations import translations

_COVER_KINDS = frozenset({"series", "chapter", "volume"})


def inscribed_from_chapter(chapter: Optional[dict]) -> Dict[str, Any]:
    """Champs d'un ChapterDto imbriqué, pour préremplir les inputs."""
    chap = chapter if isinstance(chapter, dict) else {}
    out = {
        "title": chap.get("titleName") or chap.get("title") or "",
        "summary": chap.get("summary") or "",
        "isbn": chap.get("isbn") or "",
        "release_date": chap.get("releaseDate") or "",
        "title_locked": bool(chap.get("titleNameLocked")),
        "summary_locked": bool(chap.get("summaryLocked")),
        "isbn_locked": bool(chap.get("isbnLocked")),
        "release_locked": bool(chap.get("releaseDateLocked")),
        "cover_locked": bool(chap.get("coverImageLocked")),
        "cover_image": chap.get("coverImage") or "",
    }
    out.update(chapter_extra_inscribed(chap))
    return out


def _merge_override_inscribed(inscribed: Dict[str, Any], override: Optional[dict]) -> Dict[str, Any]:
    """Le Champ Magique / Review gagne sur Kavita pour ce que le formulaire affiche."""
    payload = (override or {}).get("payload") if isinstance(override, dict) else None
    if not isinstance(payload, dict):
        return inscribed
    out = dict(inscribed)
    for field in ("title", "summary", "isbn", "release_date"):
        val = payload.get(field)
        if val:
            out[field] = val
    if payload.get("cover_url"):
        out["cover_url"] = payload["cover_url"]
    return out


def cover_etag(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "0"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def cover_url_for(kind: str, entity_id, cover_image: str = "") -> str:
    kind = str(kind or "chapter")
    if kind not in _COVER_KINDS:
        kind = "chapter"
    etag = cover_etag(cover_image)
    try:
        from flask import has_request_context, url_for

        if has_request_context():
            return url_for(
                "workshop.kavita_cover",
                kind=kind,
                entity_id=int(entity_id),
                v=etag,
            )
    except Exception:
        pass
    return f"/api/kavita-cover/{kind}/{int(entity_id)}?v={etag}"


def overlay_overrides(
    series_id: int,
    index: Optional[Dict[str, Any]],
    units: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """L'override gagne champ par champ sur l'index fournisseur."""
    merged = dict(index or {})
    overrides = get_volume_unit_overrides(series_id)
    if not overrides:
        return merged
    for unit in units or []:
        cid = int(unit.get("chapter_id") or 0)
        ov = overrides.get(cid)
        if not ov:
            continue
        payload = ov.get("payload") or {}
        if payload.get("_staged"):
            continue
        key = unit_key(unit) or f"{CHAPTER_KEY_PREFIX}{cid}"
        base = dict(merged.get(key) or {})
        for field in INDEX_FIELDS:
            if payload.get(field):
                base[field] = payload[field]
        if ov.get("provider_ref"):
            base["provider_ref"] = ov["provider_ref"]
        if ov.get("provider"):
            base["provider"] = ov["provider"]
        merged[key] = base
    return merged


def has_volume_overrides(series_id: int) -> bool:
    return bool(get_volume_unit_overrides(series_id))


def _pass_blocks(series_id: int) -> bool:
    """Vrai seulement si la passe auto est *sur cette série*.

    Une passe de bibliothèque sur une autre série ne doit pas geler l'atelier.
    Le `claim_series_write` rattrape le croisement si la passe arrive ici.
    """
    from services.volume_enrichment.job import get_volume_enrich_state

    state = get_volume_enrich_state()
    if not state.get("running"):
        return False
    current = state.get("series_id")
    if current in (None, "", False):
        return False
    try:
        return int(current) == int(series_id)
    except (TypeError, ValueError):
        return False


def workshop_payload(api: KavitaAPI, series_id: int, *, config: dict = None) -> Optional[Dict[str, Any]]:
    """Série + unités Kavita/Meta. Aucun scrape."""
    cfg = config if config is not None else load_config()
    series = api.get_series(series_id)
    if not isinstance(series, dict) or not series.get("id"):
        return None
    metadata = unwrap_metadata(api.get_series_metadata(series_id) or {})
    volumes = api.get_series_volumes(series_id) or []
    units = units_from_volumes(volumes)
    states = get_volume_unit_states(series_id)
    overrides = get_volume_unit_overrides(series_id)
    history = list_workshop_history(series_id)
    series_cover = cover_url_for("series", series_id, series.get("coverImage") or "")
    t = translations.get(cfg.get("UI_LANG", "fr"), translations["fr"])
    form = series_form(series, metadata, t)
    s_ov = get_workshop_series_override(series_id) or {}
    staged_payload = s_ov.get("payload") or {}
    staged_cover = str(s_ov.get("cover_url") or "")
    if staged_payload:
        for field in form:
            k = field.get("key")
            if k in staged_payload and staged_payload[k] is not None:
                field["value"] = staged_payload[k]
                field["staged"] = True
    cards = []
    for unit in units:
        chap = unit.get("chapter") if isinstance(unit.get("chapter"), dict) else {}
        inscribed = inscribed_from_chapter(chap)
        cid = int(unit.get("chapter_id") or 0)
        ov = overrides.get(cid) or {}
        inscribed = _merge_override_inscribed(inscribed, ov)
        staged_cover_unit = str((ov.get("payload") or {}).get("cover_url") or "")
        cards.append(
            {
                "chapter_id": cid,
                "volume_id": unit.get("volume_id"),
                "volume_number": unit.get("volume_number"),
                "chapter_number": unit.get("chapter_number"),
                "is_special": bool(unit.get("is_special")),
                "name": unit.get("name") or "",
                "inscribed": inscribed,
                "state": states.get(cid) or {},
                "override": ov,
                "cover_url": cover_url_for("chapter", cid, inscribed.get("cover_image") or ""),
                "staged_cover_url": staged_cover_unit,
                "checked": True,
            }
        )
    summary = ""
    if isinstance(metadata, dict):
        summary = metadata.get("summary") or ""
    reason = unmatchable_reason(units, series.get("name") or "")
    if reason and overrides:
        reason = ""
    return {
        "series": {
            "id": int(series["id"]),
            "name": series.get("name") or "",
            "localizedName": staged_payload.get("localizedName") or series.get("localizedName") or "",
            "libraryId": series.get("libraryId"),
            "libraryType": series.get("libraryType") or "",
            "summary": staged_payload.get("summary") or summary,
            "cover_url": staged_cover or series_cover,
            "staged_cover_url": staged_cover,
            "override": staged_payload,
            "coverImage": series.get("coverImage") or "",
            "year": series.get("year"),
            "form": form,
        },
        "lookups": workshop_lookups(t),
        "units": cards,
        "history": history,
        "force": True,
        "pass_running": _pass_blocks(series_id),
        "skipped_reason": reason,
    }


def workshop_rail(api: KavitaAPI, *, config: dict = None) -> List[Dict[str, Any]]:
    """Inventaire des séries (biblios désactivées exclues), pour le rail."""
    cfg = config if config is not None else load_config()
    disabled = {str(i) for i in get_disabled_library_ids(cfg)}
    series = api.get_all_series() or []
    cached = get_all_cached_data()
    rail = []
    for item in series:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        lib = str(item.get("libraryId") or "")
        if lib in disabled:
            continue
        cover = item.get("coverImage") or ""
        sid = item["id"]
        row = cached.get(sid) or {}
        rail.append(
            {
                "id": item["id"],
                "name": item.get("name") or "",
                "libraryId": item.get("libraryId"),
                "libraryName": item.get("libraryName") or "",
                "search": (item.get("name") or "").lower(),
                "status": row.get("status") or "PENDING",
                "cover_url": cover_url_for("series", sid, cover),
            }
        )
    rail.sort(key=lambda s: (s["name"] or "").casefold())
    return rail


def fetch_volume_from_url(url: str, volume_number=None) -> Optional[Dict[str, Any]]:
    provider = detect_volume_provider_from_url(url)
    if not provider:
        return None
    from scrapers import ScraperRegistry

    scraper = ScraperRegistry.get(provider)
    if not scraper or not callable(getattr(scraper, "fetch_volume", None)):
        return None
    extracted = extract_id_for_provider(provider, url) or url
    from services.provider_throttle import throttle_provider

    throttle_provider(scraper)
    payload = scraper.fetch_volume(
        extracted,
        volume_number=volume_number,
        existing_metadata={"url": url},
    )
    if isinstance(payload, dict):
        payload.setdefault("provider", provider)
        payload.setdefault("provider_ref", url)
        return payload
    return None


def save_magic_override(series_id: int, chapter_id: int, url: str, volume_number=None) -> Dict[str, Any]:
    payload = fetch_volume_from_url(url, volume_number=volume_number)
    if not payload:
        return {"success": False, "error": "no_match"}
    provider = payload.get("provider") or detect_volume_provider_from_url(url) or ""
    save_volume_unit_override(
        series_id,
        chapter_id,
        provider=provider,
        provider_ref=payload.get("provider_ref") or url,
        payload={k: payload.get(k) for k in INDEX_FIELDS if payload.get(k)},
    )
    record_lifetime_event("workshop_magic")
    record_workshop_history(
        series_id,
        "magic",
        chapter_id=chapter_id,
        detail={"provider": provider, "fields": [k for k in INDEX_FIELDS if payload.get(k)], "volume_number": volume_number},
    )
    return {"success": True, "provider": provider, "payload": payload}


def _entry_from_edits(chapter_id: int, edits: dict, cover_url: str = "", extra: dict = None) -> Dict[str, Any]:
    payload = dict(edits or {})
    if cover_url:
        payload["cover_url"] = cover_url
    entry = {
        "chapter_id": int(chapter_id),
        "changes": {
            field: {"proposed": payload[field], "write": True, "reason": "workshop"}
            for field in INDEX_FIELDS
            if payload.get(field)
        },
    }
    if extra:
        entry.update(extra)
    return entry


def _claim(series_id: int):
    from services.volume_enrichment.job import claim_series_write, release_series_write

    return claim_series_write(series_id), release_series_write


def send_volume(
    api: KavitaAPI,
    series_id: int,
    chapter_id: int,
    edits: dict,
    *,
    force: bool = False,
    cover_url: str = "",
    record_origin: bool = True,
    extra: dict = None,
    claim: bool = True,
) -> Dict[str, Any]:
    if _pass_blocks(series_id):
        return {"success": False, "error": "busy", "busy": True, "chapter_id": int(chapter_id)}
    release = lambda _sid: None
    if claim:
        claimed, release = _claim(series_id)
        if not claimed:
            return {
                "success": False,
                "error": "busy",
                "busy": True,
                "series_busy": True,
                "chapter_id": int(chapter_id),
            }
    try:
        ov = get_volume_unit_overrides(series_id).get(int(chapter_id)) or {}
        if not cover_url:
            cover_url = str((ov.get("payload") or {}).get("cover_url") or "")
        entry = _entry_from_edits(chapter_id, edits, cover_url, extra=extra)
        entry["edits"] = dict(edits or {})
        outcome = apply_entry(
            api,
            series_id,
            entry,
            force=force,
            origin="workshop",
        )
        status = outcome.get("status") or "SKIPPED"
        if status == "DONE":
            try:
                save_volume_unit_state(
                    series_id,
                    chapter_id,
                    "DONE",
                    volume_id=(extra or {}).get("volume_id"),
                    volume_number=(extra or {}).get("volume_number"),
                    chapter_number=(extra or {}).get("chapter_number"),
                    provider=str((ov.get("provider") or "")),
                    written_fields=outcome.get("written"),
                )
                if (ov.get("payload") or {}).get("_staged"):
                    clean_payload = {k: v for k, v in ov["payload"].items() if k != "_staged"}
                    save_volume_unit_override(
                        series_id,
                        chapter_id,
                        provider=str(ov.get("provider") or ""),
                        provider_ref=str(ov.get("provider_ref") or ""),
                        payload=clean_payload,
                    )
            except Exception:
                pass
            if record_origin:
                record_run_origin("workshop")
            if edits:
                record_lifetime_event("workshop_edits")
        noop = status in ("SKIPPED", "NOTHING_FOUND")
        return {
            "success": status == "DONE" or noop,
            "noop": noop,
            "status": status,
            "chapter_id": int(chapter_id),
            "written": outcome.get("written") or [],
            "error": outcome.get("error") or "",
        }
    finally:
        if claim:
            release(series_id)


def extract_external_ids_from_weblinks(
    weblinks: str,
    extra_ids: dict = None,
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Extrait (anilist_id, mal_id, mangabaka_id) depuis webLinks ou extra_ids."""
    anilist_id = (extra_ids or {}).get("anilist")
    mal_id = (extra_ids or {}).get("mal")
    mangabaka_id = (extra_ids or {}).get("mangabaka")

    tokens = [t.strip() for t in str(weblinks or "").replace("\n", ",").split(",") if t.strip()]
    for token in tokens:
        if not anilist_id:
            m = re.search(r"anilist\.co/manga/(\d+)", token, re.IGNORECASE)
            if m:
                anilist_id = m.group(1)
        if not mal_id:
            m = re.search(r"myanimelist\.net/manga/(\d+)", token, re.IGNORECASE)
            if m:
                mal_id = m.group(1)
        if not mangabaka_id:
            m = re.search(r"mangabaka\.(?:org|dev|com)/series/(\d+)", token, re.IGNORECASE)
            if m:
                mangabaka_id = m.group(1)

    def _clean(val):
        if val is None or val is False:
            return None
        try:
            v = int(str(val).strip())
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    return _clean(anilist_id), _clean(mal_id), _clean(mangabaka_id)


def send_series(
    api: KavitaAPI,
    series_id: int,
    edits: dict,
    *,
    force: bool = False,
    cover_url: str = "",
) -> Dict[str, Any]:
    if _pass_blocks(series_id):
        return {"success": False, "error": "busy", "busy": True}
    claimed, release = _claim(series_id)
    if not claimed:
        return {"success": False, "error": "busy", "busy": True, "series_busy": True}
    try:
        raw_meta = api.get_series_metadata(series_id)
        if raw_meta is None:
            return {"success": False, "error": "series-read-failed"}
        metadata = unwrap_metadata(raw_meta)
        series = api.get_series(series_id) or {}
        edits = edits or {}
        cfg = load_config()
        t = translations.get(cfg.get("UI_LANG", "fr"), translations["fr"])
        form = series_form(series, metadata, t)
        meta, written, localized = apply_series_edits(
            metadata, series, form, edits, force=force
        )

        if any(key != "localizedName" for key in written):
            result = api.update_series_metadata(meta)
            ok = result[0] if isinstance(result, tuple) else bool(result)
            detail = result[1] if isinstance(result, tuple) and len(result) > 1 else ""
            if not ok:
                return {"success": False, "error": detail, "written": []}

        if localized is not None:
            ok, detail = api.update_series_general(series_id, localized_name=localized)
            if not ok:
                already = [w for w in written if w != "localizedName"]
                return {
                    "success": False,
                    "partial": bool(already),
                    "written": already,
                    "error": detail,
                }

        if cover_url and is_http_url(cover_url):
            ok, detail = api.upload_series_cover(series_id, cover_url)
            if not ok:
                return {
                    "success": False,
                    "partial": bool(written),
                    "written": written,
                    "error": detail,
                }
            written.append("cover")
            mark_cover_manual(series_id)

        # IDs Externes (AniList, MyAnimeList, MangaBaka)
        s_ov = get_workshop_series_override(series_id) or {}
        extra_ids = (s_ov.get("payload") or {}).get("_external_ids")
        links = edits.get("webLinks") if "webLinks" in edits else metadata.get("webLinks") or ""
        a_id, m_id, mb_id = extract_external_ids_from_weblinks(links, extra_ids=extra_ids)
        if a_id or m_id or mb_id:
            try:
                ids_res = api.update_series_external_ids(
                    series_id, anilist_id=a_id, mal_id=m_id, mangabaka_id=mb_id
                )
                ids_ok = ids_res[0] if isinstance(ids_res, tuple) else bool(ids_res)
                if ids_ok:
                    written.append("externalIds")
            except Exception:
                pass

        if not written:
            return {"success": True, "noop": True, "written": []}

        # Consomme et efface le brouillon persistant après envoi réussi
        clear_workshop_series_override(series_id)

        # Met à jour le statut en COMPLETED et purge les reviews pendantes de la série
        try:
            from services.enrichment_engine import _emit_series_status
            from services.manual_review import emit_pending_count

            update_status(series_id, "COMPLETED")
            deleted = delete_pending_by_series(series_id)
            if deleted:
                emit_pending_count()
            _emit_series_status(series_id, "COMPLETED", series.get("name") or "")
        except Exception:
            pass

        record_run_origin("workshop")
        record_workshop_history(
            series_id,
            "send-series",
            detail={"fields": written},
        )
        return {"success": True, "written": written}
    finally:
        release(series_id)


def send_selection(
    api: KavitaAPI,
    series_id: int,
    items: List[Dict[str, Any]],
    *,
    force: bool = False,
) -> Dict[str, Any]:
    if _pass_blocks(series_id):
        return {"success": False, "error": "busy", "busy": True}
    claimed, release = _claim(series_id)
    if not claimed:
        return {"success": False, "error": "busy", "busy": True, "series_busy": True}
    results = []
    try:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            cid = item.get("chapter_id")
            if cid is None:
                continue
            outcome = send_volume(
                api,
                series_id,
                int(cid),
                item.get("edits") or {},
                force=force,
                cover_url=str(item.get("cover_url") or ""),
                extra={
                    "volume_id": item.get("volume_id"),
                    "volume_number": item.get("volume_number"),
                    "chapter_number": item.get("chapter_number"),
                },
                claim=False,
                record_origin=False,
            )
            results.append(outcome)
        dones = sum(1 for r in results if r.get("status") == "DONE")
        record_run_origin("workshop")
        if dones:
            record_workshop_history(
                series_id,
                "send-selection",
                detail={"count": dones, "chapters": [r["chapter_id"] for r in results if r.get("status") == "DONE"]},
            )
        failed = [r for r in results if not r.get("success")]
        sent = sum(1 for r in results if r.get("status") == "DONE")
        if failed:
            return {
                "success": False,
                "partial": sent > 0,
                "sent": sent,
                "total": len(results),
                "results": results,
                "error": failed[0].get("error") or "",
            }
        return {
            "success": True,
            "noop": sent == 0,
            "sent": sent,
            "total": len(results),
            "results": results,
        }
    finally:
        release(series_id)


def reset_workshop(api: KavitaAPI, series_id: int, chapter_id=None) -> Dict[str, Any]:
    """Efface Meta (overrides, historique, cache de passe, index) et relit Kavita.

    N'écrit pas dans Kavita.
    """
    if chapter_id is None:
        clear_workshop_series_override(series_id)
        clear_volume_unit_overrides(series_id)
        clear_workshop_history(series_id)
        clear_volume_unit_states(series_id)
        forgotten = forget_series(series_id)
    else:
        clear_volume_unit_overrides(series_id, chapter_id)
        clear_workshop_history(series_id, chapter_id)
        clear_volume_unit_states(series_id, chapter_id=chapter_id)
        forgotten = 0
    record_lifetime_event("workshop_resets")
    record_workshop_history(
        series_id,
        "reset",
        chapter_id=chapter_id,
        detail={"source": "reset"},
    )
    payload = workshop_payload(api, series_id)
    return {
        "success": True,
        "index_forgotten": forgotten,
        "payload": payload,
    }


def _dedupe_candidates(raw: List[dict]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("provider_ref") or ""),
            str(item.get("isbn") or ""),
            str(item.get("title") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def begin_volume_review(
    api: KavitaAPI,
    series_id: int,
    chapter_id: int,
    *,
    super_review: bool = False,
    config: dict = None,
) -> Dict[str, Any]:
    """Candidats tome (ISBN / URL / titre+numéro). Pas de PENDING_REVIEW série."""
    cfg = config if config is not None else load_config()
    volumes = api.get_series_volumes(series_id) or []
    units = [
        u for u in units_from_volumes(volumes) if int(u.get("chapter_id") or 0) == int(chapter_id)
    ]
    if not units:
        return {"success": False, "error": "not_found"}
    unit = units[0]
    series = api.get_series(series_id) or {}
    name = series.get("name") or ""
    candidates: List[dict] = []
    ov = get_volume_unit_overrides(series_id).get(int(chapter_id)) or {}
    ref = ov.get("provider_ref") or ""
    if is_http_url(ref):
        hit = fetch_volume_from_url(ref, volume_number=unit.get("volume_number"))
        if hit:
            candidates.append(hit)
    isbn = (unit.get("chapter") or {}).get("isbn") or (ov.get("payload") or {}).get("isbn")
    if isbn:
        from services.volume_enrichment.providers import fetch_by_isbn

        search_unit = dict(unit)
        search_unit["isbn"] = str(isbn).strip()
        if isinstance(search_unit.get("chapter"), dict):
            chap = dict(search_unit["chapter"])
            chap["isbn"] = str(isbn).strip()
            search_unit["chapter"] = chap
        extra = fetch_by_isbn(
            [search_unit],
            library_type=series.get("libraryType") or "Manga",
            config=cfg,
        )
        for payload in (extra or {}).values():
            if isinstance(payload, dict):
                candidates.append(payload)
    if super_review or cfg.get("VOLUME_ENRICH_EXPERIMENTAL"):
        from services.volume_enrichment.providers import fetch_by_title_volume

        extra = fetch_by_title_volume(
            name,
            [unit],
            library_type=series.get("libraryType") or "Manga",
        )
        for payload in (extra or {}).values():
            if isinstance(payload, dict):
                candidates.append(payload)
    record_lifetime_event("workshop_reviews")
    return {
        "success": True,
        "kind": "volume",
        "chapter_id": int(chapter_id),
        "series_id": series_id,
        "series_name": name,
        "candidates": _dedupe_candidates(candidates)[:12],
        "super": bool(super_review),
    }


def confirm_volume_review(
    api: KavitaAPI,
    series_id: int,
    chapter_id: int,
    candidate: dict,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Pose le candidat sur la carte atelier. Kavita n'est écrit qu'à l'envoi.

    ``api`` / ``force`` restent pour le contrat d'appel de la route ; le
    staging n'écrit pas et n'honore pas ``force``.
    """
    del api, force
    cand = candidate if isinstance(candidate, dict) else {}
    edits = {
        field: cand.get(field)
        for field in INDEX_FIELDS
        if field != "cover_url" and cand.get(field)
    }
    cover = str(cand.get("cover_url") or "")
    payload = {k: cand.get(k) for k in INDEX_FIELDS if cand.get(k)}
    if payload or cand.get("provider") or cand.get("provider_ref"):
        payload["_staged"] = True
        payload["_source"] = "review"
        save_volume_unit_override(
            series_id,
            chapter_id,
            provider=str(cand.get("provider") or ""),
            provider_ref=str(cand.get("provider_ref") or ""),
            payload=payload,
        )
    fields = list(edits.keys())
    if cover:
        fields.append("cover")
    record_workshop_history(
        series_id,
        "review",
        chapter_id=int(chapter_id),
        detail={
            "fields": fields,
            "provider": cand.get("provider") or "",
        },
    )
    return {
        "success": True,
        "staged": True,
        "chapter_id": int(chapter_id),
        "edits": edits,
        "cover_url": cover,
    }


def library_is_disabled(series: dict, config: dict) -> bool:
    lib = str((series or {}).get("libraryId") or "")
    return lib in {str(i) for i in get_disabled_library_ids(config)}
