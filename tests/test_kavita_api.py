"""
Non-régression sur les deux bugs critiques corrigés dans kavita_api.py :

1. update_series_general() envoyait des payloads PARTIELS à Kavita. Comme
   Kavita ne protège pas `localizedName`/`nameLocked`/`sortNameLocked`/
   `localizedNameLocked` côté serveur (contrairement à `name`/`sortName`),
   toute clé absente du JSON était réinitialisée à null/false, ce qui a
   cassé l'extension KOReader "Kamare" (crash sur localizedName == null).
   Le correctif : toujours faire un GET /api/Series/{id} avant le POST, et
   ré-injecter explicitement l'état actuel de tout champ non modifié.

2. update_series_metadata() renvoyait à Kavita des propriétés calculées/
   système (totalCount, maxCount, pages, wordCount, created, lastModified)
   récupérées via un GET préalable, ce qui provoquait des valeurs aberrantes
   côté Kavita (ex: maxCount:-100000) et un crash de l'ingestion.

3. Soft-success 2-pass + KAVITA_HTTP_TIMEOUT (issue SqueezedByte) : si l'écriture
   réussit mais le RE-LOCK timeout, l'opération est un succès (données déjà
   persistées). Un seul retry léger du RE-LOCK (timeout retry plafonné à 20s)
   tente de sceller les verrous sans rejouer scrape/écriture. sealed=False
   propage le soft-fail vers le statut NEEDS_RELOCK.
"""
import pytest
import requests

from kavita_api import KavitaAPI, _RELOCK_RETRY_TIMEOUT_CAP_S


def _authenticated_api():
    api = KavitaAPI("http://kavita.local", "fake-api-key")
    api.token = "fake-token"
    api.headers = {"Authorization": "Bearer fake-token", "Content-Type": "application/json"}
    return api


class TestUpdateSeriesGeneral:
    def test_fetches_current_state_before_posting(self, mocker):
        api = _authenticated_api()
        current_state = {
            "id": 42,
            "name": "One Piece",
            "sortName": "One Piece",
            "localizedName": "Wan Pisu",
            "nameLocked": True,
            "sortNameLocked": True,
            "localizedNameLocked": True,
        }
        mock_get = mocker.patch("kavita_api.requests.get")
        mock_get.return_value = mocker.Mock(status_code=200, json=lambda: current_state)
        mock_post = mocker.patch("kavita_api.requests.post")
        mock_post.return_value = mocker.Mock(status_code=200, text="OK")

        success, _, sealed = api.update_series_general(42, format_val=3)

        assert success is True
        assert sealed is True
        mock_get.assert_called_once()
        assert mock_post.call_count == 2  # protocole Unlock -> Write -> Lock

    def test_never_sends_null_localized_name_when_not_explicitly_changed(self, mocker):
        """C'est exactement le bug qui a cassé KOReader : appeler l'update pour
        changer uniquement le format ne doit JAMAIS nuller localizedName."""
        api = _authenticated_api()
        current_state = {
            "id": 42,
            "name": "One Piece",
            "sortName": "One Piece",
            "localizedName": "Wan Pisu",
            "nameLocked": True,
            "sortNameLocked": True,
            "localizedNameLocked": True,
        }
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current_state))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        success, _, sealed = api.update_series_general(42, localized_name=None, format_val=3)

        assert success is True
        assert sealed is True
        for call in mock_post.call_args_list:
            payload = call.kwargs["json"]
            assert payload["localizedName"] == "Wan Pisu"
            assert payload["localizedName"] is not None
            assert payload["localizedNameLocked"] is True

    def test_never_resets_name_and_sort_name_locks(self, mocker):
        api = _authenticated_api()
        current_state = {
            "id": 42,
            "name": "One Piece",
            "sortName": "One Piece",
            "localizedName": None,
            "nameLocked": True,
            "sortNameLocked": True,
            "localizedNameLocked": False,
        }
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current_state))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.update_series_general(42, format_val=2)

        for call in mock_post.call_args_list:
            payload = call.kwargs["json"]
            assert payload["nameLocked"] is True
            assert payload["sortNameLocked"] is True

    def test_explicit_localized_name_uses_unlock_relock(self, mocker):
        api = _authenticated_api()
        current_state = {
            "id": 42,
            "name": "One Piece",
            "sortName": "One Piece",
            "localizedName": None,
            "nameLocked": False,
            "sortNameLocked": False,
            "localizedNameLocked": False,
        }
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current_state))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        success, _, sealed = api.update_series_general(42, localized_name="Wan Pisu")

        assert success is True
        assert sealed is True
        unlock_payload = mock_post.call_args_list[0].kwargs["json"]
        lock_payload = mock_post.call_args_list[1].kwargs["json"]
        assert unlock_payload["localizedNameLocked"] is False
        assert lock_payload["localizedNameLocked"] is True

    def test_noop_when_nothing_to_update(self, mocker):
        api = _authenticated_api()
        mock_get = mocker.patch("kavita_api.requests.get")
        mock_post = mocker.patch("kavita_api.requests.post")

        success, _, sealed = api.update_series_general(42)

        assert success is True
        assert sealed is True
        mock_get.assert_not_called()
        mock_post.assert_not_called()


