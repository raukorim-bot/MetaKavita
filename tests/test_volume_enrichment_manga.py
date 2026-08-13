"""
Le chemin manga de l'enrichissement par tome.

Un manga n'est pas une BD : aucun fournisseur ne publie de résumé par tome, et
Kavita affiche pour chaque volume une vignette découpée dans la première page —
souvent une page de garde noire. MangaDex tient les vraies couvertures de tomes,
un appel pour toute la série ; les ISBN déjà présents dans Kavita apportent le
reste. Les deux doivent se compléter : c'est le point que ces tests gardent.
"""
from __future__ import annotations

import pytest

from services.volume_enrichment import providers as prov


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _cover(volume, file_name, locale="ja"):
    return {"attributes": {"volume": volume, "fileName": file_name, "locale": locale}}


def _load_repo_scraper_module():
    """Le module de `scrapers/`, pas la copie installée dans `data/scrapers/`.

    Le nom donné au module reste préfixé par `scrapers.` pour que ses imports
    relatifs se résolvent — même précaution que pour ComicVine.
    """
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scrapers" / "mangadex.py"
    spec = importlib.util.spec_from_file_location("scrapers.mangadex_volume_index_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mangadex(monkeypatch):
    """Le scraper du dépôt, avec son réseau et sa cadence débranchés.

    La cadence ne vient plus d'un `time.sleep` du scraper mais de
    `throttle_provider`, appelé par `_http_get` : c'est `conftest` qui la
    neutralise pour toute la suite, il n'y a plus rien à débrancher ici."""
    module = _load_repo_scraper_module()
    monkeypatch.setattr(module, "load_config", lambda: {"TARGET_LANG": "FR"})
    return module


def test_one_call_brings_back_every_volume_cover(mangadex, monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, dict(params or [])))
        return _Response(
            {
                "data": [_cover("1", "a.jpg"), _cover("2", "b.jpg"), _cover("3", "c.jpg")],
                "total": 3,
            }
        )

    monkeypatch.setattr(mangadex.requests, "get", fake_get)
    scraper = mangadex.MangaDexScraper()

    index = scraper.fetch_volume_index("Berserk", series_id="a1b2c3d4-0000-1111-2222-333344445555")

    assert set(index) == {"1", "2", "3"}
    assert index["2"]["cover_url"].endswith("/a1b2c3d4-0000-1111-2222-333344445555/b.jpg")
    assert len(calls) == 1, "une série entière tient en un appel"


def test_the_reader_language_wins_over_the_original_edition(mangadex, monkeypatch):
    monkeypatch.setattr(
        mangadex.requests,
        "get",
        lambda *a, **k: _Response(
            {"data": [_cover("1", "jp.jpg", "ja"), _cover("1", "fr.jpg", "fr")], "total": 2}
        ),
    )
    scraper = mangadex.MangaDexScraper()

    index = scraper.fetch_volume_index("Berserk", series_id="a1b2c3d4-0000-1111-2222-333344445555")

    assert index["1"]["cover_url"].endswith("fr.jpg")


def test_a_cover_without_a_volume_number_is_dropped(mangadex, monkeypatch):
    """Les couvertures promotionnelles n'appartiennent à aucun tome : les
    laisser passer collerait une affiche sur le tome 1."""
    monkeypatch.setattr(
        mangadex.requests,
        "get",
        lambda *a, **k: _Response(
            {"data": [_cover(None, "promo.jpg"), _cover("1", "t1.jpg")], "total": 2}
        ),
    )
    scraper = mangadex.MangaDexScraper()

    index = scraper.fetch_volume_index("Berserk", series_id="a1b2c3d4-0000-1111-2222-333344445555")

    assert set(index) == {"1"}


def test_a_title_search_goes_through_the_matching_score(mangadex, monkeypatch):
    """Sans identifiant, prendre le premier résultat venu suffirait à coller les
    couvertures d'une autre série. On repasse par `fetch`, donc par le score."""
    seen = {}

    def fake_fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
        seen["query"] = query
        return {"url": "https://mangadex.org/title/a1b2c3d4-0000-1111-2222-333344445555"}

    monkeypatch.setattr(mangadex.MangaDexScraper, "fetch", fake_fetch)
    monkeypatch.setattr(
        mangadex.requests, "get", lambda *a, **k: _Response({"data": [_cover("1", "t1.jpg")], "total": 1})
    )

    index = mangadex.MangaDexScraper().fetch_volume_index("Berserk")

    assert seen["query"] == "Berserk"
    assert set(index) == {"1"}


def test_no_match_means_no_index(mangadex, monkeypatch):
    monkeypatch.setattr(
        mangadex.MangaDexScraper, "fetch", lambda *a, **k: None
    )

    assert mangadex.MangaDexScraper().fetch_volume_index("Série inexistante") is None


