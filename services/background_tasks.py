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
from db_manager import record_run_origin, clean_orphaned_cache, get_all_cached_data
from kavita_api import KavitaAPI
from secure_logging import safe_exc_str, series_label
from translations import translations
from services.enrichment_engine import enrich_series

# File partagée : alimentée par routes/sync.py (batch-sync, webhook) et
# consommée par le worker démarré ci-dessous.
sync_queue = queue.Queue()

# Réveils thread-safe (hub SignalR, tests) : scan / config / timeout.
auto_sync_wake_queue = queue.Queue()

# Filet heures (trigger scan) : horodatage process, pas en base.
_last_catchup_at = None

# Sérialise put / put_front / drain-detach qui réordonnent la file RAM.
_sync_queue_lock = threading.Lock()

# Sérialise « lire la file SQLite, écarter ce qui est déjà en RAM, empiler » :
# deux hydrates concurrents (double-clic sur « Reprendre », ou Reprendre pendant
# qu'un /batch-sync lève la pause) liraient les mêmes lignes `queued` avant que
# l'un des deux ne les ait poussées. Toujours pris AVANT `_sync_queue_lock`.
_hydrate_lock = threading.Lock()

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

# Job actuellement dans `_worker` (déjà sorti de la file). Stop ne le drain pas :
# le rapport de vague attend sa fin avant de se clore.
_inflight_lock = threading.Lock()
_inflight_origin = ""


def set_batch_enqueue_enabled(enabled: bool) -> None:
    global _batch_enqueue_enabled
    with _batch_enqueue_lock:
        _batch_enqueue_enabled = bool(enabled)


def is_batch_enqueue_enabled() -> bool:
    with _batch_enqueue_lock:
        return _batch_enqueue_enabled


_ALLOWED_ORIGINS = frozenset({"batch", "webhook", "auto", "row"})


def make_sync_item(
    series_id,
    series_name,
    force_update,
    fields_override=None,
    is_batch=False,
    *,
    super_review=False,
    force_auto=False,
    origin=None,
    manual_review_override=False,
):
    """Structure unique poussée dans `sync_queue` par les 3 producteurs (batch-sync,
    webhook, auto-sync). `is_batch` est le seul signal utilisé pour la barre de
    progression batch — voir le commentaire sur `_batch_total` ci-dessus.

    C33 Companion : `super_review` / `force_auto` sont des overrides one-shot
    (webhook) ; défauts False pour rétrocompat batch / auto-sync.

    C96 : `manual_review_override` parque en Review (entre Super et Auto).

    C94 : `origin` dit d'où vient le job (`batch` / `webhook` / `auto` / `row`).
    Défaut `batch` si `is_batch`, sinon `row`. Le worker ne compte un run que
    sur une vraie écriture Kavita (`_REAL_SEND_MESSAGES`).
    """
    raw = str(origin or "").strip().lower()
    if raw not in _ALLOWED_ORIGINS:
        raw = "batch" if is_batch else "row"
    return {
        "series_id": series_id,
        "series_name": series_name,
        "force_update": force_update,
        "fields_override": fields_override,
        "is_batch": is_batch,
        "super_review": bool(super_review),
        "force_auto": bool(force_auto),
        "manual_review_override": bool(manual_review_override),
        "origin": raw,
    }


def register_batch_enqueue(count, new_batch):
    """Un paquet /batch-sync vient d'empiler `count` séries taguées `is_batch`.

    `new_batch=True` (1er paquet, `resume_enqueue=true` côté UI) redémarre le
    compteur à zéro ; les paquets suivants du même batch s'additionnent dessus,
    puisque le total réel n'est connu qu'une fois tous les paquets envoyés mais
    que le premier paquet doit déjà pouvoir afficher une progression.
    À appeler AVANT `put_sync(...)` pour que le worker ne lise jamais un
    total pas encore à jour.

    ⚠️ `new_batch` décidé par l'appelant vaut pour un appelant qui SAIT déjà
    qu'il ouvre le lot. Quand la décision se déduit de l'état courant, elle
    doit se prendre ici : voir `register_batch_enqueue_if_first`.
    """
    global _batch_total, _batch_done, _batch_real_sends
    with _batch_progress_lock:
        if new_batch:
            _batch_total = 0
            _batch_done = 0
            _batch_real_sends = 0
        _batch_total += max(0, int(count))


