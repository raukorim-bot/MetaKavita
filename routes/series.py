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
from secure_logging import safe_exc_str, series_label
from translations import translations

series_bp = Blueprint('series', __name__)


def _series_log_label(series_id, name=None, kavita=None):
    """Étiquette Live Logs : nom + id, avec repli Kavita si le front n'a pas envoyé le titre."""
    text = str(name or "").strip()
    if not text and kavita is not None:
        try:
            series = kavita.get_series(series_id) or {}
            text = (
                series.get("name")
                or series.get("Name")
                or series.get("originalName")
                or ""
            ).strip()
        except Exception:
            text = ""
    return series_label(text, series_id)


@series_bp.route('/save-override', methods=['POST'])
def save_override():
    series_id = request.form.get('series_id')
    forced_id = request.form.get('forced_id', '').strip()
    alt_title = request.form.get('alternative_title', '').strip()
    forced_provider = request.form.get('forced_provider', 'AUTO').strip()
    # Masque de champs ciblés : absent = « tout » (appelants qui ne gèrent pas
    # le granulaire), mais présent et vide = « aucun ». Sans cette distinction,
    # décocher toutes les cases et enregistrer stockait une chaîne vide, que
    # `resolve_active_fields` relit comme « ALL » : la série se remettait à tout
    # écrire alors que l'utilisateur venait de tout décocher. Le piège devient
    # atteignable sans le moindre clic sur les cases depuis le retrait du champ
    # « Sens lecture » — un panneau dont le masque enregistré ne contenait que
    # lui s'ouvre désormais entièrement décoché.
    raw_targeted_fields = request.form.get('targeted_fields')
    targeted_fields = 'ALL' if raw_targeted_fields is None else (raw_targeted_fields.strip() or 'NONE')
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
    body = request.get_json(silent=True) or {}
    cover_url = body.get('cover_url')
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
            ).format(_series_log_label(series_id, body.get("series_name"), kavita))
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
    body = request.get_json(silent=True) or {}
    kavita = None
    if not str(body.get("series_name") or "").strip():
        kavita = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
    logging.info(
        t.get(
            "log_cover_released",
            "🔓 [{0}] Couverture rendue à la gestion automatique.",
        ).format(_series_log_label(series_id, body.get("series_name"), kavita))
    )
    return jsonify({"success": True, "cover_manual": False})


@series_bp.route('/api/series/<int:series_id>/seal-locks', methods=['POST'])
def seal_series_locks(series_id):
    """Rescelle les verrous Kavita (après NEEDS_RELOCK) sans re-scraper.

    Aucune liste de verrous n'est transmise, à dessein : le bouton 🔒 est une
    action manuelle qui arrive après coup, souvent bien après la passe soft-fail
    (voire après un redémarrage), et rien ne mémorise ce que cette passe avait
    écrit. `targeted_fields` du cache ne peut pas tenir ce rôle : c'est le masque
    souhaité par l'utilisateur, pas la trace d'une écriture — une passe où le
    fournisseur n'a rendu aucun éditeur laisse `publisherLocked` intact alors que
    « publisher » est dans le masque, et s'en servir comme liste de verrous
    refermerait justement des champs jamais écrits. Le repli de
    `seal_series_locks` (« scelle ce qui porte du contenu, ne rouvre rien »)
    correspond exactement à ce que le bouton promet.
    """
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
    """Rescelle toutes les séries en statut NEEDS_RELOCK.

    Même repli que l'action unitaire ci-dessus, et pour la même raison : la liste
    des verrous posés n'est mémorisée nulle part. Une série dont toutes les
    métadonnées sont vides ne verra donc aucun verrou se fermer, et passera
    malgré tout en COMPLETED — c'est voulu : le statut dit que Kavita a accepté
    les deux POST, pas qu'un verrou de plus a été fermé.
    """
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
