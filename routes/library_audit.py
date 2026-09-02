"""Library hygiene APIs — volume report, duplicates, catalogue, scan, dismiss, script."""

from __future__ import annotations

import logging

from flask import Blueprint, Response, jsonify, request

from config_manager import get_kavita_ui_url, load_config
from db_manager import (
    delete_dup_dismissal,
    get_all_cached_data,
    get_catalog_expected_override,
    get_duplicate_groups_cache,
    get_hygiene_library_meta,
    get_inventory_excluded_ids,
    get_series_audit_flags,
    get_volume_report_badges,
    get_volume_report_cache,
    get_volume_report_hygiene_map,
    has_duplicate_groups_cache,
    list_catalog_expected_overrides,
    list_dup_dismissals,
    purge_series_hygiene_cache,
    save_dup_dismissal,
    save_volume_report_cache,
    set_catalog_expected_override,
    set_hygiene_library_meta,
    set_inventory_excluded,
)
from kavita_api import KavitaAPI
from routes.volume_enrichment import volume_enrichment_enabled
from secure_logging import safe_exc_str
from services.library_audit import (
    build_duplicate_folder_script,
    build_volume_report,
    duplicates_to_csv,
    duplicates_to_txt,
    inventory_folder_path_prefix_from_config,
    volume_report_to_csv,
    volume_report_to_txt,
)
from services.library_audit.catalog_count import (
    apply_catalog_override,
    resolve_catalog_expected,
)
from services.library_audit.export_csv import (
    missing_volumes_to_csv,
    missing_volumes_to_txt,
)
from services.library_audit.hygiene_scan import (
    cancel_hygiene_scan,
    get_hygiene_scan_state,
    start_hygiene_scan,
)
from services.library_audit.series_identity import merge_series_identity
from translations import translations

library_audit_bp = Blueprint("library_audit", __name__)


def _api() -> KavitaAPI:
    config = load_config()
    return KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))


def _t():
    config = load_config()
    return translations.get(config.get("UI_LANG", "fr"), translations["fr"])


def inventory_enabled(config: dict = None) -> bool:
    """L'inventaire est-il activé ? (défaut oui, pour ne rien changer aux
    installations existantes)."""
    cfg = config if config is not None else load_config()
    return cfg.get("LIBRARY_INVENTORY_ENABLED", True) is not False


#: Le détail tome par tome, reconstruit depuis Kavita seul (aucun appel de
#: fournisseur, aucun attendu de catalogue). C'est la surface d'aperçu de
#: l'enrichissement par tome, une fonctionnalité voisine mais distincte : la
#: couper avec l'Inventaire rendait celle-ci injoignable alors que son propre
#: interrupteur était allumé.
_REACHABLE_FOR_VOLUME_ENRICHMENT = frozenset(
    {"library_audit.series_volume_report_units"}
)


@library_audit_bp.before_request
def _guard_inventory_disabled():
    """Coupe toutes les routes d'inventaire quand la fonctionnalité est éteinte :
    l'interface la masque déjà, mais un onglet resté ouvert ne doit pas relancer
    de scan ni de cascade provider en arrière-plan."""
    if inventory_enabled():
        return None
    if request.endpoint in _REACHABLE_FOR_VOLUME_ENRICHMENT and volume_enrichment_enabled():
        return None
    t = _t()
    return jsonify(
        {
            "success": False,
            "error": t.get("audit_err_disabled", "Inventaire désactivé."),
            "disabled": True,
        }
    ), 403


