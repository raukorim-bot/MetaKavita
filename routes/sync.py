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
import secrets
import time

from flask import Blueprint, request, jsonify, Response

from config_manager import load_config
from db_manager import (
    get_all_cached_data,
    get_auto_sync_report_badge,
    get_latest_auto_sync_report,
    mark_auto_sync_report_read,
    reset_errors,
)
from kavita_api import KavitaAPI
from secure_logging import series_label
from translations import translations
from services.background_tasks import (
    set_batch_enqueue_enabled,
    is_batch_enqueue_enabled,
    drain_sync_queue,
    detach_batch_from_ram,
    hydrate_batch_queue_to_ram,
    make_sync_item,
    register_batch_enqueue,
    register_batch_enqueue_if_first,
    put_sync,
    put_front,
    is_auto_sync_waiting,
    _auto_sync_enabled,
    broadcast_auto_sync_report,
)
from services import batch_queue as batch_queue_svc

sync_bp = Blueprint('sync', __name__)

# Inventaire Kavita mis en cache pour la durée d'un batch (voir _get_batch_inventory).
_BATCH_INVENTORY_TTL = 900  # secondes ; filet de sécurité, pas le mécanisme normal
_batch_inventory_cache = {}

# Once-per-process: prefer X-Webhook-Token; ?token= is legacy (BF63 / B15).
_webhook_query_token_warned = False


def _get_batch_inventory(kavita, library_id, force_refresh):
    """Inventaire Kavita pour `/batch-sync`, réutilisé entre les paquets d'UN batch.

    Le front (voir `batch.js`) découpe un batch en paquets d'environ 50 séries
    et poste un `/batch-sync` par paquet. Sans ce cache, chaque paquet
    déclenchait un appel complet à `get_all_series()` — sur 1000 séries en 20
    paquets, 20 aller-retours HTTP identiques vers Kavita, et 20 purges du
    cache mémoire des types de bibliothèque (voir
    `kavita_api.py::get_all_series`). Le premier paquet d'un batch
    (`resume_enqueue=true`) force un instantané frais ; les paquets suivants du
    même batch réutilisent cet instantané. Le TTL borne la durée de vie de ce
    cache pour un batch anormalement long ou interrompu ; ce n'est pas ainsi
    qu'un batch normal se rafraîchit.
    """
    key = (getattr(kavita, 'url', None), getattr(kavita, 'api_key', None), library_id)
    now = time.time()
    cached = _batch_inventory_cache.get(key)
    if not force_refresh and cached and (now - cached[0]) < _BATCH_INVENTORY_TTL:
        return cached[1]
    series = kavita.get_all_series(library_id=library_id)
    _batch_inventory_cache[key] = (now, series)
    return series


@sync_bp.route('/reset-errors', methods=['POST'])
def amnistie():
    reset_errors()
    return jsonify(success=True)


@sync_bp.route('/force-sync', methods=['POST'])
def force_sync():
    """Met UNE série en tête de la file de synchronisation.

    L'enrichissement ne s'exécute plus dans la requête : il durait de quelques
    secondes à plusieurs minutes (scrapers, écritures Kavita, éventuel parking en
    review), pendant lesquelles le worker eventlet restait bloqué et le
    reverse-proxy pouvait couper la connexion. L'utilisateur voyait alors « Fail »
    sur un traitement qui se terminait en réalité correctement, et la série
    tournait en parallèle du worker de fond au lieu d'être sérialisée avec lui.

    Réponse 202 : le travail est accepté, pas terminé. L'UI suit la fin via
    l'événement Socket.IO `series_status` de la série (voir batch.js).
    """
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    series_id = request.form.get('series_id')
    series_name = request.form.get('series_name')
    if not series_id or not series_name:
        return jsonify(success=False, msg=t.get('err_missing'))

    try:
        series_id_int = int(series_id)
    except (TypeError, ValueError):
        return jsonify(success=False, msg=t.get('err_missing')), 400

    payload_json = request.get_json(silent=True) or {}

    def _truthy(val):
        if val is None:
            return False
        return str(val).lower() in ("true", "1", "yes")

    want_super = _truthy(request.form.get("super_review")) or _truthy(
        payload_json.get("super_review") or payload_json.get("superReview")
    )
    want_review = _truthy(request.form.get("manual_review_override")) or _truthy(
        payload_json.get("manual_review_override") or payload_json.get("manualReviewOverride")
    )
    if want_super:
        want_review = False

    # En tête de file : le clic vient d'un humain qui regarde sa série, il passe
    # devant le reste d'un batch en cours. Sans toucher aux jobs déjà en attente
    # (`replace_pending=False`) : le lot est constitué par l'utilisateur, et une
    # ligne retirée d'une file en pause ne revient jamais.
    put_front(
        make_sync_item(
            series_id_int,
            series_name,
            True,
            origin="row",
            super_review=want_super,
            manual_review_override=want_review,
        ),
        replace_pending=False,
    )
    logging.info(
        t.get(
            "log_force_sync_queued",
            "⚡ Série {0} placée en tête de la file de synchronisation.",
        ).format(series_label(series_name, series_id_int))
    )
    return jsonify(
        success=True,
        queued=True,
        series_id=series_id_int,
        msg=t.get("msg_force_sync_queued", "Série mise en file."),
    ), 202


