"""C97 — rapport de vague Auto-sync (pas le lot dashboard, pas le webhook)."""
from __future__ import annotations

from flask import Flask
from pathlib import Path

import services.background_tasks as bg
from routes.sync import sync_bp
from services import auto_sync as asy

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
BATCH_JS = (ROOT / "static" / "js" / "batch.js").read_text(encoding="utf-8")
ASR_JS = (ROOT / "static" / "js" / "auto_sync_report.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")


def _client(monkeypatch):
    monkeypatch.setattr(
        "routes.sync.load_config",
        lambda: {
            "UI_LANG": "fr",
            "AUTO_SYNC_ENABLED": True,
            "AUTO_SYNC_TRIGGER": "scan",
        },
    )
    monkeypatch.setattr("services.background_tasks.broadcast_auto_sync_report", lambda *a, **k: None)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sync_bp)
    return app.test_client()


def _clear_queue():
    bg._set_inflight_origin("")
    while not bg.sync_queue.empty():
        try:
            bg.sync_queue.get_nowait()
        except Exception:
            break


def test_classify_outcomes():
    from db_manager import classify_auto_sync_outcome

    assert classify_auto_sync_outcome(True, "Succès", "COMPLETED") == "completed"
    assert classify_auto_sync_outcome(True, "Déjà à jour.", "COMPLETED") == "completed"
    assert classify_auto_sync_outcome(True, "PENDING_REVIEW", "PENDING_REVIEW") == "review"
    assert classify_auto_sync_outcome(True, "NEEDS_RELOCK", "NEEDS_RELOCK") == "relock"
    assert classify_auto_sync_outcome(False, "Introuvable.", "NOT_FOUND") == "error"
    assert classify_auto_sync_outcome(False, "Erreur Kavita", None) == "error"


def test_enqueue_opens_a_pending_run(isolated_db, monkeypatch):
    monkeypatch.setattr("services.background_tasks.put_sync", lambda item: None)
    monkeypatch.setattr("services.background_tasks.broadcast_auto_sync_report", lambda *a, **k: None)
    n = asy.enqueue_auto(
        [{"id": 11, "name": "Alpha"}, {"id": 12, "name": "Beta"}],
        {"AUTO_SYNC_TRIGGER": "scan", "AUTO_SYNC_MODE": "auto"},
    )
    assert n == 2
    report = isolated_db.get_latest_auto_sync_report()
    assert report["run"]["trigger"] == "scan"
    assert report["run"]["finished_at"] is None
    assert report["badge"]["running"] is True
    assert report["badge"]["unread"] is False
    assert report["badge"]["visible"] is True
    assert report["counts"]["total"] == 2
    assert report["counts"]["pending"] == 2
    names = {item["series_name"] for item in report["items"]}
    assert names == {"Alpha", "Beta"}


def test_row_and_webhook_jobs_do_not_write_the_report(isolated_db, mocker):
    mocker.patch("services.background_tasks.enrich_series", return_value=(True, "Succès", []))
    mocker.patch("services.background_tasks.load_config", return_value={"UI_LANG": "fr"})
    mocker.patch("services.background_tasks.broadcast_sync_settled")
    mocker.patch("services.background_tasks.broadcast_auto_sync_report")
    isolated_db.begin_auto_sync_run("interval", [(1, "Should stay pending")])
    _clear_queue()
    bg.sync_queue.put(bg.make_sync_item(99, "Row", False, origin="row"))
    bg.sync_queue.put(bg.make_sync_item(98, "Hook", False, origin="webhook"))
    bg.sync_queue.put(None)
    bg._worker()
    report = isolated_db.get_latest_auto_sync_report()
    assert report["items"][0]["outcome"] == "pending"
    assert report["run"]["finished_at"] is None


def test_worker_records_auto_jobs_and_closes_when_the_wave_is_done(isolated_db, mocker):
    mocker.patch(
        "services.background_tasks.enrich_series",
        side_effect=[
            (True, "Succès", []),
            (False, "Introuvable.", []),
        ],
    )
    mocker.patch("services.background_tasks.load_config", return_value={"UI_LANG": "fr"})
    mocker.patch("services.background_tasks.broadcast_sync_settled")
    mocker.patch("services.background_tasks.broadcast_auto_sync_report")
    isolated_db.update_status(1, "COMPLETED")
    isolated_db.update_status(2, "NOT_FOUND")
    isolated_db.begin_auto_sync_run("interval", [(1, "Ok"), (2, "Miss")])
    _clear_queue()
    bg.sync_queue.put(bg.make_sync_item(1, "Ok", False, origin="auto"))
    bg.sync_queue.put(bg.make_sync_item(2, "Miss", False, origin="auto"))
    bg.sync_queue.put(None)
    bg._worker()
    report = isolated_db.get_latest_auto_sync_report()
    by_id = {item["series_id"]: item for item in report["items"]}
    assert by_id[1]["outcome"] == "completed"
    assert by_id[2]["outcome"] == "error"
    assert report["counts"]["ok"] == 1
    assert report["counts"]["errors"] == 1
    assert report["run"]["finished_at"] is not None
    assert report["badge"]["unread"] is True
    assert report["badge"]["running"] is False
    assert report["badge"]["visible"] is True
    life = isolated_db.get_lifetime_stats()
    assert life["auto_sync_waves"] == 1
    assert life["auto_sync_waves_interval"] == 1
    assert life["auto_sync_waves_scan"] == 0
    assert life["auto_sync_series"] == 2
    assert life["auto_sync_ok"] == 1
    assert life["auto_sync_errors"] == 1
    assert life["auto_sync_review"] == 0
    assert life["auto_sync_stopped"] == 0


