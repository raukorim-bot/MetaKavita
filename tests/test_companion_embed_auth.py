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
            "MANUAL_REVIEW_COVER_PICK": True,
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


def test_embed_exposes_review_options(companion_app):
    """BF107 — the shell has no sidebar, so manual_review.js reads the cover-pick /
    super-review options from COMPANION_EMBED.options. Missing them silently
    skipped the cover phase on every Companion Super Review."""
    client = companion_app.test_client()
    tok = _issue_token(client, series_id=7)

    res = client.get(f"/companion/embed?series_id=7&embed_token={tok}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert '"coverPick": true' in html
    assert '"superReview": true' in html
    assert '"manualMode": true' in html


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


def test_proxy_image_requires_login_without_embed_token(companion_app):
    client = companion_app.test_client()
    res = client.get("/api/proxy-image?url=https://uploads.mangadex.org/covers/x.jpg")
    assert res.status_code in (302, 401)


def _issue_token(client, series_id=7):
    res = client.post(
        "/companion/embed-token",
        headers={"X-Webhook-Token": "w-secret"},
        json={"seriesId": series_id, "parent_origin": "chrome-extension://abc"},
    )
    return res.get_json()["embed_token"]


def _stub_proxy_image(monkeypatch):
    class FakeResp:
        status_code = 200
        headers = {"Content-Type": "image/jpeg", "Content-Length": "4"}

        def iter_content(self, chunk_size=65536):
            yield b"\xff\xd8\xff\xd9"

        def close(self):
            pass

    monkeypatch.setattr(
        "routes.misc.fetch_with_safe_redirects",
        lambda *a, **k: (FakeResp(), None, "https://uploads.mangadex.org/covers/x.jpg"),
    )
    monkeypatch.setattr(
        "routes.misc.ScraperRegistry.get_all_proxy_domains",
        lambda: ["uploads.mangadex.org", "mangadex.org"],
    )
    monkeypatch.setattr(
        "routes.misc.ScraperRegistry.get_all",
        lambda include_disabled=False: [],
    )


def test_proxy_image_allows_companion_embed_token(companion_app, monkeypatch):
    """Cover picker <img> on Kavita page: absolute Meta proxy + ?embed_token=."""
    client = companion_app.test_client()
    tok = _issue_token(client)
    _stub_proxy_image(monkeypatch)

    res = client.get(
        "/api/proxy-image?url=https://uploads.mangadex.org/covers/x.jpg"
        f"&embed_token={tok}"
    )
    assert res.status_code == 200
    assert res.data[:2] == b"\xff\xd8"


def test_proxy_image_allows_companion_embed_token_header(companion_app, monkeypatch):
    """Mixed content (HTTPS Kavita + HTTP Meta): the service worker fetches the
    preview itself and can send the token as a header instead of a query param."""
    client = companion_app.test_client()
    tok = _issue_token(client)
    _stub_proxy_image(monkeypatch)

    res = client.get(
        "/api/proxy-image?url=https://uploads.mangadex.org/covers/x.jpg",
        headers={"X-Companion-Embed-Token": tok},
    )
    assert res.status_code == 200
    assert res.data[:2] == b"\xff\xd8"


# --------------------------------------------------------------------------
# Portée série du jeton sur les routes de review manuelle
#
# Le préfixe `manual_review.*` acceptait n'importe quel jeton valide : un jeton
# émis pour la série 7 pouvait lister, confirmer, re-chercher ou passer les
# reviews de toutes les autres séries pendant ses 15 minutes de vie.
# --------------------------------------------------------------------------

@pytest.fixture
def review_app(companion_app, isolated_db):
    from routes.manual_review import manual_review_bp

    companion_app.register_blueprint(manual_review_bp)
    return companion_app


def _park(isolated_db, series_id, name):
    payload = {"above": [{"provider": "A", "score": 0.9, "title": name, "data": {}}],
               "below": [], "query": name}
    review_id = f"rev-{series_id}"
    isolated_db.park_pending_review(
        review_id=review_id, series_id=series_id, series_name=name,
        candidates_json=payload, base_provider="A", chosen_score=0.9,
    )
    return review_id


def test_embed_token_cannot_confirm_another_series_review(review_app, isolated_db, monkeypatch):
    client = review_app.test_client()
    tok = _issue_token(client, series_id=7)
    other = _park(isolated_db, 99, "Autre série")
    applied = []
    monkeypatch.setattr(
        "routes.manual_review.apply_manual_review",
        lambda *a, **k: applied.append(a) or (True, "ok", {}),
    )

    res = client.post(
        f"/api/manual-reviews/{other}/confirm",
        json={"base_provider": "A"},
        headers={"X-Companion-Embed-Token": tok},
    )

    assert res.status_code in (302, 401), "le jeton de la série 7 ne doit pas confirmer la série 99"
    assert applied == [], "aucune écriture ne doit avoir lieu"


def test_embed_token_confirms_its_own_series_review(review_app, isolated_db, monkeypatch):
    client = review_app.test_client()
    tok = _issue_token(client, series_id=7)
    mine = _park(isolated_db, 7, "Ma série")
    monkeypatch.setattr(
        "routes.manual_review.apply_manual_review",
        lambda *a, **k: (True, "ok", {}),
    )

    res = client.post(
        f"/api/manual-reviews/{mine}/confirm",
        json={"base_provider": "A"},
        headers={"X-Companion-Embed-Token": tok},
    )

    assert res.status_code == 200
    assert res.get_json()["success"] is True


def test_embed_token_cannot_skip_another_series_review(review_app, isolated_db):
    client = review_app.test_client()
    tok = _issue_token(client, series_id=7)
    other = _park(isolated_db, 99, "Autre série")

    res = client.post(
        f"/api/manual-reviews/{other}/skip",
        headers={"X-Companion-Embed-Token": tok},
    )

    assert res.status_code in (302, 401)
    assert isolated_db.get_pending_review(other) is not None


def test_embed_token_only_sees_its_own_series_in_the_queue(review_app, isolated_db):
    """La file complète — noms des autres séries, volumétrie de la bibliothèque —
    ne doit pas sortir par un jeton d'embed."""
    client = review_app.test_client()
    tok = _issue_token(client, series_id=7)
    _park(isolated_db, 7, "Ma série")
    _park(isolated_db, 99, "Série privée")

    res = client.get("/api/manual-reviews", headers={"X-Companion-Embed-Token": tok})

    assert res.status_code == 200
    body = res.get_json()
    assert [r["series_id"] for r in body["reviews"]] == [7]
    assert body["count"] == 1
    assert "Série privée" not in res.get_data(as_text=True)


def test_embed_token_cannot_bulk_accept_or_purge(review_app, isolated_db):
    """Deux opérations de masse sur toute la file : session obligatoire."""
    client = review_app.test_client()
    tok = _issue_token(client, series_id=7)
    _park(isolated_db, 7, "Ma série")
    _park(isolated_db, 99, "Autre série")

    for url in ("/api/manual-reviews/bulk-accept", "/api/manual-reviews/purge"):
        res = client.post(url, json={}, headers={"X-Companion-Embed-Token": tok})
        assert res.status_code in (302, 401), url

    assert isolated_db.count_pending_reviews() == 2


def test_an_unknown_review_answers_404_not_a_login_redirect(review_app, isolated_db):
    """Un 302 vers /login ferait croire à une session expirée dans l'embed."""
    client = review_app.test_client()
    tok = _issue_token(client, series_id=7)

    res = client.post(
        "/api/manual-reviews/does-not-exist/skip",
        headers={"X-Companion-Embed-Token": tok},
    )

    assert res.status_code == 404
