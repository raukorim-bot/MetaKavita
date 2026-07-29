"""
Point d'entrée de l'application MetaKavita.

Ce module reste volontairement fin depuis le refactor architecture (voir
DEVELOPER.md section 11) : il assemble l'application Flask (extensions,
logging, middlewares, blueprints, handlers socket, workers de fond) mais ne
contient plus aucune logique métier ni aucune route directement. Toute la
logique a été déplacée vers :
  - kavita_constants.py / models.py : contrats de données partagés
  - services/            : moteur d'enrichissement, workers de fond, changelog
  - routes/              : blueprints HTTP (auth, pages, config, series, sync, misc)
  - sockets/handlers.py  : handlers Socket.IO

⚠️ Contrainte figée : Gunicorn est démarré avec `app:app` (voir Dockerfile).
Cette variable `app` doit donc rester un objet Flask créé au niveau module,
et NON le résultat d'une fabrique appelée conditionnellement.
"""

import eventlet
eventlet.monkey_patch()

import os
import logging
import secrets
from datetime import timedelta

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, request, session, redirect, url_for, make_response

from auth_manager import (
    get_trusted_proxy_count,
    login_gate,
    seed_user_from_env,
    setup_gate,
)
from config_manager import load_config
from cors_config import (
    parse_cors_allowed_origins_detailed,
    log_cors_config,
    is_origin_allowed,
)
from db_manager import init_db
from extensions import socketio
from services.changelog_service import get_current_version
from services.background_tasks import start_background_workers

app = Flask(__name__)
# SECRET_KEY : toujours fournie par load_config() (générée au 1er boot).
# Jamais de fallback hardcodé public (ex-L1 audit).
_boot_config = load_config()
_secret_key = (_boot_config.get("SECRET_KEY") or "").strip()
if not _secret_key:
    _secret_key = secrets.token_hex(24)
    logging.error(
        "[Security] SECRET_KEY absente après load_config — clé éphémère générée pour ce process uniquement. "
        "Vérifiez data/config.json."
    )
app.config['SECRET_KEY'] = _secret_key
# Cookie de session : Lax réduit le CSRF cross-site classique ; Secure à activer
# derrière HTTPS via reverse-proxy (SESSION_COOKIE_SECURE=1).
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
if str(os.environ.get('SESSION_COOKIE_SECURE', '')).lower() in ('1', 'true', 'yes'):
    app.config['SESSION_COOKIE_SECURE'] = True

# --- CORS WHITELIST (Docker env CORS_ALLOWED_ORIGINS) ---
# Origins explicites uniquement ; liste vide = Same-Origin (on ne passe pas le
# kwarg à Socket.IO pour conserver le comportement par défaut du package).
CORS_ALLOWED_ORIGINS, CORS_STAR_IGNORED = parse_cors_allowed_origins_detailed()
if CORS_ALLOWED_ORIGINS:
    socketio.init_app(app, cors_allowed_origins=CORS_ALLOWED_ORIGINS)
else:
    socketio.init_app(app)
# --- SUPPORT REVERSE PROXY & SUBPATH (TICKET C17) ---
# Le nombre de proxies de confiance décide si les en-têtes `X-Forwarded-*` sont
# crus ou ignorés, et ce n'est PAS un détail cosmétique : `x_for` remplace
# `request.remote_addr` par la valeur de `X-Forwarded-For`. Derrière un reverse
# proxy c'est le comportement correct. En exposition directe — l'application
# écoute sur 0.0.0.0, choix explicite du mainteneur pour l'extension Companion —
# cet en-tête est fourni par le client lui-même, donc le faire varier suffirait à
# rendre le verrouillage par IP de `auth_manager` totalement inopérant.
#
# `TRUSTED_PROXY_COUNT=0` désactive l'ensemble des en-têtes forwarded et fait
# autorité sur le pair TCP réel. Défaut `1` : comportement historique inchangé
# pour les installations existantes derrière un proxy.
_trusted_proxies = get_trusted_proxy_count()
if _trusted_proxies:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=_trusted_proxies,
        x_proto=_trusted_proxies,
        x_host=_trusted_proxies,
        x_prefix=_trusted_proxies,
    )
else:
    logging.info(
        "[Security] TRUSTED_PROXY_COUNT=0 — en-têtes X-Forwarded-* ignorés, "
        "le verrouillage par IP s'appuie sur l'adresse TCP réelle."
    )

root_path = os.environ.get('ROOT_PATH', '')
if root_path:
    root_path = '/' + root_path.strip('/')

    class ScriptNameStripper(object):
        def __init__(self, wsgi_app, script_name):
            self.wsgi_app = wsgi_app
            self.script_name = script_name

        def __call__(self, environ, start_response):
            path_info = environ.get('PATH_INFO', '')
            if path_info.startswith(self.script_name):
                environ['SCRIPT_NAME'] = self.script_name
                environ['PATH_INFO'] = path_info[len(self.script_name):] or '/'
            return self.wsgi_app(environ, start_response)

    app.wsgi_app = ScriptNameStripper(app.wsgi_app, root_path)

init_db()

