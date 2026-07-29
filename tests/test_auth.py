"""
Suite d'authentification (issue #15) : hachage, gates, verrouillage IP, migration.

Le mainteneur a explicitement demandé une couverture pytest sur « l'auth, le ban
IP et la logique de hachage ». Chaque bloc ci-dessous cible une propriété qui,
si elle cassait, ouvrirait l'application ou en fermerait l'accès à son
propriétaire — pas la simple couverture de lignes.

Comme le reste de la suite (voir tests/conftest.py), on n'importe jamais
`app.py`. Les gates sont des callables enregistrables, donc on les branche sur
une app Flask ad hoc : c'est précisément pourquoi ils vivent dans
`auth_manager.py` et non dans `app.py`.
"""
import json
import os

import pytest
from flask import Flask

import auth_manager
from routes.auth import auth_bp


@pytest.fixture(autouse=True)
def _clean_lockout_state():
    """Le compteur d'échecs est un global de module : à isoler entre tests."""
    auth_manager.reset_lockout_state()
    yield
    auth_manager.reset_lockout_state()


@pytest.fixture
def auth_app(isolated_db, monkeypatch):
    """App Flask ad hoc : blueprint auth + les deux gates, dans le bon ordre."""
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)

    test_app = Flask(__name__, template_folder="../templates", static_folder="../static")
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    test_app.register_blueprint(auth_bp)

    # ⚠️ Enregistrement via `add_url_rule` UNIQUEMENT, jamais via `@route` :
    # le nom d'endpoint est ce sur quoi portent les listes blanches des gates.
    # Un `@test_app.route("/healthz")` créerait l'endpoint 'healthz', et le gate
    # — qui whiteliste 'misc.healthz' — ne le reconnaîtrait pas. Le test échouerait
    # alors sur un artefact du harnais et non sur le comportement réel.
    def index():
        return "dashboard", 200

    def healthz():
        return {"status": "ok"}, 200

    test_app.add_url_rule("/", endpoint="pages.index", view_func=index)
    test_app.add_url_rule("/healthz", endpoint="misc.healthz", view_func=healthz)

    # Ordre significatif, identique à app.py.
    test_app.before_request(auth_manager.setup_gate)
    test_app.before_request(auth_manager.login_gate)
    return test_app


@pytest.fixture
def client(auth_app):
    return auth_app.test_client()


def _complete_setup(client, username="admin", password="correct horse"):
    return client.post("/setup", data={
        "username": username,
        "password": password,
        "password_confirm": password,
    }, follow_redirects=False)


# ---------------------------------------------------------------------------
# Hachage
# ---------------------------------------------------------------------------

def test_password_round_trip(isolated_db):
    ok, err = auth_manager.create_user("alice", "correct horse")
    assert ok and err is None

    assert auth_manager.verify_credentials("alice", "correct horse")["username"] == "alice"
    assert auth_manager.verify_credentials("alice", "wrong password") is None


def test_password_is_never_stored_in_clear(isolated_db):
    auth_manager.create_user("alice", "correct horse")

    import sqlite3
    conn = sqlite3.connect(isolated_db.DB_FILE)
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()

    assert "correct horse" not in stored
    assert stored.startswith(auth_manager.PASSWORD_HASH_METHOD), (
        "la méthode doit rester épinglée, pas suivre le défaut de Werkzeug"
    )


def test_hash_is_salted_per_user(isolated_db):
    """Deux comptes au même mot de passe ne doivent pas partager le même hachage."""
    auth_manager.create_user("alice", "same password")
    auth_manager.create_user("bob", "same password")

    import sqlite3
    conn = sqlite3.connect(isolated_db.DB_FILE)
    hashes = [row[0] for row in conn.execute("SELECT password_hash FROM users")]
    conn.close()

    assert hashes[0] != hashes[1]


def test_usernames_are_case_insensitive_and_unique(isolated_db):
    assert auth_manager.create_user("Alice", "correct horse")[0] is True

    ok, err = auth_manager.create_user("alice", "another password")
    assert ok is False
    assert err == "setup_err_username_taken"

    # …et la connexion doit fonctionner quelle que soit la casse saisie.
    assert auth_manager.verify_credentials("ALICE", "correct horse") is not None


def test_short_password_is_refused(isolated_db):
    ok, err = auth_manager.create_user("alice", "short")
    assert ok is False
    assert err == "setup_err_password_too_short"
    assert auth_manager.user_count() == 0


# ---------------------------------------------------------------------------
# Gate de setup
# ---------------------------------------------------------------------------

