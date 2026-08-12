"""
Handlers Socket.IO : authentification à la connexion et streaming des
couvertures de séries trouvées par les scrapers (une émission par fournisseur,
au fil de l'eau, pour un affichage progressif côté UI).

Ce module ne définit aucune route Flask : il enregistre ses handlers en
décorant directement l'instance partagée `extensions.socketio`. Il suffit de
l'importer une fois (pour effet de bord) depuis app.py, après
`socketio.init_app(app)`, pour que les handlers soient actifs.
"""

import logging

from flask import request
from flask_socketio import disconnect

import auth_manager
from extensions import socketio
from config_manager import load_config
from db_manager import get_all_cached_data
from kavita_api import KavitaAPI
from services.cover_search import iter_cover_jobs, run_cover_job
from translations import get_ui_translations


def _companion_embed_series(auth=None):
    """`series_id` du jeton d'embed présenté par cette connexion, sinon None.

    La valeur vient du jeton lui-même, jamais du `series_id` fourni par le
    client : ce dernier ne sert qu'à vérifier que les deux concordent.

    Relu à chaque événement plutôt que mémorisé à la connexion : le client passe
    le jeton dans la query string du handshake (`static/js/websocket.js`), donc
    `request.args` reste lisible pendant toute la vie de la socket — et un jeton
    révoqué ou expiré cesse d'agir immédiatement, sans attendre une reconnexion.
    """
    try:
        from services.companion_embed_auth import peek_embed_token, validate_embed_token

        payload = auth if isinstance(auth, dict) else {}
        token = (
            str(payload.get("embed_token") or payload.get("embedToken") or "").strip()
            or (request.args.get("embed_token") or request.args.get("embedToken") or "").strip()
        )
        if not token:
            return None
        sid_raw = (
            payload.get("series_id")
            or payload.get("seriesId")
            or request.args.get("series_id")
            or request.args.get("seriesId")
        )
        if sid_raw is not None and str(sid_raw).strip() != "":
            data = validate_embed_token(token, int(sid_raw))
        else:
            data = peek_embed_token(token)
        if not data:
            return None
        return int(data["series_id"])
    except Exception:
        return None


def _companion_socket_authorized(auth=None) -> bool:
    """Accept Companion embed_token from Socket.IO auth/query (cross-origin iframe)."""
    return _companion_embed_series(auth) is not None


def _reject_unauthenticated(event_name):
    """True (et socket fermée) si l'émetteur n'a pas de session valide.

    Défense en profondeur : le rejet à la connexion ci-dessous suffit en théorie,
    mais il ne tient qu'à la bonne interprétation d'un paquet de refus par le
    client. Chaque handler qui déclenche un travail réel vérifie donc lui-même,
    pour qu'un client qui émettrait avant d'avoir été éjecté ne fasse rien.
    """
    if auth_manager.is_authenticated() or _companion_socket_authorized():
        return False
    t = get_ui_translations()
    logging.warning(t.get("log_ws_event_rejected", "🚨 [Sécurité] Événement WebSocket '{0}' rejeté (Non authentifié) IP: {1}").format(event_name, request.remote_addr))
    disconnect()
    return True


