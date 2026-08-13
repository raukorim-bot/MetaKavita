"""
Passe tomes : une série dont les tomes ont échoué doit revenir à la reprise.

La sentinelle de reprise (`volume_unit_cache`, `chapter_id = 0`) n'était posée
qu'en fonction de l'annulation : `counts["failed"]` n'était jamais consulté.
Kavita qui hoquette — scan en cours, redémarrage, 502 du reverse-proxy — fait
rendre `None` à `get_chapter()` ; `apply_entry` sort alors en `FAILED` sans
jamais lever, donc la série traversait l'incident, recevait sa sentinelle, et se
trouvait **définitivement** exclue de la reprise : relancer la passe affichait
« N séries déjà traitées » et les sautait. Aucune sortie de secours n'existait,
`clear_volume_unit_states` n'étant exposée par aucune route.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment import job


class _FakeApi:
    """Kavita indisponible le temps de la série : la lecture du tome rend None."""

    def __init__(self, *, chapter_read_ok=True):
        self.chapter_read_ok = chapter_read_ok
        self.written = []

    def get_library_type_for_series(self, series_id):
        return "Comic"

    def get_series_volumes(self, series_id):
        return [
            {"id": 900 + n, "minNumber": n,
             "chapters": [{"id": 100 + n, "minNumber": n}]}
            for n in (1, 2, 3)
        ]

    def get_chapter(self, chapter_id):
        return {"id": chapter_id} if self.chapter_read_ok else None

    def update_chapter_metadata(self, dto):
        self.written.append(dto)
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        return True, "ok"


@pytest.fixture
def db(monkeypatch, tmp_path):
    import db_manager

    monkeypatch.setattr(db_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "DB_FILE", str(tmp_path / "test.db"))
    db_manager.init_db()
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index",
        lambda name, **kw: ("comicvine", {str(n): {"summary": f"Tome {n}"} for n in (1, 2, 3)}),
    )
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_by_isbn", lambda units, **kw: {}
    )
    return db_manager


def _enrich(api, db):
    return job.enrich_one_series(api, {"id": 4242, "name": "Série de test"})


def test_a_series_whose_volumes_all_failed_is_not_marked_as_done(db):
    api = _FakeApi(chapter_read_ok=False)

    result = _enrich(api, db)

    assert result["counts"]["failed"] == 3
    assert db.list_enriched_series_ids() == set(), (
        "une série fermée sur un incident Kavita ne serait plus jamais retentée"
    )


def test_a_series_that_went_through_is_marked_as_done(db):
    api = _FakeApi()

    result = _enrich(api, db)

    assert result["counts"]["done"] == 3
    assert db.list_enriched_series_ids() == {4242}


def test_the_next_pass_retries_the_volumes_that_failed(db):
    failing = _FakeApi(chapter_read_ok=False)
    _enrich(failing, db)

    recovered = _FakeApi()
    result = _enrich(recovered, db)

    assert result["counts"]["done"] == 3
    assert len(recovered.written) == 3
    assert db.list_enriched_series_ids() == {4242}


def test_a_sentinel_already_written_by_a_previous_version_reopens_itself(db):
    """Les bases déjà marquées à tort doivent se rouvrir seules : la condition
    est aussi à la lecture, pas seulement à la pose de la sentinelle."""
    db.save_volume_unit_state(4242, 101, "FAILED")
    db.mark_series_pass_done(4242, provider="comicvine")

    assert db.list_enriched_series_ids() == set()


def test_an_empty_series_stays_closed(db):
    """Rien à écrire est un résultat, et il se retient : sans quoi la passe
    réinterrogerait un fournisseur à chaque tour pour une série vide."""
    api = _FakeApi()
    api.get_series_volumes = lambda series_id: []

    _enrich(api, db)

    assert db.list_enriched_series_ids() == {4242}