def test_everything_redirects_to_setup_when_no_account_exists(client):
    res = client.get("/")
    assert res.status_code == 302
    assert "/setup" in res.headers["Location"]


def test_login_page_redirects_to_setup_when_no_account_exists(client):
    res = client.get("/login")
    assert res.status_code == 302
    assert "/setup" in res.headers["Location"]


def test_setup_creates_the_account_and_logs_in(client, isolated_db):
    res = _complete_setup(client)

    assert res.status_code == 302
    assert auth_manager.user_count() == 1
    # Session ouverte dans la foulée : l'utilisateur atterrit sur le dashboard.
    assert client.get("/").status_code == 200


def test_setup_refuses_mismatched_confirmation(client):
    res = client.post("/setup", data={
        "username": "admin",
        "password": "correct horse",
        "password_confirm": "different horse",
    })
    assert res.status_code == 200
    assert auth_manager.user_count() == 0


def test_setup_is_closed_once_an_account_exists(client):
    """Sinon l'écran resterait un moyen non authentifié de créer un compte."""
    _complete_setup(client)
    client.get("/logout")

    res = client.get("/setup")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]

    res = client.post("/setup", data={
        "username": "intruder",
        "password": "correct horse",
        "password_confirm": "correct horse",
    })
    assert res.status_code == 302
    assert auth_manager.user_count() == 1, "aucun second compte ne doit être créé"


# ---------------------------------------------------------------------------
# Gate de connexion
# ---------------------------------------------------------------------------

def test_dashboard_requires_a_session(client):
    _complete_setup(client)
    client.get("/logout")

    res = client.get("/")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_login_with_valid_credentials_opens_the_session(client):
    _complete_setup(client)
    client.get("/logout")

    res = client.post("/login", data={"username": "admin", "password": "correct horse"})
    assert res.status_code == 302
    assert client.get("/").status_code == 200


def test_login_with_a_wrong_password_is_refused(client):
    _complete_setup(client)
    client.get("/logout")

    res = client.post("/login", data={"username": "admin", "password": "nope"})
    assert res.status_code == 200
    assert client.get("/").status_code == 302


def test_logout_clears_the_session(client):
    _complete_setup(client)
    assert client.get("/").status_code == 200

    client.get("/logout")
    assert client.get("/").status_code == 302


def test_the_gate_fails_closed_with_no_admin_password_configured(client):
    """Régression du comportement historique.

    L'ancien gate ne protégeait l'application QUE si `ADMIN_PASSWORD` était
    renseigné : sans lui, l'interface était servie à tout le monde. C'était
    l'exposition à l'origine de l'issue #15. Il ne doit plus exister aucune
    configuration dans laquelle le dashboard répond sans session.
    """
    _complete_setup(client)
    client.get("/logout")

    assert client.get("/").status_code == 302
    assert client.get("/stats").status_code in (302, 404)


# ---------------------------------------------------------------------------
# Endpoints qui doivent RESTER ouverts
# ---------------------------------------------------------------------------

def test_healthz_stays_reachable_before_and_after_setup(client):
    """Le HEALTHCHECK du conteneur ne doit jamais dépendre d'une session."""
    assert client.get("/healthz").status_code == 200  # aucun compte

    _complete_setup(client)
    client.get("/logout")

    assert client.get("/healthz").status_code == 200  # compte créé, déconnecté


def test_webhook_endpoint_is_not_gated(auth_app, client):
    """`sync.webhook` porte sa propre auth par jeton : l'extension Companion
    doit continuer de fonctionner sans session."""
    hits = {}

    def webhook():
        hits["called"] = True
        return "", 200

    auth_app.add_url_rule(
        "/webhook", endpoint="sync.webhook", view_func=webhook, methods=["POST"]
    )

    _complete_setup(client)
    client.get("/logout")

    assert client.post("/webhook").status_code == 200
    assert hits.get("called") is True


# ---------------------------------------------------------------------------
# Verrouillage par IP
# ---------------------------------------------------------------------------

def test_lockout_after_five_failed_attempts(client):
    _complete_setup(client)
    client.get("/logout")

    for _ in range(auth_manager.MAX_FAILED_ATTEMPTS):
        client.post("/login", data={"username": "admin", "password": "wrong"})

    locked, remaining = auth_manager.is_locked_out("127.0.0.1")
    assert locked is True
    assert 0 < remaining <= auth_manager.LOCKOUT_SECONDS


