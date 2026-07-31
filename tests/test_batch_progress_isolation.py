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
"""
import services.background_tasks as bg


def test_worker_ignores_non_batch_items_for_progress(mocker, isolated_db):
    mocker.patch("services.background_tasks.enrich_series", return_value=(True, "ok", []))
    mocker.patch("services.background_tasks.load_config", return_value={"UI_LANG": "fr"})
    calls = []
    mocker.patch(
        "services.background_tasks.broadcast_batch_progress",
        side_effect=lambda *a, **k: calls.append((a, k)),
    )

    bg.register_batch_enqueue(2, new_batch=True)
    bg.sync_queue.put(bg.make_sync_item(1, "Batch A", False, is_batch=True))
    # Un événement webhook (ou une candidate auto-sync) intercalé en plein batch :
    # ne doit produire AUCUN broadcast, donc AUCUN saut de barre côté UI.
    bg.sync_queue.put(bg.make_sync_item(999, "Webhook Intruder", False, is_batch=False))
    bg.sync_queue.put(bg.make_sync_item(2, "Batch B", False, is_batch=True))
    bg.sync_queue.put(None)  # sentinel : stoppe _worker() après ces items

    bg._worker()

    assert len(calls) == 3, "seuls les 2 items batch (+ le signal de fin) doivent émettre"
    assert calls[0] == ((1,), {"active": "Batch A"})
    assert calls[1] == ((0,), {"active": "Batch B"})
    assert calls[2] == ((0,), {})


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
    fin ne doit plus émettre de progression (le total de référence n'existe plus)."""
    mocker.patch("services.background_tasks.enrich_series", return_value=(True, "ok", []))
    mocker.patch("services.background_tasks.load_config", return_value={"UI_LANG": "fr"})
    calls = []
    mocker.patch(
        "services.background_tasks.broadcast_batch_progress",
        side_effect=lambda *a, **k: calls.append((a, k)),
    )

    bg.register_batch_enqueue(1, new_batch=True)
    bg.sync_queue.put(bg.make_sync_item(1, "In-flight when stopped", False, is_batch=True))
    bg.sync_queue.put(None)

    # Le Stop arrive "pendant" le traitement : simulé ici par un reset avant que
    # _worker() ne traite l'item unique déjà dans la file.
    bg.reset_batch_progress()

    bg._worker()

    assert calls == [((0,), {"active": "In-flight when stopped"})], (
        "le broadcast de démarrage utilise déjà remaining=0 (total réinitialisé) "
        "mais aucun broadcast de FIN ne doit suivre puisque total == 0"
    )