def register_batch_enqueue_if_first(count) -> bool:
    """Empile `count` séries et décide *ici* si elles ouvrent un nouveau lot.

    Le test « un lot tourne-t-il déjà ? » et la remise à zéro des compteurs
    doivent tenir dans la même section critique. Sous eventlet, `/batch-sync`
    rend la main entre les deux — authentification Kavita, inventaire, lecture
    du cache, écriture de la file SQLite : deux onglets, ou un double-clic sur
    « Lancer », lisaient tous les deux « aucun lot en cours » et le second
    remettait `_batch_total`/`_batch_done`/`_batch_real_sends` à zéro EN PLEIN
    MILIEU du premier. Comme `_batch_done` est plafonné par `_batch_total`, la
    barre atteignait alors la fin à la moitié du lot : l'UI recevait
    `remaining: 0`, la barre disparaissait, et l'utilisateur pouvait fermer
    l'onglet ou éteindre le conteneur pendant que la seconde moitié des séries
    s'écrivait encore vers Kavita.

    Rend True si ce paquet a bien ouvert le lot (compteurs repartis de zéro).
    """
    global _batch_total, _batch_done, _batch_real_sends
    with _batch_progress_lock:
        active = _batch_total > 0 and _batch_done < _batch_total
        if not active:
            _batch_total = 0
            _batch_done = 0
            _batch_real_sends = 0
        _batch_total += max(0, int(count))
    return not active


def put_sync(item) -> None:
    """Enqueue FIFO sous lock (producteurs batch / webhook / auto-sync / hydrate)."""
    with _sync_queue_lock:
        sync_queue.put(item)


def put_front(item, *, replace_pending: bool = True) -> int:
    """Insert `item` at the head of the RAM queue (next job after in-flight).

    Does not preempt the job already taken by ``_worker``.

    `replace_pending` (défaut, one-shot Companion) : retire aussi les jobs en
    attente sur la même série — RAM et lignes C63 `queued` — pour que le job
    Companion les remplace vraiment.

    Le bouton « Mettre à jour » d'une ligne passe à False et se contente de
    doubler la file : le lot en attente est constitué par l'utilisateur, et une
    file en pause ne vit qu'en base — une ligne annulée là ne serait jamais
    réhydratée, donc la série quitterait le lot sans un mot. Le second passage ne
    coûte rien : une série déjà à jour est sautée, et si le lot était forcé,
    c'est précisément ce qui avait été demandé.

    Returns the number of pending jobs removed.
    """
    global _batch_done
    sid = int(item["series_id"])
    dropped = 0
    dropped_batch = 0
    with _sync_queue_lock:
        rest = []
        # La file est vidée dans tous les cas : « en tête » ne s'obtient qu'en la
        # reconstruisant derrière le nouveau job.
        while True:
            try:
                pending = sync_queue.get_nowait()
            except queue.Empty:
                break
            is_dupe = isinstance(pending, dict) and int(pending.get("series_id", -1)) == sid
            if is_dupe and replace_pending:
                sync_queue.task_done()
                dropped += 1
                if pending.get("is_batch"):
                    dropped_batch += 1
            else:
                rest.append(pending)

        sync_queue.put(item)
        for other in rest:
            sync_queue.put(other)
            sync_queue.task_done()

    if replace_pending:
        # Clear durable queued rows for this series (paused file, or RAM drop).
        try:
            from services import batch_queue as bq

            bq.cancel_queued_by_series(sid)
        except Exception as exc:
            logging.debug("cancel_queued_by_series skipped: %s", exc)

    if dropped_batch:
        with _batch_progress_lock:
            _batch_done = min(_batch_total, _batch_done + dropped_batch)
            remaining = max(0, _batch_total - _batch_done)
            batch_finished = _batch_total > 0 and _batch_done >= _batch_total
            real_sends = _batch_real_sends
        if batch_finished:
            broadcast_batch_progress(0, real_sends=real_sends)
        else:
            broadcast_batch_progress(remaining)

    return dropped


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


