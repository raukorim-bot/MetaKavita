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

4. Le jeton n'était demandé qu'une fois. Kavita le signe pour trois jours
   (`TokenService`) et une clé d'API peut être révoquée, alors qu'une instance de
   `KavitaAPI` vit le temps d'une passe de bibliothèque : à partir du premier 401,
   toutes les lectures rendaient `None` et toutes les écritures échouaient — les
   séries traversées étant malgré tout marquées traitées, donc écartées des passes
   suivantes.

5. Ce que Kavita fait des clés qu'on lui envoie n'est pas toujours ce qu'on croit.
   `UpdateSeriesDto` n'a ni `Format`/`FormatLocked` ni `dontMatch`, et
   `SeriesFilterV2Dto` n'a pas de `libraryId` : System.Text.Json ignore ces clés,
   Kavita répond 200, et rien de ce qu'on croyait écrire ou filtrer n'a eu lieu.
"""
import requests

from kavita_api import (
    COVER_FETCH_TIMEOUT_SECONDS,
    MAX_COVER_BYTES,
    KavitaAPI,
    _RELOCK_RETRY_TIMEOUT_CAP_S,
    lock_keys_from_payload,
)


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

        success, _, sealed = api.update_series_general(42, localized_name="Wan Pīsu")

        assert success is True
        assert sealed is True
        mock_get.assert_called_once()
        assert mock_post.call_count == 2  # protocole Unlock -> Write -> Lock

    def test_a_call_that_only_carries_a_reading_direction_writes_nothing(self, mocker):
        """Le piège d'origine : `update_series_general(id, format_val=3)` était le
        chemin par lequel MetaKavita croyait écrire un sens de lecture, et c'est ce
        payload partiel qui nullait `localizedName` (crash KOReader « Kamare »).

        `UpdateSeriesDto` ne porte ni `Format` ni `FormatLocked` : System.Text.Json
        ignorait les deux clés, Kavita répondait 200 et rien n'était écrit. Le
        paramètre reste accepté pour ne pas casser les appelants, mais un appel qui
        ne porte que lui ne doit plus toucher au réseau — ni GET, ni POST. C'est la
        seule forme de protection qui vaille : un appel qui n'a pas lieu ne peut
        rien détruire."""
        api = _authenticated_api()
        mock_get = mocker.patch("kavita_api.requests.get")
        mock_post = mocker.patch("kavita_api.requests.post")

        success, _, sealed = api.update_series_general(42, localized_name=None, format_val=3)

        assert success is True
        assert sealed is True
        mock_get.assert_not_called()
        mock_post.assert_not_called()

    def test_no_payload_ever_carries_format_or_format_locked(self, mocker):
        """`{"format": 1|2|3|4, "formatLocked": true}` n'a jamais rien écrit, et
        `formatLocked` était en plus relu depuis `SeriesDto.Format`, qui est un
        `MangaFormat` (type de fichier) sans rapport avec un sens de lecture. Les
        deux clés ne doivent plus partir : les laisser laisserait croire, au
        prochain lecteur du journal de payloads, que le champ est écrit."""
        api = _authenticated_api()
        current_state = {
            "id": 42,
            "name": "One Piece",
            "sortName": "One Piece",
            "localizedName": "Wan Pisu",
            "format": 1,
            "formatLocked": True,
        }
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current_state))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.update_series_general(42, localized_name="Wan Pīsu", format_val=4)

        assert mock_post.call_count == 2
        for call in mock_post.call_args_list:
            payload = call.kwargs["json"]
            assert "format" not in payload
            assert "formatLocked" not in payload

    def test_never_sends_null_localized_name_when_not_explicitly_changed(self, mocker):
        """C'est exactement le bug qui a cassé KOReader : une écriture qui ne
        prétend pas toucher au titre alternatif ne doit JAMAIS le nuller. Ici, le
        nom alternatif est réécrit à l'identique — le cas d'un scraper qui reproduit
        la valeur déjà en base."""
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

        success, _, sealed = api.update_series_general(42, localized_name="Wan Pisu")

        assert success is True
        assert sealed is True
        assert mock_post.call_count == 2
        for call in mock_post.call_args_list:
            payload = call.kwargs["json"]
            assert payload["localizedName"] == "Wan Pisu"
            assert payload["localizedName"] is not None
        assert mock_post.call_args_list[1].kwargs["json"]["localizedNameLocked"] is True

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

        api.update_series_general(42, localized_name="Wan Pisu")

        assert mock_post.call_count == 2
        for call in mock_post.call_args_list:
            payload = call.kwargs["json"]
            assert payload["nameLocked"] is True
            assert payload["sortNameLocked"] is True

    def test_never_unlocks_cover_image(self, mocker):
        """BF106 : un `coverImageLocked` absent (donc false côté .NET) fait vider
        `CoverImage` à Kavita et régénérer la couverture depuis les fichiers, ce qui
        détruisait la couverture choisie manuellement au sync suivant.

        `dontMatch`, lui, ne fait plus partie du payload : la propriété n'est pas
        sur `UpdateSeriesDto` — Kavita ne l'expose que par
        `POST /api/Series/dont-match` — donc la recopier ne protégeait de rien."""
        api = _authenticated_api()
        current_state = {
            "id": 42,
            "name": "One Piece",
            "sortName": "One Piece",
            "localizedName": "Wan Pisu",
            "nameLocked": True,
            "sortNameLocked": True,
            "localizedNameLocked": True,
            "coverImageLocked": True,
            "dontMatch": True,
        }
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current_state))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.update_series_general(42, localized_name="Wan Pīsu")

        assert mock_post.call_count == 2
        for call in mock_post.call_args_list:
            payload = call.kwargs["json"]
            assert payload["coverImageLocked"] is True
            assert "dontMatch" not in payload

    def test_cover_lock_false_stays_false(self, mocker):
        """Miroir de BF106 : on reflète l'état réel, on ne verrouille pas d'office."""
        api = _authenticated_api()
        current_state = {
            "id": 42,
            "name": "One Piece",
            "sortName": "One Piece",
            "localizedName": None,
            "nameLocked": False,
            "sortNameLocked": False,
            "localizedNameLocked": False,
            "coverImageLocked": False,
        }
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current_state))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.update_series_general(42, localized_name="Wan Pisu")

        assert mock_post.call_count == 2
        for call in mock_post.call_args_list:
            assert call.kwargs["json"]["coverImageLocked"] is False

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
        assert ("écriture OK" in msg) or ("write OK" in msg)
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
        assert msg in ("Succès", "Success")
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
        assert ("re-lock échoué" in msg) or ("re-lock failed" in msg)
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

        success, msg, sealed = api.update_series_general(42, localized_name="Wan Pīsu")

        assert success is True
        assert sealed is False
        assert ("écriture OK" in msg) or ("write OK" in msg)
        assert mock_post.call_count == 3


class TestSealSeriesLocks:
    """`SeriesService` assigne les booléens `...Locked` depuis le DTO SANS
    CONDITION : un verrou envoyé à `True` est fermé, point. Sceller « tout »
    figeait donc des champs vides que l'utilisateur avait laissés ouverts exprès
    pour que le scan de fichiers ou Kavita+ les remplisse — et rien ne le
    signalait, puisque Kavita répond 200."""

    def _series(self, **overrides):
        series = {
            "id": 7,
            "name": "X",
            "sortName": "X",
            "localizedName": "Y",
            "nameLocked": False,
            "sortNameLocked": False,
            "localizedNameLocked": False,
            "format": 1,
            "coverImageLocked": True,
        }
        series.update(overrides)
        return series

    def test_seal_only_closes_locks_whose_field_carries_something(self, mocker):
        """Sans liste de verrous, le repli ne scelle que ce qui a du contenu :
        `summary` est renseigné donc son verrou se ferme, `genres` est vide donc
        le sien reste ouvert. Fermer un verrou sur un champ vide ne protège
        aucune donnée — il interdit seulement de le remplir plus tard."""
        api = _authenticated_api()
        meta = {
            "seriesId": 7,
            "summary": "Hello",
            "summaryLocked": False,
            "genres": [],
            "genresLocked": False,
            "totalCount": 1,
        }
        mocker.patch.object(api, "get_series_metadata", return_value=dict(meta))
        mocker.patch.object(api, "get_series", return_value=self._series())
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        ok, _msg = api.seal_series_locks(7)

        assert ok is True
        assert mock_post.call_count == 2
        meta_payload = mock_post.call_args_list[0].kwargs["json"]["seriesMetadata"]
        assert meta_payload["summaryLocked"] is True
        assert meta_payload["genresLocked"] is False, (
            "un verrou fermé sur des genres vides empêche le scan de les remplir"
        )
        assert "totalCount" not in meta_payload
        gen_payload = mock_post.call_args_list[1].kwargs["json"]
        assert gen_payload["localizedNameLocked"] is True
        # BF106 : sceller les verrous ne doit pas faire régénérer la couverture.
        assert gen_payload["coverImageLocked"] is True

    def test_seal_never_writes_format_or_format_locked(self, mocker):
        """L'ancien scellement relisait `SeriesDto.format` — un `MangaFormat`
        déduit du type de fichier — et le renvoyait comme sens de lecture avec
        `formatLocked: true`. Aucune des deux clés n'existe sur
        `UpdateSeriesDto` : elles n'ont plus à figurer dans le payload."""
        api = _authenticated_api()
        mocker.patch.object(api, "get_series_metadata", return_value={"seriesId": 7})
        mocker.patch.object(api, "get_series", return_value=self._series())
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.seal_series_locks(7)

        gen_payload = mock_post.call_args_list[1].kwargs["json"]
        assert "format" not in gen_payload
        assert "formatLocked" not in gen_payload

    def test_seal_restricted_to_the_locks_the_pass_actually_wrote(self, mocker):
        """Le cas qui a motivé le correctif : l'utilisateur a délibérément laissé
        `tagsLocked` ouvert pour que Kavita continue d'y verser les tags des
        fichiers, la passe MetaKavita n'a écrit que le résumé, et le rescellement
        — automatique ou par le bouton 🔒 — refermait quand même le verrou des
        tags. Avec la liste des verrous réellement posés, seul le résumé est
        scellé."""
        api = _authenticated_api()
        meta = {
            "seriesId": 7,
            "summary": "Hello",
            "summaryLocked": False,
            "tags": [{"id": 1, "title": "Shonen"}],
            "tagsLocked": False,
        }
        mocker.patch.object(api, "get_series_metadata", return_value=dict(meta))
        mocker.patch.object(api, "get_series", return_value=self._series())
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        ok, _msg = api.seal_series_locks(7, lock_keys=["summaryLocked"])

        assert ok is True
        meta_payload = mock_post.call_args_list[0].kwargs["json"]["seriesMetadata"]
        assert meta_payload["summaryLocked"] is True
        assert meta_payload["tagsLocked"] is False, (
            "verrou refermé alors que la passe n'a pas écrit les tags"
        )

    def test_seal_never_reopens_a_lock_the_user_had_closed(self, mocker):
        """L'inverse est tout aussi destructeur : un verrou déjà fermé qu'on
        renverrait à `False` rouvrirait le champ au prochain scan de fichiers.
        Le scellement ne ferme jamais moins que ce qu'il a lu."""
        api = _authenticated_api()
        meta = {
            "seriesId": 7,
            "summary": "",
            "summaryLocked": False,
            "genres": [],
            "genresLocked": True,
            "tags": [],
            "tagsLocked": True,
        }
        mocker.patch.object(api, "get_series_metadata", return_value=dict(meta))
        mocker.patch.object(api, "get_series", return_value=self._series(localizedNameLocked=True))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.seal_series_locks(7, lock_keys=["summaryLocked"])

        meta_payload = mock_post.call_args_list[0].kwargs["json"]["seriesMetadata"]
        assert meta_payload["genresLocked"] is True
        assert meta_payload["tagsLocked"] is True
        assert mock_post.call_args_list[1].kwargs["json"]["localizedNameLocked"] is True

    def test_seal_leaves_an_empty_localized_name_unlocked(self, mocker):
        """Verrouiller un titre alternatif absent interdit à Kavita de le
        renseigner plus tard sans rien protéger en échange."""
        api = _authenticated_api()
        mocker.patch.object(api, "get_series_metadata", return_value={"seriesId": 7})
        mocker.patch.object(api, "get_series", return_value=self._series(localizedName=None))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.seal_series_locks(7)

        assert mock_post.call_args_list[1].kwargs["json"]["localizedNameLocked"] is False


