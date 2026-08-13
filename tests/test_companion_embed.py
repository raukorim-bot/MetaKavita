"""
C33 Companion — /companion/embed route, CSP frame-ancestors, allowlist helper.

Contient aussi le périmètre du jeton d'embed : il contourne à la fois la session
et — dans ce périmètre — le CSRF, donc chaque test ci-dessous fixe une frontière
qui, si elle bougeait, ouvrirait l'application à un jeton qui voyage en query
string (journaux de reverse proxy, historique, `Referer`).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask, jsonify

import auth_manager
from companion_csp import (
    build_frame_ancestors_csp,
    is_allowed_parent_origin,
    is_http_origin,
    normalize_origin,
    parse_companion_frame_ancestors,
)
from csrf_utils import csrf_protect_before_request
from routes.companion import companion_bp
from routes.misc import misc_bp
from services.companion_embed_auth import (
    clear_all_embed_tokens,
    issue_embed_token,
    peek_embed_token,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_parse_companion_frame_ancestors_rejects_star():
    assert parse_companion_frame_ancestors("https://kavita.local, * , https://other.local") == [
        "https://kavita.local",
        "https://other.local",
    ]


def test_build_frame_ancestors_always_includes_extension_schemes():
    csp = build_frame_ancestors_csp(["https://kavita.local"])
    assert "chrome-extension:" in csp
    assert "moz-extension:" in csp
    assert "https://kavita.local" in csp
    assert "*" not in csp.split()


def test_is_http_origin_accepts_bare_origins():
    assert is_http_origin("http://192.168.1.116:5001")
    assert is_http_origin("https://kavita.example")
    assert is_http_origin("http://localhost:5000")


def test_is_http_origin_rejects_junk():
    assert not is_http_origin("")
    assert not is_http_origin(None)
    assert not is_http_origin("javascript:alert(1)")
    assert not is_http_origin("chrome-extension://abc")
    assert not is_http_origin("http://host/with/path")
    assert not is_http_origin("ftp://host")


def test_normalize_origin_strips_trailing_slash():
    assert normalize_origin("http://host:5001/") == "http://host:5001"
    assert normalize_origin("  http://host  ") == "http://host"
    assert normalize_origin(None) == ""


def test_is_allowed_parent_origin():
    assert is_allowed_parent_origin("chrome-extension://abcdef")
    assert is_allowed_parent_origin("moz-extension://abcdef")
    assert not is_allowed_parent_origin("https://evil.example")
    assert not is_allowed_parent_origin("")
    assert not is_allowed_parent_origin(None)


@pytest.fixture
def companion_app(monkeypatch):
    monkeypatch.setattr(
        "routes.companion.load_config",
        lambda: {
            "UI_LANG": "fr",
            "KAVITA_URL": "http://kavita.local",
            "COMPANION_FRAME_ANCESTORS": "https://kavita.local",
            "WEBHOOK_TOKEN": "w",
            "SECRET_KEY": "k",
        },
    )
    monkeypatch.setattr(auth_manager, "setup_required", lambda: False)

    app = Flask(
        __name__,
        template_folder=str(REPO_ROOT / "templates"),
        static_folder=str(REPO_ROOT / "static"),
    )
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(companion_bp)
    app.register_blueprint(misc_bp)

    @app.route("/")
    def index():
        return "ok", 200

    @app.route("/login")
    def login():
        return "login", 200

    @app.route("/stats")
    def stats():
        return "stats", 200

    # login_gate uses url_for("auth.login") — alias endpoint name.
    app.add_url_rule("/login", endpoint="auth.login", view_func=login)
    app.add_url_rule("/stats", endpoint="pages.stats", view_func=stats)

    app.before_request(auth_manager.login_gate)

    @app.context_processor
    def _inject():
        return {"csrf_token": "test-csrf", "proxy_cover_hosts": []}

    return app


def test_companion_blueprint_registered(companion_app):
    rules = [r.endpoint for r in companion_app.url_map.iter_rules()]
    assert "companion.companion_embed" in rules


def test_embed_requires_login(companion_app):
    client = companion_app.test_client()
    res = client.get("/companion/embed?series_id=1")
    assert res.status_code in (302, 401)
    if res.status_code == 302:
        assert "/login" in (res.headers.get("Location") or "")


def test_embed_ok_when_authenticated(companion_app):
    client = companion_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    res = client.get("/companion/embed?series_id=42")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'data-companion-marker="embed-wait"' in body
    assert "COMPANION_EMBED" in body
    assert "seriesId: 42" in body


def test_embed_sets_frame_ancestors_extension_schemes(companion_app):
    client = companion_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    res = client.get("/companion/embed?series_id=1")
    csp = res.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors" in csp
    assert "chrome-extension:" in csp
    assert "moz-extension:" in csp
    assert "https://kavita.local" in csp
    assert res.headers.get("X-Frame-Options") is None


def test_embed_includes_kavita_ui_origin_in_frame_ancestors(companion_app):
    """The top-level Kavita page (KAVITA_URL origin) must be a valid ancestor."""
    client = companion_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    res = client.get("/companion/embed?series_id=1")
    csp = res.headers.get("Content-Security-Policy", "")
    assert "http://kavita.local" in csp


def test_embed_whitelists_top_origin_query_param(companion_app):
    """A Kavita page served on a different origin is added via ?top_origin."""
    client = companion_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    res = client.get(
        "/companion/embed?series_id=1&top_origin=http://192.168.1.116:5001"
    )
    csp = res.headers.get("Content-Security-Policy", "")
    assert "http://192.168.1.116:5001" in csp


def test_embed_ignores_malformed_top_origin(companion_app):
    """Non-origin junk in top_origin must never reach the CSP header."""
    client = companion_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    res = client.get(
        "/companion/embed?series_id=1&top_origin=javascript:alert(1)"
    )
    csp = res.headers.get("Content-Security-Policy", "")
    assert "javascript:" not in csp


def test_embed_rejects_missing_series_id(companion_app):
    client = companion_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    res = client.get("/companion/embed")
    assert res.status_code == 400


def test_embed_does_not_weaken_other_routes_framing(companion_app):
    client = companion_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    res = client.get("/")
    assert res.status_code == 200
    csp = res.headers.get("Content-Security-Policy", "")
    assert "chrome-extension:" not in csp


# ---------------------------------------------------------------------------
# Périmètre du jeton d'embed : session ET CSRF
# ---------------------------------------------------------------------------

@pytest.fixture
def embed_scope_app(monkeypatch):
    """App portant les deux gates ET le CSRF réellement actif.

    `csrf_protect_before_request` est un no-op sous `TESTING` : il faut donc une
    app dédiée en `TESTING=False` pour observer ce que le jeton d'embed exempte,
    et surtout ce qu'il n'exempte plus.

    Les vues de review manuelle sont des doublures : ce qui est testé ici est la
    frontière posée par les gates, pas le moteur d'application des métadonnées.
    Les endpoints portent en revanche les NOMS réels — c'est sur eux que portent
    les listes de `auth_manager`.
    """
    monkeypatch.setattr(auth_manager, "setup_required", lambda: False)
    clear_all_embed_tokens()

    def fake_get_pending_review(review_id):
        """`r-9…` appartient à la série 9, tout le reste à la série 4242."""
        rid = str(review_id)
        return {"review_id": rid, "series_id": 9 if rid.startswith("r-9") else 4242}

    monkeypatch.setattr("db_manager.get_pending_review", fake_get_pending_review)

    app = Flask(__name__)
    app.config.update(TESTING=False, SECRET_KEY="test-secret")
    calls = {"save_config": 0, "choice": 0, "confirm": 0, "skip": 0}
    app.probe_calls = calls

    def login():
        return "login", 200

    def save_config():
        calls["save_config"] += 1
        return jsonify(success=True)

    def choice(review_id):
        calls["choice"] += 1
        # `-auto` = pas d'étape d'édition : la revue est conclue tout de suite.
        if str(review_id).endswith("-auto"):
            return jsonify(success=True, mode="applied", message="ok")
        return jsonify(success=True, mode="preview", preview={})

    def confirm(review_id):
        calls["confirm"] += 1
        if str(review_id).endswith("-fail"):
            return jsonify(success=False, error="Review introuvable"), 400
        return jsonify(success=True, message="ok")

    def skip(review_id):
        calls["skip"] += 1
        return jsonify(success=True, count=0)

    app.add_url_rule("/login", endpoint="auth.login", view_func=login)
    app.add_url_rule(
        "/save-config", endpoint="config.save_config",
        view_func=save_config, methods=["POST"],
    )
    app.add_url_rule(
        "/api/manual-reviews/<review_id>/choice",
        endpoint="manual_review.api_manual_review_choice",
        view_func=choice, methods=["POST"],
    )
    app.add_url_rule(
        "/api/manual-reviews/<review_id>/confirm",
        endpoint="manual_review.api_manual_review_confirm",
        view_func=confirm, methods=["POST"],
    )
    app.add_url_rule(
        "/api/manual-reviews/<review_id>/skip",
        endpoint="manual_review.api_manual_review_skip",
        view_func=skip, methods=["POST"],
    )

    # Ordre identique à app.py : login_gate puis csrf_protect.
    app.before_request(auth_manager.login_gate)
    app.before_request(csrf_protect_before_request)
    yield app
    clear_all_embed_tokens()


def test_an_embed_token_does_not_disable_csrf_outside_its_scope(embed_scope_app):
    """Le piège : l'exemption CSRF acceptait « n'importe quel jeton encore valide ».

    Elle appelait `authorize_companion_request()` sans `series_id` et sans
    regarder l'endpoint, donc un jeton émis pour une série quelconque faisait
    sauter la protection CSRF de TOUTE l'application. Ce jeton n'est pas un
    secret bien gardé : il voyage en query string, donc dans les journaux du
    reverse proxy, l'historique du navigateur et le `Referer`.
    """
    token = issue_embed_token(4242)
    client = embed_scope_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1

    res = client.post("/save-config?embed_token=" + token, data={"PROVIDERS_SAVE": "1"})
    assert res.status_code == 403
    res = client.post("/save-config", headers={"X-Companion-Embed-Token": token})
    assert res.status_code == 403
    assert embed_scope_app.probe_calls["save_config"] == 0


def test_an_embed_token_still_exempts_the_reviews_of_its_own_series(embed_scope_app):
    """L'exemption doit survivre au correctif, sinon la Super Review est morte.

    SameSite=Lax n'envoie pas le cookie de session dans une iframe Kavita
    cross-origin : il n'existe alors aucun jeton CSRF de session à soumettre.
    """
    token = issue_embed_token(4242)
    client = embed_scope_app.test_client()

    res = client.post(
        "/api/manual-reviews/r-4242/choice",
        headers={"X-Companion-Embed-Token": token},
        json={"base_provider": "MANGADEX"},
    )
    assert res.status_code == 200
    assert res.get_json()["success"] is True


def test_an_embed_token_cannot_reach_the_reviews_of_another_series(embed_scope_app):
    """Le `series_id` est résolu en base, jamais déduit de l'URL."""
    token = issue_embed_token(4242)
    client = embed_scope_app.test_client()

    res = client.post(
        "/api/manual-reviews/r-9/skip",
        headers={"X-Companion-Embed-Token": token},
    )
    assert res.status_code == 401
    assert embed_scope_app.probe_calls["skip"] == 0


