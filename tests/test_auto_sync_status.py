"""GET /api/auto-sync/status — Stop UI + ligne hub (session, pas de JWT)."""
from flask import Flask

import services.background_tasks as bg
from routes.sync import sync_bp


def _client(monkeypatch):
    monkeypatch.setattr(
        "routes.sync.load_config",
        lambda: {
            "UI_LANG": "fr",
            "AUTO_SYNC_ENABLED": True,
            "AUTO_SYNC_TRIGGER": "scan",
        },
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sync_bp)
    return app.test_client()


def test_status_reports_waiting_auto_without_hub_token(monkeypatch, isolated_db):
    while not bg.sync_queue.empty():
        try:
            bg.sync_queue.get_nowait()
        except Exception:
            break
    client = _client(monkeypatch)

    empty = client.get("/api/auto-sync/status")
    assert empty.status_code == 200
    body = empty.get_json()
    assert body["waiting_auto"] is False
    assert body["enabled"] is True
    assert body["trigger"] == "scan"
    assert body["hub"]["status"] in (
        "disconnected",
        "connecting",
        "connected",
        "reconnecting",
        "error",
        "idle",
    )
    assert "token" not in str(body).lower()
    assert "jwt" not in str(body).lower()

    bg.sync_queue.put(bg.make_sync_item(3, "Auto", False, origin="auto"))
    waiting = client.get("/api/auto-sync/status").get_json()
    assert waiting["waiting_auto"] is True
    assert "report" in waiting
    assert waiting["report"]["visible"] is False
    assert waiting["report"]["series_ids"] == []
    while not bg.sync_queue.empty():
        bg.sync_queue.get_nowait()
