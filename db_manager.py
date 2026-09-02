import sqlite3
import os
import logging
import threading
import time
from typing import Optional

from models import SeriesOverride
from secure_logging import safe_exc_str


def _resolve_data_dir() -> str:
    env = (os.environ.get("METAKAVITA_DATA_DIR") or os.environ.get("DATA_DIR") or "").strip()
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))


DATA_DIR = _resolve_data_dir()
DB_FILE = os.path.join(DATA_DIR, "cache.db")


#: Connexion oisive qui ne sert à AUCUNE requête. Quand la dernière connexion à
#: une base WAL se ferme, SQLite recopie le journal dans le fichier principal et
#: supprime les fichiers `-wal`/`-shm` : le cycle « ouvrir, écrire, fermer » que
#: fait chaque fonction de ce module payait donc un checkpoint complet à chaque
#: appel — 19 ms par tome écrit, mesurés sur disque local, contre 1 ms avec ce
#: lecteur maintenu ouvert. Et comme aucun appel SQLite n'a de point de bascule
#: eventlet, ces 19 ms figeaient tout le serveur, Live Logs et Socket.IO compris.
#: La connexion ne prend aucune transaction de lecture, donc elle ne retient
#: jamais le checkpoint automatique.
_wal_keeper = None
_wal_keeper_file = None
_wal_keeper_lock = threading.Lock()


def _hold_wal_open():
    global _wal_keeper, _wal_keeper_file
    if _wal_keeper is not None and _wal_keeper_file == DB_FILE:
        return
    with _wal_keeper_lock:
        if _wal_keeper is not None and _wal_keeper_file == DB_FILE:
            return
        stale, _wal_keeper, _wal_keeper_file = _wal_keeper, None, None
        if stale is not None:
            try:
                stale.close()
            except Exception:
                pass
        try:
            # `check_same_thread=False` : la connexion n'exécute rien, mais elle
            # peut être refermée par un autre thread que celui qui l'a ouverte
            # (bascule de base en test, arrêt du process).
            keeper = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
            keeper.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error as exc:
            logging.debug("[DB] journal WAL non maintenu ouvert : %s", safe_exc_str(exc))
            return
        _wal_keeper, _wal_keeper_file = keeper, DB_FILE


def release_wal_keeper():
    """Referme le lecteur oisif — le fichier de base redevient supprimable.

    Utile aux tests et aux outils qui déplacent ou effacent `cache.db` : sous
    Windows, un fichier tenu ouvert par SQLite ne peut pas être supprimé.
    """
    global _wal_keeper, _wal_keeper_file
    with _wal_keeper_lock:
        stale, _wal_keeper, _wal_keeper_file = _wal_keeper, None, None
    if stale is not None:
        try:
            stale.close()
        except Exception:
            pass


