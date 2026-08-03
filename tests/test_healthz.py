"""
Non-régression de la sonde de liveness `/healthz` (endpoint 'misc.healthz').

Deux propriétés comptent, et une seule des deux est évidente :

1. L'endpoint répond 200 avec `{status, version}`.
2. Il reste joignable **sans session**. C'est là qu'est le vrai risque de
   régression : les whitelists de `auth_manager.setup_gate` / `login_gate`
   portent sur les *noms d'endpoints Flask*, donc renommer le blueprint ou la
   vue casse silencieusement la sonde — le HEALTHCHECK du conteneur se met à
   recevoir des 302, Docker marque un conteneur sain comme unhealthy, et une
   restart policy le redémarre en boucle. Rien dans le reste de la suite
   n'attraperait ça (hors `tests/test_auth.py`, qui couvre le même contrat
   avec les vrais gates).

Comme le reste de la suite (voir tests/conftest.py), on n'importe jamais
`app.py` : il démarre des threads de fond et charge tous les scrapers à
l'import. On reconstruit donc ici un gate fail-closed aligné sur
`auth_manager` (C58) sur une app Flask ad hoc.
"""
import pytest
from flask import Flask, redirect, request, session, url_for

from routes.misc import misc_bp

# Doit rester synchronisé avec auth_manager._LOGIN_ALLOWED_ENDPOINTS (C58).
_LOGIN_ALLOWED_ENDPOINTS = frozenset({
    "auth.login",
    "auth.setup",
    "auth.setup_test_kavita",
    "static",
    "misc.healthz",
    "sync.webhook",
})


@pytest.fixture
def healthz_client():
    """App Flask minimale n'exposant que le blueprint 'misc'."""
    test_app = Flask(__name__)
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    test_app.register_blueprint(misc_bp)
    return test_app.test_client()


def test_healthz_returns_200_and_a_payload(healthz_client):
    res = healthz_client.get("/healthz")

    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "ok"
    assert body["version"], "la version ne doit jamais être vide"


def test_healthz_is_json(healthz_client):
    assert healthz_client.get("/healthz").mimetype == "application/json"


def test_healthz_does_not_leak_more_than_status_and_version(healthz_client):
    """L'endpoint est non authentifié : son payload doit rester minimal.

    Garde-fou délibéré contre l'ajout futur d'un détail « utile » (chemin de la
    base, URL Kavita, présence d'une clé d'API…) à une réponse que n'importe qui
    peut interroger sans session.
    """
    assert set(healthz_client.get("/healthz").get_json()) == {"status", "version"}


# ---------------------------------------------------------------------------
# Le point qui compte : la whitelist fail-closed (C58)
# ---------------------------------------------------------------------------

def _build_app_with_login_gate(*, authenticated: bool):
    """Reproduit le contrat de `auth_manager.login_gate` (fail-closed + whitelist)."""
    test_app = Flask(__name__)
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    test_app.register_blueprint(misc_bp)

    @test_app.route("/login", endpoint="auth.login")
    def login():  # noqa: D401 - simple stub pour url_for
        return "login page", 200

    @test_app.route("/setup", endpoint="auth.setup")
    def setup():
        return "setup page", 200

    @test_app.route("/protected", endpoint="pages.index")
    def protected():
        return "secret", 200

    @test_app.before_request
    def login_gate():
        if request.method == "OPTIONS":
            return None
        if request.endpoint in _LOGIN_ALLOWED_ENDPOINTS:
            return None
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return None

    client = test_app.test_client()
    if authenticated:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
    return client


def test_healthz_reachable_without_a_session_when_auth_is_enforced():
    """Le cas qui casse en production si la whitelist perd 'misc.healthz'."""
    client = _build_app_with_login_gate(authenticated=False)

    res = client.get("/healthz")

    assert res.status_code == 200, (
        "/healthz doit rester accessible sans session : c'est la cible du "
        "HEALTHCHECK du conteneur"
    )
    assert res.get_json()["status"] == "ok"


def test_the_gate_still_protects_everything_else():
    """Contre-épreuve : la whitelist n'ouvre pas le reste de l'application."""
    client = _build_app_with_login_gate(authenticated=False)

    res = client.get("/protected")

    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_healthz_also_fine_when_authenticated():
    client = _build_app_with_login_gate(authenticated=True)
    assert client.get("/healthz").status_code == 200
    assert client.get("/protected").status_code == 200
