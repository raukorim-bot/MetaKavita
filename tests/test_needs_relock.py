"""NEEDS_RELOCK : soft-fail re-lock → statut orange + seal différé."""

import time

from kavita_api import KavitaAPI
from services import kavita_payload
from services.kavita_payload import build_kavita_payload


def test_apply_kavita_payload_sets_needs_relock_when_unsealed(mocker, isolated_db):
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")
    mocker.patch("services.kavita_payload._schedule_seal_retry")

    class FakeKavita:
        def update_series_external_ids(self, *a, **k):
            return True, "ok"

        def update_series_metadata(self, meta):
            return True, "Succès (écriture OK ; re-lock échoué: timeout)", False

        def update_series_general(self, *a, **k):
            return True, "Succès", True

        def upload_series_cover(self, *a, **k):
            return True, "ok"

    built = {
        "metadata": {"seriesId": 55, "summary": "Hi", "summaryLocked": True},
        "localized_name": None,
        "format_val": None,
        "cover_url": None,
        "external_ids": {},
    }
    t = {"log_sending": "[{0}] send", "log_success": "[{0}] ok", "log_needs_relock": "[{0}] needs", "log_kavita_refused": "[{0}] refuse {1}"}

    ok, msg, used = kavita_payload.apply_kavita_payload(
        FakeKavita(),
        55,
        "Series X",
        built,
        ["summary"],
        {},
        ["ANILIST"],
        t,
    )

    assert ok is True
    assert msg == "NEEDS_RELOCK"
    assert isolated_db.get_all_cached_data()[55]["status"] == "NEEDS_RELOCK"
    kavita_payload._schedule_seal_retry.assert_called_once()


def test_apply_kavita_payload_completed_when_sealed(mocker, isolated_db):
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")
    sched = mocker.patch("services.kavita_payload._schedule_seal_retry")

    class FakeKavita:
        def update_series_external_ids(self, *a, **k):
            return True, "ok"

        def update_series_metadata(self, meta):
            return True, "Succès", True

        def update_series_general(self, *a, **k):
            return True, "Succès", True

        def upload_series_cover(self, *a, **k):
            return True, "ok"

    built = {
        "metadata": {"seriesId": 56, "summary": "Hi", "summaryLocked": True},
        "localized_name": None,
        "format_val": None,
        "cover_url": None,
        "external_ids": {},
    }
    t = {"log_sending": "[{0}] send", "log_success": "[{0}] ok", "log_needs_relock": "[{0}] needs", "log_kavita_refused": "[{0}] refuse {1}"}

    ok, msg, used = kavita_payload.apply_kavita_payload(
        FakeKavita(),
        56,
        "Series Y",
        built,
        ["summary"],
        {},
        ["ANILIST"],
        t,
    )

    assert ok is True
    assert msg == "Succès"
    assert isolated_db.get_all_cached_data()[56]["status"] == "COMPLETED"
    sched.assert_not_called()


def test_schedule_seal_retry_seals_on_success(mocker, isolated_db):
    """Cas normal : la série n'est réclamée par personne, le retry doit sceller."""
    mocker.patch("services.kavita_payload._emit_series_status")
    mocker.patch(
        "config_manager.load_config",
        return_value={"KAVITA_URL": "http://kavita.test", "KAVITA_API_KEY": "key"},
    )
    fake_api = mocker.Mock()
    fake_api.authenticate.return_value = True
    fake_api.seal_series_locks.return_value = (True, "ok")
    mocker.patch("kavita_api.KavitaAPI", return_value=fake_api)

    from services.enrichment_engine import _processing_series_ids

    kavita_payload._schedule_seal_retry(77, "Series Z", delay_s=0.01)
    time.sleep(0.2)

    fake_api.seal_series_locks.assert_called_once_with(77, lock_keys=None)
    assert isolated_db.get_all_cached_data()[77]["status"] == "COMPLETED"
    assert 77 not in _processing_series_ids, "le verrou doit être relâché en fin de retry"


def test_schedule_seal_retry_skips_a_series_already_being_processed(mocker, isolated_db):
    """Une série déjà réclamée (re-scrape concurrent) ne doit pas être touchée par
    le retry — c'est exactement le scénario que `_processing_lock` doit éviter."""
    mocker.patch("services.kavita_payload._emit_series_status")
    fake_api = mocker.Mock()
    mocker.patch("kavita_api.KavitaAPI", return_value=fake_api)

    from services.enrichment_engine import _processing_lock, _processing_series_ids

    with _processing_lock:
        _processing_series_ids.add(78)
    try:
        kavita_payload._schedule_seal_retry(78, "Series W", delay_s=0.01)
        time.sleep(0.2)
        fake_api.authenticate.assert_not_called()
        fake_api.seal_series_locks.assert_not_called()
    finally:
        with _processing_lock:
            _processing_series_ids.discard(78)


# --- Portée du scellement différé ------------------------------------------
#
# Ce que Kavita porte déjà quand la passe commence : un éditeur et une
# classification d'âge posés par le scan de fichiers (ComicInfo.xml), verrous
# laissés ouverts par l'utilisateur pour qu'un prochain scan les corrige. La
# passe, elle, n'a que le résumé et le statut dans son masque.
SCANNED_META = {
    "seriesId": 55,
    "summary": "",
    "summaryLocked": False,
    "publishers": [{"id": 3, "name": "Glénat"}],
    "publisherLocked": False,
    "ageRating": 8,
    "ageRatingLocked": False,
    "publicationStatus": 0,
    "publicationStatusLocked": False,
}

SERIES_DTO = {
    "id": 55,
    "name": "Série Cible",
    "sortName": "Série Cible",
    "localizedName": None,
    "nameLocked": False,
    "sortNameLocked": False,
    "localizedNameLocked": False,
    "coverImageLocked": False,
}