@sync_bp.route('/batch-sync', methods=['POST'])
def batch_sync():
    """Ajouter des séries à la file batch persistante (+ RAM si non pausée)."""
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    # Premier paquet d'un ajout UI : inventaire frais. Append autorisé si un batch
    # tourne déjà (file persistante) — new_batch=False pour ne pas reset les compteurs.
    is_first_chunk = request.form.get('resume_enqueue') == 'true'
    if is_first_chunk:
        set_batch_enqueue_enabled(True)
    else:
        if not is_batch_enqueue_enabled():
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

    all_series = _get_batch_inventory(kavita, lib_id, force_refresh=is_first_chunk)
    cached = get_all_cached_data()

    if not selected_ids:
        series_to_process = [
            s for s in all_series
            if cached.get(s['id'], {}).get('status') not in ('IGNORED', 'PENDING_REVIEW')
        ]
    else:
        series_to_process = [s for s in all_series if str(s['id']) in selected_ids]

    if not series_to_process:
        return jsonify(success=False, msg=t.get('err_no_sel_or_empty', "Aucune série à traiter."))

    if not is_batch_enqueue_enabled():
        return jsonify(
            success=False,
            rejected=True,
            msg=t.get('batch_stopped', "Batch arrêté."),
        ), 409

    payload = [
        {
            "series_id": s["id"],
            "series_name": s.get("name") or "",
            "force_update": force_update,
            "fields_override": fields_override,
        }
        for s in series_to_process
    ]
    was_paused = batch_queue_svc.is_paused()
    result = batch_queue_svc.enqueue_items(payload)
    added = int(result.get("added") or 0)
    skipped = int(result.get("skipped_dupes") or 0)
    hydrated = 0
    resumed = False

    log_msg = t.get('log_batch_added', "🚀 {0} série(s) ajoutée(s) (Total : {1})")
    logging.info(log_msg.format(added, result.get("count") or 0))

    # Lancer / Ajouter via UI : si la file était en pause, lever la pause et
    # hydrater toute la file SQLite (anciens + nouveaux), comme « Reprendre ».
    if was_paused:
        batch_queue_svc.set_paused(False)
        set_batch_enqueue_enabled(True)
        hydrated = hydrate_batch_queue_to_ram()
        resumed = True
    elif added:
        # « Ce paquet ouvre-t-il un nouveau lot ? » se décide au moment
        # d'incrémenter les compteurs, pas ici : entre la lecture de l'état et
        # cette ligne, le handler a rendu la main quatre fois (authentification
        # Kavita, inventaire, cache, file SQLite), le temps qu'un second
        # /batch-sync passe et remette la barre à zéro à mi-parcours du premier.
        if is_first_chunk:
            register_batch_enqueue_if_first(added)
        else:
            register_batch_enqueue(added, new_batch=False)
        for item in result.get("items") or []:
            put_sync(
                make_sync_item(
                    item["series_id"],
                    item["series_name"],
                    item["force_update"],
                    item.get("fields_override"),
                    is_batch=True,
                )
            )

    paused = batch_queue_svc.is_paused()
    msg = t.get('batch_queue_added', "{0} added to queue ({1} already queued skipped).").format(
        added, skipped
    )
    return jsonify(
        success=True,
        msg=msg,
        added=added,
        skipped_dupes=skipped,
        paused=paused,
        resumed=resumed,
        hydrated=hydrated,
        count=result.get("count") or 0,
    )


@sync_bp.route('/api/batch-queue', methods=['GET'])
def api_batch_queue_list():
    return jsonify(success=True, **batch_queue_svc.snapshot_status())


@sync_bp.route('/api/batch-queue/<item_id>', methods=['DELETE'])
def api_batch_queue_remove(item_id):
    status = batch_queue_svc.cancel_item(item_id)
    if status == "running":
        return jsonify(success=False, error="running"), 409
    if status == "missing":
        return jsonify(success=False, error="missing"), 404
    # Item éventuellement encore en RAM : le worker le skippera (should_skip).
    return jsonify(success=True, **batch_queue_svc.snapshot_status())