def broadcast_batch_progress(remaining, active=None, series_id=None, stopped=False, real_sends=None):
    """Notifie l'UI (barre de progression batch) via Socket.IO.

    `series_id` (quand une série est en cours) : le liséré violet et le suivi
    de la ligne se font sur cet identifiant, pas sur le texte du journal — le
    titre y est désormais `« Name » (id)`, ce qui ne matche plus `.series-name`.
    `active` reste le titre nu : la barre et la review manuelle s'en servent
    pour savoir qu'un job est encore ouvert (`hasActive`).

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
        if series_id is not None:
            payload["series_id"] = int(series_id)
        if real_sends is not None:
            payload["real_sends"] = int(real_sends)
        socketio.emit("batch_progress", payload)
    except Exception as exc:
        logging.debug("batch_progress emit skipped: %s", exc)


def broadcast_sync_settled(series_id, *, ok: bool) -> None:
    """Fin d'un job unitaire (clic « Mettre à jour », webhook, auto-sync).

    `enrich_series` ne diffuse un `series_status` que quand le statut de la série
    change : Kavita injoignable, métadonnées absentes, série déjà en traitement
    ailleurs ou erreur interne se terminent en silence. Le bouton de la ligne, qui
    ne fait plus qu'enfiler, n'avait alors plus rien pour se rendre la main.
    """
    try:
        from extensions import socketio

        socketio.emit(
            "sync_settled", {"series_id": int(series_id), "ok": bool(ok)}
        )
    except Exception as exc:
        logging.debug("sync_settled emit skipped: %s", exc)


def _item_origin(item) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("origin") or "").strip().lower()


def _should_drain_item(item, *, include_auto: bool) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("is_batch"):
        return True
    return include_auto and _item_origin(item) == "auto"


def _detach_batch_from_ram_unlocked(*, include_auto: bool = False):
    """Retire les items is_batch (et optionnellement origin=auto). Réinsère le reste.

    Pause : `include_auto=False` — la file Auto-sync continue. Stop : True.
    Caller must hold `_sync_queue_lock`.
    Rend (drained_count, drained_auto_items).
    """
    drained = 0
    drained_auto = []
    kept = []
    while True:
        try:
            item = sync_queue.get_nowait()
        except queue.Empty:
            break
        if _should_drain_item(item, include_auto=include_auto):
            if include_auto and _item_origin(item) == "auto":
                drained_auto.append(item)
            sync_queue.task_done()
            drained += 1
        else:
            kept.append(item)

    for item in kept:
        sync_queue.put(item)
        sync_queue.task_done()
    return drained, drained_auto


def drain_sync_queue() -> int:
    """Stop : retire les lots (`is_batch`) et l'Auto-sync (`origin=auto`).

    Webhook et clic ligne restent. Appelé avec cancel SQLite côté stop_batch.
    Les jobs Auto-sync encore en file passent `stopped` dans le rapport de vague.
    """
    with _sync_queue_lock:
        drained, drained_auto = _detach_batch_from_ram_unlocked(include_auto=True)
    reset_batch_progress()
    if drained:
        broadcast_batch_progress(0, stopped=True)
    if drained_auto:
        try:
            from db_manager import mark_auto_sync_items_stopped

            mark_auto_sync_items_stopped(
                item.get("series_id") for item in drained_auto
            )
        except Exception as exc:
            logging.debug("auto-sync report stop skipped: %s", exc)
        if not try_finish_auto_sync_run(stopped=True):
            broadcast_auto_sync_report()
    return drained


def detach_batch_from_ram() -> int:
    """Pause : retire le batch de la RAM sans annuler la file SQLite."""
    with _sync_queue_lock:
        drained, _auto = _detach_batch_from_ram_unlocked(include_auto=False)
    reset_batch_progress()
    if drained:
        broadcast_batch_progress(0, stopped=False)
    return drained


def queued_series_ids(*, batch_only: bool = False, origin=None) -> set:
    """Séries qui attendent déjà leur tour dans la file RAM.

    État DÉRIVÉ de la file, et non un registre tenu en parallèle : un compteur
    alimenté par les quatre producteurs et purgé par le worker se désynchronise
    au premier chemin oublié, et une entrée fantôme exclurait une série de
    l'auto-sync jusqu'au redémarrage du conteneur. La série en cours de
    traitement n'y figure pas (elle a quitté la file) — la réenfiler une fois
    ne coûte qu'un passage « déjà à jour ».

    `origin=` restreint au producteur (`auto` / `webhook` / `row` / `batch`).

    Rend un ensemble vide si la file ne sait pas s'inspecter (double de test).
    """
    mutex = getattr(sync_queue, "mutex", None)
    pending = getattr(sync_queue, "queue", None)
    if mutex is None or pending is None:
        return set()
    want_origin = None if origin is None else str(origin).strip().lower()
    with mutex:
        snapshot = list(pending)
    out = set()
    for item in snapshot:
        if not isinstance(item, dict):
            continue
        if batch_only and not item.get("is_batch"):
            continue
        if want_origin is not None and _item_origin(item) != want_origin:
            continue
        try:
            out.add(int(item["series_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def is_auto_sync_waiting() -> bool:
    """True s'il reste des jobs `origin=auto` en file (pas le scrape en cours)."""
    return bool(queued_series_ids(origin="auto"))


