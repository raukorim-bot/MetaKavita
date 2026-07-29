"""
Non-régression de la sonde de liveness `/healthz` (endpoint 'misc.healthz').

Deux propriétés comptent, et une seule des deux est évidente :

1. L'endpoint répond 200 avec `{status, version}`.
2. Il reste joignable **sans session**. C'est là qu'est le vrai risque de
   régression : la whitelist de `require_login` (app.py) fonctionne sur les *noms
   d'endpoints Flask*, donc renommer le blueprint ou la vue casse silencieusement
   la sonde — le HEALTHCHECK du conteneur se met à recevoir des 302, Docker
   marque un conteneur sain comme unhealthy, et une restart policy le redémarre
   en boucle. Rien dans le reste de la suite n'attraperait ça.

Comme le reste de la suite (voir tests/conftest.py), on n'importe jamais
`app.py` : il démarre des threads de fond et charge tous les scrapers à
l'import. On reconstruit donc ici le gate `require_login` à l'identique sur une
app Flask ad hoc.
"""
import pytest
from flask import Flask, redirect, request, session, url_for

from routes.misc import misc_bp


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
# Le point qui compte : la whitelist de require_login
# ---------------------------------------------------------------------------

def _build_app_with_login_gate(admin_password):
    """Reproduit le gate `require_login` de app.py, whitelist comprise."""
    test_app = Flask(__name__)
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    test_app.register_blueprint(misc_bp)

    @test_app.route("/login")
    def login():  # noqa: D401 - simple stub pour url_for
        return "login page", 200

    @test_app.route("/protected")
    def protected():
        return "secret", 200

    @test_app.before_request
    def require_login():
        if request.method == "OPTIONS":
            return None
        # Doit rester synchronisé avec app.py::require_login.
        if request.endpoint in ["login", "static", "sync.webhook", "misc.healthz"]:
            return
        if admin_password and not session.get("logged_in"):
            return redirect(url_for("login"))

    return test_app.test_client()


def test_healthz_reachable_without_a_session_when_a_password_is_set():
    """Le cas qui casse en production si la whitelist perd 'misc.healthz'."""
    client = _build_app_with_login_gate(admin_password="hunter2")

    res = client.get("/healthz")

    assert res.status_code == 200, (
        "/healthz doit rester accessible sans session : c'est la cible du "
        "HEALTHCHECK du conteneur"
    )
    assert res.get_json()["status"] == "ok"


def test_the_gate_still_protects_everything_else():
    """Contre-épreuve : la whitelist n'ouvre pas le reste de l'application."""
    client = _build_app_with_login_gate(admin_password="hunter2")

    res = client.get("/protected")

    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_healthz_also_fine_when_no_password_is_configured():
    client = _build_app_with_login_gate(admin_password="")
    assert client.get("/healthz").status_code == 200
