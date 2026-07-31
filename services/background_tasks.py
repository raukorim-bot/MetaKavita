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

from config_manager import load_config, is_library_enabled
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

# Compteurs DÉDIÉS à la barre de progression batch — délibérément séparés de
# `sync_queue.qsize()`. Cette file est partagée avec le webhook et le polling
# auto-sync (voir routes/sync.py::webhook et _auto_sync_worker ci-dessous) ;
# un événement Kavita ou un tick auto-sync arrivant en plein batch faisait
# gonfler/dégonfler `qsize()` sans rapport avec l'avancement réel du batch,
# ce qui faisait sauter la barre de façon erratique côté UI (batch.js). Seuls
# les items tagués `is_batch=True` (voir `make_sync_item`) font avancer ces
# compteurs et sont diffusés via `broadcast_batch_progress`.
_batch_progress_lock = threading.Lock()
_batch_total = 0
_batch_done = 0


def set_batch_enqueue_enabled(enabled: bool) -> None:
    global _batch_enqueue_enabled
    with _batch_enqueue_lock:
        _batch_enqueue_enabled = bool(enabled)


def is_batch_enqueue_enabled() -> bool:
    with _batch_enqueue_lock:
        return _batch_enqueue_enabled


def make_sync_item(series_id, series_name, force_update, fields_override=None, is_batch=False):
    """Structure unique poussée dans `sync_queue` par les 3 producteurs (batch-sync,
    webhook, auto-sync). `is_batch` est le seul signal utilisé pour la barre de
    progression batch — voir le commentaire sur `_batch_total` ci-dessus."""
    return {
        "series_id": series_id,
        "series_name": series_name,
        "force_update": force_update,
        "fields_override": fields_override,
        "is_batch": is_batch,
    }


def register_batch_enqueue(count, new_batch):
    """Un paquet /batch-sync vient d'empiler `count` séries taguées `is_batch`.

    `new_batch=True` (1er paquet, `resume_enqueue=true` côté UI) redémarre le
    compteur à zéro ; les paquets suivants du même batch s'additionnent dessus,
    puisque le total réel n'est connu qu'une fois tous les paquets envoyés mais
    que le premier paquet doit déjà pouvoir afficher une progression.
    À appeler AVANT `sync_queue.put(...)` pour que le worker ne lise jamais un
    total pas encore à jour.
    """
    global _batch_total, _batch_done
    with _batch_progress_lock:
        if new_batch:
            _batch_total = 0
            _batch_done = 0
        _batch_total += max(0, int(count))


def reset_batch_progress():
    """Stop / drain : la barre ne doit plus attendre des séries qui viennent
    d'être jetées de la file (voir routes/sync.py::stop_batch)."""
    global _batch_total, _batch_done
    with _batch_progress_lock:
        _batch_total = 0
        _batch_done = 0


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
    reset_batch_progress()
    if drained:
        broadcast_batch_progress(0, stopped=True)
    return drained


def _worker():
    global _batch_total, _batch_done
    while True:
        item = sync_queue.get()
        try:
            if item is None:
                break
            series_id = item["series_id"]
            series_name = item["series_name"]
            force_update = item["force_update"]
            fields_override = item.get("fields_override")
            is_batch = bool(item.get("is_batch"))

            config = load_config()
            t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])

            if is_batch:
                with _batch_progress_lock:
                    remaining = max(0, _batch_total - _batch_done - 1)
                logging.info(t.get('log_worker_start').format(series_name, remaining))
                broadcast_batch_progress(remaining, active=series_name)
            else:
                # Item hors batch (webhook / auto-sync) : ne touche jamais à la
                # barre de progression batch, même si un batch tourne en parallèle.
                logging.info(t.get('log_worker_start').format(series_name, sync_queue.qsize()))

            # Le Rate-Limiter intelligent dans metadata_fetcher.py gère désormais 100% des délais au millième de seconde près !
            enrich_series(
                series_id,
                series_name,
                force_update,
                targeted_fields_override=fields_override,
            )

            if is_batch:
                with _batch_progress_lock:
                    _batch_done = min(_batch_total, _batch_done + 1)
                    batch_finished = _batch_total > 0 and _batch_done >= _batch_total
                if batch_finished:
                    logging.info(t.get('log_batch_finished'))
                    broadcast_batch_progress(0)
        finally:
            # Toujours appeler task_done() pour chaque get() réussi (sauf sentinel
            # de shutdown). Sinon unfinished_tasks croît et tout futur join() bloque.
            if item is not None:
                sync_queue.task_done()


def select_auto_sync_candidates(all_series, cached, config=None):
    """Séries à enfiler par le polling auto-sync.

    Seul endroit où DISABLED_LIBRARIES s'applique : l'utilisateur choisit les
    bibliothèques que le polling périodique doit balayer. Le dashboard, le batch
    manuel et l'export voient toujours l'intégralité de Kavita.
    """
    candidates = []
    for s in all_series or []:
        if not is_library_enabled(s.get('libraryId'), config):
            continue
        s_id = s['id']
        if s_id not in cached or cached[s_id].get('status') == 'PENDING':
            candidates.append(s)
    return candidates


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
                        # Inventaire complet : le nettoyage du cache doit voir les
                        # séries des bibliothèques exclues du polling, sinon elles
                        # seraient traitées comme orphelines et purgées.
                        all_series = kavita.get_all_series()
                        active_ids = {s['id'] for s in all_series}
                        clean_orphaned_cache(active_ids)
                        cached = get_all_cached_data()

                        to_process = select_auto_sync_candidates(all_series, cached, config)

                        if to_process:
                            logging.info(t.get('log_auto_sync_found').format(len(to_process)))
                            for s in to_process:
                                sync_queue.put(make_sync_item(s['id'], s['name'], False))

                except Exception as e:
                    logging.error(f"❌ [Auto-Sync] Erreur : {e}")

        time.sleep(30)


def start_background_workers():
    """Démarre les deux threads démons de traitement de fond. Appelé une seule
    fois par app.py au chargement du module (comportement identique à l'ancien
    `threading.Thread(...).start()` exécuté au niveau module)."""
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_auto_sync_worker, daemon=True).start()
