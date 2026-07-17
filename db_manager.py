import sqlite3
import os

DB_FILE = "cache.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS series_cache
                 (series_id INTEGER PRIMARY KEY, 
                  status TEXT, 
                  forced_id INTEGER, 
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
    f_id = int(forced_id) if forced_id and str(forced_id).isdigit() else None
    a_title = alt_title.strip() if alt_title else None
    
    # Correction de la syntaxe SQL ici
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
