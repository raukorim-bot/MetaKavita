"""
Granularité batch : resolve_active_fields + enqueue targeted_fields override.
"""
from services.enrichment_engine import ALL_TARGETED_FIELDS, resolve_active_fields


def test_resolve_active_fields_defaults_and_override():
    assert resolve_active_fields("ALL") == list(ALL_TARGETED_FIELDS)
    assert resolve_active_fields(None) == list(ALL_TARGETED_FIELDS)
    assert resolve_active_fields("summary,cover") == ["summary", "cover"]
    assert resolve_active_fields("NONE") == []
    # Override batch prime sur le cache série
    assert resolve_active_fields("summary,cover,staff", override="summary") == ["summary"]
    assert resolve_active_fields("summary", override="ALL") == list(ALL_TARGETED_FIELDS)
    assert resolve_active_fields("ALL", override="NONE") == []


def test_batch_sync_enqueues_fields_override(monkeypatch, isolated_db):
    from flask import Flask
    from routes.sync import sync_bp
    import services.background_tasks as bg

    enqueued = []
    bg.set_batch_enqueue_enabled(True)

    class FakeQueue:
        def qsize(self):
            return len(enqueued)

        def put(self, item):
            enqueued.append(item)

    class FakeKavita:
        def __init__(self, *a, **k):
            pass

        def authenticate(self):
            return True

        def get_all_series(self, library_id=None):
            return [{"id": 10, "name": "One Piece"}, {"id": 11, "name": "Naruto"}]

    monkeypatch.setattr("routes.sync.KavitaAPI", FakeKavita)
    monkeypatch.setattr("routes.sync.load_config", lambda: {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "x",
        "UI_LANG": "fr",
    })
    fake_q = FakeQueue()
    monkeypatch.setattr(bg, "sync_queue", fake_q)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sync_bp)
    client = app.test_client()

    res = client.post(
        "/batch-sync",
        data={
            "selected_series": ["10"],
            "targeted_fields": "summary,alt_titles",
            "force_update": "true",
            "resume_enqueue": "true",
        },
    )
    assert res.status_code == 200
    assert res.get_json()["success"] is True
    assert len(enqueued) == 1
    assert enqueued[0] == {
        "series_id": 10,
        "series_name": "One Piece",
        "force_update": True,
        "fields_override": "summary,alt_titles",
        "is_batch": True,
        "super_review": False,
        "force_auto": False,
    }


def test_batch_sync_no_override_when_all(monkeypatch, isolated_db):
    from flask import Flask
    from routes.sync import sync_bp
    import services.background_tasks as bg

    enqueued = []
    bg.set_batch_enqueue_enabled(True)

    class FakeQueue:
        def qsize(self):
            return 0

        def put(self, item):
            enqueued.append(item)

    class FakeKavita:
        def __init__(self, *a, **k):
            pass

        def authenticate(self):
            return True

        def get_all_series(self, library_id=None):
            return [
                {"id": 10, "name": "One Piece"},
                {"id": 11, "name": "Naruto"},
            ]

    monkeypatch.setattr("routes.sync.KavitaAPI", FakeKavita)
    monkeypatch.setattr("routes.sync.load_config", lambda: {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "x",
        "UI_LANG": "fr",
    })
    fake_q = FakeQueue()
    monkeypatch.setattr(bg, "sync_queue", fake_q)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sync_bp)
    client = app.test_client()

    expected_10 = {
        "series_id": 10,
        "series_name": "One Piece",
        "force_update": False,
        "fields_override": None,
        "is_batch": True,
        "super_review": False,
        "force_auto": False,
    }
    expected_11 = {
        "series_id": 11,
        "series_name": "Naruto",
        "force_update": False,
        "fields_override": None,
        "is_batch": True,
        "super_review": False,
        "force_auto": False,
    }

    # Pas de targeted_fields → fields_override=None
    res = client.post(
        "/batch-sync",
        data={"selected_series": ["10"], "resume_enqueue": "true"},
    )
    assert res.status_code == 200
    assert enqueued[0] == expected_10

    # Autre série : C63 refuse le doublon SQLite sur le même series_id.
    enqueued.clear()
    res = client.post(
        "/batch-sync",
        data={"selected_series": ["11"], "targeted_fields": "ALL"},
    )
    assert res.status_code == 200
    assert enqueued[0] == expected_11


def test_stop_batch_rejects_late_chunks(monkeypatch, isolated_db):
    """Après Stop, les paquets /batch-sync encore en vol ne doivent plus remplir la file."""
    from flask import Flask
    from routes.sync import sync_bp
    import services.background_tasks as bg

    enqueued = []

    class FakeQueue:
        def qsize(self):
            return len(enqueued)

        def put(self, item):
            enqueued.append(item)

        def empty(self):
            return len(enqueued) == 0

        def get_nowait(self):
            if not enqueued:
                raise bg.queue.Empty()
            return enqueued.pop(0)

        def task_done(self):
            pass

    class FakeKavita:
        def __init__(self, *a, **k):
            pass

        def authenticate(self):
            return True

        def get_all_series(self, library_id=None):
            return [{"id": 10, "name": "One Piece"}, {"id": 11, "name": "Naruto"}]

    monkeypatch.setattr("routes.sync.KavitaAPI", FakeKavita)
    monkeypatch.setattr("routes.sync.load_config", lambda: {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "x",
        "UI_LANG": "fr",
    })
    fake_q = FakeQueue()
    monkeypatch.setattr(bg, "sync_queue", fake_q)
    bg.set_batch_enqueue_enabled(True)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sync_bp)
    client = app.test_client()

    assert client.post(
        "/batch-sync",
        data={"selected_series": ["10"], "resume_enqueue": "true"},
    ).status_code == 200
    assert len(enqueued) == 1

    stop = client.post("/stop-batch")
    assert stop.status_code == 200
    assert stop.get_json()["success"] is True
    assert bg.is_batch_enqueue_enabled() is False
    assert len(enqueued) == 0

    late = client.post("/batch-sync", data={"selected_series": ["11"]})
    assert late.status_code == 409
    assert late.get_json().get("rejected") is True
    assert len(enqueued) == 0

    # Nouveau batch : premier paquet réarme
    resume = client.post(
        "/batch-sync",
        data={"selected_series": ["11"], "resume_enqueue": "true"},
    )
    assert resume.status_code == 200
    assert bg.is_batch_enqueue_enabled() is True
    assert enqueued == [{
        "series_id": 11,
        "series_name": "Naruto",
        "force_update": False,
        "fields_override": None,
        "is_batch": True,
        "super_review": False,
        "force_auto": False,
    }]
