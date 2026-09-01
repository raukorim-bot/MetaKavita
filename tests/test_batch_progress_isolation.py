"""
La barre de progression batch (`batch.js::applyBatchProgressPayload`) faisait des
bonds erratiques : `broadcast_batch_progress` se basait sur `sync_queue.qsize()`,
une file PARTAGÉE avec le webhook Kavita et le polling auto-sync. Un événement
Kavita ou un tick auto-sync arrivant en plein batch gonflait/dégonflait ce
compteur sans rapport avec l'avancement réel du batch.

Le fix : `_batch_total`/`_batch_done` (services/background_tasks.py), alimentés
uniquement par les items tagués `is_batch=True` (voir `make_sync_item` /
`register_batch_enqueue`). Ces tests prouvent que :
- un item hors-batch traversant la file pendant un batch ne déclenche AUCUN
  `broadcast_batch_progress` ;
- les items batch avancent bien `remaining` puis signalent la fin ;
- les paquets successifs d'un même batch s'additionnent, un nouveau batch
  redémarre le compteur, et un Stop/drain le remet à zéro.

`_batch_real_sends` (même fichier) résout un second bug apparenté : le nagware
supporter (`onBatchComplete`, static/js/license_nag.js) se déclenchait pour un
batch entièrement composé de séries déjà à jour (skip silencieux, aucune
écriture Kavita). Le signal de fin de batch expose désormais `real_sends`,
compté uniquement sur les messages `enrich_series()` qui correspondent à une
écriture Kavita réelle (`_REAL_SEND_MESSAGES`).
"""
import services.background_tasks as bg


def _put_batch_item(series_id, series_name, force_update=False):
    """C63 : le worker skippe sans ligne SQLite active — seed file + RAM."""
    from services import batch_queue as bq

    bq.enqueue_items([{
        "series_id": series_id,
        "series_name": series_name,
        "force_update": force_update,
    }])
    bg.sync_queue.put(
        bg.make_sync_item(series_id, series_name, force_update, is_batch=True)
    )


def test_worker_ignores_non_batch_items_for_progress(mocker, isolated_db):
    mocker.patch("services.background_tasks.enrich_series", return_value=(True, "ok", []))
    mocker.patch("services.background_tasks.load_config", return_value={"UI_LANG": "fr"})
    calls = []
    mocker.patch(
        "services.background_tasks.broadcast_batch_progress",
        side_effect=lambda *a, **k: calls.append((a, k)),
    )

    bg.register_batch_enqueue(2, new_batch=True)
    _put_batch_item(1, "Batch A")
    # Un événement webhook (ou une candidate auto-sync) intercalé en plein batch :
    # ne doit produire AUCUN broadcast, donc AUCUN saut de barre côté UI.
    bg.sync_queue.put(bg.make_sync_item(999, "Webhook Intruder", False, is_batch=False))
    _put_batch_item(2, "Batch B")
    bg.sync_queue.put(None)  # sentinel : stoppe _worker() après ces items

    bg._worker()

    assert len(calls) == 3, "seuls les 2 items batch (+ le signal de fin) doivent émettre"
    assert calls[0] == ((1,), {"active": "Batch A", "series_id": 1})
    assert calls[1] == ((0,), {"active": "Batch B", "series_id": 2})
    assert calls[2] == ((0,), {"real_sends": 0})


def test_batch_finished_reports_zero_real_sends_when_everything_was_skipped(mocker, isolated_db):
    """Bug rapporté : le nagware supporter se déclenchait pour un batch entièrement
    composé de séries déjà à jour (`enrich_series` renvoie "Déjà à jour." sans
    jamais écrire vers Kavita). Le signal de fin doit exposer `real_sends=0`."""
    mocker.patch(
        "services.background_tasks.enrich_series",
        return_value=(True, "Déjà à jour.", []),
    )
    mocker.patch("services.background_tasks.load_config", return_value={"UI_LANG": "fr"})
    calls = []
    mocker.patch(
        "services.background_tasks.broadcast_batch_progress",
        side_effect=lambda *a, **k: calls.append((a, k)),
    )

    bg.register_batch_enqueue(2, new_batch=True)
    _put_batch_item(1, "Already up to date A")
    _put_batch_item(2, "Already up to date B")
    bg.sync_queue.put(None)

    bg._worker()

    assert calls[-1] == ((0,), {"real_sends": 0})


def test_batch_finished_counts_only_real_kavita_writes(mocker, isolated_db):
    """Un batch mixte (1 skip, 1 écriture réelle, 1 mise en review manuelle) ne
    doit compter que la véritable écriture Kavita dans `real_sends`."""
    results = iter([
        (True, "Déjà à jour.", []),
        (True, "Succès", ["ANILIST"]),
        (True, "PENDING_REVIEW", []),
    ])
    mocker.patch("services.background_tasks.enrich_series", side_effect=lambda *a, **k: next(results))
    mocker.patch("services.background_tasks.load_config", return_value={"UI_LANG": "fr"})
    calls = []
    mocker.patch(
        "services.background_tasks.broadcast_batch_progress",
        side_effect=lambda *a, **k: calls.append((a, k)),
    )

    bg.register_batch_enqueue(3, new_batch=True)
    _put_batch_item(1, "Skip")
    _put_batch_item(2, "Real write")
    _put_batch_item(3, "Parked for review")
    bg.sync_queue.put(None)

    bg._worker()

    assert calls[-1] == ((0,), {"real_sends": 1})


def test_register_batch_enqueue_accumulates_across_packets():
    bg.register_batch_enqueue(50, new_batch=True)
    bg.register_batch_enqueue(50, new_batch=False)
    bg.register_batch_enqueue(30, new_batch=False)

    with bg._batch_progress_lock:
        assert bg._batch_total == 130
        assert bg._batch_done == 0