def test_the_embed_token_is_revoked_once_the_review_is_confirmed(embed_scope_app):
    """`revoke_embed_token` n'avait aucun appelant en production.

    Après un « Confirmer », le shell d'embed est fermé mais le jeton restait
    utilisable jusqu'à son expiration — alors qu'il contourne la session ET, dans
    son périmètre, le CSRF.
    """
    token = issue_embed_token(4242)
    client = embed_scope_app.test_client()

    res = client.post(
        "/api/manual-reviews/r-4242/confirm",
        headers={"X-Companion-Embed-Token": token},
        json={"base_provider": "MANGADEX"},
    )
    assert res.status_code == 200
    assert peek_embed_token(token) is None

    # …et il ne rouvre plus rien.
    res = client.post(
        "/api/manual-reviews/r-4242/skip",
        headers={"X-Companion-Embed-Token": token},
    )
    assert res.status_code == 401


def test_the_embed_token_is_revoked_when_the_review_is_skipped(embed_scope_app):
    token = issue_embed_token(4242)
    client = embed_scope_app.test_client()

    res = client.post(
        "/api/manual-reviews/r-4242/skip",
        headers={"X-Companion-Embed-Token": token},
    )
    assert res.status_code == 200
    assert peek_embed_token(token) is None


def test_a_choice_that_only_returns_a_preview_keeps_the_token(embed_scope_app):
    """`/choice` n'est pas toujours une conclusion : avec l'édition activée il
    renvoie `mode="preview"` et la revue continue. Révoquer là couperait l'embed
    entre le choix du candidat et le « Confirmer »."""
    token = issue_embed_token(4242)
    client = embed_scope_app.test_client()

    res = client.post(
        "/api/manual-reviews/r-4242/choice",
        headers={"X-Companion-Embed-Token": token},
        json={"base_provider": "MANGADEX"},
    )
    assert res.get_json()["mode"] == "preview"
    assert peek_embed_token(token) is not None


