"""
Tests du classificateur de diagnostic scrapers + préflight + routes API.

Aucun appel réseau réel : requests / KavitaAPI / scrapers sont mockés.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
from flask import Flask, redirect, session, url_for, request

from routes.diagnostics import diagnostics_bp
from routes.pages import pages_bp
from scrapers.base import BaseScraper
from services import scraper_diagnostics as diag


# ---------------------------------------------------------------------------
# Classificateur unitaire
# ---------------------------------------------------------------------------

def test_analyze_metadata_complete_is_ok():
    result = diag._analyze_metadata({
        "title": "Berserk",
        "summary": "Dark fantasy",
        "cover_url": "https://example.com/c.jpg",
        "genres": ["Action"],
        "year": 1989,
    })
    assert result["status"] == "ok"
    assert result["cause"] == "ok"
    assert result["sample_title"] == "Berserk"


def test_analyze_metadata_none_is_schema():
    result = diag._analyze_metadata(None)
    assert result["status"] == "down"
    assert result["cause"] == "schema"


def test_analyze_metadata_partial_is_degraded():
    result = diag._analyze_metadata({"title": "Berserk"})
    assert result["status"] == "degraded"
    assert result["cause"] == "partial"


def test_analyze_covers_empty_is_covers_schema():
    result = diag._analyze_covers([], supported=True)
    assert result["status"] == "down"
    assert result["cause"] == "covers_schema"


def test_analyze_covers_valid():
    result = diag._analyze_covers(
        [{"provider": "X", "title": "T", "url": "https://example.com/a.jpg"}],
        supported=True,
    )
    assert result["status"] == "ok"
    assert result["count"] == 1


def test_analyze_covers_n_a_when_unsupported():
    result = diag._analyze_covers([], supported=False)
    assert result["status"] == "n_a"


def test_combine_ok_plus_covers_down_is_degraded():
    status, cause = diag._combine(
        {"status": "ok", "cause": "ok"},
        {"status": "down", "cause": "covers_schema"},
    )
    assert status == "degraded"
    assert cause == "covers_schema"


def test_combine_both_ok():
    status, cause = diag._combine(
        {"status": "ok", "cause": "ok"},
        {"status": "ok", "cause": "ok"},
    )
    assert status == "ok"
    assert cause == "ok"


def test_combine_covers_na_does_not_degrade():
    status, cause = diag._combine(
        {"status": "ok", "cause": "ok"},
        {"status": "n_a", "cause": "ok"},
    )
    assert status == "ok"


# ---------------------------------------------------------------------------
# Préflight mocké
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code

    def close(self):
        pass


def test_probe_internet_ok_generate_204(monkeypatch):
    def fake_get(url, **kwargs):
        assert "generate_204" in url
        return _FakeResp(204)

    monkeypatch.setattr(diag.requests, "get", fake_get)
    result = diag.probe_internet()
    assert result["status"] == "ok"
    assert result["cause"] == "ok"


def test_probe_internet_timeout(monkeypatch):
    def fake_get(url, **kwargs):
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(diag.requests, "get", fake_get)
    result = diag.probe_internet()
    assert result["status"] == "down"
    assert result["cause"] == "network"
    assert result["detail"] == "timeout"


def test_probe_kavita_missing_config():
    result = diag.probe_kavita({"KAVITA_URL": "", "KAVITA_API_KEY": ""})
    assert result["status"] == "down"
    assert result["detail"] == "missing"


def test_probe_kavita_ok(monkeypatch):
    fake = MagicMock()
    fake.authenticate.return_value = True
    fake.get_libraries.return_value = [{"id": 1}, {"id": 2}]
    fake.last_auth_error = None
    monkeypatch.setattr(diag, "KavitaAPI", lambda url, key: fake)

    result = diag.probe_kavita({
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "secret",
    })
    assert result["status"] == "ok"
    assert result["library_count"] == 2


def test_probe_kavita_auth_fail(monkeypatch):
    fake = MagicMock()
    fake.authenticate.return_value = False
    fake.last_auth_error = "http_401"
    monkeypatch.setattr(diag, "KavitaAPI", lambda url, key: fake)

    result = diag.probe_kavita({
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "bad",
    })
    assert result["status"] == "down"
    assert result["detail"] == "http_401"
    assert result["cause"] == "ban"


# ---------------------------------------------------------------------------
# probe_scraper mocké
# ---------------------------------------------------------------------------

class _MetaOkScraper(BaseScraper):
    id = "TESTMETA"
    display_name = "Test Meta"
    supported_types = {"Manga"}
    rate_limit = 0.0
    proxy_domains = ["example.com"]

    def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
        return {
            "title": "Berserk",
            "summary": "x",
            "cover_url": "https://example.com/c.jpg",
            "year": 1989,
        }

    def fetch_covers(self, query, library_type="Manga"):
        return [{"provider": "Test", "title": "Berserk", "url": "https://example.com/c.jpg"}]


class _KeyScraper(BaseScraper):
    id = "TESTKEY"
    display_name = "Test Key"
    supported_types = {"Manga"}
    needs_api_key = True
    rate_limit = 0.0

    def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "X", "summary": "y", "year": 2000}


def test_probe_scraper_skipped_without_key(monkeypatch):
    monkeypatch.setattr(diag, "_probe_reachability", lambda url, timeout=10.0: {"ok": True, "http_status": 200})
    monkeypatch.setattr(diag, "throttle_provider", lambda s: None)
    result = diag.probe_scraper(_KeyScraper(), config={})
    assert result["status"] == "skipped"
    assert result["cause"] == "auth_missing"


def test_probe_scraper_full_ok(monkeypatch):
    monkeypatch.setattr(
        diag,
        "_probe_reachability",
        lambda url, timeout=10.0, **kwargs: {
            "ok": True,
            "status": "ok",
            "cause": "ok",
            "http_status": 200,
            "latency_ms": 1,
            "detail": "ok",
        },
    )
    monkeypatch.setattr(diag, "throttle_provider", lambda s: None)
    result = diag.probe_scraper(_MetaOkScraper(), config={})
    assert result["status"] == "ok"
    assert result["metadata"]["status"] == "ok"
    assert result["covers"]["status"] == "ok"
    assert result["covers"]["count"] == 1


def test_probe_scraper_reachability_ban(monkeypatch):
    monkeypatch.setattr(
        diag,
        "_probe_reachability",
        lambda url, timeout=10.0, **kwargs: {
            "ok": False,
            "status": "down",
            "cause": "ban",
            "http_status": 429,
            "latency_ms": 5,
            "detail": "ban",
        },
    )
    result = diag.probe_scraper(_MetaOkScraper(), config={})
    assert result["status"] == "down"
    assert result["cause"] == "ban"


def test_probe_scraper_covers_empty_degrades(monkeypatch):
    class CoversBroken(_MetaOkScraper):
        def fetch_covers(self, query, library_type="Manga"):
            return []

    monkeypatch.setattr(
        diag,
        "_probe_reachability",
        lambda url, timeout=10.0, **kwargs: {
            "ok": True,
            "status": "ok",
            "cause": "ok",
            "http_status": 200,
            "latency_ms": 1,
            "detail": "ok",
        },
    )
    monkeypatch.setattr(diag, "throttle_provider", lambda s: None)
    result = diag.probe_scraper(CoversBroken(), config={})
    assert result["status"] == "degraded"
    assert result["cause"] == "covers_schema"


def test_status_from_http_code():
    assert diag._status_from_http_code(429) == "ban"
    assert diag._status_from_http_code(503) == "network"
    assert diag._status_from_http_code(200) is None
    assert diag._status_from_http_code(401, ignore_auth_bans=True) is None
    assert diag._status_from_http_code(403, ignore_auth_bans=True) is None
    assert diag._status_from_http_code(429, ignore_auth_bans=True) is None
    assert diag._status_from_http_code(401, ignore_auth_bans=False) == "ban"
    assert diag._status_from_http_code(403) == "ban"


def test_googlebooks_picks_book_dune_not_comic():
    scraper = SimpleNamespace(
        id="GOOGLEBOOKS",
        supported_types={"Book", "Comic"},
    )
    assert diag._pick_library_type(scraper) == "Book"
    case = diag._resolve_test_case(scraper, "Book")
    assert case["query"] == "elZSm9GK66IC"
    assert case["is_id"] is True
    assert case["context"] == {}


def test_openlibrary_probe_uses_work_id_not_search():
    scraper = SimpleNamespace(
        id="OPENLIBRARY",
        supported_types={"Book", "Comic"},
    )
    assert diag._pick_library_type(scraper) == "Book"
    case = diag._resolve_test_case(scraper, "Book")
    assert case["query"] == "OL10263W"
    assert case["is_id"] is True
    assert case["context"] == {}


def test_hardcover_probe_uses_slug_not_search():
    scraper = SimpleNamespace(
        id="HARDCOVER",
        supported_types={"Book", "Comic"},
    )
    assert diag._pick_library_type(scraper) == "Book"
    case = diag._resolve_test_case(scraper, "Book")
    assert case["query"] == "the-little-prince"
    assert case["is_id"] is True
    assert case["context"] == {}


def test_babelio_probe_uses_petit_prince_not_dune():
    scraper = SimpleNamespace(id="BABELIO", supported_types={"Book"})
    assert diag._pick_library_type(scraper) == "Book"
    case = diag._resolve_test_case(scraper, "Book")
    assert case["query"] == "Le Petit Prince"
    assert case["is_id"] is False


def test_metron_probe_uses_watchmen_not_lanfeust():
    scraper = SimpleNamespace(id="METRON", supported_types={"Comic"})
    assert diag._pick_library_type(scraper) == "Comic"
    case = diag._resolve_test_case(scraper, "Comic")
    assert case["query"] == "Watchmen"
    assert "Lanfeust" not in case["query"]


def test_ann_probe_uses_death_note():
    scraper = SimpleNamespace(id="ANN", supported_types={"Manga"})
    case = diag._resolve_test_case(scraper, "Manga")
    assert case["query"] == "Death Note"


def test_planetebd_probe_uses_asterix():
    scraper = SimpleNamespace(id="PLANETEBD", supported_types={"Comic"})
    case = diag._resolve_test_case(scraper, "Comic")
    assert case["query"] == "Astérix"


def test_probe_urls_cover_new_core_scrapers():
    for sid in ("BABELIO", "DECITRE", "SENSCRITIQUE", "ANN", "LOCG", "PLANETEBD", "METRON"):
        assert sid in diag.PROBE_URLS
        assert diag.PROBE_URLS[sid].startswith("https://")


def test_get_active_scraper_ids_dedupes_and_filters(monkeypatch):
    monkeypatch.setattr(
        diag.ScraperRegistry,
        "get",
        lambda sid, include_disabled=False: (
            SimpleNamespace(id=sid) if sid in {"ANILIST", "BEDETHEQUE", "BABELIO"} else None
        ),
    )
    ids = diag.get_active_scraper_ids({
        "PROVIDER_1": "ANILIST",
        "PROVIDER_2": "ANILIST",
        "PROVIDER_3": "NONE",
        "COMIC_PROVIDER_1": "BEDETHEQUE",
        "COMIC_PROVIDER_2": "",
        "COMIC_PROVIDER_3": "GHOST_PROVIDER",
        "BOOK_PROVIDER_1": "babelio",
        "BOOK_PROVIDER_2": "NONE",
        "BOOK_PROVIDER_3": "NONE",
    })
    assert ids == ["ANILIST", "BEDETHEQUE", "BABELIO"]


def test_resolve_probe_targets_active_scope(monkeypatch):
    a = SimpleNamespace(id="ANILIST")
    b = SimpleNamespace(id="BABELIO")
    monkeypatch.setattr(diag, "get_active_scraper_ids", lambda config=None: ["ANILIST", "BABELIO"])
    monkeypatch.setattr(
        diag.ScraperRegistry,
        "get",
        lambda sid, include_disabled=False: {"ANILIST": a, "BABELIO": b}.get(sid),
    )
    monkeypatch.setattr(
        diag.ScraperRegistry,
        "get_all",
        lambda include_disabled=False, scope=None: [a, b, SimpleNamespace(id="KITSU")],
    )
    active = diag.resolve_probe_targets({}, scope="active")
    assert [s.id for s in active] == ["ANILIST", "BABELIO"]
    all_targets = diag.resolve_probe_targets({}, scope="all")
    assert len(all_targets) == 3


def test_list_inventory_marks_active(monkeypatch):
    scrapers = [
        SimpleNamespace(
            id="ANILIST",
            localized_display_name="AniList",
            supported_types={"Manga"},
            needs_api_key=False,
            rate_limit=1.0,
        ),
        SimpleNamespace(
            id="KITSU",
            localized_display_name="Kitsu",
            supported_types={"Manga"},
            needs_api_key=False,
            rate_limit=1.0,
        ),
    ]
    monkeypatch.setattr(
        diag.ScraperRegistry,
        "get_all",
        lambda include_disabled=False, scope=None: scrapers,
    )
    monkeypatch.setattr(
        diag.ScraperRegistry,
        "get",
        lambda sid, include_disabled=False: next((s for s in scrapers if s.id == sid), None),
    )
    monkeypatch.setattr(diag, "get_active_scraper_ids", lambda config=None: ["ANILIST"])
    monkeypatch.setattr(diag, "_has_api_key", lambda scraper, config: True)
    monkeypatch.setattr(diag, "_supports_covers", lambda scraper: True)
    rows = diag.list_scrapers_inventory({})
    by_id = {r["id"]: r for r in rows}
    assert by_id["ANILIST"]["active"] is True
    assert by_id["KITSU"]["active"] is False


def test_probe_scraper_hardcover_is_id_uses_meta_cover(monkeypatch):
    calls = []

    class HC(BaseScraper):
        id = "HARDCOVER"
        display_name = "Hardcover"
        supported_types = {"Book", "Comic"}
        needs_api_key = True
        rate_limit = 0.0

        def fetch(self, query, library_type="Book", is_id=False, existing_metadata=None):
            calls.append(("fetch", query, library_type, existing_metadata, is_id))
            return {
                "title": "The Little Prince",
                "summary": "Conte " + ("x" * 40),
                "cover_url": "https://img.hardcover.app/cover.jpg",
                "year": 1943,
                "genres": ["Fiction"],
                "staff": [],
            }

        def fetch_covers(self, query, library_type="Book"):
            calls.append(("covers", query, library_type))
            raise AssertionError("fetch_covers ne doit pas être appelé pour le probe is_id")

    monkeypatch.setattr(diag, "throttle_provider", lambda s: None)
    monkeypatch.setattr(
        diag,
        "_probe_reachability",
        lambda *a, **k: {"ok": True, "cause": "ok", "http_status": 200, "latency_ms": 1, "detail": "ok"},
    )
    result = diag.probe_scraper(HC(), config={"HARDCOVER_API_KEY": "k"})
    assert result["status"] == "ok"
    assert calls == [("fetch", "the-little-prince", "Book", {}, True)]
    assert result["covers"]["status"] == "ok"
    assert result["covers"]["sample_url"] == "https://img.hardcover.app/cover.jpg"


def test_probe_scraper_openlibrary_is_id_uses_meta_cover(monkeypatch):
    calls = []

    class OL(BaseScraper):
        id = "OPENLIBRARY"
        display_name = "Open Library"
        supported_types = {"Book", "Comic"}
        needs_api_key = False
        rate_limit = 0.0

        def fetch(self, query, library_type="Book", is_id=False, existing_metadata=None):
            calls.append(("fetch", query, library_type, existing_metadata, is_id))
            return {
                "title": "Le petit prince",
                "summary": "Conte " + ("x" * 40),
                "cover_url": "https://covers.openlibrary.org/b/id/2137711-L.jpg",
                "year": 1943,
                "genres": ["Fiction"],
                "staff": [],
            }

        def fetch_covers(self, query, library_type="Book"):
            calls.append(("covers", query, library_type))
            raise AssertionError("fetch_covers ne doit pas être appelé pour le probe is_id")

    monkeypatch.setattr(diag, "throttle_provider", lambda s: None)
    monkeypatch.setattr(
        diag,
        "_probe_reachability",
        lambda *a, **k: {"ok": True, "cause": "ok", "http_status": 200, "latency_ms": 1, "detail": "ok"},
    )
    result = diag.probe_scraper(OL(), config={})
    assert result["status"] == "ok"
    assert calls == [("fetch", "OL10263W", "Book", {}, True)]
    assert result["covers"]["status"] == "ok"
    assert "2137711" in (result["covers"]["sample_url"] or "")


def test_googlebooks_author_context_would_kill_score():
    """Regression : search+authors peut tuer le score — d'où le probe is_id."""
    from scrapers.utils import score_candidate

    cand = {
        "title": "Le Petit Prince",
        "alternative_titles": [],
        "staff": [{"role": "Story", "node": {"name": {"full": "Kentaro Miura"}}}],
        "year": 1943,
    }
    bad = score_candidate(cand, "Le Petit Prince", {"authors": ["Antoine de Saint-Exupéry"]})
    good = score_candidate(cand, "Le Petit Prince", {})
    assert bad < 0.6, bad
    assert good >= 0.6, good


