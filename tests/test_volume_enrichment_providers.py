"""
Choix du fournisseur pour l'enrichissement des tomes.

Le danger de ce module n'est pas de ne rien trouver — c'est de trouver la
mauvaise série et de l'écrire tome par tome, verrous compris, sans qu'aucun
message ne le signale. Un identifiant forcé n'a de sens que chez le fournisseur
qui l'a émis : `30002` désigne une série AniList, et ComicVine le lira sans
broncher comme un numéro de volume.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment.providers import (
    cascade_rank,
    fetch_by_isbn,
    fetch_index,
    forced_id_for,
    resolve_index,
    volume_providers,
)


class _Scraper:
    """Fournisseur minimal qui enregistre l'identifiant qu'on lui a transmis."""

    def __init__(self, scraper_id, index=None, supported_types=None):
        self.id = scraper_id
        self.display_name = scraper_id
        self.rate_limit = 0
        self.seen_series_id = "sentinelle"
        self.supported_types = set(supported_types or ())
        self._index = index

    def fetch_volume_index(self, query, library_type="Comic", series_id=None,
                           existing_metadata=None):
        self.seen_series_id = series_id
        return self._index


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(
        "services.volume_enrichment.providers.throttle_provider", lambda *_a, **_k: None
    )


def test_an_id_reaches_the_provider_it_was_recorded_for():
    scraper = _Scraper("COMICVINE", {"1": {"title": "Un"}})

    fetch_index("Saga", forced_id="4050-12345", forced_provider="COMICVINE",
                providers=[scraper])

    assert scraper.seen_series_id == "4050-12345"


def test_an_id_recorded_elsewhere_is_not_handed_over():
    """Le cas qui écrivait une autre œuvre : un identifiant AniList transmis à
    ComicVine, qui le prend pour un numéro de volume et rend un run entier."""
    scraper = _Scraper("COMICVINE", {"1": {"title": "Une autre série"}})

    fetch_index("Berserk", forced_id="30002", forced_provider="ANILIST",
                providers=[scraper])

    assert scraper.seen_series_id is None, "ComicVine ne doit pas voir un identifiant AniList"


def test_a_url_carries_its_own_provider(monkeypatch):
    """Le Champ Magique laisse souvent le fournisseur sur AUTO : c'est alors le
    domaine de l'URL qui tranche, pas la préférence enregistrée."""
    monkeypatch.setattr(
        "services.volume_enrichment.providers.detect_provider_from_url",
        lambda url: "COMICVINE" if "comicvine" in url else "BEDETHEQUE",
    )
    cv = _Scraper("COMICVINE")
    bd = _Scraper("BEDETHEQUE")
    url = "https://comicvine.gamespot.com/saga/4050-12345/"

    assert forced_id_for(cv, url, "AUTO") == url
    assert forced_id_for(bd, url, "AUTO") is None


def test_no_forced_id_means_search_by_name():
    scraper = _Scraper("COMICVINE")

    assert forced_id_for(scraper, "", "COMICVINE") is None
    assert forced_id_for(scraper, "   ", "COMICVINE") is None


def test_the_first_provider_with_something_to_say_wins():
    empty = _Scraper("BEDETHEQUE", None)
    full = _Scraper("COMICVINE", {"1": {"title": "Un"}})

    provider, index = fetch_index("Saga", providers=[empty, full])

    assert provider == "COMICVINE"
    assert index == {"1": {"title": "Un"}}


def test_a_provider_that_crashes_does_not_sink_the_series():
    class _Broken(_Scraper):
        def fetch_volume_index(self, *a, **k):
            raise RuntimeError("502")

    provider, index = fetch_index(
        "Saga", providers=[_Broken("BEDETHEQUE"), _Scraper("COMICVINE", {"1": {"title": "Un"}})]
    )

    assert provider == "COMICVINE"


