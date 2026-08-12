import sqlite3
import os
import logging

from models import SeriesOverride
from secure_logging import safe_exc_str


def _resolve_data_dir() -> str:
    env = (os.environ.get("METAKAVITA_DATA_DIR") or os.environ.get("DATA_DIR") or "").strip()
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))


DATA_DIR = _resolve_data_dir()
DB_FILE = os.path.join(DATA_DIR, "cache.db")


def _connect():
    """Ouvre une connexion SQLite avec WAL + busy_timeout (anti « database is locked »)."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    return conn


def _ensure_schema(c):
    """Vérifie et ajoute les colonnes manquantes une par une de manière sécurisée."""
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
    for col_name, col_type in columns:
        try:
            c.execute(f"ALTER TABLE series_cache ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass # La colonne existe déjà, on passe à la suivante en silence

def init_db():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
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
    conn.commit()
    conn.close()


def _ensure_library_audit_tables(c):
    """Caches for library hygiene reports (volume gaps / duplicate groups)."""
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


def _ensure_lifetime_stats_table(c):
    c.execute('''CREATE TABLE IF NOT EXISTS lifetime_stats
                 (stat_key TEXT PRIMARY KEY,
                  value INTEGER NOT NULL DEFAULT 0)''')


def _ensure_provider_stats_table(c):
    c.execute('''CREATE TABLE IF NOT EXISTS provider_stats
                 (provider_id TEXT PRIMARY KEY,
                  wins INTEGER NOT NULL DEFAULT 0)''')


def _ensure_batch_queue_tables(c):
    """File batch persistante (C63) — survie au redémarrage du conteneur."""
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


def _ensure_pending_reviews_table(c):
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
    try:
        c.execute("ALTER TABLE pending_reviews ADD COLUMN library_id INTEGER")
    except sqlite3.OperationalError:
        pass
    # Migration one-shot : index non-unique → UNIQUE (une review par série).
    c.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_pending_reviews_series_id'"
    )
    idx_row = c.fetchone()
    idx_sql = (idx_row[0] or "") if idx_row else ""
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_pending_reviews_state ON pending_reviews(state)"
    )


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
        "manual_reviews": _as_int("manual_reviews"),
        "manual_skips": _as_int("manual_skips"),
        "manual_top1_accepts": _as_int("manual_top1_accepts"),
        "manual_score_sum": _as_float("manual_score_sum"),
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


def update_pending_review(review_id, **fields):
    """Met à jour les colonnes fournies d'une pending review. Retourne True si une ligne touchée."""
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
    c.execute(f"UPDATE pending_reviews SET {cols} WHERE review_id = ?", values)
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
    c.execute("SELECT series_id FROM series_cache")
    cached_ids = {row[0] for row in c.fetchall()}
    orphans = cached_ids - active_ids
    if orphans:
        orphan_list = list(orphans)
        c.executemany("DELETE FROM series_cache WHERE series_id = ?", [(o,) for o in orphan_list])
        placeholders = ",".join("?" for _ in orphan_list)
        c.execute(
            f"DELETE FROM pending_reviews WHERE series_id IN ({placeholders})",
            orphan_list,
        )
        conn.commit()
    conn.close()
    return len(orphans)


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
    c.execute(
        "DELETE FROM hygiene_dup_dismissals WHERE library_id = ? AND group_key = ?",
        (str(library_id), gkey),
    )
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


def list_dup_dismissals(library_id):
    import json

    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_library_audit_tables(c)
    c.execute(
        "SELECT group_key, series_ids_json, reason, updated_at "
        "FROM hygiene_dup_dismissals WHERE library_id = ?",
        (str(library_id),),
    )
    out = []
    for gkey, sids, reason, updated in c.fetchall():
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


def list_dismissed_group_keys(library_id) -> set:
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
    conn.commit()
    conn.close()

