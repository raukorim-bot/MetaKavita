"""
File batch persistante (C63) — SQLite + hydrate vers sync_queue au boot / reprise.

La file mémoire reste le chemin chaud ; SQLite survit au redémarrage du conteneur.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import db_manager

_META_PAUSED = "paused"
_LOCK = threading.RLock()

STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_CANCELLED = "cancelled"

#: Lignes terminées gardées pour l'historique / le débogage. Le module ne
#: contenait AUCUN `DELETE FROM batch_queue` : les lignes passaient en
#: `done`/`cancelled` et y restaient à vie, si bien qu'après quelques milliers
#: d'enrichissements chaque `enqueue_items` balayait toute la table.
_TERMINAL_KEEP = 200

#: Base pour laquelle les tables ont déjà été créées dans ce process. Sans ce
#: garde-fou, les treize fonctions du module ouvraient une connexion neuve et
#: deux DDL avant leur propre requête — `should_skip_batch_item`, appelé une fois
#: par série de lot, faisait deux connexions et six requêtes pour un SELECT.
_tables_ready_for = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_tables() -> None:
    """Crée les tables de la file batch — une seule fois par base et par process."""
    global _tables_ready_for
    db_file = db_manager.DB_FILE
    if _tables_ready_for == db_file:
        return
    conn = db_manager._connect()
    try:
        c = conn.cursor()
        db_manager._ensure_batch_queue_tables(c)
        conn.commit()
    finally:
        conn.close()
    _tables_ready_for = db_file


def is_paused() -> bool:
    ensure_tables()
    conn = db_manager._connect()
    try:
        row = conn.execute(
            "SELECT value FROM batch_queue_meta WHERE key = ?",
            (_META_PAUSED,),
        ).fetchone()
        return bool(row and str(row[0]) == "1")
    finally:
        conn.close()


def set_paused(paused: bool) -> None:
    ensure_tables()
    with _LOCK:
        conn = db_manager._connect()
        try:
            conn.execute(
                "INSERT INTO batch_queue_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_META_PAUSED, "1" if paused else "0"),
            )
            conn.commit()
        finally:
            conn.close()
    broadcast_queue_updated()


def count_active() -> int:
    ensure_tables()
    conn = db_manager._connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM batch_queue WHERE state IN (?, ?)",
            (STATE_QUEUED, STATE_RUNNING),
        ).fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def list_active() -> List[Dict[str, Any]]:
    ensure_tables()
    conn = db_manager._connect()
    try:
        rows = conn.execute(
            "SELECT id, series_id, series_name, force_update, fields_override, state, "
            "created_at, position FROM batch_queue "
            "WHERE state IN (?, ?) ORDER BY position ASC, created_at ASC",
            (STATE_QUEUED, STATE_RUNNING),
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0],
                "series_id": r[1],
                "series_name": r[2] or "",
                "force_update": bool(r[3]),
                "fields_override": r[4],
                "state": r[5],
                "created_at": r[6],
                "position": r[7],
            })
        return out
    finally:
        conn.close()


def snapshot_status() -> Dict[str, Any]:
    items = list_active()
    return {
        "paused": is_paused(),
        "count": len(items),
        "items": items,
    }


def _next_position(conn) -> int:
    row = conn.execute("SELECT COALESCE(MAX(position), 0) FROM batch_queue").fetchone()
    return int(row[0] if row else 0) + 1


def _prune_terminal(conn) -> int:
    """Ne garde que la queue de l'historique terminé (`done` / `cancelled`).

    Rien ne lit ces lignes : `snapshot_status` et `should_skip_batch_item` ne
    regardent que `queued`/`running`. Les laisser s'accumuler ne coûtait qu'un
    balayage de plus en plus long à chaque ajout, et une base qui grossit sans
    fin. Une ligne effacée reste « à sauter » pour le worker, puisque c'est
    l'ABSENCE de ligne active qui le décide.
    """
    cur = conn.execute(
        "DELETE FROM batch_queue WHERE state IN (?, ?) AND id NOT IN ("
        "  SELECT id FROM batch_queue WHERE state IN (?, ?)"
        "  ORDER BY position DESC LIMIT ?"
        ")",
        (STATE_DONE, STATE_CANCELLED, STATE_DONE, STATE_CANCELLED, _TERMINAL_KEEP),
    )
    return max(0, int(cur.rowcount or 0))


def enqueue_items(series_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    series_list items: series_id, series_name, force_update, fields_override.
    Returns added, skipped_dupes, item payloads for RAM put.
    """
    ensure_tables()
    added = 0
    skipped_dupes = 0
    to_put: List[Dict[str, Any]] = []

    with _LOCK:
        conn = db_manager._connect()
        try:
            c = conn.cursor()
            _prune_terminal(conn)
            # Position calculée une fois pour tout le paquet : la reprendre par
            # série relançait un `MAX(position)` sur toute la table à chaque
            # ligne insérée, soit cinquante balayages par paquet /batch-sync.
            pos = _next_position(conn)
            for s in series_list:
                sid = int(s["series_id"])
                exists = c.execute(
                    "SELECT 1 FROM batch_queue WHERE series_id = ? AND state IN (?, ?) LIMIT 1",
                    (sid, STATE_QUEUED, STATE_RUNNING),
                ).fetchone()
                if exists:
                    skipped_dupes += 1
                    continue
                item_id = str(uuid.uuid4())
                c.execute(
                    "INSERT INTO batch_queue "
                    "(id, series_id, series_name, force_update, fields_override, state, created_at, position) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_id,
                        sid,
                        s.get("series_name") or "",
                        1 if s.get("force_update") else 0,
                        s.get("fields_override"),
                        STATE_QUEUED,
                        _utc_now(),
                        pos,
                    ),
                )
                pos += 1
                added += 1
                to_put.append({
                    "id": item_id,
                    "series_id": sid,
                    "series_name": s.get("series_name") or "",
                    "force_update": bool(s.get("force_update")),
                    "fields_override": s.get("fields_override"),
                })
            conn.commit()
        finally:
            conn.close()

    broadcast_queue_updated()
    return {
        "added": added,
        "skipped_dupes": skipped_dupes,
        "items": to_put,
        "paused": is_paused(),
        "count": count_active(),
    }