def _set_inflight_origin(origin) -> None:
    global _inflight_origin
    with _inflight_lock:
        _inflight_origin = str(origin or "").strip().lower()


def is_auto_sync_in_flight() -> bool:
    with _inflight_lock:
        return _inflight_origin == "auto"


def broadcast_auto_sync_report(payload=None) -> None:
    """Pastille + modale : la vague a bougé (enqueue, série, Stop, lu)."""
    try:
        from extensions import socketio
        from db_manager import get_auto_sync_report_badge

        socketio.emit(
            "auto_sync_report",
            payload if payload is not None else get_auto_sync_report_badge(),
        )
    except Exception as exc:
        logging.debug("auto_sync_report emit skipped: %s", exc)


def try_finish_auto_sync_run(*, stopped=False, from_worker=False) -> bool:
    """Clôt le rapport quand plus aucun job auto n'attend (ni en file, ni en vol).

    `from_worker=True` : l'item courant vient d'être enregistré et a déjà quitté
    la file — on ne recule pas derrière `is_auto_sync_in_flight()`.
    """
    if queued_series_ids(origin="auto"):
        return False
    if not from_worker and is_auto_sync_in_flight():
        return False
    try:
        from db_manager import finish_open_auto_sync_run

        if not finish_open_auto_sync_run(stopped=stopped):
            return False
    except Exception as exc:
        logging.debug("auto-sync report finish skipped: %s", exc)
        return False
    broadcast_auto_sync_report()
    return True


def _record_auto_sync_job(series_id, series_name, ok, msg) -> None:
    try:
        from db_manager import record_auto_sync_item

        record_auto_sync_item(series_id, series_name, ok, msg)
    except Exception as exc:
        logging.debug("auto-sync report item skipped: %s", exc)
        return
    broadcast_auto_sync_report()


def hydrate_batch_queue_to_ram(*, new_batch=None) -> int:
    """Pousse les lignes SQLite `queued` vers sync_queue (reprise / boot).

    `new_batch=None` : la décision se prend au moment d'incrémenter les
    compteurs (voir `register_batch_enqueue_if_first`), parce que l'appelant
    HTTP la déduirait d'une lecture déjà périmée.

    Les séries déjà présentes en RAM sont écartées : la route « Reprendre »
    hydrate sans condition, et un double-clic empilait donc deux fois chaque
    série — deux enrichissements pour une, et un `_batch_total` doublé qui
    faisait attendre la barre des séries qui n'existaient pas.
    """
    from services import batch_queue as bq

    with _hydrate_lock:
        items = bq.list_queued_for_hydrate()
        already = queued_series_ids(batch_only=True)
        if already:
            items = [s for s in items if int(s["series_id"]) not in already]
        if not items:
            return 0
        if new_batch is None:
            register_batch_enqueue_if_first(len(items))
        else:
            register_batch_enqueue(len(items), new_batch=new_batch)
        for s in items:
            put_sync(
                make_sync_item(
                    s["series_id"],
                    s["series_name"],
                    s["force_update"],
                    s.get("fields_override"),
                    is_batch=True,
                )
            )
        return len(items)


