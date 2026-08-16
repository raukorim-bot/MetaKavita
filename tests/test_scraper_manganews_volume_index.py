"""
Index des tomes VF chez Manga-News.

La fiche série porte `#serieVolumes` : numéro, couverture, lien. Le résumé,
l'ISBN et la date sont sur la fiche de chaque tome. Une requête pour la série,
une par tome, à 6 s — on ne visite pas le reste de la page, pleine de `/vol-`
qui appartiennent à d'autres mangas.
"""
from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scrapers" / "manganews.py"
    spec = importlib.util.spec_from_file_location("scrapers.manganews_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, text, status_code=200, url=""):
        self.text = text
        self.content = text.encode("utf-8") if isinstance(text, str) else text
        self.status_code = status_code
        self.url = url


class _Session:
    def __init__(self, pages, default=""):
        self.pages = pages
        self.default = default
        self.urls = []

    def get(self, url, headers=None, params=None, timeout=None, allow_redirects=None):
        label = url
        if params and params.get("q"):
            label = f"{url}?q={params['q']}"
        self.urls.append(label)
        if params and params.get("q") is not None:
            key = f"search:{params['q']}"
            if key in self.pages:
                return _Response(self.pages[key], 200, url)
        for fragment, html in self.pages.items():
            if fragment.startswith("search:"):
                continue
            if fragment in url:
                return _Response(html, 200, url)
        return _Response(self.default, 404 if self.default == "" else 200, url)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *_a, **_k: None)


def _stub(module, session):
    stub = types.ModuleType("curl_cffi.requests.stub")
    stub.__dict__.update(vars(module.requests))
    stub.Session = lambda *a, **k: session
    module.requests = stub


def _scraper(pages):
    module = _load()
    scraper = module.MangaNewsScraper()
    session = _Session(pages)
    _stub(module, session)
    return module, scraper, session


_SERIE = """
<html><body>
<h1 class="entry-page-title">Naruto</h1>
<div id="serieVolumes">
  <h2>Les volumes de la série</h2>
  <a class="title-all-link" href="https://www.manga-news.com/index.php/serie/editions/Naruto">Voir tous</a>
  <a href="https://www.manga-news.com/index.php/manga/Naruto/vol-1" title="Naruto Vol.1">
    <img alt="Naruto Vol.1" src="https://www.manga-news.com/public/images/vols/n1_medium.jpg"/>
  </a>
  <div class="selection">Vol.1</div>
  <a href="https://www.manga-news.com/index.php/manga/Naruto/vol-2" title="Naruto Vol.2">
    <img alt="Naruto Vol.2" src="/public/images/vols/n2_medium.jpg"/>
  </a>
  <a href="https://www.manga-news.com/index.php/manga/critique/Naruto/vol-1">critique, à ignorer</a>
  <a href="https://www.manga-news.com/index.php/manga/Bleach/vol-7" title="Bleach Vol.7">hors liste</a>
</div>
<a href="https://www.manga-news.com/index.php/manga/Bleach/vol-15">suggestion hors bloc</a>
</body></html>
"""

_TOME = """
<html><body>
<h1 class="entry-page-title">Naruto Vol.7The path to follow !!</h1>
<img class="entryPicture" src="https://www.manga-news.com/public/images/vols/n7_large.jpg"/>
<div id="summary"><div class="bigsize">Sakura reste seule pour lutter contre les ninjas d'Oto no Kuni.</div></div>
<li>EAN : 9782871295358</li>
<li>Date de publication : 05 Juillet 2003</li>
</body></html>
"""


def test_indexes_every_volume_of_the_block():
    _, scraper, _ = _scraper({
        "/index.php/serie/Naruto": _SERIE,
        "/manga/Naruto/vol-": _TOME,
    })

    index = scraper.fetch_volume_index(
        "Naruto", series_id="https://www.manga-news.com/index.php/serie/Naruto"
    )

    assert sorted(index) == ["1", "2"]
    assert index["1"]["title"] == "The path to follow !!"
    assert index["1"]["summary"].startswith("Sakura reste seule")
    assert index["1"]["isbn"] == "9782871295358"
    assert index["1"]["release_date"] == "2003-07-05"
    assert index["1"]["provider_ref"].endswith("/vol-1")


def test_ignores_vol_links_outside_the_block():
    """La page série est pleine de `/vol-` (critiques, suggestions) : les
    suivre écrirait Bleach 15 sur Naruto."""
    _, scraper, session = _scraper({
        "/index.php/serie/Naruto": _SERIE,
        "/manga/Naruto/vol-": _TOME,
        "/manga/Bleach/vol-": "<html><h1>Bleach</h1></html>",
    })

    scraper.fetch_volume_index(
        "Naruto", series_id="https://www.manga-news.com/index.php/serie/Naruto"
    )

    assert not any("Bleach" in url for url in session.urls)


