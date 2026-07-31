"""
Workers de fond (thread démons) : file de synchronisation manuelle/webhook et
polling d'auto-synchronisation périodique.

Extrait de l'ancien `app.py`. Le comportement de démarrage est préservé à
l'identique : `start_background_workers()` doit être appelé une seule fois,
au démarrage du process (voir app.py), pour rester compatible avec le
déploiement Gunicorn `-w 1` (une seule instance de worker de fond).
"""

import logging
import queue
import threading
import time

from config_manager import load_config
from db_manager import get_all_cached_data, clean_orphaned_cache
from kavita_api import KavitaAPI
from translations import translations
from services.enrichment_engine import enrich_series

# File partagée : alimentée par routes/sync.py (batch-sync, webhook) et
# consommée par le worker démarré ci-dessous.
sync_queue = queue.Queue()

# Après Stop, rejette les paquets /batch-sync encore en vol (chunks de 50 côté UI).
# Le premier chunk d'un nouveau lancement renvoie `resume_enqueue=true` pour réarmer.
_batch_enqueue_lock = threading.Lock()
_batch_enqueue_enabled = True


def set_batch_enqueue_enabled(enabled: bool) -> None:
    global _batch_enqueue_enabled
    with _batch_enqueue_lock:
        _batch_enqueue_enabled = bool(enabled)


def is_batch_enqueue_enabled() -> bool:
    with _batch_enqueue_lock:
        return _batch_enqueue_enabled


def broadcast_batch_progress(remaining, active=None, stopped=False):
    """Notifie l'UI (barre de progression batch) via Socket.IO."""
    try:
        from extensions import socketio
        payload = {
            "remaining": int(remaining),
            "stopped": bool(stopped),
        }
        if active is not None:
            payload["active"] = active
        socketio.emit("batch_progress", payload)
    except Exception as exc:
        logging.debug("batch_progress emit skipped: %s", exc)


def drain_sync_queue() -> int:
    """Vide la file d'attente (hors job en cours). Retourne le nombre d'items retirés."""
    drained = 0
    while not sync_queue.empty():
        try:
            sync_queue.get_nowait()
            sync_queue.task_done()
            drained += 1
        except queue.Empty:
            break
    if drained:
        broadcast_batch_progress(0, stopped=True)
    return drained


def _worker():
    while True:
        item = sync_queue.get()
        try:
            if item is None:
                break
            # 3-tuple historique (webhook / auto-sync) ou 4-tuple batch (masque champs).
            if len(item) == 4:
                series_id, series_name, force_update, fields_override = item
            else:
                series_id, series_name, force_update = item
                fields_override = None

            config = load_config()
            t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])

            remaining = sync_queue.qsize()
            logging.info(t.get('log_worker_start').format(series_name, remaining))
            broadcast_batch_progress(remaining, active=series_name)

            # Le Rate-Limiter intelligent dans metadata_fetcher.py gère désormais 100% des délais au millième de seconde près !
            enrich_series(
                series_id,
                series_name,
                force_update,
                targeted_fields_override=fields_override,
            )

            if sync_queue.empty():
                logging.info(t.get('log_batch_finished'))
                broadcast_batch_progress(0)
        finally:
            # Toujours appeler task_done() pour chaque get() réussi (sauf sentinel
            # de shutdown). Sinon unfinished_tasks croît et tout futur join() bloque.
            if item is not None:
                sync_queue.task_done()


def _auto_sync_worker():
    last_run = 0
    while True:
        config = load_config()
        interval = config.get('AUTO_SYNC_INTERVAL', 0)

        if interval > 0:
            current_time = time.time()
            if current_time - last_run >= (interval * 60):
                last_run = current_time
                t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])

                try:
                    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
                    if kavita.authenticate():
                        logging.info(t.get('log_auto_sync_start'))
                        # Dénylist DISABLED_LIBRARIES : uniquement ici (polling auto).
                        all_series = kavita.get_all_series(respect_disabled_filter=True)
                        active_ids = {s['id'] for s in all_series}
                        clean_orphaned_cache(active_ids)
                        cached = get_all_cached_data()

                        to_process = []
                        for s in all_series:
                            s_id = s['id']
                            if s_id not in cached or cached[s_id].get('status') == 'PENDING':
                                to_process.append(s)

                        if to_process:
                            logging.info(t.get('log_auto_sync_found').format(len(to_process)))
                            for s in to_process:
                                sync_queue.put((s['id'], s['name'], False))

                except Exception as e:
                    logging.error(f"❌ [Auto-Sync] Erreur : {e}")

        time.sleep(30)


def start_background_workers():
    """Démarre les deux threads démons de traitement de fond. Appelé une seule
    fois par app.py au chargement du module (comportement identique à l'ancien
    `threading.Thread(...).start()` exécuté au niveau module)."""
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_auto_sync_worker, daemon=True).start()
