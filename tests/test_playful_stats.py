"""
C7 — Stats ludiques : compteurs lifetime, formules organiques, Chart data.
"""
import os

import pytest
from flask import Flask

from services.stats_service import (
    STATS_MINUTES_PER_MATCH,
    STATS_MINUTES_PER_SERIES,
    _estimate_minutes,
    _format_duration,
    compute_playful_stats,
)


def test_record_enrichment_telemetry(isolated_db):
    d1 = isolated_db.record_enrichment_telemetry(["ANILIST", "MANGABAKA", "ANILIST"])
    d2 = isolated_db.record_enrichment_telemetry(["ANILIST (Titre Traduit)", "KITSU"])
    d3 = isolated_db.record_enrichment_telemetry([])
    d4 = isolated_db.record_enrichment_miss()
    d5 = isolated_db.record_enrichment_miss()

    assert d1 == {"series_enriched_delta": 1, "matches_won_delta": 2, "series_missed_delta": 0}
    assert d2["matches_won_delta"] == 2
    assert d3["matches_won_delta"] == 0
    assert d4 == {"series_enriched_delta": 0, "matches_won_delta": 0, "series_missed_delta": 1}
    assert d5["series_missed_delta"] == 1

    life = isolated_db.get_lifetime_stats()
    assert life["series_enriched"] == 3
    assert life["matches_won"] == 4
    assert life["series_missed"] == 2

    wins = isolated_db.get_provider_stats()
    assert wins["ANILIST"] == 2
    assert wins["MANGABAKA"] == 1
    assert wins["KITSU"] == 1


def test_broadcast_enrichment_stats_emits_lifetime(monkeypatch, isolated_db):
    from services import enrichment_engine as eng

    captured = {}

    class FakeSocket:
        def emit(self, event, payload):
            captured["event"] = event
            captured["payload"] = payload

    monkeypatch.setattr("extensions.socketio", FakeSocket())
    isolated_db.record_enrichment_telemetry(["ANILIST"])
    eng._broadcast_enrichment_stats(
        {"series_enriched_delta": 1, "matches_won_delta": 1, "series_missed_delta": 0}
    )

    assert captured["event"] == "enrichment_stats"
    assert captured["payload"]["series_enriched_delta"] == 1
    assert captured["payload"]["matches_won_delta"] == 1
    assert captured["payload"]["lifetime"]["series_enriched"] == 1
    assert captured["payload"]["lifetime"]["matches_won"] == 1
    assert captured["payload"]["lifetime"]["series_missed"] == 0


def test_format_duration_days_and_hours():
    assert _format_duration(0)["display"] == "0 min"
    assert _format_duration(45)["display"] == "45 min"
    assert _format_duration(90)["display"] == "1h 30m"
    d = _format_duration(60 * 24 + 90)
    assert d["days"] == 1
    assert d["display"] == "1j 1h 30m"


def test_estimate_minutes_includes_matches():
    assert _estimate_minutes(10, 0) == 10 * STATS_MINUTES_PER_SERIES
    assert _estimate_minutes(10, 25) == int(round(10 * STATS_MINUTES_PER_SERIES + 25 * STATS_MINUTES_PER_MATCH))


def test_compute_playful_stats_uses_lifetime_not_cache_completed():
    cache = {
        1: {"status": "COMPLETED", "forced_id": "", "forced_provider": "AUTO", "targeted_fields": "ALL", "alt_title_langs": "", "publisher_pref": "GLOBAL"},
        2: {"status": "COMPLETED", "forced_id": "123", "forced_provider": "AUTO", "targeted_fields": "summary,genres", "alt_title_langs": "", "publisher_pref": "LOCALIZED"},
        3: {"status": "NOT_FOUND", "forced_id": "", "forced_provider": "AUTO", "targeted_fields": "ALL", "alt_title_langs": "", "publisher_pref": "GLOBAL"},
        4: {"status": "PENDING", "forced_id": "", "forced_provider": "ANILIST", "targeted_fields": "ALL", "alt_title_langs": "", "publisher_pref": "ORIGINAL"},
        5: {"status": "IGNORED", "forced_id": "", "forced_provider": "AUTO", "targeted_fields": "ALL", "alt_title_langs": "en", "publisher_pref": "GLOBAL"},
    }
    lifetime = {"series_enriched": 10, "matches_won": 25, "series_missed": 5}
    wins = {"ANILIST": 5, "MANGABAKA": 2, "KITSU": 1}

    playful = compute_playful_stats(cache, wins, lifetime)

    assert playful["series_enriched"] == 10
    assert playful["matches_won"] == 25
    assert playful["series_missed"] == 5
    assert playful["lifetime_hit_rate"] == round(100.0 * 10 / 15, 1)
    assert playful["avg_matches"] == 2.5
    assert playful["estimate_series"] == 10
    assert playful["estimate_matches"] == 25
    assert playful["estimates_use_cache_floor"] is False
    assert playful["time_saved"]["total_minutes"] == _estimate_minutes(10, 25)
    assert playful["completed"] == 2
    assert playful["charts"]["lifetime"]["values"] == [10, 25, 5]
    assert playful["charts"]["hit_miss"]["values"] == [10, 5]
    assert playful["charts"]["status"]["values"] == [2, 1, 0, 1, 1]
    assert playful["charts"]["status"]["labels"] == [
        "COMPLETED", "PENDING", "PENDING_REVIEW", "NOT_FOUND", "IGNORED"
    ]
    assert playful["champion"]["id"] == "ANILIST"
    assert playful["underdog"]["id"] == "KITSU"