def test_a_cancelled_pass_stops_before_the_next_provider():
    """Un index Bédéthèque dure deux minutes : sans ce contrôle, l'annulation
    ne se verrait qu'une fois la série entière parcourue."""
    scraper = _Scraper("COMICVINE", {"1": {"title": "Un"}})

    provider, index = fetch_index("Saga", providers=[scraper], should_cancel=lambda: True)

    assert index == {}
    assert scraper.seen_series_id == "sentinelle", "le fournisseur ne doit pas être appelé"


# --- Annulation de la cascade ISBN -------------------------------------------
#
# Tout le reste du chemin était câblé : `fetch_index` teste l'annulation à chaque
# fournisseur, `fetch_by_title_volume` à chaque tome, `apply_plan` à chaque
# unité. La cascade ISBN, elle, ne la testait nulle part — et c'est celle qui
# prend systématiquement le relais sur une bibliothèque Manga. Une série de
# soixante tomes, trois fournisseurs cadencés à une seconde par appel : le clic
# sur Annuler répondait `{"cancelled": true}` puis trois minutes d'appels
# continuaient, jusqu'à onze minutes au plafond de deux cents tomes, pendant
# lesquelles `/status` disait `running: true` et aucune nouvelle passe n'était
# acceptée.


class _IsbnScraper:
    """Fournisseur ISBN qui compte ses appels."""

    def __init__(self, scraper_id="GOOGLEBOOKS", found=True):
        self.id = scraper_id
        self.display_name = scraper_id
        self.rate_limit = 0
        self.calls = []
        self._found = found

    def fetch(self, query, library_type="Manga", existing_metadata=None):
        self.calls.append(query)
        return {"title": f"Tome {query}"} if self._found else None


def _isbn_units(count=60):
    return [
        {"volume_number": str(n), "chapter": {"isbn": f"978000000{n:04d}"}}
        for n in range(1, count + 1)
    ]


def _registry_with(monkeypatch, scraper):
    from scrapers import ScraperRegistry

    monkeypatch.setattr(
        ScraperRegistry, "get", lambda pid: scraper if pid == scraper.id else None
    )
    return scraper


def test_a_cancelled_pass_stops_the_isbn_cascade_at_the_next_volume(monkeypatch):
    scraper = _registry_with(monkeypatch, _IsbnScraper())
    seen = {"n": 0}

    def cancel_after_two_volumes():
        seen["n"] += 1
        return seen["n"] > 2

    index = fetch_by_isbn(
        _isbn_units(),
        provider_ids=[scraper.id],
        should_cancel=cancel_after_two_volumes,
    )

    assert len(scraper.calls) == 2, "aucun appel fournisseur après l'annulation"
    assert len(index) == 2, "ce qui a été trouvé avant l'annulation est gardé"


def test_the_isbn_cascade_is_told_about_the_cancellation(monkeypatch):
    """`resolve_index` enchaîne l'index par série puis la cascade ISBN : sans
    transmission, l'annulation testée par le premier était perdue par la
    seconde."""
    scraper = _registry_with(monkeypatch, _IsbnScraper())
    monkeypatch.setattr(
        "services.volume_enrichment.providers.ISBN_PROVIDERS", (scraper.id,)
    )
    monkeypatch.setattr(
        "services.volume_enrichment.providers.fetch_index",
        # Index de couvertures seules (cas MangaDex) : c'est ce qui déclenche la
        # cascade ISBN au lieu de s'arrêter là.
        lambda name, **kw: ("MANGADEX", {"1": {"cover_url": "https://x/1.jpg"}}),
    )

    provider, index = resolve_index(
        "Berserk",
        _isbn_units(),
        library_type="Manga",
        should_cancel=lambda: True,
        config={},
    )

    assert scraper.calls == [], "la cascade ISBN ne doit pas démarrer après l'annulation"
    assert provider == "MANGADEX"
    assert index == {"1": {"cover_url": "https://x/1.jpg"}}


def test_without_cancellation_the_isbn_cascade_goes_through(monkeypatch):
    scraper = _registry_with(monkeypatch, _IsbnScraper())

    index = fetch_by_isbn(_isbn_units(3), provider_ids=[scraper.id])

    assert len(scraper.calls) == 3
    assert len(index) == 3


