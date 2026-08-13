"""
Schéma SQLite : ce qui échoue doit se voir, et ne se rejouer qu'une fois.

Trois défauts distincts, même fichier.

`_ensure_schema` enveloppait chaque `ALTER` dans un `except
sqlite3.OperationalError: pass` en affirmant en commentaire que la colonne
existait déjà. Cette exception couvre aussi « attempt to write a readonly
database », « database is locked », « no such table » et le disque plein : sur un
volume monté en lecture seule (PUID/PGID mal posés), les six migrations passaient
en silence, puis le tableau de bord rendait un 500 `no such column:
cover_manual` sans une ligne de journal.

Les migrations étaient par ailleurs rejouées à CHAQUE appel de fonction : deux
DDL et une connexion neuve par tome écrit, alors qu'aucun appel SQLite n'a de
point de bascule eventlet — chaque `fsync` fige tout le serveur, Live Logs
compris.

Enfin, une série supprimée dans Kavita ne voyait purger que `series_cache` et
`pending_reviews` : son rapport de tomes, ses flags d'audit, son attendu forcé et
l'état de chacun de ses tomes restaient derrière elle, à gonfler les compteurs de
progression et à faire désérialiser du JSON mort à chaque rendu du tableau de
bord.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

import db_manager


class _Rows(list):
    def fetchall(self):
        return list(self)

    def fetchone(self):
        return self[0] if self else None


class _ReadOnlyCursor:
    """Base ouverte en lecture seule : la lecture passe, l'`ALTER` est refusé."""

    def __init__(self, columns):
        self.columns = columns
        self.altered = []

    def execute(self, sql, params=()):
        if sql.startswith("PRAGMA table_info"):
            return _Rows((i, name, "TEXT", 0, None, 0) for i, name in enumerate(self.columns))
        if sql.startswith("ALTER"):
            self.altered.append(sql)
            raise sqlite3.OperationalError("attempt to write a readonly database")
        return _Rows()


def test_a_migration_refused_by_the_base_is_not_swallowed():
    cursor = _ReadOnlyCursor(["series_id", "status"])

    with pytest.raises(sqlite3.OperationalError):
        db_manager._ensure_schema(cursor)

    assert cursor.altered, "la migration doit avoir été tentée"


def test_a_base_already_up_to_date_is_not_written_to_at_all(isolated_db):
    """Le chemin normal est une LECTURE : le tableau de bord appelle
    `_ensure_schema` à chaque rafraîchissement, il ne doit pas y prendre un
    verrou d'écriture."""
    db_manager._schema_ready.clear()
    conn = db_manager._connect()
    try:
        columns = db_manager._table_columns(conn.cursor(), "series_cache")
    finally:
        conn.close()
    cursor = _ReadOnlyCursor(sorted(columns))

    db_manager._ensure_schema(cursor)

    assert cursor.altered == []


def test_a_migration_already_played_is_not_replayed(isolated_db):
    """Ce qui coûtait vingt millisecondes par tome écrit."""

    class _Boom:
        def execute(self, *args, **kwargs):
            raise AssertionError("migration rejouée sur un chemin chaud")

    for ensure in (
        db_manager._ensure_volume_unit_tables,
        db_manager._ensure_library_audit_tables,
        db_manager._ensure_batch_queue_tables,
        db_manager._ensure_pending_reviews_table,
    ):
        ensure(_Boom())


def test_a_base_recreated_from_scratch_replays_everything(tmp_path, monkeypatch):
    """`init_db` est le seul point qui annule le mémo : une base neuve,
    restaurée ou effacée doit tout rejouer."""
    monkeypatch.setattr(db_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "DB_FILE", str(tmp_path / "cache.db"))
    db_manager.init_db()
    assert db_manager._schema_pending("volume_unit_tables") is False

    db_manager.release_wal_keeper()  # sous Windows, un fichier tenu ouvert ne s'efface pas
    (tmp_path / "cache.db").unlink()
    db_manager.init_db()

    db_manager.save_volume_unit_state(1, 10, "DONE")
    assert db_manager.count_volume_units_by_status() == {"DONE": 1}


def test_commits_no_longer_wait_for_a_disk_flush(isolated_db):
    """`synchronous=FULL` impose un fsync par commit, et aucun appel SQLite ne
    rend la main à eventlet : chaque tome écrit figeait tout le serveur."""
    conn = db_manager._connect()
    try:
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_the_wal_is_not_torn_down_between_two_writes(isolated_db):
    """Quand la DERNIÈRE connexion à une base WAL se ferme, SQLite recopie le
    journal dans le fichier principal et supprime les `-wal`/`-shm` : le cycle
    « ouvrir, écrire, fermer » de chaque fonction de ce module payait un
    checkpoint complet, 19 ms par tome écrit, pendant lesquelles rien d'autre ne
    tournait dans le process."""
    isolated_db.save_volume_unit_state(1, 10, "DONE")

    assert os.path.exists(str(isolated_db.DB_FILE) + "-wal")


