"""
Authentification utilisateur : stockage, hachage, verrouillage IP et gates HTTP.

Ce module concentre TOUTE la logique d'authentification pour que `app.py` reste
un simple assembleur (voir DEVELOPER.md section 11) et surtout pour qu'elle soit
testable : `tests/conftest.py` n'importe volontairement jamais `app.py` (il
démarre des threads de fond, initialise le logging fichier et charge tous les
scrapers à l'import). Les deux gates ci-dessous sont donc de simples callables
enregistrables en `before_request` sur n'importe quelle app Flask, y compris une
app ad hoc construite dans un test.

⚠️ Base de données : on lit `db_manager.DB_FILE` par ACCÈS, jamais par import de
valeur (`from db_manager import DB_FILE`). C'est ce qui permet à la fixture
`isolated_db` de rediriger l'ensemble de ce module vers une base jetable en ne
patchant qu'une seule globale.
"""

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone

from flask import redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db_manager


# --- HACHAGE ---------------------------------------------------------------
# Méthode épinglée explicitement plutôt que de laisser le défaut de Werkzeug
# décider : ce défaut a déjà changé entre les versions majeures (pbkdf2 -> scrypt
# en 3.0), et un hachage qui change silencieusement selon la version installée
# est exactement le genre d'ambiguïté qui produit des bugs d'authentification
# impossibles à reproduire.
#
# pbkdf2:sha256 plutôt que scrypt, pour deux raisons propres à ce déploiement :
#   - Portabilité : scrypt dépend du support OpenSSL de l'interpréteur. Il est
#     présent sur `python:3.11-slim`, mais une image reconstruite ailleurs peut
#     ne pas l'avoir, et l'échec se produirait au moment le plus coûteux — la
#     création du tout premier compte.
#   - Gunicorn tourne en `-w 1` avec le worker eventlet : un seul processus pour
#     toute l'application. Le hachage est CPU-bound et bloque donc la totalité
#     des requêtes le temps de son calcul. scrypt y ajoute ~32 Mo d'allocation
#     mémoire par appel. pbkdf2 reste largement suffisant pour une instance
#     auto-hébergée à compte unique, sans ce pic.
#
# Les hachages Werkzeug embarquent leur propre méthode et leurs paramètres :
# `check_password_hash` continuera donc de valider les anciens hachages si cette
# constante change un jour.
PASSWORD_HASH_METHOD = "pbkdf2:sha256"

# Longueur minimale imposée à la création du compte. Volontairement modeste :
# l'application n'est pas destinée à être exposée sur Internet (cf. issue #15),
# le verrouillage par IP ci-dessous couvre le brute-force en ligne, et un seuil
# agressif pousse surtout les gens vers des mots de passe notés sur un post-it.
MIN_PASSWORD_LENGTH = 8


# --- VERROUILLAGE PAR IP ---------------------------------------------------
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60

# État en mémoire : {ip: (nombre_d_échecs, timestamp_du_dernier_échec)}.
#
# En mémoire et non en base, DÉLIBÉRÉMENT. Gunicorn tourne en `-w 1` : il n'y a
# qu'un seul processus, donc pas de problème de partage d'état entre workers.
# Écrire en SQLite à chaque tentative ratée reviendrait à offrir à un attaquant
# non authentifié un levier d'écriture disque illimité — le remède serait pire
# que le mal.
#
# Contrepartie assumée : l'état est perdu au redémarrage du conteneur. Un
# attaquant non authentifié ne peut pas provoquer ce redémarrage, donc il ne
# peut pas s'en servir pour réarmer son compteur.
_failed_attempts = {}


def _now():
    return time.time()


