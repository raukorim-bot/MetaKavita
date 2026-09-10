"""
Index des albums chez les deux fournisseurs BD.

Bédéthèque et Planète BD n'ont pas d'API : chaque album coûte une page HTML à
deux secondes de cadence. Ce qui se teste ici n'est donc pas seulement le
parsing, mais le nombre de pages demandées — un index qui visite trois cents
albums pour une série de dix mettrait un quart d'heure et finirait banni.

Les modules sont chargés depuis `scrapers/` (image du dépôt) plutôt que par
`import scrapers.xxx`, qui renvoie la copie installée dans `data/scrapers/`.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    path = ROOT / "scrapers" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"scrapers.{name}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, text, status_code=200, url=""):
        self.text = text
        self.status_code = status_code
        self.url = url


class _Session:
    """Session qui sert des pages depuis une table URL → HTML."""

    def __init__(self, pages, default=""):
        self.pages = pages
        self.default = default
        self.urls = []
        self.headers = {}

    def get(self, url, headers=None, params=None, timeout=None, allow_redirects=None):
        self.urls.append(url)
        for fragment, html in self.pages.items():
            if fragment in url:
                return _Response(html, 200, url)
        return _Response(self.default, 404 if self.default == "" else 200, url)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Sans cela, un index de dix albums prendrait vingt secondes de test."""
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *_a, **_k: None)


# ===== Bédéthèque =====

_BD_SERIE = """
<html><body><h1>Thorgal</h1>
<ul class="liste-albums">
  <li><a href="/BD-Thorgal-Tome-1-album-1.html">1. La Magicienne trahie</a></li>
  <li><a href="/BD-Thorgal-Tome-2-album-2.html">2. L'Île des mers gelées</a></li>
  <li><a href="/BD-Thorgal-Tome-3-album-3.html">3. Les Trois Vieillards</a></li>
</ul>
<div class="autre-liste"><a href="/album-999.html">Hors liste, ne doit pas compter</a></div>
</body></html>
"""

_BD_ALBUM = """
<html><body><h1>Thorgal - 1. La Magicienne trahie</h1>
<img class="couv" src="/cache/thb_couv/Thorgal1.jpg">
<div class="synopsis">Thorgal Aegirsson est jugé par le roi des Vikings. 1980 fut l'année.</div>
</body></html>
"""


def _stub_sessions(module, session):
    """Remplace `requests` DANS le module sous test, pas dans `curl_cffi`.

    `module.requests` est le paquet `curl_cffi.requests` lui-même, partagé par
    tout le processus : lui affecter `Session` contaminait la suite entière et
    les tests suivants recevaient sans le savoir la session bouchonnée d'ici.
    Le module sous test, lui, est une copie jetable chargée par `_load()`.
    """
    stub = types.ModuleType("curl_cffi.requests.stub")
    stub.__dict__.update(vars(module.requests))
    stub.Session = lambda *a, **k: session
    module.requests = stub


def _bedetheque(pages):
    module = _load("bedetheque")
    scraper = module.BedethequeScraper()
    session = _Session(pages)
    _stub_sessions(module, session)
    return module, scraper, session


def test_bedetheque_indexes_every_album_of_the_list():
    _, scraper, _ = _bedetheque(
        {"/serie-33-BD-Thorgal.html": _BD_SERIE, "album-": _BD_ALBUM}
    )

    index = scraper.fetch_volume_index(
        "Thorgal", series_id="https://www.bedetheque.com/serie-33-BD-Thorgal.html"
    )

    assert sorted(index) == ["1", "2", "3"]
    assert index["1"]["summary"].startswith("Thorgal Aegirsson")
    assert index["2"]["provider_ref"].endswith("album-2.html")


def test_bedetheque_only_reads_the_album_list():
    """Une fiche série porte des dizaines de liens `/album-` hors liste (albums
    voisins, publicités) : les suivre multiplierait le coût par dix."""
    _, scraper, session = _bedetheque(
        {"/serie-33-BD-Thorgal.html": _BD_SERIE, "album-": _BD_ALBUM}
    )

    scraper.fetch_volume_index(
        "Thorgal", series_id="https://www.bedetheque.com/serie-33-BD-Thorgal.html"
    )

    assert not any("album-999" in url for url in session.urls)


