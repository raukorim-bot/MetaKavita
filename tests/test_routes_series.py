"""
Test bout-en-bout (route Flask réelle -> db_manager -> SQLite temporaire) du
bug historique de `/save-override` : `publisher_pref` était lu depuis le
formulaire mais jamais transmis à la couche de persistance, et disparaissait
donc silencieusement à chaque sauvegarde d'override.
"""


def test_save_override_persists_publisher_pref_original(client, isolated_db):
    response = client.post("/save-override", data={
        "series_id": "42",
        "forced_id": "12345",
        "alternative_title": "One Piece VF",
        "forced_provider": "ANILIST",
        "targeted_fields": "summary,cover",
        "publisher_pref": "ORIGINAL",
    })

    assert response.status_code == 200

    cached = isolated_db.get_all_cached_data()
    assert 42 in cached
    assert cached[42]["publisher_pref"] == "ORIGINAL"
    assert cached[42]["forced_id"] == "12345"
    assert cached[42]["alternative_title"] == "One Piece VF"
    assert cached[42]["forced_provider"] == "ANILIST"
    assert cached[42]["targeted_fields"] == "summary,cover"


def test_save_override_defaults_publisher_pref_to_global_when_omitted(client, isolated_db):
    response = client.post("/save-override", data={"series_id": "7"})

    assert response.status_code == 200
    cached = isolated_db.get_all_cached_data()
    assert cached[7]["publisher_pref"] == "GLOBAL"


def test_save_override_persists_alt_title_langs(client, isolated_db):
    response = client.post("/save-override", data={
        "series_id": "42",
        "publisher_pref": "GLOBAL",
        "alt_title_langs": "en, ja-ro",
    })
    assert response.status_code == 200
    cached = isolated_db.get_all_cached_data()
    assert cached[42]["alt_title_langs"] == "en, ja-ro"


def test_save_override_defaults_alt_title_langs_empty(client, isolated_db):
    response = client.post("/save-override", data={"series_id": "9"})
    assert response.status_code == 200
    assert isolated_db.get_all_cached_data()[9]["alt_title_langs"] == ""


def _kavita_stub(mocker, api):
    """Branche `api` sur le blueprint série, sans config ni réseau réels."""
    mocker.patch(
        "routes.series.load_config",
        return_value={"KAVITA_URL": "http://kavita.local", "KAVITA_API_KEY": "k", "UI_LANG": "fr"},
    )
    mocker.patch("routes.series.KavitaAPI", return_value=api)


class TestLeBoutonDeVerrouillage:
    """Le bouton 🔒 (unitaire et en lot) ne transmet volontairement aucune liste
    de verrous : rien ne mémorise ce qu'une passe a écrit, et `targeted_fields`
    est un masque souhaité, pas une trace d'écriture. Le repli de
    `seal_series_locks` — « scelle ce qui porte du contenu, ne rouvre jamais
    rien » — est donc exactement ce que le bouton promet. Ces tests figent ce
    choix et vérifient qu'il ne réserve pas de surprise depuis que le repli ne
    ferme plus tous les verrous."""

    def test_the_button_relies_on_the_content_fallback(self, client, isolated_db, mocker):
        api = mocker.Mock()
        api.authenticate.return_value = True
        api.seal_series_locks.return_value = (True, "Verrous posés")
        _kavita_stub(mocker, api)

        response = client.post("/api/series/55/seal-locks")

        assert response.status_code == 200
        assert response.get_json()["status"] == "COMPLETED"
        api.seal_series_locks.assert_called_once_with(55)
        assert isolated_db.get_all_cached_data()[55]["status"] == "COMPLETED"

    def test_the_bulk_button_only_walks_the_series_left_to_seal(self, client, isolated_db, mocker):
        isolated_db.update_status(55, "NEEDS_RELOCK")
        isolated_db.update_status(56, "COMPLETED")
        api = mocker.Mock()
        api.authenticate.return_value = True
        api.seal_series_locks.return_value = (True, "Verrous posés")
        _kavita_stub(mocker, api)

        response = client.post("/api/series/seal-locks-pending")

        body = response.get_json()
        assert (body["sealed_count"], body["failed_count"]) == (1, 0)
        api.seal_series_locks.assert_called_once_with(55)

    def test_a_series_with_nothing_to_protect_still_ends_up_completed(
        self, client, isolated_db, mocker
    ):
        """La surprise possible du repli : sur une série aux métadonnées vides,
        aucun verrou ne se ferme. Le bouton répond quand même COMPLETED, et c'est
        le bon contrat — le statut dit que Kavita a accepté les deux POST, pas
        qu'un verrou de plus a été fermé."""
        from kavita_api import KavitaAPI

        api = KavitaAPI("http://kavita.local", "k")
        api.token = "fake-token"
        api.headers = {"Authorization": "Bearer fake-token"}
        mocker.patch.object(api, "authenticate", return_value=True)
        mocker.patch.object(
            api,
            "get_series_metadata",
            return_value={"seriesId": 55, "summary": "", "summaryLocked": False, "genres": [], "genresLocked": False},
        )
        mocker.patch.object(
            api,
            "get_series",
            return_value={"id": 55, "name": "X", "sortName": "X", "localizedName": None},
        )
        post = mocker.patch(
            "kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK")
        )
        _kavita_stub(mocker, api)

        response = client.post("/api/series/55/seal-locks")

        assert response.get_json()["success"] is True
        sealed = post.call_args_list[0].kwargs["json"]["seriesMetadata"]
        assert sealed["summaryLocked"] is False
        assert sealed["genresLocked"] is False
        assert post.call_args_list[1].kwargs["json"]["localizedNameLocked"] is False
        assert isolated_db.get_all_cached_data()[55]["status"] == "COMPLETED"


def test_toggle_ignore_flips_status(client, isolated_db):
    response = client.post("/toggle-ignore", data={"series_id": "5", "current_status": "PENDING"})

    assert response.status_code == 200
    assert response.get_json() == {"success": True, "new_status": "IGNORED"}

    response = client.post("/toggle-ignore", data={"series_id": "5", "current_status": "IGNORED"})
    assert response.get_json()["new_status"] == "PENDING"