class TestReauthenticatesOnUnauthorized:
    """Le piège : `if not self.token and not self.authenticate()` ne demande un
    jeton qu'une fois. Kavita le signe pour trois jours (`TokenService`) et une clé
    d'API peut être révoquée, alors qu'une instance de `KavitaAPI` vit le temps
    d'une passe de bibliothèque — potentiellement des jours. Un 401 en cours de
    passe était donc définitif : lectures à `None`, écritures en échec, et séries
    malgré tout marquées traitées, donc écartées des passes suivantes."""

    def test_a_read_replays_itself_after_getting_a_fresh_token(self, mocker):
        api = _authenticated_api()
        series = {"id": 42, "name": "One Piece"}
        mock_get = mocker.patch(
            "kavita_api.requests.get",
            side_effect=[
                mocker.Mock(status_code=401, text="Unauthorized"),
                mocker.Mock(status_code=200, json=lambda: series),
            ],
        )

        def _reauth():
            api.token = "renewed-token"
            api.headers = {"Authorization": "Bearer renewed-token"}
            return True

        auth = mocker.patch.object(api, "authenticate", side_effect=_reauth)

        assert api.get_series(42) == series
        auth.assert_called_once()
        assert mock_get.call_count == 2
        assert mock_get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer renewed-token"

    def test_a_write_replays_itself_after_getting_a_fresh_token(self, mocker):
        """Une écriture perdue sur 401 est plus grave qu'une lecture : la série
        est comptée comme traitée et ne repassera pas."""
        api = _authenticated_api()
        mock_post = mocker.patch(
            "kavita_api.requests.post",
            side_effect=[
                mocker.Mock(status_code=401, text="Unauthorized"),
                mocker.Mock(status_code=200, text="OK"),  # écriture rejouée
                mocker.Mock(status_code=200, text="OK"),  # re-lock
            ],
        )
        mocker.patch.object(api, "authenticate", return_value=True)

        success, _msg, sealed = api.update_series_metadata({"seriesId": 1, "summaryLocked": True})

        assert (success, sealed) == (True, True)
        assert mock_post.call_count == 3

    def test_a_second_unauthorized_is_reported_instead_of_looping(self, mocker):
        """Une clé révoquée rend 401 quoi qu'on fasse : une seule reprise, puis on
        remonte l'échec plutôt que de marteler l'endpoint d'authentification."""
        api = _authenticated_api()
        mock_get = mocker.patch(
            "kavita_api.requests.get",
            return_value=mocker.Mock(status_code=401, text="Unauthorized"),
        )
        auth = mocker.patch.object(api, "authenticate", return_value=True)

        assert api.get_series(42) is None
        assert auth.call_count == 1
        assert mock_get.call_count == 2

    def test_an_impossible_reauthentication_stops_before_the_replay(self, mocker):
        api = _authenticated_api()
        mock_get = mocker.patch(
            "kavita_api.requests.get",
            return_value=mocker.Mock(status_code=401, text="Unauthorized"),
        )
        mocker.patch.object(api, "authenticate", return_value=False)

        data, err = api.fetch_series(42)

        assert (data, err) == (None, "kavita_unreachable")
        assert mock_get.call_count == 1