def _client_ip():
    """IP à laquelle imputer les tentatives ratées.

    `app.py` applique `ProxyFix`, qui remplace `request.remote_addr` par la
    valeur de `X-Forwarded-For`. C'est correct DERRIÈRE un reverse proxy, et
    dangereux sans : l'application écoute sur `0.0.0.0` (choix explicite du
    mainteneur pour l'extension Companion), donc en exposition directe cet
    en-tête est fourni par le client lui-même. Un attaquant n'aurait qu'à le
    faire varier à chaque requête pour que le compteur par IP n'atteigne jamais
    5 et que le verrouillage ne se déclenche jamais.

    `TRUSTED_PROXY_COUNT` tranche : `1` (défaut) conserve le comportement
    actuel, correct derrière un reverse proxy ; `0` ignore l'en-tête et impute
    la tentative au pair TCP réel, ce qu'il faut en exposition directe. Voir
    aussi `app.py`, qui utilise la même valeur pour construire `ProxyFix`.
    """
    if get_trusted_proxy_count() == 0:
        # `werkzeug.middleware.proxy_fix` conserve l'adresse réelle ici lorsqu'il
        # a réécrit REMOTE_ADDR ; à défaut on retombe sur remote_addr.
        real = request.environ.get("werkzeug.proxy_fix.orig", {}).get("REMOTE_ADDR")
        return real or request.environ.get("REMOTE_ADDR") or request.remote_addr or "unknown"
    return request.remote_addr or "unknown"


def get_trusted_proxy_count() -> int:
    """Nombre de reverse proxies de confiance devant l'application (0 ou 1).

    Lu directement dans l'environnement, PAS via `config_manager.load_config()`.
    C'est délibéré : c'est un réglage de déploiement, il doit être fixé avant que
    la moindre requête soit servie (`ProxyFix` est construit à l'import de
    `app.py`), et le mettre dans `config.json` le rendrait modifiable depuis
    l'interface web — où se tromper coupe l'accès à cette même interface.

    Le mainteneur a explicitement écarté la prise en charge de N proxies chaînés
    comme disproportionnée pour cette application : toute valeur autre que `0`
    est donc traitée comme `1`.
    """
    raw = (os.environ.get("TRUSTED_PROXY_COUNT") or "").strip()
    if raw == "0":
        return 0
    if raw and raw != "1":
        logging.warning(
            "[Auth] TRUSTED_PROXY_COUNT=%r non reconnu — seuls 0 et 1 sont gérés, "
            "repli sur 1 (un reverse proxy de confiance).",
            raw,
        )
    return 1


def is_locked_out(ip=None):
    """(verrouillé: bool, secondes_restantes: int) pour cette IP."""
    ip = ip or _client_ip()
    entry = _failed_attempts.get(ip)
    if not entry:
        return False, 0
    attempts, last_attempt = entry
    if attempts < MAX_FAILED_ATTEMPTS:
        return False, 0
    elapsed = _now() - last_attempt
    if elapsed >= LOCKOUT_SECONDS:
        # Fenêtre expirée : on repart de zéro. Le verrouillage est TEMPORAIRE —
        # exigence explicite du mainteneur, pour qu'une faute de frappe ne
        # bannisse pas définitivement un utilisateur légitime.
        _failed_attempts.pop(ip, None)
        return False, 0
    return True, int(LOCKOUT_SECONDS - elapsed)


def register_failed_attempt(ip=None):
    """Incrémente le compteur d'échecs et retourne le nombre de tentatives."""
    ip = ip or _client_ip()
    attempts, _ = _failed_attempts.get(ip, (0, 0.0))
    attempts += 1
    _failed_attempts[ip] = (attempts, _now())
    if attempts >= MAX_FAILED_ATTEMPTS:
        logging.warning(
            "🚨 [Sécurité] %s tentatives de connexion échouées depuis %s — "
            "verrouillage %s minutes.",
            attempts, ip, LOCKOUT_SECONDS // 60,
        )
    return attempts


def clear_failed_attempts(ip=None):
    """Remet le compteur à zéro (connexion réussie)."""
    _failed_attempts.pop(ip or _client_ip(), None)


def reset_lockout_state():
    """Vide tout l'état de verrouillage. Réservé aux tests."""
    _failed_attempts.clear()


# --- STOCKAGE --------------------------------------------------------------

def _connect():
    """Connexion SQLite, une par appel — même convention que db_manager."""
    return sqlite3.connect(db_manager.DB_FILE)


def _ensure_users_table(c):
    """Crée la table si absente.

    Appelée défensivement par chaque accesseur plutôt qu'une seule fois au
    démarrage, comme `_ensure_provider_stats_table` et consorts dans
    `db_manager.py` : le fichier de base peut être supprimé ou restauré sous
    l'application sans qu'elle redémarre.

    Le schéma accepte N utilisateurs dès maintenant, mais cette version n'en
    expose qu'un seul (décision du mainteneur : pas de modèle de rôles tant
    qu'il n'y a aucune donnée par utilisateur à cloisonner). Ajouter la gestion
    multi-comptes plus tard ne demandera donc pas de migration de schéma.
    """
    c.execute(
        '''CREATE TABLE IF NOT EXISTS users
           (id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT)'''
    )


