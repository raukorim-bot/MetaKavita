"""
Le thread `_worker` (services/background_tasks.py) est unique et démarré une
seule fois au boot (`start_background_workers`). Deux conséquences que ces tests
verrouillent :

1. Une exception inattendue dans le corps de boucle — hors du `try` interne de
   `enrich_series` : SQLite verrouillé sur `should_skip_batch_item`, un emit
   Socket.IO, une traduction manquante — faisait sortir de `while True` et tuait
   le thread. Plus aucune série n'était traitée jusqu'au redémarrage du
   conteneur : batch figé à mi-parcours, webhooks et candidates auto-sync
   empilés dans une file que personne ne dépile, et rien dans l'UI pour le dire.

2. `enrich_series` ne diffuse pas toujours un `series_status` (Kavita
   injoignable, métadonnées absentes, série déjà en cours de traitement,
   erreur interne). Depuis que le bouton « Mettre à jour » d'une ligne se
   contente d'enfiler (BF109), c'est ce statut qui rend la main au bouton : sans
   signal de fin de job, la ligne tournait jusqu'au chien de garde de 10
   minutes. Le worker annonce donc la fin réelle de chaque job unitaire.
"""
import services.background_tasks as bg


def _no_config(mocker):
    mocker.patch(
        "services.background_tasks.load_config", return_value={"UI_LANG": "fr"}
    )


def _settled(mocker):
    """Capture les signaux de fin de job unitaire émis par le worker."""
    events = []
    mocker.patch(
        "services.background_tasks.broadcast_sync_settled",
        side_effect=lambda *a, **k: events.append((a, k)),
    )
    return events


def test_a_crash_on_one_series_does_not_kill_the_worker(mocker, isolated_db):
    _no_config(mocker)
    _settled(mocker)
    seen = []

    def _enrich(series_id, *a, **k):
        seen.append(series_id)
        if series_id == 1:
            raise RuntimeError("database is locked")
        return True, "Succès", []

    mocker.patch("services.background_tasks.enrich_series", side_effect=_enrich)

    bg.sync_queue.put(bg.make_sync_item(1, "Explose", False))
    bg.sync_queue.put(bg.make_sync_item(2, "Suivante", False))
    bg.sync_queue.put(None)

    bg._worker()

    assert seen == [1, 2], "la série suivante doit être traitée malgré l'échec de la première"
    life = isolated_db.get_lifetime_stats()
    assert life["runs_row"] == 1
    assert life["runs_batch"] == 0


def test_a_crashed_batch_series_still_advances_the_bar(mocker, isolated_db):
    """Sinon la barre reste bloquée sur N-1/N et le batch ne se termine jamais."""
    from services import batch_queue as bq

    _no_config(mocker)
    _settled(mocker)
    mocker.patch(
        "services.background_tasks.enrich_series",
        side_effect=RuntimeError("boom"),
    )
    calls = []
    mocker.patch(
        "services.background_tasks.broadcast_batch_progress",
        side_effect=lambda *a, **k: calls.append((a, k)),
    )

    bg.register_batch_enqueue(1, new_batch=True)
    bq.enqueue_items([{"series_id": 5, "series_name": "Batch KO", "force_update": False}])
    bg.sync_queue.put(bg.make_sync_item(5, "Batch KO", False, is_batch=True))
    bg.sync_queue.put(None)

    bg._worker()

    assert calls[-1] == ((0,), {"real_sends": 0}), \
        "un échec doit compter comme traité, sinon la barre ne retombe jamais à zéro"
    assert isolated_db.get_lifetime_stats()["runs_batch"] == 0


def test_every_single_sync_gets_a_settled_signal(mocker, isolated_db):
    """Kavita injoignable : aucun `series_status` n'est diffusé, le bouton de la
    ligne n'a que ce signal pour se rendre la main."""
    _no_config(mocker)
    events = _settled(mocker)
    mocker.patch(
        "services.background_tasks.enrich_series",
        return_value=(False, "Erreur Kavita.", []),
    )

    bg.sync_queue.put(bg.make_sync_item(42, "Sans statut", True))
    bg.sync_queue.put(None)

    bg._worker()

    assert events == [((42,), {"ok": False})]
    assert isolated_db.get_lifetime_stats()["runs_row"] == 0


def test_a_crash_also_settles_the_row_button(mocker, isolated_db):
    _no_config(mocker)
    events = _settled(mocker)
    mocker.patch(
        "services.background_tasks.enrich_series",
        side_effect=RuntimeError("boom"),
    )

    bg.sync_queue.put(bg.make_sync_item(42, "Explose", True))
    bg.sync_queue.put(None)

    bg._worker()

    assert events == [((42,), {"ok": False})]
    assert isolated_db.get_lifetime_stats()["runs_row"] == 0


def test_a_batch_series_does_not_settle_a_row_button(mocker, isolated_db):
    """Le lot a sa propre barre ; ce signal ne concerne que le clic unitaire."""
    from services import batch_queue as bq

    _no_config(mocker)
    events = _settled(mocker)
    mocker.patch(
        "services.background_tasks.enrich_series", return_value=(True, "Succès", [])
    )
    mocker.patch("services.background_tasks.broadcast_batch_progress")

    bg.register_batch_enqueue(1, new_batch=True)
    bq.enqueue_items([{"series_id": 7, "series_name": "Batch", "force_update": False}])
    bg.sync_queue.put(bg.make_sync_item(7, "Batch", False, is_batch=True))
    bg.sync_queue.put(None)

    bg._worker()

    assert events == []
    life = isolated_db.get_lifetime_stats()
    assert life["runs_batch"] == 1
    assert life["runs_row"] == 0


def test_a_successful_single_sync_settles_ok(mocker, isolated_db):
    _no_config(mocker)
    events = _settled(mocker)
    mocker.patch(
        "services.background_tasks.enrich_series", return_value=(True, "Succès", [])
    )

    bg.sync_queue.put(bg.make_sync_item(42, "OK", True))
    bg.sync_queue.put(None)

    bg._worker()

    assert events == [((42,), {"ok": True})]
    life = isolated_db.get_lifetime_stats()
    assert life["runs_row"] == 1
    assert life["runs_batch"] == 0
    assert life["runs_webhook"] == 0


def test_an_already_up_to_date_series_is_not_a_run(mocker, isolated_db):
    _no_config(mocker)
    _settled(mocker)
    mocker.patch(
        "services.background_tasks.enrich_series",
        return_value=(True, "Déjà à jour.", []),
    )

    bg.sync_queue.put(bg.make_sync_item(42, "Skip", True))
    bg.sync_queue.put(None)

    bg._worker()

    assert isolated_db.get_lifetime_stats()["runs_row"] == 0


def test_a_webhook_write_counts_as_webhook(mocker, isolated_db):
    _no_config(mocker)
    _settled(mocker)
    mocker.patch(
        "services.background_tasks.enrich_series", return_value=(True, "Succès", [])
    )

    bg.sync_queue.put(bg.make_sync_item(42, "From webhook", True, origin="webhook"))
    bg.sync_queue.put(None)

    bg._worker()

    life = isolated_db.get_lifetime_stats()
    assert life["runs_webhook"] == 1
    assert life["runs_row"] == 0