class TestLockKeysFromPayload:
    """Le seul endroit qui sait ce qu'une passe a écrit est le payload qu'elle a
    construit : `lock_keys_from_payload` en extrait les verrous fermés, pour que
    le rescellement s'y limite au lieu de tout refermer."""

    def test_only_the_locks_set_to_true_are_collected(self):
        metadata = {
            "seriesId": 1,
            "summary": "Hello",
            "summaryLocked": True,
            "genresLocked": False,
            "tagsLocked": None,
        }

        assert lock_keys_from_payload(metadata) == ["summaryLocked"]

    def test_the_two_payloads_of_a_pass_are_merged_without_duplicates(self):
        """Les métadonnées et les champs généraux partent par deux endpoints
        différents ; le scellement, lui, est un seul geste."""
        metadata = {"summaryLocked": True, "ageRatingLocked": True}
        general = {"localizedNameLocked": True, "summaryLocked": True}

        assert lock_keys_from_payload(metadata, general) == [
            "summaryLocked",
            "ageRatingLocked",
            "localizedNameLocked",
        ]

    def test_nothing_written_means_nothing_to_seal(self):
        assert lock_keys_from_payload(None, {}) == []


class TestMetadataSanitisationLeavesTheCallerAlone:
    def test_the_caller_dict_keeps_its_system_keys(self, mocker):
        """L'assainissement retire les propriétés calculées du payload, pas du
        dictionnaire de l'appelant : celui-ci le relit après coup (journalisation,
        statistiques) et n'a pas demandé à perdre des clés."""
        api = _authenticated_api()
        mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))
        metadata = {"seriesId": 1, "summary": "Hello", "totalCount": 99, "pages": 12}

        api.update_series_metadata(metadata)

        assert metadata["totalCount"] == 99
        assert metadata["pages"] == 12


