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


@pytest.fixture(autouse=True)
def _isolated_config_file(tmp_path, monkeypatch):
    """Aucun test de ce fichier ne doit lire le `data/config.json` du dépôt.

    L'écran de setup consulte `ADMIN_PASSWORD` pour décider s'il exige la preuve
    de propriété (`auth_manager.legacy_proof_required`) : sans cette isolation,
    le résultat de la suite dépendrait de la configuration de la machine qui la
    lance. Même tmp_path que la fixture `isolated_config` ci-dessous, qui peut
    donc continuer d'écrire dans ce même fichier.
    """
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))


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


def _complete_setup(
    client,
    username="admin",
    password="correct horse",
    legacy_password=None,
    *,
    kavita_url="http://kavita.test",
    kavita_api_key="test-kavita-key",
    extra=None,
):
    """POST /setup. `legacy_password` n'est envoyé que si le test le fournit —
    l'écran ne le réclame que sur une instance qui avait un `ADMIN_PASSWORD`.

    Depuis le wizard first-run, URL + clé Kavita sont obligatoires (le test
    de connexion n'est pas requis).
    """
    data = {
        "username": username,
        "password": password,
        "password_confirm": password,
        "KAVITA_URL": kavita_url,
        "KAVITA_API_KEY": kavita_api_key,
        "UI_LANG": "fr",
        "TARGET_LANG": "FR",
        "TRANSLATION_PROVIDER": "GOOGLE",
        "SMART_SCORING": "true",
        "SMART_COMPLETION": "true",
        "MANUAL_REVIEW_MODE": "false",
        "AUTO_COVER": "false",
        "AUTO_READING_DIR": "false",
        "TITLE_FALLBACK_TRANSLATION": "false",
        "AUTO_SYNC_INTERVAL": "360",
        "PUBLISHER_PREFERENCE": "LOCALIZED",
        "LOCALIZED_TITLE_MODE": "all",
    }
    if legacy_password is not None:
        data["legacy_password"] = legacy_password
    if extra:
        data.update(extra)
    return client.post("/setup", data=data, follow_redirects=False)


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
# Égalisation du temps de réponse
# ---------------------------------------------------------------------------

def test_the_dummy_hash_is_computed_once(isolated_db):
    """Le hachage factice est un KDF complet : le recalculer à chaque tentative
    ferait d'un nom inconnu le chemin le PLUS coûteux, sur un worker unique."""
    first = auth_manager._get_dummy_password_hash()
    assert auth_manager._get_dummy_password_hash() is first


def test_unknown_and_wrong_password_cost_the_same_number_of_hashes(isolated_db, monkeypatch):
    """Un nom inconnu et un mot de passe faux doivent coûter UN KDF chacun.

    C'est la propriété que l'égalisation cherche à obtenir : si les deux chemins
    ne font pas le même travail, l'écart de latence dit à l'attaquant quels
    comptes existent — et l'ancienne version, qui générait un hachage avant de le
    vérifier, en faisait deux pour un nom inconnu contre un seul pour un compte
    réel.
    """
    from werkzeug import security as werkzeug_security

    auth_manager.create_user("admin", "correct horse")
    auth_manager._get_dummy_password_hash()  # préchauffage hors mesure

    calls = {"generate": 0, "check": 0}

    def counting_generate(*args, **kwargs):
        calls["generate"] += 1
        return werkzeug_security.generate_password_hash(*args, **kwargs)

    def counting_check(*args, **kwargs):
        calls["check"] += 1
        return werkzeug_security.check_password_hash(*args, **kwargs)

    monkeypatch.setattr(auth_manager, "generate_password_hash", counting_generate)
    monkeypatch.setattr(auth_manager, "check_password_hash", counting_check)

    assert auth_manager.verify_credentials("ghost", "whatever") is None
    unknown_user = dict(calls)

    calls["generate"] = calls["check"] = 0
    assert auth_manager.verify_credentials("admin", "wrong password") is None
    wrong_password = dict(calls)

    assert unknown_user == wrong_password == {"generate": 0, "check": 1}


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


def test_setup_refuses_without_kavita_credentials(client):
    res = client.post("/setup", data={
        "username": "admin",
        "password": "correct horse",
        "password_confirm": "correct horse",
        "KAVITA_URL": "",
        "KAVITA_API_KEY": "",
    })
    assert res.status_code == 200
    assert auth_manager.user_count() == 0