def test_lockout_refuses_even_the_correct_password(client):
    """Le verrou doit tenir face au bon mot de passe, sinon il ne verrouille rien."""
    _complete_setup(client)
    client.get("/logout")

    for _ in range(auth_manager.MAX_FAILED_ATTEMPTS):
        client.post("/login", data={"username": "admin", "password": "wrong"})

    res = client.post("/login", data={"username": "admin", "password": "correct horse"})
    assert res.status_code == 200, "doit réafficher le formulaire, pas rediriger"
    assert client.get("/").status_code == 302, "aucune session ne doit être ouverte"


def test_lockout_expires_after_the_window(client, monkeypatch):
    _complete_setup(client)
    client.get("/logout")

    for _ in range(auth_manager.MAX_FAILED_ATTEMPTS):
        client.post("/login", data={"username": "admin", "password": "wrong"})
    assert auth_manager.is_locked_out("127.0.0.1")[0] is True

    # Avance le temps au-delà de la fenêtre plutôt que d'attendre 15 minutes.
    real_now = auth_manager._now()
    monkeypatch.setattr(
        auth_manager, "_now", lambda: real_now + auth_manager.LOCKOUT_SECONDS + 1
    )

    assert auth_manager.is_locked_out("127.0.0.1")[0] is False, (
        "le verrouillage doit être TEMPORAIRE — exigence explicite du mainteneur "
        "pour qu'une faute de frappe ne bannisse pas définitivement quelqu'un"
    )


def test_a_successful_login_clears_the_counter(client):
    _complete_setup(client)
    client.get("/logout")

    for _ in range(auth_manager.MAX_FAILED_ATTEMPTS - 1):
        client.post("/login", data={"username": "admin", "password": "wrong"})

    client.post("/login", data={"username": "admin", "password": "correct horse"})
    assert auth_manager.is_locked_out("127.0.0.1")[0] is False
    assert "127.0.0.1" not in auth_manager._failed_attempts


def test_lockout_is_per_ip(client):
    _complete_setup(client)
    client.get("/logout")

    for _ in range(auth_manager.MAX_FAILED_ATTEMPTS):
        client.post(
            "/login",
            data={"username": "admin", "password": "wrong"},
            environ_overrides={"REMOTE_ADDR": "10.0.0.5"},
        )

    assert auth_manager.is_locked_out("10.0.0.5")[0] is True
    assert auth_manager.is_locked_out("10.0.0.9")[0] is False


# ---------------------------------------------------------------------------
# TRUSTED_PROXY_COUNT
# ---------------------------------------------------------------------------

