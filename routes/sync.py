"""
Blueprint de synchronisation : déclenchement manuel/lot, webhook entrant,
export des erreurs.

⚠️ Endpoints réels : 'sync.force_sync', 'sync.batch_sync', 'sync.stop_batch',
'sync.amnistie' (reset-errors), 'sync.export_errors', 'sync.webhook'.
'sync.webhook' est whitelisté dans `require_login` (app.py) car il utilise sa
propre authentification par jeton — gardez ce nom synchronisé si vous le
renommez.
"""

import logging
import queue
import secrets

from flask import Blueprint, request, jsonify, Response

from config_manager import load_config, is_library_enabled
from db_manager import get_all_cached_data, reset_errors
from kavita_api import KavitaAPI
from translations import translations
from services.background_tasks import (
    sync_queue,
    set_batch_enqueue_enabled,
    is_batch_enqueue_enabled,
    drain_sync_queue,
)
from services.enrichment_engine import enrich_series

sync_bp = Blueprint('sync', __name__)


@sync_bp.route('/reset-errors', methods=['POST'])
def amnistie():
    reset_errors()
    return jsonify(success=True)


@sync_bp.route('/force-sync', methods=['POST'])
def force_sync():
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    series_id = request.form.get('series_id')
    series_name = request.form.get('series_name')
    if not series_id or not series_name: return jsonify(success=False, msg=t.get('err_missing'))

    success, result_msg, _ = enrich_series(series_id, series_name, force_update=True)
    return jsonify(success=success, msg=result_msg)


@sync_bp.route('/batch-sync', methods=['POST'])
def batch_sync():
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    # Premier paquet d'un nouveau batch : réarme l'acceptation après un Stop.
    if request.form.get('resume_enqueue') == 'true':
        set_batch_enqueue_enabled(True)
    elif not is_batch_enqueue_enabled():
        return jsonify(
            success=False,
            rejected=True,
            msg=t.get('batch_stopped', "Batch arrêté."),
        ), 409

    library_id = request.form.get('library_id')
    force_update = request.form.get('force_update') == 'true'
    selected_ids = request.form.getlist('selected_series')
    raw_fields = request.form.get('targeted_fields')
    fields_override = None
    if raw_fields is not None:
        cleaned = raw_fields.strip()
        if cleaned and cleaned != 'ALL':
            fields_override = cleaned

    lib_id = library_id if library_id and library_id != "" and library_id != "None" else None

    config = load_config()
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))

    if not kavita.authenticate():
        return jsonify(success=False, msg=t.get('err_kavita', "Connexion échouée."))

    all_series = kavita.get_all_series(library_id=lib_id)
    cached = get_all_cached_data()

    if not selected_ids:
        # Si aucune case n'est cochée (batch global), on exclut les ignorés
        # et les séries déjà garées en review manuelle (évite les doublons).
        series_to_process = [
            s for s in all_series
            if cached.get(s['id'], {}).get('status') not in ('IGNORED', 'PENDING_REVIEW')
        ]
    else:
        # Si l'utilisateur a COCHÉ des séries spécifiques, ON LES TRAITE TOUTES,
        # même si elles étaient marquées comme IGNORED !
        series_to_process = [s for s in all_series if str(s['id']) in selected_ids]

    if not series_to_process:
        return jsonify(success=False, msg=t.get('err_no_sel_or_empty', "Aucune série à traiter."))

    # Re-check après le travail I/O : un Stop a pu arriver pendant get_all_series.
    if not is_batch_enqueue_enabled():
        return jsonify(
            success=False,
            rejected=True,
            msg=t.get('batch_stopped', "Batch arrêté."),
        ), 409

    current_size = sync_queue.qsize()
    total_after_add = current_size + len(series_to_process)
    log_msg = t.get('log_batch_added', "🚀 {0} série(s) ajoutée(s) (Total : {1})")
    logging.info(log_msg.format(len(series_to_process), total_after_add))

    for s in series_to_process:
        if fields_override is not None:
            sync_queue.put((s['id'], s['name'], force_update, fields_override))
        else:
            sync_queue.put((s['id'], s['name'], force_update))

    msg_added = t.get('batch_added').replace('{}', str(len(series_to_process)))
    return jsonify(success=True, msg=msg_added)


