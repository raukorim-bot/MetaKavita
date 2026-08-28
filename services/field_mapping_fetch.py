"""C88 — fetch mapping (HTTP + assemblage)."""
from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional, Tuple

from metadata_fetcher import apply_explicit_label_age, call_scraper, fetch_metadata
from scrapers import ScraperRegistry
from scrapers.utils import get_match_accept_threshold
from services.field_assembly import (
    absorb_identity,
    assemble_field_picks,
    pick_assembly_base,
    source_from_scraper_data,
)
from services.field_mapping import CASCADE, map_to_field_picks
from services.magic_input import is_http_url

_PROVIDER_OWN_ID = {
    "ANILIST": "anilist_id",
    "MAL": "mal_id",
    "MANGABAKA": "mangabaka_id",
}


def title_from_hit(blob: Optional[dict]) -> str:
    if not isinstance(blob, dict):
        return ""
    for key in ("title", "localized_name"):
        val = blob.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _blob_useful(blob: dict) -> bool:
    return bool(
        blob.get("summary")
        or blob.get("genres")
        or blob.get("cover_url")
        or blob.get("staff")
        or blob.get("year")
    )


def blob_accepted_for_auto(blob, config) -> bool:
    """Utile et score ≥ seuil Auto (même seuil que fetch_metadata)."""
    if not isinstance(blob, dict) or not _blob_useful(blob):
        return False
    from metadata_fetcher import _safe_match_score

    score = _safe_match_score(blob)
    return score >= get_match_accept_threshold(config)


def _blob_urls(blob: dict):
    urls = []
    raw = blob.get("url")
    if is_http_url(raw):
        urls.append(str(raw).strip())
    for item in blob.get("links") or []:
        if is_http_url(item):
            urls.append(str(item).strip())
    for item in blob.get("external_links") or []:
        if isinstance(item, dict) and is_http_url(item.get("url")):
            urls.append(str(item.get("url")).strip())
        elif is_http_url(item):
            urls.append(str(item).strip())
    return urls


def override_fetch_args(
    *,
    is_forced_id: bool,
    magic_query: str,
    hit_blob: Optional[dict],
    target_provider: str,
) -> Tuple[str, bool]:
    """
    Pas ID : (titre série, False).
    ID : URL / id croisé du hit pour CE provider → is_id=True ;
    sinon (title_from_hit, False). Jamais l'ID MAL brut vers AniList.
    """
    hit = hit_blob if isinstance(hit_blob, dict) else {}
    title = title_from_hit(hit)
    if not is_forced_id:
        query = (magic_query or "").strip() or title
        return query, False

    scraper = ScraperRegistry.get(target_provider)
    raw_magic = (magic_query or "").strip()
    if scraper:
        if is_http_url(raw_magic):
            try:
                extracted = scraper.extract_id_from_url(raw_magic)
            except Exception:
                extracted = None
            if extracted:
                return str(extracted), True
        for url in _blob_urls(hit):
            try:
                extracted = scraper.extract_id_from_url(url)
            except Exception:
                extracted = None
            if extracted:
                return str(extracted), True
        own_key = _PROVIDER_OWN_ID.get(str(target_provider or "").upper())
        if own_key and hit.get(own_key) not in (None, ""):
            return str(hit[own_key]), True
    return title, False


_FETCH_METADATA_KEYS = (
    "fallback_query",
    "library_type",
    "is_forced_id",
    "forced_provider",
    "existing_metadata",
    "smart_scoring",
    "return_candidates",
    "on_candidate",
)


@dataclass
class DefaultFetch:
    data: Optional[dict]
    used: list
    score_tie: bool = False
    tie_review_payload: Optional[dict] = None


@dataclass
class WaveResult:
    data: Optional[dict]
    used: list
    useful: bool
    score_tie: bool = False
    tie_review_payload: Optional[dict] = None
    mapping_noop: bool = False


def _meta_kwargs(fetch_kwargs: dict) -> dict:
    return {k: fetch_kwargs[k] for k in _FETCH_METADATA_KEYS if k in fetch_kwargs}


