"""
Deux lancements de lot qui s'entrelacent : la barre ne doit pas se croire finie.

Sous eventlet, tout appel réseau ou I/O rend la main au greenlet suivant. Entre
le moment où `/batch-sync` lit « un lot tourne-t-il déjà ? » et celui où il
enregistre ses séries, le handler rend la main quatre fois : authentification
Kavita, inventaire, lecture du cache, écriture de la file SQLite. Deux onglets,
ou un double-clic sur « Lancer », lisaient donc tous les deux « aucun lot en
cours », et le second remettait `_batch_total` / `_batch_done` /
`_batch_real_sends` à zéro EN PLEIN MILIEU du premier. Comme `_batch_done` est
plafonné par `_batch_total`, la barre atteignait la fin à la moitié du lot :
l'UI recevait `remaining: 0`, la barre disparaissait, et l'utilisateur pouvait
fermer l'onglet ou éteindre le conteneur pendant que la seconde moitié des
séries s'écrivait encore vers Kavita.

La fenêtre d'entrelacement est fabriquée ici en instrumentant la fonction qui
rend la main — c'est exactement ce que fait eventlet.

Second sujet du fichier, même famille : « Reprendre » hydrate la file SQLite
sans regarder ce qui est déjà en RAM, et la route l'appelle sans condition.
"""
from __future__ import annotations

import threading

import pytest
from flask import Flask

import services.background_tasks as bg
import services.batch_queue as bq
from routes.sync import sync_bp

TAB_A = [str(i) for i in range(1, 11)]
TAB_B = [str(i) for i in range(11, 21)]


class _FakeKavita:
    """`authenticate()` est le premier endroit où le handler rend la main."""

    hooks: list = []

    def __init__(self, *args, **kwargs):
        pass

    def authenticate(self):
        while self.hooks:
            self.hooks.pop(0)()
        return True

    def get_all_series(self, library_id=None):
        return [{"id": i, "name": f"Série {i}"} for i in range(1, 21)]


@pytest.fixture
def client(monkeypatch, isolated_db):
    _drain_ram()
    _FakeKavita.hooks = []
    monkeypatch.setattr("routes.sync.KavitaAPI", _FakeKavita)
    monkeypatch.setattr(
        "routes.sync.load_config",
        lambda: {"KAVITA_URL": "http://kavita.test", "KAVITA_API_KEY": "k", "UI_LANG": "fr"},
    )
    bq.set_paused(False)
    bg.set_batch_enqueue_enabled(True)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sync_bp)
    yield app.test_client()

    _FakeKavita.hooks = []
    _drain_ram()


def _drain_ram():
    """La file RAM est un global de module partagé par toute la suite."""
    while True:
        try:
            bg.sync_queue.get_nowait()
        except Exception:
            break


def _launch(client, selection):
    return client.post(
        "/batch-sync",
        data={"selected_series": selection, "resume_enqueue": "true"},
    )


def test_a_second_launch_inside_the_window_adds_up_instead_of_resetting(client):
    """Le second onglet poste pendant que le premier attend Kavita : ses séries
    doivent s'ajouter au lot en cours, pas en redémarrer le décompte."""
    posted = []

    def second_tab():
        posted.append(_launch(client, TAB_B).status_code)

    _FakeKavita.hooks = [second_tab]

    assert _launch(client, TAB_A).status_code == 200
    assert posted == [200], "le second onglet doit avoir posté dans la fenêtre"

    with bg._batch_progress_lock:
        assert bg._batch_total == 20, "les deux paquets comptent pour un seul lot"
        assert bg._batch_done == 0, "aucune série n'a encore été traitée"


def test_the_finish_signal_waits_for_the_last_series_of_both_launches(client, mocker):
    """Le symptôme visible : avec des compteurs remis à zéro à mi-parcours, la
    barre annonçait `remaining: 0` — et le nagware son `real_sends` — dès la
    dixième série sur vingt, puis à chacune des suivantes."""
    _FakeKavita.hooks = [lambda: _launch(client, TAB_B)]
    assert _launch(client, TAB_A).status_code == 200

    mocker.patch("services.background_tasks.enrich_series", return_value=(True, "Succès", []))
    mocker.patch("services.background_tasks.load_config", return_value={"UI_LANG": "fr"})
    calls = []
    mocker.patch(
        "services.background_tasks.broadcast_batch_progress",
        side_effect=lambda *a, **k: calls.append((a, k)),
    )

    bg.sync_queue.put(None)
    bg._worker()

    finished = [c for c in calls if "real_sends" in c[1]]
    assert len(finished) == 1, "un seul signal de fin, à la vingtième série"
    assert finished[0] == ((0,), {"real_sends": 20})
    assert calls.index(finished[0]) == len(calls) - 1


