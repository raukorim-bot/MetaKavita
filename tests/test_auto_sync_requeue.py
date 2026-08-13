"""
Polling auto-sync : un tick ne doit pas réenfiler ce qui attend déjà.

Le critère de candidature est « absente du cache, ou `status == 'PENDING'` », et
ce statut ne change qu'une fois la série traitée par le worker unique. Un tick
ne regardait ni `sync_queue` ni ce que le tick précédent avait empilé : avec
l'intervalle que pose l'assistant d'installation (six heures) et plusieurs
milliers de séries, le backlog dépasse l'intervalle et TOUT repartait à chaque
tour. `sync_queue` est une `queue.Queue` en RAM non bornée ; chaque doublon
coûtait une authentification et un `get_series_metadata` pour finir sur « Déjà à
jour », mais surtout il passait devant tout ce que l'utilisateur enfilerait
ensuite — et « Stop » ne retire que les items de lot, donc rien dans l'interface
ne permettait de purger ces fantômes.
"""
from __future__ import annotations

import pytest

import services.background_tasks as bg
from translations import translations

SERIES = [{"id": i, "name": f"Série {i}", "libraryId": 1} for i in range(1, 201)]


class _FakeKavita:
    def __init__(self, *args, **kwargs):
        self.last_inventory_complete = True

    def authenticate(self):
        return True

    def get_all_series(self, library_id=None):
        return list(SERIES)


@pytest.fixture
def ticking(monkeypatch):
    """Un tick auto-sync sans réseau, sans base, sur une file RAM vide."""
    _drain_ram()
    monkeypatch.setattr(bg, "KavitaAPI", _FakeKavita)
    monkeypatch.setattr(bg, "clean_orphaned_cache", lambda ids: 0)
    # Aucune série en cache : toutes sont candidates, comme au premier
    # démarrage — c'est le cas où le backlog dépasse l'intervalle.
    monkeypatch.setattr(bg, "get_all_cached_data", lambda: {})
    config = {"UI_LANG": "fr", "AUTO_SYNC_INTERVAL": 360}
    yield config, translations["fr"]
    _drain_ram()


def _drain_ram():
    while True:
        try:
            bg.sync_queue.get_nowait()
        except Exception:
            break


def test_three_ticks_in_a_row_enqueue_each_series_only_once(ticking):
    config, t = ticking

    first = bg._auto_sync_tick(config, t)
    second = bg._auto_sync_tick(config, t)
    third = bg._auto_sync_tick(config, t)

    assert (first, second, third) == (200, 0, 0)
    assert bg.sync_queue.qsize() == 200, "600 items pour 200 séries noieraient la file"


def test_a_series_the_user_queued_himself_is_not_doubled_by_the_next_tick(ticking):
    """Le clic « Mettre à jour » et le webhook partagent cette file : la série
    qu'ils viennent d'y mettre n'a pas besoin d'un second passage."""
    config, t = ticking
    bg.put_sync(bg.make_sync_item(42, "Série 42", True))

    enqueued = bg._auto_sync_tick(config, t)

    assert enqueued == 199
    ids = []
    while not bg.sync_queue.empty():
        ids.append(bg.sync_queue.get_nowait()["series_id"])
    assert ids.count(42) == 1


def test_a_series_that_left_the_queue_can_be_picked_up_again(ticking):
    """Le filtre porte sur ce qui attend, pas sur ce qui est déjà passé : une
    série restée `PENDING` après un échec doit pouvoir être retentée."""
    config, t = ticking

    assert bg._auto_sync_tick(config, t) == 200
    _drain_ram()

    assert bg._auto_sync_tick(config, t) == 200


def test_a_queue_that_cannot_be_inspected_keeps_the_old_behaviour(ticking, monkeypatch):
    """Le filtre lit la file elle-même. Un double de test qui ne sait pas
    s'inspecter ne doit pas faire disparaître les candidates."""
    config, t = ticking

    class _Opaque:
        def __init__(self):
            self.items = []

        def put(self, item):
            self.items.append(item)

    opaque = _Opaque()
    monkeypatch.setattr(bg, "sync_queue", opaque)

    assert bg._auto_sync_tick(config, t) == 200
    assert len(opaque.items) == 200
