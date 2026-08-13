"""Reprendre la main sur les fournisseurs de tomes, et sur les deux familles.

Constaté en production, sur une bibliothèque « Comic (Flexible) » ne contenant
que de la bande dessinée franco-belge : le journal montre
« [MangaDex] Recherche par titre : 'Gaston Lagaffe' ». Ce n'est pas un défaut de
la cascade — ce type de bibliothèque enchaîne par construction les fournisseurs
comics puis les manga en repli, et l'utilisateur peut y ranger les deux — mais
c'est du temps perdu, à la cadence du fournisseur, pour quelqu'un qui n'y range
que des albums. Et jusqu'ici rien ne permettait de l'éviter : même les
fournisseurs qu'aucun slot ne nomme restent joignables en dernier recours.

D'où :

* `VOLUME_NO_MANGA_FALLBACK` — écarte les fournisseurs qui ne servent que le
  manga, sur les bibliothèques flexibles seulement ;
* `VOLUME_PROVIDER` — n'en consulte qu'un, la cascade écartée.

Le second porte une nuance qui se teste : un forçage ne doit pas casser les
autres bibliothèques. Imposer ComicVine ne doit pas priver une bibliothèque manga
de tout fournisseur, ce qui rendrait un « aucun fournisseur ne connaît cette
série » accusant le fournisseur au lieu du réglage.

Et il ne lisait qu'une des deux familles. Google Books, Open Library et Hardcover
servent les tomes depuis le début — par ISBN, pour compléter un index manga
qui n'a pas tout dit (Manga-News s'arrête à quarante tomes, MangaDex ne rend
que des couvertures) — mais aucun n'apparaissait au menu, et imposer l'un d'eux
journalisait « fournisseur imposé inutilisable » avant de reprendre la cascade.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment.providers import (
    forced_unit_provider,
    forced_volume_provider,
    provides_volume_index,
    resolve_index,
    volume_provider_choices,
    volume_providers,
)

CONFIG = {
    "COMIC_PROVIDER_1": "COMICVINE",
    "COMIC_PROVIDER_2": "BEDETHEQUE",
    "COMIC_PROVIDER_3": "NONE",
    "PROVIDER_1": "MANGADEX",
    "PROVIDER_2": "ANILIST",
    "PROVIDER_3": "NONE",
}


class _Faux:
    def __init__(self, scraper_id, supported):
        self.id = scraper_id
        self.display_name = scraper_id.title()
        self.supported_types = set(supported)

    def fetch_volume_index(self, *a, **kw):  # pragma: no cover - jamais appelé ici
        return {}


@pytest.fixture
def registre(monkeypatch):
    scrapers = [
        _Faux("BEDETHEQUE", {"Comic"}),
        _Faux("COMICVINE", {"Comic"}),
        _Faux("MANGADEX", {"Manga"}),
        _Faux("MANGANEWS", {"Manga"}),
        _Faux("PLANETEBD", {"Comic"}),
    ]
    monkeypatch.setattr(
        "scrapers.ScraperRegistry.get_by_scope", lambda scope: list(scrapers)
    )
    return scrapers


def _config(**overrides):
    merged = dict(CONFIG)
    merged.update(overrides)
    return merged


class TestLectureDuReglage:
    """« Laisser la cascade décider » a plusieurs orthographes à l'arrivée."""

    @pytest.mark.parametrize("raw", ["", None, "AUTO", "auto", "  ", "NONE"])
    def test_ces_valeurs_veulent_dire_cascade(self, raw):
        assert forced_volume_provider({"VOLUME_PROVIDER": raw}) == ""

    def test_un_identifiant_est_normalise_en_majuscules(self):
        """Le formulaire peut renvoyer ce qu'il veut : la comparaison porte sur
        des identifiants de scrapers, qui sont en majuscules."""
        assert forced_volume_provider({"VOLUME_PROVIDER": " comicvine "}) == "COMICVINE"

    def test_une_configuration_sans_la_cle_ne_force_rien(self):
        assert forced_volume_provider({}) == ""