def _connect():
    """Ouvre une connexion SQLite avec WAL + busy_timeout (anti « database is locked »)."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        # `synchronous=FULL` (le défaut) impose un fsync par commit, et
        # l'enrichissement par tome commite une fois par tome : 4,1 ms par unité
        # mesurées contre 0,95 ms en `NORMAL`. En WAL, `NORMAL` ne risque que la
        # perte des toutes dernières transactions sur coupure brutale, jamais la
        # corruption de la base : c'est un cache reconstructible depuis Kavita,
        # le compromis est bon.
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
    # Après les PRAGMA, jamais avant : un lecteur ouvert sur un fichier encore
    # vide reste attaché au mode journal de ce fichier vide et ne retient alors
    # rien du tout. La base doit déjà être en WAL quand il arrive.
    _hold_wal_open()
    return conn


#: Migrations déjà jouées dans ce process, par (fichier de base, clé). Elles
#: étaient rejouées à chaque appel de fonction : `save_volume_unit_state` payait
#: deux DDL par tome écrit, `should_skip_batch_item` deux connexions et six
#: requêtes pour un seul SELECT. `init_db()` vide ce mémo — une base neuve ou
#: restaurée doit tout rejouer.
_schema_ready = set()


def _schema_pending(key) -> bool:
    """True si la migration `key` reste à jouer pour la base courante."""
    return (DB_FILE, key) not in _schema_ready


def _schema_done(key) -> None:
    """À appeler seulement après une migration réussie : un échec (base en
    lecture seule, disque plein) doit être rejoué, et revu, au prochain appel."""
    _schema_ready.add((DB_FILE, key))


def _table_columns(c, table) -> set:
    try:
        return {row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def _ensure_schema(c):
    """Ajoute les colonnes manquantes de `series_cache`, une par une.

    L'ancienne version enveloppait chaque `ALTER` dans un `except
    sqlite3.OperationalError: pass` en affirmant en commentaire que la colonne
    existait déjà. Or cette exception couvre aussi « no such table », « database
    is locked », « attempt to write a readonly database » et le disque plein :
    sur un volume monté en lecture seule (PUID/PGID mal posés), les six
    migrations passaient en silence, puis le tableau de bord rendait un 500
    `no such column: cover_manual` sans une ligne de journal. On lit donc le
    schéma avant d'écrire, et ce qui échoue quand même remonte.
    """
    if not _schema_pending("series_cache_columns"):
        return
    columns = [
        ("forced_provider", "TEXT DEFAULT 'AUTO'"),
        ("targeted_fields", "TEXT DEFAULT 'ALL'"),
        ("publisher_pref", "TEXT DEFAULT 'GLOBAL'"),
        ("alt_title_langs", "TEXT DEFAULT ''"),
        # Provenance de la couverture : 1 = choisie à la main dans MetaKavita.
        # Distinct du verrou Kavita `coverImageLocked`, que MetaKavita pose sur
        # TOUS ses uploads (sans quoi le scan Kavita régénère la vignette depuis
        # les fichiers) et qui ne dit donc rien de l'origine de l'image.
        ("cover_manual", "INTEGER DEFAULT 0"),
        # Séries que l'inventaire doit ignorer (compilations, doujin, séries que
        # nul catalogue ne connaîtra) : sans ça elles polluent les compteurs de
        # manquants à vie, et le seul recours serait de couper l'inventaire.
        ("inventory_excluded", "INTEGER DEFAULT 0"),
    ]
    existing = _table_columns(c, "series_cache")
    if not existing:
        # Table pas encore créée (appel hors `init_db`) : rien à migrer, et
        # surtout rien à mémoriser.
        return
    for col_name, col_type in columns:
        if col_name in existing:
            continue
        c.execute(f"ALTER TABLE series_cache ADD COLUMN {col_name} {col_type}")
    _schema_done("series_cache_columns")


def init_db():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    # Base neuve, restaurée ou effacée : toutes les migrations se rejouent, quel
    # que soit ce que ce process avait déjà vu sur ce chemin.
    _schema_ready.clear()

    conn = _connect()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS series_cache
                 (series_id INTEGER PRIMARY KEY, 
                  status TEXT, 
                  forced_id TEXT, 
                  alternative_title TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS provider_stats
                 (provider_id TEXT PRIMARY KEY,
                  wins INTEGER NOT NULL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS lifetime_stats
                 (stat_key TEXT PRIMARY KEY,
                  value INTEGER NOT NULL DEFAULT 0)''')
    _ensure_schema(c)
    _ensure_pending_reviews_table(c)
    _ensure_batch_queue_tables(c)
    _ensure_library_audit_tables(c)
    _ensure_volume_unit_tables(c)
    _ensure_workshop_tables(c)
    _ensure_auto_sync_tables(c)
    conn.commit()
    conn.close()


def _ensure_library_audit_tables(c):
    """Caches for library hygiene reports (volume gaps / duplicate groups)."""
    if not _schema_pending("library_audit_tables"):
        return
    c.execute(
        '''CREATE TABLE IF NOT EXISTS volume_report_cache (
             series_id INTEGER PRIMARY KEY,
             summary_json TEXT NOT NULL,
             badge TEXT,
             structure TEXT,
             updated_at TEXT NOT NULL
           )'''
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS duplicate_group_cache (
             library_id TEXT NOT NULL,
             group_id TEXT NOT NULL,
             payload_json TEXT NOT NULL,
             updated_at TEXT NOT NULL,
             PRIMARY KEY (library_id, group_id)
           )'''
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_dup_cache_lib ON duplicate_group_cache(library_id)"
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS series_audit_flags (
             series_id INTEGER PRIMARY KEY,
             has_external_id INTEGER,
             duplicate_group_id TEXT,
             updated_at TEXT NOT NULL
           )'''
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS hygiene_library_meta (
             library_id TEXT PRIMARY KEY,
             scanned_at TEXT NOT NULL,
             counts_json TEXT NOT NULL
           )'''
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS hygiene_dup_dismissals (
             library_id TEXT NOT NULL,
             group_key TEXT NOT NULL,
             series_ids_json TEXT NOT NULL,
             reason TEXT NOT NULL,
             updated_at TEXT NOT NULL,
             PRIMARY KEY (library_id, group_key)
           )'''
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_hygiene_dismiss_lib "
        "ON hygiene_dup_dismissals(library_id)"
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS hygiene_catalog_overrides (
             series_id INTEGER PRIMARY KEY,
             expected INTEGER NOT NULL,
             updated_at TEXT NOT NULL
           )'''
    )
    _schema_done("library_audit_tables")


def _ensure_volume_unit_tables(c):
    """État d'enrichissement par unité (tome ou chapitre) — issue #27.

    Une ligne par chapitre Kavita, parce que c'est là que vivent les
    métadonnées : un tome n'en est que le conteneur. C'est cette table qui rend
    la passe de bibliothèque reprenable après un redémarrage et qui évite de
    réinterroger un fournisseur pour une unité déjà traitée.
    """
    if not _schema_pending("volume_unit_tables"):
        return
    c.execute(
        '''CREATE TABLE IF NOT EXISTS volume_unit_cache (
             series_id INTEGER NOT NULL,
             chapter_id INTEGER NOT NULL,
             volume_id INTEGER,
             volume_number TEXT,
             chapter_number TEXT,
             status TEXT NOT NULL,
             provider TEXT,
             written_fields TEXT,
             updated_at TEXT NOT NULL,
             PRIMARY KEY (series_id, chapter_id)
           )'''
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_volume_unit_series "
        "ON volume_unit_cache(series_id)"
    )
    _schema_done("volume_unit_tables")


def _ensure_workshop_tables(c):
    """Overrides Champ Magique par tome + journal borné de l'atelier."""
    if not _schema_pending("workshop_tables"):
        return
    c.execute(
        '''CREATE TABLE IF NOT EXISTS volume_unit_overrides (
             series_id INTEGER NOT NULL,
             chapter_id INTEGER NOT NULL,
             provider TEXT,
             provider_ref TEXT,
             payload_json TEXT,
             updated_at TEXT NOT NULL,
             PRIMARY KEY (series_id, chapter_id)
           )'''
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_volume_overrides_series "
        "ON volume_unit_overrides(series_id)"
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS workshop_history (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             series_id INTEGER NOT NULL,
             chapter_id INTEGER,
             event TEXT NOT NULL,
             detail_json TEXT,
             created_at TEXT NOT NULL
           )'''
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_workshop_history_series "
        "ON workshop_history(series_id)"
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS workshop_series_overrides (
             series_id INTEGER PRIMARY KEY,
             payload_json TEXT NOT NULL,
             cover_url TEXT,
             updated_at TEXT NOT NULL
           )'''
    )
    _schema_done("workshop_tables")


def _ensure_lifetime_stats_table(c):
    if not _schema_pending("lifetime_stats"):
        return
    c.execute('''CREATE TABLE IF NOT EXISTS lifetime_stats
                 (stat_key TEXT PRIMARY KEY,
                  value INTEGER NOT NULL DEFAULT 0)''')
    _schema_done("lifetime_stats")


def _ensure_provider_stats_table(c):
    if not _schema_pending("provider_stats"):
        return
    c.execute('''CREATE TABLE IF NOT EXISTS provider_stats
                 (provider_id TEXT PRIMARY KEY,
                  wins INTEGER NOT NULL DEFAULT 0)''')
    _schema_done("provider_stats")


def _ensure_batch_queue_tables(c):
    """File batch persistante (C63) — survie au redémarrage du conteneur."""
    if not _schema_pending("batch_queue_tables"):
        return
    c.execute(
        '''CREATE TABLE IF NOT EXISTS batch_queue (
             id TEXT PRIMARY KEY,
             series_id INTEGER NOT NULL,
             series_name TEXT,
             force_update INTEGER NOT NULL DEFAULT 0,
             fields_override TEXT,
             state TEXT NOT NULL,
             created_at TEXT NOT NULL,
             position INTEGER NOT NULL
           )'''
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_batch_queue_state ON batch_queue(state)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_batch_queue_series ON batch_queue(series_id)"
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS batch_queue_meta (
             key TEXT PRIMARY KEY,
             value TEXT NOT NULL
           )'''
    )
    c.execute(
        "INSERT OR IGNORE INTO batch_queue_meta(key, value) VALUES ('paused', '0')"
    )
    _schema_done("batch_queue_tables")


_auto_sync_report_lock = threading.Lock()

_ASR_EMPTY_BADGE = {
    "visible": False,
    "unread": False,
    "running": False,
    "total": 0,
    "ok": 0,
    "errors": 0,
    "review": 0,
    "relock": 0,
    "stopped": 0,
    "pending": 0,
}


def _ensure_auto_sync_tables(c):
    """Snapshot d'IDs Kavita pour le trigger scan (C96) + rapport de vague (C97)."""
    if _schema_pending("auto_sync_known_series"):
        c.execute(
            '''CREATE TABLE IF NOT EXISTS auto_sync_known_series (
                 series_id INTEGER PRIMARY KEY
               )'''
        )
        _schema_done("auto_sync_known_series")
    if not _schema_pending("auto_sync_report_tables"):
        return
    c.execute(
        '''CREATE TABLE IF NOT EXISTS auto_sync_runs (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             started_at REAL NOT NULL,
             finished_at REAL,
             trigger TEXT NOT NULL DEFAULT '',
             unread INTEGER NOT NULL DEFAULT 0,
             stopped INTEGER NOT NULL DEFAULT 0
           )'''
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS auto_sync_run_items (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             run_id INTEGER NOT NULL,
             series_id INTEGER NOT NULL,
             series_name TEXT,
             outcome TEXT NOT NULL DEFAULT 'pending',
             message TEXT,
             finished_at REAL,
             UNIQUE(run_id, series_id)
           )'''
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_auto_sync_run_items_run "
        "ON auto_sync_run_items(run_id)"
    )
    _schema_done("auto_sync_report_tables")


def get_auto_sync_known_ids() -> set:
    """IDs Kavita déjà vus par le trigger scan (snapshot)."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    try:
        c = conn.cursor()
        _ensure_auto_sync_tables(c)
        rows = c.execute("SELECT series_id FROM auto_sync_known_series").fetchall()
        return {int(row[0]) for row in rows}
    finally:
        conn.close()


def replace_auto_sync_known_ids(ids) -> None:
    """Remplace le snapshot en une transaction (DELETE + INSERT, pas un merge)."""
    if not os.path.exists(DB_FILE):
        init_db()
    seen = set()
    rows = []
    for raw in ids or []:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid in seen:
            continue
        seen.add(sid)
        rows.append((sid,))
    conn = _connect()
    try:
        c = conn.cursor()
        _ensure_auto_sync_tables(c)
        c.execute("DELETE FROM auto_sync_known_series")
        if rows:
            c.executemany(
                "INSERT INTO auto_sync_known_series (series_id) VALUES (?)",
                rows,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def classify_auto_sync_outcome(ok, msg, status=None) -> str:
    """Classe le résultat d'un job Auto-sync pour le rapport de vague (C97)."""
    token = str(status or "").strip().upper()
    message = str(msg or "").strip()
    if token == "PENDING_REVIEW" or message == "PENDING_REVIEW":
        return "review"
    if token == "NEEDS_RELOCK" or message == "NEEDS_RELOCK":
        return "relock"
    if token == "NOT_FOUND":
        return "error"
    if message in ("Introuvable.", "Not found.", "Not found"):
        return "error"
    if not ok:
        return "error"
    return "completed"


def _open_auto_sync_run_id(c):
    row = c.execute(
        "SELECT id FROM auto_sync_runs WHERE finished_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return int(row[0]) if row else None


def _counts_from_outcomes(outcomes) -> dict:
    counts = {
        "total": 0,
        "ok": 0,
        "errors": 0,
        "review": 0,
        "relock": 0,
        "stopped": 0,
        "pending": 0,
    }
    for raw in outcomes or []:
        counts["total"] += 1
        key = str(raw or "pending").strip().lower()
        if key in ("completed", "relock"):
            counts["ok"] += 1
        if key == "error":
            counts["errors"] += 1
        elif key == "review":
            counts["review"] += 1
        elif key == "relock":
            counts["relock"] += 1
        elif key == "stopped":
            counts["stopped"] += 1
        elif key == "pending":
            counts["pending"] += 1
    return counts


def _badge_from_run(run, counts, series_ids=None) -> dict:
    ids = []
    for raw in series_ids or []:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not run:
        badge = dict(_ASR_EMPTY_BADGE)
        badge["series_ids"] = ids
        return badge
    running = run.get("finished_at") is None
    unread = bool(run.get("unread")) and not running
    badge = dict(_ASR_EMPTY_BADGE)
    badge.update(counts or {})
    badge["visible"] = running or unread
    badge["unread"] = unread
    badge["running"] = running
    badge["series_ids"] = ids
    return badge


def _run_row_to_dict(row) -> dict:
    return {
        "id": int(row[0]),
        "started_at": row[1],
        "finished_at": row[2],
        "trigger": row[3] or "",
        "unread": bool(row[4]),
        "stopped": bool(row[5]),
    }


def begin_auto_sync_run(trigger, items) -> int:
    """Ouvre (ou réutilise) la vague courante et y pose les séries en `pending`.

    Une vague encore ouverte (Stop n'a pas tout fini, un scrape tourne) reçoit
    les nouvelles séries. Sinon on remplace le rapport précédent : l'UI ne
    montre que la dernière vague.
    """
    prepared = []
    seen = set()
    for raw in items or []:
        if isinstance(raw, dict):
            sid, name = raw.get("series_id"), raw.get("series_name")
        else:
            try:
                sid, name = raw[0], raw[1]
            except (TypeError, IndexError, ValueError):
                continue
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            continue
        if sid in seen:
            continue
        seen.add(sid)
        prepared.append((sid, str(name or sid)))
    if not prepared:
        return 0
    trig = str(trigger or "").strip().lower()
    now = time.time()
    with _auto_sync_report_lock:
        if not os.path.exists(DB_FILE):
            init_db()
        conn = _connect()
        try:
            c = conn.cursor()
            _ensure_auto_sync_tables(c)
            run_id = _open_auto_sync_run_id(c)
            if run_id is None:
                c.execute("DELETE FROM auto_sync_run_items")
                c.execute("DELETE FROM auto_sync_runs")
                c.execute(
                    "INSERT INTO auto_sync_runs (started_at, trigger, unread, stopped) "
                    "VALUES (?, ?, 0, 0)",
                    (now, trig),
                )
                run_id = int(c.lastrowid)
            for sid, name in prepared:
                c.execute(
                    "INSERT OR IGNORE INTO auto_sync_run_items "
                    "(run_id, series_id, series_name, outcome) VALUES (?, ?, ?, 'pending')",
                    (run_id, sid, name),
                )
                c.execute(
                    "UPDATE auto_sync_run_items SET series_name = ? "
                    "WHERE run_id = ? AND series_id = ? AND outcome = 'pending'",
                    (name, run_id, sid),
                )
            conn.commit()
            return run_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def record_auto_sync_item(series_id, series_name, ok, msg) -> None:
    """Enregistre le résultat d'un job `origin=auto` sur la vague ouverte."""
    try:
        sid = int(series_id)
    except (TypeError, ValueError):
        return
    now = time.time()
    with _auto_sync_report_lock:
        if not os.path.exists(DB_FILE):
            return
        conn = _connect()
        try:
            c = conn.cursor()
            _ensure_auto_sync_tables(c)
            run_id = _open_auto_sync_run_id(c)
            if run_id is None:
                return
            status_row = c.execute(
                "SELECT status FROM series_cache WHERE series_id = ?",
                (sid,),
            ).fetchone()
            status = status_row[0] if status_row else None
            outcome = classify_auto_sync_outcome(ok, msg, status)
            message = str(msg or "")
            name = str(series_name or sid)
            c.execute(
                "UPDATE auto_sync_run_items "
                "SET outcome = ?, message = ?, finished_at = ?, series_name = ? "
                "WHERE run_id = ? AND series_id = ?",
                (outcome, message, now, name, run_id, sid),
            )
            if c.rowcount == 0:
                c.execute(
                    "INSERT INTO auto_sync_run_items "
                    "(run_id, series_id, series_name, outcome, message, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (run_id, sid, name, outcome, message, now),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def mark_auto_sync_items_stopped(series_ids) -> int:
    """Stop : les jobs Auto-sync encore `pending` de la vague ouverte passent en stopped."""
    ids = []
    seen = set()
    for raw in series_ids or []:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid in seen:
            continue
        seen.add(sid)
        ids.append(sid)
    if not ids:
        return 0
    now = time.time()
    with _auto_sync_report_lock:
        if not os.path.exists(DB_FILE):
            return 0
        conn = _connect()
        try:
            c = conn.cursor()
            _ensure_auto_sync_tables(c)
            run_id = _open_auto_sync_run_id(c)
            if run_id is None:
                return 0
            placeholders = ",".join("?" for _ in ids)
            c.execute(
                f"UPDATE auto_sync_run_items SET outcome = 'stopped', finished_at = ?, "
                f"message = 'stopped' WHERE run_id = ? AND outcome = 'pending' "
                f"AND series_id IN ({placeholders})",
                [now, run_id, *ids],
            )
            n = c.rowcount
            if n:
                c.execute(
                    "UPDATE auto_sync_runs SET stopped = 1 WHERE id = ?",
                    (run_id,),
                )
            conn.commit()
            return n
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def finish_open_auto_sync_run(*, stopped=False) -> bool:
    """Clôt la vague ouverte et la marque non lue. False s'il n'y en avait pas."""
    now = time.time()
    with _auto_sync_report_lock:
        if not os.path.exists(DB_FILE):
            return False
        conn = _connect()
        try:
            c = conn.cursor()
            _ensure_auto_sync_tables(c)
            run_id = _open_auto_sync_run_id(c)
            if run_id is None:
                return False
            if stopped:
                c.execute(
                    "UPDATE auto_sync_runs SET finished_at = ?, unread = 1, stopped = 1 "
                    "WHERE id = ? AND finished_at IS NULL",
                    (now, run_id),
                )
            else:
                c.execute(
                    "UPDATE auto_sync_runs SET finished_at = ?, unread = 1 "
                    "WHERE id = ? AND finished_at IS NULL",
                    (now, run_id),
                )
            changed = c.rowcount > 0
            if changed:
                meta = c.execute(
                    "SELECT trigger, stopped FROM auto_sync_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                outcomes = [
                    row[0]
                    for row in c.execute(
                        "SELECT outcome FROM auto_sync_run_items WHERE run_id = ?",
                        (run_id,),
                    ).fetchall()
                ]
                was_stopped = bool(stopped) or bool(meta and meta[1])
                trigger = (meta[0] if meta else "") or ""
                _apply_auto_sync_wave_telemetry(
                    c, trigger=trigger, stopped=was_stopped, outcomes=outcomes
                )
            conn.commit()
            return changed
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _apply_auto_sync_wave_telemetry(c, *, trigger, stopped, outcomes) -> None:
    """Incrémente les compteurs lifetime d'une vague Auto-sync tout juste close."""
    counts = _counts_from_outcomes(outcomes)
    _ensure_lifetime_stats_table(c)
    _bump_lifetime_stat(c, "auto_sync_waves", 1)
    if stopped:
        _bump_lifetime_stat(c, "auto_sync_waves_stopped", 1)
    if str(trigger or "").strip().lower() == "scan":
        _bump_lifetime_stat(c, "auto_sync_waves_scan", 1)
    else:
        _bump_lifetime_stat(c, "auto_sync_waves_interval", 1)
    _bump_lifetime_stat(c, "auto_sync_series", counts.get("total") or 0)
    _bump_lifetime_stat(c, "auto_sync_ok", counts.get("ok") or 0)
    _bump_lifetime_stat(c, "auto_sync_errors", counts.get("errors") or 0)
    _bump_lifetime_stat(c, "auto_sync_review", counts.get("review") or 0)
    _bump_lifetime_stat(c, "auto_sync_relock", counts.get("relock") or 0)
    _bump_lifetime_stat(c, "auto_sync_stopped", counts.get("stopped") or 0)


def mark_auto_sync_report_read() -> bool:
    """Marque le dernier rapport terminé comme lu (cache le bouton KPI)."""
    with _auto_sync_report_lock:
        if not os.path.exists(DB_FILE):
            return False
        conn = _connect()
        try:
            c = conn.cursor()
            _ensure_auto_sync_tables(c)
            row = c.execute(
                "SELECT id, finished_at FROM auto_sync_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row or row[1] is None:
                return False
            c.execute(
                "UPDATE auto_sync_runs SET unread = 0 WHERE id = ?",
                (int(row[0]),),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _load_latest_auto_sync_run(c):
    row = c.execute(
        "SELECT id, started_at, finished_at, trigger, unread, stopped "
        "FROM auto_sync_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None, []
    run = _run_row_to_dict(row)
    items = []
    for item in c.execute(
        "SELECT series_id, series_name, outcome, message, finished_at "
        "FROM auto_sync_run_items WHERE run_id = ? ORDER BY series_name COLLATE NOCASE",
        (run["id"],),
    ).fetchall():
        items.append({
            "series_id": int(item[0]),
            "series_name": item[1] or str(item[0]),
            "outcome": item[2] or "pending",
            "message": item[3] or "",
            "finished_at": item[4],
        })
    return run, items


def get_auto_sync_report_badge() -> dict:
    """Pastille KPI : visible si la vague tourne ou si le dernier rapport est non lu."""
    with _auto_sync_report_lock:
        if not os.path.exists(DB_FILE):
            return dict(_ASR_EMPTY_BADGE)
        conn = _connect()
        try:
            c = conn.cursor()
            _ensure_auto_sync_tables(c)
            run, items = _load_latest_auto_sync_run(c)
        finally:
            conn.close()
    return _badge_from_run(
        run,
        _counts_from_outcomes(i["outcome"] for i in items),
        [i["series_id"] for i in items],
    )


def get_latest_auto_sync_report() -> dict:
    """Dernière vague + séries, ou un rapport vide si aucune n'a encore tourné."""
    with _auto_sync_report_lock:
        if not os.path.exists(DB_FILE):
            return {"run": None, "items": [], "counts": dict(_ASR_EMPTY_BADGE), "badge": dict(_ASR_EMPTY_BADGE)}
        conn = _connect()
        try:
            c = conn.cursor()
            _ensure_auto_sync_tables(c)
            run, items = _load_latest_auto_sync_run(c)
        finally:
            conn.close()
    counts = _counts_from_outcomes(i["outcome"] for i in items)
    ids = [i["series_id"] for i in items]
    badge = _badge_from_run(run, counts, ids)
    return {"run": run, "items": items, "counts": counts, "badge": badge}


def _ensure_pending_reviews_table(c):
    if not _schema_pending("pending_reviews_tables"):
        return
    c.execute('''CREATE TABLE IF NOT EXISTS pending_reviews
                 (review_id TEXT PRIMARY KEY,
                  series_id INTEGER NOT NULL,
                  series_name TEXT,
                  candidates_json TEXT NOT NULL,
                  preview_json TEXT,
                  state TEXT NOT NULL DEFAULT 'awaiting_pick',
                  created_at TEXT,
                  base_provider TEXT,
                  chosen_score REAL)''')
    # Lien de vérification Kavita dans le pick UI (voir templates manual_review.js) :
    # ID de bibliothèque Kavita de la série, absent des lignes créées avant cette
    # migration (reste NULL, le lien est alors simplement omis côté UI).
    # Colonne testée plutôt que `except OperationalError: pass` : cette exception
    # couvre aussi la base en lecture seule et le disque plein (voir
    # `_ensure_schema`).
    if "library_id" not in _table_columns(c, "pending_reviews"):
        c.execute("ALTER TABLE pending_reviews ADD COLUMN library_id INTEGER")
    # Migration one-shot : index non-unique → UNIQUE (une review par série).
    c.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_pending_reviews_series_id'"
    )
    idx_row = c.fetchone()
    idx_sql = (idx_row[0] or "") if idx_row else ""
    migrated_index = False
    if "UNIQUE" not in idx_sql.upper():
        try:
            c.execute(
                '''DELETE FROM pending_reviews WHERE rowid NOT IN (
                     SELECT MAX(rowid) FROM pending_reviews GROUP BY series_id
                   )'''
            )
        except sqlite3.Error:
            pass
        c.execute("DROP INDEX IF EXISTS idx_pending_reviews_series_id")
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_reviews_series_id "
            "ON pending_reviews(series_id)"
        )
        migrated_index = True
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_pending_reviews_state ON pending_reviews(state)"
    )
    if migrated_index:
        # Le `DELETE` ci-dessus ouvre une transaction qui absorbe le DDL qui
        # suit : appelée depuis un chemin de LECTURE (`clean_orphaned_cache`,
        # une liste de reviews), la migration était annulée par le `close()`
        # sans `commit()`, puis rejouée à chaque appel — en prenant un verrou
        # d'écriture depuis une lecture.
        try:
            c.connection.commit()
        except sqlite3.Error as exc:
            logging.warning(
                "[DB] migration d'index pending_reviews non validée : %s",
                safe_exc_str(exc),
            )
    _schema_done("pending_reviews_tables")


def record_enrichment_telemetry(used_providers):
    """
    Télémétrie lifetime après un enrichissement réussi :
    - series_enriched += 1
    - matches_won += nombre de scrapers utiles (used_providers)
    - +1 win par scraper dans used_providers (podium)
    """
    providers = []
    seen = set()
    for raw in used_providers or []:
        pid = _normalize_provider_stat_id(raw)
        if pid and pid not in seen:
            seen.add(pid)
            providers.append(pid)

    match_count = len(providers)
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_lifetime_stats_table(c)
    _ensure_provider_stats_table(c)

    c.execute(
        '''INSERT INTO lifetime_stats (stat_key, value) VALUES ('series_enriched', 1)
           ON CONFLICT(stat_key) DO UPDATE SET value = value + 1'''
    )
    if match_count:
        c.execute(
            '''INSERT INTO lifetime_stats (stat_key, value) VALUES ('matches_won', ?)
               ON CONFLICT(stat_key) DO UPDATE SET value = value + excluded.value''',
            (match_count,),
        )
        for pid in providers:
            c.execute(
                '''INSERT INTO provider_stats (provider_id, wins) VALUES (?, 1)
                   ON CONFLICT(provider_id) DO UPDATE SET wins = wins + 1''',
                (pid,),
            )

    conn.commit()
    conn.close()
    return {
        "series_enriched_delta": 1,
        "matches_won_delta": match_count,
        "series_missed_delta": 0,
    }


def record_enrichment_miss():
    """Télémétrie lifetime : +1 quand MetaKavita ne trouve rien (NOT_FOUND)."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_lifetime_stats_table(c)
    c.execute(
        '''INSERT INTO lifetime_stats (stat_key, value) VALUES ('series_missed', 1)
           ON CONFLICT(stat_key) DO UPDATE SET value = value + 1'''
    )
    conn.commit()
    conn.close()
    return {
        "series_enriched_delta": 0,
        "matches_won_delta": 0,
        "series_missed_delta": 1,
    }


def get_lifetime_stats():
    """Retourne compteurs lifetime (0 si absents), y compris télémétrie review manuelle."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_lifetime_stats_table(c)
    c.execute("SELECT stat_key, value FROM lifetime_stats")
    rows = {row[0]: row[1] for row in c.fetchall()}
    conn.close()

    def _as_int(key, default=0):
        try:
            return int(rows.get(key, default) or 0)
        except (TypeError, ValueError):
            return default

    def _as_float(key, default=0.0):
        try:
            return float(rows.get(key, default) or 0)
        except (TypeError, ValueError):
            return default

    return {
        "series_enriched": _as_int("series_enriched"),
        "matches_won": _as_int("matches_won"),
        "series_missed": _as_int("series_missed"),
        "covers_applied": _as_int("covers_applied"),
        "locks_sealed": _as_int("locks_sealed"),
        "runs_batch": _as_int("runs_batch"),
        "runs_webhook": _as_int("runs_webhook"),
        "runs_auto": _as_int("runs_auto"),
        "runs_row": _as_int("runs_row"),
        "runs_workshop": _as_int("runs_workshop"),
        "workshop_units": _as_int("workshop_units"),
        "workshop_reviews": _as_int("workshop_reviews"),
        "workshop_magic": _as_int("workshop_magic"),
        "workshop_edits": _as_int("workshop_edits"),
        "workshop_resets": _as_int("workshop_resets"),
        "auto_sync_waves": _as_int("auto_sync_waves"),
        "auto_sync_waves_stopped": _as_int("auto_sync_waves_stopped"),
        "auto_sync_waves_scan": _as_int("auto_sync_waves_scan"),
        "auto_sync_waves_interval": _as_int("auto_sync_waves_interval"),
        "auto_sync_series": _as_int("auto_sync_series"),
        "auto_sync_ok": _as_int("auto_sync_ok"),
        "auto_sync_errors": _as_int("auto_sync_errors"),
        "auto_sync_review": _as_int("auto_sync_review"),
        "auto_sync_relock": _as_int("auto_sync_relock"),
        "auto_sync_stopped": _as_int("auto_sync_stopped"),
        "manual_reviews": _as_int("manual_reviews"),
        "manual_skips": _as_int("manual_skips"),
        "manual_top1_accepts": _as_int("manual_top1_accepts"),
        "manual_score_sum": _as_float("manual_score_sum"),
        "manual_score_n": _as_int("manual_score_n"),
        "manual_field_edits": _as_int("manual_field_edits"),
        "manual_fusions": _as_int("manual_fusions"),
        "manual_weak_picks": _as_int("manual_weak_picks"),
        "manual_researches": _as_int("manual_researches"),
        "manual_purges": _as_int("manual_purges"),
        "manual_super_confirms": _as_int("manual_super_confirms"),
    }


def _bump_lifetime_stat(c, key, delta):
    try:
        if delta is None or float(delta) == 0:
            return
    except (TypeError, ValueError):
        return
    c.execute(
        '''INSERT INTO lifetime_stats (stat_key, value) VALUES (?, ?)
           ON CONFLICT(stat_key) DO UPDATE SET value = value + excluded.value''',
        (key, delta),
    )


# Gestes hors enrichissement / hors review : allowlist pour ne pas inventer de clés.
_LIFETIME_EVENT_KEYS = frozenset({
    "covers_applied",
    "locks_sealed",
    "runs_batch",
    "runs_webhook",
    "runs_auto",
    "runs_row",
    "runs_workshop",
    "workshop_units",
    "workshop_reviews",
    "workshop_magic",
    "workshop_edits",
    "workshop_resets",
})

_RUN_ORIGIN_KEYS = {
    "batch": "runs_batch",
    "webhook": "runs_webhook",
    "auto": "runs_auto",
    "row": "runs_row",
    "workshop": "runs_workshop",
}


def record_lifetime_event(key, delta=1):
    """Incrémente un compteur lifetime listé. Inconnu ou delta 0 : no-op."""
    if key not in _LIFETIME_EVENT_KEYS:
        return 0
    try:
        n = int(delta or 0)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_lifetime_stats_table(c)
    _bump_lifetime_stat(c, key, n)
    conn.commit()
    conn.close()
    return n


def record_run_origin(origin):
    """+1 sur l'origine d'une écriture Kavita (lot / webhook / auto / clic ligne)."""
    key = _RUN_ORIGIN_KEYS.get(str(origin or "").strip().lower())
    if not key:
        return 0
    return record_lifetime_event(key, 1)


def record_manual_review_telemetry(
    score,
    is_top1,
    field_edits=0,
    *,
    fused=False,
    weak_pick=False,
    super_review=False,
):
    """
    Télémétrie après Confirm d'une review manuelle :
    - manual_reviews += 1
    - manual_score_sum += score
    - manual_top1_accepts += 1 si is_top1
    - manual_field_edits += field_edits
    - manual_fusions / manual_weak_picks / manual_super_confirms selon flags
    """
    try:
        score_val = float(score or 0)
    except (TypeError, ValueError):
        score_val = 0.0
    if score_val != score_val:  # NaN
        score_val = 0.0
    try:
        edits = max(0, int(field_edits or 0))
    except (TypeError, ValueError):
        edits = 0
    top1 = 1 if is_top1 else 0
    fusion_delta = 1 if fused else 0
    weak_delta = 1 if weak_pick else 0
    super_delta = 1 if super_review else 0

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_lifetime_stats_table(c)
    _bump_lifetime_stat(c, "manual_reviews", 1)
    _bump_lifetime_stat(c, "manual_score_sum", score_val)
    # Dénominateur distinct du nombre de reviews : une confirmation dont le
    # candidat n'a pas de score (scraper communautaire qui n'appelle pas
    # attach_match_score) entrerait à 0,00 et diluerait la moyenne des autres.
    if score_val > 0:
        _bump_lifetime_stat(c, "manual_score_n", 1)
    if top1:
        _bump_lifetime_stat(c, "manual_top1_accepts", 1)
    if edits:
        _bump_lifetime_stat(c, "manual_field_edits", edits)
    if fusion_delta:
        _bump_lifetime_stat(c, "manual_fusions", fusion_delta)
    if weak_delta:
        _bump_lifetime_stat(c, "manual_weak_picks", weak_delta)
    if super_delta:
        _bump_lifetime_stat(c, "manual_super_confirms", super_delta)
    conn.commit()
    conn.close()
    return {
        "manual_reviews_delta": 1,
        "manual_skips_delta": 0,
        "manual_top1_accepts_delta": top1,
        "manual_score_sum_delta": score_val,
        "manual_score_n_delta": 1 if score_val > 0 else 0,
        "manual_field_edits_delta": edits,
        "manual_fusions_delta": fusion_delta,
        "manual_weak_picks_delta": weak_delta,
        "manual_super_confirms_delta": super_delta,
    }


def record_manual_research_telemetry():
    """Télémétrie : +1 re-recherche titre depuis la review manuelle."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_lifetime_stats_table(c)
    _bump_lifetime_stat(c, "manual_researches", 1)
    conn.commit()
    conn.close()
    return {"manual_researches_delta": 1}


def record_manual_purge_telemetry(deleted=0):
    """Télémétrie : +deleted reviews purgées (ou +1 event si deleted inconnu)."""
    try:
        n = max(0, int(deleted or 0))
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        n = 1
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_lifetime_stats_table(c)
    _bump_lifetime_stat(c, "manual_purges", n)
    conn.commit()
    conn.close()
    return {"manual_purges_delta": n}


def get_provider_stats():
    """Retourne {provider_id: wins} trié par wins décroissant."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_provider_stats_table(c)
    c.execute("SELECT provider_id, wins FROM provider_stats ORDER BY wins DESC, provider_id ASC")
    rows = c.fetchall()
    conn.close()
    return {row[0]: int(row[1]) for row in rows}


def _normalize_provider_stat_id(provider_id):
    if not provider_id:
        return None
    pid = str(provider_id).strip()
    if " (" in pid:
        pid = pid.split(" (", 1)[0].strip()
    if not pid or pid.lower() in ("inconnu", "unknown", "none"):
        return None
    return pid


# --- pending_reviews (mode manuel C29) ---

def _pending_review_row_to_dict(row):
    if not row:
        return None
    return {
        "review_id": row[0],
        "series_id": row[1],
        "series_name": row[2],
        "candidates_json": row[3],
        "preview_json": row[4],
        "state": row[5],
        "created_at": row[6],
        "base_provider": row[7],
        "chosen_score": row[8],
        "library_id": row[9] if len(row) > 9 else None,
    }


_PENDING_REVIEW_COLUMNS = (
    "review_id, series_id, series_name, candidates_json, preview_json, "
    "state, created_at, base_provider, chosen_score, library_id"
)


def park_pending_review(
    review_id,
    series_id,
    series_name,
    candidates_json,
    preview_json=None,
    state="awaiting_pick",
    created_at=None,
    base_provider=None,
    chosen_score=None,
    library_id=None,
):
    """
    Park atomique : remplace la review de la série + statut PENDING_REVIEW
    dans une seule transaction (évite file/statut désynchronisés).
    """
    import json
    from datetime import datetime, timezone

    if not os.path.exists(DB_FILE):
        init_db()
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    if not isinstance(candidates_json, str):
        candidates_json = json.dumps(candidates_json, ensure_ascii=False)
    if preview_json is not None and not isinstance(preview_json, str):
        preview_json = json.dumps(preview_json, ensure_ascii=False)

    sid = int(series_id)
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    # Une review de cette série est écrasée : c'est voulu sur un re-scrape forcé
    # (l'appelant vient de reconstruire des candidats frais), mais l'utilisateur
    # peut avoir la modale ouverte sur l'ancien identifiant. La perte ne doit pas
    # être silencieuse — c'est le seul indice si un chemin non forcé y revenait.
    c.execute(
        "SELECT review_id, state FROM pending_reviews WHERE series_id = ?", (sid,)
    )
    replaced = c.fetchone()
    if replaced and replaced[0] != review_id:
        logging.warning(
            "⚠️ [Review] Série %s : review %s (%s) remplacée par %s — "
            "un examen en cours sur l'ancien identifiant est perdu.",
            sid,
            replaced[0],
            replaced[1] or "awaiting_pick",
            review_id,
        )
    c.execute("DELETE FROM pending_reviews WHERE series_id = ?", (sid,))
    c.execute(
        '''INSERT INTO pending_reviews
           (review_id, series_id, series_name, candidates_json, preview_json,
            state, created_at, base_provider, chosen_score, library_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            review_id,
            sid,
            series_name,
            candidates_json,
            preview_json,
            state or "awaiting_pick",
            created_at,
            base_provider,
            chosen_score,
            library_id,
        ),
    )
    c.execute(
        '''INSERT INTO series_cache (series_id, status) VALUES (?, 'PENDING_REVIEW')
           ON CONFLICT(series_id) DO UPDATE SET status=excluded.status''',
        (sid,),
    )
    conn.commit()
    conn.close()
    return review_id


def close_pending_review(review_id, new_status="PENDING", *, skip_telemetry=False):
    """
    Clôture atomique : delete review + update statut série (+ télémétrie skip optionnelle).
    Retourne le dict de la review avant suppression, ou None si introuvable.
    """
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    _ensure_lifetime_stats_table(c)
    c.execute(
        f'''SELECT {_PENDING_REVIEW_COLUMNS}
           FROM pending_reviews WHERE review_id = ?''',
        (review_id,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    review = _pending_review_row_to_dict(row)
    sid = int(review["series_id"])
    c.execute("DELETE FROM pending_reviews WHERE review_id = ?", (review_id,))
    c.execute(
        '''INSERT INTO series_cache (series_id, status) VALUES (?, ?)
           ON CONFLICT(series_id) DO UPDATE SET status=excluded.status''',
        (sid, new_status),
    )
    if skip_telemetry:
        _bump_lifetime_stat(c, "manual_skips", 1)
    conn.commit()
    conn.close()
    return review


def get_pending_review(review_id):
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    c.execute(
        f'''SELECT {_PENDING_REVIEW_COLUMNS}
           FROM pending_reviews WHERE review_id = ?''',
        (review_id,),
    )
    row = c.fetchone()
    conn.close()
    return _pending_review_row_to_dict(row)


def list_pending_reviews(state=None, limit=200):
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    if state:
        c.execute(
            f'''SELECT {_PENDING_REVIEW_COLUMNS}
               FROM pending_reviews WHERE state = ?
               ORDER BY created_at ASC LIMIT ?''',
            (state, int(limit)),
        )
    else:
        c.execute(
            f'''SELECT {_PENDING_REVIEW_COLUMNS}
               FROM pending_reviews
               ORDER BY created_at ASC LIMIT ?''',
            (int(limit),),
        )
    rows = c.fetchall()
    conn.close()
    return [_pending_review_row_to_dict(r) for r in rows]


def update_pending_review(review_id, *, expected_state=None, **fields):
    """
    Met à jour les colonnes fournies d'une pending review. Retourne True si une ligne touchée.

    `expected_state` transforme l'écriture en compare-and-swap : l'UPDATE ne
    s'applique que si la ligne est encore dans cet état. Indispensable dès que
    l'appelant a décidé quoi écrire d'après une lecture antérieure — un état
    relu puis écrit en deux temps peut changer entre les deux (l'utilisateur
    choisit un fournisseur pendant qu'un scrape se termine) et l'appelant
    imposerait alors une décision périmée. Un retour False signifie « rien
    écrit » : à l'appelant de relire et de recalculer.
    """
    import json

    allowed = {
        "series_id", "series_name", "candidates_json", "preview_json",
        "state", "created_at", "base_provider", "chosen_score", "library_id",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    if "candidates_json" in updates and not isinstance(updates["candidates_json"], str):
        updates["candidates_json"] = json.dumps(updates["candidates_json"], ensure_ascii=False)
    if "preview_json" in updates and updates["preview_json"] is not None and not isinstance(updates["preview_json"], str):
        updates["preview_json"] = json.dumps(updates["preview_json"], ensure_ascii=False)

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    cols = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [review_id]
    if expected_state is None:
        c.execute(f"UPDATE pending_reviews SET {cols} WHERE review_id = ?", values)
    else:
        c.execute(
            f"UPDATE pending_reviews SET {cols} WHERE review_id = ? AND state = ?",
            values + [expected_state],
        )
    touched = c.rowcount > 0
    conn.commit()
    conn.close()
    return touched


def delete_pending_by_series(series_id):
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    c.execute("DELETE FROM pending_reviews WHERE series_id = ?", (int(series_id),))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def count_pending_reviews(state=None):
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    if state:
        c.execute("SELECT COUNT(*) FROM pending_reviews WHERE state = ?", (state,))
    else:
        c.execute("SELECT COUNT(*) FROM pending_reviews")
    n = int(c.fetchone()[0])
    conn.close()
    return n


def purge_all_pending_reviews(reset_status="PENDING"):
    """
    Vide toute la file `pending_reviews`.

    Remet le statut des séries concernées à `reset_status` (défaut PENDING)
    uniquement si elles étaient encore en PENDING_REVIEW.
    Retourne ``{"deleted": int, "series_ids": list[int]}``.
    """
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    c.execute("SELECT DISTINCT series_id FROM pending_reviews")
    series_ids = [int(r[0]) for r in c.fetchall() if r and r[0] is not None]
    c.execute("DELETE FROM pending_reviews")
    deleted = int(c.rowcount or 0)
    if series_ids and reset_status:
        placeholders = ",".join("?" for _ in series_ids)
        c.execute(
            f'''UPDATE series_cache SET status = ?
                WHERE series_id IN ({placeholders}) AND status = 'PENDING_REVIEW' ''',
            [reset_status, *series_ids],
        )
    conn.commit()
    conn.close()
    return {"deleted": deleted, "series_ids": series_ids}

def update_status(series_id, status):
    conn = _connect()
    c = conn.cursor()
    c.execute('''INSERT INTO series_cache (series_id, status) VALUES (?, ?)
                 ON CONFLICT(series_id) DO UPDATE SET status=excluded.status''', (series_id, status))
    conn.commit()
    conn.close()

def set_cover_manual(series_id, manual: bool = True):
    """Marque (ou libère) la provenance manuelle de la couverture d'une série.

    Écrit uniquement `cover_manual` : ni le statut d'une ligne existante, ni les
    champs ciblés. C'est ce qui distingue ce marqueur de l'ancien détournement
    de `targeted_fields`, qui décochait `cover` dans la config de l'utilisateur
    et rendait la protection invisible autant qu'irréversible sans clic.
    """
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_schema(c)
    c.execute('''INSERT INTO series_cache (series_id, status, cover_manual) VALUES (?, 'PENDING', ?)
                 ON CONFLICT(series_id) DO UPDATE SET cover_manual=excluded.cover_manual''',
              (int(series_id), 1 if manual else 0))
    conn.commit()
    conn.close()


def is_cover_manual(series_id) -> bool:
    """Provenance manuelle de la couverture, lue à la source (sans passer par
    l'inventaire complet de `get_all_cached_data`)."""
    if not os.path.exists(DB_FILE):
        return False
    conn = _connect()
    c = conn.cursor()
    _ensure_schema(c)
    row = c.execute(
        "SELECT cover_manual FROM series_cache WHERE series_id = ?", (int(series_id),)
    ).fetchone()
    conn.close()
    return bool(row[0]) if row and row[0] is not None else False


def set_inventory_excluded(series_id, excluded: bool = True):
    """Exclut (ou réintègre) une série de l'inventaire, sans toucher au reste."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_schema(c)
    c.execute('''INSERT INTO series_cache (series_id, status, inventory_excluded) VALUES (?, 'PENDING', ?)
                 ON CONFLICT(series_id) DO UPDATE SET inventory_excluded=excluded.inventory_excluded''',
              (int(series_id), 1 if excluded else 0))
    conn.commit()
    conn.close()


def get_inventory_excluded_ids() -> set:
    """Identifiants des séries exclues de l'inventaire."""
    if not os.path.exists(DB_FILE):
        return set()
    conn = _connect()
    c = conn.cursor()
    _ensure_schema(c)
    rows = c.execute(
        "SELECT series_id FROM series_cache WHERE inventory_excluded = 1"
    ).fetchall()
    conn.close()
    return {int(r[0]) for r in rows}


def save_series_override(override: SeriesOverride, *, purge_pending: bool = True, status: str = "PENDING"):
    """
    Persiste un SeriesOverride complet en une seule opération atomique.

    Exige un objet à champs nommés plutôt qu'une liste d'arguments positionnels
    (l'ancien wrapper `save_forced_overrides` a été retiré) : cela rend beaucoup
    plus visible (à la relecture comme à la complétion IDE) tout champ oublié
    lors de la construction de l'objet — c'est exactement l'angle mort qui avait
    fait disparaître silencieusement `publisher_pref` dans l'ancienne route
    `/save-override`.

    `purge_pending` : True (défaut) purge les reviews manuelles de la série —
    comportement historique après un override UI. False pour une re-recherche
    depuis la modale de review (même review_id conservé).

    `status` : statut cache écrit (défaut PENDING). Passer PENDING_REVIEW
    lors d'une re-recherche manuelle pour ne pas casser le badge.
    """
    conn = _connect()
    c = conn.cursor()
    f_id = override.forced_id.strip() if override.forced_id else None
    a_title = override.alternative_title.strip() if override.alternative_title else None
    new_status = (status or "PENDING").strip() or "PENDING"

    _ensure_schema(c)

    c.execute('''INSERT INTO series_cache (series_id, status, forced_id, alternative_title, forced_provider, targeted_fields, publisher_pref, alt_title_langs) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(series_id) DO UPDATE SET 
                 forced_id=excluded.forced_id, 
                 alternative_title=excluded.alternative_title, 
                 forced_provider=excluded.forced_provider,
                 targeted_fields=excluded.targeted_fields,
                 publisher_pref=excluded.publisher_pref,
                 alt_title_langs=excluded.alt_title_langs,
                 status=excluded.status''',
              (override.series_id, new_status, f_id, a_title, override.forced_provider, override.targeted_fields, override.publisher_pref, override.alt_title_langs or ""))
    conn.commit()
    conn.close()
    # Override utilisateur : purge toute review manuelle orpheline pour cette série
    if purge_pending:
        try:
            delete_pending_by_series(override.series_id)
        except Exception as e:
            logging.debug(
                "override orphan pending_review purge failed (series_id=%s): %s",
                override.series_id,
                safe_exc_str(e),
            )

def reset_errors():
    """Réinitialise les statuts NOT_FOUND et IGNORED en PENDING."""
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE series_cache SET status = 'PENDING' WHERE status IN ('NOT_FOUND', 'IGNORED')")
    conn.commit()
    conn.close()

def get_all_cached_data():
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    
    _ensure_schema(c)
        
    c.execute("SELECT series_id, status, forced_id, alternative_title, forced_provider, targeted_fields, publisher_pref, alt_title_langs, cover_manual, inventory_excluded FROM series_cache")
    rows = c.fetchall()
    conn.close()
    return {row[0]: {
        'status': row[1], 
        'forced_id': row[2], 
        'alternative_title': row[3],
        'forced_provider': row[4],
        'targeted_fields': row[5],
        'publisher_pref': row[6] if len(row) > 6 else 'GLOBAL',
        'alt_title_langs': row[7] if len(row) > 7 else '',
        'cover_manual': bool(row[8]) if len(row) > 8 else False,
        'inventory_excluded': bool(row[9]) if len(row) > 9 else False,
    } for row in rows}

#: Tables portant une ligne par série, à purger avec elle. `series_cache` et
#: `pending_reviews` étaient les deux seules nettoyées : une série supprimée dans
#: Kavita laissait derrière elle son rapport de tomes, ses flags d'audit, son
#: attendu forcé et l'état de chacun de ses tomes. Conséquences visibles :
#: `count_volume_units_by_status()` gonflait la progression avec des tomes
#: disparus, et `get_volume_report_hygiene_map()` désérialisait le JSON de ces
#: lignes mortes à chaque rendu du tableau de bord.
_SERIES_SCOPED_TABLES = (
    "series_cache",
    "pending_reviews",
    "volume_report_cache",
    "series_audit_flags",
    "hygiene_catalog_overrides",
    "volume_unit_cache",
    "auto_sync_known_series",
    "volume_unit_overrides",
    "workshop_history",
    "workshop_series_overrides",
)

#: SQLite plafonne le nombre de paramètres liés (999 sur les builds anciens) :
#: une bibliothèque qui perd un millier de séries d'un coup ferait exploser un
#: `IN (...)` d'un seul tenant.
_DELETE_CHUNK = 400


def clean_orphaned_cache(active_ids):
    """Retire du cache les séries absentes de `active_ids`.

    `series_cache` porte les réglages saisis à la main (id forcé, champs ciblés,
    préférence éditeur, couverture manuelle) et la suppression entraîne celle des
    reviews en attente : un inventaire Kavita vide n'est donc jamais un feu vert
    suffisant. Les appelants doivent en plus vérifier
    `KavitaAPI.last_inventory_complete`.
    """
    if not active_ids:
        logging.warning(
            "[Cache] Purge des orphelines ignorée : inventaire Kavita vide "
            "(refus de supprimer tout le cache et les reviews en attente)."
        )
        return 0
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    _ensure_library_audit_tables(c)
    _ensure_volume_unit_tables(c)
    _ensure_workshop_tables(c)
    _ensure_auto_sync_tables(c)
    c.execute("SELECT series_id FROM series_cache")
    cached_ids = {row[0] for row in c.fetchall()}
    try:
        c.execute("SELECT series_id FROM volume_report_cache")
        cached_ids.update(row[0] for row in c.fetchall())
    except Exception:
        pass
    orphans = cached_ids - active_ids
    if orphans:
        orphan_list = list(orphans)
        for start in range(0, len(orphan_list), _DELETE_CHUNK):
            chunk = orphan_list[start:start + _DELETE_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            for table in _SERIES_SCOPED_TABLES:
                c.execute(
                    f"DELETE FROM {table} WHERE series_id IN ({placeholders})",
                    chunk,
                )
        try:
            import json
            orphans_int = {int(x) for x in orphans}
            c.execute("SELECT library_id, group_id, payload_json FROM duplicate_group_cache")
            for lib_id, grp_id, p_json in c.fetchall():
                if not p_json:
                    continue
                try:
                    p = json.loads(p_json)
                    sids = p.get("series_ids") or []
                    remaining = [s for s in sids if int(s) not in orphans_int]
                    if len(remaining) < 2:
                        c.execute("DELETE FROM duplicate_group_cache WHERE library_id = ? AND group_id = ?", (lib_id, grp_id))
                    elif len(remaining) < len(sids):
                        p["names"] = [p["names"][i] for i, s in enumerate(sids) if int(s) not in orphans_int and "names" in p and i < len(p["names"])]
                        p["folder_paths"] = [p["folder_paths"][i] for i, s in enumerate(sids) if int(s) not in orphans_int and "folder_paths" in p and i < len(p["folder_paths"])]
                        if "volume_counts" in p:
                            p["volume_counts"] = [p["volume_counts"][i] for i, s in enumerate(sids) if int(s) not in orphans_int and i < len(p["volume_counts"])]
                        if "chapter_counts" in p:
                            p["chapter_counts"] = [p["chapter_counts"][i] for i, s in enumerate(sids) if int(s) not in orphans_int and i < len(p["chapter_counts"])]
                        p["series_ids"] = remaining
                        c.execute(
                            "UPDATE duplicate_group_cache SET payload_json = ? WHERE library_id = ? AND group_id = ?",
                            (json.dumps(p, ensure_ascii=False), lib_id, grp_id),
                        )
                except Exception:
                    pass
        except Exception:
            pass
        conn.commit()
        try:
            from services import kavita_cover_cache

            for sid in orphan_list:
                kavita_cover_cache.purge_series(sid)
        except Exception:
            pass
    conn.close()
    return len(orphans)


def purge_single_series_from_all_caches(series_id: int) -> int:
    """Supprime une unique série de toutes les tables de cache sans affecter les autres.

    Contrairement à `clean_orphaned_cache` (qui attend l'ensemble *complet* des IDs
    Kavita actifs), cette fonction est chirurgicale : elle ne touche que `series_id`
    et laisse toutes les autres séries intactes. À utiliser quand une seule série est
    supprimée (purge-empty, SignalR SeriesRemoved).
    """
    import json

    sid = int(series_id)
    if not os.path.exists(DB_FILE):
        return 0
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    _ensure_library_audit_tables(c)
    _ensure_volume_unit_tables(c)
    _ensure_workshop_tables(c)
    _ensure_auto_sync_tables(c)

    deleted = 0
    for table in _SERIES_SCOPED_TABLES:
        c.execute(f"DELETE FROM {table} WHERE series_id = ?", (sid,))
        deleted += c.rowcount

    # Nettoyage chirurgical de duplicate_group_cache (séries stockées en JSON).
    try:
        c.execute(
            "SELECT library_id, group_id, payload_json FROM duplicate_group_cache"
        )
        for lib_id, grp_id, p_json in c.fetchall():
            if not p_json:
                continue
            try:
                p = json.loads(p_json)
                sids = p.get("series_ids") or []
                int_sids = [int(s) for s in sids]
                if sid not in int_sids:
                    continue
                remaining_idx = [i for i, s in enumerate(int_sids) if s != sid]
                if len(remaining_idx) < 2:
                    c.execute(
                        "DELETE FROM duplicate_group_cache "
                        "WHERE library_id = ? AND group_id = ?",
                        (lib_id, grp_id),
                    )
                else:
                    for key in ("names", "folder_paths", "volume_counts",
                                "chapter_counts", "library_ids"):
                        lst = p.get(key)
                        if isinstance(lst, list):
                            p[key] = [lst[i] for i in remaining_idx if i < len(lst)]
                    p["series_ids"] = [int_sids[i] for i in remaining_idx]
                    c.execute(
                        "UPDATE duplicate_group_cache SET payload_json = ? "
                        "WHERE library_id = ? AND group_id = ?",
                        (json.dumps(p, ensure_ascii=False), lib_id, grp_id),
                    )
            except Exception:
                pass
    except Exception:
        pass

    conn.commit()
    conn.close()

    try:
        from services import kavita_cover_cache
        kavita_cover_cache.purge_series(sid)
    except Exception:
        pass

    return deleted


def save_volume_report_cache(series_id: int, report: dict):
    """Persist compact volume hygiene summary for badges (not full units)."""
    import json
    from datetime import datetime, timezone

    if not os.path.exists(DB_FILE):
        init_db()
    cat = report.get("catalog") or {}
    summary = {
        "series_name": report.get("series_name") or "",
        "structure": report.get("structure"),
        "is_oneshot": report.get("is_oneshot"),
        "gaps": report.get("gaps") or [],
        "missing_volumes": report.get("missing_volumes") or [],
        "catalog": cat,
        "stats": report.get("stats") or {},
        "badge": report.get("badge") or "—",
        "publication_status": (
            report.get("publication_status")
            or cat.get("publication_status")
            or "UNKNOWN"
        ),
        # C66 : unité de la série (tomes ou chapitres), état de complétion et
        # attendu forcé, nécessaires au code couleur du dashboard sans relire
        # le rapport complet.
        "unit_mode": report.get("unit_mode") or "volumes",
        "primary": report.get("primary") or {},
        "completion": report.get("completion") or {},
        "chapters": report.get("chapters") or {},
    }
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        '''INSERT INTO volume_report_cache(series_id, summary_json, badge, structure, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(series_id) DO UPDATE SET
             summary_json=excluded.summary_json,
             badge=excluded.badge,
             structure=excluded.structure,
             updated_at=excluded.updated_at''',
        (
            int(series_id),
            json.dumps(summary, ensure_ascii=False),
            summary["badge"],
            summary.get("structure") or "",
            now,
        ),
    )
    conn.commit()
    conn.close()


def get_volume_report_cache(series_id: int):
    import json

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        "SELECT summary_json, badge, structure, updated_at FROM volume_report_cache WHERE series_id = ?",
        (int(series_id),),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    try:
        summary = json.loads(row[0] or "{}")
    except (TypeError, ValueError):
        summary = {}
    summary.setdefault("badge", row[1] or "—")
    summary.setdefault("structure", row[2] or "")
    summary["updated_at"] = row[3]
    return summary


def get_volume_report_badges(series_ids=None) -> dict:
    """Map series_id -> badge string for dashboard (optional id filter)."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    if series_ids:
        ids = [int(x) for x in series_ids]
        placeholders = ",".join("?" for _ in ids)
        c.execute(
            f"SELECT series_id, badge FROM volume_report_cache WHERE series_id IN ({placeholders})",
            ids,
        )
    else:
        c.execute("SELECT series_id, badge FROM volume_report_cache")
    out = {row[0]: row[1] or "—" for row in c.fetchall()}
    conn.close()
    return out


def get_volume_report_hygiene_map(series_ids=None) -> dict:
    """Map series_id -> {badge, missing_count, catalog_expected, publication_status}."""
    import json

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    if series_ids:
        ids = [int(x) for x in series_ids]
        ph = ",".join("?" for _ in ids)
        c.execute(
            f"SELECT series_id, badge, summary_json FROM volume_report_cache "
            f"WHERE series_id IN ({ph})",
            ids,
        )
    else:
        c.execute("SELECT series_id, badge, summary_json FROM volume_report_cache")
    out = {}
    for sid, badge, raw in c.fetchall():
        try:
            summary = json.loads(raw or "{}")
        except (TypeError, ValueError):
            summary = {}
        cat = summary.get("catalog") or {}
        stats = summary.get("stats") or {}
        primary = summary.get("primary") or {}
        completion = summary.get("completion") or {}
        # Rapports d'avant C66 : pas de bloc `primary`, on retombe sur les tomes.
        missing = primary.get("missing") or summary.get("missing_volumes") or []
        out[sid] = {
            "badge": badge or summary.get("badge") or "—",
            "missing_count": len(missing),
            "catalog_expected": cat.get("expected"),
            "publication_status": (
                summary.get("publication_status")
                or cat.get("publication_status")
                or "UNKNOWN"
            ),
            "series_name": summary.get("series_name") or "",
            "missing_volumes": list(missing),
            "missing_label": primary.get("missing_label") or "",
            "catalog_status": cat.get("status") or "unknown",
            "catalog_provider": cat.get("provider") or "",
            "catalog_reason": cat.get("reason") or "",
            "kavita_count": stats.get("kavita_count"),
            "unit_mode": summary.get("unit_mode") or "volumes",
            "unit": primary.get("unit") or cat.get("unit") or "volumes",
            "primary_count": primary.get("count", stats.get("kavita_count")),
            "primary_expected": primary.get("expected", cat.get("expected")),
            "chapter_count": (summary.get("chapters") or {}).get("count") or 0,
            "completion_state": completion.get("state") or "unknown",
            "completion_ratio": completion.get("ratio"),
            "forced_expected": bool(
                completion.get("forced")
                or cat.get("reason") == "manual"
                or cat.get("provider") == "MANUAL"
            ),
        }
    conn.close()
    return out


def get_catalog_expected_override(series_id: int):
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        "SELECT expected FROM hygiene_catalog_overrides WHERE series_id = ?",
        (int(series_id),),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    try:
        n = int(row[0])
        return n if n >= 1 else None
    except (TypeError, ValueError):
        return None


def set_catalog_expected_override(series_id: int, expected):
    """Set or clear (expected=None) manual catalogue expected for a series."""
    from datetime import datetime, timezone

    if not os.path.exists(DB_FILE):
        init_db()
    sid = int(series_id)
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    if expected is None:
        c.execute("DELETE FROM hygiene_catalog_overrides WHERE series_id = ?", (sid,))
    else:
        n = int(expected)
        if n < 1:
            raise ValueError("expected must be >= 1")
        now = datetime.now(timezone.utc).isoformat()
        c.execute(
            """INSERT INTO hygiene_catalog_overrides(series_id, expected, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(series_id) DO UPDATE SET
                 expected=excluded.expected,
                 updated_at=excluded.updated_at""",
            (sid, n, now),
        )
    conn.commit()
    conn.close()
    return expected


def list_catalog_expected_overrides() -> dict:
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute("SELECT series_id, expected FROM hygiene_catalog_overrides")
    out = {int(r[0]): int(r[1]) for r in c.fetchall()}
    conn.close()
    return out


_DUP_META_GROUP_ID = "__meta__"


def save_duplicate_groups_cache(library_id, groups: list):
    import json
    from datetime import datetime, timezone

    if not os.path.exists(DB_FILE):
        init_db()
    lib = str(library_id)
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        "SELECT group_id, payload_json FROM duplicate_group_cache WHERE library_id = ?",
        (lib,),
    )
    old_sids = []
    for (gid, payload) in c.fetchall():
        if gid == _DUP_META_GROUP_ID:
            continue
        try:
            old = json.loads(payload or "{}")
            old_sids.extend(old.get("series_ids") or [])
        except (TypeError, ValueError):
            pass
    if old_sids:
        ph = ",".join("?" for _ in old_sids)
        c.execute(
            f"UPDATE series_audit_flags SET duplicate_group_id = NULL "
            f"WHERE series_id IN ({ph})",
            [int(x) for x in old_sids],
        )
    c.execute("DELETE FROM duplicate_group_cache WHERE library_id = ?", (lib,))
    # Sentinel so "scanned, zero groups" ≠ "never scanned"
    c.execute(
        '''INSERT INTO duplicate_group_cache(library_id, group_id, payload_json, updated_at)
           VALUES (?, ?, ?, ?)''',
        (
            lib,
            _DUP_META_GROUP_ID,
            json.dumps({"scanned": True, "count": len(groups or [])}, ensure_ascii=False),
            now,
        ),
    )
    for g in groups or []:
        gid = g.get("group_id") or ""
        if not gid or gid == _DUP_META_GROUP_ID:
            continue
        c.execute(
            '''INSERT INTO duplicate_group_cache(library_id, group_id, payload_json, updated_at)
               VALUES (?, ?, ?, ?)''',
            (lib, gid, json.dumps(g, ensure_ascii=False), now),
        )
        for sid in g.get("series_ids") or []:
            c.execute(
                '''INSERT INTO series_audit_flags(series_id, has_external_id, duplicate_group_id, updated_at)
                   VALUES (?, NULL, ?, ?)
                   ON CONFLICT(series_id) DO UPDATE SET
                     duplicate_group_id=excluded.duplicate_group_id,
                     updated_at=excluded.updated_at''',
                (int(sid), gid, now),
            )
    conn.commit()
    conn.close()


def has_duplicate_groups_cache(library_id) -> bool:
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        "SELECT 1 FROM duplicate_group_cache WHERE library_id = ? LIMIT 1",
        (str(library_id),),
    )
    row = c.fetchone()
    conn.close()
    return bool(row)


def get_duplicate_groups_cache(library_id) -> list:
    import json

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        "SELECT group_id, payload_json FROM duplicate_group_cache WHERE library_id = ? ORDER BY group_id",
        (str(library_id),),
    )
    rows = c.fetchall()
    conn.close()
    out = []
    for (gid, payload) in rows:
        if gid == _DUP_META_GROUP_ID:
            continue
        try:
            out.append(json.loads(payload))
        except (TypeError, ValueError):
            continue
    return out


def set_series_external_id_flags(flags: dict):
    """flags: {series_id: bool has_external_id}"""
    from datetime import datetime, timezone

    if not flags:
        return
    if not os.path.exists(DB_FILE):
        init_db()
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    for sid, has in flags.items():
        c.execute(
            '''INSERT INTO series_audit_flags(series_id, has_external_id, duplicate_group_id, updated_at)
               VALUES (?, ?, NULL, ?)
               ON CONFLICT(series_id) DO UPDATE SET
                 has_external_id=excluded.has_external_id,
                 updated_at=excluded.updated_at''',
            (int(sid), 1 if has else 0, now),
        )
    conn.commit()
    conn.close()


def get_series_audit_flags(series_ids=None) -> dict:
    """{series_id: {has_external_id, duplicate_group_id}}"""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    if series_ids:
        ids = [int(x) for x in series_ids]
        ph = ",".join("?" for _ in ids)
        c.execute(
            f"SELECT series_id, has_external_id, duplicate_group_id FROM series_audit_flags WHERE series_id IN ({ph})",
            ids,
        )
    else:
        c.execute(
            "SELECT series_id, has_external_id, duplicate_group_id FROM series_audit_flags"
        )
    out = {}
    for sid, has_ext, dup in c.fetchall():
        out[sid] = {
            "has_external_id": None if has_ext is None else bool(has_ext),
            "duplicate_group_id": dup,
        }
    conn.close()
    return out

def set_hygiene_library_meta(library_id, counts: dict, scanned_at=None):
    import json
    from datetime import datetime, timezone

    if not os.path.exists(DB_FILE):
        init_db()
    lib = str(library_id)
    now = scanned_at or datetime.now(timezone.utc).isoformat()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        """INSERT INTO hygiene_library_meta(library_id, scanned_at, counts_json)
           VALUES (?, ?, ?)
           ON CONFLICT(library_id) DO UPDATE SET
             scanned_at=excluded.scanned_at,
             counts_json=excluded.counts_json""",
        (lib, now, json.dumps(counts or {}, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def get_hygiene_library_meta(library_id):
    import json

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        "SELECT scanned_at, counts_json FROM hygiene_library_meta WHERE library_id = ?",
        (str(library_id),),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    try:
        counts = json.loads(row[1] or "{}")
    except (TypeError, ValueError):
        counts = {}
    return {"library_id": str(library_id), "scanned_at": row[0], "counts": counts}


def list_hygiene_library_meta() -> list:
    """Toutes les analyses Inventaire encore en base (clé `all` comprise)."""
    import json

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute("SELECT library_id, scanned_at, counts_json FROM hygiene_library_meta")
    rows = []
    for library_id, scanned_at, raw in c.fetchall():
        try:
            counts = json.loads(raw or "{}")
        except (TypeError, ValueError):
            counts = {}
        rows.append({
            "library_id": str(library_id),
            "scanned_at": scanned_at,
            "counts": counts,
        })
    conn.close()
    return rows


def save_dup_dismissal(library_id, series_ids, reason: str):
    import json
    from datetime import datetime, timezone

    from services.library_audit.duplicates import dup_group_key

    if reason not in ("not_duplicate", "ignored"):
        raise ValueError("invalid dismissal reason")
    ids = [int(x) for x in series_ids]
    if len(ids) < 2:
        raise ValueError("need at least 2 series_ids")
    gkey = dup_group_key(ids)
    if not os.path.exists(DB_FILE):
        init_db()
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        """INSERT INTO hygiene_dup_dismissals(library_id, group_key, series_ids_json, reason, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(library_id, group_key) DO UPDATE SET
             series_ids_json=excluded.series_ids_json,
             reason=excluded.reason,
             updated_at=excluded.updated_at""",
        (str(library_id), gkey, json.dumps(sorted(ids)), reason, now),
    )
    conn.commit()
    conn.close()
    return gkey


def delete_dup_dismissal(library_id, series_ids=None, group_key=None):
    from services.library_audit.duplicates import dup_group_key

    if not os.path.exists(DB_FILE):
        init_db()
    gkey = group_key
    if not gkey and series_ids:
        gkey = dup_group_key([int(x) for x in series_ids])
    if not gkey:
        raise ValueError("group_key or series_ids required")
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    lib = str(library_id).strip().lower() if library_id is not None else ""
    if lib == "all":
        c.execute(
            "DELETE FROM hygiene_dup_dismissals WHERE group_key = ?",
            (gkey,),
        )
    else:
        c.execute(
            "DELETE FROM hygiene_dup_dismissals WHERE (library_id = ? OR library_id = 'all') AND group_key = ?",
            (str(library_id), gkey),
        )
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


def list_dup_dismissals(library_id=None):
    import json

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    lib = str(library_id).strip().lower() if library_id is not None else ""
    if not lib or lib == "all":
        c.execute(
            "SELECT group_key, series_ids_json, reason, updated_at "
            "FROM hygiene_dup_dismissals"
        )
    else:
        c.execute(
            "SELECT group_key, series_ids_json, reason, updated_at "
            "FROM hygiene_dup_dismissals WHERE library_id = ? OR library_id = 'all'",
            (str(library_id),),
        )
    out = []
    seen = set()
    for gkey, sids, reason, updated in c.fetchall():
        if gkey in seen:
            continue
        seen.add(gkey)
        try:
            ids = json.loads(sids or "[]")
        except (TypeError, ValueError):
            ids = []
        out.append(
            {
                "group_key": gkey,
                "series_ids": ids,
                "reason": reason,
                "updated_at": updated,
            }
        )
    conn.close()
    return out


def list_dismissed_group_keys(library_id=None) -> set:
    return {d["group_key"] for d in list_dup_dismissals(library_id)}


def purge_series_hygiene_cache(series_id: int, *, keep_overrides: bool = False):
    """Remove volume cache + audit flags for a deleted series.

    `keep_overrides` sert à l'exclusion d'inventaire : on efface le rapport pour
    faire disparaître la cartouche, mais l'attendu forcé saisi par l'utilisateur
    doit survivre à une réintégration.
    """
    if not os.path.exists(DB_FILE):
        return
    sid = int(series_id)
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute("DELETE FROM volume_report_cache WHERE series_id = ?", (sid,))
    c.execute("DELETE FROM series_audit_flags WHERE series_id = ?", (sid,))
    if not keep_overrides:
        c.execute("DELETE FROM hygiene_catalog_overrides WHERE series_id = ?", (sid,))
        # Série réellement partie : son état par tome n'a plus d'objet. Une
        # série seulement exclue de l'inventaire, elle, le garde.
        _ensure_volume_unit_tables(c)
        c.execute("DELETE FROM volume_unit_cache WHERE series_id = ?", (sid,))
    conn.commit()
    conn.close()


# ===== Enrichissement par tome / album (issue #27) =====

VOLUME_UNIT_STATES = ("DONE", "NOTHING_FOUND", "FAILED", "SKIPPED")


def save_volume_unit_state(
    series_id: int,
    chapter_id: int,
    status: str,
    *,
    volume_id=None,
    volume_number=None,
    chapter_number=None,
    provider=None,
    written_fields=None,
):
    """Marque une unité traitée. C'est ce qui rend la passe de masse reprenable."""
    import json
    from datetime import datetime, timezone

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_volume_unit_tables(c)
    c.execute(
        """INSERT OR REPLACE INTO volume_unit_cache
           (series_id, chapter_id, volume_id, volume_number, chapter_number,
            status, provider, written_fields, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(series_id),
            int(chapter_id),
            int(volume_id) if volume_id not in (None, "") else None,
            str(volume_number) if volume_number not in (None, "") else None,
            str(chapter_number) if chapter_number not in (None, "") else None,
            str(status or "FAILED"),
            str(provider or "") or None,
            json.dumps(list(written_fields or []), ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


#: Ligne sentinelle : la série entière a été parcourue jusqu'au bout. Kavita ne
#: donne jamais l'identifiant 0 à un chapitre, la place est donc libre. Sans
#: elle, la reprise se ferait à la maille « au moins une unité écrite », et une
#: passe annulée au tome 3 sur 40 ferait passer les 37 autres pour traités.
SERIES_PASS_CHAPTER_ID = 0
SERIES_PASS_STATUS = "SERIES_DONE"


def mark_series_pass_done(series_id: int, provider: str = "") -> None:
    """Marque une série comme parcourue en entier, pour la reprise."""
    save_volume_unit_state(
        series_id,
        SERIES_PASS_CHAPTER_ID,
        SERIES_PASS_STATUS,
        provider=provider,
    )


def get_volume_unit_states(series_id: int) -> dict:
    """chapter_id -> {status, provider, written_fields, updated_at} pour une série."""
    import json

    if not os.path.exists(DB_FILE):
        return {}
    conn = _connect()
    c = conn.cursor()
    _ensure_volume_unit_tables(c)
    c.execute(
        """SELECT chapter_id, status, provider, written_fields, updated_at
           FROM volume_unit_cache WHERE series_id = ? AND chapter_id != ?""",
        (int(series_id), SERIES_PASS_CHAPTER_ID),
    )
    out = {}
    for chapter_id, status, provider, fields, updated in c.fetchall():
        try:
            written = json.loads(fields or "[]")
        except (TypeError, ValueError):
            written = []
        out[int(chapter_id)] = {
            "status": status,
            "provider": provider or "",
            "written_fields": written,
            "updated_at": updated,
        }
    conn.close()
    return out


def count_volume_units_by_status(series_ids=None) -> dict:
    """Compte global par état, pour la barre de progression et le résumé."""
    if not os.path.exists(DB_FILE):
        return {}
    conn = _connect()
    c = conn.cursor()
    _ensure_volume_unit_tables(c)
    if series_ids:
        ids = [int(x) for x in series_ids]
        ph = ",".join("?" for _ in ids)
        c.execute(
            f"SELECT status, COUNT(*) FROM volume_unit_cache "
            f"WHERE series_id IN ({ph}) AND chapter_id != ? GROUP BY status",
            ids + [SERIES_PASS_CHAPTER_ID],
        )
    else:
        c.execute(
            "SELECT status, COUNT(*) FROM volume_unit_cache "
            "WHERE chapter_id != ? GROUP BY status",
            (SERIES_PASS_CHAPTER_ID,),
        )
    out = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return out


def count_dup_dismissals() -> int:
    """Pardons de doublons (toutes biblios), hors ligne méta du cache."""
    if not os.path.exists(DB_FILE):
        return 0
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        "SELECT COUNT(*) FROM hygiene_dup_dismissals WHERE group_key != ?",
        (_DUP_META_GROUP_ID,),
    )
    n = int((c.fetchone() or [0])[0] or 0)
    conn.close()
    return n


def summarize_volume_writes() -> dict:
    """Unités DONE : victoires par fournisseur + champs réellement écrits.

    La sentinelle de fin de série (`chapter_id` 0) est exclue. Pas de nouvel
    enregistrement : on relit `volume_unit_cache`.
    """
    import json

    if not os.path.exists(DB_FILE):
        return {"providers": {}, "fields": {}}
    conn = _connect()
    c = conn.cursor()
    _ensure_volume_unit_tables(c)
    c.execute(
        "SELECT provider, written_fields FROM volume_unit_cache "
        "WHERE status = 'DONE' AND chapter_id != ?",
        (SERIES_PASS_CHAPTER_ID,),
    )
    providers = {}
    fields = {}
    for provider, raw in c.fetchall():
        pid = (provider or "").strip()
        if pid:
            providers[pid] = providers.get(pid, 0) + 1
        try:
            written = json.loads(raw or "[]")
        except (TypeError, ValueError):
            written = []
        if not isinstance(written, list):
            continue
        for field in written:
            key = str(field or "").strip()
            if key:
                fields[key] = fields.get(key, 0) + 1
    conn.close()
    return {"providers": providers, "fields": fields}


def list_enriched_series_ids() -> set:
    """Séries parcourues **en entier** : la reprise repart après elles.

    Le critère est la ligne sentinelle, pas la présence d'unités écrites. Une
    série interrompue en cours de route garde ses unités déjà faites — la passe
    relit `get_volume_unit_states` et ne replanifie que les unités en attente,
    donc ni le travail ni le coût fournisseur ne sont payés deux fois — mais la
    série revient dans les cibles pour que ses tomes restants soient traités.

    Une série qui porte au moins une unité `FAILED` est rendue à la reprise même
    si elle a sa sentinelle : c'est le cas des séries traversées pendant une
    indisponibilité de Kavita, que la passe fermait quand même et qui restaient
    exclues pour toujours. La condition est ici, et non seulement à la pose de la
    sentinelle, pour que les bases déjà marquées se rouvrent d'elles-mêmes.
    """
    if not os.path.exists(DB_FILE):
        return set()
    conn = _connect()
    c = conn.cursor()
    _ensure_volume_unit_tables(c)
    c.execute(
        "SELECT DISTINCT series_id FROM volume_unit_cache "
        "WHERE chapter_id = ? AND status = ?",
        (SERIES_PASS_CHAPTER_ID, SERIES_PASS_STATUS),
    )
    out = {int(row[0]) for row in c.fetchall()}
    c.execute(
        "SELECT DISTINCT series_id FROM volume_unit_cache WHERE status = 'FAILED'"
    )
    out -= {int(row[0]) for row in c.fetchall()}
    conn.close()
    return out


def clear_volume_unit_states(series_id=None, chapter_id=None):
    """Efface l'état d'une série, d'un tome, ou de tout le monde.

    `chapter_id` n'a de sens qu'avec une série : le Reset atelier d'un tome
    doit rouvrir ce chapitre à la passe auto, sans jeter le reste de la série.
    """
    if not os.path.exists(DB_FILE):
        return
    conn = _connect()
    c = conn.cursor()
    _ensure_volume_unit_tables(c)
    if series_id is None:
        c.execute("DELETE FROM volume_unit_cache")
    elif chapter_id is None:
        c.execute("DELETE FROM volume_unit_cache WHERE series_id = ?", (int(series_id),))
    else:
        c.execute(
            "DELETE FROM volume_unit_cache WHERE series_id = ? AND chapter_id = ?",
            (int(series_id), int(chapter_id)),
        )
        # Supprime aussi la sentinelle de fin de passe pour que la reprise traverse à nouveau la série
        c.execute(
            "DELETE FROM volume_unit_cache WHERE series_id = ? AND chapter_id = ?",
            (int(series_id), SERIES_PASS_CHAPTER_ID),
        )
    conn.commit()
    conn.close()


WORKSHOP_HISTORY_CAP = 50


def save_volume_unit_override(
    series_id: int,
    chapter_id: int,
    *,
    provider: str = "",
    provider_ref: str = "",
    payload: dict = None,
):
    """Lien magique d'un tome : survit au reset de la passe auto."""
    import json
    from datetime import datetime, timezone

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_workshop_tables(c)
    c.execute(
        """INSERT OR REPLACE INTO volume_unit_overrides
           (series_id, chapter_id, provider, provider_ref, payload_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            int(series_id),
            int(chapter_id),
            str(provider or ""),
            str(provider_ref or ""),
            json.dumps(payload or {}, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_volume_unit_overrides(series_id: int, chapter_id=None) -> dict:
    """chapter_id -> {provider, provider_ref, payload}."""
    import json

    if not os.path.exists(DB_FILE):
        return {}
    conn = _connect()
    c = conn.cursor()
    _ensure_workshop_tables(c)
    if chapter_id is not None:
        c.execute(
            """SELECT chapter_id, provider, provider_ref, payload_json
               FROM volume_unit_overrides WHERE series_id = ? AND chapter_id = ?""",
            (int(series_id), int(chapter_id)),
        )
    else:
        c.execute(
            """SELECT chapter_id, provider, provider_ref, payload_json
               FROM volume_unit_overrides WHERE series_id = ?""",
            (int(series_id),),
        )
    out = {}
    for cid, provider, ref, payload in c.fetchall():
        try:
            body = json.loads(payload or "{}")
        except (TypeError, ValueError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        out[int(cid)] = {
            "provider": provider or "",
            "provider_ref": ref or "",
            "payload": body,
        }
    conn.close()
    return out


def clear_volume_unit_overrides(series_id: int, chapter_id=None):
    if not os.path.exists(DB_FILE):
        return
    conn = _connect()
    c = conn.cursor()
    _ensure_workshop_tables(c)
    if chapter_id is None:
        c.execute(
            "DELETE FROM volume_unit_overrides WHERE series_id = ?",
            (int(series_id),),
        )
    else:
        c.execute(
            "DELETE FROM volume_unit_overrides WHERE series_id = ? AND chapter_id = ?",
            (int(series_id), int(chapter_id)),
        )
    conn.commit()
    conn.close()


def save_workshop_series_override(series_id: int, payload: dict, cover_url: str = ""):
    """Brouillon persistant de la fiche série dans l'atelier (survit au F5)."""
    import json
    from datetime import datetime, timezone

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_workshop_tables(c)
    c.execute(
        """INSERT OR REPLACE INTO workshop_series_overrides
           (series_id, payload_json, cover_url, updated_at)
           VALUES (?, ?, ?, ?)""",
        (
            int(series_id),
            json.dumps(payload or {}, ensure_ascii=False),
            str(cover_url or ""),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_workshop_series_override(series_id: int) -> Optional[dict]:
    """Retourne {'payload': dict, 'cover_url': str} ou None."""
    import json

    if not os.path.exists(DB_FILE):
        return None
    conn = _connect()
    c = conn.cursor()
    _ensure_workshop_tables(c)
    row = c.execute(
        """SELECT payload_json, cover_url
           FROM workshop_series_overrides WHERE series_id = ?""",
        (int(series_id),),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        body = json.loads(row[0] or "{}")
    except (TypeError, ValueError):
        body = {}
    return {
        "payload": body if isinstance(body, dict) else {},
        "cover_url": row[1] or "",
    }


def clear_workshop_series_override(series_id: int):
    """Purge le brouillon de fiche série une fois envoyé à Kavita ou réinitialisé."""
    if not os.path.exists(DB_FILE):
        return
    conn = _connect()
    c = conn.cursor()
    _ensure_workshop_tables(c)
    c.execute(
        "DELETE FROM workshop_series_overrides WHERE series_id = ?",
        (int(series_id),),
    )
    conn.commit()
    conn.close()


def record_workshop_history(
    series_id: int,
    event: str,
    *,
    chapter_id=None,
    detail: dict = None,
):
    """Ajoute une ligne et taille le journal à 50 par série."""
    import json
    from datetime import datetime, timezone

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_workshop_tables(c)
    body = dict(detail or {})
    for banned in ("summary", "cover_url", "coverImage"):
        body.pop(banned, None)
    c.execute(
        """INSERT INTO workshop_history
           (series_id, chapter_id, event, detail_json, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            int(series_id),
            int(chapter_id) if chapter_id not in (None, "") else None,
            str(event or "").strip() or "event",
            json.dumps(body, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    c.execute(
        """DELETE FROM workshop_history WHERE series_id = ? AND id NOT IN (
             SELECT id FROM workshop_history WHERE series_id = ?
             ORDER BY id DESC LIMIT ?
           )""",
        (int(series_id), int(series_id), WORKSHOP_HISTORY_CAP),
    )
    conn.commit()
    conn.close()


def list_workshop_history(series_id: int, limit: int = WORKSHOP_HISTORY_CAP) -> list:
    import json

    if not os.path.exists(DB_FILE):
        return []
    conn = _connect()
    c = conn.cursor()
    _ensure_workshop_tables(c)
    c.execute(
        """SELECT id, chapter_id, event, detail_json, created_at
           FROM workshop_history WHERE series_id = ?
           ORDER BY id DESC LIMIT ?""",
        (int(series_id), int(limit)),
    )
    out = []
    for hid, chapter_id, event, detail, created in c.fetchall():
        try:
            body = json.loads(detail or "{}")
        except (TypeError, ValueError):
            body = {}
        out.append(
            {
                "id": hid,
                "chapter_id": chapter_id,
                "event": event,
                "detail": body if isinstance(body, dict) else {},
                "created_at": created,
            }
        )
    conn.close()
    return out


def clear_workshop_history(series_id: int, chapter_id=None):
    if not os.path.exists(DB_FILE):
        return
    conn = _connect()
    c = conn.cursor()
    _ensure_workshop_tables(c)
    if chapter_id is None:
        c.execute("DELETE FROM workshop_history WHERE series_id = ?", (int(series_id),))
    else:
        c.execute(
            "DELETE FROM workshop_history WHERE series_id = ? AND chapter_id = ?",
            (int(series_id), int(chapter_id)),
        )
    conn.commit()
    conn.close()