class TestSeriesVolumes:
    """`get_series_volumes` rendait `[]` aussi bien pour une série sans tome que
    pour un Kavita muet. Confondre les deux fait marquer une série comme traitée
    pendant une indisponibilité, ce qui l'écarte définitivement des passes
    suivantes — d'où `fetch_series_volumes`, sur le modèle de `fetch_series`."""

    def test_an_empty_series_is_not_an_error(self, mocker):
        api = _authenticated_api()
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: []))

        assert api.fetch_series_volumes(7) == ([], None)

    def test_a_mute_kavita_is_not_an_empty_series(self, mocker):
        api = _authenticated_api()
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=500, text="boom"))

        volumes, err = api.fetch_series_volumes(7)

        assert volumes is None
        assert err == "kavita_unreachable"

    def test_a_deleted_series_says_so(self, mocker):
        api = _authenticated_api()
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=404, text=""))

        assert api.fetch_series_volumes(7) == (None, "series_not_found")

    def test_a_refused_authentication_says_so(self, mocker):
        api = KavitaAPI("http://kavita.local", "fake-api-key")
        mocker.patch.object(api, "authenticate", return_value=False)

        assert api.fetch_series_volumes(7) == (None, "kavita_auth")

    def test_the_legacy_list_helper_still_flattens_everything_to_a_list(self, mocker):
        """Les appelants qui ne font pas la différence continuent de recevoir une
        liste : le correctif ne doit pas les obliger à changer d'un coup."""
        api = _authenticated_api()
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=500, text="boom"))

        assert api.get_series_volumes(7) == []


