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
        self.urls.append(url)
        for fragment, html in self.pages.items():
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
