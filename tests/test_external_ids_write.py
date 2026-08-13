"""
Écriture des IDs externes (`POST /api/Series/update`) : BF122 et BF124.

BF122 — `update_series_external_ids()` tape le même endpoint que
`update_series_general()`, mais omettait `coverImageLocked`. Côté
.NET une clé absente vaut `false` : Kavita voit le verrou de couverture passer de
`true` à `false`, EFFACE `CoverImage` et replanifie une génération depuis les
fichiers. Comme MetaKavita uploade toutes ses couvertures avec `lockCover: True`
et que cet appel part en PREMIER dans `apply_kavita_payload()` — avant l'étape
couverture, elle-même sautée quand la couverture est un choix manuel — la
couverture choisie à la main était détruite sans rien pour la remplacer.

BF124 — le tuple `(success, msg)` de `update_series_external_ids()` n'était jamais
lu : un refus Kavita passait inaperçu et la série était quand même marquée
COMPLETED (statut terminal) avec des champs AniList/MAL vides.

BF140 — `UpdateSeriesDto` porte SEPT identifiants de correspondance externe, et
`SeriesController.UpdateSeries` appelle `SetExternalMetadataIds` sans condition,
qui fait `entity.X = dto.X ?? 0`. Les trois fonctions qui tapent
`POST /api/Series/update` doivent donc porter les sept clés : sans quoi
`update_series_external_ids()` effaçait Hardcover / Metron / ComicVine / CBR,
`update_series_general()` effaçait les sept — annulant, deux appels plus tard dans
la même transaction, ceux qu'on venait d'écrire — et le bouton 🔒 les effaçait
aussi, alors qu'il ne prétend rien modifier.
"""
from services import kavita_payload
from kavita_api import SERIES_EXTERNAL_ID_KEYS, KavitaAPI


def _authenticated_api():
    api = KavitaAPI("http://kavita.local", "fake-api-key")
    api.token = "fake-token"
    api.headers = {"Authorization": "Bearer fake-token", "Content-Type": "application/json"}
    return api


def _current_state(**extra):
    state = {
        "id": 42,
        "name": "One Piece",
        "sortName": "One Piece",
        "localizedName": "Wan Pisu",
        "nameLocked": True,
        "sortNameLocked": True,
        "localizedNameLocked": True,
        "aniListId": None,
        "malId": None,
        "mangaBakaId": None,
    }
    state.update(extra)
    return state


# Une série que Kavita a appariée sur les sept plateformes. MetaKavita n'écrit que
# les trois premières ; les quatre autres viennent de Kavita+ ou de la main de
# l'utilisateur, et rien ici n'a le droit d'y toucher.
MATCHED_EXTERNAL_IDS = {
    "aniListId": 30013,
    "malId": 21,
    "hardcoverId": 4587,
    "metronId": 91234,
    "comicVineId": "4050-12345",
    "mangaBakaId": 77821,
    "cbrId": 616,
}


class TestUpdateSeriesExternalIds:
    def test_ne_deverrouille_jamais_la_couverture(self, mocker):
        """BF122 : le verrou de couverture doit être réinjecté tel quel."""
        api = _authenticated_api()
        current = _current_state(coverImageLocked=True, dontMatch=True)
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        ok, _msg = api.update_series_external_ids(42, anilist_id=1234)

        assert ok is True
        payload = mock_post.call_args_list[0].kwargs["json"]
        assert payload["coverImageLocked"] is True, (
            "coverImageLocked absent/false → Kavita efface la couverture verrouillée"
        )
        assert payload["aniListId"] == 1234

    def test_ne_pretend_plus_recopier_dont_match(self, mocker):
        """`dontMatch` n'est pas sur `UpdateSeriesDto` : contrairement au verrou de
        couverture, l'omettre ne détruit rien — Kavita ne le lit pas ici. Le
        recopier laissait croire à une protection qui n'existait pas, alors que la
        seule façon d'écrire ce drapeau est
        `POST /api/Series/dont-match?seriesId=&dontMatch=`."""
        api = _authenticated_api()
        current = _current_state(coverImageLocked=True, dontMatch=True)
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.update_series_external_ids(42, anilist_id=1234)

        assert "dontMatch" not in mock_post.call_args_list[0].kwargs["json"]

    def test_reflete_un_verrou_de_couverture_absent(self, mocker):
        """Miroir : on reflète l'état réel, on ne verrouille pas d'office."""
        api = _authenticated_api()
        current = _current_state(coverImageLocked=False)
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.update_series_external_ids(42, mal_id=77)

        payload = mock_post.call_args_list[0].kwargs["json"]
        assert payload["coverImageLocked"] is False


