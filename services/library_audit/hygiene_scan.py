"""Background library hygiene scan (metadata + volumes + catalogue + duplicates)."""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from config_manager import load_config
from db_manager import (
    get_all_cached_data,
    get_catalog_expected_override,
    get_inventory_excluded_ids,
    get_volume_report_cache,
    list_dismissed_group_keys,
    save_duplicate_groups_cache,
    save_volume_report_cache,
    set_hygiene_library_meta,
    set_series_external_id_flags,
)
from kavita_api import KavitaAPI
from scrapers.utils import get_dup_accept_threshold
from secure_logging import safe_exc_str
from services.library_audit.catalog_count import (
    apply_catalog_override,
    resolve_catalog_expected,
)
from services.library_audit.duplicates import cluster_duplicate_series
from services.library_audit.series_identity import (
    identity_has_external_id,
    merge_series_identity,
)
from services.library_audit.volume_report import build_volume_report

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "running": False,
    "library_id": None,
    "done": 0,
    "total": 0,
    "current_name": "",
    "phase": "",
    "error": None,
    "counts": {},
    "cancelled": False,
    "mode": "full",
    "skipped": 0,
}

# États de complétion regroupés pour la barre de santé de la bibliothèque.
# `overshoot` (plus d'unités que l'attendu) compte parmi les saines : il ne
# manque rien : c'est le catalogue qui est en retard. Le tenir pour « incomplète »
# faisait mentir le libellé du segment.
_HEALTHY_STATES = frozenset({"complete", "uptodate", "neutral", "overshoot"})
_INCOMPLETE_STATES = frozenset({"near", "partial", "poor"})


def summarize_states(state_counts: Dict[str, int]) -> Dict[str, int]:
    """Répartition des états de complétion pour la barre de santé."""
    return {
        "healthy": sum(n for st, n in state_counts.items() if st in _HEALTHY_STATES),
        "incomplete": sum(
            n for st, n in state_counts.items() if st in _INCOMPLETE_STATES
        ),
        "unknown_expected": int(state_counts.get("unknown", 0)),
    }


def _emit(event: str, payload: dict) -> None:
    # `extensions` et non `app` : importer le module applicatif depuis un thread de
    # fond réexécute son chargement (et ses effets de bord) partout où il n'est pas
    # déjà l'entrée du process — un échec ici ne coûterait qu'une barre de
    # progression figée, sans trace.
    try:
        from extensions import socketio

        socketio.emit(event, payload)
    except Exception as exc:
        logging.debug("[Inventaire] emit %s ignoré : %s", event, exc)


def _emit_progress(payload: dict) -> None:
    """Dual emit for new + legacy socket listeners."""
    _emit("hygiene_progress", payload)
    _emit("volume_hygiene_progress", payload)


def get_hygiene_scan_state() -> dict:
    with _lock:
        return dict(_state)


def start_hygiene_scan(
    library_id,
    series_ids: Optional[List[int]] = None,
    *,
    with_catalog: bool = True,
    mode: str = "full",
) -> Dict[str, Any]:
    """Start async hygiene scan. Returns {success, started|busy, ...}."""
    mode = "incremental" if str(mode).strip().lower() == "incremental" else "full"
    with _lock:
        if _state["running"]:
            return {"success": False, "busy": True, **dict(_state)}
        _state.update(
            {
                "running": True,
                "library_id": str(library_id) if library_id is not None else "",
                "done": 0,
                "total": 0,
                "current_name": "",
                "phase": "starting",
                "error": None,
                "counts": {},
                "cancelled": False,
                "mode": mode,
                "skipped": 0,
            }
        )

    t = threading.Thread(
        target=_run_scan,
        args=(library_id, list(series_ids or []), with_catalog, mode),
        daemon=True,
        name="hygiene-scan",
    )
    t.start()
    return {"success": True, "started": True, "mode": mode}


def start_volume_hygiene_scan(
    library_id,
    series_ids: Optional[List[int]] = None,
    *,
    with_catalog: bool = True,
) -> Dict[str, Any]:
    """Alias — keep old route/name working."""
    return start_hygiene_scan(library_id, series_ids, with_catalog=with_catalog)


def cancel_hygiene_scan() -> Dict[str, Any]:
    """Demande l'arrêt du scan en cours (traité entre deux séries)."""
    with _lock:
        if not _state["running"]:
            return {"success": False, "running": False}
        _state["cancelled"] = True
    return {"success": True, "cancelled": True}


def _cancel_requested() -> bool:
    with _lock:
        return bool(_state.get("cancelled"))


def _is_all_libraries(library_id) -> bool:
    return not library_id or str(library_id).strip().lower() == "all"


def _cached_catalog(series_id: int):
    """Attendu catalogue déjà en cache, quel qu'en soit l'état — ou None.

    Sert au scan `catalog=false` : sans lui, reconstruire les rapports sans
    interroger les providers réécrivait chaque série en « attendu inconnu » et
    effaçait des heures de cascade.
    """
    try:
        summary = get_volume_report_cache(series_id) or {}
    except Exception:
        return None
    cat = summary.get("catalog") or {}
    return dict(cat) if cat else None