def test_a_broken_endpoint_is_silent_not_fatal(mangadex, monkeypatch):
    monkeypatch.setattr(mangadex.requests, "get", lambda *a, **k: _Response({}, status=503))
    scraper = mangadex.MangaDexScraper()

    assert scraper.fetch_volume_index(
        "Berserk", series_id="a1b2c3d4-0000-1111-2222-333344445555"
    ) is None


def test_mangadex_declares_the_volume_scope(mangadex):
    assert "volume" in mangadex.MangaDexScraper.scopes


# --- Complémentarité couvertures / ISBN ------------------------------------


def test_covers_alone_do_not_close_the_door_on_the_isbn_cascade(monkeypatch):
    """Le bug qu'on prévient : MangaDex rend un index non vide, l'ancienne
    logique s'arrêtait là, et les mangas repartaient sans titre ni résumé alors
    que leurs ISBN étaient dans Kavita."""
    monkeypatch.setattr(
        prov, "fetch_index", lambda name, **kw: ("MANGADEX", {"1": {"cover_url": "c.jpg"}})
    )
    monkeypatch.setattr(
        prov,
        "fetch_by_isbn",
        lambda units, **kw: {"1": {"title": "Tome 1", "summary": "Un résumé"}},
    )

    provider, index = prov.resolve_index("Berserk", [], library_type="Manga")

    assert provider == "MANGADEX+ISBN"
    assert index["1"] == {"cover_url": "c.jpg", "title": "Tome 1", "summary": "Un résumé"}


def test_the_series_index_keeps_the_upper_hand_field_by_field(monkeypatch):
    monkeypatch.setattr(
        prov,
        "fetch_index",
        lambda name, **kw: ("MANGADEX", {"1": {"cover_url": "de-mangadex.jpg"}}),
    )
    monkeypatch.setattr(
        prov, "fetch_by_isbn", lambda units, **kw: {"1": {"cover_url": "generique.jpg"}}
    )

    _provider, index = prov.resolve_index("Berserk", [], library_type="Manga")

    assert index["1"]["cover_url"] == "de-mangadex.jpg"


def test_a_full_index_does_not_pay_for_the_isbn_cascade(monkeypatch):
    """La cascade coûte un appel par tome : un index déjà complet ne doit pas la
    déclencher."""
    called = []
    monkeypatch.setattr(
        prov, "fetch_index", lambda name, **kw: ("COMICVINE", {"1": {"summary": "Un"}})
    )
    monkeypatch.setattr(prov, "fetch_by_isbn", lambda units, **kw: called.append(1) or {})

    provider, _index = prov.resolve_index("Saga", [], library_type="Comic")

    assert provider == "COMICVINE"
    assert called == []


def test_a_cancelled_pass_does_not_start_the_isbn_cascade(monkeypatch):
    called = []
    monkeypatch.setattr(prov, "fetch_index", lambda name, **kw: ("", {}))
    monkeypatch.setattr(prov, "fetch_by_isbn", lambda units, **kw: called.append(1) or {})

    prov.resolve_index("Saga", [], library_type="Manga", should_cancel=lambda: True)

    assert called == []


# --- Chemin expérimental : recherche par titre + numéro ---------------------


def _load_googlebooks():
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scrapers" / "googlebooks.py"
    spec = importlib.util.spec_from_file_location("scrapers.googlebooks_volume_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gb = _load_googlebooks()


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Berserk, Vol. 7", "7"),
        ("Naruto T7", "7"),
        ("Monster tome 7", "7"),
        ("One Piece #7", "7"),
        ("Berserk Volume 07", "7"),
        ("20th Century Boys", None),
        ("Akira 2020", None),
        ("Berserk", None),
    ],
)
def test_a_volume_number_is_only_read_where_it_is_announced(title, expected):
    """« 20th Century Boys » n'est pas le tome 20, et « Akira 2020 » n'est pas
    le tome 2020. Sans le mot-clé, ces deux titres écrasaient un vrai tome."""
    assert gb._volume_in_title(title) == expected


@pytest.mark.parametrize(
    "title, series, expected",
    [
        ("Berserk, Vol. 7", "Berserk", True),
        ("Bérserk, Vol. 7", "Berserk", True),
        ("BERSERK vol 7", "berserk", True),
        ("Berserker Grimoire, Vol. 7", "Berserk", False),
        ("Guide to Manga, Vol. 7", "Berserk", False),
    ],
)
def test_the_book_title_must_really_carry_the_series_name(title, series, expected):
    assert gb._title_matches_series(title, series) is expected


def _gb_scraper(monkeypatch, items):
    monkeypatch.setattr(gb, "load_config", lambda: {"GOOGLEBOOKS_API_KEY": "", "TARGET_LANG": "FR"})
    monkeypatch.setattr(gb, "clean_title", lambda q, library_type=None: q)
    monkeypatch.setattr(
        gb.requests, "get", lambda *a, **k: _Response({"items": items})
    )
    return gb.GoogleBooksScraper()


