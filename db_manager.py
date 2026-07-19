import sqlite3
import os

DATA_DIR = "data"
DB_FILE = os.path.join(DATA_DIR, "cache.db")

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
    conn.commit()
    conn.close()

def update_status(series_id, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO series_cache (series_id, status) VALUES (?, ?)
                 ON CONFLICT(series_id) DO UPDATE SET status=excluded.status''', (series_id, status))
    conn.commit()
    conn.close()

def save_forced_overrides(series_id, forced_id, alt_title):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Suppression de .isdigit() pour autoriser l'enregistrement de texte (slugs)
    f_id = forced_id.strip() if forced_id else None
    a_title = alt_title.strip() if alt_title else None
    
    c.execute('''INSERT INTO series_cache (series_id, status, forced_id, alternative_title) 
                 VALUES (?, 'PENDING', ?, ?)
                 ON CONFLICT(series_id) DO UPDATE SET 
                 forced_id=excluded.forced_id, 
                 alternative_title=excluded.alternative_title, 
                 status='PENDING' ''', 
              (series_id, f_id, a_title))
    conn.commit()
    conn.close()

def reset_errors():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE series_cache SET status = 'PENDING' WHERE status = 'NOT_FOUND'")
    conn.commit()
    conn.close()

def get_all_cached_data():
    if not os.path.exists(DB_FILE):
        init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT series_id, status, forced_id, alternative_title FROM series_cache")
    rows = c.fetchall()
    conn.close()
    return {row[0]: {'status': row[1], 'forced_id': row[2], 'alternative_title': row[3]} for row in rows}

def clean_orphaned_cache(active_ids):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # On récupère tous les IDs actuellement dans notre cache
    c.execute("SELECT series_id FROM series_cache")
    cached_ids = {row[0] for row in c.fetchall()}
    
    # On trouve les fantômes (ceux qui sont dans le cache mais plus dans active_ids)
    orphans = cached_ids - active_ids
    if orphans:
        # On les supprime du cache
        c.executemany("DELETE FROM series_cache WHERE series_id = ?", [(o,) for o in orphans])
        conn.commit()
        
    conn.close()
    return len(orphans)