"""BF203 — `POST /api/Series/update` face à Kavita 0.9.1.

Deux nouveautés du contrôleur `SeriesController.UpdateSeries` changent le contrat
que MetaKavita tenait pour acquis depuis la 0.9.0 :

1. `UpdateSeriesDto` porte désormais `metadataProviderOverride`, et l'action se
   termine par `UpdateSeriesMetadataProviderOverride(id, dto.MetadataProviderOverride)`.
   Une clé absente arrive en `null` côté .NET, et `null` veut dire « hérite du
   fournisseur de la bibliothèque » : le fournisseur choisi pour la série était
   donc effacé par une écriture de titre alternatif, et Kavita purgeait au passage
   ses avis / notes / recommandations externes en cache. Même famille de pièges
   que `localizedName` (BF106), `coverImageLocked` (BF122) et les sept
   identifiants externes (BF140) : la valeur se relit et se réinjecte.

2. Kavita refuse maintenant, en 400, un nom ou un titre alternatif qui entrerait
   en collision avec une autre série de la même bibliothèque, et refuse de
   remplacer celui qui ancre encore un dossier fusionné sur disque. Ces verdicts
   sont définitifs : les traiter comme une panne ferait rejouer l'écriture à
   chaque passe et marquerait indéfiniment en échec une série que Kavita se
   contente de protéger.
"""
import pytest

from kavita_api import (
    KavitaAPI,
    KavitaRefusal,
    classify_series_update_refusal,
    refusal_reason,
    series_preserved_state,
)
from services import kavita_payload


def _authenticated_api():
    api = KavitaAPI("http://kavita.local", "fake-api-key")
    api.token = "fake-token"
    api.headers = {"Authorization": "Bearer fake-token", "Content-Type": "application/json"}
    return api


def _current_state(**extra):
    """Un `SeriesDto` tel que Kavita 0.9.1 le rend, fournisseur imposé compris."""
    state = {
        "id": 42,
        "name": "One Piece",
        "sortName": "One Piece",
        "localizedName": "Wan Pisu",
        "nameLocked": True,
        "sortNameLocked": True,
        "localizedNameLocked": True,
        "coverImageLocked": True,
        "aniListId": 30013,
        "malId": 21,
        "hardcoverId": 4587,
        "metronId": 91234,
        "comicVineId": "4050-12345",
        "mangaBakaId": 77821,
        "cbrId": 616,
        # MetadataProvider.Mangabaka — un choix que l'utilisateur a fait dans Kavita
        # et que MetaKavita n'a aucune raison de défaire.
        "metadataProviderOverride": 3,
    }
    state.update(extra)
    return state


class TestFournisseurImpose:
    """Le fournisseur imposé voyage dans tout payload `POST /api/Series/update`."""

    def test_helper_recopie_les_sept_ids_et_le_fournisseur(self):
        preserved = series_preserved_state(_current_state())

        assert preserved["metadataProviderOverride"] == 3
        assert preserved["cbrId"] == 616
        assert preserved["comicVineId"] == "4050-12345"

    def test_helper_supporte_une_serie_sans_fournisseur_impose(self):
        """Absent du DTO lu = hérite déjà : on renvoie `None`, pas un défaut inventé."""
        current = _current_state()
        del current["metadataProviderOverride"]

        assert series_preserved_state(current)["metadataProviderOverride"] is None

    def test_ecriture_du_titre_alternatif_preserve_le_fournisseur(self, mocker):
        api = _authenticated_api()
        mocker.patch(
            "kavita_api.requests.get",
            return_value=mocker.Mock(status_code=200, json=lambda: _current_state()),
        )
        mock_post = mocker.patch(
            "kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK")
        )

        ok, _msg, _sealed = api.update_series_general(42, localized_name="Wanpīsu")

        assert ok is True
        for call in mock_post.call_args_list:
            payload = call.kwargs["json"]
            assert payload["metadataProviderOverride"] == 3, (
                "sans la clé, Kavita 0.9.1 remet la série sur le fournisseur de la "
                "bibliothèque et purge ses métadonnées externes en cache"
            )

    def test_ecriture_des_ids_externes_preserve_le_fournisseur(self, mocker):
        api = _authenticated_api()
        mocker.patch(
            "kavita_api.requests.get",
            return_value=mocker.Mock(status_code=200, json=lambda: _current_state()),
        )
        mock_post = mocker.patch(
            "kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK")
        )

        ok, _msg = api.update_series_external_ids(42, anilist_id=1234)

        assert ok is True
        assert mock_post.call_args_list[0].kwargs["json"]["metadataProviderOverride"] == 3

    def test_scellement_des_verrous_preserve_le_fournisseur(self, mocker):
        """Le bouton 🔒 ne prétend rien modifier : il ne doit rien emporter non plus."""
        api = _authenticated_api()
        mocker.patch.object(
            api, "get_series_metadata", return_value={"seriesId": 42, "summary": "x", "summaryLocked": False}
        )
        mocker.patch.object(api, "get_series", return_value=_current_state())
        mock_post = mocker.patch(
            "kavita_api.requests.post", return_value=mocker.Mock(status_code=200, text="OK")
        )

        ok, _msg = api.seal_series_locks(42, lock_keys=["summaryLocked"])

        assert ok is True
        general_payload = mock_post.call_args_list[-1].kwargs["json"]
        assert general_payload["metadataProviderOverride"] == 3


