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
import secrets
import sqlite3
import time
from collections import deque
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

# Hachage factice servant à égaliser le coût d'un nom d'utilisateur inconnu
# (voir `verify_credentials`). Calculé une seule fois, à la première tentative
# ratée, et mémorisé.
#
# ⚠️ NE PAS le recalculer à chaque appel : `generate_password_hash` est un KDF
# complet (600 000 itérations pbkdf2 sous Werkzeug 3). Le générer puis le
# vérifier coûtait DEUX KDF pour un nom inconnu contre UN pour un compte
# existant — l'écart de latence que la manœuvre prétendait effacer était donc
# simplement inversé, et le chemin le moins cher pour un attaquant devenait
# deux fois plus lourd pour le worker eventlet unique.
#
# Paresseux et non calculé à l'import : la suite pytest importe ce module dans
# presque tous ses fichiers, et une installation qui n'a jamais d'échec de
# connexion n'a aucune raison de payer ce calcul.
_dummy_password_hash = None


# --- VERROUILLAGE PAR IP ---------------------------------------------------
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60

# Plafond GLOBAL, toutes IP confondues, sur la même fenêtre glissante.
#
# Le compteur par IP ci-dessous ne vaut que si l'IP est fiable, et elle ne l'est
# pas toujours : avec `TRUSTED_PROXY_COUNT=1` (le défaut, cf. plus bas), c'est
# `X-Forwarded-For` qui fait autorité, et en exposition directe cet en-tête est
# fourni par le client. Le faire varier à chaque requête suffisait donc à ce
# qu'aucun compteur n'atteigne jamais 5 : brute-force illimité, et — plus grave
# sur ce déploiement — hachage illimité sur le worker eventlet unique.
#
# Ce plafond global ne peut pas être contourné par rotation d'IP puisqu'il n'en
# regarde aucune. Il est volontairement 4× plus haut que le seuil par IP : un
# utilisateur légitime qui se trompe ne l'atteint jamais, alors qu'un attaquant
# se retrouve borné à 20 essais par quart d'heure quelle que soit sa capacité à
# maquiller son adresse.
GLOBAL_MAX_FAILED_ATTEMPTS = 20

# Nombre maximal d'IP suivies simultanément. Sans plafond, chaque adresse
# usurpée laisserait une entrée permanente : le compteur censé freiner
# l'attaquant deviendrait lui-même sa charge utile.
MAX_TRACKED_IPS = 1024

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

# Horodatages des échecs récents, toutes IP confondues, pour le plafond global.
_global_failures = deque()


def _now():
    return time.time()