class _Response:
    def __init__(self, payload):
        self.status_code = 200
        self.text = "OK"
        self._payload = payload

    def json(self):
        return self._payload


class FakeSeriesEndpoint:
    """Un `POST /api/Series/update` qui se comporte comme celui de Kavita.

    Reproduit la seule règle qui compte ici : le contrôleur appelle
    `ExternalMetadataIdHelper.SetExternalMetadataIds(series, dto)` sans condition,
    et le helper fait `entity.X = dto.X ?? 0`. Une clé absente du corps JSON — ou
    présente à `null` — remet donc l'identifiant à zéro, et Kavita répond quand
    même 200.

    Se contenter de relire le payload envoyé ne prouverait pas la perte : c'est
    l'état de la base après plusieurs appels qui la révèle, en particulier quand
    un appel défait ce qu'un autre venait d'écrire.
    """

    # Ce que `?? 0` laisse dans l'entité quand la clé manque. `ComicVineId` est un
    # `string?` assigné tel quel, sans repli : il retombe à `null`.
    RESET = dict({key: 0 for key in SERIES_EXTERNAL_ID_KEYS}, comicVineId=None)

    def __init__(self, **overrides):
        self.series = _current_state(
            coverImageLocked=True,
            dontMatch=False,
            format=1,
            **dict(MATCHED_EXTERNAL_IDS, **overrides),
        )

    def get(self, url, **_kwargs):
        if "/api/Series/metadata" in url:
            return _Response({"seriesId": self.series["id"], "summaryLocked": False})
        return _Response(dict(self.series))

    def post(self, url, json=None, **_kwargs):
        body = json or {}
        if "/api/Series/update" in url:
            for key in ("name", "sortName", "localizedName"):
                self.series[key] = body.get(key)
            for key in SERIES_EXTERNAL_ID_KEYS:
                value = body.get(key)
                self.series[key] = self.RESET[key] if value is None else value
        return _Response({})

    def external_ids(self):
        return {key: self.series[key] for key in SERIES_EXTERNAL_ID_KEYS}


def _patch(mocker, server):
    mocker.patch("kavita_api.requests.get", side_effect=server.get)
    mocker.patch("kavita_api.requests.post", side_effect=server.post)


class TestSeriesUpdatePreservesEveryExternalId:
    """Les trois fonctions qui tapent `POST /api/Series/update` (BF140).

    Le piège est qu'aucune d'elles ne prétend toucher aux identifiants : l'une
    n'écrit qu'un titre alternatif, l'autre ne pose que des verrous. Kavita ne
    fait pourtant aucune différence entre « je ne t'envoie pas ce champ » et
    « efface ce champ ».
    """

    def test_writing_the_three_ids_it_knows_keeps_the_four_it_does_not(self, mocker):
        """MetaKavita ne sait écrire qu'AniList / MyAnimeList / MangaBaka. Hardcover,
        Metron, ComicVine et CBR viennent de Kavita+ ou de l'utilisateur : ne pas les
        renvoyer, c'est les détruire."""
        server = FakeSeriesEndpoint()
        _patch(mocker, server)

        ok, _msg = _authenticated_api().update_series_external_ids(42, anilist_id=1234)

        assert ok is True
        assert server.external_ids() == dict(MATCHED_EXTERNAL_IDS, aniListId=1234)

    def test_writing_general_fields_keeps_every_external_id(self, mocker):
        """Écrire un titre alternatif ne doit rien coûter d'autre. Les deux
        passages (unlock puis re-lock) partent du même instantané : les sept
        identifiants doivent survivre aux deux."""
        server = FakeSeriesEndpoint()
        _patch(mocker, server)

        ok, _msg, sealed = _authenticated_api().update_series_general(
            42, localized_name="Wan Pisu", format_val=1
        )

        assert (ok, sealed) == (True, True)
        assert server.external_ids() == MATCHED_EXTERNAL_IDS

    def test_sealing_the_locks_keeps_every_external_id(self, mocker):
        """Le bouton 🔒 ne fait que reposer des verrous déjà mérités — il détruisait
        les correspondances Hardcover / Metron / ComicVine / CBR au passage."""
        server = FakeSeriesEndpoint()
        _patch(mocker, server)

        ok, _msg = _authenticated_api().seal_series_locks(42)

        assert ok is True
        assert server.external_ids() == MATCHED_EXTERNAL_IDS

    def test_the_ids_just_written_survive_the_general_write_that_follows(self, mocker):
        """Le scénario complet du bug : `apply_kavita_payload()` écrit les IDs, puis
        les métadonnées, puis les champs généraux. Comme `alt_titles` est dans le
        masque par défaut, le troisième appel arrivait presque toujours — et
        annulait le premier. La fonctionnalité d'écriture des IDs se détruisait
        elle-même dans la même transaction, sans un mot dans le journal."""
        server = FakeSeriesEndpoint(**FakeSeriesEndpoint.RESET)
        _patch(mocker, server)
        api = _authenticated_api()

        api.update_series_external_ids(42, anilist_id=1234, mal_id=77, mangabaka_id=99)
        assert server.external_ids()["aniListId"] == 1234

        api.update_series_general(42, localized_name="Wan Pisu")

        assert server.external_ids() == dict(
            FakeSeriesEndpoint.RESET, aniListId=1234, malId=77, mangaBakaId=99
        ), "les IDs écrits par le premier appel ont été effacés par le troisième"


