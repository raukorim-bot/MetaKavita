"""C33 Companion — put_front priority + replace pending same series_id."""
from __future__ import annotations

import queue

import pytest
from flask import Flask

from routes.sync import sync_bp
from services import background_tasks as bg


@pytest.fixture(autouse=True)
def isolated_queue(monkeypatch):
    q = queue.Queue()
    monkeypatch.setattr(bg, "sync_queue", q)
    bg.reset_batch_progress()
    yield q
    bg.reset_batch_progress()
    while not q.empty():
        try:
            q.get_nowait()
        except queue.Empty:
            break


def _drain_ids(q):
    ids = []
    while not q.empty():
        ids.append(q.get_nowait()["series_id"])
    return ids


def test_put_front_empty_queue(isolated_queue):
    item = bg.make_sync_item(1, "Solo", True, super_review=True)
    assert bg.put_front(item) == 0
    assert isolated_queue.get_nowait()["series_id"] == 1


def test_put_front_ahead_of_batch(isolated_queue, monkeypatch):
    monkeypatch.setattr("services.batch_queue.cancel_queued_by_series", lambda sid: 0)
    bg.put_sync(bg.make_sync_item(1, "A", False, is_batch=True))
    bg.put_sync(bg.make_sync_item(2, "B", False, is_batch=True))
    c = bg.make_sync_item(99, "Companion", True, super_review=True)
    assert bg.put_front(c) == 0
    assert _drain_ids(isolated_queue) == [99, 1, 2]


def test_put_front_replaces_same_series_batch(isolated_queue, monkeypatch):
    cancelled = []

    def fake_cancel(sid):
        cancelled.append(int(sid))
        return 1

    monkeypatch.setattr("services.batch_queue.cancel_queued_by_series", fake_cancel)
    monkeypatch.setattr(
        "services.background_tasks.broadcast_batch_progress",
        lambda *a, **k: None,
    )

    bg.register_batch_enqueue(3, new_batch=True)
    bg.put_sync(bg.make_sync_item(1, "A", False, is_batch=True))
    bg.put_sync(bg.make_sync_item(42, "Target", False, is_batch=True))
    bg.put_sync(bg.make_sync_item(3, "C", False, is_batch=True))

    companion = bg.make_sync_item(42, "Target", True, super_review=True)
    dropped = bg.put_front(companion)
    assert dropped == 1
    assert cancelled == [42]
    assert _drain_ids(isolated_queue) == [42, 1, 3]

    # Flags on the replacement job
    bg.put_sync(bg.make_sync_item(1, "A", False, is_batch=True))
    bg.put_sync(bg.make_sync_item(42, "Target", False, is_batch=True))
    bg.put_front(bg.make_sync_item(42, "Target", True, super_review=True))
    first = isolated_queue.get_nowait()
    assert first["series_id"] == 42
    assert first["super_review"] is True
    assert first["is_batch"] is False
    with bg._batch_progress_lock:
        assert bg._batch_done >= 1


def test_put_front_lifo_different_series(isolated_queue, monkeypatch):
    monkeypatch.setattr("services.batch_queue.cancel_queued_by_series", lambda sid: 0)
    bg.put_sync(bg.make_sync_item(1, "Batch", False, is_batch=True))
    bg.put_front(bg.make_sync_item(10, "C1", True, super_review=True))
    bg.put_front(bg.make_sync_item(20, "C2", True, force_auto=True))
    assert _drain_ids(isolated_queue) == [20, 10, 1]


def test_put_front_replaces_prior_companion_same_series(isolated_queue, monkeypatch):
    monkeypatch.setattr("services.batch_queue.cancel_queued_by_series", lambda sid: 0)
    bg.put_front(bg.make_sync_item(7, "X", True, force_auto=True))
    dropped = bg.put_front(bg.make_sync_item(7, "X", True, super_review=True))
    assert dropped == 1
    only = isolated_queue.get_nowait()
    assert only["super_review"] is True
    assert only["force_auto"] is False
    assert isolated_queue.empty()