def test_the_idle_reader_can_be_let_go(isolated_db):
    """Sous Windows, un fichier tenu ouvert par SQLite ne peut pas être
    supprimé : déplacer ou effacer `cache.db` doit rester possible."""
    isolated_db.save_volume_unit_state(1, 10, "DONE")

    isolated_db.release_wal_keeper()

    assert isolated_db._wal_keeper is None
    # La base reste utilisable : le lecteur oisif se rouvre au besoin.
    assert isolated_db.count_volume_units_by_status() == {"DONE": 1}


def test_the_unique_index_migration_survives_the_connection_being_closed(isolated_db):
    """Le `DELETE` de la migration ouvre une transaction qui absorbe le DDL qui
    suit : appelée depuis un chemin de lecture, la migration était annulée par le
    `close()` sans `commit()`, puis rejouée à chaque appel — en prenant un verrou
    d'écriture depuis une lecture."""
    conn = db_manager._connect()
    conn.execute("DROP INDEX IF EXISTS idx_pending_reviews_series_id")
    conn.execute(
        "CREATE INDEX idx_pending_reviews_series_id ON pending_reviews(series_id)"
    )
    conn.commit()
    conn.close()
    db_manager._schema_ready.clear()

    conn = db_manager._connect()
    db_manager._ensure_pending_reviews_table(conn.cursor())
    conn.close()  # aucun commit : c'est le chemin de lecture

    conn = db_manager._connect()
    try:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='idx_pending_reviews_series_id'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert "UNIQUE" in sql.upper()


# ===== Séries supprimées dans Kavita =====


def _seed_series(db, series_id):
    db.update_status(series_id, "COMPLETED")
    db.save_volume_report_cache(series_id, {"badge": "3/3", "series_name": f"S{series_id}"})
    db.set_series_external_id_flags({series_id: True})
    db.set_catalog_expected_override(series_id, 12)
    db.save_volume_unit_state(series_id, series_id * 10, "DONE")
    db.mark_series_pass_done(series_id)


def test_a_series_deleted_in_kavita_leaves_nothing_behind(isolated_db):
    _seed_series(isolated_db, 501)
    _seed_series(isolated_db, 502)

    assert isolated_db.clean_orphaned_cache({502}) == 1

    assert set(isolated_db.get_all_cached_data()) == {502}
    assert isolated_db.get_volume_report_cache(501) is None
    assert 501 not in isolated_db.get_series_audit_flags()
    assert isolated_db.get_catalog_expected_override(501) is None
    assert isolated_db.get_volume_unit_states(501) == {}
    assert isolated_db.list_enriched_series_ids() == {502}


def test_the_progress_counters_stop_counting_volumes_that_no_longer_exist(isolated_db):
    """`count_volume_units_by_status()` sans filtre alimente la progression de la
    passe tomes : les unités des séries disparues la gonflaient à vie."""
    _seed_series(isolated_db, 501)
    _seed_series(isolated_db, 502)
    assert isolated_db.count_volume_units_by_status() == {"DONE": 2}

    isolated_db.clean_orphaned_cache({502})

    assert isolated_db.count_volume_units_by_status() == {"DONE": 1}


def test_the_surviving_series_keeps_everything(isolated_db):
    _seed_series(isolated_db, 502)

    isolated_db.clean_orphaned_cache({502})

    assert isolated_db.get_volume_report_cache(502)["badge"] == "3/3"
    assert isolated_db.get_catalog_expected_override(502) == 12
    assert isolated_db.get_volume_unit_states(502)[5020]["status"] == "DONE"


def test_an_empty_inventory_purges_nothing(isolated_db):
    """Un inventaire Kavita vide n'est jamais un feu vert : ces tables portent
    des réglages saisis à la main."""
    _seed_series(isolated_db, 501)

    assert isolated_db.clean_orphaned_cache(set()) == 0

    assert isolated_db.get_volume_report_cache(501) is not None


def test_a_thousand_orphans_do_not_blow_the_parameter_limit(isolated_db):
    """SQLite plafonne les paramètres liés : une bibliothèque qui perd un
    millier de séries d'un coup faisait exploser un `IN (...)` d'un seul tenant."""
    conn = isolated_db._connect()
    try:
        conn.executemany(
            "INSERT INTO series_cache(series_id, status) VALUES (?, 'COMPLETED')",
            [(sid,) for sid in range(1, 1001)],
        )
        conn.executemany(
            "INSERT INTO volume_unit_cache(series_id, chapter_id, status, updated_at) "
            "VALUES (?, ?, 'DONE', '')",
            [(sid, sid * 10) for sid in range(1, 1001)],
        )
        conn.commit()
    finally:
        conn.close()

    assert isolated_db.clean_orphaned_cache({1}) == 999

    assert set(isolated_db.get_all_cached_data()) == {1}
    assert isolated_db.count_volume_units_by_status() == {"DONE": 1}