class TestSeriesIsbn:
    def test_the_isbn_is_read_on_the_chapter_not_on_the_volume(self, mocker):
        """`VolumeDto` ne porte pas d'`Isbn` — seul `ChapterDto` en a un, renseigné
        depuis le ComicInfo des fichiers. L'ancienne lecture interrogeait le tome
        d'abord et ne marchait que grâce au repli sur le chapitre."""
        api = _authenticated_api()
        volumes = [{"id": 1, "chapters": [{"id": 10, "isbn": "978-2-505-06407-7"}]}]
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: volumes))

        assert api.get_series_isbn(7) == "9782505064077"

    def test_a_series_without_any_isbn_returns_none(self, mocker):
        api = _authenticated_api()
        volumes = [{"id": 1, "chapters": [{"id": 10}]}]
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: volumes))

        assert api.get_series_isbn(7) is None


class _StreamedImage:
    """Réponse HTTP telle que `curl_cffi` la rend hors mode flux : corps déjà lu."""

    def __init__(self, body=b"", content_type="image/jpeg", declared_length=None, status_code=200):
        self.status_code = status_code
        self._body = body
        self.headers = {}
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        if declared_length is not None:
            self.headers["Content-Length"] = str(declared_length)
        self.closed = False
        self.read_bytes = 0

    @property
    def content(self):
        self.read_bytes = len(self._body)
        return self._body

    def close(self):
        self.closed = True


