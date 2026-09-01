"""
C7 — Stats ludiques : compteurs lifetime, formules organiques, Chart data.
"""
import os

import pytest
from flask import Flask

from services.stats_service import (
    STATS_MINUTES_PER_MATCH,
    STATS_MINUTES_PER_SERIES,
    STATS_MINUTES_TYPE_PER_VOLUME,
    STATS_PAGES_PER_VOLUME,
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
    assert life["covers_applied"] == 0
    assert life["locks_sealed"] == 0
    assert life["runs_batch"] == 0
    assert life["auto_sync_waves"] == 0
    assert life["auto_sync_series"] == 0

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
    assert playful["needs_relock"] == 0
    assert playful["charts"]["lifetime"]["values"] == [10, 25, 5]
    assert playful["charts"]["hit_miss"]["values"] == [2, 1]
    assert playful["manga_pages"] == 0
    assert playful["charts"]["status"]["values"] == [2, 0, 1, 0, 1, 1]
    assert playful["charts"]["status"]["labels"] == [
        "COMPLETED", "NEEDS_RELOCK", "PENDING", "PENDING_REVIEW", "NOT_FOUND", "IGNORED"
    ]
    assert playful["champion"]["id"] == "ANILIST"
    assert playful["underdog"]["id"] == "KITSU"


def test_compute_playful_stats_floors_estimates_on_cache_when_lifetime_empty():
    """Ancienne install : cache plein, télémétrie lifetime encore à 0.
    Le plancher cache alimente le temps gagné, pas les tuiles lifetime."""
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
    assert playful["manga_pages"] == 0
    assert playful["avg_matches"] == 0.0
    assert playful["lifetime_hit_rate"] == 0.0
    assert playful["success_rate"] == round(100.0 * 5 / 6, 1)
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
    assert playful["needs_relock"] == 0
    assert playful["time_saved"]["display"] == "0 min"
    assert playful["champion"] is None
    assert playful["has_provider_data"] is False
    assert playful["mr_achievements"]["unlocked_count"] == 0
    assert playful["mr_achievements"]["total"] > 0
    assert "empty_session" not in {c["id"] for c in playful["mr_achievements"]["locked"]}
    assert playful["inventory"]["has_data"] is False
    assert playful["volumes"]["has_data"] is False
    assert playful["mapping_enabled"] is False
    assert playful["mapping_overrides"] == 0
    assert playful["manual_fusions"] == 0
    assert playful["alt_titles"] == 0
    assert playful["lang_palette"] == 0
    assert playful["train_rides"] == 0.0
    assert playful["sleep_nights"] == 0.0
    assert playful["expected_overrides"] == 0
    assert playful["dup_dismissals"] == 0
    assert playful["volumes"]["champion"] is None
    assert playful["volumes"]["shelf_cm"] == 0.0
    assert playful["covers_applied"] == 0
    assert playful["locks_sealed"] == 0
    assert playful["runs_batch"] == 0
    assert playful["runs_webhook"] == 0
    assert playful["runs_auto"] == 0
    assert playful["runs_row"] == 0
    assert playful["runs_workshop"] == 0
    assert playful["volumes"]["workshop_runs"] == 0
    assert playful["auto_sync"]["waves"] == 0
    assert playful["auto_sync"]["series"] == 0
    assert playful["auto_sync"]["ok"] == 0
    assert playful["auto_sync"]["ok_rate"] == 0.0
    assert playful["auto_sync"]["writes"] == 0
    assert playful["auto_sync"]["time_saved"]["total_minutes"] == 0


@pytest.fixture
def pages_client(isolated_db):
    from routes.pages import pages_bp

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
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
    assert "À côté" not in html
    assert "Trajets TGV" not in html
    assert 'id="stats-autosync"' not in html
    assert "Les vagues qui tournent toutes seules" not in html


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
    assert "télémétrie lifetime" in html
    assert "Matchs lifetime" in html
    assert "Distinct des mystères encore dans le cache" in html
    assert "160 pages par série" not in html
    assert "Pages « manga »" not in html
    assert 'id="stats-autosync"' in html
    assert "Les vagues qui tournent toutes seules" in html
    assert "le 🔒 reste à poser" not in html


# Les six statuts que le moteur écrit en cache — même liste que
# tests/test_sidebar_stats_card.py, recopiée pour que /stats ne puisse pas
# dériver de la carte sidebar sans que ce fichier ne le voie.
_ENGINE_STATUSES = (
    "COMPLETED",
    "NOT_FOUND",
    "NEEDS_RELOCK",
    "PENDING",
    "PENDING_REVIEW",
    "IGNORED",
)


def test_stats_page_lists_every_engine_status(pages_client, isolated_db, monkeypatch):
    """C68 a ajouté NEEDS_RELOCK à la carte sidebar ; /stats gardait un donut
    à quatre parts pour six nombres. La page doit montrer les six, et Chart.js
    doit recevoir autant de libellés que de valeurs."""
    import json
    import re

    from translations import translations

    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    for index, status in enumerate(_ENGINE_STATUSES, start=1):
        isolated_db.update_status(100 + index, status)

    html = pages_client.get("/stats").get_data(as_text=True)
    t = translations["fr"]

    for key in (
        "stats_ok",
        "stats_needs_relock",
        "stats_pending_review",
        "stats_wait",
        "stats_err",
        "stats_ignored",
    ):
        assert t[key] in html, key

    labels = json.loads(re.search(r"const labelsStatus = (\[.*?\]);", html).group(1))
    charts_start = html.index("const charts = ") + len("const charts = ")
    charts, _ = json.JSONDecoder().raw_decode(html[charts_start:])
    assert len(labels) == 6
    assert len(charts["status"]["values"]) == 6
    assert labels == [
        t["stats_enriched"],
        t["stats_needs_relock"],
        t["stats_pending"],
        t["stats_pending_review"],
        t["stats_errors"],
        t["stats_ignored"],
    ]
    assert sum(charts["status"]["values"]) == len(_ENGINE_STATUSES)
    assert "'#2dd4bf', '#f59e0b', '#38bdf8', '#a78bfa', '#fb7185', '#94a3b8'" in html


def test_cover_manual_counts_as_protected():
    cache = {
        1: {
            "status": "COMPLETED",
            "forced_id": "",
            "forced_provider": "AUTO",
            "targeted_fields": "ALL",
            "alt_title_langs": "",
            "publisher_pref": "GLOBAL",
            "cover_manual": True,
        },
        2: {
            "status": "COMPLETED",
            "forced_id": "",
            "forced_provider": "AUTO",
            "targeted_fields": "ALL",
            "alt_title_langs": "",
            "publisher_pref": "GLOBAL",
            "cover_manual": False,
        },
    }
    playful = compute_playful_stats(cache, {}, {})
    assert playful["protected_covers"] == 1


def test_surgical_mask_without_cover_is_not_a_protected_cover():
    """C65 : omettre cover du masque, ce n'est pas une couverture 🔒."""
    cache = {
        1: {
            "status": "COMPLETED",
            "forced_id": "",
            "forced_provider": "AUTO",
            "targeted_fields": "summary,genres",
            "alt_title_langs": "",
            "publisher_pref": "GLOBAL",
            "cover_manual": False,
        },
    }
    playful = compute_playful_stats(cache, {}, {})
    assert playful["protected_covers"] == 0
    assert playful["surgical"] == 1


def test_inventory_and_volumes_and_mapping_join_playful():
    from services.field_mapping import PLAN_SPECS

    map_key = PLAN_SPECS[0][4]
    hygiene = {
        "series": 10,
        "healthy": 7,
        "incomplete": 2,
        "unknown_expected": 1,
        "missing": 14,
        "duplicates": 3,
        "no_external_id": 1,
        "failed": 0,
        "excluded": 1,
    }
    playful = compute_playful_stats(
        {},
        {},
        {"manual_fusions": 4, "manual_super_confirms": 2, "manual_weak_picks": 1},
        config={"FIELD_MAPPING_ENABLED": True, map_key: {"cover": "ANILIST", "summary": "CASCADE"}},
        hygiene_counts=hygiene,
        volume_status_counts={"DONE": 40, "FAILED": 2, "NOTHING_FOUND": 3, "SKIPPED": 5},
        volume_series_done=8,
    )
    assert playful["inventory"]["has_data"] is True
    assert playful["inventory"]["healthy"] == 7
    assert playful["inventory"]["missing"] == 14
    assert playful["volumes"]["has_data"] is True
    assert playful["volumes"]["done"] == 40
    assert playful["volumes"]["series_done"] == 8
    assert playful["volumes"]["units"] == 50
    assert playful["mapping_enabled"] is True
    assert playful["mapping_overrides"] == 1
    assert playful["manual_fusions"] == 4
    assert playful["manual_super_confirms"] == 2
    assert playful["alt_titles"] == 0
    assert playful["volumes"]["champion"] is None
    assert playful["volumes"]["shelf_cm"] == round(40 * 1.6, 1)
    assert playful["manga_pages"] == 40 * STATS_PAGES_PER_VOLUME
    assert playful["time_saved"]["total_minutes"] == int(
        round(40 * STATS_MINUTES_TYPE_PER_VOLUME)
    )


def test_pick_hygiene_prefers_all_libraries_scan():
    from services.stats_service import pick_hygiene_counts

    all_meta = {"counts": {"series": 12, "healthy": 9}}
    others = [{"library_id": "7", "scanned_at": "2099-01-01", "counts": {"series": 3, "healthy": 1}}]
    assert pick_hygiene_counts(all_meta, others)["series"] == 12
    assert pick_hygiene_counts(None, others)["series"] == 3


def _stats_css():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return open(os.path.join(root, "static", "css", "stats.css"), encoding="utf-8").read()


def test_stats_page_is_not_the_dashboard_shell(pages_client, isolated_db, monkeypatch):
    """BF176 — /stats chargeait style.css dans un .dashboard-wrapper / .content.
    Ces classes figent 100vh et overflow:hidden : le récit était coupé."""
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    html = pages_client.get("/stats").get_data(as_text=True)
    assert 'class="stats-page"' in html
    assert "dashboard-wrapper" not in html
    assert 'class="content stats-story"' not in html
    assert "css/stats.css" in html
    assert "js/stats.js" in html
    css = _stats_css()
    assert "html.stats-page" in css
    assert "overflow: hidden" not in css.split("html.stats-page body", 1)[1].split("}", 1)[0]


def test_stats_page_scroll_story_is_not_clipped(pages_client, isolated_db, monkeypatch):
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    html = pages_client.get("/stats").get_data(as_text=True)
    css = _stats_css()
    chapter_css = css.split(".stats-chapter {", 1)[1].split("}", 1)[0]
    assert "overflow: visible" in chapter_css
    assert "overflow: hidden" not in chapter_css
    assert "min-height: 100dvh" in chapter_css
    assert "min(100dvh, 920px)" not in css
    assert "scroll-snap-type: y proximity" in css
    assert 'class="stats-dots"' in html
    assert 'id="stats-hero"' in html
    assert 'id="stats-lifetime"' in html
    assert 'id="stats-autosync"' in html
    assert 'id="stats-time"' in html


def test_stats_page_shows_inventory_and_volumes_when_data_exists(
    pages_client, isolated_db, monkeypatch
):
    from db_manager import mark_series_pass_done, save_volume_unit_state, set_hygiene_library_meta

    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    set_hygiene_library_meta(
        "all",
        {
            "series": 8,
            "healthy": 5,
            "incomplete": 2,
            "unknown_expected": 1,
            "missing": 11,
            "duplicates": 2,
            "no_external_id": 1,
            "failed": 0,
            "excluded": 0,
        },
    )
    save_volume_unit_state(7, 701, "DONE")
    save_volume_unit_state(8, 801, "FAILED")
    mark_series_pass_done(7)

    html = pages_client.get("/stats").get_data(as_text=True)
    assert 'id="stats-inventory"' in html
    assert 'id="stats-volumes"' in html
    assert "Fusions de champs" in html
    assert "Mapping par champ" in html
    assert "Tomes écrits" in html


def test_sidequests_from_cache_and_volume_writes():
    cache = {
        1: {
            "status": "COMPLETED",
            "forced_id": "",
            "forced_provider": "AUTO",
            "targeted_fields": "ALL",
            "alt_title_langs": "en,ja-ro",
            "publisher_pref": "GLOBAL",
            "alternative_title": "Gloutons et Dragons",
        },
        2: {
            "status": "COMPLETED",
            "forced_id": "",
            "forced_provider": "AUTO",
            "targeted_fields": "ALL",
            "alt_title_langs": "en",
            "publisher_pref": "GLOBAL",
            "alternative_title": "",
        },
    }
    playful = compute_playful_stats(
        cache,
        {"ANILIST": 3},
        {"series_enriched": 4, "matches_won": 8},
        expected_overrides=2,
        dup_dismissals=3,
        volume_status_counts={"DONE": 10},
        volume_writes={
            "providers": {"MANGANEWS": 7, "COMICVINE": 3},
            "fields": {"title": 8, "summary": 5, "isbn": 2, "writers": 1},
        },
    )
    assert playful["alt_titles"] == 1
    assert playful["lang_palette"] == 2
    assert "en" in playful["lang_codes"]
    assert playful["expected_overrides"] == 2
    assert playful["dup_dismissals"] == 3
    assert playful["train_rides"] > 0
    assert playful["sleep_nights"] > 0
    assert playful["volumes"]["champion"]["id"] == "MANGANEWS"
    assert playful["volumes"]["champion"]["wins"] == 7
    assert playful["volumes"]["titles"] == 8
    assert playful["volumes"]["summaries"] == 5
    assert playful["volumes"]["isbns"] == 2
    assert playful["volumes"]["credits"] == 1
    assert playful["volumes"]["shelf_cm"] == 16.0
    assert playful["volumes"]["typing"]["total_minutes"] == 10
    assert playful["manga_pages"] == 10 * STATS_PAGES_PER_VOLUME
    assert playful["time_saved"]["total_minutes"] == _estimate_minutes(4, 8) + 10


def test_stats_page_shows_sidequests(pages_client, isolated_db, monkeypatch):
    from db_manager import (
        save_dup_dismissal,
        save_series_override,
        save_volume_unit_state,
        set_catalog_expected_override,
    )
    from models import SeriesOverride

    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    save_series_override(
        SeriesOverride(series_id=11, alternative_title="Maison", alt_title_langs="fr,en"),
        status="COMPLETED",
    )
    set_catalog_expected_override(11, 12)
    save_dup_dismissal(7, [10, 11], "not_duplicate")
    save_volume_unit_state(
        11, 1101, "DONE", provider="MANGANEWS",
        written_fields=["title", "summary", "isbn"],
    )

    html = pages_client.get("/stats").get_data(as_text=True)
    assert 'id="stats-sidequests"' in html
    assert "À côté" in html
    assert "Trajets TGV" in html
    assert "Titres maison" in html
    assert "Doublons pardonnés" in html
    assert "Champion des tomes" in html
    assert "Étagère (cm)" in html
    assert "Saisie évitée" in html
    assert "Pages « manga »" in html
    assert "180 pages par tome" in html
    assert "Lots" in html
    assert "Clic ligne" in html
    assert "Couvertures posées" in html
    assert "Verrous scellés" in html


def test_record_lifetime_gestures(isolated_db):
    assert isolated_db.record_lifetime_event("not_a_key") == 0
    assert isolated_db.record_lifetime_event("covers_applied", 2) == 2
    isolated_db.record_run_origin("webhook")
    isolated_db.record_run_origin("auto")
    isolated_db.record_run_origin("workshop")
    life = isolated_db.get_lifetime_stats()
    assert life["covers_applied"] == 2
    assert life["runs_webhook"] == 1
    assert life["runs_auto"] == 1
    assert life["runs_workshop"] == 1
    assert life["runs_batch"] == 0
    assert life["runs_row"] == 0
    assert life["locks_sealed"] == 0


def test_compute_playful_stats_exposes_run_origins():
    playful = compute_playful_stats(
        {},
        {},
        {
            "covers_applied": 4,
            "locks_sealed": 3,
            "runs_batch": 10,
            "runs_webhook": 2,
            "runs_auto": 1,
            "runs_row": 7,
        },
    )
    assert playful["covers_applied"] == 4
    assert playful["locks_sealed"] == 3
    assert playful["runs_batch"] == 10
    assert playful["runs_webhook"] == 2
    assert playful["runs_auto"] == 1
    assert playful["runs_row"] == 7


def test_workshop_lifetime_makes_volumes_has_data():
    playful = compute_playful_stats(
        {},
        {},
        {"runs_workshop": 1, "workshop_units": 4},
    )
    assert playful["runs_workshop"] == 1
    assert playful["volumes"]["has_data"] is True
    assert playful["volumes"]["workshop_runs"] == 1
    assert playful["volumes"]["workshop_units"] == 4


def test_compute_playful_stats_exposes_auto_sync_without_inflating_time_saved():
    playful = compute_playful_stats(
        {},
        {},
        {
            "auto_sync_waves": 3,
            "auto_sync_waves_stopped": 1,
            "auto_sync_waves_scan": 2,
            "auto_sync_waves_interval": 1,
            "auto_sync_series": 10,
            "auto_sync_ok": 2,
            "auto_sync_errors": 3,
            "auto_sync_review": 4,
            "auto_sync_relock": 1,
            "auto_sync_stopped": 1,
            "runs_auto": 5,
        },
    )
    snap = playful["auto_sync"]
    assert snap["waves"] == 3
    assert snap["waves_stopped"] == 1
    assert snap["waves_scan"] == 2
    assert snap["waves_interval"] == 1
    assert snap["series"] == 10
    assert snap["ok"] == 2
    assert snap["errors"] == 3
    assert snap["review"] == 4
    assert snap["relock"] == 1
    assert snap["stopped"] == 1
    assert snap["writes"] == 5
    assert snap["ok_rate"] == 20.0
    assert snap["time_saved"]["total_minutes"] == 2 * STATS_MINUTES_PER_SERIES
    assert playful["time_saved"]["total_minutes"] == 0
    assert playful["runs_auto"] == 5


def test_stats_page_shows_auto_sync_relock_when_counted(pages_client, isolated_db, monkeypatch):
    isolated_db.begin_auto_sync_run("scan", [(21, "Soft")])
    isolated_db.record_auto_sync_item(21, "Soft", True, "NEEDS_RELOCK")
    isolated_db.finish_open_auto_sync_run()
    monkeypatch.setattr("routes.pages.load_config", lambda: {"UI_LANG": "fr"})
    html = pages_client.get("/stats").get_data(as_text=True)
    assert "le 🔒 reste à poser" in html
    assert "Vagues scan" in html
    assert "Temps Auto-sync" in html