def test_register_batch_enqueue_resets_on_a_new_batch():
    bg.register_batch_enqueue(50, new_batch=True)
    with bg._batch_progress_lock:
        bg._batch_done = 50  # simule un batch entièrement traité

    bg.register_batch_enqueue(10, new_batch=True)

    with bg._batch_progress_lock:
        assert bg._batch_total == 10
        assert bg._batch_done == 0


def test_drain_sync_queue_resets_batch_progress_counters(mocker):
    mocker.patch("services.background_tasks.broadcast_batch_progress")
    bg.register_batch_enqueue(5, new_batch=True)
    bg.sync_queue.put(bg.make_sync_item(1, "Batch A", False, is_batch=True))

    bg.drain_sync_queue()

    with bg._batch_progress_lock:
        assert bg._batch_total == 0
        assert bg._batch_done == 0


def test_a_batch_item_finishing_after_a_stop_does_not_broadcast_stale_progress(mocker, isolated_db):
    """Le job en cours au moment du Stop n'est pas drainé (voir `drain_sync_queue`) :
    il continue jusqu'au bout. Une fois `_batch_total` remis à zéro par le Stop, sa
    fin ne doit plus émettre de progression (le total de référence n'existe plus).

    On laisse la ligne SQLite active : cas « déjà get()'d / mark_running », pas un
    leftover RAM après cancel (celui-là est skippé sans enrich)."""
    mocker.patch("services.background_tasks.enrich_series", return_value=(True, "ok", []))
    mocker.patch("services.background_tasks.load_config", return_value={"UI_LANG": "fr"})
    calls = []
    mocker.patch(
        "services.background_tasks.broadcast_batch_progress",
        side_effect=lambda *a, **k: calls.append((a, k)),
    )

    bg.register_batch_enqueue(1, new_batch=True)
    _put_batch_item(1, "In-flight when stopped")
    bg.sync_queue.put(None)

    # Le Stop arrive "pendant" le traitement : simulé ici par un reset avant que
    # _worker() ne traite l'item unique déjà dans la file.
    bg.reset_batch_progress()

    bg._worker()

    assert calls == [((0,), {"active": "In-flight when stopped", "series_id": 1})], (
        "le broadcast de démarrage utilise déjà remaining=0 (total réinitialisé) "
        "mais aucun broadcast de FIN ne doit suivre puisque total == 0"
    )


def test_drain_sync_queue_never_drops_non_batch_items(mocker, isolated_db):
    """Stop vide les lots et l'Auto-sync ; webhook et clic ligne restent."""
    mocker.patch("services.background_tasks.broadcast_batch_progress")
    bg.register_batch_enqueue(2, new_batch=True)
    bg.sync_queue.put(bg.make_sync_item(1, "Batch A", False, is_batch=True))
    bg.sync_queue.put(bg.make_sync_item(999, "Webhook Intruder", False, origin="webhook"))
    bg.sync_queue.put(bg.make_sync_item(2, "Batch B", False, is_batch=True))
    bg.sync_queue.put(bg.make_sync_item(998, "Auto-sync tick", False, origin="auto"))
    bg.sync_queue.put(bg.make_sync_item(997, "Row click", False, origin="row"))

    drained = bg.drain_sync_queue()

    assert drained == 3, "2 lots + 1 auto-sync"
    remaining_ids = []
    while not bg.sync_queue.empty():
        remaining_ids.append(bg.sync_queue.get_nowait()["series_id"])
    assert remaining_ids == [999, 997], "webhook et clic ligne restent, dans l'ordre"


def test_drain_sync_queue_does_not_touch_an_empty_queue(mocker):
    mocker.patch("services.background_tasks.broadcast_batch_progress")
    assert bg.drain_sync_queue() == 0
    assert bg.sync_queue.empty()


def test_is_batch_active_reflects_in_flight_progress():
    assert bg.is_batch_active() is False

    bg.register_batch_enqueue(3, new_batch=True)
    assert bg.is_batch_active() is True

    with bg._batch_progress_lock:
        bg._batch_done = 3
    assert bg.is_batch_active() is False, "un batch entièrement traité n'est plus actif"

    bg.reset_batch_progress()
    assert bg.is_batch_active() is False


def test_pause_does_not_drain_auto_sync_jobs(mocker):
    mocker.patch("services.background_tasks.broadcast_batch_progress")
    bg.sync_queue.put(bg.make_sync_item(1, "Batch", False, is_batch=True))
    bg.sync_queue.put(bg.make_sync_item(8, "Auto", False, origin="auto"))

    drained = bg.detach_batch_from_ram()

    assert drained == 1
    remaining = []
    while not bg.sync_queue.empty():
        remaining.append(bg.sync_queue.get_nowait()["origin"])
    assert remaining == ["auto"]


def test_is_auto_sync_waiting_and_origin_filter():
    while not bg.sync_queue.empty():
        bg.sync_queue.get_nowait()
    assert bg.is_auto_sync_waiting() is False
    bg.sync_queue.put(bg.make_sync_item(1, "W", False, origin="webhook"))
    bg.sync_queue.put(bg.make_sync_item(2, "A", False, origin="auto"))
    assert bg.is_auto_sync_waiting() is True
    assert bg.queued_series_ids(origin="auto") == {2}
    assert bg.queued_series_ids(origin="webhook") == {1}
    while not bg.sync_queue.empty():
        bg.sync_queue.get_nowait()
    assert bg.is_auto_sync_waiting() is False
