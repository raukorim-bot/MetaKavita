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
from urllib.parse import quote

from flask import request
from flask_socketio import disconnect

import auth_manager
from extensions import socketio
from config_manager import load_config
from db_manager import get_all_cached_data
from kavita_api import KavitaAPI
from scrapers import ScraperRegistry
from scrapers.utils import library_type_for_scraper
from translations import get_ui_translations


def _reject_unauthenticated(event_name):
    """True (et socket fermée) si l'émetteur n'a pas de session valide.

    Défense en profondeur : le rejet à la connexion ci-dessous suffit en théorie,
    mais il ne tient qu'à la bonne interprétation d'un paquet de refus par le
    client. Chaque handler qui déclenche un travail réel vérifie donc lui-même,
    pour qu'un client qui émettrait avant d'avoir été éjecté ne fasse rien.
    """
    if auth_manager.is_authenticated():
        return False
    t = get_ui_translations()
    logging.warning(t.get("log_ws_event_rejected", "🚨 [Sécurité] Événement WebSocket '{0}' rejeté (Non authentifié) IP: {1}").format(event_name, request.remote_addr))
    disconnect()
    return True


@socketio.on('connect')
def handle_connect():
    """Refuse toute connexion WebSocket non authentifiée.

    Le gate HTTP (`auth_manager.login_gate`) ne couvre PAS Socket.IO : le
    handshake passe par le serveur eventlet et non par la pile `before_request`
    de Flask. Sans ce contrôle, l'interface serait protégée mais le flux
    temps réel — logs applicatifs, progression des batchs, couvertures — resterait
    lisible sans compte.

    Fail-closed comme le gate HTTP : on exige une session, au lieu de l'ancien
    comportement qui ne vérifiait quoi que ce soit que si un `ADMIN_PASSWORD`
    était renseigné.

    ⚠️ Le refus se fait par `return False`, seule forme documentée par
    Flask-SocketIO pour rejeter un handshake : le serveur répond alors
    `connect_error` et n'acquitte jamais la connexion. Un `disconnect()` posé ici
    laissait au contraire le serveur acquitter la connexion puis envoyer un
    paquet de fermeture — deux paquets dont l'ordre d'interprétation côté client
    décidait si une fenêtre d'émission existait ou non.
    """
    if not auth_manager.is_authenticated():
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
        n = count_pending_reviews()
        socketio.emit("manual_review_pending_count", {"count": n}, to=sid)
        if n:
            summary = []
            for r in list_pending_reviews(limit=30):
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
    if not series_id or not query: return

    cache_data = get_all_cached_data().get(int(series_id), {})
    search_query = cache_data.get('forced_id') or cache_data.get('alternative_title') or query

    config = load_config()
    t = get_ui_translations(config=config)
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
    library_type = kavita.get_library_type_for_series(series_id)

    target_scrapers = ScraperRegistry.get_by_type(library_type) or ScraperRegistry.get_by_type("Manga")
    script_root = request.script_root or ""
    # Capturé ici : les tâches de fond ci-dessous tournent hors contexte de
    # requête, `request.sid` n'y serait plus lisible. Les couvertures répondent à
    # la recherche d'un client précis et n'ont rien à faire chez les autres.
    sid = request.sid

    total_scrapers = len(target_scrapers)
    finished_counter = [0]

    def process_and_emit_covers(scraper):
        try:
            fetch_lt = library_type_for_scraper(scraper, library_type)
            s_covers = scraper.fetch_covers(search_query, library_type=fetch_lt)
            if s_covers:
                results = []
                for c in s_covers:
                    if getattr(scraper, 'requires_proxy', False):
                        c['display_url'] = f"{script_root}/api/proxy-image?url={quote(c['url'])}"
                    else:
                        c['display_url'] = c['url']
                    results.append(c)

                # Émission vers le client web à l'origine de la recherche
                socketio.emit('cover_stream_data', {
                    'series_id': int(series_id),
                    'provider': scraper.localized_display_name,
                    'covers': results
                }, to=sid)
                # VITAL POUR EVENTLET : Force l'envoi immédiat de la trame WebSocket sur le réseau
                socketio.sleep(0)
        except Exception as e:
            logging.error(t.get("log_covers_stream_err", "[Covers Stream] Erreur sur {0} : {1}").format(scraper.id, e))
        finally:
            finished_counter[0] += 1
            if finished_counter[0] >= total_scrapers:
                socketio.emit('cover_stream_complete', {'series_id': int(series_id)}, to=sid)
                socketio.sleep(0)

    for scraper in target_scrapers:
        socketio.start_background_task(process_and_emit_covers, scraper)