def test_googlebooks_reachability_uses_api_key(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        content = b'{"id":"x","volumeInfo":{"title":"Le petit prince"}}'
        def json(self):
            return {"id": "x", "volumeInfo": {"title": "Le petit prince"}}
        def close(self):
            pass

    def fake_get(url, params=None, headers=None, timeout=10):
        captured["url"] = url
        captured["params"] = params or {}
        return FakeResp()

    monkeypatch.setattr(diag.requests, "get", fake_get)
    reach = diag._googlebooks_smoke({"GOOGLEBOOKS_API_KEY": "secret-key"})
    assert reach["ok"] is True
    assert captured["url"].endswith("/volumes/elZSm9GK66IC")
    assert captured["params"].get("key") == "secret-key"
    assert captured["params"].get("country") == "US"


def test_googlebooks_reachability_403_with_key_is_ban(monkeypatch):
    class Fake403:
        status_code = 403
        content = b'{"error":{"message":"forbidden"}}'
        def json(self):
            return {"error": {"message": "forbidden"}}
        def close(self):
            pass

    monkeypatch.setattr(diag.requests, "get", lambda *a, **k: Fake403())
    reach = diag._googlebooks_smoke({"GOOGLEBOOKS_API_KEY": "bad"})
    assert reach["ok"] is False
    assert reach["cause"] == "ban"


def test_probe_scraper_googlebooks_continues_after_smoke_5xx(monkeypatch):
    """Un 5xx smoke ne doit pas short-circuiter : fetch is_id reste la vérité."""
    calls = []

    class GB(BaseScraper):
        id = "GOOGLEBOOKS"
        display_name = "Google Books"
        supported_types = {"Book", "Comic"}
        needs_api_key = True
        rate_limit = 0.0

        def fetch(self, query, library_type="Book", is_id=False, existing_metadata=None):
            calls.append(("fetch", query, library_type, is_id))
            return {
                "title": "Le petit prince",
                "summary": "Conte " + ("x" * 40),
                "cover_url": "https://example.com/prince.jpg",
                "year": 2001,
                "staff": [{"role": "Story", "node": {"name": {"full": "Antoine de Saint-Exupéry"}}}],
            }

        def fetch_covers(self, query, library_type="Book"):
            calls.append(("covers", query, library_type))
            return []

    monkeypatch.setattr(
        diag,
        "_googlebooks_smoke",
        lambda config, timeout=12.0: {
            "ok": False,
            "cause": "network",
            "http_status": 503,
            "latency_ms": 50,
            "detail": "http_5xx",
        },
    )
    monkeypatch.setattr(diag, "throttle_provider", lambda s: None)
    result = diag.probe_scraper(GB(), config={"GOOGLEBOOKS_API_KEY": "k"})
    assert result["status"] == "ok"
    assert [c[0] for c in calls] == ["fetch"]  # covers from meta.cover_url, pas fetch_covers
    assert calls[0][1] == "elZSm9GK66IC"
    assert calls[0][3] is True
    assert result["covers"]["status"] == "ok"
    assert result["covers"]["count"] == 1


def test_probe_reachability_ignores_403_for_api_key_scrapers(monkeypatch):
    class Fake403:
        status_code = 403
        def close(self):
            pass

    monkeypatch.setattr(diag.requests, "get", lambda *a, **k: Fake403())
    reach = diag._probe_reachability(
        "https://www.googleapis.com/books/v1/volumes",
        needs_api_key=True,
    )
    assert reach["ok"] is True
    assert reach["http_status"] == 403


def test_probe_reachability_403_is_ban_without_api_key(monkeypatch):
    class Fake403:
        status_code = 403
        def close(self):
            pass

    monkeypatch.setattr(diag.requests, "get", lambda *a, **k: Fake403())
    reach = diag._probe_reachability("https://example.com/", needs_api_key=False)
    assert reach["ok"] is False
    assert reach["cause"] == "ban"


def test_probe_scraper_googlebooks_uses_book_case(monkeypatch):
    """Probe GB = volumes.get (is_id) + cover depuis meta.cover_url."""
    calls = []

    class GB(BaseScraper):
        id = "GOOGLEBOOKS"
        display_name = "Google Books"
        supported_types = {"Book", "Comic"}
        needs_api_key = True
        rate_limit = 0.0

        def fetch(self, query, library_type="Book", is_id=False, existing_metadata=None):
            calls.append(("fetch", query, library_type, existing_metadata, is_id))
            return {
                "title": "Le petit prince",
                "summary": "Conte " + ("x" * 40),
                "cover_url": "https://example.com/prince.jpg",
                "year": 2001,
                "staff": [{"role": "Story", "node": {"name": {"full": "Antoine de Saint-Exupéry"}}}],
            }

        def fetch_covers(self, query, library_type="Book"):
            calls.append(("covers", query, library_type))
            raise AssertionError("fetch_covers ne doit pas être appelé pour le probe is_id")

    monkeypatch.setattr(
        diag,
        "_googlebooks_smoke",
        lambda config, timeout=12.0: {
            "ok": True,
            "cause": "ok",
            "http_status": 200,
            "latency_ms": 1,
            "detail": "ok",
        },
    )
    monkeypatch.setattr(diag, "throttle_provider", lambda s: None)
    result = diag.probe_scraper(GB(), config={"GOOGLEBOOKS_API_KEY": "k"})
    assert result["status"] == "ok"
    assert result["library_type"] == "Book"
    assert calls == [("fetch", "elZSm9GK66IC", "Book", {}, True)]
    assert result["covers"]["status"] == "ok"
    assert result["covers"]["sample_url"] == "https://example.com/prince.jpg"
    assert result["metadata"]["sample_title"] == "Le petit prince"


# ---------------------------------------------------------------------------
# Routes (app Flask minimale, pas d'import app.py)
# ---------------------------------------------------------------------------

_LOGIN_ALLOWED = frozenset({
    "auth.login",
    "static",
    "misc.healthz",
    "sync.webhook",
})


@pytest.fixture
def diag_client(monkeypatch):
    """Client avec pages + diagnostics blueprints et login_gate fail-closed."""
    import os

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    test_app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
        root_path=root,
    )
    test_app.config.update(TESTING=True, SECRET_KEY="test-secret")

    test_app.register_blueprint(diagnostics_bp)
    test_app.register_blueprint(pages_bp)

    @test_app.route("/login", endpoint="auth.login")
    def login():
        return "login", 200

    @test_app.before_request
    def login_gate():
        if request.endpoint in _LOGIN_ALLOWED:
            return None
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return None

    @test_app.context_processor
    def inject():
        return {"csrf_token": "test-csrf", "is_authenticated": True, "app_version": "test"}

    monkeypatch.setattr(
        "routes.diagnostics.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://k", "KAVITA_API_KEY": "k"},
    )
    monkeypatch.setattr(
        "routes.pages.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://k", "KAVITA_API_KEY": "k"},
    )
    monkeypatch.setattr(
        "routes.pages.list_scrapers_inventory",
        lambda config=None: [{
            "id": "ANILIST",
            "display_name": "AniList",
            "supported_types": ["Manga"],
            "needs_api_key": False,
            "has_api_key": True,
            "supports_covers": True,
            "rate_limit": 1.0,
            "active": True,
        }],
    )
    monkeypatch.setattr("routes.pages.get_current_version", lambda: "9.9.9")

    client = test_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    return client


