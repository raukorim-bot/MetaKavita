import sqlite3
import os

from models import SeriesOverride

DATA_DIR = "data"
DB_FILE = os.path.join(DATA_DIR, "cache.db")

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
        
    conn = sqlite3.connect(DB_FILE)
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


def increment_provider_win(provider_id):
    """Incrémente le compteur de victoires d'un scraper (télémétrie C7)."""
    pid = _normalize_provider_stat_id(provider_id)
    if not pid:
        return
    if not os.path.exists(DB_FILE):
        init_db()
    conn = sqlite3.connect(DB_FILE)
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
    conn = sqlite3.connect(DB_FILE)
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
    conn = sqlite3.connect(DB_FILE)
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
    """Retourne {series_enriched, matches_won, series_missed} (0 si absents)."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    _ensure_lifetime_stats_table(c)
    c.execute("SELECT stat_key, value FROM lifetime_stats")
    rows = {row[0]: int(row[1]) for row in c.fetchall()}
    conn.close()
    return {
        "series_enriched": rows.get("series_enriched", 0),
        "matches_won": rows.get("matches_won", 0),
        "series_missed": rows.get("series_missed", 0),
    }


def get_provider_stats():
    """Retourne {provider_id: wins} trié par wins décroissant."""
    if not os.path.exists(DB_FILE):
        init_db()
    conn = sqlite3.connect(DB_FILE)
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

def update_status(series_id, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO series_cache (series_id, status) VALUES (?, ?)
                 ON CONFLICT(series_id) DO UPDATE SET status=excluded.status''', (series_id, status))
    conn.commit()
    conn.close()

def save_series_override(override: SeriesOverride):
    """
    Persiste un SeriesOverride complet en une seule opération atomique.

    Préférer cette fonction à `save_forced_overrides()` dans tout nouveau code :
    en exigeant un objet à champs nommés plutôt qu'une liste d'arguments
    positionnels, elle rend beaucoup plus visible (à la relecture comme à la
    complétion IDE) tout champ oublié lors de la construction de l'objet —
    c'est exactement l'angle mort qui avait fait disparaître silencieusement
    `publisher_pref` dans l'ancienne route `/save-override`.
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    f_id = override.forced_id.strip() if override.forced_id else None
    a_title = override.alternative_title.strip() if override.alternative_title else None

    _ensure_schema(c)

    c.execute('''INSERT INTO series_cache (series_id, status, forced_id, alternative_title, forced_provider, targeted_fields, publisher_pref, alt_title_langs) 
                 VALUES (?, 'PENDING', ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(series_id) DO UPDATE SET 
                 forced_id=excluded.forced_id, 
                 alternative_title=excluded.alternative_title, 
                 forced_provider=excluded.forced_provider,
                 targeted_fields=excluded.targeted_fields,
                 publisher_pref=excluded.publisher_pref,
                 alt_title_langs=excluded.alt_title_langs,
                 status='PENDING' ''',
              (override.series_id, f_id, a_title, override.forced_provider, override.targeted_fields, override.publisher_pref, override.alt_title_langs or ""))
    conn.commit()
    conn.close()


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
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE series_cache SET status = 'PENDING' WHERE status IN ('NOT_FOUND', 'IGNORED')")
    conn.commit()
    conn.close()

def get_all_cached_data():
    if not os.path.exists(DB_FILE):
        init_db()
    conn = sqlite3.connect(DB_FILE)
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
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT series_id FROM series_cache")
    cached_ids = {row[0] for row in c.fetchall()}
    orphans = cached_ids - active_ids
    if orphans:
        c.executemany("DELETE FROM series_cache WHERE series_id = ?", [(o,) for o in orphans])
        conn.commit()
    conn.close()
    return len(orphans)