def _client_ip():
    """IP à laquelle imputer les tentatives ratées.

    `app.py` applique `ProxyFix`, qui remplace `request.remote_addr` par la
    valeur de `X-Forwarded-For`. C'est correct DERRIÈRE un reverse proxy, et
    dangereux sans : l'application écoute sur `0.0.0.0` (choix explicite du
    mainteneur pour l'extension Companion), donc en exposition directe cet
    en-tête est fourni par le client lui-même. Un attaquant n'a qu'à le faire
    varier à chaque requête pour qu'aucun compteur par IP n'atteigne jamais 5.

    `TRUSTED_PROXY_COUNT` tranche : `1` (défaut) conserve le comportement
    actuel, correct derrière un reverse proxy ; `0` ignore l'en-tête et impute
    la tentative au pair TCP réel, ce qu'il faut en exposition directe. Voir
    aussi `app.py`, qui utilise la même valeur pour construire `ProxyFix`.

    Le réglage reste donc à faire, mais il n'est plus la seule chose qui sépare
    l'application d'un brute-force illimité : `GLOBAL_MAX_FAILED_ATTEMPTS` borne
    les tentatives sans regarder aucune adresse, et cette borne-là tient même
    quand celle-ci est maquillée.
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


def _prune_failed_attempts(now):
    """Oublie les IP dont la fenêtre est expirée, puis borne la taille du suivi."""
    for ip, (_, last_attempt) in list(_failed_attempts.items()):
        if now - last_attempt >= LOCKOUT_SECONDS:
            _failed_attempts.pop(ip, None)
    # Filet de sécurité : si autant d'IP distinctes échouent dans la même
    # fenêtre, c'est déjà une rotation d'adresses, et le plafond global fait le
    # travail. On sacrifie les entrées les plus anciennes plutôt que la mémoire.
    while len(_failed_attempts) > MAX_TRACKED_IPS:
        oldest = min(_failed_attempts, key=lambda key: _failed_attempts[key][1])
        _failed_attempts.pop(oldest, None)


def _global_lockout_remaining(now):
    """Secondes restantes imposées par le plafond global (0 si non atteint)."""
    while _global_failures and now - _global_failures[0] >= LOCKOUT_SECONDS:
        _global_failures.popleft()
    if len(_global_failures) < GLOBAL_MAX_FAILED_ATTEMPTS:
        return 0
    # La fenêtre est glissante : le verrou se lève quand l'échec le plus ancien
    # sort de la fenêtre, donc au plus tard 15 minutes après la dernière rafale.
    return max(1, int(LOCKOUT_SECONDS - (now - _global_failures[0])))


def is_locked_out(ip=None):
    """(verrouillé: bool, secondes_restantes: int) pour cette IP.

    Deux verrous, on retient le plus contraignant : celui de l'IP, et le plafond
    global qui reste opposable même quand l'adresse est maquillée.
    """
    now = _now()
    remaining = _global_lockout_remaining(now)

    ip = ip or _client_ip()
    entry = _failed_attempts.get(ip)
    if entry:
        attempts, last_attempt = entry
        if attempts >= MAX_FAILED_ATTEMPTS:
            elapsed = now - last_attempt
            if elapsed >= LOCKOUT_SECONDS:
                # Fenêtre expirée : on repart de zéro. Le verrouillage est
                # TEMPORAIRE — exigence explicite du mainteneur, pour qu'une
                # faute de frappe ne bannisse pas définitivement un utilisateur
                # légitime.
                _failed_attempts.pop(ip, None)
            else:
                remaining = max(remaining, int(LOCKOUT_SECONDS - elapsed))

    return remaining > 0, remaining


def register_failed_attempt(ip=None):
    """Incrémente le compteur d'échecs et retourne le nombre de tentatives."""
    now = _now()
    ip = ip or _client_ip()
    attempts, _ = _failed_attempts.get(ip, (0, 0.0))
    attempts += 1
    _failed_attempts[ip] = (attempts, now)
    _global_failures.append(now)
    _prune_failed_attempts(now)
    _global_lockout_remaining(now)  # purge la fenêtre glissante

    if attempts >= MAX_FAILED_ATTEMPTS:
        logging.warning(
            "🚨 [Sécurité] %s tentatives de connexion échouées depuis %s — "
            "verrouillage %s minutes.",
            attempts, ip, LOCKOUT_SECONDS // 60,
        )
    elif len(_global_failures) >= GLOBAL_MAX_FAILED_ATTEMPTS:
        # Ce cas-là signale presque toujours une rotation d'adresses : le seuil
        # global est atteint alors qu'aucune IP n'a échoué 5 fois.
        logging.warning(
            "🚨 [Sécurité] %s tentatives de connexion échouées toutes adresses "
            "confondues en moins de %s minutes — verrouillage global. Si cette "
            "instance n'est pas derrière un reverse proxy, posez "
            "TRUSTED_PROXY_COUNT=0 pour que le verrouillage par IP redevienne "
            "fiable.",
            len(_global_failures), LOCKOUT_SECONDS // 60,
        )
    return attempts


def clear_failed_attempts(ip=None):
    """Remet les compteurs à zéro (connexion réussie).

    Le compteur global est purgé lui aussi : celui qui vient de fournir le bon
    mot de passe est le propriétaire, et le laisser verrouillé par la rafale
    d'un attaquant transformerait la protection en déni de service. La
    contrepartie est bornée — un attaquant ne regagne des essais qu'à condition
    que le propriétaire se connecte entre-temps.
    """
    _failed_attempts.pop(ip or _client_ip(), None)
    _global_failures.clear()


def reset_lockout_state():
    """Vide tout l'état de verrouillage. Réservé aux tests."""
    _failed_attempts.clear()
    _global_failures.clear()


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


def _get_dummy_password_hash():
    """Hachage factice mémorisé, pour l'égalisation de temps de `verify_credentials`."""
    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = generate_password_hash(
            "no-such-account", method=PASSWORD_HASH_METHOD
        )
    return _dummy_password_hash


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
        # Aucun compte de ce nom. On vérifie quand même le mot de passe fourni
        # contre un hachage factice pour que « utilisateur inconnu » et « mot de
        # passe faux » coûtent exactement le même temps — un seul KDF de part et
        # d'autre. Sans cela, l'écart de latence révèle quels noms existent.
        check_password_hash(_get_dummy_password_hash(), password)
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