def _build_full_report(series_id: int, *, with_catalog: bool = True) -> dict:
    config = load_config()
    api = _api()
    series = api.get_series(series_id)
    if not series:
        raise LookupError(f"Series {series_id} not found in Kavita")
    name = series.get("name") or ""
    metadata = api.get_series_metadata(series_id) or {}
    volumes = api.get_series_volumes(series_id)
    catalog = None
    if with_catalog:
        cached = get_all_cached_data().get(series_id) or {}
        lib_type = (
            series.get("libraryType")
            or api.get_library_type_for_series(series_id)
            or "Manga"
        )
        identity = merge_series_identity(
            series,
            metadata,
            forced_id=cached.get("forced_id") or "",
            forced_provider=cached.get("forced_provider") or "",
            series_name=name,
            library_type=lib_type,
        )
        catalog = resolve_catalog_expected(
            identity=identity,
            library_type=lib_type,
            series_name=name,
            forced_id=cached.get("forced_id") or "",
            forced_provider=cached.get("forced_provider") or "",
            config=config,
            series=series,
            metadata=metadata,
        )
    else:
        cached_rep = get_volume_report_cache(series_id) or {}
        catalog = dict(cached_rep.get("catalog") or {}) if cached_rep.get("catalog") else None
    catalog = apply_catalog_override(
        catalog, get_catalog_expected_override(series_id)
    )
    report = build_volume_report(series_id, volumes, series_name=name, catalog=catalog)
    save_volume_report_cache(series_id, report)
    report["kavita_url"] = (
        f"{get_kavita_ui_url(config)}/library/{series.get('libraryId')}/series/{series_id}"
        if series.get("libraryId")
        else None
    )
    report["inventory_excluded"] = series_id in get_inventory_excluded_ids()
    return report