class TestRepliManga:
    """Le repli ne se coupe que là où il existe : les bibliothèques flexibles."""

    def test_mangadex_est_ecarte_quand_le_repli_est_coupe(self, registre):
        ordre = [
            s.id
            for s in volume_providers(
                "ComicFlexible", config=_config(VOLUME_NO_MANGA_FALLBACK=True)
            )
        ]

        assert "MANGADEX" not in ordre
        assert ordre[0] == "COMICVINE", "les comics gardent leur ordre de cascade"

    def test_les_fournisseurs_comics_sont_tous_conserves(self, registre):
        """Couper le repli ne doit pas couper autre chose au passage."""
        ordre = [
            s.id
            for s in volume_providers(
                "ComicFlexible", config=_config(VOLUME_NO_MANGA_FALLBACK=True)
            )
        ]

        assert set(ordre) == {"COMICVINE", "BEDETHEQUE", "PLANETEBD"}

    def test_le_repli_reste_par_defaut(self, registre):
        """Le réglage est éteint à la mise à jour : rien ne change sans le cocher."""
        ordre = [s.id for s in volume_providers("ComicFlexible", config=_config())]

        assert "MANGADEX" in ordre
        assert "MANGANEWS" in ordre
        assert ordre.index("MANGANEWS") < ordre.index("MANGADEX")

    def test_une_bibliotheque_manga_n_est_pas_touchee(self, registre):
        """Le réglage nomme les bibliothèques flexibles, et lui seul les concerne.

        L'appliquer à une bibliothèque manga la priverait de ses fournisseurs
        de tomes.
        """
        ordre = [
            s.id
            for s in volume_providers(
                "Manga", config=_config(VOLUME_NO_MANGA_FALLBACK=True)
            )
        ]

        assert ordre == ["MANGANEWS", "MANGADEX"]


class TestFournisseurImpose:
    def test_un_seul_fournisseur_est_consulte(self, registre):
        retenus = volume_providers(
            "ComicFlexible", config=_config(VOLUME_PROVIDER="COMICVINE")
        )

        assert [s.id for s in retenus] == ["COMICVINE"]

    def test_il_prime_sur_l_ordre_de_la_cascade(self, registre):
        """Imposer le troisième de la cascade doit écarter les deux premiers."""
        retenus = volume_providers(
            "ComicFlexible", config=_config(VOLUME_PROVIDER="PLANETEBD")
        )

        assert [s.id for s in retenus] == ["PLANETEBD"]

    def test_la_cascade_reprend_la_ou_l_impose_ne_sait_pas_servir(self, registre, caplog):
        """La nuance qui évite de casser les autres bibliothèques.

        ComicVine ne sert pas le manga. Le retenir quand même rendrait une liste
        vide, donc un aperçu « aucun fournisseur ne connaît cette série » qui
        accuserait le fournisseur au lieu du réglage.
        """
        with caplog.at_level("INFO"):
            retenus = volume_providers(
                "Manga", config=_config(VOLUME_PROVIDER="COMICVINE")
            )

        assert [s.id for s in retenus] == ["MANGANEWS", "MANGADEX"]
        assert "COMICVINE" in caplog.text, "le repli doit se lire dans le journal"

    def test_un_fournisseur_inconnu_ne_vide_pas_la_liste(self, registre):
        """Un scraper désinstallé depuis le réglage ne doit pas tout arrêter."""
        retenus = volume_providers(
            "ComicFlexible", config=_config(VOLUME_PROVIDER="PLUSINSTALLE")
        )

        assert [s.id for s in retenus][0] == "COMICVINE"

    def test_les_deux_reglages_se_combinent(self, registre):
        """Le forçage s'applique après le filtrage : imposer MangaDex alors que le
        repli manga est coupé ne doit pas le faire rentrer par la fenêtre."""
        retenus = volume_providers(
            "ComicFlexible",
            config=_config(VOLUME_PROVIDER="MANGADEX", VOLUME_NO_MANGA_FALLBACK=True),
        )

        assert "MANGADEX" not in [s.id for s in retenus]


