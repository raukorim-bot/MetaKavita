"""
La table `users` partage le fichier SQLite du cache : sa connexion doit porter
les mêmes garde-fous de concurrence que celle de `db_manager` (WAL +
`busy_timeout`). Sans eux, le timeout par défaut de 5 s de sqlite3 faisait
échouer un login pendant un batch ou une analyse d'inventaire.
"""
import sqlite3

import auth_manager


def test_auth_connection_enables_wal_and_busy_timeout(isolated_db):
    conn = auth_manager._connect()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) >= 30000
    finally:
        conn.close()


def test_auth_connection_targets_the_same_file_as_the_cache(isolated_db):
    conn = auth_manager._connect()
    try:
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    finally:
        conn.close()

    assert db_path == isolated_db.DB_FILE


def test_a_login_survives_a_concurrent_writer(isolated_db):
    """Régression : un écrivain gardant une transaction ouverte faisait échouer
    la lecture de la table users au bout de 5 s au lieu d'attendre son tour."""
    auth_manager.create_user("admin", "correct horse battery")

    blocker = sqlite3.connect(isolated_db.DB_FILE, timeout=5.0)
    blocker.execute("PRAGMA journal_mode=WAL")
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("INSERT INTO series_cache (series_id, status) VALUES (9001, 'PENDING')")
    try:
        # En WAL, un lecteur n'est pas bloqué par un écrivain : la vérification
        # doit aboutir immédiatement, sans dépendre du busy_timeout.
        assert auth_manager.verify_credentials("admin", "correct horse battery") is not None
        assert auth_manager.user_count() == 1
    finally:
        blocker.rollback()
        blocker.close()