@library_audit_bp.route("/api/series/<int:series_id>/volume-report", methods=["GET"])
def series_volume_report(series_id: int):
    t = _t()
    fmt = (request.args.get("format") or "json").lower()
    with_catalog = request.args.get("catalog", "1") not in ("0", "false", "no")
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        # Default: cache if fresh enough for UI; refresh=1 forces rebuild.
        if not refresh and fmt == "json":
            cached = get_volume_report_cache(series_id)
            if cached:
                cached["inventory_excluded"] = series_id in get_inventory_excluded_ids()
                return jsonify({"success": True, "cached": True, **cached})
        report = _build_full_report(series_id, with_catalog=with_catalog)
        if fmt == "csv":
            return Response(
                volume_report_to_csv(report),
                mimetype="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=volume-report-{series_id}.csv"
                },
            )
        if fmt == "txt":
            return Response(
                volume_report_to_txt(report),
                mimetype="text/plain",
                headers={
                    "Content-Disposition": f"attachment; filename=volume-report-{series_id}.txt"
                },
            )
        return jsonify({"success": True, "cached": False, **report})
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logging.error("volume-report failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("audit_err_generic", str(e))}), 500


@library_audit_bp.route("/api/series/<int:series_id>/volume-report/summary", methods=["GET"])
def series_volume_report_summary(series_id: int):
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    if refresh:
        return series_volume_report(series_id)
    cached = get_volume_report_cache(series_id)
    if cached:
        cached["inventory_excluded"] = series_id in get_inventory_excluded_ids()
        return jsonify({"success": True, "cached": True, **cached})
    return jsonify({"success": False, "error": "no_cache", "cached": False}), 404


@library_audit_bp.route("/api/series/<int:series_id>/volume-report/units", methods=["GET"])
def series_volume_report_units(series_id: int):
    """Détail tome par tome, reconstruit depuis Kavita seul.

    Le cache ne stocke que le résumé (les `units` de 1000 séries pèseraient des
    dizaines de Mo), si bien que la modale ouvrait un tableau vide jusqu'au
    « Rafraîchir ». Cette route relit les volumes Kavita — un appel local — et
    réutilise l'attendu catalogue déjà connu, sans toucher aux providers.
    """
    t = _t()
    try:
        api = _api()
        series = api.get_series(series_id)
        if not series:
            return jsonify({"success": False, "error": f"Series {series_id} not found in Kavita"}), 404
        name = series.get("name") or ""
        volumes = api.get_series_volumes(series_id)
        cached = get_volume_report_cache(series_id) or {}
        catalog = dict(cached.get("catalog") or {})
        catalog = apply_catalog_override(
            catalog or None, get_catalog_expected_override(series_id)
        )
        report = build_volume_report(
            series_id, volumes, series_name=name or cached.get("series_name") or "", catalog=catalog
        )
        save_volume_report_cache(series_id, report)
        report["inventory_excluded"] = series_id in get_inventory_excluded_ids()
        return jsonify({"success": True, "cached": False, "local_only": True, **report})
    except Exception as e:
        logging.error("volume-report units failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("audit_err_generic", str(e))}), 500


def _duplicate_flags_payload(series_ids=None) -> dict:
    stored = get_series_audit_flags(series_ids)
    out = {}
    for sid, flag in stored.items():
        out[str(sid)] = {
            "has_external_id": bool(flag.get("has_external_id")),
            "duplicate_group_id": flag.get("duplicate_group_id") or "",
        }
    if series_ids:
        for sid in series_ids:
            key = str(int(sid))
            out.setdefault(key, {"has_external_id": False, "duplicate_group_id": ""})
    return out


def _duplicates_json(library_id, groups, *, cached: bool, series_ids=None):
    member_ids = []
    for g in groups or []:
        member_ids.extend(g.get("series_ids") or [])
    meta = get_hygiene_library_meta(library_id)
    cfg = load_config() or {}
    return {
        "success": True,
        "library_id": library_id,
        "cached": cached,
        "groups": groups,
        "count": len(groups or []),
        "member_ids": [int(x) for x in member_ids],
        "flags": _duplicate_flags_payload(series_ids),
        "meta": meta,
        "folder_path_prefix": inventory_folder_path_prefix_from_config(cfg),
        "folder_trash": cfg.get("INVENTORY_FOLDER_TRASH") or "",
    }


@library_audit_bp.route("/api/libraries/<library_id>/duplicates", methods=["GET"])
def library_duplicates(library_id):
    t = _t()
    fmt = (request.args.get("format") or "json").lower()
    refresh = request.args.get("refresh") in ("1", "true", "yes")
    try:
        if refresh:
            return jsonify(
                {
                    "success": False,
                    "error": t.get(
                        "audit_err_run_analyser",
                        "Lancez Analyser la bibliothèque pour rafraîchir les doublons.",
                    ),
                }
            ), 400

        if not has_duplicate_groups_cache(library_id):
            if fmt == "csv":
                return Response(
                    duplicates_to_csv([], library_id=library_id),
                    mimetype="text/csv",
                    headers={
                        "Content-Disposition": f"attachment; filename=duplicates-{library_id}.csv"
                    },
                )
            if fmt == "txt":
                return Response(
                    duplicates_to_txt([], library_id=library_id),
                    mimetype="text/plain",
                    headers={
                        "Content-Disposition": f"attachment; filename=duplicates-{library_id}.txt"
                    },
                )
            return jsonify(
                {
                    "success": False,
                    "error": t.get(
                        "audit_err_run_analyser",
                        "Lancez Analyser la bibliothèque pour scanner les doublons.",
                    ),
                    "groups": [],
                    "count": 0,
                }
            ), 404

        cached = get_duplicate_groups_cache(library_id)
        if fmt == "csv":
            return Response(
                duplicates_to_csv(cached, library_id=library_id),
                mimetype="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=duplicates-{library_id}.csv"
                },
            )
        if fmt == "txt":
            return Response(
                duplicates_to_txt(cached, library_id=library_id),
                mimetype="text/plain",
                headers={
                    "Content-Disposition": f"attachment; filename=duplicates-{library_id}.txt"
                },
            )
        return jsonify(_duplicates_json(library_id, cached, cached=True))
    except Exception as e:
        logging.error("duplicates report failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("audit_err_generic", str(e))}), 500


@library_audit_bp.route("/api/libraries/<library_id>/duplicates/dismiss", methods=["POST"])
def library_duplicates_dismiss(library_id):
    t = _t()
    payload = request.get_json(silent=True) or {}
    series_ids = payload.get("series_ids") or []
    reason = (payload.get("reason") or "not_duplicate").strip()
    try:
        gkey = save_dup_dismissal(library_id, series_ids, reason)
        # Drop from cache groups if present
        groups = get_duplicate_groups_cache(library_id)
        from services.library_audit.duplicates import dup_group_key
        from db_manager import save_duplicate_groups_cache

        def _evict_from_cache(lid, gk):
            """Retire le groupe dismissé du cache d'une vue donnée."""
            grps = get_duplicate_groups_cache(lid)
            remaining = [
                g for g in grps
                if dup_group_key(g.get("series_ids") or []) != gk
                and g.get("group_key") != gk
            ]
            if len(remaining) != len(grps):
                save_duplicate_groups_cache(lid, remaining)
                m = get_hygiene_library_meta(lid)
                if m and isinstance(m.get("counts"), dict):
                    c = dict(m["counts"])
                    c["duplicates"] = len(remaining)
                    set_hygiene_library_meta(lid, c, scanned_at=m.get("scanned_at"))
            return len(remaining) != len(grps)

        _evict_from_cache(library_id, gkey)

        # Synchronisation cross-vue : si on dismiss dans une bibliothèque
        # spécifique, le cache « all » doit aussi être nettoyé et vice versa.
        if str(library_id).lower() != "all":
            _evict_from_cache("all", gkey)
        else:
            # Dismiss depuis la vue globale : chercher chaque lib spécifique
            # qui pourrait contenir ce groupe et la nettoyer aussi.
            try:
                from db_manager import _connect, _ensure_library_audit_tables
                conn = _connect()
                c = conn.cursor()
                _ensure_library_audit_tables(c)
                c.execute(
                    "SELECT DISTINCT library_id FROM duplicate_group_cache "
                    "WHERE library_id != 'all'"
                )
                other_libs = [row[0] for row in c.fetchall()]
                conn.close()
                for lid in other_libs:
                    _evict_from_cache(lid, gkey)
            except Exception:
                pass

        return jsonify({"success": True, "group_key": gkey})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logging.error("dismiss failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("audit_err_generic", str(e))}), 500


@library_audit_bp.route("/api/libraries/<library_id>/duplicates/dismiss", methods=["DELETE"])
def library_duplicates_undismiss(library_id):
    t = _t()
    payload = request.get_json(silent=True) or {}
    series_ids = payload.get("series_ids")
    group_key = payload.get("group_key")
    try:
        ok = delete_dup_dismissal(library_id, series_ids=series_ids, group_key=group_key)
        return jsonify({"success": True, "deleted": ok})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logging.error("undismiss failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("audit_err_generic", str(e))}), 500


@library_audit_bp.route("/api/hygiene/dismissals", methods=["GET"])
def hygiene_dismissals():
    library_id = request.args.get("library_id")
    if not library_id:
        return jsonify({"success": False, "error": "library_id required"}), 400
    return jsonify({"success": True, "dismissals": list_dup_dismissals(library_id)})


@library_audit_bp.route("/api/libraries/<library_id>/audit-badges", methods=["GET"])
def library_audit_badges(library_id):
    try:
        ids = request.args.get("ids")
        want = [int(x) for x in ids.split(",") if x.strip().isdigit()] if ids else None
        hygiene_map = get_volume_report_hygiene_map(want)
        badges = {}
        items = {}
        for k, v in hygiene_map.items():
            b = v.get("badge") or "—"
            badges[str(k)] = b
            items[str(k)] = {
                "badge": b,
                "state": v.get("completion_state") or "",
                "forced": bool(v.get("forced_expected")),
                "unit": v.get("unit") or "volumes",
            }
        return jsonify({"success": True, "badges": badges, "items": items})
    except Exception as e:
        logging.error("audit-badges failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": str(e)}), 500


def _start_scan_handler(library_id):
    t = _t()
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("series_ids") or request.form.getlist("selected_series")
    series_ids = []
    for x in raw_ids:
        try:
            series_ids.append(int(x))
        except (TypeError, ValueError):
            continue
    with_catalog = payload.get("catalog", True)
    if isinstance(with_catalog, str):
        with_catalog = with_catalog not in ("0", "false", "no")
    mode = str(payload.get("mode") or request.form.get("mode") or "full")
    result = start_hygiene_scan(
        library_id, series_ids or None, with_catalog=bool(with_catalog), mode=mode
    )
    if not result.get("success"):
        return jsonify(
            {
                "success": False,
                "error": t.get("audit_scan_busy", "Scan already running"),
                **result,
            }
        ), 409
    return jsonify(result)


def _missing_volumes_rows(library_id, *, include_unknown: bool = False) -> list:
    """Build missing-volumes list from hygiene cache (optionally include N/?)."""
    hygiene_map = get_volume_report_hygiene_map()
    # Scope filter: for a concrete library, keep series whose libraryId matches
    # when we can resolve it from Kavita; otherwise return all cached (all scope).
    scope_ids = None
    if library_id and str(library_id).lower() != "all":
        try:
            api = _api()
            series = api.get_all_series(library_id=library_id) or []
            scope_ids = {int(s["id"]) for s in series if s.get("id") is not None}
        except Exception:
            logging.warning(
                "[Inventaire] Impossible de résoudre le périmètre de la bibliothèque %s "
                "— le rapport de manquants sera vide plutôt que global.",
                library_id,
            )
            scope_ids = set()
    excluded_ids = get_inventory_excluded_ids()

    def _row(sid, hy, missing) -> dict:
        return {
            "series_id": int(sid),
            "name": hy.get("series_name") or str(sid),
            "badge": hy.get("badge") or "",
            "kavita_count": hy.get("kavita_count"),
            "catalog_expected": hy.get("catalog_expected"),
            "catalog_status": (hy.get("catalog_status") or "").lower(),
            "catalog_provider": hy.get("catalog_provider") or "",
            "publication_status": hy.get("publication_status") or "UNKNOWN",
            "reason": hy.get("catalog_reason") or "",
            "missing_volumes": list(missing),
            "missing_label": hy.get("missing_label") or "",
            "unit": hy.get("unit") or "volumes",
            "unit_mode": hy.get("unit_mode") or "volumes",
            "count": hy.get("primary_count"),
            "expected": hy.get("primary_expected"),
            "completion_state": hy.get("completion_state") or "unknown",
            "completion_ratio": hy.get("completion_ratio"),
            "forced_expected": bool(hy.get("forced_expected")),
        }

    rows = []
    for sid, hy in hygiene_map.items():
        if scope_ids is not None and int(sid) not in scope_ids:
            continue
        if int(sid) in excluded_ids:
            continue
        missing = hy.get("missing_volumes") or []
        cat_status = (hy.get("catalog_status") or "").lower()
        if missing:
            rows.append(_row(sid, hy, missing))
        elif include_unknown and (
            cat_status == "unknown" or (hy.get("completion_state") == "unknown")
        ):
            rows.append(_row(sid, hy, []))
    # Le plus incomplet d'abord : c'est ce qu'on vient chercher dans ce rapport.
    severity = {"poor": 0, "partial": 1, "near": 2, "overshoot": 3, "unknown": 4}
    rows.sort(
        key=lambda r: (
            severity.get(r.get("completion_state"), 5),
            -(len(r.get("missing_volumes") or [])),
            (r.get("name") or "").lower(),
        )
    )
    return rows


@library_audit_bp.route("/api/libraries/<library_id>/missing-volumes", methods=["GET"])
def library_missing_volumes(library_id):
    t = _t()
    fmt = (request.args.get("format") or "json").lower()
    include_unknown = request.args.get("include_unknown") in ("1", "true", "yes")
    meta = get_hygiene_library_meta(library_id)
    if not meta:
        if fmt == "csv":
            return Response(
                missing_volumes_to_csv([], library_id=library_id),
                mimetype="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=missing-volumes-{library_id}.csv"
                },
            )
        if fmt == "txt":
            return Response(
                missing_volumes_to_txt([], library_id=library_id),
                mimetype="text/plain",
                headers={
                    "Content-Disposition": f"attachment; filename=missing-volumes-{library_id}.txt"
                },
            )
        return jsonify(
            {
                "success": False,
                "error": t.get(
                    "audit_err_run_analyser",
                    "Lancez Analyser la bibliothèque pour mettre à jour ce rapport.",
                ),
                "rows": [],
                "count": 0,
            }
        ), 404
    rows = _missing_volumes_rows(library_id, include_unknown=include_unknown)
    if fmt == "csv":
        return Response(
            missing_volumes_to_csv(rows, library_id=library_id),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=missing-volumes-{library_id}.csv"
            },
        )
    if fmt == "txt":
        return Response(
            missing_volumes_to_txt(rows, library_id=library_id),
            mimetype="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=missing-volumes-{library_id}.txt"
            },
        )
    return jsonify(
        {
            "success": True,
            "library_id": library_id,
            "rows": rows,
            "count": len(rows),
            "meta": meta,
        }
    )