def test_bedetheque_turns_a_thumbnail_into_a_full_cover():
    """L'URL de vignette rend une image de 100 px : la poser en couverture de
    tome donnerait un mur d'imagettes floues dans Kavita."""
    _, scraper, _ = _bedetheque(
        {"/serie-33-BD-Thorgal.html": _BD_SERIE, "album-": _BD_ALBUM}
    )

    index = scraper.fetch_volume_index(
        "Thorgal", series_id="https://www.bedetheque.com/serie-33-BD-Thorgal.html"
    )

    cover = index["1"]["cover_url"]
    assert "/media/Couvertures/" in cover
    assert "thb_couv" not in cover
    assert cover.startswith("https://")


def test_bedetheque_stops_at_the_ceiling():
    """Plafond à cinquante albums : au-delà, l'index dépasserait deux minutes."""
    rows = "".join(
        f'<li><a href="/BD-Thorgal-album-{n}.html">{n}. Album {n}</a></li>'
        for n in range(1, 121)
    )
    _, scraper, session = _bedetheque(
        {
            "/serie-33.html": f'<html><body><ul class="liste-albums">{rows}</ul></body></html>',
            "album-": _BD_ALBUM,
        }
    )

    index = scraper.fetch_volume_index(
        "Thorgal", series_id="https://www.bedetheque.com/serie-33.html"
    )

    assert len(index) == scraper.VOLUME_INDEX_MAX


def test_bedetheque_only_fetches_the_wanted_albums():
    """Douze albums possédés parmi quatre-vingts listés : douze GET, pas cinquante."""
    rows = "".join(
        f'<li><a href="/BD-Thorgal-album-{n}.html">{n}. Album {n}</a></li>'
        for n in range(1, 81)
    )
    _, scraper, session = _bedetheque(
        {
            "/serie-33.html": f'<html><body><ul class="liste-albums">{rows}</ul></body></html>',
            "album-": _BD_ALBUM,
        }
    )
    wanted = {str(n) for n in (3, 7, 12, 19, 22, 28, 33, 41, 50, 55, 61, 77)}

    index = scraper.fetch_volume_index(
        "Thorgal",
        series_id="https://www.bedetheque.com/serie-33.html",
        wanted_numbers=wanted,
    )

    album_calls = [u for u in session.urls if "album-" in u]
    assert len(album_calls) == 12
    assert sorted(index) == sorted(wanted)


def test_bedetheque_cancel_returns_the_partial_index():
    rows = "".join(
        f'<li><a href="/BD-Thorgal-album-{n}.html">{n}. Album {n}</a></li>'
        for n in range(1, 8)
    )
    _, scraper, session = _bedetheque(
        {
            "/serie-33.html": f'<html><body><ul class="liste-albums">{rows}</ul></body></html>',
            "album-": _BD_ALBUM,
        }
    )
    n = {"i": 0}

    def should_cancel():
        n["i"] += 1
        return n["i"] > 2

    index = scraper.fetch_volume_index(
        "Thorgal",
        series_id="https://www.bedetheque.com/serie-33.html",
        should_cancel=should_cancel,
    )

    album_calls = [u for u in session.urls if "album-" in u]
    assert len(album_calls) == 2
    assert index is not None
    assert len(index) == 2


def test_bedetheque_reads_the_album_isbn():
    """og:isbn (ou un EAN annoncé) débloque la cascade ISBN des one-shots BD."""
    album = """
    <html><head><meta property="og:isbn" content="978-2-205-07018-7"></head>
    <body><h1>Thorgal - 1. La Magicienne trahie</h1>
    <img class="couv" src="/cache/thb_couv/Thorgal1.jpg">
    <div class="synopsis">Thorgal Aegirsson est jugé par le roi des Vikings. 1980 fut l'année.</div>
    </body></html>
    """
    _, scraper, _ = _bedetheque(
        {"/serie-33-BD-Thorgal.html": _BD_SERIE, "album-": album}
    )

    index = scraper.fetch_volume_index(
        "Thorgal", series_id="https://www.bedetheque.com/serie-33-BD-Thorgal.html"
    )

    assert index["1"]["isbn"] == "9782205070187"