class TestUpdateSeriesMetadataSanitization:
    def test_strips_system_properties_before_post(self, mocker):
        api = _authenticated_api()
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))
        metadata = {
            "seriesId": 1,
            "summary": "Hello",
            "summaryLocked": True,
            "totalCount": 99,
            "maxCount": -100000,
            "pages": 12,
            "wordCount": 0,
            "created": "2020-01-01",
            "lastModified": "2020-01-02",
        }

        success, _, sealed = api.update_series_metadata(metadata)

        assert success is True
        assert sealed is True
        sent = mock_post.call_args_list[0].kwargs["json"]["seriesMetadata"]
        for key in ("totalCount", "maxCount", "pages", "wordCount", "created", "lastModified"):
            assert key not in sent

    def test_unlock_then_relock_protocol(self, mocker):
        api = _authenticated_api()
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))
        metadata = {"seriesId": 1, "summary": "Test", "summaryLocked": True, "genresLocked": True}

        api.update_series_metadata(metadata)

        unlock_payload = mock_post.call_args_list[0].kwargs["json"]["seriesMetadata"]
        lock_payload = mock_post.call_args_list[1].kwargs["json"]["seriesMetadata"]
        assert unlock_payload["summaryLocked"] is False
        assert unlock_payload["genresLocked"] is False
        assert lock_payload["summaryLocked"] is True
        assert lock_payload["genresLocked"] is True

    def test_aborts_if_first_call_fails(self, mocker):
        api = _authenticated_api()
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=500, text="Server Error"))

        success, msg, sealed = api.update_series_metadata({"seriesId": 1})

        assert success is False
        assert sealed is False
        assert mock_post.call_count == 1

    def test_relock_timeout_is_soft_success_after_write_ok(self, mocker):
        """Issue SqueezedByte : étape 1 = 200, RE-LOCK timeout×2 → soft-success sealed=False."""
        api = _authenticated_api()
        api._write_timeout_override = 60
        mocker.patch("kavita_api.time.sleep")

        ok = mocker.Mock(status_code=200, text="Successfully updated")
        mock_post = mocker.patch(
            "kavita_api.requests.post",
            side_effect=[
                ok,
                requests.exceptions.ReadTimeout("read timeout=60"),
                requests.exceptions.ReadTimeout("read timeout=20"),
            ],
        )

        success, msg, sealed = api.update_series_metadata({
            "seriesId": 19797,
            "summary": "After watching a video...",
            "summaryLocked": True,
        })

        assert success is True
        assert sealed is False
        assert "écriture OK" in msg
        assert mock_post.call_count == 3  # write + lock + lock retry
        assert mock_post.call_args_list[0].kwargs["timeout"] == 60
        assert mock_post.call_args_list[1].kwargs["timeout"] == 60
        assert mock_post.call_args_list[2].kwargs["timeout"] == _RELOCK_RETRY_TIMEOUT_CAP_S

    def test_relock_succeeds_on_retry(self, mocker):
        api = _authenticated_api()
        api._write_timeout_override = 60
        mocker.patch("kavita_api.time.sleep")
        ok = mocker.Mock(status_code=200, text="OK")
        mock_post = mocker.patch(
            "kavita_api.requests.post",
            side_effect=[
                ok,
                requests.exceptions.ReadTimeout("read timeout=60"),
                ok,
            ],
        )

        success, msg, sealed = api.update_series_metadata({
            "seriesId": 1,
            "summaryLocked": True,
        })

        assert success is True
        assert sealed is True
        assert msg == "Succès"
        assert mock_post.call_count == 3
        assert mock_post.call_args_list[2].kwargs["timeout"] == _RELOCK_RETRY_TIMEOUT_CAP_S

    def test_relock_http_error_is_soft_success_after_write_ok(self, mocker):
        api = _authenticated_api()
        mocker.patch("kavita_api.time.sleep")
        ok = mocker.Mock(status_code=200, text="OK")
        bad = mocker.Mock(status_code=504, text="Gateway Timeout")
        mock_post = mocker.patch("kavita_api.requests.post", side_effect=[ok, bad, bad])

        success, msg, sealed = api.update_series_metadata({"seriesId": 1, "summaryLocked": True})

        assert success is True
        assert sealed is False
        assert "re-lock échoué" in msg
        assert mock_post.call_count == 3

    def test_write_timeout_override_is_passed_to_posts(self, mocker):
        api = _authenticated_api()
        api._write_timeout_override = 90
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))
        api.update_series_metadata({"seriesId": 1})
        assert mock_post.call_args_list[0].kwargs["timeout"] == 90

    def test_general_relock_timeout_is_soft_success(self, mocker):
        api = _authenticated_api()
        api._write_timeout_override = 60
        mocker.patch("kavita_api.time.sleep")
        current_state = {
            "id": 42,
            "name": "One Piece",
            "sortName": "One Piece",
            "localizedName": "Wan Pisu",
            "nameLocked": True,
            "sortNameLocked": True,
            "localizedNameLocked": True,
        }
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current_state))
        ok = mocker.Mock(status_code=200, text="OK")
        mock_post = mocker.patch(
            "kavita_api.requests.post",
            side_effect=[
                ok,
                requests.exceptions.ReadTimeout("read timeout=60"),
                requests.exceptions.ReadTimeout("read timeout=20"),
            ],
        )

        success, msg, sealed = api.update_series_general(42, format_val=3)

        assert success is True
        assert sealed is False
        assert "écriture OK" in msg
        assert mock_post.call_count == 3


