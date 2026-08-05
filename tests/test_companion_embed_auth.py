"""C33 Companion embed token auth (SameSite iframe bypass)."""
from __future__ import annotations

import time

import pytest
from flask import Flask

import auth_manager
from companion_csp import parse_companion_frame_ancestors
from pathlib import Path
from routes.companion import companion_bp
from routes.misc import misc_bp
from services import companion_embed_auth as cea

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_tokens():
    cea.clear_all_embed_tokens()
    yield
    cea.clear_all_embed_tokens()


def test_issue_and_validate_embed_token():
    tok = cea.issue_embed_token(42, parent_origin="chrome-extension://abc")
    assert cea.validate_embed_token(tok, 42)["series_id"] == 42
    assert cea.validate_embed_token(tok, 99) is None
    assert cea.validate_embed_token("nope", 42) is None


def test_embed_token_expires(monkeypatch):
    tok = cea.issue_embed_token(1, ttl_sec=60)
    with cea._LOCK:
        cea._TOKENS[tok]["exp"] = time.time() - 1
    assert cea.peek_embed_token(tok) is None


def test_empty_config_frame_ancestors_does_not_read_env(monkeypatch):
    from routes.companion import _extra_frame_ancestors

    monkeypatch.setenv("COMPANION_FRAME_ANCESTORS", "https://from-env.example")
    # Explicit empty string in config must mean "no extras" (B11).
    assert _extra_frame_ancestors({"COMPANION_FRAME_ANCESTORS": ""}) == []
    # Missing key still falls back to env.
    assert "https://from-env.example" in _extra_frame_ancestors({})
    assert parse_companion_frame_ancestors("") == []


@pytest.fixture
def companion_app(monkeypatch):
    monkeypatch.setattr(
        "routes.companion.load_config",
        lambda: {
            "UI_LANG": "fr",
            "KAVITA_URL": "http://kavita.local",
            "COMPANION_FRAME_ANCESTORS": "",
            "WEBHOOK_TOKEN": "w-secret",
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

    app.add_url_rule("/login", endpoint="auth.login", view_func=login)
    app.add_url_rule("/stats", endpoint="pages.stats", view_func=stats)
    app.before_request(auth_manager.login_gate)

    @app.context_processor
    def _inject():
        return {"csrf_token": "test-csrf", "proxy_cover_hosts": []}

    return app


def test_embed_token_endpoint_requires_webhook_auth(companion_app):
    client = companion_app.test_client()
    res = client.post(
        "/companion/embed-token",
        json={"seriesId": 7, "parent_origin": "chrome-extension://abc"},
    )
    assert res.status_code == 401


def test_embed_with_token_bypasses_login(companion_app):
    client = companion_app.test_client()
    res = client.post(
        "/companion/embed-token",
        headers={"X-Webhook-Token": "w-secret"},
        json={"seriesId": 7, "parent_origin": "chrome-extension://abc"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    tok = body["embed_token"]
    assert tok

    res2 = client.get(f"/companion/embed?series_id=7&embed_token={tok}&parent_origin=chrome-extension://abc")
    assert res2.status_code == 200
    assert 'data-companion-marker="embed-wait"' in res2.get_data(as_text=True)


def test_embed_token_wrong_series_still_requires_login(companion_app):
    client = companion_app.test_client()
    res = client.post(
        "/companion/embed-token",
        headers={"X-Webhook-Token": "w-secret"},
        json={"seriesId": 7},
    )
    tok = res.get_json()["embed_token"]
    res2 = client.get(f"/companion/embed?series_id=99&embed_token={tok}")
    assert res2.status_code in (302, 401)