class TestClassificationDesRefus:
    """Kavita répond en clair, traduit : le texte est le seul signal lisible."""

    @pytest.mark.parametrize(
        "body, expected",
        [
            (
                "Another series in this library already uses this name",
                "localized_name_exists",
            ),
            (
                "Une autre série de cette bibliothèque utilise déjà ce nom",
                "localized_name_exists",
            ),
            (
                "Changing this localized name would split files that are currently merged into this series",
                "localized_name_orphans_files",
            ),
            (
                "Changer ce nom localisé diviserait les fichiers qui sont actuellement fusionnés dans cette série",
                "localized_name_orphans_files",
            ),
            (
                "A series with this name already exists in this library",
                "name_exists",
            ),
            (
                "Changing this name would split files that are currently merged into this series",
                "name_orphans_files",
            ),
        ],
    )
    def test_motifs_reconnus_en_francais_et_en_anglais(self, body, expected):
        assert classify_series_update_refusal(body) == expected

    def test_message_mal_decode_reste_reconnaissable(self):
        """Un `é` arrivé en `Ã©` ne doit pas faire passer un refus pour une panne."""
        mangled = "Une autre sÃ©rie de cette bibliothÃ¨que utilise dÃ©jÃ  ce nom"

        assert classify_series_update_refusal(mangled.replace("Ã©", "é").replace("Ã¨", "è")) == (
            "localized_name_exists"
        )

    def test_panne_ordinaire_n_est_pas_un_refus(self):
        assert classify_series_update_refusal("There was an error with updating the series") is None
        assert classify_series_update_refusal("") is None
        assert classify_series_update_refusal(None) is None

    def test_refusal_reason_ignore_une_chaine_ordinaire(self):
        assert refusal_reason("Code 500 : boom") is None
        assert refusal_reason(KavitaRefusal("…", "name_exists")) == "name_exists"

    def test_un_refus_reste_une_chaine_pour_les_appelants_existants(self):
        """Aucun appelant qui se contente d'afficher le détail n'a à changer."""
        refusal = KavitaRefusal("Titre alternatif refusé par Kavita", "localized_name_exists")

        assert isinstance(refusal, str)
        assert "Erreur : {0}".format(refusal).endswith("refusé par Kavita")


class TestUpdateSeriesGeneral:
    def test_un_400_structurel_rend_un_refus_motive(self, mocker):
        api = _authenticated_api()
        mocker.patch(
            "kavita_api.requests.get",
            return_value=mocker.Mock(status_code=200, json=lambda: _current_state()),
        )
        mocker.patch(
            "kavita_api.requests.post",
            return_value=mocker.Mock(
                status_code=400,
                text="Changing this localized name would split files that are currently merged into this series",
            ),
        )

        ok, detail, sealed = api.update_series_general(42, localized_name="Wanpīsu")

        assert ok is False
        assert sealed is False
        assert refusal_reason(detail) == "localized_name_orphans_files"

    def test_une_panne_reste_une_panne(self, mocker):
        """500, ou 400 non reconnu : le comportement d'avant, sans verdict inventé."""
        api = _authenticated_api()
        mocker.patch(
            "kavita_api.requests.get",
            return_value=mocker.Mock(status_code=200, json=lambda: _current_state()),
        )
        mocker.patch(
            "kavita_api.requests.post",
            return_value=mocker.Mock(status_code=500, text="Internal Server Error"),
        )

        ok, detail, _sealed = api.update_series_general(42, localized_name="Wanpīsu")

        assert ok is False
        assert refusal_reason(detail) is None
        assert "500" in detail


