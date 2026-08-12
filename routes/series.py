"""
Blueprint des actions par série : overrides manuels, ignorer/inclure, recherche
et application de couvertures.

⚠️ Endpoints réels : 'series.save_override', 'series.toggle_ignore',
'series.get_series_covers', 'series.apply_series_cover'.
"""

import logging

from flask import Blueprint, request, jsonify

from config_manager import load_config
from db_manager import get_all_cached_data, update_status, save_series_override
from kavita_api import KavitaAPI
from models import SeriesOverride
from services.cover_search import collect_covers_http
from services.kavita_payload import mark_cover_manual, release_cover_manual
from secure_logging import safe_exc_str
from translations import translations

series_bp = Blueprint('series', __name__)


@series_bp.route('/save-override', methods=['POST'])
def save_override():
    series_id = request.form.get('series_id')
    forced_id = request.form.get('forced_id', '').strip()
    alt_title = request.form.get('alternative_title', '').strip()
    forced_provider = request.form.get('forced_provider', 'AUTO').strip()
    targeted_fields = request.form.get('targeted_fields', 'ALL').strip()
    publisher_pref = request.form.get('publisher_pref', 'GLOBAL').strip()
    alt_title_langs = request.form.get('alt_title_langs', '').strip()

    save_series_override(SeriesOverride(
        series_id=int(series_id),
        forced_id=forced_id,
        alternative_title=alt_title,
        forced_provider=forced_provider,
        targeted_fields=targeted_fields,
        publisher_pref=publisher_pref,
        alt_title_langs=alt_title_langs,
    ))
    return "OK", 200


@series_bp.route('/toggle-ignore', methods=['POST'])
def toggle_ignore():
    series_id = request.form.get('series_id')
    current_status = request.form.get('current_status')
    if not series_id: return jsonify(success=False)

    new_status = 'IGNORED' if current_status != 'IGNORED' else 'PENDING'
    update_status(int(series_id), new_status)
    # Une série ignorée ne doit plus apparaître dans la file de review.
    if new_status == 'IGNORED':
        try:
            from db_manager import delete_pending_by_series
            from services.manual_review import emit_pending_count
            deleted = delete_pending_by_series(int(series_id))
            if deleted:
                emit_pending_count()
        except Exception as e:
            logging.debug("ignore-series orphan purge failed: %s", safe_exc_str(e))
    return jsonify(success=True, new_status=new_status)


@series_bp.route('/api/series/<int:series_id>/covers', methods=['GET'])
def get_series_covers(series_id):
    series_name = request.args.get('series_name') or ""
    cache_data = get_all_cached_data().get(series_id, {})

    config = load_config()
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
    library_type = kavita.get_library_type_for_series(series_id)
    script_root = request.script_root or ""

    covers = collect_covers_http(
        cache_data,
        series_name,
        library_type,
        script_root=script_root,
        max_covers=20,
        max_workers=8,
    )
    return jsonify({"success": True, "covers": covers})


@series_bp.route('/api/series/<int:series_id>/update-cover', methods=['POST'])
def apply_series_cover(series_id):
    cover_url = request.json.get('cover_url')
    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))

    success, msg = kavita.upload_series_cover(series_id, cover_url)

    if success:
        # Marque la provenance manuelle : ni le statut (IGNORED / COMPLETED / …)
        # ni les champs ciblés de l'utilisateur ne sont touchés.
        mark_cover_manual(series_id)
        logging.info(
            t.get(
                "log_cover_marked_manual",
                "🔒 [{0}] Couverture marquée comme choix manuel (protégée des scrapings automatiques).",
            ).format(series_id)
        )

    return jsonify({"success": success, "msg": msg, "cover_manual": bool(success)})


@series_bp.route('/api/series/<int:series_id>/release-cover', methods=['POST'])
def release_series_cover(series_id):
    """Rend une couverture manuelle à la gestion automatique (clic sur la cartouche).

    Le pendant de masse est l'interrupteur `COVER_FORCE_OVERWRITE` : ici on
    libère une série, là on écrase tout un run sans clic.
    """
    release_cover_manual(series_id)
    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    logging.info(
        t.get(
            "log_cover_released",
            "🔓 [{0}] Couverture rendue à la gestion automatique.",
        ).format(series_id)
    )
    return jsonify({"success": True, "cover_manual": False})


@series_bp.route('/api/series/<int:series_id>/seal-locks', methods=['POST'])
def seal_series_locks(series_id):
    """Rescelle les verrous Kavita (après NEEDS_RELOCK) sans re-scraper."""
    config = load_config()
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    if not kavita.authenticate():
        return jsonify(success=False, error=t.get("err_kavita_auth_failed", "Auth Kavita échouée")), 502

    ok, msg = kavita.seal_series_locks(series_id)
    if not ok:
        return jsonify(success=False, error=msg), 502

    update_status(int(series_id), 'COMPLETED')
    try:
        from services.kavita_payload import _emit_series_status
        cache = get_all_cached_data().get(int(series_id), {})
        _emit_series_status(series_id, 'COMPLETED', cache.get('alternative_title') or '')
    except Exception as e:
        logging.debug("seal-locks status emit failed: %s", safe_exc_str(e))
    return jsonify(success=True, status='COMPLETED', message=msg)


@series_bp.route('/api/series/seal-locks-pending', methods=['POST'])
def seal_all_needs_relock():
    """Rescelle toutes les séries en statut NEEDS_RELOCK."""
    config = load_config()
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
    if not kavita.authenticate():
        return jsonify(success=False, error=t.get("err_kavita_auth_failed", "Auth Kavita échouée")), 502

    cached = get_all_cached_data()
    targets = [sid for sid, row in cached.items() if (row or {}).get('status') == 'NEEDS_RELOCK']
    sealed = []
    failed = []
    from services.kavita_payload import _emit_series_status
    for sid in targets:
        ok, msg = kavita.seal_series_locks(sid)
        if ok:
            update_status(int(sid), 'COMPLETED')
            _emit_series_status(sid, 'COMPLETED')
            sealed.append(int(sid))
        else:
            failed.append({"series_id": int(sid), "error": msg})
    return jsonify(
        success=True,
        sealed_count=len(sealed),
        failed_count=len(failed),
        sealed=sealed,
        failed=failed,
    )