def fetch_default(plan, query, fetch_kwargs) -> DefaultFetch:
    kw = dict(fetch_kwargs or {})
    providers_list = kw.pop("providers_list", None) or []
    library_type = kw.get("library_type") or plan.fetch_library_type
    kw["library_type"] = library_type
    smart_fusion = kw.pop("smart_fusion", False)
    if plan.default == CASCADE:
        data, used = fetch_metadata(
            query,
            providers_list,
            smart_fusion,
            skip_keys=plan.skip_keys or None,
            **_meta_kwargs(kw),
        )
    else:
        existing = kw.get("existing_metadata") or {}

        def _call(q, is_id):
            _, blob = call_scraper(
                plan.default,
                q,
                library_type=library_type,
                is_id=is_id,
                existing_metadata=existing,
                forced_provider=plan.default,
            )
            return blob

        is_id = bool(kw.get("is_forced_id"))
        data = _call(query, is_id)
        if not data:
            fb = str(kw.get("fallback_query") or "").strip()
            raw = str(query or "").strip()
            if fb and fb.lower() != raw.lower():
                data = _call(fb, False)
        used = [plan.default] if data else []
        if data:
            data = apply_explicit_label_age(data) or data
            data.setdefault("_provider_used", plan.default)
    score_tie = bool((data or {}).get("_score_tie"))
    tie_payload = (data or {}).get("_tie_review_payload") if isinstance(data, dict) else None
    return DefaultFetch(
        data=data,
        used=list(used or []),
        score_tie=score_tie,
        tie_review_payload=tie_payload if isinstance(tie_payload, dict) else None,
    )


def _normalize_cascade_entry(entry):
    """Entrée stock : `{blob, query, is_id}`. Un blob nu (tests) a query/is_id inconnus."""
    if not isinstance(entry, dict):
        return None
    if "blob" in entry and isinstance(entry.get("blob"), dict) and "is_id" in entry:
        return {
            "blob": entry["blob"],
            "query": entry.get("query"),
            "is_id": entry.get("is_id"),
            "is_default": False,
        }
    return {"blob": entry, "query": None, "is_id": None, "is_default": False}


def _same_fetch_args(stored_query, stored_is_id, want_query, want_is_id) -> bool:
    if stored_is_id is None or stored_query is None:
        return False
    if bool(stored_is_id) != bool(want_is_id):
        return False
    a = str(stored_query or "").strip().casefold()
    b = str(want_query or "").strip().casefold()
    return bool(a) and a == b


def _stock_from_hit(hit_blob) -> dict:
    """Blobs déjà obtenus (vainqueur + reste de la cascade). Clés upper."""
    stock = {}
    if not isinstance(hit_blob, dict):
        return stock
    extra = hit_blob.get("_cascade_blobs")
    if isinstance(extra, dict):
        for pid, entry in extra.items():
            if not pid:
                continue
            norm = _normalize_cascade_entry(entry)
            if norm:
                stock[str(pid).upper()] = norm
    default_id = str(hit_blob.get("_provider_used") or "").upper()
    if default_id:
        stock.setdefault(
            default_id,
            {
                "blob": hit_blob,
                "query": None,
                "is_id": None,
                "is_default": True,
            },
        )
    return stock


def _submit_override(executor, fn, *args):
    return executor.submit(contextvars.copy_context().run, fn, *args)


def fetch_overrides(
    plan,
    hit_blob,
    *,
    is_forced_id,
    magic_query,
    existing,
    config=None,
) -> dict:
    out = {}
    default_id = ""
    if isinstance(hit_blob, dict):
        default_id = str(hit_blob.get("_provider_used") or "").upper()
    stock = _stock_from_hit(hit_blob)
    pending = []
    for pid in plan.override_providers:
        key = str(pid or "").upper()
        query, is_id = override_fetch_args(
            is_forced_id=bool(is_forced_id),
            magic_query=magic_query or "",
            hit_blob=hit_blob,
            target_provider=pid,
        )
        cached = stock.get(key)
        blob = cached.get("blob") if isinstance(cached, dict) else None
        if isinstance(blob, dict):
            is_default = bool(cached.get("is_default")) and key == default_id
            args_match = _same_fetch_args(
                cached.get("query"), cached.get("is_id"), query, is_id
            )
            # Blob nu sans args (tests) : réemploi seulement en recherche titre.
            legacy_title = (
                cached.get("query") is None
                and cached.get("is_id") is None
                and not cached.get("is_default")
                and not is_forced_id
            )
            if is_default or (
                blob_accepted_for_auto(blob, config)
                and (args_match or legacy_title)
            ):
                out[pid] = blob
                continue
        if not query:
            logging.warning(
                "[field_mapping] override %s skipped: empty query", pid
            )
            continue
        pending.append((pid, query, is_id))

    if not pending:
        return out

    library_type = plan.fetch_library_type
    if existing is not None:
        existing_ctx = existing
    elif isinstance(hit_blob, dict):
        existing_ctx = hit_blob
    else:
        existing_ctx = {}
    if isinstance(existing_ctx, dict):
        existing_ctx = dict(existing_ctx)
        existing_ctx.pop("_cascade_blobs", None)

    def _one(pid, query, is_id):
        _, blob = call_scraper(
            pid,
            query,
            library_type=library_type,
            is_id=is_id,
            existing_metadata=existing_ctx,
            forced_provider="AUTO",
        )
        if not blob:
            return pid, None
        blob = apply_explicit_label_age(blob) or blob
        if not blob_accepted_for_auto(blob, config):
            logging.warning(
                "[field_mapping] override %s skipped: below Auto threshold", pid
            )
            return pid, None
        return pid, blob

    if len(pending) == 1:
        pid, blob = _one(*pending[0])
        if blob:
            out[pid] = blob
        return out

    with ThreadPoolExecutor(max_workers=len(pending)) as executor:
        futs = {
            _submit_override(executor, _one, pid, query, is_id): pid
            for pid, query, is_id in pending
        }
        for fut in as_completed(futs):
            pid = futs[fut]
            try:
                got_pid, blob = fut.result()
            except Exception as exc:
                logging.error(
                    "[field_mapping] override %s parallel error: %s", pid, exc
                )
                continue
            if blob:
                out[got_pid] = blob
    return out