@sync_bp.route('/stop-batch', methods=['POST'])
def stop_batch():
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    set_batch_enqueue_enabled(False)
    drained = drain_sync_queue()
    # drain_sync_queue émet déjà stopped si items retirés ; sinon forcer le reset UI
    # (job en cours seul, file déjà vide).
    if drained == 0:
        from services.background_tasks import broadcast_batch_progress
        broadcast_batch_progress(0, stopped=True)
    logging.info(t.get('log_batch_stopped') + f" ({drained} en attente retirée(s))")
    return jsonify(success=True, msg=t.get('batch_stopped'), drained=drained)


@sync_bp.route('/export-errors', methods=['GET'])
def export_errors():
    config = load_config()
    t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])
    all_series = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY')).get_all_series()
    cached = get_all_cached_data()

    error_lines = [f"{t.get('report_title')}\n", "="*50, "\n\n"]
    for s in all_series:
        if cached.get(s['id'], {}).get('status') == 'NOT_FOUND':
            error_lines.append(f"- {s['name']} ({t.get('report_item')} {s['id']})\n")

    return Response("".join(error_lines), mimetype="text/plain", headers={"Content-disposition": "attachment; filename=metakavita_erreurs.txt"})


@sync_bp.route('/webhook', methods=['POST'])
def webhook():
    config = load_config()
    webhook_token = config.get('WEBHOOK_TOKEN', '')

    # The token may arrive either as the `X-Webhook-Token` header or as the historical
    # `?token=` query parameter.
    #
    # The header is preferred and is what new integrations should use, because a query
    # string is echoed into places a secret should never reach: reverse-proxy and web
    # server access logs (nginx and Traefik both log the full request line by default),
    # browser history, and `Referer` headers on any onward request. A header is not
    # logged by default anywhere in that chain.
    #
    # The query form is deliberately kept working. Existing users have already pasted
    # `?token=...` URLs into their Kavita webhook settings, and breaking those silently
    # would stop their automation with no error they could see — so this is additive,
    # and the header simply wins when both are present.
    token = request.headers.get('X-Webhook-Token') or request.args.get('token')

    # `secrets.compare_digest` raises TypeError on `str` arguments containing
    # non-ASCII characters, so a token with an accent or an emoji in it would turn a
    # failed authentication into an unhandled 500. Comparing the UTF-8 bytes avoids
    # that entirely while keeping the constant-time property, and mirrors the same
    # defensive pattern already used in routes/auth.py.
    token_ok = False
    if token and webhook_token:
        try:
            token_ok = secrets.compare_digest(
                token.encode('utf-8'),
                webhook_token.encode('utf-8'),
            )
        except (TypeError, ValueError):
            token_ok = False

    if not token_ok:
        logging.warning("🚨 [Sécurité] Tentative d'accès au webhook bloquée (Jeton invalide).")
        return jsonify(success=False, message="Unauthorized"), 401

    payload = request.get_json(silent=True) or request.form or {}
    series_id = payload.get("seriesId") or payload.get("SeriesId") or payload.get("series_id")
    series_name = payload.get("name") or payload.get("Name") or payload.get("series_name")

    force_param = payload.get("force") or payload.get("force_update") or payload.get("forceUpdate") or request.args.get('force')
    force_update = str(force_param).lower() in ['true', '1', 'yes'] if force_param is not None else False

    if series_id and series_name:
        # Respecte DISABLED_LIBRARIES : pas d'enrichissement hors périmètre sync
        try:
            kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
            series = kavita.get_series(series_id) if kavita.authenticate() else None
            lib_id = (series or {}).get('libraryId')
            if lib_id is not None and not is_library_enabled(lib_id, config):
                logging.info(
                    "⏸️ [Webhook] Série '%s' (ID: %s) ignorée — bibliothèque %s désactivée.",
                    series_name, series_id, lib_id,
                )
                return jsonify(
                    success=True,
                    message="Bibliothèque désactivée — événement ignoré",
                    skipped=True,
                ), 200
        except Exception as e:
            logging.warning("⚠️ [Webhook] Impossible de vérifier la bibliothèque : %s", e)

        sync_queue.put((series_id, series_name, force_update))
        mode_str = " (⚠️ Mode Forcé)" if force_update else ""
        logging.info(f"⚡ [Webhook] Événement reçu ! Série '{series_name}' (ID: {series_id}){mode_str} ajoutée à la file.")
        return jsonify(success=True, message="Event reçu", force_update=force_update), 200

    logging.warning("⚠️ [Webhook] Événement ignoré : champs 'seriesId' ou 'name' manquants dans le payload.")
    return jsonify(success=False, message="Champs requis manquants"), 400