def cancel_item(item_id: str) -> str:
    """Returns 'ok' | 'running' | 'missing'."""
    ensure_tables()
    with _LOCK:
        conn = db_manager._connect()
        try:
            row = conn.execute(
                "SELECT state FROM batch_queue WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not row:
                return "missing"
            if row[0] == STATE_RUNNING:
                return "running"
            if row[0] != STATE_QUEUED:
                return "missing"
            conn.execute(
                "UPDATE batch_queue SET state = ? WHERE id = ?",
                (STATE_CANCELLED, item_id),
            )
            conn.commit()
        finally:
            conn.close()
    broadcast_queue_updated()
    return "ok"


def cancel_queued_by_series(series_id: int) -> int:
    """Cancel all STATE_QUEUED rows for this series_id. Leaves running untouched.

    Used when Companion Super/Auto replaces a pending batch job for the same series.
    Returns the number of rows cancelled.
    """
    ensure_tables()
    with _LOCK:
        conn = db_manager._connect()
        try:
            cur = conn.execute(
                "UPDATE batch_queue SET state = ? WHERE series_id = ? AND state = ?",
                (STATE_CANCELLED, int(series_id), STATE_QUEUED),
            )
            n = cur.rowcount if cur.rowcount is not None else 0
            conn.commit()
        finally:
            conn.close()
    n = max(0, int(n))
    if n:
        broadcast_queue_updated()
    return n


def cancel_all_queued() -> int:
    ensure_tables()
    with _LOCK:
        conn = db_manager._connect()
        try:
            cur = conn.execute(
                "UPDATE batch_queue SET state = ? WHERE state = ?",
                (STATE_CANCELLED, STATE_QUEUED),
            )
            n = cur.rowcount if cur.rowcount is not None else 0
            conn.commit()
        finally:
            conn.close()
    broadcast_queue_updated()
    return max(0, int(n))


def cancel_all_pending() -> int:
    """Stop : queued + running → cancelled."""
    ensure_tables()
    with _LOCK:
        conn = db_manager._connect()
        try:
            cur = conn.execute(
                "UPDATE batch_queue SET state = ? WHERE state IN (?, ?)",
                (STATE_CANCELLED, STATE_QUEUED, STATE_RUNNING),
            )
            n = cur.rowcount if cur.rowcount is not None else 0
            conn.commit()
        finally:
            conn.close()
    set_paused(False)
    broadcast_queue_updated()
    return max(0, int(n))


def should_skip_batch_item(series_id: int) -> bool:
    """True si pas de ligne active (cancel/clear/done) — ne pas enrichir."""
    ensure_tables()
    conn = db_manager._connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM batch_queue WHERE series_id = ? AND state IN (?, ?) LIMIT 1",
            (int(series_id), STATE_QUEUED, STATE_RUNNING),
        ).fetchone()
        return row is None
    finally:
        conn.close()


def mark_running(series_id: int) -> bool:
    ensure_tables()
    with _LOCK:
        conn = db_manager._connect()
        try:
            cur = conn.execute(
                "UPDATE batch_queue SET state = ? WHERE series_id = ? AND state = ?",
                (STATE_RUNNING, int(series_id), STATE_QUEUED),
            )
            conn.commit()
            return (cur.rowcount or 0) > 0
        finally:
            conn.close()


def mark_done(series_id: int) -> None:
    ensure_tables()
    with _LOCK:
        conn = db_manager._connect()
        try:
            conn.execute(
                "UPDATE batch_queue SET state = ? WHERE series_id = ? AND state IN (?, ?)",
                (STATE_DONE, int(series_id), STATE_QUEUED, STATE_RUNNING),
            )
            conn.commit()
        finally:
            conn.close()
    broadcast_queue_updated()


def reset_running_to_queued() -> int:
    ensure_tables()
    with _LOCK:
        conn = db_manager._connect()
        try:
            cur = conn.execute(
                "UPDATE batch_queue SET state = ? WHERE state = ?",
                (STATE_QUEUED, STATE_RUNNING),
            )
            n = cur.rowcount if cur.rowcount is not None else 0
            conn.commit()
        finally:
            conn.close()
    return max(0, int(n))


def list_queued_for_hydrate() -> List[Dict[str, Any]]:
    ensure_tables()
    conn = db_manager._connect()
    try:
        rows = conn.execute(
            "SELECT series_id, series_name, force_update, fields_override FROM batch_queue "
            "WHERE state = ? ORDER BY position ASC, created_at ASC",
            (STATE_QUEUED,),
        ).fetchall()
        return [
            {
                "series_id": r[0],
                "series_name": r[1] or "",
                "force_update": bool(r[2]),
                "fields_override": r[3],
            }
            for r in rows
        ]
    finally:
        conn.close()


def broadcast_queue_updated() -> None:
    try:
        from extensions import socketio
        socketio.emit("batch_queue_updated", {
            "count": count_active(),
            "paused": is_paused(),
        })
    except Exception as exc:
        logging.debug("batch_queue_updated emit skipped: %s", exc)
