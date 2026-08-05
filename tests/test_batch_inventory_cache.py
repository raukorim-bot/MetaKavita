"""
/batch-sync ne doit refaire un appel complet à `get_all_series()` qu'au premier
paquet d'un batch (`resume_enqueue=true`) ; les paquets suivants réutilisent
l'instantané pris à ce moment-là (voir `routes/sync.py::_get_batch_inventory`).
"""
from flask import Flask

from routes.sync import sync_bp
import services.background_tasks as bg


def _build_app(monkeypatch, get_all_series_calls, series):
    class FakeQueue:
        def __init__(self):
            self.items = []

        def qsize(self):
            return len(self.items)

        def put(self, item):
            self.items.append(item)

        def empty(self):
            return len(self.items) == 0

        def get_nowait(self):
            if not self.items:
                raise bg.queue.Empty()
            return self.items.pop(0)

        def task_done(self):
            pass

    class FakeKavita:
        # url/api_key réels (pas juste `pass`) : la clé du cache en dépend.
        def __init__(self, url, api_key, *a, **k):
            self.url = url
            self.api_key = api_key

        def authenticate(self):
            return True

        def get_all_series(self, library_id=None):
            get_all_series_calls.append(library_id)
            return series

    monkeypatch.setattr("routes.sync.KavitaAPI", FakeKavita)
    monkeypatch.setattr("routes.sync.load_config", lambda: {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "x",
        "UI_LANG": "fr",
    })
    fake_q = FakeQueue()
    # sync_queue vit dans background_tasks (put_sync) — plus dans routes.sync.
    monkeypatch.setattr(bg, "sync_queue", fake_q)
    bg.set_batch_enqueue_enabled(True)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sync_bp)
    return app.test_client(), fake_q


def test_only_the_first_packet_of_a_batch_refetches_the_inventory(monkeypatch, isolated_db):
    calls = []
    series = [
        {"id": 10, "name": "One Piece"},
        {"id": 11, "name": "Naruto"},
        {"id": 12, "name": "Bleach"},
    ]
    client, fake_q = _build_app(monkeypatch, calls, series)

    # Paquet 1/3 : nouveau batch, doit aller chercher l'inventaire.
    res = client.post("/batch-sync", data={"selected_series": ["10"], "resume_enqueue": "true"})
    assert res.status_code == 200
    assert len(calls) == 1

    # Paquets 2 et 3 : même batch, IDs distincts (C63 déduplique sinon), aucun nouvel appel réseau.
    for sid in ("11", "12"):
        res = client.post("/batch-sync", data={"selected_series": [sid]})
        assert res.status_code == 200
    assert len(calls) == 1, "les paquets suivants doivent réutiliser l'instantané du 1er paquet"
    assert len(fake_q.items) == 3


def test_a_new_batch_forces_a_fresh_inventory(monkeypatch, isolated_db):
    calls = []
    series = [{"id": 10, "name": "One Piece"}]
    client, _fake_q = _build_app(monkeypatch, calls, series)

    client.post("/batch-sync", data={"selected_series": ["10"], "resume_enqueue": "true"})
    client.post("/stop-batch")
    # Nouveau batch : resume_enqueue=true doit forcer un inventaire frais, pas
    # servir un instantané potentiellement périmé par le batch précédent.
    client.post("/batch-sync", data={"selected_series": ["10"], "resume_enqueue": "true"})

    assert len(calls) == 2


def test_a_second_resume_enqueue_appends_without_resetting_progress(monkeypatch, isolated_db):
    """C63 : un second `resume_enqueue=true` (autre onglet / nouvel ajout) append
    pendant qu'un batch tourne. `new_batch=False` : les compteurs s'accumulent,
    ils ne sont pas remis à zéro (régression ex-409 already_running)."""
    calls = []
    series = [{"id": 10, "name": "One Piece"}, {"id": 11, "name": "Naruto"}]
    client, fake_q = _build_app(monkeypatch, calls, series)

    res1 = client.post("/batch-sync", data={"selected_series": ["10"], "resume_enqueue": "true"})
    assert res1.status_code == 200
    with bg._batch_progress_lock:
        assert bg._batch_total == 1

    res2 = client.post("/batch-sync", data={"selected_series": ["11"], "resume_enqueue": "true"})
    assert res2.status_code == 200
    assert res2.get_json()["added"] == 1

    with bg._batch_progress_lock:
        assert bg._batch_total == 2
        assert bg._batch_done == 0
    assert len(fake_q.items) == 2


def test_a_new_batch_is_accepted_once_the_previous_one_is_done(monkeypatch, isolated_db):
    calls = []
    series = [{"id": 10, "name": "One Piece"}]
    client, _fake_q = _build_app(monkeypatch, calls, series)

    client.post("/batch-sync", data={"selected_series": ["10"], "resume_enqueue": "true"})
    with bg._batch_progress_lock:
        bg._batch_done = bg._batch_total  # simule un batch entièrement traité par _worker()

    res = client.post("/batch-sync", data={"selected_series": ["10"], "resume_enqueue": "true"})
    assert res.status_code == 200


def test_inventory_cache_is_scoped_per_kavita_instance(monkeypatch, isolated_db):
    """Deux batchs ciblant des URL/clé Kavita différentes ne doivent jamais
    partager le même instantané en cache."""
    from routes.sync import _get_batch_inventory

    calls = []

    class FakeKavita:
        def __init__(self, url, api_key):
            self.url = url
            self.api_key = api_key

        def get_all_series(self, library_id=None):
            calls.append((self.url, library_id))
            return [{"id": 1, "name": f"Series-{self.url}"}]

    a = FakeKavita("http://kavita-a.local", "key-a")
    b = FakeKavita("http://kavita-b.local", "key-b")

    result_a = _get_batch_inventory(a, None, force_refresh=True)
    result_b = _get_batch_inventory(b, None, force_refresh=True)

    assert result_a[0]["name"] == "Series-http://kavita-a.local"
    assert result_b[0]["name"] == "Series-http://kavita-b.local"
    assert len(calls) == 2