def _utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def user_count():
    """Nombre de comptes existants. 0 = installation neuve.

    Fail-closed : si la base est illisible, on renvoie -1 plutôt que 0. Un 0
    signifierait « aucun compte, laisse passer vers le setup » et transformerait
    une base corrompue en contournement complet de l'authentification.
    """
    try:
        conn = _connect()
        c = conn.cursor()
        _ensure_users_table(c)
        c.execute("SELECT COUNT(*) FROM users")
        total = int(c.fetchone()[0])
        conn.close()
        return total
    except sqlite3.Error as e:
        logging.error("[Auth] Table users illisible (%s) — accès refusé par précaution.", e)
        return -1


def setup_required() -> bool:
    """True si le premier compte reste à créer."""
    return user_count() == 0


def create_user(username, password):
    """Crée un compte. Retourne (ok: bool, message_d_erreur: str | None).

    Le message retourné est une CLÉ de traduction, pas une phrase : la couche
    HTTP est responsable de la localisation (voir routes/auth.py).
    """
    username = (username or "").strip()
    if not username:
        return False, "setup_err_username_required"
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return False, "setup_err_password_too_short"

    try:
        conn = _connect()
        c = conn.cursor()
        _ensure_users_table(c)
        c.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (
                username,
                generate_password_hash(password, method=PASSWORD_HASH_METHOD),
                _utcnow(),
            ),
        )
        conn.commit()
        conn.close()
        logging.info("[Auth] Compte '%s' créé.", username)
        return True, None
    except sqlite3.IntegrityError:
        return False, "setup_err_username_taken"
    except sqlite3.Error as e:
        logging.error("[Auth] Création de compte impossible : %s", e)
        return False, "setup_err_generic"


def verify_credentials(username, password):
    """Retourne {id, username} si le couple est valide, sinon None."""
    username = (username or "").strip()
    if not username or not password:
        return None
    try:
        conn = _connect()
        c = conn.cursor()
        _ensure_users_table(c)
        c.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        )
        row = c.fetchone()
        conn.close()
    except sqlite3.Error as e:
        logging.error("[Auth] Vérification impossible (%s) — refus.", e)
        return None

    if not row:
        # Aucun compte de ce nom. On hache quand même une valeur bidon pour que
        # « utilisateur inconnu » et « mot de passe faux » coûtent le même temps :
        # sans cela, l'écart de latence révèle quels noms existent.
        check_password_hash(
            generate_password_hash("timing-equalizer", method=PASSWORD_HASH_METHOD),
            "timing-equalizer",
        )
        return None

    user_id, real_username, password_hash = row
    if not check_password_hash(password_hash, password):
        return None
    return {"id": user_id, "username": real_username}


def record_login(user_id):
    """Horodate la dernière connexion. Best-effort : ne doit jamais faire échouer un login."""
    try:
        conn = _connect()
        c = conn.cursor()
        _ensure_users_table(c)
        c.execute("UPDATE users SET last_login = ? WHERE id = ?", (_utcnow(), user_id))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logging.warning("[Auth] last_login non mis à jour : %s", e)


def seed_user_from_env():
    """Crée le compte initial depuis `ADMIN_USERNAME` / `ADMIN_PASSWORD_HASH`.

    Destiné aux déploiements docker-compose qui veulent une instance déjà
    configurée, sans passer par l'écran de setup.

    Variable dédiée `ADMIN_PASSWORD_HASH`, et surtout PAS de réutilisation de
    `ADMIN_PASSWORD` pour y mettre parfois un hachage : distinguer les deux
    supposerait de deviner si une chaîne « ressemble » à un hachage, et cette
    ambiguïté-là est précisément ce qui produit des failles d'authentification.

    Lu directement dans l'environnement plutôt que via `config_manager` : ces
    valeurs ne doivent jamais être recopiées dans `config.json`, et le réglage
    doit s'appliquer au premier démarrage avant toute requête.

    Sans effet si un compte existe déjà — cette fonction ne peut pas écraser un
    mot de passe existant.
    """
    password_hash = (os.environ.get("ADMIN_PASSWORD_HASH") or "").strip()
    if not password_hash:
        return False
    if user_count() != 0:
        return False

    username = (os.environ.get("ADMIN_USERNAME") or "admin").strip() or "admin"
    try:
        conn = _connect()
        c = conn.cursor()
        _ensure_users_table(c)
        c.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, _utcnow()),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logging.error("[Auth] Amorçage depuis ADMIN_PASSWORD_HASH impossible : %s", e)
        return False

    logging.info(
        "[Auth] Compte '%s' amorcé depuis ADMIN_PASSWORD_HASH — écran de setup ignoré.",
        username,
    )
    return True


