"""
C33 Companion — /companion/embed route, CSP frame-ancestors, allowlist helper.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

import auth_manager
from companion_csp import (
    build_frame_ancestors_csp,
    is_allowed_parent_origin,
    is_http_origin,
    normalize_origin,
    parse_companion_frame_ancestors,
)
from routes.companion import companion_bp
from routes.misc import misc_bp

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