def test_a_packet_that_is_not_the_first_never_restarts_the_count(client):
    """Les paquets suivants (`resume_enqueue` absent) s'additionnent : c'est le
    découpage en paquets de cinquante côté UI, pas un nouveau lot."""
    assert _launch(client, TAB_A).status_code == 200

    res = client.post("/batch-sync", data={"selected_series": TAB_B})

    assert res.status_code == 200
    with bg._batch_progress_lock:
        assert bg._batch_total == 20


def test_a_launch_after_the_previous_batch_finished_starts_from_zero(client):
    """Le lot précédent est soldé : le nouveau doit repartir de zéro, sinon la
    barre attendrait des séries déjà traitées."""
    assert _launch(client, TAB_A).status_code == 200
    with bg._batch_progress_lock:
        bg._batch_done = bg._batch_total
    _drain_ram()

    assert _launch(client, TAB_B).status_code == 200

    with bg._batch_progress_lock:
        assert bg._batch_total == 10
        assert bg._batch_done == 0


# ===== « Reprendre » =====


@pytest.fixture
def queued(isolated_db):
    """Trois séries en attente dans la file SQLite, rien en RAM."""
    _drain_ram()
    bq.set_paused(False)
    bq.cancel_all_pending()
    bq.enqueue_items([
        {"series_id": 1, "series_name": "Saga"},
        {"series_id": 2, "series_name": "Monstress"},
        {"series_id": 3, "series_name": "Bone"},
    ])
    yield bq
    _drain_ram()
    bq.cancel_all_pending()


def test_clicking_resume_twice_does_not_queue_every_series_twice(queued):
    """La route de reprise hydrate sans condition : un double-clic empilait deux
    fois chaque série — deux enrichissements pour une — et doublait
    `_batch_total`, si bien que la barre attendait des séries inexistantes."""
    assert bg.hydrate_batch_queue_to_ram() == 3
    assert bg.hydrate_batch_queue_to_ram() == 0

    assert bg.sync_queue.qsize() == 3
    with bg._batch_progress_lock:
        assert bg._batch_total == 3


def test_two_resumes_at_the_same_time_hydrate_each_series_once(queued, monkeypatch):
    """La fenêtre : les deux appels lisent les mêmes lignes `queued` avant que
    l'un des deux ne les ait poussées en RAM. La lecture, le filtrage et
    l'empilement tiennent donc dans la même section critique."""
    original = bq.list_queued_for_hydrate
    reading = threading.Event()
    resume = threading.Event()
    first = {"done": False}

    def slow_read():
        if not first["done"]:
            first["done"] = True
            reading.set()
            resume.wait(5)
        return original()

    monkeypatch.setattr(bq, "list_queued_for_hydrate", slow_read)

    results = {}
    threads = [
        threading.Thread(target=lambda k=k: results.__setitem__(k, bg.hydrate_batch_queue_to_ram()))
        for k in ("a", "b")
    ]
    threads[0].start()
    assert reading.wait(5), "le premier hydrate doit être entré dans sa lecture"
    threads[1].start()
    resume.set()
    for t in threads:
        t.join(5)

    assert sorted(results.values()) == [0, 3]
    assert bg.sync_queue.qsize() == 3
    with bg._batch_progress_lock:
        assert bg._batch_total == 3


def test_the_boot_hydrate_still_opens_a_fresh_batch(queued):
    """Au démarrage du process il n'y a rien à ménager : le lot repart à zéro
    (voir `start_background_workers`)."""
    with bg._batch_progress_lock:
        bg._batch_total = 99
        bg._batch_done = 40

    assert bg.hydrate_batch_queue_to_ram(new_batch=True) == 3

    with bg._batch_progress_lock:
        assert bg._batch_total == 3
        assert bg._batch_done == 0
