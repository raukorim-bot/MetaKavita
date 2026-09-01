"""
C33 Companion — webhook seriesId-only, flags auto/super_review, enrich overrides.
"""
from __future__ import annotations

import queue

import pytest
from flask import Flask

from routes.sync import sync_bp
from services import background_tasks as bg
from services import enrichment_engine


@pytest.fixture
def webhook_app(monkeypatch):
    monkeypatch.setattr(
        "routes.sync.load_config",
        lambda: {
            "WEBHOOK_TOKEN": "s3cret-token",
            "UI_LANG": "fr",
            "KAVITA_URL": "http://kavita.local",
            "KAVITA_API_KEY": "k",
        },
    )
    # File isolée pour ne pas polluer le worker global des autres tests.
    q = queue.Queue()
    monkeypatch.setattr(bg, "sync_queue", q)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(sync_bp)
    return app, q


@pytest.fixture
def client(webhook_app):
    app, _q = webhook_app
    return app.test_client()


def _auth_headers():
    return {"X-Webhook-Token": "s3cret-token"}


class _FakeKavitaBase:
    """Minimal KavitaAPI stub with fetch_series (C33 webhook resolve)."""

    def __init__(self, *a, **k):
        pass

    def get_series(self, series_id):
        return None

    def fetch_series(self, series_id, timeout=15):
        data = self.get_series(series_id)
        if data is None:
            return None, "series_not_found"
        return data, None


def test_make_sync_item_defaults_compat():
    item = bg.make_sync_item(1, "Title", True)
    assert item["super_review"] is False
    assert item["force_auto"] is False
    assert item["manual_review_override"] is False
    assert item["is_batch"] is False
    assert item["origin"] == "row"


def test_make_sync_item_batch_defaults_to_batch_origin():
    item = bg.make_sync_item(1, "Title", False, is_batch=True)
    assert item["origin"] == "batch"


def test_webhook_empty_body_good_token_returns_400(client):
    res = client.post("/webhook", headers=_auth_headers(), json={})
    assert res.status_code == 400


def test_webhook_probe_ok_no_queue(client, webhook_app):
    _app, q = webhook_app
    res = client.post("/webhook", headers=_auth_headers(), json={"probe": True})
    assert res.status_code == 200
    assert res.get_json()["probe"] is True
    assert q.empty()


def test_webhook_bad_token_401(client):
    res = client.post("/webhook", headers={"X-Webhook-Token": "wrong"}, json={"seriesId": 1})
    assert res.status_code == 401