class _ALUnite:
    """Fournisseur qui répond à l'unité : un ISBN, un tome.

    Google Books, Open Library et Hardcover : ils ne listent pas les albums d'une
    série, ils identifient un tome à la fois. Sur un manga ils complètent
    Manga-News (et MangaDex, qui ne rend que des jaquettes).
    """

    def __init__(self, scraper_id, cherche_par_titre=False):
        self.id = scraper_id
        self.display_name = scraper_id.title()
        self.rate_limit = 0
        self.supported_types = {"Book", "Comic"}
        self.isbns = []
        if cherche_par_titre:
            self.fetch_volume = self._fetch_volume

    def fetch(self, query, library_type="Manga", existing_metadata=None):
        self.isbns.append(query)
        return {"title": f"Tome {query}", "summary": "Un résumé"}

    def _fetch_volume(self, query, library_type="Manga", volume_number=None,
                      series_id=None, existing_metadata=None):
        return {"title": f"{query} {volume_number}"}


@pytest.fixture
def registre_complet(monkeypatch, registre):
    """Le registre des deux familles : ceux qui listent, ceux qui identifient."""
    from scrapers import ScraperRegistry

    a_l_unite = {
        "GOOGLEBOOKS": _ALUnite("GOOGLEBOOKS", cherche_par_titre=True),
        "OPENLIBRARY": _ALUnite("OPENLIBRARY"),
        "HARDCOVER": _ALUnite("HARDCOVER"),
    }
    par_id = {s.id: s for s in registre}
    par_id.update(a_l_unite)
    monkeypatch.setattr(ScraperRegistry, "get", lambda pid, **kw: par_id.get(pid))
    monkeypatch.setattr(
        "services.volume_enrichment.providers.throttle_provider", lambda *_a, **_k: None
    )
    return a_l_unite


def _tomes(count=3, avec_isbn=True):
    return [
        {
            "chapter_id": n,
            "volume_number": str(n),
            "chapter": {"isbn": f"978000000{n:04d}"} if avec_isbn else {},
        }
        for n in range(1, count + 1)
    ]


class TestLesDeuxFamillesDeFournisseurs:
    """Le réglage ne lisait que les fournisseurs d'index.

    Google Books, Open Library et Hardcover servaient déjà les tomes — par ISBN,
    et c'est ce qui fait tout le travail sur les mangas — mais aucun n'apparaissait
    au menu, et imposer l'un d'eux journalisait « fournisseur imposé inutilisable »
    avant de reprendre la cascade. Un réglage sans effet sur les seuls fournisseurs
    qui répondent quand la série n'a pas de liste d'albums.
    """

    def test_les_fournisseurs_par_isbn_figurent_au_menu(self, registre_complet):
        propose = {c["id"]: c["kind"] for c in volume_provider_choices()}

        assert propose["GOOGLEBOOKS"] == "unit"
        assert propose["OPENLIBRARY"] == "unit"
        assert propose["HARDCOVER"] == "unit"
        assert propose["COMICVINE"] == "index", "les fournisseurs d'index restent proposés"

    def test_les_deux_familles_sont_distinguees(self, registre_complet):
        """Un fournisseur par ISBN ne rend rien sur un tome qui n'en porte pas :
        le menu doit le dire avant le choix, pas le journal après."""
        familles = {c["kind"] for c in volume_provider_choices()}

        assert familles == {"index", "unit"}

    def test_un_fournisseur_absent_du_registre_n_est_pas_propose(self, monkeypatch, registre):
        """Hardcover demande une clé d'API : il peut ne pas être installé."""
        from scrapers import ScraperRegistry

        monkeypatch.setattr(ScraperRegistry, "get", lambda pid, **kw: None)

        assert not [c for c in volume_provider_choices() if c["kind"] == "unit"]