def test_turns_a_thumbnail_into_a_full_cover():
    _, scraper, _ = _scraper({
        "/index.php/serie/Naruto": _SERIE,
        "/manga/Naruto/vol-": _TOME,
    })

    index = scraper.fetch_volume_index(
        "Naruto", series_id="https://www.manga-news.com/index.php/serie/Naruto"
    )

    assert "_large.jpg" in index["1"]["cover_url"]
    assert "_medium" not in index["1"]["cover_url"]


def test_fetch_by_id_rewrites_a_volume_url_to_the_series():
    """Même URL collée pour l'enrichissement par série : pas la page du tome."""
    _, scraper, session = _scraper({
        "/index.php/serie/Naruto": _SERIE,
        "/manga/Naruto/vol-": _TOME,
    })

    scraper.fetch(
        "https://www.manga-news.com/index.php/manga/Naruto/vol-7",
        is_id=True,
    )

    assert any("/index.php/serie/Naruto" in url for url in session.urls)
    assert not any(url.rstrip("/").endswith("/vol-7") for url in session.urls)


def test_a_volume_url_as_id_still_opens_the_series():
    """Le Champ Magique peut coller l'URL d'un tome : on remonte à la série."""
    _, scraper, session = _scraper({
        "/index.php/serie/Naruto": _SERIE,
        "/manga/Naruto/vol-": _TOME,
    })

    scraper.fetch_volume_index(
        "Naruto",
        series_id="https://www.manga-news.com/index.php/manga/Naruto/vol-7",
    )

    assert any("/index.php/serie/Naruto" in url for url in session.urls)


def test_stops_at_the_ceiling():
    rows = "".join(
        f'<a href="https://www.manga-news.com/index.php/manga/Naruto/vol-{n}" '
        f'title="Naruto Vol.{n}"><img src="x.jpg"/></a>'
        for n in range(1, 55)
    )
    serie = f'<html><body><div id="serieVolumes">{rows}</div></body></html>'
    _, scraper, session = _scraper({
        "/index.php/serie/Naruto": serie,
        "/manga/Naruto/vol-": _TOME,
    })

    index = scraper.fetch_volume_index(
        "Naruto", series_id="https://www.manga-news.com/index.php/serie/Naruto"
    )

    assert len(index) == scraper.VOLUME_INDEX_MAX
    tome_calls = [u for u in session.urls if "/vol-" in u]
    assert len(tome_calls) == scraper.VOLUME_INDEX_MAX


def test_unknown_series_returns_none():
    _, scraper, _ = _scraper({})

    assert scraper.fetch_volume_index("Série inexistante") is None


def test_cadence_is_wide_enough():
    """Six secondes, pas 2,5 : une page par tome, derrière Cloudflare."""
    _, scraper, _ = _scraper({})
    assert scraper.rate_limit >= 6.0
    assert scraper.VOLUME_INDEX_MAX <= 40


def test_french_publication_date_and_subtitle():
    """Ce que la fiche live porte : '05 Juillet 2003', titre collé au Vol.N."""
    _, scraper, _ = _scraper({})
    assert scraper._volume_release_date("Date de publication : 05 Juillet 2003") == "2003-07-05"
    assert scraper._volume_isbn("EAN : 9782871295358 Code prix") == "9782871295358"
    assert scraper._volume_title("Naruto Vol.7La voie a suivre !!") == "La voie a suivre !!"


_DEMON = """
<html><body>
<h1 class="entry-page-title">Demon Slayer</h1>
<div id="serieVolumes">
  <a href="https://www.manga-news.com/index.php/manga/Demon-Slayer/vol-1" title="Demon Slayer Vol.1">
    <img src="https://www.manga-news.com/public/images/vols/ds1_medium.jpg"/>
  </a>
  <a href="https://www.manga-news.com/index.php/manga/Demon-slayer/vol-4" title="Demon Slayer Vol.4">
    <img src="https://www.manga-news.com/public/images/vols/ds4_medium.jpg"/>
  </a>
  <a href="https://www.manga-news.com/index.php/manga/Bleach/vol-7" title="Bleach Vol.7">hors liste</a>
</div>
</body></html>
"""

_FRIEREN = """
<html><body>
<div id="serieVolumes">
  <a href="https://www.manga-news.com/index.php/manga/Frieren/vol-1" title="Frieren Vol.1">
    <img src="x.jpg"/>
  </a>
</div>
</body></html>
"""