@pytest.mark.parametrize(
    "label,expected",
    [
        ("1. La Magicienne trahie", "1"),
        ("12. Le Pays Qâ", "12"),
        ("T7 - L'Enfant des étoiles", "7"),
        ("Tome 4 : La Galère noire", "4"),
        ("HS. Kriss de Valnor", None),
        ("Intégrale", None),
        # Hors-série intercalaires : la décimale fait partie du numéro.
        ("1.5. Hors-série", "1.5"),
        ("3,5 - Le Serment", "3.5"),
        ("T1.5 : L'histoire d'avant", "1.5"),
        ("Tome 2.5 : Interlude", "2.5"),
    ],
)
def test_bedetheque_reads_the_album_number(label, expected):
    module = _load("bedetheque")

    assert module.BedethequeScraper._album_number(label) == expected


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Lanfeust de Troy T1 : L'ivoire du Magohamoth", "1"),
        ("Astérix T41", "41"),
        ("T1.5 : Hors-série", "1.5"),
        ("T3,5 : Interlude", "3.5"),
        ("2. Thanos l'incongru", "2"),
        ("Un récit complet", None),
    ],
)
def test_planetebd_reads_the_album_number(label, expected):
    module = _load("planetebd")

    assert module._album_number(label) == expected


def test_a_bd_album_number_lines_up_with_what_kavita_sends():
    """Les deux parseurs et l'appariement doivent s'accorder au caractère près.

    L'index est comparé à des numéros venus de Kavita, où le tome 1.5 arrive en
    `1.5` (float). Un parseur qui rendrait « 1,5 » ou « 1.50 » produirait une
    clé qui ne s'apparie à rien, et le tome resterait muet sans erreur.
    """
    from scrapers.utils import album_number_key
    from services.volume_enrichment.matching import number_key

    for raw in ("1", "01", "1.0", "1,5", "1.5", "1.50", "41", 3, 3.5):
        assert album_number_key(raw) == number_key(raw), f"désaccord sur {raw!r}"


@pytest.mark.parametrize("raw", [None, "", "  ", "hors-série", "T", True])
def test_a_label_without_a_number_has_no_key(raw):
    from scrapers.utils import album_number_key

    assert album_number_key(raw) is None


_BD_SERIE_WITH_HS = """
<html><body><h1>Thorgal</h1>
<ul class="liste-albums">
  <li><a href="/BD-Thorgal-HS-album-15.html">1.5. Hors-série : Kriss de Valnor</a></li>
  <li><a href="/BD-Thorgal-Tome-1-album-1.html">1. La Magicienne trahie</a></li>
</ul>
</body></html>
"""

_BD_HS_ALBUM = """
<html><body><h1>Thorgal - Hors-série</h1>
<div class="synopsis">Un récit parallèle, qui n'est pas le premier tome.</div>
</body></html>
"""


def test_bedetheque_does_not_let_a_half_volume_steal_the_first_one():
    """Le hors-série 1.5 arrive avant le tome 1 dans la liste, et la boucle
    d'index garde la première entrée d'une clé. La décimale tronquée les
    ramenait tous deux sur « 1 » : le vrai tome 1 repartait avec le résumé et la
    couverture du hors-série, sans un mot à l'écran."""
    _, scraper, _ = _bedetheque(
        {
            "/serie-33-BD-Thorgal.html": _BD_SERIE_WITH_HS,
            "album-15.html": _BD_HS_ALBUM,
            "album-1.html": _BD_ALBUM,
        }
    )

    index = scraper.fetch_volume_index(
        "Thorgal", series_id="https://www.bedetheque.com/serie-33-BD-Thorgal.html"
    )

    assert sorted(index) == ["1", "1.5"]
    assert index["1"]["summary"].startswith("Thorgal Aegirsson")
    assert index["1.5"]["summary"].startswith("Un récit parallèle")
    assert index["1.5"]["title"] == "Hors-série : Kriss de Valnor"