def _abandon_sync_item(series_id, is_batch: bool) -> None:
    """Solde un job qui a échoué sur une erreur inattendue.

    Un item batch doit quand même faire avancer la barre, sinon un batch de 200
    séries reste bloqué à 199 et ne se termine jamais ; un job unitaire doit
    rendre la main au bouton de sa ligne.
    """
    global _batch_done, _batch_real_sends
    if series_id is None:
        return
    if not is_batch:
        broadcast_sync_settled(series_id, ok=False)
        return
    try:
        from services import batch_queue as bq

        bq.mark_done(series_id)
    except Exception as exc:
        logging.debug("mark_done skipped for %s: %s", series_id, exc)
    with _batch_progress_lock:
        _batch_done = min(_batch_total, _batch_done + 1)
        batch_finished = _batch_total > 0 and _batch_done >= _batch_total
        real_sends = _batch_real_sends
    if batch_finished:
        broadcast_batch_progress(0, real_sends=real_sends)


def _worker():
    """Consommateur unique de `sync_queue` (batch, webhook, auto-sync, clic ligne).

    Une seule instance tourne pour tout le process (voir `start_background_workers`) :
    tout ce qui remonte jusqu'à `while True` tue la synchronisation jusqu'au
    redémarrage du conteneur, sans un mot dans l'UI. Le corps de boucle est donc
    borné par un `except Exception` — une série qui explose est une série perdue,
    pas une file morte.
    """
    global _batch_total, _batch_done, _batch_real_sends
    while True:
        item = sync_queue.get()
        series_id = None
        is_batch = False
        item_origin = ""
        series_name = ""
        try:
            if item is None:
                break
            series_id = item["series_id"]
            series_name = item["series_name"]
            force_update = item["force_update"]
            fields_override = item.get("fields_override")
            is_batch = bool(item.get("is_batch"))
            item_origin = _item_origin(item)
            _set_inflight_origin(item_origin)
            item_super_review = bool(item.get("super_review"))
            item_force_auto = bool(item.get("force_auto"))
            item_manual_review = bool(item.get("manual_review_override"))

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
                logging.info(t.get('log_worker_start').format(series_label(series_name, series_id), remaining))
                broadcast_batch_progress(remaining, active=series_name, series_id=series_id)
            else:
                logging.info(t.get('log_worker_start').format(series_label(series_name, series_id), sync_queue.qsize()))

            _ok, _msg, _used = enrich_series(
                series_id,
                series_name,
                force_update,
                targeted_fields_override=fields_override,
                super_review_override=True if item_super_review else None,
                force_auto=item_force_auto,
                manual_review_override=item_manual_review,
            )

            if _msg in _REAL_SEND_MESSAGES:
                record_run_origin(
                    item.get("origin") or ("batch" if is_batch else "row")
                )

            if item_origin == "auto":
                _record_auto_sync_job(series_id, series_name, bool(_ok), _msg)

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
            else:
                # Fin réelle du job : le bouton de la ligne ne peut pas compter sur
                # `series_status`, qui n'est diffusé que si le statut change.
                broadcast_sync_settled(series_id, ok=bool(_ok))
        except Exception as exc:
            logging.error(
                "❌ [Sync] Série %s abandonnée sur erreur inattendue : %s",
                series_id,
                safe_exc_str(exc),
            )
            _abandon_sync_item(series_id, is_batch)
            if item_origin == "auto" and series_id is not None:
                _record_auto_sync_job(series_id, series_name, False, "internal_error")
        finally:
            was_auto = item_origin == "auto"
            _set_inflight_origin("")
            if was_auto:
                try_finish_auto_sync_run(from_worker=True)
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