def test_stop_marks_waiting_auto_jobs_stopped(isolated_db, mocker):
    mocker.patch("services.background_tasks.broadcast_batch_progress")
    mocker.patch("services.background_tasks.broadcast_auto_sync_report")
    isolated_db.begin_auto_sync_run("scan", [(8, "Kept flying"), (9, "Drained")])
    _clear_queue()
    bg._set_inflight_origin("auto")
    bg.sync_queue.put(bg.make_sync_item(9, "Drained", False, origin="auto"))
    bg.drain_sync_queue()
    report = isolated_db.get_latest_auto_sync_report()
    by_id = {item["series_id"]: item for item in report["items"]}
    assert by_id[9]["outcome"] == "stopped"
    assert by_id[8]["outcome"] == "pending"
    assert report["run"]["finished_at"] is None, "un scrape auto en vol retarde la clôture"
    bg._set_inflight_origin("")
    bg.try_finish_auto_sync_run(from_worker=True)
    report = isolated_db.get_latest_auto_sync_report()
    assert report["run"]["finished_at"] is not None
    assert report["run"]["stopped"] is True
    assert report["badge"]["unread"] is True
    life = isolated_db.get_lifetime_stats()
    assert life["auto_sync_waves"] == 1
    assert life["auto_sync_waves_stopped"] == 1
    assert life["auto_sync_waves_scan"] == 1
    assert life["auto_sync_stopped"] == 1
    assert life["auto_sync_series"] == 2


def test_mark_read_hides_the_badge(isolated_db):
    isolated_db.begin_auto_sync_run("interval", [(3, "A")])
    isolated_db.record_auto_sync_item(3, "A", True, "Succès")
    isolated_db.finish_open_auto_sync_run()
    badge = isolated_db.get_auto_sync_report_badge()
    assert badge["unread"] is True
    assert badge["visible"] is True
    assert isolated_db.mark_auto_sync_report_read() is True
    badge = isolated_db.get_auto_sync_report_badge()
    assert badge["unread"] is False
    assert badge["visible"] is False


def test_report_routes(isolated_db, monkeypatch):
    client = _client(monkeypatch)
    isolated_db.begin_auto_sync_run("scan", [(4, "Delta")])
    isolated_db.record_auto_sync_item(4, "Delta", True, "Succès")
    isolated_db.finish_open_auto_sync_run()

    raw = client.get("/api/auto-sync/report")
    assert raw.status_code == 200
    body = raw.get_json()
    assert body["run"]["trigger"] == "scan"
    assert body["counts"]["ok"] == 1
    assert body["items"][0]["series_name"] == "Delta"
    assert body["badge"]["unread"] is True
    assert body["badge"]["series_ids"] == [4]

    read = client.post("/api/auto-sync/report/read")
    assert read.status_code == 200
    assert read.get_json()["report"]["unread"] is False
    assert isolated_db.get_auto_sync_report_badge()["visible"] is False


def test_button_sits_beside_reviews_and_is_hidden_by_default():
    assert 'id="mrOpenQueueBtn"' in INDEX
    assert 'id="asrOpenBtn"' in INDEX
    assert INDEX.index("asrOpenBtn") > INDEX.index("mrOpenQueueBtn")
    assert 'onclick="openAutoSyncReportModal()"' in INDEX
    chunk = INDEX.split('id="asrOpenBtn"', 1)[1].split("</button>", 1)[0]
    assert "hidden" in chunk
    assert "partials/_auto_sync_report_modal.html" in INDEX
    assert "js/auto_sync_report.js" in INDEX