@sync_bp.route('/api/batch-queue/clear', methods=['POST'])
def api_batch_queue_clear():
    n = batch_queue_svc.cancel_all_queued()
    detach_batch_from_ram()
    if not batch_queue_svc.is_paused():
        # running éventuel est toujours en cours dans le worker ; queued hydratés = 0
        pass
    return jsonify(success=True, cleared=n, **batch_queue_svc.snapshot_status())


@sync_bp.route('/api/batch-queue/pause', methods=['POST'])
def api_batch_queue_pause():
    batch_queue_svc.set_paused(True)
    drained = detach_batch_from_ram()
    return jsonify(success=True, drained=drained, **batch_queue_svc.snapshot_status())


@sync_bp.route('/api/batch-queue/resume', methods=['POST'])
def api_batch_queue_resume():
    batch_queue_svc.set_paused(False)
    set_batch_enqueue_enabled(True)
    n = hydrate_batch_queue_to_ram()
    return jsonify(success=True, hydrated=n, **batch_queue_svc.snapshot_status())


@sync_bp.route('/stop-batch', methods=['POST'])
def stop_batch():
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    set_batch_enqueue_enabled(False)
    cancelled = batch_queue_svc.cancel_all_pending()
    drained = drain_sync_queue()
    if drained == 0:
        from services.background_tasks import broadcast_batch_progress
        broadcast_batch_progress(0, stopped=True)
    logging.info(
        t.get('log_batch_stopped')
        + t.get("log_batch_drained_suffix", " ({0} en attente retirée(s))").format(drained)
        + f" [sqlite cancelled={cancelled}]"
    )
    return jsonify(
        success=True,
        msg=t.get('batch_stopped'),
        drained=drained,
        cancelled=cancelled,
        **batch_queue_svc.snapshot_status(),
    )


@sync_bp.route('/api/auto-sync/status', methods=['GET'])
def auto_sync_status():
    """État Auto-sync pour la barre Stop et la ligne SignalR (modale Config)."""
    config = load_config()
    from services.auto_sync import normalize_trigger
    hub = {"status": "disconnected", "last_error": ""}
    try:
        from services.kavita_hub import hub_public_status
        hub = hub_public_status()
    except Exception:
        pass
    return jsonify(
        waiting_auto=is_auto_sync_waiting(),
        enabled=_auto_sync_enabled(config),
        trigger=normalize_trigger(config.get("AUTO_SYNC_TRIGGER")),
        hub=hub,
        report=get_auto_sync_report_badge(),
    )


@sync_bp.route('/api/auto-sync/report', methods=['GET'])
def auto_sync_report():
    """Dernière vague Auto-sync (séries, totaux). Pas le lot du tableau de bord."""
    payload = get_latest_auto_sync_report()
    payload["badge"] = payload.get("badge") or get_auto_sync_report_badge()
    return jsonify(payload)