class TestSavoirListerNeSeDeclarePas:
    """`hasattr(scraper, "fetch_volume_index")` répondait oui pour tout le monde.

    `BaseScraper` définit la méthode et sa version rend `None`. Un scraper tiers
    qui déclare `scopes = {"volume"}` sans l'écrire était donc consulté — cadence
    payée, une seconde ou deux perdues par série — pour un `None` garanti.
    """

    def _scraper_sans_index(self):
        from scrapers.base import BaseScraper

        class _Tiers(BaseScraper):
            id = "TIERS"
            display_name = "Tiers"
            supported_types = {"Comic"}
            scopes = {"series", "volume"}

            def fetch(self, query, library_type="Manga", is_id=False,
                      existing_metadata=None):  # pragma: no cover
                return None

        return _Tiers()

    def test_heriter_de_la_base_ne_suffit_pas(self):
        assert provides_volume_index(self._scraper_sans_index()) is False

    def test_ecrire_la_methode_suffit(self):
        assert provides_volume_index(_Faux("COMICVINE", {"Comic"})) is True

    def test_il_ne_consomme_aucune_cadence(self, monkeypatch):
        from services.volume_enrichment import providers as prov

        cadences = []
        monkeypatch.setattr(prov, "throttle_provider", lambda s: cadences.append(s.id))

        provider, index = prov.fetch_index("Saga", providers=[self._scraper_sans_index()])

        assert cadences == [], "rien à demander, donc rien à attendre"
        assert (provider, index) == ("", {})

    def test_il_n_est_pas_propose_au_menu(self, monkeypatch):
        from scrapers import ScraperRegistry

        monkeypatch.setattr(
            ScraperRegistry, "get_by_scope",
            lambda scope, **kw: [self._scraper_sans_index()],
        )
        monkeypatch.setattr(ScraperRegistry, "get", lambda pid, **kw: None)

        assert volume_provider_choices() == []