class TestSealSeriesLocks:
    def test_seal_sets_all_locked_true(self, mocker):
        api = _authenticated_api()
        meta = {
            "seriesId": 7,
            "summary": "Hello",
            "summaryLocked": False,
            "genresLocked": False,
            "totalCount": 1,
        }
        series = {
            "id": 7,
            "name": "X",
            "sortName": "X",
            "localizedName": "Y",
            "nameLocked": False,
            "sortNameLocked": False,
            "localizedNameLocked": False,
            "format": 1,
        }
        mocker.patch.object(api, "get_series_metadata", return_value=dict(meta))
        mocker.patch.object(api, "get_series", return_value=dict(series))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        ok, msg = api.seal_series_locks(7)

        assert ok is True
        assert mock_post.call_count == 2
        meta_payload = mock_post.call_args_list[0].kwargs["json"]["seriesMetadata"]
        assert meta_payload["summaryLocked"] is True
        assert meta_payload["genresLocked"] is True
        assert "totalCount" not in meta_payload
        gen_payload = mock_post.call_args_list[1].kwargs["json"]
        assert gen_payload["localizedNameLocked"] is True
        assert gen_payload["formatLocked"] is True


class TestCachedLibraryId:
    """`get_cached_library_id` alimente le lien de vérification Kavita du pick UI
    de la review manuelle (voir services/manual_review.py) — sans coût réseau
    supplémentaire au-delà de l'appel `get_library_type_for_series` déjà fait
    par `enrich_series()`."""

    def _mock_get(self, mocker, libraries, series_by_id):
        def _side_effect(url, headers=None, timeout=None):
            if url.endswith("/api/Library/libraries"):
                return mocker.Mock(status_code=200, json=lambda: libraries)
            for sid, payload in series_by_id.items():
                if url.endswith(f"/api/Series/{sid}"):
                    return mocker.Mock(status_code=200, json=lambda payload=payload: payload)
            return mocker.Mock(status_code=404, json=lambda: {})

        return mocker.patch("kavita_api.requests.get", side_effect=_side_effect)

    def test_is_none_before_any_resolution(self):
        api = _authenticated_api()
        assert api.get_cached_library_id(999) is None

    def test_gets_populated_by_get_library_type_for_series(self, mocker):
        api = _authenticated_api()
        self._mock_get(
            mocker,
            libraries=[{"id": 3, "type": "Manga"}],
            series_by_id={42: {"id": 42, "libraryId": 3}},
        )

        lib_type = api.get_library_type_for_series(42)

        assert lib_type == "Manga"
        assert api.get_cached_library_id(42) == 3

    def test_shared_between_instances_pointing_at_the_same_process(self, mocker):
        """Le cache est un attribut de CLASSE (voir kavita_api.py) : une 2e
        instance de KavitaAPI (créée par un autre appel à enrich_series) doit
        pouvoir lire une valeur déjà résolue sans nouvel appel réseau."""
        api = _authenticated_api()
        mock_get = self._mock_get(
            mocker,
            libraries=[{"id": 5, "type": "Comic"}],
            series_by_id={7: {"id": 7, "libraryId": 5}},
        )
        api.get_library_type_for_series(7)
        assert mock_get.call_count == 2  # 1x libraries + 1x series

        other_api = _authenticated_api()
        assert other_api.get_cached_library_id(7) == 5
        assert mock_get.call_count == 2, "aucun appel réseau supplémentaire attendu"


class TestAuthenticateDiagnostics:
    def test_rejects_localhost_without_http_call(self, mocker):
        api = KavitaAPI("http://localhost:5001", "fake-key")
        mock_post = mocker.patch("kavita_api.requests.post")
        assert api.authenticate() is False
        assert api.last_auth_error == "localhost"
        mock_post.assert_not_called()

    def test_missing_key_sets_missing(self):
        api = KavitaAPI("http://kavita.local", "")
        assert api.authenticate() is False
        assert api.last_auth_error == "missing"

    def test_http_401_sets_unauthorized(self, mocker):
        api = KavitaAPI("http://kavita.local", "bad-key")
        resp = mocker.Mock(status_code=401)
        err = requests.exceptions.HTTPError(response=resp)
        mock_post = mocker.patch("kavita_api.requests.post")
        mock_post.return_value.raise_for_status.side_effect = err
        assert api.authenticate() is False
        assert api.last_auth_error == "http_401"