@pytest.fixture
def bq(tmp_path, monkeypatch):
    import db_manager
    import services.batch_queue as batch_queue

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(db_manager, "DATA_DIR", str(data))
    monkeypatch.setattr(db_manager, "DB_FILE", str(data / "cache.db"))
    batch_queue.ensure_tables()
    batch_queue.set_paused(False)
    batch_queue.cancel_all_pending()
    yield batch_queue
    batch_queue.cancel_all_pending()


def test_cancel_queued_by_series(bq):
    bq.enqueue_items([
        {"series_id": 5, "series_name": "Keep"},
        {"series_id": 8, "series_name": "Drop"},
    ])
    assert bq.cancel_queued_by_series(8) == 1
    assert bq.cancel_queued_by_series(8) == 0
    active = {r["series_id"] for r in bq.list_active()}
    assert active == {5}
    assert bq.should_skip_batch_item(8) is True


@pytest.fixture
def webhook_client(monkeypatch, isolated_queue):
    monkeypatch.setattr(
        "routes.sync.load_config",
        lambda: {
            "WEBHOOK_TOKEN": "s3cret-token",
            "UI_LANG": "fr",
            "KAVITA_URL": "http://kavita.local",
            "KAVITA_API_KEY": "k",
        },
    )
    monkeypatch.setattr("services.batch_queue.cancel_queued_by_series", lambda sid: 0)
    monkeypatch.setattr(
        "services.background_tasks.broadcast_batch_progress",
        lambda *a, **k: None,
    )
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(sync_bp)
    return app.test_client()


def test_webhook_super_goes_front(webhook_client, isolated_queue):
    bg.put_sync(bg.make_sync_item(1, "A", False, is_batch=True))
    bg.put_sync(bg.make_sync_item(2, "B", False, is_batch=True))
    res = webhook_client.post(
        "/webhook",
        headers={"X-Webhook-Token": "s3cret-token"},
        json={"seriesId": 99, "name": "Super", "super_review": True, "force": True},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["priority"] is True
    assert body["super_review"] is True
    assert _drain_ids(isolated_queue) == [99, 1, 2]


def test_webhook_super_replaces_batch_pending(webhook_client, isolated_queue, monkeypatch):
    cancelled = []
    monkeypatch.setattr(
        "services.batch_queue.cancel_queued_by_series",
        lambda sid: cancelled.append(sid) or 1,
    )
    bg.register_batch_enqueue(2, new_batch=True)
    bg.put_sync(bg.make_sync_item(1, "A", False, is_batch=True))
    bg.put_sync(bg.make_sync_item(42, "Target", False, is_batch=True))
    res = webhook_client.post(
        "/webhook",
        headers={"X-Webhook-Token": "s3cret-token"},
        json={"seriesId": 42, "name": "Target", "super_review": True},
    )
    assert res.status_code == 200
    assert res.get_json()["replaced_pending"] == 1
    assert cancelled == [42]
    assert _drain_ids(isolated_queue) == [42, 1]


def test_webhook_plain_stays_fifo(webhook_client, isolated_queue):
    bg.put_sync(bg.make_sync_item(1, "A", False, is_batch=True))
    res = webhook_client.post(
        "/webhook",
        headers={"X-Webhook-Token": "s3cret-token"},
        json={"seriesId": 50, "name": "Plain", "force": True},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body.get("priority") is False
    assert body.get("replaced_pending") == 0
    assert _drain_ids(isolated_queue) == [1, 50]


def test_drain_keeps_companion_after_put_front(isolated_queue, monkeypatch):
    monkeypatch.setattr("services.batch_queue.cancel_queued_by_series", lambda sid: 0)
    monkeypatch.setattr(
        "services.background_tasks.broadcast_batch_progress",
        lambda *a, **k: None,
    )
    bg.register_batch_enqueue(2, new_batch=True)
    bg.put_sync(bg.make_sync_item(1, "A", False, is_batch=True))
    bg.put_front(bg.make_sync_item(99, "Companion", True, super_review=True))
    bg.put_sync(bg.make_sync_item(2, "B", False, is_batch=True))
    drained = bg.drain_sync_queue()
    assert drained == 2
    assert _drain_ids(isolated_queue) == [99]