def _built(series_id):
    return {
        "metadata": {"seriesId": series_id, "summary": "Hi", "summaryLocked": True},
        "localized_name": None,
        "format_val": None,
        "cover_url": None,
        "external_ids": {"anilist": 21, "mal": None, "mangabaka": None},
    }


def _t():
    return {
        "log_sending": "[{0}] send",
        "log_success": "[{0}] ok",
        "log_needs_relock": "[{0}] needs",
        "log_kavita_refused": "[{0}] refuse {1}",
    }


def test_echec_des_ids_externes_ne_marque_pas_la_serie_terminee(mocker, isolated_db):
    """BF124 : un refus Kavita sur les IDs externes interdit le statut COMPLETED."""
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")
    sched = mocker.patch("services.kavita_payload._schedule_seal_retry")

    class FakeKavita:
        def update_series_external_ids(self, *a, **k):
            return False, "Code 400 : Bad Request"

        def update_series_metadata(self, meta):
            return True, "Succès", True

        def update_series_general(self, *a, **k):
            return True, "Succès", True

        def upload_series_cover(self, *a, **k):
            return True, "ok"

    ok, msg, _used = kavita_payload.apply_kavita_payload(
        FakeKavita(),
        58,
        "Series IDs KO",
        _built(58),
        ["summary", "weblinks"],
        {},
        ["ANILIST"],
        _t(),
    )

    assert ok is False, "l'échec d'écriture des IDs externes doit être remonté"
    assert "400" in msg
    assert isolated_db.get_all_cached_data().get(58, {}).get("status") != "COMPLETED", (
        "statut terminal COMPLETED alors que les IDs externes sont absents de Kavita"
    )
    sched.assert_not_called()


def test_succes_des_ids_externes_laisse_la_serie_terminee(mocker, isolated_db):
    """Contrôle : le chemin nominal reste COMPLETED."""
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")

    calls = []

    class FakeKavita:
        def update_series_external_ids(self, series_id, a_id, m_id, mb_id):
            calls.append((series_id, a_id, m_id, mb_id))
            return True, "Succès"

        def update_series_metadata(self, meta):
            return True, "Succès", True

        def update_series_general(self, *a, **k):
            return True, "Succès", True

        def upload_series_cover(self, *a, **k):
            return True, "ok"

    ok, msg, _used = kavita_payload.apply_kavita_payload(
        FakeKavita(),
        59,
        "Series IDs OK",
        _built(59),
        ["summary", "weblinks"],
        {},
        ["ANILIST"],
        _t(),
    )

    assert ok is True
    assert msg == "Succès"
    assert calls == [(59, 21, None, None)]
    assert isolated_db.get_all_cached_data()[59]["status"] == "COMPLETED"
