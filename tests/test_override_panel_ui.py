"""
UI Options / overrides — contrat template + JS + persistance + usage enrichissement.

Couvre notamment :
- titre alternatif
- champ magique (ID / URL)
- force provider (select ≠ AUTO)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from flask import Flask

from models import SeriesOverride

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture
def pages_client(isolated_db):
    from routes.auth import auth_bp
    from routes.config import config_bp
    from routes.manual_review import manual_review_bp
    from routes.misc import misc_bp
    from routes.pages import pages_bp
    from routes.scrapers_manage import scrapers_manage_bp
    from routes.series import series_bp
    from routes.sync import sync_bp

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    for bp in (
        auth_bp,
        pages_bp,
        config_bp,
        series_bp,
        sync_bp,
        misc_bp,
        manual_review_bp,
        scrapers_manage_bp,
    ):
        app.register_blueprint(bp)
    return app.test_client()


def _fake_kavita(series):
    class FakeKavita:
        def __init__(self, *a, **k):
            pass

        def authenticate(self):
            return True

        def get_libraries(self):
            return [{"id": 1, "name": "Manga"}]

        def get_all_series(self, library_id=None):
            return series

    return FakeKavita


# --- Template / row contracts -------------------------------------------------


def test_override_panel_template_has_magic_alt_title_provider_fields():
    html = _read("templates/partials/_override_panel_template.html")
    assert 'id="override-panel-template"' in html
    assert 'id="title-__SID__"' in html
    assert 'id="id-__SID__"' in html
    assert 'id="provider-__SID__"' in html
    assert 'option value="AUTO"' in html
    assert "magic_scrapers" in html
    assert 'data-save-override="1"' in html
    assert 'id="alt-langs-__SID__"' in html
    # Compact layout classes (BF100)
    assert "override-main" in html
    assert "override-field--magic" in html


def test_override_panel_sid_rewrite_produces_stable_ids():
    html = _read("templates/partials/_override_panel_template.html")
    # Mimic overrides.js:: _buildOverridePanelFromTemplate SID rewrite
    built = html.replace("__SID__", "42")
    assert 'id="title-42"' in built
    assert 'id="id-42"' in built
    assert 'id="provider-42"' in built
    assert 'name="pubpref-42"' in built
    assert 'id="field-summary-42"' in built
    panel = re.search(
        r'<div id="panel-42" class="override-panel">[\s\S]*?</template>',
        built,
    )
    assert panel, "panel block missing after SID rewrite"
    assert "__SID__" not in panel.group(0)


def test_series_row_exposes_override_data_attributes():
    html = _read("templates/partials/_series_row.html")
    for attr in (
        "data-forced-id=",
        "data-alt-title=",
        "data-forced-provider=",
        "data-targeted-fields=",
        "data-publisher-pref=",
        "data-alt-langs=",
    ):
        assert attr in html


# --- JS wiring ----------------------------------------------------------------


def test_overrides_js_fills_and_saves_magic_alt_title_provider():
    js = _read("static/js/overrides.js")

    assert "function _fillOverridePanelFields" in js
    assert "ds.altTitle" in js
    assert "ds.forcedId" in js
    assert "ds.forcedProvider" in js
    assert "titleEl.value = ds.altTitle" in js or "ds.altTitle || ds.seriesName" in js
    assert "idEl.value = ds.forcedId" in js
    assert "prov.value = ds.forcedProvider" in js

    assert "function saveOverride" in js
    save_start = js.index("function saveOverride")
    save_body = js[save_start: save_start + 2500]
    assert "alternative_title=" in save_body
    assert "forced_provider=" in save_body
    assert "forced_id=" in save_body
    assert "/save-override" in save_body
    assert "encodeURIComponent(altTitle)" in save_body
    assert "encodeURIComponent(forcedProvider)" in save_body
    assert "encodeURIComponent(forcedId)" in save_body
    # Dataset sync after save (virtual list / re-open)
    assert "item.dataset.forcedId = forcedId" in save_body
    assert "item.dataset.altTitle = altTitle" in save_body
    assert "item.dataset.forcedProvider = forcedProvider" in save_body


def test_series_list_js_emits_override_data_attrs_for_virtual_rows():
    js = _read("static/js/series_list.js")
    assert 'data-forced-id="' in js
    assert "data-alt-title=" in js or "data-alt-title=\"" in js
    assert "data-forced-provider=" in js
    assert "forced_provider" in js
    assert "alternative_title" in js


# --- HTTP persistence ---------------------------------------------------------


def test_save_override_magic_url_alt_title_and_forced_provider(client, isolated_db):
    magic = "https://myanimelist.net/manga/2/Berserk"
    res = client.post(
        "/save-override",
        data={
            "series_id": "77",
            "forced_id": magic,
            "alternative_title": "Berserk VF",
            "forced_provider": "MAL",
            "targeted_fields": "summary,cover,staff",
            "publisher_pref": "LOCALIZED",
            "alt_title_langs": "en,fr",
        },
    )
    assert res.status_code == 200
    assert res.data == b"OK"

    cached = isolated_db.get_all_cached_data()[77]
    assert cached["forced_id"] == magic
    assert cached["alternative_title"] == "Berserk VF"
    assert cached["forced_provider"] == "MAL"
    assert cached["targeted_fields"] == "summary,cover,staff"
    assert cached["publisher_pref"] == "LOCALIZED"
    assert cached["alt_title_langs"] == "en,fr"
    assert cached["status"] == "PENDING"


def test_save_override_numeric_magic_id_with_anilist(client, isolated_db):
    res = client.post(
        "/save-override",
        data={
            "series_id": "12",
            "forced_id": "30013",
            "alternative_title": "Le Collège Fou Fou Fou",
            "forced_provider": "ANILIST",
        },
    )
    assert res.status_code == 200
    cached = isolated_db.get_all_cached_data()[12]
    assert cached["forced_id"] == "30013"
    assert cached["alternative_title"] == "Le Collège Fou Fou Fou"
    assert cached["forced_provider"] == "ANILIST"


def test_save_override_can_clear_forced_provider_back_to_auto(client, isolated_db):
    client.post(
        "/save-override",
        data={
            "series_id": "3",
            "forced_id": "99",
            "alternative_title": "X",
            "forced_provider": "KITSU",
        },
    )
    client.post(
        "/save-override",
        data={
            "series_id": "3",
            "forced_id": "",
            "alternative_title": "X",
            "forced_provider": "AUTO",
        },
    )
    cached = isolated_db.get_all_cached_data()[3]
    assert not cached.get("forced_id")
    assert cached["forced_provider"] == "AUTO"


# --- Enrichment uses overrides ------------------------------------------------


def test_forced_provider_restricts_provider_list_outside_super(monkeypatch):
    from services import enrichment_engine as ee
    from types import SimpleNamespace

    scrapers = [
        SimpleNamespace(id="ANILIST", needs_api_key=False, display_name="AniList"),
        SimpleNamespace(id="MAL", needs_api_key=False, display_name="MAL"),
    ]

    class FakeRegistry:
        def get_by_type(self, lib_type):
            return list(scrapers)

        def get(self, scraper_id):
            return next((s for s in scrapers if s.id == scraper_id), None)

        _scrapers = {s.id: s for s in scrapers}

    monkeypatch.setattr(ee, "ScraperRegistry", FakeRegistry())
    assert ee.apply_provider_overrides(
        ["ANILIST", "MAL"],
        config={},
        provider_family="Manga",
        forced_provider="MAL",
        super_review=False,
    ) == ["MAL"]
    assert ee.apply_provider_overrides(
        ["ANILIST", "MAL"],
        config={},
        provider_family="Manga",
        forced_provider="AUTO",
        super_review=False,
    ) == ["ANILIST", "MAL"]


def test_enrichment_search_query_priority_forced_id_then_alt_title():
    """Miroir de enrichment_engine : forced_id > alternative_title > series_name."""
    series_name = "Kavita Folder Name"
    cache = {
        "forced_id": "https://anilist.co/manga/30013",
        "alternative_title": "Le Collège Fou Fou Fou",
    }
    forced_id = cache.get("forced_id")
    search_query = forced_id or cache.get("alternative_title") or series_name
    fallback_query = cache.get("alternative_title") or series_name
    assert search_query == "https://anilist.co/manga/30013"
    assert fallback_query == "Le Collège Fou Fou Fou"

    cache_no_id = {"forced_id": "", "alternative_title": "Alt Only"}
    forced_id = cache_no_id.get("forced_id")
    search_query = forced_id or cache_no_id.get("alternative_title") or series_name
    assert search_query == "Alt Only"

    cache_empty = {"forced_id": "", "alternative_title": ""}
    forced_id = cache_empty.get("forced_id")
    search_query = forced_id or cache_empty.get("alternative_title") or series_name
    assert search_query == series_name


# --- Rendered dashboard -------------------------------------------------------


def test_dashboard_override_template_includes_magic_providers(
    pages_client, isolated_db, monkeypatch
):
    monkeypatch.setattr(
        "routes.pages.load_config",
        lambda: {
            "UI_LANG": "fr",
            "KAVITA_URL": "http://kavita.test",
            "KAVITA_API_KEY": "key",
        },
    )
    monkeypatch.setattr(
        "routes.pages.KavitaAPI",
        _fake_kavita([{"id": 1, "name": "One Piece", "libraryId": 1}]),
    )

    res = pages_client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="override-panel-template"' in html
    assert 'id="title-__SID__"' in html
    assert 'id="id-__SID__"' in html
    assert 'id="provider-__SID__"' in html
    assert 'option value="AUTO"' in html
    # At least one real magic scraper option (AniList / MAL / …)
    assert re.search(r'<option value="(ANILIST|MAL|KITSU|MANGADEX)"', html), html[:2000]
    assert "overrides.js" in html or 'src=' in html


def test_dashboard_series_row_reflects_saved_overrides(
    pages_client, isolated_db, monkeypatch
):
    isolated_db.save_series_override(
        SeriesOverride(
            series_id=42,
            forced_id="https://anilist.co/manga/30013",
            alternative_title="Le Collège Fou Fou Fou",
            forced_provider="MAL",
            targeted_fields="summary,cover",
            publisher_pref="ORIGINAL",
            alt_title_langs="en,ja-ro",
        )
    )
    monkeypatch.setattr(
        "routes.pages.load_config",
        lambda: {
            "UI_LANG": "fr",
            "KAVITA_URL": "http://kavita.test",
            "KAVITA_API_KEY": "key",
        },
    )
    monkeypatch.setattr(
        "routes.pages.KavitaAPI",
        _fake_kavita(
            [{"id": 42, "name": "Le College Fou Fou Fou", "libraryId": 1}]
        ),
    )

    res = pages_client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'data-series-id="42"' in html
    assert 'data-forced-id="https://anilist.co/manga/30013"' in html
    assert 'data-alt-title="Le Collège Fou Fou Fou"' in html
    assert 'data-forced-provider="MAL"' in html
    assert 'data-targeted-fields="summary,cover"' in html
    assert 'data-publisher-pref="ORIGINAL"' in html
    assert 'data-alt-langs="en,ja-ro"' in html


def test_dashboard_series_index_json_includes_override_fields(
    pages_client, isolated_db, monkeypatch
):
    """Virtual-list payload must carry the same override fields as Jinja rows."""
    isolated_db.save_series_override(
        SeriesOverride(
            series_id=99,
            forced_id="4242",
            alternative_title="Alt JSON",
            forced_provider="ANILIST",
        )
    )
    monkeypatch.setattr(
        "routes.pages.load_config",
        lambda: {
            "UI_LANG": "en",
            "KAVITA_URL": "http://kavita.test",
            "KAVITA_API_KEY": "key",
        },
    )
    # Force virtual list (≥120) so series_index_payload is embedded.
    series = [
        {"id": i, "name": f"Series {i}", "libraryId": 1} for i in range(1, 125)
    ]
    series[98] = {"id": 99, "name": "Series 99", "libraryId": 1}
    monkeypatch.setattr("routes.pages.KavitaAPI", _fake_kavita(series))

    res = pages_client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'data-virtual="1"' in html
    assert '"forced_id": "4242"' in html or '"forced_id":"4242"' in html
    assert '"alternative_title": "Alt JSON"' in html or '"alternative_title":"Alt JSON"' in html
    assert '"forced_provider": "ANILIST"' in html or '"forced_provider":"ANILIST"' in html