def test_preflight_route_requires_auth():
    test_app = Flask(__name__)
    test_app.config.update(TESTING=True, SECRET_KEY="x")
    test_app.register_blueprint(diagnostics_bp)

    @test_app.route("/login", endpoint="auth.login")
    def login():
        return "login", 200

    @test_app.before_request
    def login_gate():
        if request.endpoint in _LOGIN_ALLOWED:
            return None
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return None

    client = test_app.test_client()
    res = client.post("/api/diagnostics/preflight")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_preflight_route_ok(diag_client, monkeypatch):
    monkeypatch.setattr(
        "routes.diagnostics.run_preflight",
        lambda config=None: {
            "internet": {"status": "ok", "cause": "ok", "latency_ms": 12, "detail": "ok"},
            "kavita": {
                "status": "ok",
                "cause": "ok",
                "latency_ms": 40,
                "detail": "ok",
                "library_count": 3,
            },
        },
    )
    res = diag_client.post("/api/diagnostics/preflight")
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["internet"]["status"] == "ok"
    assert body["kavita"]["library_count"] == 3


def test_probe_one_unknown_404(diag_client, monkeypatch):
    monkeypatch.setattr(
        "routes.diagnostics.ScraperRegistry.get",
        lambda sid, include_disabled=False: None,
    )
    res = diag_client.post("/api/scrapers/NOPE/probe")
    assert res.status_code == 404