def test_a_decimal_volume_reaches_its_own_kavita_chapter():
    """De bout en bout : ce que le parseur produit doit atteindre le tome 1.5 de
    Kavita, et lui seul."""
    from services.volume_enrichment.matching import units_from_volumes
    from services.volume_enrichment.plan import build_plan

    volumes = [
        {"id": 10, "minNumber": 1, "chapters": [{"id": 100, "minNumber": 1}]},
        {"id": 11, "minNumber": 1.5, "chapters": [{"id": 150, "minNumber": 1}]},
    ]
    index = {
        "1": {"summary": "Le premier tome"},
        "1.5": {"summary": "Le hors-série"},
    }

    plan = build_plan(units_from_volumes(volumes), index, provider="BEDETHEQUE")

    written = {
        entry["chapter_id"]: entry["changes"]["summary"]["proposed"]
        for entry in plan["units"]
    }
    assert written == {100: "Le premier tome", 150: "Le hors-série"}
    assert plan["counts"]["unmatched"] == 0


def test_bedetheque_does_not_invent_a_release_date():
    """La date était prise sur la première suite de quatre chiffres de la page.
    Ici, c'est « 1980 » au milieu du synopsis — et il partait chez Kavita,
    verrouillé, comme date de parution de l'album."""
    _, scraper, _ = _bedetheque(
        {"/serie-33-BD-Thorgal.html": _BD_SERIE, "album-": _BD_ALBUM}
    )

    index = scraper.fetch_volume_index(
        "Thorgal", series_id="https://www.bedetheque.com/serie-33-BD-Thorgal.html"
    )

    assert "release_date" not in index["1"]


@pytest.mark.parametrize(
    "html, expected",
    [
        ('<meta itemprop="datePublished" content="2019-05-07">', "2019-05-07"),
        ('<li><label>Dépot légal :</label> 09/2023 (Parution)</li>', "2023-09"),
        ('<li><label>Dépot légal :</label> 15/09/2023</li>', "2023-09-15"),
        ('<li><label>Dépot légal :</label> 1980</li>', "1980"),
        ('<li><label>Estimation :</label> 1980</li>', ""),
        ('<p>Né en 1954, il publie depuis 1977.</p>', ""),
    ],
)
def test_bedetheque_only_reads_a_date_where_one_is_announced(html, expected):
    from bs4 import BeautifulSoup

    module = _load("bedetheque")
    soup = BeautifulSoup(f"<html><body>{html}</body></html>", "html.parser")

    assert module.BedethequeScraper._album_release_date(soup) == expected


def test_bedetheque_drops_the_rank_prefix_from_the_title():
    """Kavita affiche déjà le numéro du tome : « 1. La Magicienne trahie » le
    doublerait à l'écran."""
    _, scraper, _ = _bedetheque(
        {"/serie-33-BD-Thorgal.html": _BD_SERIE, "album-": _BD_ALBUM}
    )

    index = scraper.fetch_volume_index(
        "Thorgal", series_id="https://www.bedetheque.com/serie-33-BD-Thorgal.html"
    )

    assert index["1"]["title"] == "La Magicienne trahie"


def test_bedetheque_gives_up_quietly_without_a_series_page():
    """Série inconnue : rendre None, pas lever — l'orchestrateur passe au
    fournisseur suivant."""
    _, scraper, _ = _bedetheque({})

    assert scraper.fetch_volume_index("Série qui n'existe pas") is None


def test_bedetheque_declares_the_volume_scope():
    module = _load("bedetheque")

    assert "volume" in module.BedethequeScraper.scopes


# ===== Planète BD =====

_PBD_SERIE = """
<html><body><h1>Lanfeust de Troy</h1>
<a href="/bd/soleil/lanfeust-de-troy/lironde-de-lumiere/101.html">Lanfeust de Troy T1 : L'ivoire du Magohamoth</a>
<a href="/bd/soleil/lanfeust-de-troy/thanos-lincongru/102.html">Lanfeust de Troy T2 : Thanos l'incongru</a>
<a href="/bd/soleil/lanfeust-de-troy/lironde-de-lumiere/101.html">doublon</a>
<a href="/bd/series/lanfeust-de-troy/9.html">La série</a>
</body></html>
"""