def _reusable_catalog(series_id: int):
    """Attendu catalogue réutilisable en analyse rapide, avec le compte local qui
    l'accompagnait — ou None s'il faut rappeler les providers.

    Deux cas ne se réutilisent pas : un catalogue sans attendu (`N/?`), sinon
    l'analyse rapide ne pourrait jamais sortir une série de l'inconnu, et un
    rapport d'avant C66 dont on ignore le compte local d'alors.
    """
    try:
        summary = get_volume_report_cache(series_id) or {}
    except Exception:
        return None
    cat = summary.get("catalog") or {}
    if (cat.get("status") or "").strip().lower() != "ok":
        return None
    if not (cat.get("expected") or cat.get("expected_chapters")):
        return None
    count = (summary.get("stats") or {}).get("primary_count")
    if count is None:
        return None
    return dict(cat), int(count)


def _run_scan(
    library_id, series_ids: List[int], with_catalog: bool, mode: str = "full"
) -> None:
    config = load_config()
    api = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
    identities_for_dup: List[dict] = []
    ext_flags: Dict[int, bool] = {}
    missing_count_total = 0
    no_id_count = 0
    failed_count = 0
    incremental = mode == "incremental"
    state_counts: Dict[str, int] = {}
    reused = 0

    # "all" is the storage/cache key for "Toutes les bibliothèques" ; l'API
    # Kavita et le clustering doublons veulent None pour ne filtrer aucune lib.
    scan_all = _is_all_libraries(library_id)
    api_library_id = None if scan_all else library_id

    try:
        if series_ids:
            targets = []
            for sid in series_ids:
                s = api.get_series(int(sid)) or {"id": int(sid), "name": str(sid)}
                if not scan_all:
                    s.setdefault("libraryId", library_id)
                targets.append(s)
        else:
            targets = api.get_all_series(library_id=api_library_id)

        cached = get_all_cached_data()
        excluded_ids = get_inventory_excluded_ids()
        if excluded_ids:
            skipped_before = len(targets)
            targets = [t for t in targets if int(t.get("id") or 0) not in excluded_ids]
            skipped = skipped_before - len(targets)
            if skipped:
                logging.info(
                    "[Inventaire] %s série(s) exclue(s) de l'inventaire, ignorée(s)",
                    skipped,
                )
                with _lock:
                    _state["skipped"] = skipped

        with _lock:
            _state["total"] = len(targets)
            _state["phase"] = "series"

        _emit_progress(
            {
                "running": True,
                "done": 0,
                "total": len(targets),
                "library_id": library_id,
                "phase": "series",
                "mode": mode,
            }
        )

        for s in targets:
            if _cancel_requested():
                logging.info("[Inventaire] annulation demandée — arrêt du scan")
                break
            sid = int(s["id"])
            name = s.get("name") or str(sid)
            with _lock:
                _state["current_name"] = name
                _state["phase"] = "metadata"

            badge = "—"
            missing_n = 0
            has_ext = False
            pub_status = "UNKNOWN"
            completion_state = "unknown"
            unit_mode = "volumes"
            failed = False
            try:
                ov = cached.get(sid) or {}
                lib_type = (
                    s.get("libraryType")
                    or api.get_library_type_for_series(sid)
                    or "Manga"
                )
                metadata = api.get_series_metadata(sid) or {}
                identity = merge_series_identity(
                    s,
                    metadata,
                    forced_id=ov.get("forced_id") or "",
                    forced_provider=ov.get("forced_provider") or "",
                    series_name=name,
                    library_type=lib_type,
                )
                has_ext = identity_has_external_id(identity)
                ext_flags[sid] = has_ext
                if not has_ext:
                    no_id_count += 1

                with _lock:
                    _state["phase"] = "volumes"
                volumes = api.get_series_volumes(sid)

                catalog = None
                # Incrémental : on relit toujours Kavita (local, rapide) mais on
                # réutilise l'attendu catalogue déjà connu — c'est l'appel
                # provider, throttlé, qui coûte les dizaines de minutes. La
                # réutilisation s'arrête dès que le compte local a bougé : de
                # nouveaux tomes chez vous, c'est souvent de nouveaux tomes parus.
                reuse = _reusable_catalog(sid) if incremental else None
                if reuse:
                    cached_catalog, cached_count = reuse
                    probe = build_volume_report(
                        sid, volumes, series_name=name, catalog=cached_catalog
                    )
                    if (probe.get("stats") or {}).get("primary_count") == cached_count:
                        catalog = cached_catalog
                        reused += 1
                if catalog is None and not with_catalog:
                    # Scan sans providers : on garde l'attendu déjà connu plutôt
                    # que de réécrire la série en « inconnu ».
                    catalog = _cached_catalog(sid)
                elif catalog is None:
                    with _lock:
                        _state["phase"] = "catalog"
                    catalog = resolve_catalog_expected(
                        identity=identity,
                        library_type=lib_type,
                        series_name=name,
                        forced_id=ov.get("forced_id") or "",
                        forced_provider=ov.get("forced_provider") or "",
                        config=config,
                        series=s,
                        metadata=metadata,
                    )
                catalog = apply_catalog_override(
                    catalog, get_catalog_expected_override(sid)
                )

                report = build_volume_report(
                    sid, volumes, series_name=name, catalog=catalog
                )
                save_volume_report_cache(sid, report)
                badge = report.get("badge") or "—"
                completion = report.get("completion") or {}
                completion_state = completion.get("state") or "unknown"
                unit_mode = report.get("unit_mode") or "volumes"
                state_counts[completion_state] = state_counts.get(completion_state, 0) + 1
                missing_n = int(completion.get("missing_count") or 0)
                if missing_n:
                    missing_count_total += 1
                pub_status = report.get("publication_status") or "UNKNOWN"

                # Identity enriched for clustering
                identity["id"] = sid
                identity["libraryId"] = s.get("libraryId") or api_library_id
                identities_for_dup.append(identity)

                logging.info(
                    "[Inventaire] %s/%s %s — %s",
                    _state["done"] + 1,
                    _state["total"],
                    name,
                    badge,
                )
            except Exception as e:
                # Analyse sans conclusion : aucun flag, aucun verdict. Écrire
                # `has_external_id = False` sur un simple 503 Kavita rangeait
                # une série pourtant identifiée dans le filtre « sans id
                # externe », en contradiction avec le compteur (incrémenté
                # seulement quand l'analyse aboutit).
                failed = True
                failed_count += 1
                logging.warning(
                    "[Inventaire] series %s failed: %s", sid, safe_exc_str(e)
                )

            with _lock:
                _state["done"] = int(_state["done"]) + 1
                done = _state["done"]
                total = _state["total"]
            progress = {
                "running": True,
                "done": done,
                "total": total,
                "series_id": sid,
                "name": name,
                "library_id": library_id,
                "phase": "series",
            }
            if failed:
                # Le front réécrit la ligne dès qu'un badge arrive (« — » est
                # truthy) : ne rien affirmer plutôt qu'afficher un verdict vide.
                progress["failed"] = True
            else:
                progress.update(
                    {
                        "badge": badge,
                        "missing_count": missing_n,
                        "has_external_id": has_ext,
                        "publication_status": pub_status,
                        "completion_state": completion_state,
                        "unit_mode": unit_mode,
                    }
                )
            _emit_progress(progress)

        # Annulation : les rapports déjà écrits restent valides, mais les
        # compteurs de bibliothèque, les flags d'id externe et le regroupement
        # de doublons seraient faux sur un parcours partiel — on garde donc les
        # précédents intacts.
        if _cancel_requested():
            logging.info(
                "[Inventaire] scan annulé après %s série(s) — compteurs de "
                "bibliothèque, flags et doublons inchangés",
                _state.get("done"),
            )
            return

        set_series_external_id_flags(ext_flags)

        with _lock:
            _state["phase"] = "cluster"
        threshold = get_dup_accept_threshold(config)
        exclude = list_dismissed_group_keys(library_id)
        groups = cluster_duplicate_series(
            identities_for_dup,
            library_id=api_library_id,
            threshold=threshold,
            exclude_keys=exclude,
            config=config,
        )
        save_duplicate_groups_cache(library_id, groups)

        counts = {
            "missing": missing_count_total,
            "duplicates": len(groups),
            "no_external_id": no_id_count,
            "series": len(targets),
            # Répartition pour la barre de santé de la bibliothèque.
            **summarize_states(state_counts),
            # Séries dont l'analyse n'a rien conclu (Kavita indisponible le temps
            # d'une série) : sans ce compteur, elles n'entraient dans aucun
            # segment et la barre affichait moins de séries qu'elle n'en annonçait.
            "failed": failed_count,
            "excluded": len(excluded_ids),
            "states": dict(state_counts),
            "mode": mode,
        }
        set_hygiene_library_meta(library_id, counts)
        with _lock:
            _state["counts"] = counts

        logging.info(
            "[Inventaire] done lib=%s missing=%s dups=%s no_id=%s sains=%s echecs=%s%s",
            library_id,
            counts["missing"],
            counts["duplicates"],
            counts["no_external_id"],
            counts["healthy"],  # sains = rien ne manque (catalogue en retard inclus)
            counts["failed"],
            f" (incrémental, {reused} attendus réutilisés)" if incremental else "",
        )
    except Exception as e:
        logging.error("[Inventaire] scan failed: %s", safe_exc_str(e))
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["running"] = False
            _state["phase"] = "done"
            done = _state["done"]
            total = _state["total"]
            err = _state["error"]
            counts = dict(_state.get("counts") or {})
            cancelled = bool(_state.get("cancelled"))
        _emit_progress(
            {
                "running": False,
                "done": done,
                "total": total,
                "library_id": library_id,
                "error": err,
                "phase": "done",
                "counts": counts,
                "cancelled": cancelled,
                "mode": mode,
            }
        )