def test_probe_one_ok(diag_client, monkeypatch):
    monkeypatch.setattr(
        "routes.diagnostics.ScraperRegistry.get",
        lambda sid, include_disabled=False: SimpleNamespace(id=sid),
    )
    monkeypatch.setattr(
        "routes.diagnostics.probe_scraper",
        lambda sid, config=None: {
            "id": sid,
            "status": "ok",
            "cause": "ok",
            "metadata": {"status": "ok"},
            "covers": {"status": "ok", "count": 2},
        },
    )
    res = diag_client.post("/api/scrapers/ANILIST/probe")
    assert res.status_code == 200
    assert res.get_json()["result"]["status"] == "ok"


def test_probe_all_bulk_json(diag_client, monkeypatch):
    monkeypatch.setattr(
        "routes.diagnostics.probe_all",
        lambda config=None, scope="all": [{"id": "ANILIST", "status": "ok"}],
    )
    res = diag_client.post(
        "/api/scrapers/probe-all",
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["scope"] == "all"
    assert body["results"][0]["id"] == "ANILIST"


def test_probe_all_bulk_json_scope_active(diag_client, monkeypatch):
    seen = {}

    def _fake_probe_all(config=None, scope="all"):
        seen["scope"] = scope
        return [{"id": "ANILIST", "status": "ok"}]

    monkeypatch.setattr("routes.diagnostics.probe_all", _fake_probe_all)
    res = diag_client.post(
        "/api/scrapers/probe-all?scope=active",
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["scope"] == "active"
    assert seen["scope"] == "active"


def test_probe_all_ndjson_stream(diag_client, monkeypatch):
    scraper = SimpleNamespace(id="ANILIST", display_name="AniList")
    monkeypatch.setattr(
        "routes.diagnostics.resolve_probe_targets",
        lambda config=None, scope="all": [scraper],
    )
    monkeypatch.setattr(
        "routes.diagnostics.probe_scraper",
        lambda s, config=None: {
            "id": "ANILIST",
            "status": "ok",
            "cause": "ok",
            "metadata": {"status": "ok"},
            "covers": {"status": "ok", "count": 1},
        },
    )
    res = diag_client.post(
        "/api/scrapers/probe-all?stream=1",
        headers={"Accept": "application/x-ndjson"},
    )
    assert res.status_code == 200
    assert "ndjson" in (res.mimetype or "")
    lines = [ln for ln in res.get_data(as_text=True).splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert events[0].get("scope") == "all"
    assert "start_scraper" in types
    assert "result" in types
    assert types[-1] == "done"
    result_evt = next(e for e in events if e["type"] == "result")
    assert result_evt["result"]["status"] == "ok"


def test_probe_all_ndjson_stream_scope_active(diag_client, monkeypatch):
    scraper = SimpleNamespace(id="ANILIST", display_name="AniList")
    seen = {}

    def _targets(config=None, scope="all"):
        seen["scope"] = scope
        return [scraper] if scope == "active" else [scraper, SimpleNamespace(id="KITSU", display_name="Kitsu")]

    monkeypatch.setattr("routes.diagnostics.resolve_probe_targets", _targets)
    monkeypatch.setattr(
        "routes.diagnostics.probe_scraper",
        lambda s, config=None: {
            "id": getattr(s, "id", "X"),
            "status": "ok",
            "cause": "ok",
            "metadata": {"status": "ok"},
            "covers": {"status": "ok", "count": 1},
        },
    )
    res = diag_client.post(
        "/api/scrapers/probe-all?stream=1&scope=active",
        headers={"Accept": "application/x-ndjson"},
    )
    assert res.status_code == 200
    events = [json.loads(ln) for ln in res.get_data(as_text=True).splitlines() if ln.strip()]
    assert seen["scope"] == "active"
    assert events[0]["total"] == 1
    assert events[0]["scope"] == "active"
    result_ids = [e["result"]["id"] for e in events if e["type"] == "result"]
    assert result_ids == ["ANILIST"]


def test_diagnostics_page_renders(diag_client):
    res = diag_client.get("/diagnostics")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "AniList" in html
    assert "cardInternet" in html
    assert "cardKavita" in html
    assert "btnProbeActive" in html
    assert 'data-active="1"' in html