class TestUnFournisseurALUniteImpose:
    """Ce qu'imposer Google Books doit vouloir dire."""

    def test_le_reglage_reconnait_la_famille(self):
        assert forced_unit_provider({"VOLUME_PROVIDER": "GOOGLEBOOKS"}) == "GOOGLEBOOKS"
        assert forced_unit_provider({"VOLUME_PROVIDER": "COMICVINE"}) == ""
        assert forced_unit_provider({"VOLUME_PROVIDER": "AUTO"}) == ""

    def test_aucun_index_n_est_demande(self, monkeypatch, registre_complet):
        """Il n'en rend pas : demander l'index à quelqu'un d'autre irait contre le
        réglage, et c'est précisément ce que faisait le repli sur la cascade."""
        from services.volume_enrichment import providers as prov

        appels = []
        monkeypatch.setattr(
            prov, "fetch_index",
            lambda *a, **kw: appels.append(a) or ("MANGADEX", {}),
        )

        provider, index = resolve_index(
            "Berserk", _tomes(), library_type="Manga",
            config=_config(VOLUME_PROVIDER="GOOGLEBOOKS"),
        )

        assert appels == [], "aucun fournisseur d'index ne doit être consulté"
        assert provider == "ISBN"
        assert len(index) == 3

    def test_la_cascade_isbn_se_restreint_a_lui(self, registre_complet):
        """Sans quoi le réglage ne ferait qu'ajouter un fournisseur en tête."""
        resolve_index(
            "Berserk", _tomes(), library_type="Manga",
            config=_config(VOLUME_PROVIDER="OPENLIBRARY"),
        )

        assert len(registre_complet["OPENLIBRARY"].isbns) == 3
        assert registre_complet["GOOGLEBOOKS"].isbns == []
        assert registre_complet["HARDCOVER"].isbns == []

    def test_la_liste_des_index_est_vide_sans_repli(self, registre):
        """`volume_providers` rend la liste des fournisseurs d'index : celle d'un
        fournisseur à l'unité est vide, et ce n'est pas un échec à corriger par un
        repli."""
        retenus = volume_providers("Manga", config=_config(VOLUME_PROVIDER="GOOGLEBOOKS"))

        assert retenus == []

    def test_un_tome_sans_isbn_ne_lui_dit_rien_et_le_journal_le_dit(
        self, caplog, registre_complet
    ):
        """C'est la limite du réglage, et elle doit se lire : l'aperçu, lui,
        affichera « aucun fournisseur ne connaît cette série », ce qui accuserait
        le fournisseur au lieu du choix."""
        with caplog.at_level("INFO"):
            provider, index = resolve_index(
                "Berserk", _tomes(avec_isbn=False), library_type="Manga",
                config=_config(VOLUME_PROVIDER="OPENLIBRARY"),
            )

        assert (provider, index) == ("", {})
        assert "OPENLIBRARY" in caplog.text
        assert "ISBN" in caplog.text

    def test_seul_google_books_cherche_par_titre_et_numero(
        self, monkeypatch, registre_complet
    ):
        from services.volume_enrichment import providers as prov

        vus = {}
        monkeypatch.setattr(
            prov, "fetch_by_title_volume",
            lambda name, units, **kw: vus.update(kw) or {"1": {"title": "Tome 1"}},
        )

        resolve_index(
            "Berserk", _tomes(avec_isbn=False), library_type="Manga",
            experimental=True, config=_config(VOLUME_PROVIDER="GOOGLEBOOKS"),
        )

        assert vus.get("provider_ids") == ["GOOGLEBOOKS"]

    def test_l_imposer_suffit_a_ouvrir_la_recherche_par_titre(
        self, caplog, registre_complet
    ):
        """Le cas de tous les mangas scannés, et l'aperçu vide qu'il rendait.

        Sans ISBN dans Kavita, la recherche par titre et numéro est le seul chemin
        qui rende un titre ou un résumé. Elle était refusée à un fournisseur pourtant
        désigné à la main, faute d'avoir aussi coché l'interrupteur expérimental :
        le geste fait pour remplir l'aperçu était précisément celui qui garantissait
        qu'il resterait vide, l'index par série étant supprimé par le même réglage.
        """
        with caplog.at_level("INFO"):
            provider, index = resolve_index(
                "Berserk", _tomes(avec_isbn=False), library_type="Manga",
                config=_config(VOLUME_PROVIDER="GOOGLEBOOKS"),
            )

        assert provider == "TITRE"
        assert set(index) == {"1", "2", "3"}
        assert index["2"]["title"] == "Berserk 2", "le fournisseur imposé a bien répondu"
        assert "GOOGLEBOOKS" in caplog.text, "le journal doit dire d'où vient la recherche"

    def test_la_cascade_automatique_reste_derriere_l_interrupteur(
        self, monkeypatch, registre_complet
    ):
        """L'activation implicite ne vaut que pour un fournisseur nommé à la main.

        Personne n'a désigné Google Books ici : la recherche sans identifiant ne
        doit pas se déclencher d'elle-même sur toute une bibliothèque.
        """
        from services.volume_enrichment import providers as prov

        appels = []
        monkeypatch.setattr(prov, "fetch_index", lambda *a, **kw: ("", {}))
        monkeypatch.setattr(
            prov, "fetch_by_title_volume", lambda *a, **kw: appels.append(a) or {}
        )

        resolve_index("Berserk", _tomes(avec_isbn=False), library_type="Manga",
                      config=_config())

        assert appels == []

    def test_open_library_impose_sans_interrupteur_ne_cherche_pas_non_plus(
        self, monkeypatch, registre_complet
    ):
        """Open Library et Hardcover n'ont pas de `fetch_volume` : les imposer ne
        peut rien ouvrir, et le journal doit nommer ceux qui savent le faire."""
        from services.volume_enrichment import providers as prov

        appels = []
        monkeypatch.setattr(
            prov, "fetch_by_title_volume", lambda *a, **kw: appels.append(a) or {}
        )

        resolve_index(
            "Berserk", _tomes(avec_isbn=False), library_type="Manga",
            config=_config(VOLUME_PROVIDER="HARDCOVER"),
        )

        assert appels == []

    def test_open_library_impose_ne_part_pas_en_recherche_par_titre(
        self, monkeypatch, registre_complet
    ):
        """Il ne sait pas le faire — pas de `fetch_volume` — et le chemin titre est
        le seul du module qui n'ait aucun identifiant pour se vérifier : y verser
        un fournisseur qui n'y répond pas ne peut que produire du silence."""
        from services.volume_enrichment import providers as prov

        appels = []
        monkeypatch.setattr(
            prov, "fetch_by_title_volume", lambda *a, **kw: appels.append(a) or {}
        )

        resolve_index(
            "Berserk", _tomes(avec_isbn=False), library_type="Manga",
            experimental=True, config=_config(VOLUME_PROVIDER="OPENLIBRARY"),
        )

        assert appels == []

    def test_imposer_un_fournisseur_d_index_ne_change_rien(
        self, monkeypatch, registre_complet
    ):
        """Non-régression : le forçage existant garde exactement son chemin."""
        from services.volume_enrichment import providers as prov

        appels = []
        monkeypatch.setattr(
            prov, "fetch_index",
            lambda *a, **kw: appels.append(kw.get("library_type")) or (
                "COMICVINE", {"1": {"title": "Un"}, "2": {"title": "Deux"},
                              "3": {"title": "Trois"}}
            ),
        )

        provider, _ = resolve_index(
            "Saga", _tomes(), library_type="Comic",
            config=_config(VOLUME_PROVIDER="COMICVINE"),
        )

        assert appels == ["Comic"]
        assert provider == "COMICVINE"


