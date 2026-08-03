"""
BF93 / issue #30 — dashboard series search must not force a reflow per row.

Regression net (no Node runtime):
- templates emit `data-search-title` and wire search to `scheduleFilterSeries`
- batch.js uses dataset / textContent + class toggle + 150 ms debounce
- CSS hides via `.is-filtered-out` (not per-item inline display)
- rendered dashboard HTML includes the attribute on series rows
"""
import os
from pathlib import Path

import pytest
from flask import Flask

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


def test_series_row_emits_data_search_title():
    html = _read("templates/partials/_series_row.html")
    assert 'data-search-title="' in html
    assert "(series.name or '')|lower|e" in html


def test_toolbar_search_uses_debounced_schedule():
    html = _read("templates/partials/_toolbar.html")
    assert 'id="searchInput"' in html
    assert 'oninput="scheduleFilterSeries()"' in html
    assert 'id="searchInsideCb"' in html


def test_batch_js_filter_avoids_innertext_and_inline_display():
    js = _read("static/js/batch.js")

    assert "function scheduleFilterSeries()" in js
    assert "function filterSeries()" in js
    assert ", 150);" in js or ", 150)" in js
    assert "dataset.searchTitle" in js
    assert "textContent" in js
    assert "classList.toggle('is-filtered-out'" in js
    assert "titleMatchesSearch" in js
    assert "startsWith" in js
    assert "getVisibleCheckedSeriesIds" in js

    filter_start = js.index("function filterSeries()")
    # Stay inside filterSeries; stop before the next top-level function.
    next_fn = js.find("\nfunction ", filter_start + 1)
    filter_body = js[filter_start:next_fn if next_fn != -1 else filter_start + 3000]
    assert "innerText" not in filter_body
    assert "style.display" not in filter_body
    # Mistype-safe: filter must not clear checkboxes (batch scopes to visible instead).
    assert "cb.checked = false" not in filter_body


def test_launch_batch_uses_visible_checked_only():
    js = _read("static/js/batch.js")
    launch_start = js.index("async function launchBatch")
    next_fn = js.find("\nfunction ", launch_start + 1)
    if next_fn == -1:
        next_fn = js.find("\nasync function ", launch_start + 1)
    body = js[launch_start:next_fn if next_fn != -1 else launch_start + 2000]
    assert "getVisibleCheckedSeriesIds" in body
    assert "querySelectorAll('.series-cb:checked')" not in body


def test_toggle_select_all_check_and_clear_semantics():
    js = _read("static/js/batch.js")
    start = js.index("function toggleSelectAll()")
    next_fn = js.find("\nfunction ", start + 1)
    body = js[start:next_fn if next_fn != -1 else start + 1200]
    assert "isSeriesItemVisible" in body
    assert "cb.checked = isSeriesItemVisible(item)" in body
    assert "cb.checked = false" in body
    assert "function updateSelectionCounters()" in js
    assert "getVisibleCheckedSeriesCbs().length" in js
    assert 'id="selectedCount"' in _read("templates/partials/_toolbar.html")
    # Resume-safe: launchBatch must not uncheck on enqueue.
    launch_start = js.index("async function launchBatch")
    next_fn = js.find("\nfunction ", launch_start + 1)
    if next_fn == -1:
        next_fn = js.find("\nasync function ", launch_start + 1)
    launch_body = js[launch_start:next_fn if next_fn != -1 else launch_start + 4000]
    assert "uncheckSeriesIds" not in launch_body


def test_css_is_filtered_out_hides_series_items():
    css = _read("static/css/style.css")
    assert ".series-item.is-filtered-out" in css
    assert "display: none" in css


def test_dashboard_series_rows_include_data_search_title(pages_client, isolated_db, monkeypatch):
    """Rendered list must carry precomputed lowercase titles for filterSeries()."""
    monkeypatch.setattr(
        "routes.pages.load_config",
        lambda: {
            "UI_LANG": "en",
            "KAVITA_URL": "http://kavita.test",
            "KAVITA_API_KEY": "key",
        },
    )

    class FakeKavita:
        def __init__(self, *a, **k):
            pass

        def authenticate(self):
            return True

        def get_libraries(self):
            return [{"id": 1, "name": "Manga"}]

        def get_all_series(self, library_id=None):
            return [
                {"id": 42, "name": "Made In Abyss", "libraryId": 1},
                {"id": 43, "name": "ONE PIECE", "libraryId": 1},
            ]

    monkeypatch.setattr("routes.pages.KavitaAPI", FakeKavita)

    response = pages_client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'data-search-title="made in abyss"' in html
    assert 'data-search-title="one piece"' in html
    assert "scheduleFilterSeries()" in html
