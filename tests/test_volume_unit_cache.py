"""
Cache d'état par unité (issue #27).

Sans lui, une passe de bibliothèque interrompue au tome 800 recommencerait au
tome 1 au redémarrage, et réinterrogerait les fournisseurs pour des unités déjà
écrites.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    import db_manager

    monkeypatch.setattr(db_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "DB_FILE", str(tmp_path / "test.db"))
    db_manager.init_db()
    return db_manager


def test_the_table_is_created_by_init_db(db):
    conn = db._connect()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='volume_unit_cache'"
    ).fetchall()
    conn.close()

    assert rows, "volume_unit_cache doit exister dès l'initialisation"


def test_a_written_unit_comes_back_with_its_fields(db):
    db.save_volume_unit_state(
        7,
        4242,
        "DONE",
        volume_id=77,
        volume_number="3",
        chapter_number="3",
        provider="comicvine",
        written_fields=["summary", "release_date"],
    )

    states = db.get_volume_unit_states(7)

    assert states[4242]["status"] == "DONE"
    assert states[4242]["provider"] == "comicvine"
    assert states[4242]["written_fields"] == ["summary", "release_date"]
    assert states[4242]["updated_at"]


def test_writing_the_same_unit_twice_updates_it(db):
    """Clé primaire (série, chapitre) : une seconde passe corrige, n'empile pas."""
    db.save_volume_unit_state(7, 4242, "FAILED")
    db.save_volume_unit_state(7, 4242, "DONE", written_fields=["summary"])

    states = db.get_volume_unit_states(7)

    assert len(states) == 1
    assert states[4242]["status"] == "DONE"


def test_units_of_another_series_are_not_returned(db):
    db.save_volume_unit_state(7, 1, "DONE")
    db.save_volume_unit_state(8, 2, "DONE")

    assert set(db.get_volume_unit_states(7)) == {1}


def test_counting_by_status(db):
    db.save_volume_unit_state(7, 1, "DONE")
    db.save_volume_unit_state(7, 2, "DONE")
    db.save_volume_unit_state(7, 3, "NOTHING_FOUND")
    db.save_volume_unit_state(8, 4, "FAILED")

    assert db.count_volume_units_by_status() == {
        "DONE": 2,
        "NOTHING_FOUND": 1,
        "FAILED": 1,
    }
    assert db.count_volume_units_by_status([7]) == {"DONE": 2, "NOTHING_FOUND": 1}


def test_the_resume_only_skips_series_gone_through_to_the_end(db):
    """La reprise se décide sur la série entière, pas sur une unité écrite.

    Une passe annulée au tome 3 sur 40 laisse trois unités en base. Les compter
    comme « série traitée » condamnerait les 37 tomes restants à ne jamais être
    écrits, et la reprise donnerait l'impression d'avoir fini alors qu'elle a
    surtout fini de regarder ailleurs.
    """
    db.save_volume_unit_state(7, 1, "DONE")
    db.mark_series_pass_done(7, provider="COMICVINE")

    db.save_volume_unit_state(8, 2, "DONE")  # interrompue en cours de route

    assert db.list_enriched_series_ids() == {7}


def test_a_series_the_providers_ignore_is_not_asked_again(db):
    """Une série que personne ne connaît est la plus chère : recherche complète
    puis échec. Le marqueur évite de la repayer à chaque passe."""
    db.mark_series_pass_done(9, provider="")

    assert 9 in db.list_enriched_series_ids()


def test_the_series_marker_never_shows_up_as_a_volume(db):
    """Le marqueur vit dans la même table que les unités : il ne doit apparaître
    ni dans les compteurs de la barre de progression, ni dans l'aperçu."""
    db.save_volume_unit_state(7, 1, "DONE")
    db.mark_series_pass_done(7, provider="COMICVINE")

    assert db.count_volume_units_by_status() == {"DONE": 1}
    assert db.count_volume_units_by_status([7]) == {"DONE": 1}
    assert set(db.get_volume_unit_states(7)) == {1}


def test_clearing_one_series_leaves_the_others(db):
    db.save_volume_unit_state(7, 1, "DONE")
    db.save_volume_unit_state(8, 2, "DONE")

    db.clear_volume_unit_states(7)

    assert db.get_volume_unit_states(7) == {}
    assert db.get_volume_unit_states(8)


def test_clearing_everything(db):
    db.save_volume_unit_state(7, 1, "DONE")
    db.save_volume_unit_state(8, 2, "DONE")

    db.clear_volume_unit_states()

    assert db.count_volume_units_by_status() == {}


def test_a_deleted_series_loses_its_unit_states_but_an_excluded_one_keeps_them(db):
    """`purge_series_hygiene_cache` sert aux deux cas : suppression réelle et
    simple exclusion de l'inventaire. Seule la première doit tout emporter."""
    db.save_volume_unit_state(7, 1, "DONE")
    db.save_volume_unit_state(8, 2, "DONE")

    db.purge_series_hygiene_cache(8, keep_overrides=True)
    assert db.get_volume_unit_states(8), "une exclusion n'est pas une suppression"

    db.purge_series_hygiene_cache(7)
    assert db.get_volume_unit_states(7) == {}


def test_reading_a_series_never_seen_returns_nothing(db):
    assert db.get_volume_unit_states(999) == {}


def test_the_migration_runs_on_a_database_created_before_the_feature(db, tmp_path):
    """Les bases existantes n'ont pas la table : elle doit apparaître sans
    perdre le reste."""
    conn = db._connect()
    conn.execute("DROP TABLE volume_unit_cache")
    conn.commit()
    conn.close()
    # Les migrations ne sont jouées qu'une fois par process : un process qui
    # ouvre une base d'avant la fonctionnalité part sans mémo, ce que ce
    # `DROP TABLE` en cours de route ne reproduit pas tout seul.
    db._schema_ready.clear()

    db.save_volume_unit_state(7, 1, "DONE")

    assert db.get_volume_unit_states(7)[1]["status"] == "DONE"