def _source_has_field(source, field) -> bool:
    if field == "staff":
        return bool(source.staff_payload())
    return source.get(field) is not None


def assemble_mapped_payload(plan, default_id, default_blob, by_provider):
    blobs = dict(by_provider or {})
    if default_id and isinstance(default_blob, dict):
        blobs.setdefault(default_id, default_blob)
    sources = {
        pid: source_from_scraper_data(blob, provider_id=pid)
        for pid, blob in blobs.items()
        if isinstance(blob, dict)
    }
    base = pick_assembly_base(
        default_id, default_blob, blobs, plan.override_providers
    )
    if base is None:
        return None
    assembled = assemble_field_picks(
        base,
        sources,
        map_to_field_picks(plan),
        merge_fields=False,
        base_provider=base.provider_id,
    )
    if not assembled:
        return None
    absorb_identity(assembled, [b for b in blobs.values() if isinstance(b, dict)])
    applied = {}
    for field, pid in plan.overrides.items():
        src = sources.get(pid)
        if src is not None and _source_has_field(src, field):
            applied[field] = pid
    assembled["_field_sources"] = applied
    assembled["_provider_used"] = base.provider_id or assembled.get("_provider_used")
    assembled.pop("_cascade_blobs", None)
    return assembled


def run_mapping_wave(plan, query, **kwargs) -> WaveResult:
    providers_list = kwargs.get("providers_list") or []
    if plan.mapping_noop:
        smart_fusion = kwargs.pop("smart_fusion", False)
        kwargs.pop("providers_list", None)
        kwargs.pop("config", None)
        kwargs.pop("skip_keys", None)
        data, used = fetch_metadata(query, providers_list, smart_fusion, **_meta_kwargs(kwargs))
        useful = _blob_useful(data) if isinstance(data, dict) else False
        return WaveResult(
            data=data,
            used=list(used or []),
            useful=useful,
            score_tie=bool((data or {}).get("_score_tie")) if isinstance(data, dict) else False,
            tie_review_payload=(data or {}).get("_tie_review_payload") if isinstance(data, dict) else None,
            mapping_noop=True,
        )

    default = fetch_default(plan, query, kwargs)
    if default.score_tie:
        return WaveResult(
            data=default.data,
            used=default.used,
            useful=False,
            score_tie=True,
            tie_review_payload=default.tie_review_payload,
        )

    overrides = fetch_overrides(
        plan,
        default.data,
        is_forced_id=kwargs.get("is_forced_id", False),
        magic_query=query,
        existing=kwargs.get("existing_metadata"),
        config=kwargs.get("config"),
    )
    if isinstance(default.data, dict):
        default.data.pop("_cascade_blobs", None)
    default_id = ""
    if isinstance(default.data, dict):
        default_id = default.data.get("_provider_used") or (default.used[0] if default.used else "")
    by_provider = dict(overrides)
    assembled = assemble_mapped_payload(plan, default_id, default.data, by_provider)
    useful = _blob_useful(assembled) if assembled else False
    used = list(default.used)
    for pid in overrides:
        if pid not in used:
            used.append(pid)
    return WaveResult(
        data=assembled,
        used=used,
        useful=useful,
        score_tie=False,
        tie_review_payload=None,
    )