class TestCoverFetchUnderEventlet:
    """Le téléchargement d'une couverture doit être bornable sous eventlet.

    Constaté sur une passe par tome : la première unité n'avait plus que sa
    couverture à écrire, et l'écriture est restée à « 0 / 11 » treize minutes,
    sans une ligne de journal — l'application, elle, répondait toujours, ce qui
    écartait un worker bloqué et désignait une attente que personne ne
    réveillerait.

    Le mode flux de `curl_cffi` est cette attente : il soumet `perform()` à un
    `ThreadPoolExecutor` et livre les morceaux par une file, sans honorer le
    `thread="eventlet"` que son chemin non-flux respecte. Mesuré par
    `debug/repro_cover_eventlet.py` : `timeout=5` sur un hôte muet attendait
    toujours à 8 s en mode flux, contre « Operation timed out after 5007 ms »
    sans lui.
    """

    def _patch(self, mocker, response=None, raises=None):
        mocker.patch(
            "scrapers.ScraperRegistry.get_all_proxy_domains", return_value=["cdn.test"]
        )
        mocker.patch("scrapers.ScraperRegistry.get_all", return_value=[])
        session = mocker.Mock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        mocker.patch("kavita_api.cffi_requests.Session", return_value=session)
        return session

    def test_the_body_is_never_asked_for_in_stream_mode(self, mocker):
        """La régression à empêcher, nommée à l'endroit où elle se réintroduirait.

        Remettre `stream=True` ramène une attente qu'aucun délai ne borne — et
        aucune erreur ne le signalerait : la passe se contenterait de ne plus
        avancer.
        """
        api = _authenticated_api()
        session = self._patch(mocker, _StreamedImage(b"\x89PNG" + b"0" * 512, content_type="image/png"))

        api._download_cover_base64("https://cdn.test/cover.jpg")

        assert session.get.call_args is not None, "aucune requête n'a été faite"
        assert not session.get.call_args.kwargs.get("stream"), (
            "le mode flux est revenu : sous eventlet, l'attente d'un morceau n'y "
            "est bornée par rien"
        )
        assert session.get.call_args.kwargs.get("timeout") == COVER_FETCH_TIMEOUT_SECONDS

    def test_a_host_that_times_out_is_named_rather_than_raised(self, mocker):
        """Une couverture est un extra : son échec ne doit pas condamner l'unité.

        L'exception de curl remontait jusqu'à `apply_plan`, qui marquait l'unité
        entière `FAILED` — alors que son texte, écrit juste avant, était bien
        passé.
        """
        api = _authenticated_api()
        self._patch(mocker, raises=RuntimeError("curl: (28) Operation timed out"))

        data, err = api._download_cover_base64("https://cdn.test/cover.jpg")

        assert data is None
        assert str(COVER_FETCH_TIMEOUT_SECONDS) in err

    def test_an_image_that_arrives_is_encoded_untouched(self, mocker):
        import base64

        api = _authenticated_api()
        body = b"\x89PNG\r\n\x1a\n" + b"0" * 2048
        response = _StreamedImage(body, content_type="image/png")
        self._patch(mocker, response)

        data, err = api._download_cover_base64("https://cdn.test/cover.jpg")

        assert data is not None, err
        assert base64.b64decode(data) == body
        assert response.closed, "la réponse doit être fermée, sans quoi la connexion fuit"


class TestCoverSessionAccommodatesEventlet:
    """`thread="eventlet"` fait passer libcurl par un vrai thread système.

    Sans lui, `perform()` s'exécute dans un greenthread : du C que le hub ne peut
    pas interrompre, donc plus une page servie ni un événement diffusé pendant le
    transfert. Le réglage n'a de sens que sous eventlet, et le demander ailleurs
    ferait payer un pool de threads aux tests et aux scripts.
    """

    def test_the_accommodation_is_asked_for_under_eventlet(self, mocker):
        from kavita_api import _cover_http_session

        mocker.patch("eventlet.patcher.is_monkey_patched", return_value=True)
        made = mocker.patch("kavita_api.cffi_requests.Session")

        _cover_http_session()

        assert made.call_args.kwargs.get("thread") == "eventlet"

    def test_a_plain_session_is_used_outside_eventlet(self, mocker):
        from kavita_api import _cover_http_session

        mocker.patch("eventlet.patcher.is_monkey_patched", return_value=False)
        made = mocker.patch("kavita_api.cffi_requests.Session")

        _cover_http_session()

        assert "thread" not in made.call_args.kwargs