def test_the_right_volume_comes_back(monkeypatch):
    scraper = _gb_scraper(
        monkeypatch,
        [{"id": "x", "volumeInfo": {"title": "Berserk, Vol. 7", "description": "Un résumé"}}],
    )

    found = scraper.fetch_volume("Berserk", volume_number="7")

    assert found["summary"] == "Un résumé"


def test_another_series_volume_seven_is_refused(monkeypatch):
    """Le faux positif typique : Google rend un tome 7 du même éditeur."""
    scraper = _gb_scraper(
        monkeypatch,
        [{"id": "x", "volumeInfo": {"title": "Bleach, Vol. 7", "description": "Pas Berserk"}}],
    )

    assert scraper.fetch_volume("Berserk", volume_number="7") is None


def test_the_wrong_volume_of_the_right_series_is_refused(monkeypatch):
    """Google classe volontiers le tome 1 en tête, quel que soit le numéro
    demandé : l'accepter décalerait toute la série d'un cran."""
    scraper = _gb_scraper(
        monkeypatch,
        [{"id": "x", "volumeInfo": {"title": "Berserk, Vol. 1", "description": "Le premier"}}],
    )

    assert scraper.fetch_volume("Berserk", volume_number="7") is None


def test_an_artbook_without_a_number_is_refused(monkeypatch):
    scraper = _gb_scraper(
        monkeypatch,
        [{"id": "x", "volumeInfo": {"title": "Berserk Illustrations File", "description": "Artbook"}}],
    )

    assert scraper.fetch_volume("Berserk", volume_number="7") is None


def test_the_first_acceptable_result_wins_over_the_first_result(monkeypatch):
    scraper = _gb_scraper(
        monkeypatch,
        [
            {"id": "a", "volumeInfo": {"title": "Berserk Artbook", "description": "Non"}},
            {"id": "b", "volumeInfo": {"title": "Berserk, Vol. 7", "description": "Oui"}},
        ],
    )

    assert scraper.fetch_volume("Berserk", volume_number="7")["summary"] == "Oui"


@pytest.mark.parametrize("number", [None, "", "hors-série", 0, -3, "3.5"])
def test_a_number_that_is_not_a_volume_asks_nothing(monkeypatch, number):
    called = []
    monkeypatch.setattr(gb, "load_config", lambda: {"GOOGLEBOOKS_API_KEY": ""})
    monkeypatch.setattr(gb.requests, "get", lambda *a, **k: called.append(1))

    assert gb.GoogleBooksScraper().fetch_volume("Berserk", volume_number=number) is None
    assert called == []


def test_the_experimental_path_stays_shut_unless_asked(monkeypatch):
    called = []
    monkeypatch.setattr(prov, "fetch_index", lambda name, **kw: ("", {}))
    monkeypatch.setattr(prov, "fetch_by_isbn", lambda units, **kw: {})
    monkeypatch.setattr(
        prov, "fetch_by_title_volume", lambda *a, **k: called.append(1) or {}
    )

    provider, index = prov.resolve_index("Berserk", [], library_type="Manga")

    assert called == [], "une recherche sans identifiant ne se déclenche pas d'elle-même"
    assert (provider, index) == ("", {})


def test_the_experimental_path_completes_the_covers_when_asked(monkeypatch):
    monkeypatch.setattr(
        prov, "fetch_index", lambda name, **kw: ("MANGADEX", {"1": {"cover_url": "c.jpg"}})
    )
    monkeypatch.setattr(prov, "fetch_by_isbn", lambda units, **kw: {})
    monkeypatch.setattr(
        prov, "fetch_by_title_volume", lambda *a, **k: {"1": {"title": "Tome 1"}}
    )

    provider, index = prov.resolve_index(
        "Berserk", [], library_type="Manga", experimental=True
    )

    assert provider == "MANGADEX+TITRE"
    assert index["1"] == {"cover_url": "c.jpg", "title": "Tome 1"}


def test_an_isbn_result_makes_the_search_unnecessary(monkeypatch):
    """L'ISBN est un identifiant : quand il répond, la recherche par titre n'a
    plus lieu d'être, et son risque non plus."""
    called = []
    monkeypatch.setattr(prov, "fetch_index", lambda name, **kw: ("", {}))
    monkeypatch.setattr(prov, "fetch_by_isbn", lambda units, **kw: {"1": {"title": "Tome 1"}})
    monkeypatch.setattr(
        prov, "fetch_by_title_volume", lambda *a, **k: called.append(1) or {}
    )

    provider, _index = prov.resolve_index(
        "Berserk", [], library_type="Manga", experimental=True
    )

    assert provider == "ISBN"
    assert called == []