# --- Ordre de la cascade -----------------------------------------------------
#
# L'ordre décide de tout, puisque le premier index non vide gagne. Le registre
# trie par nom d'affichage, ce qui place Bédéthèque avant ComicVine : sur une
# bibliothèque de comics américains, une homonymie franco-belge suffisait à
# faire écrire les tomes d'une autre œuvre sans que ComicVine soit consulté.

@pytest.fixture
def _registry(monkeypatch):
    """Le registre tel qu'il répond vraiment : trié par nom d'affichage."""
    from scrapers import ScraperRegistry

    catalogue = [
        _Scraper("BEDETHEQUE", supported_types={"Comic"}),
        _Scraper("COMICVINE", supported_types={"Comic"}),
        _Scraper("MANGADEX", supported_types={"Manga"}),
        _Scraper("PLANETEBD", supported_types={"Comic"}),
    ]
    monkeypatch.setattr(
        ScraperRegistry, "get_by_scope", lambda scope, **kw: list(catalogue)
    )
    return catalogue


def _ids(library_type, config, **kw):
    return [s.id for s in volume_providers(library_type, config=config, **kw)]


def test_the_cascade_of_the_providers_modal_decides_the_order(_registry):
    config = {"COMIC_PROVIDER_1": "COMICVINE", "COMIC_PROVIDER_2": "ANILIST",
              "COMIC_PROVIDER_3": "LOCG"}

    assert _ids("Comic", config)[0] == "COMICVINE"


def test_a_franco_belge_library_can_ask_bedetheque_first(_registry):
    config = {"COMIC_PROVIDER_1": "BEDETHEQUE", "COMIC_PROVIDER_2": "COMICVINE",
              "COMIC_PROVIDER_3": "NONE"}

    assert _ids("Comic", config)[:2] == ["BEDETHEQUE", "COMICVINE"]


def test_providers_the_cascade_ignores_stay_reachable_but_last(_registry):
    """Trois slots ne couvrent pas cinq fournisseurs : les autres restent en
    repli, dans l'ordre du registre, mais jamais avant ceux qu'on a nommés."""
    config = {"COMIC_PROVIDER_1": "COMICVINE", "COMIC_PROVIDER_2": "NONE",
              "COMIC_PROVIDER_3": "NONE"}

    assert _ids("Comic", config) == ["COMICVINE", "BEDETHEQUE", "PLANETEBD"]


def test_the_library_type_still_filters_before_the_order(_registry):
    """MangaDex ne connaît pas les comics : le nommer dans la cascade Comic ne
    doit pas l'y faire entrer."""
    config = {"COMIC_PROVIDER_1": "MANGADEX", "COMIC_PROVIDER_2": "COMICVINE",
              "COMIC_PROVIDER_3": "NONE"}

    assert _ids("Comic", config) == ["COMICVINE", "BEDETHEQUE", "PLANETEBD"]


def test_manga_reads_its_own_slots(_registry):
    config = {"PROVIDER_1": "MANGADEX", "COMIC_PROVIDER_1": "COMICVINE"}

    assert _ids("Manga", config) == ["MANGADEX"]


def test_an_empty_cascade_keeps_the_registry_order(_registry):
    assert _ids("Comic", {}) == ["BEDETHEQUE", "COMICVINE", "PLANETEBD"]


def test_a_provider_named_twice_keeps_its_best_rank():
    ranks = cascade_rank("Comic", {"COMIC_PROVIDER_1": "COMICVINE",
                                   "COMIC_PROVIDER_2": "COMICVINE"})

    assert ranks["COMICVINE"] == 0


def test_none_and_blank_slots_are_not_providers():
    ranks = cascade_rank("Book", {"BOOK_PROVIDER_1": "NONE", "BOOK_PROVIDER_2": "  ",
                                  "BOOK_PROVIDER_3": "openlibrary"})

    assert ranks == {"OPENLIBRARY": 2}