@socketio.on('connect')
def handle_connect(auth=None):
    """Refuse toute connexion WebSocket non authentifiée.

    Le gate HTTP (`auth_manager.login_gate`) ne couvre PAS Socket.IO : le
    handshake passe par le serveur eventlet et non par la pile `before_request`
    de Flask. Sans ce contrôle, l'interface serait protégée mais le flux
    temps réel — logs applicatifs, progression des batchs, couvertures — resterait
    lisible sans compte.

    Fail-closed comme le gate HTTP : on exige une session, au lieu de l'ancien
    comportement qui ne vérifiait quoi que ce soit que si un `ADMIN_PASSWORD`
    était renseigné.

    Companion Super Review may also connect with a short-lived embed_token
    (session cookies are not sent in cross-origin Kavita iframes).

    ⚠️ Le refus se fait par `return False`, seule forme documentée par
    Flask-SocketIO pour rejeter un handshake : le serveur répond alors
    `connect_error` et n'acquitte jamais la connexion. Un `disconnect()` posé ici
    laissait au contraire le serveur acquitter la connexion puis envoyer un
    paquet de fermeture — deux paquets dont l'ordre d'interprétation côté client
    décidait si une fenêtre d'émission existait ou non.
    """
    embed_scope = None
    if not auth_manager.is_authenticated():
        embed_scope = _companion_embed_series(auth)
        if embed_scope is None:
            t = get_ui_translations()
            logging.warning(t.get("log_ws_connect_rejected", "🚨 [Sécurité] Connexion WebSocket rejetée (Non authentifié) IP: {0}").format(request.remote_addr))
            return False

    # Compteur + résumé file review manuelle (mode C29).
    #
    # Émis vers le seul `sid` qui vient de se connecter, jamais en diffusion : la
    # file de review est un état de session, et un `socketio.emit()` sans
    # destinataire l'enverrait à toutes les sockets ouvertes. Sans conséquence
    # avec le compte unique d'aujourd'hui, mais la table `users` accepte déjà N
    # comptes — autant ne pas laisser la fuite s'installer d'avance.
    sid = request.sid
    try:
        from db_manager import count_pending_reviews, list_pending_reviews
        rows = list_pending_reviews(limit=30)
        if embed_scope is not None:
            # Jeton d'embed : la file des autres séries ne sort pas d'ici.
            rows = [r for r in rows if str(r.get("series_id")) == str(embed_scope)]
            n = len(rows)
        else:
            n = count_pending_reviews()
        socketio.emit("manual_review_pending_count", {"count": n}, to=sid)
        if n:
            summary = []
            for r in rows:
                summary.append({
                    "review_id": r["review_id"],
                    "series_id": r["series_id"],
                    "series_name": r["series_name"],
                    "state": r["state"],
                })
            socketio.emit(
                "manual_review_queue_summary",
                {"reviews": summary, "count": n},
                to=sid,
            )
    except Exception as exc:
        logging.debug("manual_review connect emit skipped: %s", exc)


@socketio.on('fetch_covers_stream')
def handle_fetch_covers_stream(data):
    """Sert les couvertures en streaming direct (flush immédiat Eventlet)."""
    if _reject_unauthenticated('fetch_covers_stream'):
        return

    series_id = data.get('series_id')
    query = data.get('query')
    if not series_id or not query:
        return

    # Connexion Companion : le jeton vaut pour une série, l'événement ne peut pas
    # en viser une autre (le `series_id` vient du client).
    if not auth_manager.is_authenticated():
        scope = _companion_embed_series()
        if scope is None or int(series_id) != scope:
            t = get_ui_translations()
            logging.warning(
                t.get(
                    "log_ws_event_rejected",
                    "🚨 [Sécurité] Événement WebSocket '{0}' rejeté (Non authentifié) IP: {1}",
                ).format("fetch_covers_stream", request.remote_addr)
            )
            return

    cache_data = get_all_cached_data().get(int(series_id), {})
    series_name = query or ""

    config = load_config()
    t = get_ui_translations(config=config)
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
    library_type = kavita.get_library_type_for_series(series_id)

    jobs = iter_cover_jobs(cache_data, series_name, library_type)
    script_root = request.script_root or ""
    # Capturé ici : les tâches de fond ci-dessous tournent hors contexte de
    # requête, `request.sid` n'y serait plus lisible. Les couvertures répondent à
    # la recherche d'un client précis et n'ont rien à faire chez les autres.
    sid = request.sid

    total_jobs = len(jobs)
    finished_counter = [0]

    if total_jobs == 0:
        socketio.emit('cover_stream_complete', {'series_id': int(series_id)}, to=sid)
        socketio.sleep(0)
        return

    def process_and_emit_covers(job):
        try:
            results = run_cover_job(job, script_root=script_root)
            if results:
                provider = getattr(
                    job.scraper, "localized_display_name", None
                ) or getattr(job.scraper, "display_name", job.scraper.id)
                socketio.emit('cover_stream_data', {
                    'series_id': int(series_id),
                    'provider': provider,
                    'covers': results,
                }, to=sid)
                # VITAL POUR EVENTLET : Force l'envoi immédiat de la trame WebSocket
                socketio.sleep(0)
        except Exception as e:
            logging.error(
                t.get(
                    "log_covers_stream_err",
                    "[Covers Stream] Erreur sur {0} : {1}",
                ).format(getattr(job.scraper, "id", "?"), e)
            )
        finally:
            finished_counter[0] += 1
            if finished_counter[0] >= total_jobs:
                socketio.emit(
                    'cover_stream_complete',
                    {'series_id': int(series_id)},
                    to=sid,
                )
                socketio.sleep(0)

    # Resolved by_id first (priority 0), then the rest — jobs already sorted.
    for job in jobs:
        socketio.start_background_task(process_and_emit_covers, job)