def test_modal_and_css_are_premium_and_prefixed():
    modal = (ROOT / "templates" / "partials" / "_auto_sync_report_modal.html").read_text(
        encoding="utf-8"
    )
    assert 'id="autoSyncReportModal"' in modal
    assert "asr-modal" in modal
    assert "asr-tiles" in modal
    assert ".asr-modal" in CSS
    assert ".asr-tile--ok" in CSS
    assert ".live-kpi-autosync.has-unread" in CSS
    assert "getRootPath() + '/api/auto-sync/report'" in ASR_JS
    assert "getRootPath() + '/api/auto-sync/report/read'" in ASR_JS
    assert "function closeAutoSyncReportModal()" in ASR_JS
    close_fn = ASR_JS.split("function closeAutoSyncReportModal()", 1)[1].split("function ", 1)[0]
    assert "/api/auto-sync/report/read" in close_fn
    open_fn = ASR_JS.split("function openAutoSyncReportModal()", 1)[1].split("function ", 1)[0]
    assert "/api/auto-sync/report/read" not in open_fn
    assert "applyAutoSyncReportBadge" in BATCH_JS
    assert "asr_" in INDEX
    assert 'id="asrShowInListBtn"' in modal
    assert "applyAutoSyncListFilter()" in modal
    assert "function applyAutoSyncListFilter()" in ASR_JS
    assert "function setAutoSyncSeriesIds(" in ASR_JS
    assert "AUTO_SYNC" in ASR_JS


def test_orphan_cleanup_does_not_drop_the_report(isolated_db):
    isolated_db.update_status(501, "COMPLETED")
    isolated_db.begin_auto_sync_run("scan", [(501, "Gone")])
    isolated_db.record_auto_sync_item(501, "Gone", True, "Succès")
    isolated_db.finish_open_auto_sync_run()
    isolated_db.clean_orphaned_cache({999})
    report = isolated_db.get_latest_auto_sync_report()
    assert report["items"][0]["series_id"] == 501


def test_closing_a_wave_bumps_lifetime_once(isolated_db):
    isolated_db.begin_auto_sync_run("scan", [(11, "Ok"), (12, "Review")])
    isolated_db.record_auto_sync_item(11, "Ok", True, "NEEDS_RELOCK")
    isolated_db.record_auto_sync_item(12, "Review", False, "PENDING_REVIEW")
    assert isolated_db.finish_open_auto_sync_run() is True
    life = isolated_db.get_lifetime_stats()
    assert life["auto_sync_waves"] == 1
    assert life["auto_sync_waves_scan"] == 1
    assert life["auto_sync_waves_interval"] == 0
    assert life["auto_sync_waves_stopped"] == 0
    assert life["auto_sync_series"] == 2
    assert life["auto_sync_ok"] == 1
    assert life["auto_sync_relock"] == 1
    assert life["auto_sync_review"] == 1
    assert isolated_db.finish_open_auto_sync_run() is False
    again = isolated_db.get_lifetime_stats()
    assert again["auto_sync_waves"] == 1
    assert again["auto_sync_series"] == 2
    assert again["auto_sync_ok"] == 1


def test_empty_trigger_counts_as_interval(isolated_db):
    isolated_db.begin_auto_sync_run("", [(13, "Solo")])
    isolated_db.record_auto_sync_item(13, "Solo", True, "Succès")
    isolated_db.finish_open_auto_sync_run()
    life = isolated_db.get_lifetime_stats()
    assert life["auto_sync_waves_interval"] == 1
    assert life["auto_sync_waves_scan"] == 0


def test_badge_carries_last_wave_series_ids(isolated_db):
    assert isolated_db.get_auto_sync_report_badge()["series_ids"] == []
    isolated_db.begin_auto_sync_run("scan", [(4, "Delta"), (5, "Echo")])
    isolated_db.record_auto_sync_item(4, "Delta", True, "Succès")
    isolated_db.finish_open_auto_sync_run()
    badge = isolated_db.get_auto_sync_report_badge()
    assert sorted(badge["series_ids"]) == [4, 5]


def test_dashboard_filter_keeps_last_wave_ids():
    toolbar = (ROOT / "templates" / "partials" / "_toolbar.html").read_text(encoding="utf-8")
    series_js = (ROOT / "static" / "js" / "series_list.js").read_text(encoding="utf-8")
    apply_js = BATCH_JS.split("function _filterSeriesApply()", 1)[1].split("\nfunction ", 1)[0]
    virtual = series_js.split("function filterAndRender", 1)[1].split("\n    function ", 1)[0]
    assert 'value="AUTO_SYNC"' in toolbar
    assert "filter_auto_sync" in toolbar
    assert "filter === 'AUTO_SYNC'" in apply_js
    assert "autoSyncSeriesIds" in apply_js
    assert "filter === 'AUTO_SYNC'" in virtual
    assert "autoSyncSeriesIds" in virtual
    assert "window.AUTO_SYNC_SERIES_IDS" in INDEX
