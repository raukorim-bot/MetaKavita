"""
Reprise à la maille de l'unité, compteurs, et point de bascule de la passe.

Trois constats de mise en charge, tous sur la même passe :

* la reprise ne se faisait qu'à la maille **série** (ligne sentinelle
  `SERIES_DONE`) : `enrich_one_series` n'a jamais lu `get_volume_unit_states`,
  que seule la route d'aperçu consultait. Annulation à l'unité 135 d'une série
  de 300 tomes, puis reprise : l'index du fournisseur était réinterrogé pour la
  série entière et les 300 unités replanifiées, donc relues une par une chez
  Kavita. Rien n'était réécrit, mais uniquement parce que la politique « on ne
  comble que les vides » rattrapait le coup — avec `VOLUME_FORCE_OVERWRITE` et
  un fournisseur HTML dont le texte varie d'une visite à l'autre, tout repartait
  en écriture ;
* `totals["failed"]` recevait un point par **série** qui lève, dans un compteur
  dont les trois autres cases comptent des **unités** : 60 séries en échec
  affichaient « 60 échecs » pour 240 tomes, et le total ne se réconciliait plus ;
* la boucle de séries et la boucle d'unités ne rendaient jamais la main. Sous le
  worker eventlet unique, la passe rendait l'interface muette — d'autant plus
  que Kavita répond vite, puisque c'est le seul endroit où elle basculait.
"""
from __future__ import annotations

import time

import pytest

from services.volume_enrichment import apply as apply_mod
from services.volume_enrichment import job

VOLUME_COUNT = 300
CANCEL_AT = 135


class _Api:
    """Kavita en mémoire, qui retient chaque lecture de chapitre."""

    def __init__(self, count=VOLUME_COUNT):
        self.volumes = [
            {"id": 900 + n, "minNumber": n, "chapters": [{"id": 1000 + n, "minNumber": n}]}
            for n in range(1, count + 1)
        ]
        self.read = []
        self.written = []

    def get_all_series(self, library_id=None):
        return [{"id": 42, "name": "Série fleuve"}]

    def get_series(self, sid):
        return {"id": 42, "name": "Série fleuve"}

    def get_library_type_for_series(self, sid):
        return "Comic"

    def get_series_volumes(self, sid):
        return self.volumes

    def get_chapter(self, chapter_id):
        self.read.append(chapter_id)
        return {"id": chapter_id}

    def update_chapter_metadata(self, dto):
        self.written.append(dto["id"])
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        return True, "ok"


@pytest.fixture
def db(monkeypatch, tmp_path):
    import db_manager

    monkeypatch.setattr(db_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "DB_FILE", str(tmp_path / "test.db"))
    db_manager.init_db()
    return db_manager


@pytest.fixture
def provider(monkeypatch):
    """Index complet, qui compte combien de fois le fournisseur est interrogé."""
    calls = {"n": 0}
    index = {str(n): {"summary": f"Tome {n}"} for n in range(1, VOLUME_COUNT + 1)}

    def fetch_index(name, **kwargs):
        calls["n"] += 1
        return "comicvine", dict(index)

    monkeypatch.setattr("services.volume_enrichment.providers.fetch_index", fetch_index)
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_by_isbn", lambda units, **kw: {}
    )
    return calls


SERIES = {"id": 42, "name": "Série fleuve"}


# --- Reprise à la maille de l'unité ------------------------------------------


def test_a_pass_resumed_after_a_cancellation_does_not_replan_what_is_done(db, provider):
    interrupted = _Api()
    job.enrich_one_series(
        interrupted,
        SERIES,
        should_cancel=lambda: len(interrupted.written) >= CANCEL_AT,
    )
    assert len(interrupted.written) == CANCEL_AT

    resumed = _Api()
    result = job.enrich_one_series(resumed, SERIES, resume=True)

    assert result["counts"]["resumed"] == CANCEL_AT
    assert len(resumed.read) == VOLUME_COUNT - CANCEL_AT, (
        "les unités déjà faites ne doivent pas être relues chez Kavita"
    )
    assert not set(resumed.read) & set(interrupted.written)


def test_a_series_whose_units_are_all_settled_costs_no_provider_call(db, provider):
    api = _Api()
    job.enrich_one_series(api, SERIES)
    assert provider["n"] == 1

    again = _Api()
    result = job.enrich_one_series(again, SERIES, resume=True)

    assert provider["n"] == 1, "le coût fournisseur ne doit pas être payé deux fois"
    assert again.read == []
    assert result["counts"]["resumed"] == VOLUME_COUNT


