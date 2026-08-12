"""
Écriture des IDs externes (`POST /api/Series/update`) : BF122 et BF124.

BF122 — `update_series_external_ids()` tape le même endpoint que
`update_series_general()`, mais omettait `coverImageLocked` / `dontMatch`. Côté
.NET une clé absente vaut `false` : Kavita voit le verrou de couverture passer de
`true` à `false`, EFFACE `CoverImage` et replanifie une génération depuis les
fichiers. Comme MetaKavita uploade toutes ses couvertures avec `lockCover: True`
et que cet appel part en PREMIER dans `apply_kavita_payload()` — avant l'étape
couverture, elle-même sautée quand la couverture est un choix manuel — la
couverture choisie à la main était détruite sans rien pour la remplacer.

BF124 — le tuple `(success, msg)` de `update_series_external_ids()` n'était jamais
lu : un refus Kavita passait inaperçu et la série était quand même marquée
COMPLETED (statut terminal) avec des champs AniList/MAL vides.
"""
from services import kavita_payload
from kavita_api import KavitaAPI


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
        assert payload["dontMatch"] is True
        assert payload["aniListId"] == 1234

    def test_reflete_un_verrou_de_couverture_absent(self, mocker):
        """Miroir : on reflète l'état réel, on ne verrouille pas d'office."""
        api = _authenticated_api()
        current = _current_state(coverImageLocked=False)
        mocker.patch("kavita_api.requests.get", return_value=mocker.Mock(status_code=200, json=lambda: current))
        mock_post = mocker.patch("kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK"))

        api.update_series_external_ids(42, mal_id=77)

        payload = mock_post.call_args_list[0].kwargs["json"]
        assert payload["coverImageLocked"] is False
        assert payload["dontMatch"] is False


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