def _t():
    return {
        "log_sending": "[{0}] send",
        "log_success": "[{0}] ok",
        "log_needs_relock": "[{0}] needs",
        "log_kavita_refused": "[{0}] refuse {1}",
        "log_kavita_refusal_series": "[{0}] refus {1}",
    }


class TestPasseDEnrichissement:
    """Un refus n'est pas un échec de passe : les métadonnées, elles, sont écrites."""

    def _run(self, mocker, isolated_db, general_result):
        mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
        mocker.patch("services.kavita_payload._emit_series_status")
        seal_retry = mocker.patch("services.kavita_payload._schedule_seal_retry")

        class FakeKavita:
            def update_series_external_ids(self, *a, **k):
                return True, "ok"

            def update_series_metadata(self, meta):
                return True, "Succès", True

            def update_series_general(self, series_id, localized_name=None, format_val=None):
                return general_result

            def upload_series_cover(self, *a, **k):
                return True, "ok"

        built = {
            "metadata": {"seriesId": 77, "summary": "Hi", "summaryLocked": True},
            "localized_name": "Titre déjà pris",
            "cover_url": None,
            "external_ids": {},
        }
        result = kavita_payload.apply_kavita_payload(
            FakeKavita(), 77, "Série 77", built, ["summary"], {}, ["ANILIST"], _t()
        )
        return result, seal_retry

    def test_refus_la_serie_reste_completed(self, mocker, isolated_db):
        refusal = KavitaRefusal("Titre alternatif refusé", "localized_name_exists")

        (ok, msg, _used), seal_retry = self._run(mocker, isolated_db, (False, refusal, False))

        assert ok is True, "un refus définitif de Kavita ne doit pas faire échouer la passe"
        assert isolated_db.get_all_cached_data()[77]["status"] == "COMPLETED"
        assert msg != "NEEDS_RELOCK"
        seal_retry.assert_not_called()

    def test_refus_ne_revendique_pas_le_verrou_du_titre_alternatif(self, mocker, isolated_db):
        """Rien n'a été écrit : il n'y a aucun `localizedNameLocked` à resceller."""
        refusal = KavitaRefusal("Titre alternatif refusé", "localized_name_orphans_files")
        mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
        mocker.patch("services.kavita_payload._emit_series_status")
        seal_retry = mocker.patch("services.kavita_payload._schedule_seal_retry")

        class FakeKavita:
            def update_series_external_ids(self, *a, **k):
                return True, "ok"

            def update_series_metadata(self, meta):
                # Métadonnées écrites, mais verrous non posés : la passe planifie
                # un rescellement, et c'est là qu'un verrou fantôme se verrait.
                return True, "Succès", False

            def update_series_general(self, *a, **k):
                return False, refusal, False

            def upload_series_cover(self, *a, **k):
                return True, "ok"

        built = {
            "metadata": {"seriesId": 78, "summary": "Hi", "summaryLocked": True},
            "localized_name": "Titre refusé",
            "cover_url": None,
            "external_ids": {},
        }
        ok, msg, _used = kavita_payload.apply_kavita_payload(
            FakeKavita(), 78, "Série 78", built, ["summary"], {}, ["ANILIST"], _t()
        )

        assert ok is True
        assert msg == "NEEDS_RELOCK"
        lock_keys = seal_retry.call_args.kwargs["lock_keys"]
        assert "localizedNameLocked" not in lock_keys
        assert "summaryLocked" in lock_keys

    def test_une_vraie_panne_fait_toujours_echouer_la_passe(self, mocker, isolated_db):
        (ok, _msg, _used), _seal = self._run(
            mocker, isolated_db, (False, "Code 500 : Internal Server Error", False)
        )

        assert ok is False
        assert isolated_db.get_all_cached_data().get(77, {}).get("status") != "COMPLETED"