class TestCoverDownloadGuards:
    """`POST /api/Upload/{series,chapter}` portent tous deux
    `[RequestSizeLimit(MaxUploadSizeBytes)]`, soit 30 Mio, et le base64 gonfle le
    corps de 4/3 : au-delà du plafond, Kavita refuse la requête entière. Et un
    hôte autorisé qui rend une page d'erreur HTML en 200 voyait sa page encodée et
    envoyée comme couverture. Le proxy d'images (`routes/misc.py`) applique déjà
    les deux règles ; elles manquaient ici."""

    def _patch_fetch(self, mocker, response):
        mocker.patch(
            "scrapers.ScraperRegistry.get_all_proxy_domains", return_value=["cdn.test"]
        )
        mocker.patch("scrapers.ScraperRegistry.get_all", return_value=[])
        session = mocker.Mock()
        session.get.return_value = response
        mocker.patch("kavita_api.cffi_requests.Session", return_value=session)
        return session

    def test_an_html_error_page_served_as_200_is_not_uploaded_as_a_cover(self, mocker):
        api = _authenticated_api()
        page = _StreamedImage(b"<html><body>404</body></html>", content_type="text/html")
        self._patch_fetch(mocker, page)

        data, err = api._download_cover_base64("https://cdn.test/cover.jpg")

        assert data is None
        assert "text/html" in err

    def test_an_image_over_the_cap_is_refused_even_without_content_length(self, mocker):
        """Le plafond doit tenir sans `Content-Length` : un hôte peut l'omettre,
        mentir, ou répondre en chunked où elle n'existe pas.

        Il s'applique désormais **après** la lecture, et non morceau par morceau :
        abandonner le mode flux était le prix à payer pour que le délai de curl
        borne enfin le transfert (`TestCoverFetchUnderEventlet`). Un corps trop
        gros est donc reçu avant d'être refusé — borné en pratique par
        `COVER_FETCH_TIMEOUT_SECONDS` et, pour les hôtes honnêtes, par le
        `Content-Length` qui fait renoncer sans rien lire. Une attente sans fin
        étant le défaut observé, et un CDN hostile une hypothèse, le compromis se
        tranche dans ce sens.
        """
        api = _authenticated_api()
        oversized = _StreamedImage(b"\xff" * (MAX_COVER_BYTES + 256 * 1024))
        self._patch_fetch(mocker, oversized)

        data, err = api._download_cover_base64("https://cdn.test/cover.jpg")

        assert data is None
        assert str(MAX_COVER_BYTES) in err

    def test_a_declared_length_over_the_cap_is_refused_without_reading(self, mocker):
        """Le cas honnête, lui, ne coûte pas un octet : l'en-tête suffit."""
        api = _authenticated_api()
        huge = _StreamedImage(b"\xff" * 32, declared_length=MAX_COVER_BYTES + 1)
        self._patch_fetch(mocker, huge)

        data, err = api._download_cover_base64("https://cdn.test/cover.jpg")

        assert data is None
        assert str(MAX_COVER_BYTES) in err
        assert huge.read_bytes == 0, "le corps a été lu alors que l'en-tête suffisait"

    def test_a_declared_length_over_the_cap_is_refused_without_reading_anything(self, mocker):
        api = _authenticated_api()
        oversized = _StreamedImage(b"\xff" * 10, declared_length=MAX_COVER_BYTES + 1)
        self._patch_fetch(mocker, oversized)

        data, _err = api._download_cover_base64("https://cdn.test/cover.jpg")

        assert data is None
        assert oversized.read_bytes == 0

    def test_a_normal_image_still_goes_through(self, mocker):
        import base64

        api = _authenticated_api()
        body = b"\x89PNG\r\n\x1a\n" + b"0" * 1024
        response = _StreamedImage(body, content_type="image/png", declared_length=len(body))
        self._patch_fetch(mocker, response)

        data, err = api._download_cover_base64("https://cdn.test/cover.png")

        assert err == ""
        assert base64.b64decode(data) == body

    def test_a_missing_content_type_is_tolerated(self, mocker):
        """Certains CDN n'en envoient pas, et Kavita valide le contenu de son
        côté : refuser ici priverait de couverture sans raison."""
        api = _authenticated_api()
        response = _StreamedImage(b"\xff\xd8\xff\xe0 jpeg", content_type=None)
        self._patch_fetch(mocker, response)

        data, err = api._download_cover_base64("https://cdn.test/cover.jpg")

        assert err == ""
        assert data


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
