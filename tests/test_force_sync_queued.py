"""
Non-régression : `/force-sync` (bouton « Sync » d'une ligne) met la série en file
et rend la main tout de suite.

L'enrichissement tournait auparavant DANS la requête HTTP : de quelques secondes
à plusieurs minutes (scrapers, écritures Kavita, parking en review manuelle)
pendant lesquelles le worker eventlet restait bloqué. Un reverse-proxy qui coupe
la connexion faisait alors afficher « Fail » sur un traitement réussi, et la
série tournait en parallèle du worker de fond au lieu d'être sérialisée avec lui.
"""
import queue

from flask import Flask

import services.background_tasks as bg
from routes.sync import sync_bp


def _client(monkeypatch):
    monkeypatch.setattr("routes.sync.load_config", lambda: {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "x",
        "UI_LANG": "fr",
    })
    monkeypatch.setattr(bg, "sync_queue", queue.Queue())
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sync_bp)
    return app.test_client()


def _drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def test_force_sync_enqueues_instead_of_enriching_in_the_request(monkeypatch, isolated_db):
    calls = []
    monkeypatch.setattr(
        "services.enrichment_engine.enrich_series",
        lambda *a, **k: calls.append(a) or (True, "ok", []),
    )
    client = _client(monkeypatch)

    res = client.post("/force-sync", data={"series_id": "42", "series_name": "One Piece"})

    assert res.status_code == 202, "202 : accepté, pas terminé"
    body = res.get_json()
    assert body["success"] is True and body["queued"] is True
    assert body["series_id"] == 42
    assert calls == [], "aucun enrichissement ne doit tourner dans la requête"

    items = _drain(bg.sync_queue)
    assert [(i["series_id"], i["series_name"]) for i in items] == [(42, "One Piece")]
    assert items[0]["force_update"] is True, "le bouton Sync force le retraitement"
    assert items[0]["is_batch"] is False, "ne doit pas compter dans la barre du batch"


def test_the_clicked_series_passes_in_front_of_a_running_batch(monkeypatch, isolated_db):
    client = _client(monkeypatch)
    bg.sync_queue.put(bg.make_sync_item(1, "Batch A", False, is_batch=True))
    bg.sync_queue.put(bg.make_sync_item(2, "Batch B", False, is_batch=True))

    res = client.post("/force-sync", data={"series_id": "42", "series_name": "Urgent"})

    assert res.status_code == 202
    assert [i["series_id"] for i in _drain(bg.sync_queue)] == [42, 1, 2]


def test_the_click_doubles_a_pending_batch_job_instead_of_dropping_it(monkeypatch, isolated_db):
    """Le clic ne retire pas le job batch de la même série : le lot garde sa
    composition, et le second passage saute une série déjà à jour."""
    client = _client(monkeypatch)
    bg.sync_queue.put(bg.make_sync_item(42, "Doublon", False, is_batch=True))
    bg.sync_queue.put(bg.make_sync_item(7, "Autre", False, is_batch=True))

    res = client.post("/force-sync", data={"series_id": "42", "series_name": "Urgent"})

    assert res.status_code == 202
    items = _drain(bg.sync_queue)
    assert [i["series_id"] for i in items] == [42, 42, 7], \
        "le job cliqué passe devant, celui du lot reste à sa place"
    assert items[0]["force_update"] is True and items[0]["is_batch"] is False
    assert items[1]["is_batch"] is True, "le job du lot doit rester compté dans la barre"


def test_a_paused_batch_keeps_the_series_it_had_queued(monkeypatch, isolated_db):
    """Le clic « Mettre à jour » traite la série tout de suite, il n'annule pas
    pour autant la file batch que l'utilisateur a constituée : une file en pause
    ne vit qu'en base, une ligne annulée là ne revient jamais."""
    from services import batch_queue as bq

    client = _client(monkeypatch)
    bq.enqueue_items([
        {"series_id": 42, "series_name": "Urgent", "force_update": False,
         "fields_override": None},
        {"series_id": 7, "series_name": "Autre", "force_update": False,
         "fields_override": None},
    ])
    bq.set_paused(True)

    res = client.post("/force-sync", data={"series_id": "42", "series_name": "Urgent"})

    assert res.status_code == 202
    still_queued = [i["series_id"] for i in bq.list_queued_for_hydrate()]
    assert still_queued == [42, 7], (
        "la série cliquée a disparu de la file batch en pause : elle ne sera "
        "jamais retraitée à la reprise"
    )


def test_missing_fields_are_refused_without_queueing(monkeypatch, isolated_db):
    client = _client(monkeypatch)

    res = client.post("/force-sync", data={"series_id": "42"})

    assert res.get_json()["success"] is False
    assert _drain(bg.sync_queue) == []


def test_a_non_numeric_series_id_is_refused(monkeypatch, isolated_db):
    client = _client(monkeypatch)

    res = client.post("/force-sync", data={"series_id": "abc", "series_name": "X"})

    assert res.status_code == 400
    assert res.get_json()["success"] is False
    assert _drain(bg.sync_queue) == []
