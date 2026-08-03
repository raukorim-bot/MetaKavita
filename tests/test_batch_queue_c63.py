"""C63 — persistent batch queue (SQLite + pause/resume/clear)."""
import pytest


@pytest.fixture
def bq(tmp_path, monkeypatch):
    import db_manager
    import services.batch_queue as batch_queue
    import services.background_tasks as bt

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(db_manager, "DATA_DIR", str(data))
    monkeypatch.setattr(db_manager, "DB_FILE", str(data / "cache.db"))
    batch_queue.ensure_tables()
    # Drain any leftover RAM from other tests
    bt.drain_sync_queue()
    batch_queue.set_paused(False)
    batch_queue.cancel_all_pending()
    yield batch_queue
    bt.drain_sync_queue()
    batch_queue.cancel_all_pending()


def test_enqueue_and_list(bq):
    r = bq.enqueue_items([
        {"series_id": 1, "series_name": "A", "force_update": False},
        {"series_id": 2, "series_name": "B", "force_update": True},
    ])
    assert r["added"] == 2
    assert r["skipped_dupes"] == 0
    assert bq.count_active() == 2
    names = {x["series_name"] for x in bq.list_active()}
    assert names == {"A", "B"}


def test_enqueue_skips_duplicates(bq):
    bq.enqueue_items([{"series_id": 1, "series_name": "A"}])
    r = bq.enqueue_items([{"series_id": 1, "series_name": "A again"}])
    assert r["added"] == 0
    assert r["skipped_dupes"] == 1
    assert bq.count_active() == 1


def test_cancel_queued_ok_running_409(bq):
    r = bq.enqueue_items([{"series_id": 10, "series_name": "X"}])
    item_id = r["items"][0]["id"]
    assert bq.cancel_item(item_id) == "ok"
    assert bq.count_active() == 0

    r2 = bq.enqueue_items([{"series_id": 11, "series_name": "Y"}])
    iid = r2["items"][0]["id"]
    bq.mark_running(11)
    assert bq.cancel_item(iid) == "running"


def test_clear_queued_keeps_running(bq):
    bq.enqueue_items([
        {"series_id": 1, "series_name": "A"},
        {"series_id": 2, "series_name": "B"},
    ])
    bq.mark_running(1)
    n = bq.cancel_all_queued()
    assert n == 1
    active = bq.list_active()
    assert len(active) == 1
    assert active[0]["series_id"] == 1
    assert active[0]["state"] == "running"


def test_pause_flag(bq):
    assert bq.is_paused() is False
    bq.set_paused(True)
    assert bq.is_paused() is True
    bq.set_paused(False)
    assert bq.is_paused() is False


def test_should_skip_after_cancel(bq):
    bq.enqueue_items([{"series_id": 5, "series_name": "Z"}])
    assert bq.should_skip_batch_item(5) is False
    item_id = bq.list_active()[0]["id"]
    bq.cancel_item(item_id)
    assert bq.should_skip_batch_item(5) is True


def test_hydrate_puts_to_ram(bq, monkeypatch):
    import services.background_tasks as bt

    puts = []
    monkeypatch.setattr(bt.sync_queue, "put", lambda item: puts.append(item))
    monkeypatch.setattr(bt, "register_batch_enqueue", lambda count, new_batch: None)

    bq.enqueue_items([
        {"series_id": 1, "series_name": "A"},
        {"series_id": 2, "series_name": "B"},
    ])
    # Don't put during enqueue test path — hydrate explicitly
    n = bt.hydrate_batch_queue_to_ram(new_batch=True)
    assert n == 2
    assert len(puts) == 2
    assert all(p.get("is_batch") for p in puts)


def test_reset_running_to_queued(bq):
    bq.enqueue_items([{"series_id": 9, "series_name": "R"}])
    bq.mark_running(9)
    assert bq.list_active()[0]["state"] == "running"
    assert bq.reset_running_to_queued() == 1
    assert bq.list_active()[0]["state"] == "queued"


def test_api_batch_queue_routes(bq, monkeypatch):
    from flask import Flask
    from routes.sync import sync_bp

    monkeypatch.setattr("routes.sync.batch_queue_svc", bq)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sync_bp)
    client = app.test_client()

    bq.enqueue_items([{"series_id": 1, "series_name": "A"}])
    res = client.get("/api/batch-queue")
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] == 1
    assert data["paused"] is False

    item_id = data["items"][0]["id"]
    res = client.delete(f"/api/batch-queue/{item_id}")
    assert res.status_code == 200
    assert res.get_json()["count"] == 0

    bq.enqueue_items([{"series_id": 2, "series_name": "B"}])
    res = client.post("/api/batch-queue/pause")
    assert res.status_code == 200
    assert res.get_json()["paused"] is True

    res = client.post("/api/batch-queue/resume")
    assert res.status_code == 200
    assert res.get_json()["paused"] is False

    res = client.post("/api/batch-queue/clear")
    assert res.status_code == 200
    assert res.get_json()["count"] == 0