def test_setup_persists_wizard_defaults(client):
    """Finish écrit Kavita + Auto-Sync 6 h + Smart Completion même sans clés scrapers."""
    import config_manager

    res = _complete_setup(client, extra={"ROOT_PATH": "/metakavita"})
    assert res.status_code == 302

    cfg = config_manager.load_config()
    assert cfg.get("KAVITA_URL") == "http://kavita.test"
    assert cfg.get("KAVITA_API_KEY") == "test-kavita-key"
    assert cfg.get("ROOT_PATH") == "/metakavita"
    assert int(cfg.get("AUTO_SYNC_INTERVAL") or 0) == 360
    assert cfg.get("SMART_SCORING") is True
    assert cfg.get("SMART_COMPLETION") is True
    assert cfg.get("TRANSLATION_PROVIDER") == "GOOGLE"
    assert cfg.get("UI_LANG") == "fr"
    assert cfg.get("TARGET_LANG") == "FR"


def test_setup_persists_full_custom_options_matrix(client):
    """Toutes les options wizard (bool off/on, langues, cascades, clés) survivent au reload."""
    import json
    import config_manager

    extra = {
        "UI_LANG": "en",
        "TARGET_LANG": "DE",
        "TRANSLATION_PROVIDER": "NONE",
        "PUBLISHER_PREFERENCE": "ORIGINAL",
        "LOCALIZED_TITLE_MODE": "prefer",
        "LOCALIZED_TITLE_LANGS": "en, ja-ro",
        "TITLE_FALLBACK_TRANSLATION": "true",
        "SMART_SCORING": "false",
        "SMART_COMPLETION": "false",
        "MANUAL_REVIEW_MODE": "true",
        "AUTO_COVER": "true",
        "AUTO_READING_DIR": "true",
        "AUTO_SYNC_INTERVAL": "1440",
        "ROOT_PATH": "/mk",
        "AZURE_REGION": "",
        "PROVIDER_1": "ANILIST",
        "PROVIDER_2": "NONE",
        "PROVIDER_3": "NONE",
        "COMIC_PROVIDER_1": "METRON",
        "COMIC_PROVIDER_2": "NONE",
        "COMIC_PROVIDER_3": "NONE",
        "BOOK_PROVIDER_1": "OPENLIBRARY",
        "BOOK_PROVIDER_2": "NONE",
        "BOOK_PROVIDER_3": "NONE",
        "COMICVINE_API_KEY": "cv-secret-from-setup",
        "HARDCOVER_API_KEY": "hc-secret-from-setup",
    }
    assert _complete_setup(client, extra=extra).status_code == 302

    cfg = config_manager.load_config()
    assert cfg["UI_LANG"] == "en"
    assert cfg["TARGET_LANG"] == "DE"
    assert cfg["TRANSLATION_PROVIDER"] == "NONE"
    assert cfg["PUBLISHER_PREFERENCE"] == "ORIGINAL"
    assert cfg["LOCALIZED_TITLE_MODE"] == "prefer"
    assert cfg["LOCALIZED_TITLE_LANGS"] == "en, ja-ro"
    assert cfg["TITLE_FALLBACK_TRANSLATION"] is True
    assert cfg["SMART_SCORING"] is False
    assert cfg["SMART_COMPLETION"] is False  # défaut code=False, wizard peut forcer False
    assert cfg["MANUAL_REVIEW_MODE"] is True
    assert cfg["AUTO_COVER"] is True
    assert cfg["AUTO_READING_DIR"] is True
    assert int(cfg["AUTO_SYNC_INTERVAL"]) == 1440
    assert cfg["ROOT_PATH"] == "/mk"
    assert cfg["PROVIDER_1"] == "ANILIST"
    assert cfg["PROVIDER_2"] == "NONE"
    assert cfg["PROVIDER_3"] == "NONE"
    assert cfg["COMIC_PROVIDER_1"] == "METRON"
    assert cfg["BOOK_PROVIDER_1"] == "OPENLIBRARY"
    assert cfg["COMICVINE_API_KEY"] == "cv-secret-from-setup"
    assert cfg["HARDCOVER_API_KEY"] == "hc-secret-from-setup"

    # Round-trip disque : JSON natif bool/int, pas de perte au 2ᵉ load_config
    with open(config_manager.CONFIG_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["SMART_SCORING"] is False
    assert raw["SMART_COMPLETION"] is False
    assert raw["AUTO_COVER"] is True
    assert raw["AUTO_SYNC_INTERVAL"] == 1440
    assert raw["COMICVINE_API_KEY"] == "cv-secret-from-setup"

    cfg2 = config_manager.load_config()
    assert cfg2["SMART_SCORING"] is False
    assert cfg2["MANUAL_REVIEW_MODE"] is True
    assert cfg2["PROVIDER_1"] == "ANILIST"


def test_setup_empty_api_keys_do_not_wipe_existing(client):
    """POST vide sur *_API_KEY conserve une clé déjà en config (contrat secrets)."""
    import config_manager

    config_manager.save_config({
        **config_manager.load_config(),
        "COMICVINE_API_KEY": "keep-me",
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
    })
    assert _complete_setup(client, extra={"COMICVINE_API_KEY": ""}).status_code == 302
    cfg = config_manager.load_config()
    assert cfg.get("COMICVINE_API_KEY") == "keep-me"


def test_setup_omitted_providers_keep_cascade_defaults(client):
    """Sans PROVIDER_* dans le POST (client minimal), les cascades défaut restent."""
    import config_manager

    before = config_manager.load_config()
    assert _complete_setup(client).status_code == 302
    after = config_manager.load_config()
    assert after.get("PROVIDER_1") == before.get("PROVIDER_1")
    assert after.get("COMIC_PROVIDER_1") == before.get("COMIC_PROVIDER_1")
    assert after.get("BOOK_PROVIDER_1") == before.get("BOOK_PROVIDER_1")


def test_setup_test_kavita_is_non_blocking_endpoint(client, monkeypatch):
    """Le probe échoue → JSON warn, pas d'écriture config ; Finish reste possible."""
    from kavita_api import KavitaAPI

    monkeypatch.setattr(KavitaAPI, "authenticate", lambda self: False)

    res = client.post("/setup/test-kavita", data={
        "KAVITA_URL": "http://kavita.test",
        "KAVITA_API_KEY": "bad",
        "UI_LANG": "fr",
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is False
    assert "bibliothèques" in (body.get("message") or "").lower() or "libraries" in (
        body.get("message") or ""
    ).lower()

    # Finish avec les mêmes creds (probe non requis côté serveur)
    assert _complete_setup(client).status_code == 302


def test_setup_page_renders_wizard(client):
    res = client.get("/setup")
    assert res.status_code == 200
    html = res.data.decode("utf-8", errors="replace")
    assert "setupForm" in html
    assert "KAVITA_URL" in html
    assert "AUTO_SYNC_INTERVAL" in html


def test_setup_csrf_token_not_blanked_by_context(auth_app):
    """Régression audit C64 : _setup_context ne doit pas écraser ensure_csrf_token."""
    from csrf_utils import ensure_csrf_token

    @auth_app.context_processor
    def _inject_csrf():
        return {"csrf_token": ensure_csrf_token()}

    client = auth_app.test_client()
    res = client.get("/setup")
    assert res.status_code == 200
    html = res.data.decode("utf-8", errors="replace")
    # meta + hidden field must carry a real token (not empty value="")
    assert 'name="csrf_token" value=""' not in html
    assert 'name="csrf-token" content=""' not in html
    assert "csrf_token" in html


def test_setup_config_save_failure_does_not_create_account(client, monkeypatch):
    import config_manager
    import routes.auth as auth_routes

    real_save = config_manager.save_config

    def boom(cfg):
        raise RuntimeError("disk full")

    # routes.auth importe save_config par nom — patcher le binding du module.
    monkeypatch.setattr(auth_routes, "save_config", boom)
    res = _complete_setup(client)
    assert res.status_code == 200
    assert auth_manager.user_count() == 0
    assert auth_manager.setup_required() is True
    # load_config / seed ne sont pas cassés
    assert real_save is config_manager.save_config


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
# Plafond global (rotation d'IP)
# ---------------------------------------------------------------------------

def test_rotating_the_ip_cannot_defeat_the_lockout(client):
    """Le constat le plus important de cette section.

    Avec `TRUSTED_PROXY_COUNT=1` (le défaut), `X-Forwarded-For` fait autorité, et
    en exposition directe c'est le client qui le fournit. Changer d'IP à chaque
    tentative permettait donc de ne jamais atteindre 5 échecs sur une même
    adresse : brute-force illimité, et autant de hachages imposés au worker
    unique. Le plafond global doit rendre cette rotation inopérante.
    """
    _complete_setup(client)
    client.get("/logout")

    for i in range(auth_manager.GLOBAL_MAX_FAILED_ATTEMPTS):
        res = client.post(
            "/login",
            data={"username": "admin", "password": "wrong"},
            environ_overrides={"REMOTE_ADDR": f"10.0.{i // 256}.{i % 256}"},
        )
        assert res.status_code == 200

    # Aucune adresse n'a échoué 5 fois…
    assert auth_manager._failed_attempts, "chaque IP ne doit avoir échoué qu'une fois"
    assert all(
        attempts < auth_manager.MAX_FAILED_ATTEMPTS
        for attempts, _ in auth_manager._failed_attempts.values()
    )

    # …et pourtant une adresse jamais vue est verrouillée.
    locked, remaining = auth_manager.is_locked_out("203.0.113.7")
    assert locked is True
    assert 0 < remaining <= auth_manager.LOCKOUT_SECONDS


def test_the_global_lockout_refuses_even_the_correct_password(client):
    _complete_setup(client)
    client.get("/logout")

    # Échecs enregistrés directement : le POST HTTP est déjà couvert par le test
    # ci-dessus, et chaque tentative réelle coûte un KDF complet à la suite.
    for i in range(auth_manager.GLOBAL_MAX_FAILED_ATTEMPTS):
        auth_manager.register_failed_attempt(f"10.1.{i // 256}.{i % 256}")

    res = client.post(
        "/login",
        data={"username": "admin", "password": "correct horse"},
        environ_overrides={"REMOTE_ADDR": "198.51.100.4"},
    )
    assert res.status_code == 200, "doit réafficher le formulaire, pas rediriger"
    assert client.get("/").status_code == 302, "aucune session ne doit être ouverte"


def test_the_global_lockout_is_a_sliding_window(monkeypatch):
    """Temporaire comme le verrou par IP : sinon une rafale bannirait le
    propriétaire pour de bon."""
    for i in range(auth_manager.GLOBAL_MAX_FAILED_ATTEMPTS):
        auth_manager.register_failed_attempt(f"10.2.{i // 256}.{i % 256}")
    assert auth_manager.is_locked_out("203.0.113.7")[0] is True

    real_now = auth_manager._now()
    monkeypatch.setattr(
        auth_manager, "_now", lambda: real_now + auth_manager.LOCKOUT_SECONDS + 1
    )
    assert auth_manager.is_locked_out("203.0.113.7")[0] is False


def test_a_successful_login_clears_the_global_counter(client):
    """Sinon la rafale d'un attaquant verrouillerait le propriétaire pendant 15
    minutes : la protection deviendrait le déni de service."""
    _complete_setup(client)
    client.get("/logout")

    for i in range(auth_manager.GLOBAL_MAX_FAILED_ATTEMPTS - 1):
        auth_manager.register_failed_attempt(f"10.3.{i // 256}.{i % 256}")

    res = client.post("/login", data={"username": "admin", "password": "correct horse"})
    assert res.status_code == 302
    assert not auth_manager._global_failures
    assert auth_manager.is_locked_out("203.0.113.7")[0] is False


def test_expired_and_excess_ip_entries_are_forgotten(monkeypatch):
    """Le suivi par IP ne doit pas devenir la charge utile de l'attaquant."""
    real_now = auth_manager._now()

    auth_manager.register_failed_attempt("10.4.0.1")
    assert "10.4.0.1" in auth_manager._failed_attempts

    # Une entrée dont la fenêtre est expirée disparaît au prochain échec.
    monkeypatch.setattr(
        auth_manager, "_now", lambda: real_now + auth_manager.LOCKOUT_SECONDS + 1
    )
    auth_manager.register_failed_attempt("10.4.0.2")
    assert "10.4.0.1" not in auth_manager._failed_attempts

    # Et le nombre d'IP suivies reste borné même dans la même fenêtre. Plafond
    # abaissé pour le test : la propriété testée est la borne, pas sa valeur.
    monkeypatch.undo()
    monkeypatch.setattr(auth_manager, "MAX_TRACKED_IPS", 10)
    for i in range(30):
        auth_manager.register_failed_attempt(f"172.16.0.{i}")
    assert len(auth_manager._failed_attempts) <= 10


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
    _complete_setup(
        client,
        username="admin",
        password="brand new password",
        legacy_password="legacy-plaintext",
    )
    client.get("/logout")
    res = client.post("/login", data={"username": "admin", "password": "legacy-plaintext"})
    assert res.status_code == 200
    assert client.get("/").status_code == 302


def test_legacy_admin_password_is_erased_after_setup(client, isolated_config):
    isolated_config.save_config({"ADMIN_PASSWORD": "legacy-plaintext", "SECRET_KEY": "k"})

    _complete_setup(client, legacy_password="legacy-plaintext")

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

    res = _complete_setup(client, legacy_password="legacy")
    assert res.status_code == 302
    assert auth_manager.user_count() == 1


# ---------------------------------------------------------------------------
# Preuve de propriété à la mise à niveau
# ---------------------------------------------------------------------------

def test_a_fresh_install_demands_no_proof(client, isolated_config):
    """Aucun secret partagé n'existe : il n'y a rien à prouver."""
    isolated_config.save_config({"SECRET_KEY": "k"})

    assert auth_manager.legacy_proof_required() is False
    assert _complete_setup(client).status_code == 302
    assert auth_manager.user_count() == 1


def test_setup_demands_the_legacy_password_when_one_exists(client, isolated_config):
    """Le cœur du correctif.

    Sur une instance déjà en service, la table `users` est vide au premier
    démarrage de cette version : `/setup` s'ouvre donc à tout le réseau alors que
    l'ancien `ADMIN_PASSWORD` ne protège plus rien. Sans preuve de propriété, le
    premier visiteur revendique l'instance — et repart avec l'écriture de
    métadonnées sur toute la bibliothèque Kavita.
    """
    isolated_config.save_config({"ADMIN_PASSWORD": "legacy-plaintext", "SECRET_KEY": "k"})

    assert auth_manager.legacy_proof_required() is True

    res = _complete_setup(client, username="attacker", password="attacker password")
    assert res.status_code == 200, "doit réafficher le formulaire, pas rediriger"
    assert auth_manager.user_count() == 0
    assert auth_manager.setup_required() is True


def test_setup_refuses_a_wrong_legacy_password_and_counts_the_attempt(client, isolated_config):
    isolated_config.save_config({"ADMIN_PASSWORD": "legacy-plaintext", "SECRET_KEY": "k"})

    res = _complete_setup(client, legacy_password="not-it")
    assert res.status_code == 200
    assert auth_manager.user_count() == 0
    assert auth_manager._failed_attempts, (
        "cet écran vérifie désormais un secret : il doit alimenter le compteur "
        "d'échecs, sinon il offre une force brute illimitée"
    )


def test_the_legacy_proof_is_subject_to_the_lockout(client, isolated_config):
    isolated_config.save_config({"ADMIN_PASSWORD": "legacy-plaintext", "SECRET_KEY": "k"})

    for _ in range(auth_manager.MAX_FAILED_ATTEMPTS):
        _complete_setup(client, legacy_password="wrong")

    assert auth_manager.is_locked_out("127.0.0.1")[0] is True

    res = _complete_setup(client, legacy_password="legacy-plaintext")
    assert res.status_code == 200, "le verrou doit tenir face à la bonne valeur"
    assert auth_manager.user_count() == 0


def test_a_valid_proof_creates_the_account_and_cannot_be_replayed(client, isolated_config):
    """La preuve est à usage unique : l'ancien mot de passe est effacé juste
    après, et l'écran de setup se ferme puisqu'un compte existe."""
    isolated_config.save_config({"ADMIN_PASSWORD": "legacy-plaintext", "SECRET_KEY": "k"})

    res = _complete_setup(client, legacy_password="legacy-plaintext")
    assert res.status_code == 302
    assert auth_manager.user_count() == 1
    assert auth_manager.legacy_proof_required() is False

    client.get("/logout")
    res = client.post("/setup", data={
        "username": "second",
        "password": "second password",
        "password_confirm": "second password",
        "legacy_password": "legacy-plaintext",
    })
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]
    assert auth_manager.user_count() == 1


def test_an_accented_legacy_password_is_compared_without_crashing(client, isolated_config):
    """`secrets.compare_digest` lève TypeError sur des `str` non ASCII : un refus
    deviendrait une 500, et un accent rendrait la preuve impossible à fournir."""
    isolated_config.save_config({"ADMIN_PASSWORD": "clé-privée-éàü", "SECRET_KEY": "k"})

    assert auth_manager.verify_legacy_password("mauvais") is False
    assert auth_manager.verify_legacy_password("clé-privée-éàü") is True
    assert _complete_setup(client, legacy_password="clé-privée-éàü").status_code == 302


def test_the_legacy_field_appears_only_when_a_proof_is_required(client, isolated_config):
    isolated_config.save_config({"SECRET_KEY": "k"})
    assert b'name="legacy_password"' not in client.get("/setup").data

    isolated_config.save_config({"ADMIN_PASSWORD": "legacy-plaintext", "SECRET_KEY": "k"})
    assert b'name="legacy_password"' in client.get("/setup").data


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


@pytest.mark.parametrize("bogus", [
    "un-mot-de-passe-en-clair",
    "pbkdf2:sha256:600000$il-manque-un-segment",
    "pas-une-methode$sel$empreinte",
    "$$",
])
def test_seeding_refuses_a_value_that_is_not_a_hash(isolated_db, monkeypatch, bogus):
    """La confusion avec l'ancien `ADMIN_PASSWORD` est facile à commettre.

    Créer le compte quand même serait le pire des deux mondes : aucun mot de
    passe ne l'ouvrirait (`check_password_hash` refuse une valeur qui n'est pas
    un hachage) et l'écran de setup se fermerait pour toujours puisqu'un compte
    existe. L'amorçage doit donc échouer et laisser le setup accessible.
    """
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", bogus)

    assert auth_manager.seed_user_from_env() is False
    assert auth_manager.user_count() == 0
    assert auth_manager.setup_required() is True


def test_a_rejected_seed_value_is_never_written_to_the_logs(isolated_db, monkeypatch, caplog):
    """Si l'utilisateur y a mis son mot de passe en clair, le journaliser ne
    ferait que le recopier dans data/metakavita.log."""
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "tr3s-secret-en-clair")

    with caplog.at_level("ERROR"):
        assert auth_manager.seed_user_from_env() is False

    assert "ADMIN_PASSWORD_HASH" in caplog.text, "l'erreur doit rester diagnosticable"
    assert "tr3s-secret-en-clair" not in caplog.text


# ---------------------------------------------------------------------------
# Changement de mot de passe
# ---------------------------------------------------------------------------

def test_change_password_requires_the_current_one(client):
    _complete_setup(client)

    res = client.post("/account/password", json={
        "current_password": "wrong password",
        "new_password": "new correct horse",
        "new_password_confirm": "new correct horse",
    })
    assert res.status_code == 400
    assert res.get_json()["success"] is False
    # L'ancien mot de passe doit rester valide : rien n'a dû changer.
    assert auth_manager.verify_credentials("admin", "correct horse") is not None


def test_change_password_updates_the_hash(client):
    _complete_setup(client)

    res = client.post("/account/password", json={
        "current_password": "correct horse",
        "new_password": "new correct horse",
        "new_password_confirm": "new correct horse",
    })
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    assert auth_manager.verify_credentials("admin", "correct horse") is None
    assert auth_manager.verify_credentials("admin", "new correct horse") is not None


def test_change_password_refuses_mismatched_confirmation(client):
    _complete_setup(client)

    res = client.post("/account/password", json={
        "current_password": "correct horse",
        "new_password": "new correct horse",
        "new_password_confirm": "something else",
    })
    assert res.status_code == 400
    assert auth_manager.verify_credentials("admin", "correct horse") is not None


def test_change_password_refuses_a_too_short_new_password(client):
    _complete_setup(client)

    res = client.post("/account/password", json={
        "current_password": "correct horse",
        "new_password": "short",
        "new_password_confirm": "short",
    })
    assert res.status_code == 400
    assert auth_manager.verify_credentials("admin", "correct horse") is not None


def test_change_password_requires_an_active_session(client):
    """Sans session (ex: cookie expiré), le gate doit rediriger avant la vue —
    même comportement que n'importe quelle autre route protégée."""
    _complete_setup(client)
    client.get("/logout")

    res = client.post("/account/password", json={
        "current_password": "correct horse",
        "new_password": "new correct horse",
        "new_password_confirm": "new correct horse",
    })
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_a_wrong_current_password_counts_as_a_failed_login_attempt(client):
    """Sinon un onglet resté ouvert deviendrait un oracle de brute-force sans le
    verrouillage qui protège /login."""
    _complete_setup(client)

    for _ in range(auth_manager.MAX_FAILED_ATTEMPTS):
        client.post("/account/password", json={
            "current_password": "wrong password",
            "new_password": "new correct horse",
            "new_password_confirm": "new correct horse",
        })

    locked, _remaining = auth_manager.is_locked_out("127.0.0.1")
    assert locked is True


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
