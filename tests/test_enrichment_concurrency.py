"""
Non-régression : `enrich_series()` (services/enrichment_engine.py) a DEUX points
d'entrée indépendants qui peuvent s'exécuter en parallèle sur le même process :

1. `routes/sync.py::force_sync()` — bouton "Sync" d'une ligne, appel HTTP
   SYNCHRONE qui appelle `enrich_series()` directement, hors file d'attente.
2. `services/background_tasks.py::_worker()` — thread de fond unique qui
   dépile `sync_queue` (alimentée par le batch-sync et le webhook Kavita).

Rien n'empêchait qu'un clic sur "Sync" pour une série arrive PENDANT qu'un
webhook pour CETTE MÊME série vient d'être dépilé par le worker : les deux
threads liraient l'état Kavita en parallèle, appliqueraient leurs changements
indépendamment, et l'un écraserait silencieusement le travail de l'autre
(perte de mise à jour) — avec le même risque pour la couverture que le bug de
course historique (voir CODE_REVIEW.md / DEVELOPER.md section 11).

Ces tests vérifient le verrou en mémoire `_processing_series_ids` qui rejette
toute requête concurrente pour un `series_id` déjà en cours de traitement, et
qu'il est bien libéré une fois le traitement terminé (succès, échec ou
exception) pour ne jamais bloquer une série indéfiniment.
"""
import threading

from kavita_api import KavitaAPI
from services import enrichment_engine


def _patch_minimal_config(mocker):
    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "fake-key",
        "UI_LANG": "fr",
    })


def test_immediate_rejection_when_series_id_already_marked_as_processing(mocker):
    """Cas simple : si l'id est déjà dans le set, on ne doit même pas atteindre
    load_config()/KavitaAPI (rejet avant tout effet de bord)."""
    _patch_minimal_config(mocker)
    mock_authenticate = mocker.patch.object(KavitaAPI, "authenticate")

    enrichment_engine._processing_series_ids.add(123)
    try:
        result = enrichment_engine.enrich_series(123, "Série Déjà En Cours")
    finally:
        enrichment_engine._processing_series_ids.discard(123)

    assert result == (False, "Déjà en cours de traitement.", [])
    mock_authenticate.assert_not_called()


def test_concurrent_call_for_same_series_is_rejected_then_lock_is_released(mocker):
    """Preuve par la concurrence réelle : un appel bloqué sur authenticate()
    doit empêcher un second appel PARALLÈLE sur le même series_id, et libérer
    le verrou une fois terminé pour ne pas bloquer les futurs traitements."""
    _patch_minimal_config(mocker)

    entered_event = threading.Event()
    release_event = threading.Event()

    def blocking_authenticate(self):
        entered_event.set()
        release_event.wait(timeout=2)
        return False

    mocker.patch.object(KavitaAPI, "authenticate", blocking_authenticate)

    results = {}

    def run_first_call():
        results["first"] = enrichment_engine.enrich_series(999, "Série Concurrente")

    first_thread = threading.Thread(target=run_first_call)
    first_thread.start()

    assert entered_event.wait(timeout=2), "Le premier appel n'a pas démarré à temps"

    # Le premier traitement est bloqué "en cours" : un second appel concurrent
    # sur LA MÊME série doit être rejeté immédiatement, pas exécuté en double.
    second_result = enrichment_engine.enrich_series(999, "Série Concurrente")
    assert second_result == (False, "Déjà en cours de traitement.", [])

    release_event.set()
    first_thread.join(timeout=2)

    assert results["first"] == (False, "Erreur Kavita.", [])
    # Le verrou doit être libéré une fois le premier traitement terminé, pour
    # ne pas bloquer indéfiniment les futurs Sync/webhooks sur cette série.
    assert 999 not in enrichment_engine._processing_series_ids

    mocker.patch.object(KavitaAPI, "authenticate", return_value=False)
    third_result = enrichment_engine.enrich_series(999, "Série Concurrente")
    assert third_result != (False, "Déjà en cours de traitement.", [])


def test_lock_is_released_even_if_enrich_series_raises(mocker):
    """La libération du verrou passe par un `finally` : même un crash inattendu
    (branche `except Exception` déjà existante) ne doit jamais laisser une
    série verrouillée pour toujours."""
    _patch_minimal_config(mocker)
    mocker.patch.object(KavitaAPI, "authenticate", side_effect=RuntimeError("boom"))

    result = enrichment_engine.enrich_series(555, "Série Qui Plante")

    assert result == (False, "Erreur interne.", [])
    assert 555 not in enrichment_engine._processing_series_ids
