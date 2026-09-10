"""Une bibliothèque « Comic (Flexible) » interroge les comics avant les mangas.

Kavita appelle « Comic (Flexible) » son type de bibliothèque 1, que MetaKavita
nomme `ComicFlexible`. Le chemin série le traite en deux vagues — les
fournisseurs comics d'abord, les manga seulement si la première n'a rien trouvé
d'utile — et `tests/test_comic_flexible.py` en fait foi.

Le chemin tome ne le faisait pas. `CASCADE_SLOTS` ne connaissait pas
`ComicFlexible`, donc `cascade_rank` retombait sur sa ligne de repli, `Manga`, et
classait les fournisseurs de tomes d'une bibliothèque de bandes dessinées par la
cascade **manga**. Constaté en production sur une série Blacksad : le journal du
conteneur montrait cinq « [MangaDex] Recherche par titre : 'Blacksad' », une par
construction de plan, avant que ComicVine ne soit consulté. L'index final restait
juste — MangaDex ne connaît pas ces séries — mais le détour était payé chaque
fois, cadence comprise.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment.providers import cascade_rank, volume_providers

CONFIG = {
    "COMIC_PROVIDER_1": "COMICVINE",
    "COMIC_PROVIDER_2": "BEDETHEQUE",
    "COMIC_PROVIDER_3": "NONE",
    "PROVIDER_1": "MANGADEX",
    "PROVIDER_2": "ANILIST",
    "PROVIDER_3": "NONE",
    "BOOK_PROVIDER_1": "GOOGLEBOOKS",
}


class _Faux:
    """Un scraper réduit à ce que la sélection et le tri lisent."""

    def __init__(self, scraper_id, supported):
        self.id = scraper_id
        self.display_name = scraper_id.title()
        self.supported_types = set(supported)

    def fetch_volume_index(self, *a, **kw):  # pragma: no cover - jamais appelé ici
        return {}


@pytest.fixture
def registre(monkeypatch):
    """`get_by_scope` rend les fournisseurs dans l'ordre alphabétique du registre.

    C'est bien cet ordre-là qu'il faut bouchonner : le tri par cascade est un tri
    **stable**, donc à rang égal l'alphabet subsiste, et un test qui partirait
    déjà trié ne prouverait rien.
    """
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


def test_le_rang_comic_flexible_place_les_comics_devant_les_mangas():
    ranks = cascade_rank("ComicFlexible", CONFIG)

    assert ranks["COMICVINE"] == 0
    assert ranks["BEDETHEQUE"] == 1
    # Les slots manga suivent les trois slots comics : rangs 3 et 4, jamais 0.
    assert ranks["MANGADEX"] == 3
    assert ranks["ANILIST"] == 4


def test_les_slots_livres_ne_s_invitent_pas():
    """« Flexible » recouvre les comics et les mangas, pas les catalogues de livres."""
    ranks = cascade_rank("ComicFlexible", CONFIG)

    assert "GOOGLEBOOKS" not in ranks


def test_comicvine_est_interroge_avant_mangadex_sur_une_bd(registre):
    """Le cas Blacksad, dans l'ordre où la cascade appellera les fournisseurs."""
    ordre = [s.id for s in volume_providers("ComicFlexible", config=CONFIG)]

    assert ordre.index("COMICVINE") < ordre.index("MANGADEX")
    assert ordre[0] == "COMICVINE"


def test_mangadex_reste_joignable_en_repli(registre):
    """Le retirer serait une régression : une bibliothèque flexible peut mélanger.

    Un manga rangé ici est d'abord servi par Manga-News ; MangaDex reste après,
    pour les couvertures, jamais à la place des comics.
    """
    ordre = [s.id for s in volume_providers("ComicFlexible", config=CONFIG)]

    assert "MANGANEWS" in ordre
    assert "MANGADEX" in ordre
    assert ordre.index("COMICVINE") < ordre.index("MANGANEWS")
    assert ordre.index("MANGANEWS") < ordre.index("MANGADEX")


def test_un_fournisseur_hors_cascade_passe_apres_ceux_qui_y_sont(registre):
    """Planète BD n'est nommé par aucun slot : il reste joignable, mais en dernier.

    Trois slots ne couvrent pas les cinq fournisseurs d'un type, et la lenteur
    d'un fournisseur HTML — une page par album — est une raison de plus de ne pas
    le laisser passer devant.
    """
    ordre = [s.id for s in volume_providers("ComicFlexible", config=CONFIG)]

    assert ordre.index("PLANETEBD") > ordre.index("BEDETHEQUE")


def test_les_types_connus_ne_changent_pas_de_comportement():
    """Garde-fou : l'ajout de `ComicFlexible` ne doit rien déplacer ailleurs."""
    assert cascade_rank("Comic", CONFIG) == {"COMICVINE": 0, "BEDETHEQUE": 1}
    assert cascade_rank("Manga", CONFIG) == {"MANGADEX": 0, "ANILIST": 1}
    assert cascade_rank("Book", CONFIG) == {"GOOGLEBOOKS": 0}


def test_un_type_inconnu_retombe_toujours_sur_la_cascade_manga():
    """Le repli existant est conservé : `ComicFlexible` n'en dépend simplement plus."""
    assert cascade_rank("TypeQuiNExistePas", CONFIG) == {"MANGADEX": 0, "ANILIST": 1}


def test_mangasanctuary_suit_manganews_sur_une_biblio_manga(monkeypatch):
    """Le Magasin se glisse juste derrière Manga-News, avant MangaDex."""
    scrapers = [
        _Faux("MANGADEX", {"Manga"}),
        _Faux("MANGANEWS", {"Manga"}),
        _Faux("MANGASANCTUARY", {"Manga"}),
    ]
    monkeypatch.setattr(
        "scrapers.ScraperRegistry.get_by_scope", lambda scope: list(scrapers)
    )
    ordre = [s.id for s in volume_providers("Manga", config=CONFIG)]

    assert ordre.index("MANGANEWS") < ordre.index("MANGASANCTUARY")
    assert ordre.index("MANGASANCTUARY") < ordre.index("MANGADEX")
