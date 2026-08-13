"""
Passe d'enrichissement par tome : thread, annulation, reprise.

Le choix structurant, testé ici : cette passe **ne passe pas par `sync_queue`**.
Cette file n'a qu'un worker, partagé par le webhook Kavita, l'auto-sync et le
bouton de chaque ligne ; y verser mille tomes gèlerait l'enrichissement série
pendant des heures.

La reprise s'appuie sur `volume_unit_cache` : sans elle, une passe interrompue
au tome 800 recommencerait au premier au redémarrage.
"""
from __future__ import annotations

import time

import pytest

from services.volume_enrichment import job


class FakeApi:
    def __init__(self, series, volumes=None, delay=0.0):
        self.series = series
        self.volumes = volumes or {}
        self.delay = delay
        self.written = []

    def get_all_series(self, library_id=None):
        return list(self.series)

    def get_series(self, sid):
        return next((s for s in self.series if s["id"] == sid), None)

    def get_library_type_for_series(self, sid):
        return "Comic"

    def get_series_volumes(self, sid):
        return self.volumes.get(sid, [])

    def get_chapter(self, chapter_id):
        return {"id": chapter_id}

    def update_chapter_metadata(self, dto):
        if self.delay:
            time.sleep(self.delay)
        self.written.append(dto)
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        return True, "ok"


def _volumes(series_id, count=2):
    return [
        {
            "id": 900 + n,
            "minNumber": n,
            "chapters": [{"id": series_id * 100 + n, "minNumber": n}],
        }
        for n in range(1, count + 1)
    ]


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Un environnement complet, sans réseau ni base partagée."""
    import db_manager

    monkeypatch.setattr(db_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "DB_FILE", str(tmp_path / "test.db"))
    db_manager.init_db()

    series = [{"id": 1, "name": "Saga"}, {"id": 2, "name": "Monstress"}]
    api = FakeApi(series, {1: _volumes(1), 2: _volumes(2)})

    monkeypatch.setattr(job, "load_config", lambda: {"KAVITA_URL": "u", "KAVITA_API_KEY": "k"})
    monkeypatch.setattr(job, "KavitaAPI", lambda url, key: api)
    monkeypatch.setattr(job, "get_all_cached_data", lambda: {})
    # On remplace les appels réseau, pas `resolve_index` : c'est lui qui décide
    # de compléter un index de couvertures par la cascade ISBN, et ce choix doit
    # rester couvert par les tests de la passe.
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index",
        lambda name, **kw: ("comicvine", {"1": {"summary": "Un"}, "2": {"summary": "Deux"}}),
    )
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_by_isbn", lambda units, **kw: {}
    )
    monkeypatch.setattr(job, "credits_fetcher", lambda pid: None)
    monkeypatch.setattr(job, "_emit", lambda *a, **kw: None)
    monkeypatch.setattr(job, "list_enriched_series_ids", db_manager.list_enriched_series_ids)
    return api, db_manager


def _wait_idle(timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not job.get_volume_enrich_state()["running"]:
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    with job._lock:
        job._state.update({"running": False, "cancelled": False, "done": 0, "total": 0})


def test_a_pass_writes_every_series(wired):
    api, _db = wired

    assert job.start_volume_enrich("all")["started"] is True
    assert _wait_idle(), "la passe doit se terminer"

    assert len(api.written) == 4
    assert job.get_volume_enrich_state()["counts"]["done"] == 4


def test_only_one_pass_at_a_time(wired):
    """Deux passes en parallèle doubleraient la charge fournisseur et
    s'écriraient l'une sur l'autre."""
    api, _db = wired
    api.delay = 0.05

    job.start_volume_enrich("all")
    second = job.start_volume_enrich("all")

    assert second["success"] is False
    assert second["busy"] is True
    _wait_idle()


def test_cancelling_stops_the_pass(wired):
    api, _db = wired
    api.delay = 0.08

    job.start_volume_enrich("all")
    time.sleep(0.05)
    result = job.cancel_volume_enrich()
    assert result["cancelled"] is True

    assert _wait_idle()
    assert len(api.written) < 4


def test_cancelling_when_nothing_runs_says_so():
    assert job.cancel_volume_enrich() == {"success": False, "running": False}


def test_a_second_pass_skips_the_series_already_done(wired):
    """C'est la reprise : sans elle, une passe interrompue au tome 800
    recommencerait au premier."""
    api, db = wired

    job.start_volume_enrich("all")
    assert _wait_idle()
    first_round = len(api.written)

    api.written.clear()
    job.start_volume_enrich("all")
    assert _wait_idle()

    assert first_round == 4
    assert api.written == [], "les séries déjà traitées ne doivent pas repartir"
    assert job.get_volume_enrich_state()["skipped"] == 2


def test_asking_for_a_series_explicitly_ignores_the_resume_filter(wired):
    """Relancer une série précise est une demande explicite : elle prime."""
    api, _db = wired

    job.start_volume_enrich("all")
    assert _wait_idle()
    api.written.clear()

    job.start_volume_enrich("all", series_ids=[1])
    assert _wait_idle()

    assert len(api.written) == 2