def test_webhook_series_id_only_resolves_name(client, webhook_app, monkeypatch):
    _app, q = webhook_app

    class FakeKavita(_FakeKavitaBase):
        def get_series(self, series_id):
            assert int(series_id) == 42
            return {"name": "Resolved Title"}

    monkeypatch.setattr("routes.sync.KavitaAPI", FakeKavita)
    res = client.post(
        "/webhook",
        headers=_auth_headers(),
        json={"seriesId": 42, "force": True, "auto": True},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["series_id"] == 42
    assert body["series_name"] == "Resolved Title"
    assert body["force_auto"] is True
    assert body["super_review"] is False
    assert body["force_update"] is True
    item = q.get_nowait()
    assert item["series_name"] == "Resolved Title"
    assert item["force_auto"] is True
    assert item["super_review"] is False
    assert item["origin"] == "webhook"


def test_webhook_series_id_unknown_returns_404(client, webhook_app, monkeypatch):
    _app, q = webhook_app

    class FakeKavita(_FakeKavitaBase):
        pass

    monkeypatch.setattr("routes.sync.KavitaAPI", FakeKavita)
    res = client.post(
        "/webhook",
        headers=_auth_headers(),
        json={"seriesId": 999},
    )
    assert res.status_code == 404
    assert res.get_json()["code"] == "series_not_found"
    assert q.empty()


def test_webhook_kavita_unreachable_returns_503(client, webhook_app, monkeypatch):
    _app, q = webhook_app

    class FakeKavita(_FakeKavitaBase):
        def fetch_series(self, series_id, timeout=15):
            return None, "kavita_unreachable"

    monkeypatch.setattr("routes.sync.KavitaAPI", FakeKavita)
    res = client.post(
        "/webhook",
        headers=_auth_headers(),
        json={"seriesId": 1, "auto": True},
    )
    assert res.status_code == 503
    assert res.get_json()["code"] == "kavita_unreachable"
    assert q.empty()


def test_webhook_auto_implies_force_update(client, webhook_app):
    _app, q = webhook_app
    res = client.post(
        "/webhook",
        headers=_auth_headers(),
        json={"seriesId": 1, "name": "A", "auto": True},
    )
    assert res.status_code == 200
    item = q.get_nowait()
    assert item["force_update"] is True
    assert item["force_auto"] is True


def test_webhook_legacy_name_still_works(client, webhook_app, monkeypatch):
    _app, q = webhook_app
    called = {"n": 0}

    class FakeKavita(_FakeKavitaBase):
        def get_series(self, series_id):
            called["n"] += 1
            return {"name": "ShouldNotUse"}

    monkeypatch.setattr("routes.sync.KavitaAPI", FakeKavita)
    res = client.post(
        "/webhook",
        headers=_auth_headers(),
        json={"seriesId": 7, "name": "Legacy Name", "force": True},
    )
    assert res.status_code == 200
    assert called["n"] == 0
    item = q.get_nowait()
    assert item["series_name"] == "Legacy Name"


def test_webhook_auto_flag_on_queue_item(client, webhook_app):
    _app, q = webhook_app
    res = client.post(
        "/webhook",
        headers=_auth_headers(),
        json={"seriesId": 1, "name": "A", "auto": True, "force": True},
    )
    assert res.status_code == 200
    item = q.get_nowait()
    assert item["force_auto"] is True
    assert item["super_review"] is False


def test_webhook_super_review_flag_on_queue_item(client, webhook_app):
    _app, q = webhook_app
    res = client.post(
        "/webhook",
        headers=_auth_headers(),
        json={"seriesId": 1, "name": "A", "super_review": True, "force": True},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["super_review"] is True
    assert body["force_auto"] is False
    item = q.get_nowait()
    assert item["super_review"] is True
    assert item["force_auto"] is False


def test_webhook_super_wins_over_auto(client, webhook_app):
    _app, q = webhook_app
    res = client.post(
        "/webhook",
        headers=_auth_headers(),
        json={
            "seriesId": 1,
            "name": "A",
            "auto": True,
            "super_review": True,
            "force": True,
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["super_review"] is True
    assert body["force_auto"] is False
    item = q.get_nowait()
    assert item["super_review"] is True
    assert item["force_auto"] is False


def _enrich_base_config(**overrides):
    cfg = {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "fake",
        "UI_LANG": "fr",
        "TARGET_LANG": "FR",
        "MAX_GENRES": 5,
        "MAX_TAGS": 15,
        "PROVIDER_1": "MANGA_FAKE",
        "PROVIDER_2": "NONE",
        "PROVIDER_3": "NONE",
        "COMIC_PROVIDER_1": "NONE",
        "COMIC_PROVIDER_2": "NONE",
        "COMIC_PROVIDER_3": "NONE",
        "SMART_COMPLETION": False,
        "SMART_SCORING": False,
        "AUTO_READING_DIR": False,
        "AUTO_COVER": False,
        "RESET_CONTEXT_ON_FORCE": False,
        "TRANSLATION_PROVIDER": "NONE",
        "DEEPL_API_KEY": "",
        "LOCALIZED_TITLE_MODE": "all",
        "LOCALIZED_TITLE_LANGS": "",
        "PUBLISHER_PREFERENCE": "LOCALIZED",
        "MANUAL_REVIEW_MODE": False,
        "MANUAL_REVIEW_SUPER": False,
        "CONFIRM_BEFORE_WRITE": False,
    }
    cfg.update(overrides)
    return cfg


def test_enrich_force_auto_bypasses_manual_review_mode(mocker, isolated_db):
    from kavita_api import KavitaAPI
    from scrapers.base import BaseScraper

    class _MangaFake(BaseScraper):
        id = "MANGA_FAKE"
        display_name = "Manga Fake"
        supported_types = {"Manga"}
        has_direct_id_support = False

        def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
            return None

        def extract_id_from_url(self, url):
            return None

    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value=_enrich_base_config(MANUAL_REVIEW_MODE=True, MANUAL_REVIEW_SUPER=False),
    )
    mocker.patch.object(enrichment_engine, "get_all_cached_data", side_effect=isolated_db.get_all_cached_data)
    mocker.patch.object(enrichment_engine, "update_status")
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI,
        "get_series_metadata",
        return_value={"summary": "", "genres": [], "tags": [], "webLinks": "", "language": ""},
    )
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="Manga")
    mocker.patch.object(
        KavitaAPI,
        "get_series_deep_metadata",
        return_value={
            "isbn": None,
            "authors": [],
            "publisher": None,
            "year": None,
            "genres": [],
            "localized_name": None,
        },
    )
    mocker.patch.object(KavitaAPI, "get_cached_library_id", return_value=1)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", side_effect=lambda pid: _MangaFake() if pid == "MANGA_FAKE" else None)

    provider_data = {
        "title": "Auto Series",
        "summary": "Hello",
        "genres": [],
        "tags": [],
        "staff": [],
        "_match_score": 0.95,
        "_provider": "MANGA_FAKE",
    }
    mocker.patch(
        "metadata_fetcher.fetch_metadata",
        return_value=(provider_data, ["MANGA_FAKE"]),
    )
    created = {"n": 0}
    mocker.patch(
        "services.manual_review.create_review_from_candidates",
        side_effect=lambda *a, **k: created.__setitem__("n", created["n"] + 1),
    )
    mocker.patch(
        "services.enrichment_engine.apply_kavita_payload",
        return_value=(True, "Succès", ["MANGA_FAKE"]),
    )
    mocker.patch(
        "services.enrichment_engine.build_kavita_payload",
        return_value={"preview_fields": {}, "meta": {}, "general": {}},
    )

    ok, msg, _used = enrichment_engine.enrich_series(
        501, "Auto Series", force_update=True, force_auto=True
    )
    assert ok is True
    assert msg != "PENDING_REVIEW"
    assert created["n"] == 0


def test_enrich_super_review_override_parks_without_global_super(mocker, isolated_db):
    from kavita_api import KavitaAPI
    from scrapers.base import BaseScraper

    class _MangaFake(BaseScraper):
        id = "MANGA_FAKE"
        display_name = "Manga Fake"
        supported_types = {"Manga"}
        has_direct_id_support = False

        def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
            return None

        def extract_id_from_url(self, url):
            return None

    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value=_enrich_base_config(
            MANUAL_REVIEW_MODE=False,
            MANUAL_REVIEW_SUPER=False,
        ),
    )
    mocker.patch.object(enrichment_engine, "get_all_cached_data", side_effect=isolated_db.get_all_cached_data)
    mocker.patch.object(enrichment_engine, "update_status")
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI,
        "get_series_metadata",
        return_value={"summary": "", "genres": [], "tags": [], "webLinks": "", "language": ""},
    )
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="Manga")
    mocker.patch.object(
        KavitaAPI,
        "get_series_deep_metadata",
        return_value={
            "isbn": None,
            "authors": [],
            "publisher": None,
            "year": None,
            "genres": [],
            "localized_name": None,
        },
    )
    mocker.patch.object(KavitaAPI, "get_cached_library_id", return_value=1)

    fake = _MangaFake()
    mocker.patch.object(
        enrichment_engine.ScraperRegistry,
        "get",
        side_effect=lambda pid: fake if pid == "MANGA_FAKE" else None,
    )
    mocker.patch.object(
        enrichment_engine.ScraperRegistry,
        "get_by_type",
        return_value=[fake],
    )
    mocker.patch.object(
        enrichment_engine.ScraperRegistry,
        "get_all",
        return_value=[fake],
    )

    card = {
        "provider": "MANGA_FAKE",
        "title": "Super Series",
        "summary": "Hello",
        "genres": [],
        "tags": [],
        "staff": [],
        "_match_score": 0.9,
    }
    mocker.patch(
        "metadata_fetcher.fetch_metadata",
        return_value=({"above": [card], "below": [], "query": "Super Series"}, ["MANGA_FAKE"]),
    )
    parked = {}
    mocker.patch(
        "services.manual_review.begin_streaming_review",
        side_effect=lambda sid, name, **kwargs: parked.update(series_id=sid, begun=True)
        or "rid-1",
    )
    mocker.patch(
        "services.manual_review.append_streaming_candidate",
        return_value=None,
    )
    mocker.patch(
        "services.manual_review.finalize_streaming_review",
        side_effect=lambda rid, sid, name, payload, **kwargs: parked.update(
            series_id=sid, payload=payload, finalized=True
        )
        or rid,
    )

    ok, msg, _used = enrichment_engine.enrich_series(
        502,
        "Super Series",
        force_update=True,
        super_review_override=True,
    )
    assert ok is True
    assert msg == "PENDING_REVIEW"
    assert parked.get("series_id") == 502
    assert parked.get("begun") is True
    assert parked.get("finalized") is True