_PBD_ALBUM = """
<html><head>
<title>Lanfeust de Troy T1 bd chez Soleil de Arleston, Tarquin</title>
<meta property="og:title" content="L'ivoire du Magohamoth">
<meta property="og:description" content="Lanfeust découvre son pouvoir absolu.">
<meta property="og:image" content="https://static.planetebd.com/couv/101.jpg">
<meta property="og:isbn" content="978-2-87764-566-1">
<meta itemprop="datePublished" content="1994-11-01">
</head><body><h1>L'ivoire du Magohamoth</h1></body></html>
"""


def _planetebd(pages):
    module = _load("planetebd")
    scraper = module.PlanetebdScraper()
    session = _Session(pages)
    _stub_sessions(module, session)
    return module, scraper, session


def test_planetebd_indexes_each_album_once():
    """`_first_album_from_series` s'arrêtait au premier lien ; la page en porte
    plusieurs, parfois deux fois le même."""
    _, scraper, _ = _planetebd(
        {"/bd/series/": _PBD_SERIE, "/lanfeust-de-troy/": _PBD_ALBUM}
    )

    index = scraper.fetch_volume_index(
        "Lanfeust de Troy",
        series_id="https://www.planetebd.com/bd/series/lanfeust-de-troy/9.html",
    )

    assert sorted(index) == ["1", "2"]
    assert index["1"]["isbn"] == "9782877645661"
    assert index["1"]["cover_url"].endswith("101.jpg")
    assert index["1"]["release_date"] == "1994"


def test_planetebd_skips_albums_without_a_number():
    """Un album sans numéro apparié au hasard écrirait les métadonnées d'un
    hors-série sur le tome 1."""
    page = (
        '<html><body>'
        '<a href="/bd/soleil/serie/un-recit-complet/500.html">Un récit complet</a>'
        '</body></html>'
    )
    _, scraper, session = _planetebd({"/bd/series/": page, "/500.html": _PBD_ALBUM})

    index = scraper.fetch_volume_index(
        "Série", series_id="https://www.planetebd.com/bd/series/serie/9.html"
    )

    assert index is None
    assert not any("/500.html" in url for url in session.urls)


def test_planetebd_ignores_the_albums_of_the_neighbouring_series():
    """Une fiche Planète BD porte des blocs « à lire aussi » sous la même forme
    d'URL. Un de ces liens dont le libellé contient « T2 » prenait la place du
    vrai tome 2, et l'utilisateur recevait le résumé et la couverture d'une
    autre série — écrits, verrouillés, sans un mot à l'écran."""
    page = (
        '<html><body>'
        '<a href="/bd/soleil/lanfeust-de-troy/tome-un/101.html">Lanfeust de Troy T1</a>'
        '<a href="/bd/soleil/lanfeust-de-troy/tome-deux/102.html">Lanfeust de Troy T2</a>'
        '<a href="/bd/glenat/trolls-de-troy/autre-tome/900.html">Trolls de Troy T2</a>'
        '</body></html>'
    )
    _, scraper, session = _planetebd({"/bd/series/": page, ".html": _PBD_ALBUM})

    scraper.fetch_volume_index(
        "Lanfeust de Troy",
        series_id="https://www.planetebd.com/bd/series/lanfeust-de-troy/9.html",
    )

    assert not any("/900.html" in url for url in session.urls)


def test_planetebd_keeps_its_albums_when_the_slug_does_not_line_up():
    """Atteinte par identifiant forcé, la page série ne porte pas toujours son
    vrai slug. Le filtre retombe alors sur le groupe le plus nombreux : une
    fiche série est faite de ses propres albums, les blocs voisins n'en
    apportent qu'un ou deux."""
    module = _load("planetebd")

    albums = module._same_series_only(
        [
            {"url": "a", "series": "lanfeust-de-troy"},
            {"url": "b", "series": "lanfeust-de-troy"},
            {"url": "c", "series": "trolls-de-troy"},
        ],
        series_slug="",
    )

    assert [a["url"] for a in albums] == ["a", "b"]