def test_a_choice_applied_without_the_edit_step_revokes_the_token(embed_scope_app):
    """Sans phase d'édition, `/choice` écrit directement : c'est la fin de la revue."""
    token = issue_embed_token(4242)
    client = embed_scope_app.test_client()

    res = client.post(
        "/api/manual-reviews/r-4242-auto/choice",
        headers={"X-Companion-Embed-Token": token},
        json={"base_provider": "MANGADEX"},
    )
    assert res.get_json()["mode"] == "applied"
    assert peek_embed_token(token) is None


def test_a_failed_completion_keeps_the_token_usable(embed_scope_app):
    """Rien n'a été écrit : révoquer fermerait la revue au lieu de laisser
    l'utilisateur réessayer."""
    token = issue_embed_token(4242)
    client = embed_scope_app.test_client()

    res = client.post(
        "/api/manual-reviews/r-4242-fail/confirm",
        headers={"X-Companion-Embed-Token": token},
        json={"base_provider": "MANGADEX"},
    )
    assert res.status_code == 400
    assert peek_embed_token(token) is not None


def test_the_embed_token_is_accepted_from_the_dedicated_header(embed_scope_app):
    """L'en-tête doit rester une alternative complète à la query string : c'est
    ce qui permet au client de ne plus publier le jeton dans une URL."""
    token = issue_embed_token(4242)
    client = embed_scope_app.test_client()

    res = client.post(
        "/api/manual-reviews/r-4242/choice",
        headers={"X-Companion-Embed-Token": token},
        json={"base_provider": "MANGADEX"},
    )
    assert res.status_code == 200