def test_a_selected_series_kavita_cannot_return_is_dropped_not_renamed(wired, monkeypatch):
    """La passe ne part plus que sur les séries cochées, ce qui fait de ce chemin
    le seul par lequel elle démarre — il n'était jamais emprunté auparavant.

    Une fiche absente était remplacée par `{"id": sid, "name": str(sid)}`, et ce
    `name` sert de titre à la recherche chez le fournisseur : chercher « 4242 »
    ramène soit rien, soit l'album d'une autre œuvre, écrit ensuite tome par tome.
    """
    api, _db = wired
    searched = []
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index",
        lambda name, **kw: (searched.append(name), ("comicvine", {}))[1],
    )

    job.start_volume_enrich("all", series_ids=[4242, 1])
    assert _wait_idle()

    assert "4242" not in searched, "un identifiant ne doit jamais servir de titre"
    assert searched == ["Saga"]
    state = job.get_volume_enrich_state()
    assert state["total"] == 1, "la série introuvable ne doit pas gonfler le total"
    assert state["counts"]["series_failed"] == 1


def test_a_series_that_explodes_does_not_stop_the_pass(wired, monkeypatch):
    api, _db = wired
    calls = {"n": 0}

    original = job.enrich_one_series

    def flaky(api_, series, **kwargs):
        calls["n"] += 1
        if series["id"] == 1:
            raise RuntimeError("fournisseur en vrac")
        return original(api_, series, **kwargs)

    monkeypatch.setattr(job, "enrich_one_series", flaky)

    job.start_volume_enrich("all")
    assert _wait_idle()

    assert calls["n"] == 2
    state = job.get_volume_enrich_state()
    # Une série, pas un tome : `failed` compte des unités, et mélanger les deux
    # faisait annoncer « 60 échecs » pour 60 séries représentant 240 tomes.
    assert state["counts"]["series_failed"] == 1
    assert state["counts"]["failed"] == 0
    assert state["done"] == 2


def test_a_series_no_provider_knows_is_counted_not_failed(wired, monkeypatch):
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index", lambda name, **kw: ("", {})
    )
    api, _db = wired

    job.start_volume_enrich("all", series_ids=[1])
    assert _wait_idle()

    state = job.get_volume_enrich_state()
    assert state["counts"]["failed"] == 0
    assert state["counts"]["nothing"] == 2


def test_the_isbn_path_takes_over_when_no_provider_lists_the_series(wired, monkeypatch):
    """Quand l'index de série est vide, chaque tome scanné qui porte un ISBN
    est encore identifiable."""
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index", lambda name, **kw: ("", {})
    )
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_by_isbn",
        lambda units, **kw: {"1": {"summary": "Par ISBN"}},
    )
    api, _db = wired

    job.start_volume_enrich("all", series_ids=[1])
    assert _wait_idle()

    assert len(api.written) == 1
    assert api.written[0]["summary"] == "Par ISBN"


def test_the_pass_never_touches_the_sync_queue(wired, monkeypatch):
    """`sync_queue` n'a qu'un worker, partagé avec le webhook et l'auto-sync."""
    import services.batch_queue as batch_queue

    for name in ("put", "put_front"):
        if hasattr(batch_queue, name):
            monkeypatch.setattr(
                batch_queue,
                name,
                lambda *a, **kw: pytest.fail("la passe tomes ne doit pas utiliser sync_queue"),
            )

    job.start_volume_enrich("all")
    assert _wait_idle()


def test_a_series_being_written_elsewhere_is_left_for_the_next_pass(wired):
    """La passe et l'enrichissement série écrivent tous deux dans Kavita. Le
    verrou par série de `enrichment_engine` existe parce que « l'un écraserait
    silencieusement le travail de l'autre » : la passe le respecte, et ne pose
    surtout pas la sentinelle sur une série qu'elle n'a pas traitée."""
    api, db = wired
    from services.enrichment_engine import _processing_lock, _processing_series_ids

    with _processing_lock:
        _processing_series_ids.add(1)
    try:
        job.start_volume_enrich("all")
        assert _wait_idle()
    finally:
        with _processing_lock:
            _processing_series_ids.discard(1)

    assert [d["id"] for d in api.written] == [201, 202], "seule la série 2 est écrite"
    assert db.list_enriched_series_ids() == {2}


def test_the_pass_releases_each_series_when_it_is_done(wired):
    api, _db = wired

    job.start_volume_enrich("all")
    assert _wait_idle()

    from services.enrichment_engine import _processing_series_ids

    assert not _processing_series_ids & {1, 2}


def test_the_state_is_readable_while_the_pass_runs(wired):
    api, _db = wired
    api.delay = 0.05

    job.start_volume_enrich("all")
    time.sleep(0.03)
    state = job.get_volume_enrich_state()

    assert state["running"] is True
    assert state["total"] == 2
    _wait_idle()
    assert job.get_volume_enrich_state()["running"] is False