def _looks_like_password_hash(value) -> bool:
    """True si `value` a la forme d'un hachage Werkzeug (`méthode$sel$empreinte`).

    Contrôle de forme uniquement — il ne s'agit pas de valider la robustesse du
    hachage, mais de distinguer un hachage d'un mot de passe en clair collé par
    erreur dans `ADMIN_PASSWORD_HASH`. La confusion avec l'ancien
    `ADMIN_PASSWORD` est facile à commettre, et sa conséquence est brutale : le
    compte serait créé, aucun mot de passe ne l'ouvrirait jamais
    (`check_password_hash` renvoie False sur une valeur qui n'est pas un
    hachage), et l'écran de setup se fermerait définitivement puisqu'un compte
    existe désormais. L'instance deviendrait inutilisable sans intervention dans
    la base.
    """
    parts = (value or "").split("$")
    if len(parts) != 3 or not all(parts):
        return False
    method = parts[0]
    return method.startswith(("pbkdf2:", "scrypt:")) or method in ("pbkdf2", "scrypt")


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
    mot de passe existant. Sans effet non plus si la valeur n'a pas la forme d'un
    hachage : mieux vaut laisser l'écran de setup ouvert qu'un compte inouvrable
    (voir `_looks_like_password_hash`).
    """
    password_hash = (os.environ.get("ADMIN_PASSWORD_HASH") or "").strip()
    if not password_hash:
        return False
    if not _looks_like_password_hash(password_hash):
        # On ne journalise JAMAIS la valeur : si l'utilisateur y a mis un mot de
        # passe en clair, l'écrire dans data/metakavita.log ne ferait que le
        # recopier ailleurs. Seule sa longueur est utile au diagnostic.
        logging.error(
            "[Auth] ADMIN_PASSWORD_HASH ignoré : la valeur fournie (%s caractères) "
            "n'a pas la forme d'un hachage Werkzeug « %s$sel$empreinte ». Cette "
            "variable attend un HACHAGE, pas un mot de passe — générez-le avec "
            "`python debug/hash_password.py`. Aucun compte n'a été créé, l'écran "
            "de setup reste donc disponible.",
            len(password_hash), PASSWORD_HASH_METHOD,
        )
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


def legacy_admin_password() -> str:
    """`ADMIN_PASSWORD` encore présent dans config.json, sinon "".

    Import local de `config_manager`, comme `purge_legacy_admin_password` : ce
    module est importé par `tests/conftest.py` sans que la configuration soit
    forcément initialisée.
    """
    from config_manager import load_config

    # `str()` défensif : config.json est éditable à la main, et une valeur
    # numérique y ferait échouer l'encodage UTF-8 de la comparaison.
    return str(load_config().get("ADMIN_PASSWORD") or "")


def legacy_proof_required() -> bool:
    """True si l'écran de setup doit exiger l'ancien mot de passe.

    Ferme la fenêtre de revendication de la mise à niveau. Sur une instance
    existante, la table `users` est vide au premier démarrage de cette version :
    `setup_required()` est donc vrai et `/setup` s'ouvre à tout le réseau, alors
    que l'ancien `ADMIN_PASSWORD` ne protège plus rien puisqu'il n'est
    volontairement pas repris. Une instance jusque-là protégée devenait ainsi
    accessible au premier visiteur, qui repartait avec le contrôle complet — donc
    avec l'écriture de métadonnées sur toute la bibliothèque Kavita.

    Exiger l'ancien mot de passe rétablit la continuité : il ne sert pas à
    authentifier une session (il a vécu en clair sur le disque, il est considéré
    comme compromis), seulement à prouver qu'on avait déjà accès à cette
    instance. Il est ensuite effacé par `purge_legacy_admin_password`, ce qui rend
    la preuve utilisable une seule fois.

    ⚠️ Une installation NEUVE n'a rien à prouver : il n'existe aucun secret
    partagé, donc le premier arrivé revendique l'instance. C'est inhérent au
    premier démarrage — la seule parade est de pré-provisionner le compte avec
    `ADMIN_PASSWORD_HASH`.
    """
    return bool(legacy_admin_password())


def verify_legacy_password(candidate) -> bool:
    """Compare en temps constant l'ancien mot de passe en clair.

    Comparaison sur les octets UTF-8 : `secrets.compare_digest` lève TypeError
    sur des `str` non ASCII, et un ancien mot de passe accentué transformerait
    alors un refus en erreur 500. Même motif défensif que `routes/sync.py`.
    """
    expected = legacy_admin_password()
    if not expected or not candidate:
        return False
    try:
        return secrets.compare_digest(expected.encode("utf-8"), candidate.encode("utf-8"))
    except (TypeError, ValueError):
        return False


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