class _SoftFailRelock:
    """Écriture acceptée, second passage (RE-LOCK) perdu : le cas NEEDS_RELOCK."""

    def update_series_external_ids(self, *a, **k):
        return True, "ok"

    def update_series_metadata(self, meta):
        return True, "Succès (écriture OK ; re-lock échoué: timeout)", False

    def update_series_general(self, *a, **k):
        return True, "Succès", True

    def upload_series_cover(self, *a, **k):
        return True, "ok"


def _summary_and_status_pass(mocker):
    """Le payload d'une passe réelle : masque « résumé + statut », rien d'autre."""
    mocker.patch(
        "services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text
    )
    return build_kavita_payload(
        {"summary": "Un résumé", "status": "RELEASING"},
        dict(SCANNED_META),
        ["summary", "status"],
        {"TARGET_LANG": "FR"},
        {},
        True,
        55,
    )


def _seal_with(mocker, lock_keys):
    """Rejoue le scellement différé sur un vrai client Kavita, HTTP mocké.

    Rend le payload `seriesMetadata` réellement posté.
    """
    api = KavitaAPI("http://kavita.local", "fake-api-key")
    api.token = "fake-token"
    api.headers = {"Authorization": "Bearer fake-token"}
    # Au moment du scellement, Kavita porte ce que la passe vient d'écrire.
    mocker.patch.object(
        api,
        "get_series_metadata",
        return_value=dict(SCANNED_META, summary="Un résumé", publicationStatus=0),
    )
    mocker.patch.object(api, "get_series", return_value=dict(SERIES_DTO))
    post = mocker.patch(
        "kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK")
    )

    ok, _msg = api.seal_series_locks(55, lock_keys=lock_keys)

    assert ok is True
    return post.call_args_list[0].kwargs["json"]["seriesMetadata"]


def test_the_deferred_seal_only_gets_the_locks_the_pass_closed(mocker, isolated_db):
    """L'appelant est le seul à savoir ce que sa passe a écrit : il doit le dire.

    Sans cette liste, `seal_series_locks` se replie sur « tout verrou dont le
    champ porte du contenu » — un repli raisonnable pour une action manuelle,
    mais faux ici : le contenu de l'éditeur vient du scan de fichiers, pas de
    cette passe.
    """
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")
    sched = mocker.patch("services.kavita_payload._schedule_seal_retry")
    built = _summary_and_status_pass(mocker)

    ok, msg, _used = kavita_payload.apply_kavita_payload(
        _SoftFailRelock(),
        55,
        "Série Cible",
        built,
        ["summary", "status"],
        {},
        ["ANILIST"],
        {
            "log_sending": "[{0}] send",
            "log_success": "[{0}] ok",
            "log_needs_relock": "[{0}] needs",
            "log_kavita_refused": "[{0}] refuse {1}",
        },
    )

    assert (ok, msg) == (True, "NEEDS_RELOCK")
    lock_keys = sched.call_args.kwargs["lock_keys"]
    assert set(lock_keys) == {"summaryLocked", "publicationStatusLocked"}
    assert "publisherLocked" not in lock_keys, (
        "l'éditeur vient du scan de fichiers : cette passe ne l'a pas écrit"
    )
    assert "ageRatingLocked" not in lock_keys


def test_the_deferred_seal_leaves_the_publisher_open_and_closes_the_status(mocker, isolated_db):
    """Le même scénario mené jusqu'au POST, verrou par verrou.

    Deux erreurs opposées disparaissent d'un coup, et aucune des deux ne se voit
    dans un journal — Kavita répond 200 dans les deux cas :

    * `publisherLocked` était fermé à tort. L'éditeur est rempli, donc le repli
      le scellait ; il venait du scan de fichiers et l'utilisateur l'avait laissé
      ouvert exprès. Une fois fermé, aucun scan ne peut plus le corriger.
    * `publicationStatusLocked` était laissé ouvert à tort. La passe a écrit
      « en cours », que Kavita code par l'entier `0` : pour le repli, le champ
      est vide, donc rien à protéger — alors que c'est bien MetaKavita qui vient
      de l'écrire, et que le prochain scan le remettra à sa valeur par défaut.
    """
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")
    sched = mocker.patch("services.kavita_payload._schedule_seal_retry")
    built = _summary_and_status_pass(mocker)

    kavita_payload.apply_kavita_payload(
        _SoftFailRelock(),
        55,
        "Série Cible",
        built,
        ["summary", "status"],
        {},
        ["ANILIST"],
        {
            "log_sending": "[{0}] send",
            "log_success": "[{0}] ok",
            "log_needs_relock": "[{0}] needs",
            "log_kavita_refused": "[{0}] refuse {1}",
        },
    )

    sealed = _seal_with(mocker, sched.call_args.kwargs["lock_keys"])

    assert sealed["summaryLocked"] is True
    assert sealed["publicationStatusLocked"] is True, (
        "statut « en cours » (0) écrit par la passe, mais laissé déverrouillé"
    )
    assert sealed["publisherLocked"] is False, (
        "verrou fermé sur un éditeur que MetaKavita n'a jamais écrit"
    )
    assert sealed["ageRatingLocked"] is False


def test_without_a_list_the_seal_guesses_and_gets_both_fields_wrong(mocker):
    """Caractérisation du repli, pour que la différence soit lisible : c'est
    exactement ce que le scellement différé faisait avant de recevoir sa liste."""
    sealed = _seal_with(mocker, None)

    assert sealed["publisherLocked"] is True
    assert sealed["publicationStatusLocked"] is False