# Amorçage optionnel du compte admin depuis ADMIN_PASSWORD_HASH (docker-compose).
# Sans effet si un compte existe déjà : cette fonction ne peut pas écraser un mot
# de passe en place.
seed_user_from_env()

# Durée de vie explicite de la session. Flask applique 31 jours par défaut à une
# session `permanent`, ce qui est très long pour une interface d'administration :
# 7 jours conserve le confort du « rester connecté » sans qu'un poste oublié
# reste indéfiniment authentifié.
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

class WebSocketLogHandler(logging.Handler):
    def emit(self, record):
        # On masque les logs verbeux de DEBUG pour ne pas polluer la console Web UI
        if record.levelno < logging.INFO:
            return

        log_entry = self.format(record)

        # Ignorer les lignes contenant [DEBUG] dans l'interface Web
        if '[DEBUG]' in log_entry:
            return

        socketio.emit('log_update', {'data': log_entry})

ws_handler = WebSocketLogHandler()
ws_formatter = logging.Formatter('%(asctime)s | %(message)s', datefmt='%H:%M:%S')
ws_handler.setFormatter(ws_formatter)

if not os.path.exists("data"):
    os.makedirs("data")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("data/metakavita.log", encoding='utf-8'),
        logging.StreamHandler(),
        ws_handler
    ]
)

logging.getLogger('werkzeug').setLevel(logging.ERROR)

log_cors_config(CORS_ALLOWED_ORIGINS, star_ignored=CORS_STAR_IGNORED)


def _apply_cors_headers(response):
    """Pose les headers CORS uniquement si Origin est dans la whitelist Docker."""
    origin = request.headers.get("Origin")
    if not is_origin_allowed(origin, CORS_ALLOWED_ORIGINS):
        return response
    # Écho uniquement d'une origin whitelistée (jamais un reflet aveugle).
    response.headers["Access-Control-Allow-Origin"] = origin.strip().rstrip("/")
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Requested-With, X-CSRF-Token"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers.add("Vary", "Origin")
    return response


@app.before_request
def handle_cors_preflight():
    """Répond au preflight OPTIONS avant le gate login (sinon redirect 302 casse CORS)."""
    if request.method != "OPTIONS":
        return None
    if not is_origin_allowed(request.headers.get("Origin"), CORS_ALLOWED_ORIGINS):
        return None
    return _apply_cors_headers(make_response(("", 204)))


@app.after_request
def add_cors_headers(response):
    return _apply_cors_headers(response)


# --- GATES D'AUTHENTIFICATION ---
# L'ORDRE D'ENREGISTREMENT EST SIGNIFICATIF. Flask exécute les `before_request`
# dans leur ordre de déclaration :
#
#   1. handle_cors_preflight (déclaré plus haut) — un OPTIONS doit recevoir ses
#      en-têtes CORS et non un 302, sinon le preflight casse.
#   2. setup_gate — sur une installation neuve aucun compte n'existe ; rediriger
#      d'abord vers /login n'offrirait aucun moyen d'entrer.
#   3. login_gate — exige une session une fois le compte créé.
#
# Les deux gates vivent dans `auth_manager.py` plutôt qu'ici, et ce n'est pas un
# choix esthétique : `tests/conftest.py` n'importe jamais `app.py` (threads de
# fond, logging fichier, chargement des scrapers à l'import), donc une logique
# écrite directement dans ce module serait impossible à tester. Voir
# tests/test_auth.py, qui les enregistre sur une app Flask ad hoc.
#
# ⚠️ Les deux listes blanches portent sur des NOMS D'ENDPOINTS Flask
# ('auth.login', 'sync.webhook', 'misc.healthz'...) : renommer un blueprint ou
# une vue déplace donc silencieusement la frontière de sécurité.
app.before_request(setup_gate)
app.before_request(login_gate)


@app.before_request
def csrf_protect():
    from csrf_utils import csrf_protect_before_request
    return csrf_protect_before_request()

# --- ENREGISTREMENT DES BLUEPRINTS (ROUTES HTTP PAR DOMAINE) ---
from routes.auth import auth_bp
from routes.pages import pages_bp
from routes.config import config_bp
from routes.series import series_bp
from routes.sync import sync_bp
from routes.misc import misc_bp

app.register_blueprint(auth_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(config_bp)
app.register_blueprint(series_bp)
app.register_blueprint(sync_bp)
app.register_blueprint(misc_bp)

# --- ENREGISTREMENT DES HANDLERS SOCKET.IO (effet de bord à l'import) ---
import sockets.handlers  # noqa: F401

# --- VERSION & CONTEXTE GLOBAL DES TEMPLATES ---
APP_VERSION = get_current_version()

@app.context_processor
def inject_globals():
    from csrf_utils import ensure_csrf_token
    return {
        'app_version': APP_VERSION,
        'csrf_token': ensure_csrf_token(),
    }

# --- DÉMARRAGE DES WORKERS DE FOND (file de sync + auto-sync périodique) ---
# Démarré une seule fois au chargement du module, comme avant le refactor,
# pour rester compatible avec un déploiement Gunicorn à worker unique (-w 1).
start_background_workers()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5010, allow_unsafe_werkzeug=True, debug=False)
