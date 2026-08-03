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
_batch_real_sends = 0

# Messages renvoyés par enrich_series()/kavita_payload.py qui correspondent à une
# ÉCRITURE effective vers Kavita (voir services/kavita_payload.py::_apply_kavita_write).
# Tout le reste ("Déjà à jour.", "PENDING_REVIEW", "Introuvable.", une erreur...) ne
# touche jamais Kavita — voir _worker() / le nagware supporter (batch.js).
_REAL_SEND_MESSAGES = {"Succès", "Success", "NEEDS_RELOCK"}


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
    global _batch_total, _batch_done, _batch_real_sends
    with _batch_progress_lock:
        if new_batch:
            _batch_total = 0
            _batch_done = 0
            _batch_real_sends = 0
        _batch_total += max(0, int(count))


def is_batch_active() -> bool:
    """True si un batch est déjà en cours (au moins un item encore non traité).

    `_batch_total`/`_batch_done` sont des globaux de PROCESS partagés par toute
    l'app — une seule barre de progression, donc un seul batch « actif » à la
    fois. Sans ce garde-fou, un second `/batch-sync` avec `resume_enqueue=true`
    (ex. deux onglets, ou un double-clic) appellerait
    `register_batch_enqueue(new_batch=True)` qui remet `_batch_total`/`_batch_done`
    à zéro EN PLEIN MILIEU du premier batch, faussant sa progression et son
    `real_sends` final (voir routes/sync.py::batch_sync).
    """
    with _batch_progress_lock:
        return _batch_total > 0 and _batch_done < _batch_total


def reset_batch_progress():
    """Stop / drain : la barre ne doit plus attendre des séries qui viennent
    d'être jetées de la file (voir routes/sync.py::stop_batch)."""
    global _batch_total, _batch_done, _batch_real_sends
    with _batch_progress_lock:
        _batch_total = 0
        _batch_done = 0
        _batch_real_sends = 0


def broadcast_batch_progress(remaining, active=None, stopped=False, real_sends=None):
    """Notifie l'UI (barre de progression batch) via Socket.IO.

    `real_sends` (uniquement sur le message de fin) : nombre de séries du batch
    réellement écrites vers Kavita — voir `_REAL_SEND_MESSAGES`. Sert de garde-fou
    au nagware supporter (batch.js) : un batch entièrement composé de séries déjà
    à jour (skip silencieux, aucune écriture) ne doit pas déclencher la demande de
    soutien, même si `remaining` tombe bien à 0.
    """
    try:
        from extensions import socketio
        payload = {
            "remaining": int(remaining),
            "stopped": bool(stopped),
        }
        if active is not None:
            payload["active"] = active
        if real_sends is not None:
            payload["real_sends"] = int(real_sends)
        socketio.emit("batch_progress", payload)
    except Exception as exc:
        logging.debug("batch_progress emit skipped: %s", exc)


def _detach_batch_from_ram_unlocked() -> int:
    """Retire les items is_batch de sync_queue ; réinsère le reste. Sans touch SQLite."""
    drained = 0
    kept = []
    while not sync_queue.empty():
        try:
            item = sync_queue.get_nowait()
        except queue.Empty:
            break
        if isinstance(item, dict) and item.get("is_batch"):
            sync_queue.task_done()
            drained += 1
        else:
            kept.append(item)

    for item in kept:
        sync_queue.put(item)
        sync_queue.task_done()
    return drained


def drain_sync_queue() -> int:
    """« Stop batch » : retire les items `is_batch=True` de la file RAM.

    `sync_queue` est partagée avec le webhook et le polling auto-sync : les items
    non-batch sont réinsérés. Appelé avec cancel SQLite côté stop_batch.
    """
    drained = _detach_batch_from_ram_unlocked()
    reset_batch_progress()
    if drained:
        broadcast_batch_progress(0, stopped=True)
    return drained


def detach_batch_from_ram() -> int:
    """Pause : retire le batch de la RAM sans annuler la file SQLite."""
    drained = _detach_batch_from_ram_unlocked()
    reset_batch_progress()
    if drained:
        broadcast_batch_progress(0, stopped=False)
    return drained


def hydrate_batch_queue_to_ram(*, new_batch: bool = True) -> int:
    """Pousse les lignes SQLite `queued` vers sync_queue (reprise / boot)."""
    from services import batch_queue as bq

    items = bq.list_queued_for_hydrate()
    if not items:
        return 0
    register_batch_enqueue(len(items), new_batch=new_batch)
    for s in items:
        sync_queue.put(
            make_sync_item(
                s["series_id"],
                s["series_name"],
                s["force_update"],
                s.get("fields_override"),
                is_batch=True,
            )
        )
    return len(items)


def _worker():
    global _batch_total, _batch_done, _batch_real_sends
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
                from services import batch_queue as bq
                if bq.should_skip_batch_item(series_id):
                    with _batch_progress_lock:
                        _batch_done = min(_batch_total, _batch_done + 1)
                        batch_finished = _batch_total > 0 and _batch_done >= _batch_total
                        real_sends = _batch_real_sends
                    if batch_finished:
                        broadcast_batch_progress(0, real_sends=real_sends)
                    continue
                bq.mark_running(series_id)
                with _batch_progress_lock:
                    remaining = max(0, _batch_total - _batch_done - 1)
                logging.info(t.get('log_worker_start').format(series_name, remaining))
                broadcast_batch_progress(remaining, active=series_name)
            else:
                logging.info(t.get('log_worker_start').format(series_name, sync_queue.qsize()))

            _ok, _msg, _used = enrich_series(
                series_id,
                series_name,
                force_update,
                targeted_fields_override=fields_override,
            )

            if is_batch:
                from services import batch_queue as bq
                bq.mark_done(series_id)
                with _batch_progress_lock:
                    _batch_done = min(_batch_total, _batch_done + 1)
                    if _msg in _REAL_SEND_MESSAGES:
                        _batch_real_sends += 1
                    batch_finished = _batch_total > 0 and _batch_done >= _batch_total
                    real_sends = _batch_real_sends
                if batch_finished:
                    logging.info(t.get('log_batch_finished'))
                    broadcast_batch_progress(0, real_sends=real_sends)
        finally:
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
    try:
        from services import batch_queue as bq
        bq.ensure_tables()
        reset_n = bq.reset_running_to_queued()
        if reset_n:
            logging.info("[BatchQueue] %s item(s) running → queued (reprise après crash)", reset_n)
        if not bq.is_paused():
            n = hydrate_batch_queue_to_ram(new_batch=True)
            if n:
                logging.info("[BatchQueue] Hydrate boot : %s série(s) en file", n)
        else:
            logging.info("[BatchQueue] File en pause — pas d'hydrate au boot")
    except Exception as exc:
        logging.warning("[BatchQueue] Init/hydrate boot ignoré : %s", exc)

    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_auto_sync_worker, daemon=True).start()