class TestLaMemoisationSuitLesReglages:
    """Un index retenu dix minutes rendrait les deux réglages muets.

    L'index fournisseur est mémoïsé entre l'aperçu et l'écriture. Sa clé porte la
    cascade, précisément pour qu'un changement de fournisseur ne resserve pas
    l'index du précédent : les deux nouveaux réglages changent la liste consultée,
    donc l'index, donc ils appartiennent à la clé. Sans cela, cocher « pas de
    repli manga » et rouvrir l'aperçu resservait l'index de MangaDex — ce qui se
    lit comme un réglage qui ne marche pas.
    """

    def _signature(self, **overrides):
        from services.volume_enrichment.index_cache import _cascade_signature

        return _cascade_signature("ComicFlexible", _config(**overrides))

    def test_couper_le_repli_manga_change_la_cle(self):
        assert self._signature() != self._signature(VOLUME_NO_MANGA_FALLBACK=True)

    def test_imposer_un_fournisseur_change_la_cle(self):
        assert self._signature() != self._signature(VOLUME_PROVIDER="COMICVINE")

    def test_deux_fournisseurs_imposes_ne_se_partagent_pas_une_entree(self):
        assert self._signature(VOLUME_PROVIDER="COMICVINE") != self._signature(
            VOLUME_PROVIDER="BEDETHEQUE"
        )

    def test_des_reglages_identiques_gardent_la_meme_cle(self):
        """L'inverse compte autant : une clé qui change sans raison rendrait la
        mémoïsation inutile et ferait repayer le fournisseur à chaque aperçu."""
        assert self._signature(VOLUME_PROVIDER="COMICVINE") == self._signature(
            VOLUME_PROVIDER="COMICVINE"
        )

    def test_auto_et_vide_sont_la_meme_demande(self):
        """« Laisser la cascade décider » ne doit pas dépendre de son orthographe."""
        assert self._signature(VOLUME_PROVIDER="AUTO") == self._signature(
            VOLUME_PROVIDER=""
        )