_HELLSING_SERIE = """
<html><body>
<h1 class="entry-page-title">Hellsing</h1>
<a class="title-all-link" href="https://www.manga-news.com/index.php/serie/editions/Hellsing">Voir tous</a>
<a href="https://www.manga-news.com/index.php/manga/critique/Love-of-Kill/vol-13">hors bloc</a>
</body></html>
"""

_HELLSING_EDITIONS = """
<html><body>
<div id="serieVolumes">
  <a href="https://www.manga-news.com/index.php/manga/Hellsing/vol-1" title="Hellsing Vol.1">
    <img alt="Hellsing Vol.1" src="https://www.manga-news.com/public/images/vols/h1_medium.jpg"/>
  </a>
  <a href="https://www.manga-news.com/index.php/manga/Hellsing/vol-2" title="Hellsing Vol.2">
    <img alt="Hellsing Vol.2" src="https://www.manga-news.com/public/images/vols/h2_medium.jpg"/>
  </a>
</div>
</body></html>
"""


def test_indexes_when_volume_slug_differs_from_serie():
    """Fiche VF `Rodeurs-de-la-nuit-les`, tomes EN `Demon-Slayer`."""
    _, scraper, session = _scraper({
        "/index.php/serie/Rodeurs-de-la-nuit-les": _DEMON,
        "/manga/Demon-Slayer/vol-": _TOME,
        "/manga/Demon-slayer/vol-": _TOME,
        "/manga/Bleach/vol-": "<html><h1>Bleach</h1></html>",
    })

    index = scraper.fetch_volume_index(
        "Demon Slayer",
        series_id="https://www.manga-news.com/index.php/serie/Rodeurs-de-la-nuit-les",
    )

    assert sorted(index) == ["1", "4"]
    assert not any("Bleach" in url for url in session.urls)


def test_indexes_when_serie_slug_has_trailing_junk():
    """`/serie/Frieren-:` vs `/manga/Frieren/vol-1`."""
    _, scraper, _ = _scraper({
        "/index.php/serie/Frieren-:": _FRIEREN,
        "/manga/Frieren/vol-": _TOME,
    })

    index = scraper.fetch_volume_index(
        "Frieren",
        series_id="https://www.manga-news.com/index.php/serie/Frieren-:",
    )

    assert list(index) == ["1"]


def test_follows_editions_page_when_bandeau_is_missing():
    """Hellsing : pas de `#serieVolumes` sur la fiche, tout est sous /editions/."""
    _, scraper, session = _scraper({
        "/index.php/serie/Hellsing": _HELLSING_SERIE,
        "/index.php/serie/editions/Hellsing": _HELLSING_EDITIONS,
        "/manga/Hellsing/vol-": _TOME,
    })

    index = scraper.fetch_volume_index(
        "Hellsing",
        series_id="https://www.manga-news.com/index.php/serie/Hellsing",
    )

    assert sorted(index) == ["1", "2"]
    assert any("/serie/editions/Hellsing" in url for url in session.urls)
    assert not any("Love-of-Kill" in url for url in session.urls)


def test_searches_vf_alias_when_english_title_misses():
    fiche = """
    <html><body>
    <h1 class="entry-page-title">Gloutons et Dragons</h1>
    <h2 class="entry-page-title-trad">Delicious in Dungeon</h2>
    <div id="summary"><div class="bigsize">Laios et son groupe explorent un donjon infesté de monstres comestibles.</div></div>
    <img class="entryPicture" src="https://www.manga-news.com/x.jpg"/>
    </body></html>
    """
    _, scraper, session = _scraper({
        "search:Delicious in Dungeon": "<html><body><p>aucun</p></body></html>",
        "search:Gloutons et Dragons": (
            '<html><body>'
            '<a href="/index.php/serie/Gloutons-et-Dragons">Gloutons et Dragons</a>'
            "</body></html>"
        ),
        "/index.php/serie/Gloutons-et-Dragons": fiche,
    })

    found = scraper.fetch("Delicious in Dungeon")

    assert found is not None
    assert found["title"] == "Gloutons et Dragons"
    assert any("Gloutons" in url for url in session.urls)


def test_norm_slug_strips_trailing_junk():
    _, scraper, _ = _scraper({})
    assert scraper._norm_slug("Frieren-:") == "frieren"
    assert scraper._slugs_compatible("Frieren-:", "Frieren")
    assert not scraper._slugs_compatible("Rodeurs-de-la-nuit-les", "Demon-Slayer")