@library_audit_bp.route("/api/series/<int:series_id>/catalog-expected", methods=["POST"])
def series_catalog_expected(series_id: int):
    t = _t()
    payload = request.get_json(silent=True) or {}
    raw = payload.get("expected", payload.get("catalog_expected"))
    try:
        if raw is None or raw == "":
            expected = None
        else:
            expected = int(raw)
            if expected < 1:
                return jsonify(
                    {"success": False, "error": "expected must be >= 1 or null"}
                ), 400
        set_catalog_expected_override(series_id, expected)
        # Réutilise le catalogue déjà en cache s'il existe pour éviter un scrape externe
        # inutile (AniList, MAL…) et son risque de timeout / erreur 500 sur un simple
        # enregistrement local. Si aucun rapport n'était encore en cache, on résout le catalogue.
        cached_rep = get_volume_report_cache(series_id)
        has_cached_cat = bool(cached_rep and cached_rep.get("catalog"))
        report = _build_full_report(series_id, with_catalog=not has_cached_cat)
        return jsonify(
            {
                "success": True,
                "series_id": series_id,
                "expected": expected,
                "badge": report.get("badge"),
                "missing_volumes": report.get("missing_volumes") or [],
                "catalog": report.get("catalog") or {},
                "publication_status": report.get("publication_status"),
                "report": report,
            }
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logging.error("catalog-expected failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("audit_err_generic", str(e))}), 500


@library_audit_bp.route("/api/libraries/<library_id>/hygiene-scan", methods=["POST"])
def library_hygiene_scan(library_id):
    return _start_scan_handler(library_id)


@library_audit_bp.route("/api/libraries/<library_id>/volume-hygiene-scan", methods=["POST"])
def library_volume_hygiene_scan(library_id):
    """Alias of hygiene-scan."""
    return _start_scan_handler(library_id)


@library_audit_bp.route("/api/libraries/<library_id>/hygiene-scan/status", methods=["GET"])
def library_hygiene_scan_status(library_id):
    state = get_hygiene_scan_state()
    meta = get_hygiene_library_meta(library_id)
    return jsonify({"success": True, **state, "meta": meta})


@library_audit_bp.route("/api/volume-hygiene-scan/status", methods=["GET"])
def volume_hygiene_scan_status():
    return jsonify({"success": True, **get_hygiene_scan_state()})


@library_audit_bp.route("/api/hygiene-scan/cancel", methods=["POST"])
def hygiene_scan_cancel():
    """Arrête le scan en cours entre deux séries (un parcours complet peut durer
    des dizaines de minutes sur une grosse bibliothèque)."""
    return jsonify(cancel_hygiene_scan())


@library_audit_bp.route("/api/series/<int:series_id>/inventory-exclude", methods=["POST"])
def series_inventory_exclude(series_id: int):
    """Exclut une série de l'inventaire (ou la réintègre).

    Pour les séries qu'aucun catalogue ne connaîtra jamais : elles gonflaient les
    compteurs de manquants sans recours autre que couper l'inventaire entier.
    """
    t = _t()
    payload = request.get_json(silent=True) or {}
    excluded = payload.get("excluded", True)
    if isinstance(excluded, str):
        excluded = excluded not in ("0", "false", "no")
    try:
        set_inventory_excluded(series_id, bool(excluded))
        if excluded:
            # Le rapport en cache ferait survivre la cartouche d'une série exclue.
            purge_series_hygiene_cache(series_id, keep_overrides=True)
        return jsonify(
            {"success": True, "series_id": series_id, "excluded": bool(excluded)}
        )
    except Exception as e:
        logging.error("inventory-exclude failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("audit_err_generic", str(e))}), 500


@library_audit_bp.route("/api/hygiene/catalog-overrides", methods=["GET"])
def hygiene_catalog_overrides():
    """Tous les attendus forcés, pour les revoir et les relâcher d'un endroit."""
    try:
        overrides = list_catalog_expected_overrides()
        hygiene_map = get_volume_report_hygiene_map(list(overrides.keys()) or None)
        rows = []
        for sid, expected in sorted(overrides.items()):
            hy = hygiene_map.get(sid) or {}
            rows.append(
                {
                    "series_id": int(sid),
                    "expected": int(expected),
                    "name": hy.get("series_name") or str(sid),
                    "badge": hy.get("badge") or "",
                    "unit": hy.get("unit") or "volumes",
                    "completion_state": hy.get("completion_state") or "unknown",
                }
            )
        return jsonify({"success": True, "rows": rows, "count": len(rows)})
    except Exception as e:
        logging.error("catalog-overrides failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@library_audit_bp.route("/api/libraries/<library_id>/duplicates/script", methods=["POST"])
def library_duplicates_script(library_id):
    """Rend un script bash à copier ou télécharger. Meta n'exécute rien."""
    t = _t()
    payload = request.get_json(silent=True) or {}
    series_ids = payload.get("series_ids") or []
    mode = (payload.get("mode") or "trash").strip().lower()
    script_format = (payload.get("format") or "sh").strip().lower()
    try:
        if not has_duplicate_groups_cache(library_id):
            return jsonify(
                {
                    "success": False,
                    "error": t.get(
                        "audit_err_run_analyser",
                        "Lancez Analyser la bibliothèque pour scanner les doublons.",
                    ),
                }
            ), 404
        groups = get_duplicate_groups_cache(library_id)
        cfg = load_config() or {}
        script, meta = build_duplicate_folder_script(
            groups,
            series_ids,
            mode=mode,
            script_format=script_format,
            trash_dir=cfg.get("INVENTORY_FOLDER_TRASH") or "",
            path_prefix=inventory_folder_path_prefix_from_config(cfg),
        )
        if meta.get("empty"):
            return jsonify(
                {
                    "success": False,
                    "error": t.get(
                        "audit_dup_script_empty",
                        "Aucune ligne Jeter n'a de dossier à déplacer.",
                    ),
                    **meta,
                }
            ), 400
        return jsonify({"success": True, "script": script, **meta})
    except ValueError:
        return jsonify(
            {
                "success": False,
                "error": t.get(
                    "audit_dup_script_empty",
                    "Cochez au moins une série à jeter.",
                ),
            }
        ), 400
    except Exception as e:
        logging.error("duplicates-script failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("audit_err_generic", str(e))}), 500


@library_audit_bp.route("/api/libraries/<library_id>/kavita-scan", methods=["POST"])
def library_kavita_scan(library_id):
    """Déclenche le scan de la bibliothèque directement dans Kavita."""
    t = _t()
    try:
        api = _api()
        ok = api.scan_library(library_id)
        if not ok:
            err_msg = t.get(
                "audit_dup_scan_failed",
                "Impossible de déclencher le scan Kavita : {error}",
            ).format(error="Kavita unreachable or returned error")
            return jsonify({"success": False, "error": err_msg}), 502
        return jsonify({
            "success": True,
            "message": t.get(
                "audit_dup_scan_triggered",
                "Scan de la bibliothèque Kavita déclenché avec succès !",
            ),
        })
    except Exception as e:
        err_msg = t.get(
            "audit_dup_scan_failed",
            "Impossible de déclencher le scan Kavita : {error}",
        ).format(error=safe_exc_str(e))
        return jsonify({"success": False, "error": err_msg}), 500


@library_audit_bp.route("/api/series/<series_id>/purge-empty", methods=["POST"])
def series_purge_empty(series_id):
    """Supprime une série vide (0 volume) dans Kavita et nettoie son cache."""
    t = _t()
    try:
        sid = int(series_id)
        api = _api()
        if not api.is_series_empty(sid):
            return jsonify({
                "success": False,
                "error": "Cette série contient des tomes ou des chapitres et ne peut être purgée comme série vide.",
            }), 400
        ok = api.delete_series(sid)
        if not ok:
            return jsonify({
                "success": False,
                "error": "Échec de la suppression dans Kavita.",
            }), 502
        # Purger du cache local MetaKavita (chirurgicalement, sans toucher aux autres)
        from db_manager import purge_single_series_from_all_caches
        purge_single_series_from_all_caches(sid)
        try:
            from flask_socketio import emit as _emit
            _emit("series_removed", {"series_id": sid}, namespace="/", broadcast=True)
        except Exception:
            pass
        return jsonify({
            "success": True,
            "message": t.get(
                "audit_empty_series_purged",
                "Série vide supprimée de Kavita avec succès.",
            ),
        })
    except Exception as e:
        return jsonify({"success": False, "error": safe_exc_str(e)}), 500