def test_planetebd_paces_itself_between_albums(monkeypatch):
    """Une page par album, cinquante albums possibles, aucune API : sans
    cadence, c'est cinquante requêtes en rafale sur un site qui bannit à vue.

    La pause ne vient plus d'un `time.sleep` du scraper mais de
    `throttle_provider`, appelé par `_http_get` : c'est donc son horloge qu'on
    observe. La page série compte comme requête, d'où une pause de moins que le
    nombre total d'appels."""
    from services import provider_throttle

    _, scraper, session = _planetebd(
        {"/bd/series/": _PBD_SERIE, "/lanfeust-de-troy/": _PBD_ALBUM}
    )
    naps = []
    now = [1_000.0]

    def fake_sleep(seconds):
        naps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(
        provider_throttle,
        "time",
        types.SimpleNamespace(time=lambda: now[0], sleep=fake_sleep),
    )

    scraper.fetch_volume_index(
        "Lanfeust de Troy",
        series_id="https://www.planetebd.com/bd/series/lanfeust-de-troy/9.html",
    )

    assert len(naps) == len(session.urls) - 1, "une pause avant chaque requête sauf la première"
    assert naps, "deux pages d'album au moins doivent être demandées"
    assert all(nap >= scraper.rate_limit for nap in naps)


def test_planetebd_declares_the_volume_scope():
    module = _load("planetebd")

    assert "volume" in module.PlanetebdScraper.scopes


def test_planetebd_gives_up_quietly_without_a_series_page():
    _, scraper, _ = _planetebd({})

    assert scraper.fetch_volume_index("Inconnue") is None


def test_planetebd_only_fetches_the_wanted_albums():
    rows = "".join(
        f'<a href="/bd/soleil/lanfeust-de-troy/album-{n}/{n}.html">'
        f'Lanfeust de Troy T{n}</a>'
        for n in range(1, 81)
    )
    page = f"<html><body>{rows}</body></html>"
    _, scraper, session = _planetebd({"/bd/series/": page, "/lanfeust-de-troy/": _PBD_ALBUM})
    wanted = {str(n) for n in (3, 7, 12, 19, 22, 28, 33, 41, 50, 55, 61, 77)}

    index = scraper.fetch_volume_index(
        "Lanfeust de Troy",
        series_id="https://www.planetebd.com/bd/series/lanfeust-de-troy/9.html",
        wanted_numbers=wanted,
    )

    album_calls = [u for u in session.urls if "/album-" in u]
    assert len(album_calls) == 12
    assert sorted(index) == sorted(wanted)


def test_planetebd_cancel_returns_the_partial_index():
    rows = "".join(
        f'<a href="/bd/soleil/lanfeust-de-troy/album-{n}/{n}.html">'
        f'Lanfeust de Troy T{n}</a>'
        for n in range(1, 8)
    )
    page = f"<html><body>{rows}</body></html>"
    _, scraper, session = _planetebd({"/bd/series/": page, "/lanfeust-de-troy/": _PBD_ALBUM})
    n = {"i": 0}

    def should_cancel():
        n["i"] += 1
        return n["i"] > 2

    index = scraper.fetch_volume_index(
        "Lanfeust de Troy",
        series_id="https://www.planetebd.com/bd/series/lanfeust-de-troy/9.html",
        should_cancel=should_cancel,
    )

    album_calls = [u for u in session.urls if "/album-" in u]
    assert len(album_calls) == 2
    assert index is not None
    assert len(index) == 2


# ===== Chemin ISBN =====


def test_the_isbn_cascade_targets_providers_that_accept_one():
    """Interroger un fournisseur qui ignore `existing_metadata['isbn']` reviendrait
    à chercher « 9782877645661 » comme un titre."""
    from services.volume_enrichment.providers import ISBN_PROVIDERS

    for name in ("googlebooks", "openlibrary", "hardcover"):
        source = (ROOT / "scrapers" / f"{name}.py").read_text(encoding="utf-8")
        assert "existing_metadata" in source and "isbn" in source.lower()

    assert set(ISBN_PROVIDERS) == {
        "GOOGLEBOOKS", "OPENLIBRARY", "HARDCOVER", "OPENBD"
    }
    fixture = (ROOT / "tests" / "fixtures" / "scrapers" / "openbd.py").read_text(
        encoding="utf-8"
    )
    assert "existing_metadata" in fixture and "isbn" in fixture.lower()