def test_a_unit_that_failed_comes_back_to_the_resumed_pass(db, provider):
    """`FAILED` n'est pas un verdict : c'est ce qu'une reprise doit retenter."""
    api = _Api()
    job.enrich_one_series(api, SERIES)
    db.save_volume_unit_state(42, 1007, "FAILED")

    again = _Api()
    result = job.enrich_one_series(again, SERIES, resume=True)

    assert again.read == [1007]
    assert result["counts"]["resumed"] == VOLUME_COUNT - 1


def test_without_resume_the_whole_series_is_replanned(db, provider):
    """`resume=False` est une demande explicite de tout refaire — c'est déjà ce
    que fait la relance d'une série nommée depuis l'interface."""
    api = _Api()
    job.enrich_one_series(api, SERIES)

    again = _Api()
    job.enrich_one_series(again, SERIES, resume=False)

    assert len(again.read) == VOLUME_COUNT


def test_a_series_kavita_cannot_read_is_not_closed(db, provider):
    """`get_series_volumes` rend `[]` pour une série vide comme pour un Kavita
    muet : la confondre faisait marquer « traitée » une série traversée pendant
    une coupure, donc écartée de toutes les passes suivantes."""
    api = _Api()
    api.volumes = []  # ce que l'ancienne méthode rend d'une coupure : rien
    api.fetch_series_volumes = lambda sid: (None, "kavita_unreachable")

    result = job.enrich_one_series(api, SERIES)

    assert db.list_enriched_series_ids() == set()
    assert result["counts"]["series_failed"] == 1
    assert provider["n"] == 0


def test_a_truly_empty_series_is_still_closed(db, provider):
    """La contrepartie : une série réellement vide reste close, sinon la passe
    réinterroge un fournisseur à chaque tour pour rien."""
    api = _Api()
    api.fetch_series_volumes = lambda sid: ([], None)

    job.enrich_one_series(api, SERIES)

    assert db.list_enriched_series_ids() == {42}


# --- Compteurs ---------------------------------------------------------------


def _wait_idle(timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not job.get_volume_enrich_state()["running"]:
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def wired(monkeypatch, db, provider):
    api = _Api(count=4)
    monkeypatch.setattr(job, "load_config", lambda: {"KAVITA_URL": "u", "KAVITA_API_KEY": "k"})
    monkeypatch.setattr(job, "KavitaAPI", lambda url, key: api)
    monkeypatch.setattr(job, "get_all_cached_data", lambda: {})
    monkeypatch.setattr(job, "credits_fetcher", lambda pid: None)
    monkeypatch.setattr(job, "_emit", lambda *a, **kw: None)
    monkeypatch.setattr(job, "list_enriched_series_ids", db.list_enriched_series_ids)
    yield api
    with job._lock:
        job._state.update({"running": False, "cancelled": False, "was_cancelled": False})


def test_a_series_that_explodes_is_not_counted_as_a_failed_volume(wired, monkeypatch):
    """Un point pour une série dans un compteur d'unités : l'écran annonçait
    « 60 échecs » sans qu'on sache s'il s'agissait de tomes ou de séries."""
    monkeypatch.setattr(
        job, "enrich_one_series", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boum"))
    )

    job.start_volume_enrich("all")
    assert _wait_idle()

    counts = job.get_volume_enrich_state()["counts"]
    assert counts["series_failed"] == 1
    assert counts["failed"] == 0, "aucune unité n'a échoué : la série n'a pas démarré"


def test_a_cancelled_pass_does_not_stay_cancelled_forever(wired):
    """`/api/volume-enrich/status` rendait `running=false, cancelled=true`
    jusqu'au démarrage suivant."""
    job.start_volume_enrich("all")
    job.cancel_volume_enrich()
    assert _wait_idle()

    state = job.get_volume_enrich_state()
    assert state["running"] is False
    assert state["cancelled"] is False
    assert state["was_cancelled"] is True


def test_a_pass_that_went_through_was_not_cancelled(wired):
    job.start_volume_enrich("all")
    assert _wait_idle()

    assert job.get_volume_enrich_state()["was_cancelled"] is False


# --- Points de bascule -------------------------------------------------------


def test_the_unit_loop_hands_the_worker_back_between_two_volumes(db, provider, monkeypatch):
    yields = {"n": 0}
    monkeypatch.setattr(
        apply_mod, "yield_to_worker", lambda: yields.__setitem__("n", yields["n"] + 1)
    )
    api = _Api(count=12)

    job.enrich_one_series(api, SERIES)

    assert yields["n"] >= 12


def test_the_series_loop_hands_the_worker_back_too(wired, monkeypatch):
    yields = {"n": 0}
    monkeypatch.setattr(
        job, "yield_to_worker", lambda: yields.__setitem__("n", yields["n"] + 1)
    )

    job.start_volume_enrich("all")
    assert _wait_idle()

    assert yields["n"] >= 1