def test_trusted_proxy_count_defaults_to_one(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
    assert auth_manager.get_trusted_proxy_count() == 1


def test_trusted_proxy_count_zero_is_honoured(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "0")
    assert auth_manager.get_trusted_proxy_count() == 0


@pytest.mark.parametrize("raw", ["2", "5", "abc", "-1", " "])
def test_unsupported_trusted_proxy_values_fall_back_to_one(monkeypatch, raw):
    """Le mainteneur a écarté la prise en charge de N proxies chaînés.

    Se rabattre sur 1 conserve le comportement historique ; interpréter « 2 »
    comme « fais confiance à deux sauts » sans l'implémenter réellement serait
    bien pire qu'un repli explicite.
    """
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", raw)
    assert auth_manager.get_trusted_proxy_count() == 1


# ---------------------------------------------------------------------------
# Migration depuis l'ancien ADMIN_PASSWORD
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    return config_manager


def test_legacy_admin_password_is_not_imported(client, isolated_config):
    """Réinitialisation forcée : l'ancien mot de passe en clair n'est jamais repris.

    Il a vécu en clair sur le disque, donc le hacher reviendrait à protéger un
    secret déjà compromis. Le mainteneur a choisi cette réinitialisation
    justement pour rendre l'utilisateur acteur de la mise à niveau.
    """
    isolated_config.save_config({"ADMIN_PASSWORD": "legacy-plaintext", "SECRET_KEY": "k"})

    # Le setup reste requis : la présence d'un ancien mot de passe ne crée aucun compte.
    assert auth_manager.setup_required() is True
    res = client.get("/")
    assert "/setup" in res.headers["Location"]

    # …et cet ancien mot de passe ne permet pas de se connecter.
    _complete_setup(client, username="admin", password="brand new password")
    client.get("/logout")
    res = client.post("/login", data={"username": "admin", "password": "legacy-plaintext"})
    assert res.status_code == 200
    assert client.get("/").status_code == 302


def test_legacy_admin_password_is_erased_after_setup(client, isolated_config):
    isolated_config.save_config({"ADMIN_PASSWORD": "legacy-plaintext", "SECRET_KEY": "k"})

    _complete_setup(client)

    with open(isolated_config.CONFIG_FILE, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved.get("ADMIN_PASSWORD") == "", (
        "le texte en clair doit cesser d'exister une fois le vrai compte créé"
    )


def test_purge_is_best_effort_and_never_breaks_setup(client, isolated_config, monkeypatch):
    """Un échec de purge ne doit pas empêcher la création du compte."""
    import config_manager

    def boom(_data):
        raise OSError("read-only filesystem")

    # SECRET_KEY et WEBHOOK_TOKEN déjà présents : sans cela `load_config()`
    # appellerait lui-même `save_config()` pour les générer, et le test
    # mesurerait l'échec de load_config au lieu de celui de la purge.
    isolated_config.save_config({
        "ADMIN_PASSWORD": "legacy",
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
    })
    monkeypatch.setattr(config_manager, "save_config", boom)

    res = _complete_setup(client)
    assert res.status_code == 302
    assert auth_manager.user_count() == 1


# ---------------------------------------------------------------------------
# Amorçage par ADMIN_PASSWORD_HASH
# ---------------------------------------------------------------------------

def test_seeding_from_env_creates_the_account_and_skips_setup(isolated_db, monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.setenv(
        "ADMIN_PASSWORD_HASH",
        generate_password_hash("seeded password", method=auth_manager.PASSWORD_HASH_METHOD),
    )
    monkeypatch.setenv("ADMIN_USERNAME", "ops")

    assert auth_manager.seed_user_from_env() is True
    assert auth_manager.setup_required() is False
    assert auth_manager.verify_credentials("ops", "seeded password") is not None


def test_seeding_defaults_the_username_to_admin(isolated_db, monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.setenv(
        "ADMIN_PASSWORD_HASH",
        generate_password_hash("seeded password", method=auth_manager.PASSWORD_HASH_METHOD),
    )

    auth_manager.seed_user_from_env()
    assert auth_manager.verify_credentials("admin", "seeded password") is not None


def test_seeding_never_overwrites_an_existing_account(isolated_db, monkeypatch):
    """Sinon une variable d'environnement oubliée écraserait le mot de passe réel
    à chaque redémarrage."""
    from werkzeug.security import generate_password_hash

    auth_manager.create_user("admin", "the real password")
    monkeypatch.setenv(
        "ADMIN_PASSWORD_HASH",
        generate_password_hash("seeded password", method=auth_manager.PASSWORD_HASH_METHOD),
    )

    assert auth_manager.seed_user_from_env() is False
    assert auth_manager.verify_credentials("admin", "the real password") is not None
    assert auth_manager.verify_credentials("admin", "seeded password") is None


def test_seeding_is_a_no_op_without_the_variable(isolated_db, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    assert auth_manager.seed_user_from_env() is False
    assert auth_manager.setup_required() is True


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------

def test_an_unreadable_users_table_denies_access(client, monkeypatch):
    """Une base illisible doit REFUSER, pas retomber sur « aucun compte, entre ».

    C'est le point le plus important du module : `user_count()` renvoie -1 en cas
    d'erreur SQLite, donc `setup_required()` est faux et `login_gate` continue
    d'exiger une session. Renvoyer 0 aurait transformé une base corrompue en
    contournement complet de l'authentification.
    """
    import sqlite3

    _complete_setup(client)
    client.get("/logout")

    def broken_connect():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(auth_manager, "_connect", broken_connect)

    assert auth_manager.user_count() == -1
    assert auth_manager.setup_required() is False
    assert auth_manager.verify_credentials("admin", "correct horse") is None

    res = client.get("/")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def test_csrf_is_enforced_on_the_login_post(isolated_db, monkeypatch):
    """`csrf_protect_before_request()` no-op sous TESTING : il faut donc
    désactiver TESTING volontairement pour vérifier que le POST de connexion est
    bien protégé."""
    from csrf_utils import csrf_protect_before_request

    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    auth_manager.create_user("admin", "correct horse")

    test_app = Flask(__name__, template_folder="../templates", static_folder="../static")
    test_app.config.update(TESTING=False, SECRET_KEY="test-secret")
    test_app.register_blueprint(auth_bp)
    test_app.before_request(csrf_protect_before_request)

    res = test_app.test_client().post(
        "/login", data={"username": "admin", "password": "correct horse"}
    )
    assert res.status_code == 403, "un POST de connexion sans jeton CSRF doit être refusé"
