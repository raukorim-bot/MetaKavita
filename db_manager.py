import sqlite3
import os

from models import SeriesOverride

DATA_DIR = "data"
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
    conn.commit()
    conn.close()


def _ensure_lifetime_stats_table(c):
    c.execute('''CREATE TABLE IF NOT EXISTS lifetime_stats
                 (stat_key TEXT PRIMARY KEY,
                  value INTEGER NOT NULL DEFAULT 0)''')


def _ensure_provider_stats_table(c):
    c.execute('''CREATE TABLE IF NOT EXISTS provider_stats
                 (provider_id TEXT PRIMARY KEY,
                  wins INTEGER NOT NULL DEFAULT 0)''')


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


def increment_provider_win(provider_id):
    """Incrémente le compteur de victoires d'un scraper (télémétrie C7)."""
    pid = _normalize_provider_stat_id(provider_id)
    if not pid:
        return
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_provider_stats_table(c)
    c.execute(
        '''INSERT INTO provider_stats (provider_id, wins) VALUES (?, 1)
           ON CONFLICT(provider_id) DO UPDATE SET wins = wins + 1''',
        (pid,),
    )
    conn.commit()
    conn.close()


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


def record_manual_skip_telemetry():
    """Télémétrie : +1 skip manuel."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_lifetime_stats_table(c)
    _bump_lifetime_stat(c, "manual_skips", 1)
    conn.commit()
    conn.close()
    return {
        "manual_reviews_delta": 0,
        "manual_skips_delta": 1,
        "manual_top1_accepts_delta": 0,
        "manual_score_sum_delta": 0.0,
        "manual_field_edits_delta": 0,
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
    }


def save_pending_review(
    review_id,
    series_id,
    series_name,
    candidates_json,
    preview_json=None,
    state="awaiting_pick",
    created_at=None,
    base_provider=None,
    chosen_score=None,
):
    """
    Insert ou remplace une review manuelle en attente.

    Idempotent par `series_id` : toute review existante pour la série est
    remplacée (contrainte UNIQUE) dans la même transaction.
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
    # Remplace toute review existante pour cette série (évite les doublons)
    c.execute("DELETE FROM pending_reviews WHERE series_id = ?", (sid,))
    c.execute(
        '''INSERT INTO pending_reviews
           (review_id, series_id, series_name, candidates_json, preview_json,
            state, created_at, base_provider, chosen_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
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
        ),
    )
    conn.commit()
    conn.close()
    return review_id


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
            state, created_at, base_provider, chosen_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
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
        '''SELECT review_id, series_id, series_name, candidates_json, preview_json,
                  state, created_at, base_provider, chosen_score
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
        '''SELECT review_id, series_id, series_name, candidates_json, preview_json,
                  state, created_at, base_provider, chosen_score
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
            '''SELECT review_id, series_id, series_name, candidates_json, preview_json,
                      state, created_at, base_provider, chosen_score
               FROM pending_reviews WHERE state = ?
               ORDER BY created_at ASC LIMIT ?''',
            (state, int(limit)),
        )
    else:
        c.execute(
            '''SELECT review_id, series_id, series_name, candidates_json, preview_json,
                      state, created_at, base_provider, chosen_score
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
        "state", "created_at", "base_provider", "chosen_score",
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


def delete_pending_review(review_id):
    if not os.path.exists(DB_FILE):
        init_db()
    conn = _connect()
    c = conn.cursor()
    _ensure_pending_reviews_table(c)
    c.execute("DELETE FROM pending_reviews WHERE review_id = ?", (review_id,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


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

def save_series_override(override: SeriesOverride, *, purge_pending: bool = True, status: str = "PENDING"):
    """
    Persiste un SeriesOverride complet en une seule opération atomique.

    Préférer cette fonction à `save_forced_overrides()` dans tout nouveau code :
    en exigeant un objet à champs nommés plutôt qu'une liste d'arguments
    positionnels, elle rend beaucoup plus visible (à la relecture comme à la
    complétion IDE) tout champ oublié lors de la construction de l'objet —
    c'est exactement l'angle mort qui avait fait disparaître silencieusement
    `publisher_pref` dans l'ancienne route `/save-override`.

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
        except Exception:
            pass

def save_forced_overrides(series_id, forced_id, alt_title, forced_provider="AUTO", targeted_fields="ALL", publisher_pref="GLOBAL", alt_title_langs=""):
    """Wrapper rétro-compatible (arguments positionnels) autour de save_series_override().
    Conservé pour les appelants existants (ex: scripts de debug) ; tout nouveau code HTTP
    (voir routes/series.py) doit construire un SeriesOverride explicite et appeler
    save_series_override() directement."""
    save_series_override(SeriesOverride(
        series_id=series_id,
        forced_id=forced_id,
        alternative_title=alt_title,
        forced_provider=forced_provider,
        targeted_fields=targeted_fields,
        publisher_pref=publisher_pref,
        alt_title_langs=alt_title_langs or "",
    ))

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
        
    c.execute("SELECT series_id, status, forced_id, alternative_title, forced_provider, targeted_fields, publisher_pref, alt_title_langs FROM series_cache")
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
    } for row in rows}

def clean_orphaned_cache(active_ids):
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