def test_compute_playful_stats_floors_estimates_on_cache_when_lifetime_empty():
    """Ancienne install : cache plein, télémétrie lifetime encore à 0."""
    cache = {
        i: {
            "status": "COMPLETED",
            "forced_id": "",
            "forced_provider": "AUTO",
            "targeted_fields": "ALL",
            "alt_title_langs": "",
            "publisher_pref": "GLOBAL",
        }
        for i in range(1, 6)
    }
    cache[6] = {
        "status": "NOT_FOUND",
        "forced_id": "",
        "forced_provider": "AUTO",
        "targeted_fields": "ALL",
        "alt_title_langs": "",
        "publisher_pref": "GLOBAL",
    }
    wins = {"ANILIST": 8, "KITSU": 2}

    playful = compute_playful_stats(cache, wins, {})

    assert playful["series_enriched"] == 0
    assert playful["matches_won"] == 0
    assert playful["estimate_series"] == 5
    assert playful["estimate_matches"] == 10
    assert playful["estimates_use_cache_floor"] is True
    assert playful["time_saved"]["total_minutes"] == _estimate_minutes(5, 10)
    assert playful["time_saved"]["total_minutes"] > 0
    assert playful["coffees_avoided"] > 0
    assert playful["manga_pages"] == 5 * 160
    assert playful["lifetime_hit_rate"] == round(100.0 * 5 / 6, 1)
    assert playful["charts"]["hit_miss"]["values"] == [5, 1]


def test_compute_playful_stats_empty():
    playful = compute_playful_stats({}, {}, {})
    assert playful["series_enriched"] == 0
    assert playful["matches_won"] == 0
    assert playful["series_missed"] == 0
    assert playful["lifetime_hit_rate"] == 0.0
    assert playful["avg_matches"] == 0.0
    assert playful["manual_reviews"] == 0
    assert playful["manual_skips"] == 0
    assert playful["manual_avg_score"] == 0.0
    assert playful["manual_top1_rate"] == 0.0
    assert playful["manual_field_edits"] == 0
    assert playful["pending_review"] == 0
    assert playful["time_saved"]["display"] == "0 min"
    assert playful["champion"] is None
    assert playful["has_provider_data"] is False
    assert playful["mr_achievements"]["unlocked_count"] == 0
    assert playful["mr_achievements"]["total"] > 0
    assert "empty_session" not in {c["id"] for c in playful["mr_achievements"]["locked"]}


@pytest.fixture
def pages_client(isolated_db):
    from routes.pages import pages_bp

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(__name__, template_folder=os.path.join(root, "templates"))
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(pages_bp)
    return app.test_client()


def test_stats_page_hides_playful_when_disabled(pages_client, isolated_db, monkeypatch):
    isolated_db.record_enrichment_telemetry(["ANILIST"])
    monkeypatch.setattr(
        "routes.pages.load_config",
        lambda: {"UI_LANG": "fr", "ENABLE_PLAYFUL_STATS": False},
    )
    response = pages_client.get("/stats")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "chartStatus" not in html
    assert "chart.js" not in html.lower()
    assert "Temps gagné" not in html


def test_stats_page_shows_charts_and_lifetime(pages_client, isolated_db, monkeypatch):
    isolated_db.record_enrichment_telemetry(["ANILIST", "MANGABAKA"])
    isolated_db.record_enrichment_miss()
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})

    response = pages_client.get("/stats")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "chart.js" in html.lower()
    assert "chartStatus" in html
    assert "chartHitMiss" in html
    assert "Séries enrichies" in html
    assert "Matchs réussis" in html
    assert "Temps gagné" in html
    assert "data-count-minutes" in html
    assert "Cafés pour le dev" in html
    assert 'id="mr-achievements"' in html
    assert "Hauts-faits" in html