@sync_bp.route('/api/auto-sync/report/read', methods=['POST'])
def auto_sync_report_read():
    """Ouvrir la modale d'un rapport terminé le marque lu et cache le bouton."""
    mark_auto_sync_report_read()
    badge = get_auto_sync_report_badge()
    broadcast_auto_sync_report(badge)
    return jsonify(success=True, report=badge)


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
    t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
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
    # The query form is deliberately kept working (legacy / deprecated, BF63). Existing
    # users have already pasted `?token=...` URLs into automation, and breaking those
    # silently would stop their pipelines with no error they could see — so this stays
    # additive, and the header simply wins when both are present.
    header_token = request.headers.get('X-Webhook-Token')
    query_token = request.args.get('token')
    token = header_token or query_token

    global _webhook_query_token_warned
    if query_token and not header_token and not _webhook_query_token_warned:
        _webhook_query_token_warned = True
        logging.warning(
            "⚠️ [Webhook] Auth via ?token= (legacy). Prefer the X-Webhook-Token header — "
            "query tokens appear in proxy access logs / Referer / browser history."
        )

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
        logging.warning(t.get("log_webhook_unauthorized", "🚨 [Sécurité] Tentative d'accès au webhook bloquée (Jeton invalide)."))
        return jsonify(success=False, code="unauthorized", message="Unauthorized"), 401

    payload = request.get_json(silent=True) or request.form or {}

    def _truthy(val):
        if val is None:
            return False
        return str(val).lower() in ("true", "1", "yes")

    # Companion / clients : sonde auth sans enfiler de job (évite le spam "missing seriesId").
    if _truthy(payload.get("probe")) or _truthy(request.args.get("probe")):
        return jsonify(success=True, probe=True), 200

    series_id = payload.get("seriesId") or payload.get("SeriesId") or payload.get("series_id")
    series_name = payload.get("name") or payload.get("Name") or payload.get("series_name")

    force_param = (
        payload.get("force")
        or payload.get("force_update")
        or payload.get("forceUpdate")
        or request.args.get("force")
    )
    force_update = _truthy(force_param) if force_param is not None else False
    # C33 Companion : Super Review one-shot > Auto one-shot si les deux sont posés.
    want_super = _truthy(payload.get("super_review") or payload.get("superReview"))
    want_auto = _truthy(payload.get("auto") or payload.get("force_auto") or payload.get("forceAuto"))
    if want_super:
        want_auto = False
    # Companion one-shots must not be skipped as "already up to date".
    if want_super or want_auto:
        force_update = True

    if not series_id:
        logging.warning(
            t.get(
                "log_webhook_ignored",
                "⚠️ [Webhook] Événement ignoré : champ 'seriesId' manquant dans le payload.",
            )
        )
        return jsonify(
            success=False,
            code="missing_series_id",
            message=t.get("msg_webhook_missing_fields", "Champs requis manquants"),
        ), 400

    try:
        series_id_int = int(series_id)
    except (TypeError, ValueError):
        return jsonify(
            success=False,
            code="invalid_series_id",
            message=t.get("msg_webhook_invalid_series_id", "seriesId invalide"),
        ), 400

    if not series_name:
        # C33 : seriesId seul — résoudre le nom via l'API Kavita (pas de scrape DOM).
        kavita = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
        series, resolve_err = kavita.fetch_series(series_id_int, timeout=8)
        if not series:
            if resolve_err in ("kavita_auth", "kavita_unreachable"):
                logging.warning(
                    t.get(
                        "log_webhook_kavita_unreachable",
                        "⚠️ [Webhook] Kavita injoignable pour résoudre {0} ({1}).",
                    ).format(series_label(None, series_id_int), resolve_err)
                )
                return jsonify(
                    success=False,
                    code=resolve_err or "kavita_unreachable",
                    message=t.get(
                        "msg_webhook_kavita_unreachable",
                        "Kavita injoignable",
                    ),
                ), 503
            logging.warning(
                t.get(
                    "log_webhook_series_not_found",
                    "⚠️ [Webhook] Série introuvable côté Kavita : {0}.",
                ).format(series_label(None, series_id_int))
            )
            return jsonify(
                success=False,
                code="series_not_found",
                message=t.get("msg_webhook_series_not_found", "Série introuvable"),
            ), 404
        series_name = (
            series.get("name")
            or series.get("Name")
            or series.get("originalName")
            or ""
        ).strip()
        if not series_name:
            return jsonify(
                success=False,
                code="series_not_found",
                message=t.get("msg_webhook_series_not_found", "Série introuvable"),
            ), 404

    item = make_sync_item(
        series_id_int,
        series_name,
        force_update,
        super_review=want_super,
        force_auto=want_auto,
        origin="webhook",
    )
    replaced = 0
    if want_super or want_auto:
        replaced = put_front(item)
    else:
        put_sync(item)
    mode_str = t.get("log_webhook_force_mode", " (⚠️ Mode Forcé)") if force_update else ""
    if want_super:
        mode_str += t.get("log_webhook_super_mode", " (Super Review)")
    elif want_auto:
        mode_str += t.get("log_webhook_auto_mode", " (Auto)")
    if want_super or want_auto:
        mode_str += t.get("log_webhook_priority", " (priorité Companion)")
    logging.info(
        t.get(
            "log_webhook_received",
            "⚡ [Webhook] Événement reçu ! Série {0}{1} ajoutée à la file.",
        ).format(series_label(series_name, series_id_int), mode_str)
    )
    if replaced:
        logging.info(
            t.get(
                "log_webhook_replaced",
                "⚡ [Webhook] Série {0} : {1} job(s) en attente remplacé(s) par Companion.",
            ).format(series_label(series_name, series_id_int), replaced)
        )
    return jsonify(
        success=True,
        message=t.get("webhook_event_received", "Event reçu"),
        series_id=series_id_int,
        series_name=series_name,
        force_update=force_update,
        force_auto=want_auto,
        super_review=want_super,
        replaced_pending=replaced,
        priority=bool(want_super or want_auto),
    ), 200