def purge_legacy_admin_password():
    """Efface `ADMIN_PASSWORD` de config.json une fois le vrai compte créé.

    Le mainteneur a choisi une réinitialisation forcée plutôt qu'une reprise
    silencieuse de l'ancien mot de passe : celui-ci était stocké en clair, donc
    le réutiliser reviendrait à hacher un secret déjà compromis par sa présence
    sur disque. Il n'est donc jamais importé — seulement supprimé, pour que le
    texte en clair cesse d'exister une fois qu'il n'a plus d'utilité.

    Best-effort : un échec ici ne doit pas faire échouer la création du compte.
    """
    try:
        from config_manager import CONFIG_LOCK, load_config, save_config

        with CONFIG_LOCK:
            config = load_config()
            if not config.get("ADMIN_PASSWORD"):
                return False
            config["ADMIN_PASSWORD"] = ""
            save_config(config)
        logging.info(
            "[Auth] ADMIN_PASSWORD hérité supprimé de config.json — remplacé par le "
            "compte utilisateur créé au setup."
        )
        return True
    except Exception as e:  # noqa: BLE001 - best-effort, jamais bloquant
        logging.warning("[Auth] Purge de l'ancien ADMIN_PASSWORD impossible : %s", e)
        return False


# --- SESSION ---------------------------------------------------------------

def login_session(user):
    """Ouvre la session applicative pour cet utilisateur."""
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]


def current_user_id():
    return session.get("user_id")


def is_authenticated() -> bool:
    return session.get("user_id") is not None


# --- GATES HTTP ------------------------------------------------------------
# Endpoints joignables sans compte. ⚠️ La liste porte sur des NOMS D'ENDPOINTS
# Flask ('blueprint.vue') : renommer un blueprint ou une vue déplace donc
# silencieusement la frontière de sécurité. Voir tests/test_auth.py, qui
# verrouille ce comportement.
_SETUP_ALLOWED_ENDPOINTS = frozenset({
    "auth.setup",
    "static",
    "misc.healthz",
    "sync.webhook",
})

_LOGIN_ALLOWED_ENDPOINTS = frozenset({
    "auth.login",
    "auth.setup",
    "static",
    "misc.healthz",
    "sync.webhook",
})


def setup_gate():
    """`before_request` : force la création du premier compte.

    DOIT être enregistré AVANT `login_gate` — sur une installation neuve il n'y
    a aucun compte, donc rediriger vers /login n'offrirait aucun moyen d'entrer.

    `sync.webhook` reste ouvert : il porte sa propre authentification par jeton
    et l'extension Companion doit continuer de fonctionner. `misc.healthz` reste
    ouvert pour que le HEALTHCHECK du conteneur ne signale pas « unhealthy » une
    instance parfaitement saine mais pas encore configurée.
    """
    if request.method == "OPTIONS":
        return None
    if request.endpoint in _SETUP_ALLOWED_ENDPOINTS:
        return None
    if setup_required():
        return redirect(url_for("auth.setup"))
    return None


def login_gate():
    """`before_request` : exige une session authentifiée.

    Fail-closed par construction : contrairement à l'ancien gate — qui ne
    protégeait l'application QUE si un `ADMIN_PASSWORD` était renseigné, et
    laissait donc tout ouvert par défaut — l'accès est ici refusé dès qu'aucune
    session valide n'est présente. Il n'existe plus de configuration dans
    laquelle l'interface est servie sans authentification.
    """
    if request.method == "OPTIONS":
        return None
    if request.endpoint in _LOGIN_ALLOWED_ENDPOINTS:
        return None
    if not is_authenticated():
        return redirect(url_for("auth.login"))
    return None