def _auto_sync_tick(config, t) -> int:
    """Un tour intervalle / filet. Délègue à `run_interval_or_catchup` (C96)."""
    from services.auto_sync import run_interval_or_catchup
    return run_interval_or_catchup(config, t)


def _auto_sync_enabled(config) -> bool:
    try:
        interval = int(config.get("AUTO_SYNC_INTERVAL") or 0)
    except (TypeError, ValueError):
        interval = 0
    enabled = config.get("AUTO_SYNC_ENABLED")
    if enabled is None:
        enabled = interval > 0
    return bool(enabled)


def _auto_sync_should_poll_interval(config) -> bool:
    """Trigger scan : pas de poll minutes (filet / hub à la place)."""
    try:
        interval = int(config.get("AUTO_SYNC_INTERVAL") or 0)
    except (TypeError, ValueError):
        interval = 0
    from services.auto_sync import normalize_trigger
    trigger = normalize_trigger(config.get("AUTO_SYNC_TRIGGER"))
    return _auto_sync_enabled(config) and trigger != "scan" and interval > 0


def _seed_scan_snapshot(config, t) -> bool:
    """GET + snapshot, 0 enqueue. False si inventaire incomplet."""
    from services.auto_sync import fetch_complete_inventory, seed_known_from_inventory

    kavita = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
    if not kavita.authenticate():
        return False
    series = fetch_complete_inventory(kavita)
    if series is None:
        logging.warning(
            t.get(
                "log_orphans_skipped",
                "🧹 Nettoyage des orphelines ignoré : inventaire Kavita incomplet.",
            )
        )
        return False
    seed_known_from_inventory(series)
    logging.info(
        t.get(
            "log_auto_sync_seed",
            "📡 [Auto-Sync] Veille de {0} série(s) — rien à enfiler.",
        ).format(len(series))
    )
    return True


def _auto_sync_worker():
    global _last_catchup_at
    last_interval_run = 0
    prev_trigger = None
    while True:
        try:
            try:
                reason = auto_sync_wake_queue.get(timeout=30)
            except queue.Empty:
                reason = "timeout"
        except Exception as exc:
            logging.error("❌ [Auto-Sync] File de réveil illisible : %s", safe_exc_str(exc))
            time.sleep(0)
            continue

        try:
            config = load_config()
        except Exception as exc:
            logging.error("❌ [Auto-Sync] Configuration illisible : %s", safe_exc_str(exc))
            time.sleep(0)
            continue

        t = translations.get(config.get("UI_LANG", "fr"), translations["fr"])
        from services.auto_sync import (
            catchup_due,
            needs_seed,
            normalize_trigger,
            run_scan_fire,
        )

        try:
            interval = int(config.get("AUTO_SYNC_INTERVAL") or 0)
        except (TypeError, ValueError):
            interval = 0
        enabled = _auto_sync_enabled(config)
        trigger = normalize_trigger(config.get("AUTO_SYNC_TRIGGER"))

        from services import kavita_hub as kh
        if enabled and trigger == "scan":
            kh.start_hub()
        else:
            kh.stop_hub()

        if enabled and trigger == "scan":
            if needs_seed(config, prev_trigger):
                if _seed_scan_snapshot(config, t):
                    _last_catchup_at = time.time()
            if reason == "scan":
                try:
                    run_scan_fire(config, t)
                except Exception as exc:
                    logging.error("❌ [Auto-Sync] Erreur scan : %s", safe_exc_str(exc))
            elif catchup_due(_last_catchup_at, config.get("AUTO_SYNC_CATCHUP_HOURS")):
                try:
                    _auto_sync_tick(config, t)
                    _last_catchup_at = time.time()
                except Exception as exc:
                    logging.error("❌ [Auto-Sync] Erreur filet : %s", safe_exc_str(exc))
        elif enabled and trigger != "scan" and interval > 0:
            current_time = time.time()
            if current_time - last_interval_run >= (interval * 60):
                last_interval_run = current_time
                try:
                    _auto_sync_tick(config, t)
                except Exception as exc:
                    logging.error("❌ [Auto-Sync] Erreur : %s", safe_exc_str(exc))

        prev_trigger = trigger
        time.sleep(0)


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
