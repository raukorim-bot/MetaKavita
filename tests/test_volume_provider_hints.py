"""Le chemin par tome ne doit pas redeviner une série déjà appariée.

La série a été appariée une fois, par l'enrichissement par série, et Kavita en
garde la trace dans les sept identifiants de correspondance externe de son
`SeriesDto`. Le plan par tome ne les transmettait pas : il ne passait que l'année,
si bien que `_resolve_volume_id` de ComicVine repartait d'une **recherche par
titre** à chaque passe.

Ce n'est pas théorique. Sur « Gaston Lagaffe », l'Inventaire obtient bien 23 tomes
attendus via ComicVine — le fournisseur connaît donc la série — et l'aperçu par
tome affiche pourtant « aucun fournisseur ne connaît cette série ». Une recherche
par titre qui tombe sur une autre édition rend un index parfaitement valide dont
aucun numéro d'album ne recoupe ceux de Kavita.

Les clés sont nommées par fournisseur, jamais génériques : `forced_id_for`
documente déjà pourquoi un `provider_id` passe-partout est dangereux — un
identifiant AniList lu comme un numéro de run ComicVine rend l'index complet
d'une œuvre sans rapport, que l'appariement écrirait tome par tome, verrous
compris.
"""
from __future__ import annotations

from services.volume_enrichment.job import provider_hints


class TestCeQueLaSerieSaitDElleMeme:
    def test_l_identifiant_comicvine_est_transmis(self):
        hints = provider_hints({"comicVineId": 12345, "year": 1957})

        assert hints["comicvine_id"] == "12345"
        assert hints["year"] == 1957

    def test_les_sept_identifiants_sont_couverts(self):
        hints = provider_hints(
            {
                "aniListId": 1,
                "malId": 2,
                "hardcoverId": 3,
                "metronId": 4,
                "comicVineId": 5,
                "mangaBakaId": 6,
                "cbrId": 7,
            }
        )

        assert hints["anilist_id"] == "1"
        assert hints["mal_id"] == "2"
        assert hints["hardcover_id"] == "3"
        assert hints["metron_id"] == "4"
        assert hints["comicvine_id"] == "5"
        assert hints["mangabaka_id"] == "6"
        assert hints["cbr_id"] == "7"

    def test_zero_est_une_absence_pas_un_numero(self):
        """Kavita rend `0` pour « pas d'identifiant » : l'envoyer ferait chercher
        le run 0, et ComicVine répondrait quelque chose."""
        hints = provider_hints({"comicVineId": 0, "malId": 0})

        assert "comicvine_id" not in hints
        assert "mal_id" not in hints

    def test_une_valeur_illisible_est_ignoree_sans_lever(self):
        hints = provider_hints({"comicVineId": "pas un nombre", "malId": None})

        assert "comicvine_id" not in hints
        assert "mal_id" not in hints

    def test_aucune_cle_generique_n_est_produite(self):
        """`_resolve_volume_id` lit aussi `provider_id` et `url` : les remplir
        ferait accepter par ComicVine un identifiant venu d'ailleurs."""
        hints = provider_hints({"comicVineId": 42, "aniListId": 99})

        assert "provider_id" not in hints
        assert "url" not in hints

    def test_une_serie_vide_rend_quand_meme_l_annee(self):
        assert provider_hints(None) == {"year": None}
        assert provider_hints({}) == {"year": None}


class TestLePlanLesTransmet:
    """Le garde-fou qui compte : la fonction peut exister et n'être pas branchée."""

    def test_build_series_plan_passe_les_indices_au_fournisseur(self, monkeypatch):
        from services.volume_enrichment import job

        vu = {}

        class _Api:
            def get_series(self, series_id):
                return {
                    "id": series_id,
                    "name": "Gaston Lagaffe",
                    "libraryType": "ComicFlexible",
                    "year": 1957,
                    "comicVineId": 4242,
                }

            def get_series_volumes(self, series_id):
                return [{"id": 1, "number": 1, "chapters": [{"id": 11, "number": "1"}]}]

        def _fake_resolve(series_id, name, units, **kwargs):
            vu.update(kwargs.get("existing_metadata") or {})
            return "COMICVINE", {}, False

        monkeypatch.setattr(job, "resolve_index_cached", _fake_resolve)
        monkeypatch.setattr(job, "get_all_cached_data", lambda: {})
        monkeypatch.setattr(job, "translate_plan_summaries", lambda plan, config: plan)

        job.build_series_plan(_Api(), 6317, config={})

        assert vu.get("comicvine_id") == "4242", (
            "l'identifiant connu de Kavita n'est pas arrivé au fournisseur : "
            "la série sera redevinée par recherche de titre"
        )
