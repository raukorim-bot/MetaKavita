"""
La cadence `rate_limit` doit s'appliquer à CHAQUE requête d'un `fetch()`.

`throttle_provider()` était appelé une seule fois, par l'appelant, AVANT
`scraper.fetch(...)` : les six à vingt-cinq requêtes émises À L'INTÉRIEUR du
`fetch()` échappaient donc au compteur. Mesuré avant correctif : un seul
`fetch()` Planète BD émettait 25 requêtes instantanées pour un `rate_limit`
déclaré de 2,5 s (dont 8 fois la même page), et Bédéthèque espaçait ses pages
d'un `time.sleep(1.0)` en dur pour un `rate_limit` de 2,0 s. C'est le profil de
trafic qui fait bannir une IP ou déclencher un 403 Cloudflare sur des sites sans
API — après quoi l'utilisateur voit « aucun résultat » chez tous ses
fournisseurs français sans savoir qu'il est bloqué.

Ces tests comptent les requêtes et mesurent les intervalles sur une **horloge
simulée** : dormir pour de vrai coûterait une minute par test, et l'horloge
simulée mesure exactement ce qui nous intéresse — la décision d'attendre, pas la
capacité de l'OS à dormir.

Les modules sont chargés depuis `scrapers/` (image du dépôt) et non par
`import scrapers.xxx`, qui renvoie la copie installée dans `data/scrapers/` —
même précaution que `tests/test_scraper_bedetheque_http.py`.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

from services import provider_throttle

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    path = ROOT / "scrapers" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"scrapers.{name}_cadence_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Clock:
    """Horloge simulée : `sleep()` avance le temps au lieu de le laisser passer.

    C'est ce qui permet d'affirmer « ces deux requêtes sont espacées de 2,5 s »
    sans immobiliser la suite pendant une minute.
    """

    def __init__(self, start: float = 1_000.0):
        self.now = float(start)
        self.naps: list = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds) -> None:
        seconds = max(0.0, float(seconds))
        self.naps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    """Remplace l'horloge de `provider_throttle`, la seule qui décide d'attendre."""
    simulated = Clock()
    monkeypatch.setattr(provider_throttle, "time", simulated)
    return simulated


class Response:
    def __init__(self, text="", status_code=200, url=""):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.url = url
        self.headers = {}


class RecordingSession:
    """Session qui note l'instant simulé de chaque requête."""

    def __init__(self, pages, clock, default_status=404):
        self.pages = pages
        self.clock = clock
        self.default_status = default_status
        self.calls: list = []  # [(instant, url), ...]
        self.headers = {}

    def get(self, url, headers=None, params=None, timeout=None, allow_redirects=None):
        self.calls.append((self.clock.time(), url))
        for fragment, html in self.pages.items():
            if fragment in url:
                return Response(html, 200, url)
        return Response("", self.default_status, url)

    def close(self):
        pass

    @property
    def urls(self):
        return [url for _instant, url in self.calls]

    def intervals(self):
        instants = [instant for instant, _url in self.calls]
        return [later - earlier for earlier, later in zip(instants, instants[1:])]


# ===== Le point de passage partagé =====


class _Fake:
    """Le strict nécessaire pour que `BaseScraper._http_get` s'applique."""

    id = "FAKE_CADENCE"
    rate_limit = 3.0


def _fake_scraper():
    from scrapers.base import BaseScraper

    return type("FakeScraper", (BaseScraper,), {
        "id": _Fake.id,
        "rate_limit": _Fake.rate_limit,
        "fetch": lambda self, *a, **k: None,
    })()


def test_chaque_requete_dun_meme_scraper_est_espacee_du_rate_limit(clock):
    scraper = _fake_scraper()
    session = RecordingSession({}, clock)

    for _ in range(4):
        scraper._http_get(session, "https://exemple.test/page")

    assert len(session.calls) == 4
    assert session.intervals() == [3.0, 3.0, 3.0], (
        "les requêtes suivant la première sont parties sans attendre : la cadence "
        "n'est appliquée qu'au premier appel"
    )


def test_le_timeout_par_defaut_est_applique_sans_ecraser_celui_de_lappelant(clock):
    scraper = _fake_scraper()
    seen = []

    client = types.SimpleNamespace(
        get=lambda url, **kwargs: seen.append(kwargs.get("timeout")) or Response()
    )

    scraper._http_get(client, "https://exemple.test/a")
    scraper._http_get(client, "https://exemple.test/b", timeout=7)

    assert seen == [scraper.http_timeout, 7], (
        "une requête sans timeout peut bloquer un worker indéfiniment ; un timeout "
        "explicite de l'appelant doit rester le sien"
    )


def test_deux_fournisseurs_differents_ne_se_ralentissent_pas(clock):
    """La cadence est par fournisseur : un site lent ne doit pas retarder les
    requêtes d'un autre, sinon une cascade de huit providers coûterait la somme
    de leurs `rate_limit`."""
    from scrapers.base import BaseScraper

    def make(sid):
        return type(f"S{sid}", (BaseScraper,), {
            "id": sid, "rate_limit": 5.0, "fetch": lambda self, *a, **k: None,
        })()

    session = RecordingSession({}, clock)
    make("CADENCE_A")._http_get(session, "https://a.test/")
    make("CADENCE_B")._http_get(session, "https://b.test/")

    assert session.intervals() == [0.0]


# ===== Planète BD : 25 requêtes en rafale, dont 8 en double =====

_PBD_CARD = """
<article class="featured">
  <div class="cat">Bande dessinée</div>
  <div class="image">
    <a href="/bd/dargaud/{slug}/album-{i}/10{i}.html" title="{title} T1 : Premier">
      <img src="https://static.planetebd.com/{slug}.jpg">
    </a>
  </div>
</article>
"""

_PBD_ALBUM = """<html><head>
<title>{title} T1 : Premier, bd chez Dargaud de Goscinny, Uderzo</title>
<meta property="og:title" content="{title} T1"/>
<meta property="og:description" content="Un resume d'album suffisamment long pour compter."/>
<meta property="og:image" content="https://static.planetebd.com/couv-{slug}.jpg"/>
<meta itemprop="datePublished" content="1965-01-01"/>
</head><body>
<h1>{title} T1 : Premier</h1>
<a href="/bd/series/{slug}/500{i}.html">{title}</a>
<a href="/auteur/1/goscinny">Goscinny</a>
<span itemprop="editor">Dargaud</span>
<span itemprop="genre">Humour</span>
</body></html>"""

_PBD_SERIES = """<html><head><title>{title}</title></head><body>
<h1>{title}</h1><p>Serie en cours</p>
<a href="/bd/dargaud/{slug}/album-{i}/10{i}.html">{title} T1 : Premier</a>
</body></html>"""

_PBD_TITLES = [
    "Asterix", "Obelix", "Idefix", "Panoramix", "Abraracourcix",
    "Assurancetourix", "Cetautomatix", "Ordralfabetix", "Bonemine",
]


class PlanetebdSession(RecordingSession):
    """Neuf séries dans les résultats : `fetch()` en garde huit, comme en vrai."""

    def get(self, url, headers=None, params=None, timeout=None, allow_redirects=None):
        self.calls.append((self.clock.time(), url))
        if "/recherche.html" in url or "/recherche/" in url:
            cards = "".join(
                _PBD_CARD.format(slug=t.lower(), title=t, i=i)
                for i, t in enumerate(_PBD_TITLES)
            )
            return Response(f"<html><body>{cards}</body></html>", 200, url)
        for i, title in enumerate(_PBD_TITLES):
            slug = title.lower()
            if f"/series/{slug}/" in url:
                return Response(_PBD_SERIES.format(title=title, slug=slug, i=i), 200, url)
            if f"/{slug}/album-{i}/" in url:
                return Response(_PBD_ALBUM.format(title=title, slug=slug, i=i), 200, url)
        return Response("", 404, url)


@pytest.fixture
def planetebd(monkeypatch, clock):
    module = _load("planetebd")
    session = PlanetebdSession({}, clock)
    monkeypatch.setattr(module, "requests", types.SimpleNamespace(Session=lambda **k: session))
    monkeypatch.setattr(module, "get_max_genres", lambda *a, **k: 5)
    monkeypatch.setattr(module, "get_max_tags", lambda *a, **k: 15)
    monkeypatch.setattr(module, "get_match_accept_threshold", lambda *a, **k: 0.60)
    return types.SimpleNamespace(scraper=module.PlanetebdScraper(), session=session)


def test_planetebd_search_hits_recherche_html(planetebd):
    """`/recherche/?mot-clef=` redirige vers `/recherche.html` sans le mot-clé."""
    planetebd.scraper._search(planetebd.session, "Asterix")
    assert any("/recherche.html" in u for u in planetebd.session.urls)
    assert all(not u.rstrip("/").endswith("/recherche") for u in planetebd.session.urls)


def test_planetebd_espace_toutes_ses_requetes(planetebd):
    result = planetebd.scraper.fetch("Asterix", library_type="Comic")

    assert result is not None, "le scénario doit rester fonctionnel"
    intervals = planetebd.session.intervals()
    assert intervals, "un seul fetch() doit émettre plusieurs requêtes"
    rate = planetebd.scraper.rate_limit
    assert all(gap >= rate for gap in intervals), (
        f"cadence déclarée {rate}s, intervalles observés {intervals} : les requêtes "
        "internes au fetch() partent en rafale"
    )


def test_planetebd_ne_charge_plus_deux_fois_la_meme_page(planetebd):
    """Le titre et le statut de la série sortaient de deux chargements distincts
    de la même page, et `_parse_album` ne renseigne jamais `status` : huit URL
    étaient donc téléchargées deux fois par `fetch()`, soit vingt secondes de
    cadence offertes à un site qui bannit à vue."""
    planetebd.scraper.fetch("Asterix", library_type="Comic")

    urls = planetebd.session.urls
    doublons = len(urls) - len(set(urls))
    assert doublons == 0, (
        f"{doublons} URL rechargées : {[u for u in urls if urls.count(u) > 1]}"
    )


def test_planetebd_garde_le_statut_de_publication_de_la_serie(planetebd):
    """Le statut vient de la page série, désormais chargée une seule fois : la
    factorisation ne doit pas l'avoir perdu en chemin."""
    result = planetebd.scraper.fetch("Asterix", library_type="Comic")

    assert result["status"] == "RELEASING"


# ===== Bédéthèque : la pause en dur valait la moitié du rate_limit =====

_BDT_SEARCH = """<html><body>
<input name="csrf_token_bel" value="TOK"/>
<ul class="search-list">
  <li><a class="image-tooltip" href="/album-1-BD-Test.html" rel="/cache/thb_couv/x.jpg">
     <span class="serie">Asterix</span><span class="num">1</span><span class="titre">Le Tour</span>
  </a></li>
</ul></body></html>"""

_BDT_ALBUM = """<html><body><h1><a href="/serie-1-BD-Asterix.html">Asterix</a></h1>
<div class="synopsis">Un resume d'album assez long pour passer le filtre.</div>
<img class="couv" src="/cache/thb_couv/x.jpg"/>
<label>Scenario</label><a>Goscinny</a>
</body></html>"""

_BDT_SERIE = """<html><body><h1>Asterix</h1>
<div class="synopsis">Un resume de serie assez long pour passer le filtre.</div>
<img class="couv" src="/cache/thb_couv/y.jpg"/>
<ul class="liste-albums"><li><a href="/album-1-BD-Test.html">1. Le Tour</a> 1965</li></ul>
<span class="style">Humour</span>
</body></html>"""


@pytest.fixture
def bedetheque(monkeypatch, clock):
    module = _load("bedetheque")
    session = RecordingSession(
        {"/serie-": _BDT_SERIE, "/album-": _BDT_ALBUM, "/search/albums": _BDT_SEARCH},
        clock,
    )
    monkeypatch.setattr(module, "requests", types.SimpleNamespace(Session=lambda **k: session))
    monkeypatch.setattr(module, "get_max_genres", lambda *a, **k: 5)
    monkeypatch.setattr(module, "get_max_tags", lambda *a, **k: 15)
    monkeypatch.setattr(module, "get_match_accept_threshold", lambda *a, **k: 0.0)
    return types.SimpleNamespace(
        module=module, scraper=module.BedethequeScraper(), session=session
    )


def test_bedetheque_espace_toutes_ses_requetes_du_rate_limit_declare(bedetheque):
    """La fiche album était précédée d'un `time.sleep(1.0)` en dur pour un
    `rate_limit` de 2,0 s : le débit dépassait de deux fois la cadence déclarée,
    et tout réglage futur de `rate_limit` restait sans effet."""
    bedetheque.scraper.fetch("Le Tour de Gaule", library_type="Comic")

    intervals = bedetheque.session.intervals()
    rate = bedetheque.scraper.rate_limit
    assert intervals, "un seul fetch() doit émettre plusieurs requêtes"
    assert all(gap >= rate for gap in intervals), (
        f"cadence déclarée {rate}s, intervalles observés {intervals}"
    )


def test_bedetheque_espace_aussi_la_recherche_de_couvertures(bedetheque):
    """`fetch_covers()` n'avait aucune pause : le sélecteur de couvertures
    interroge tous les fournisseurs en parallèle, et Bédéthèque y partait en
    rafale."""
    bedetheque.scraper.fetch_covers("Le Tour de Gaule", library_type="Comic")

    rate = bedetheque.scraper.rate_limit
    assert all(gap >= rate for gap in bedetheque.session.intervals())


def test_bedetheque_espace_les_pages_de_lindex_des_albums(bedetheque):
    bedetheque.scraper.fetch_volume_index(
        "Asterix", series_id="https://www.bedetheque.com/serie-1-BD-Asterix.html"
    )

    rate = bedetheque.scraper.rate_limit
    assert all(gap >= rate for gap in bedetheque.session.intervals())


def test_bedetheque_ne_deduit_plus_lannee_dun_nombre_a_quatre_chiffres(bedetheque):
    """L'année de série était le premier nombre à quatre chiffres de la liste
    d'albums : un album intitulé « 1984 » devenait l'année de la série, écrite
    puis verrouillée dans Kavita. C'est l'heuristique que le docstring de
    `_album_release_date` condamne déjà pour les dates d'album."""
    result = bedetheque.scraper.fetch("Le Tour de Gaule", library_type="Comic")

    assert result is not None
    assert result.get("year") is None, (
        "le « 1965 » qui traîne dans la liste d'albums est reparti en année de série"
    )


@pytest.mark.parametrize(
    "html, attendu",
    [
        ('<meta itemprop="datePublished" content="1963-05-07">', 1963),
        ('<li><label>Dépot légal :</label> 09/1963</li>', 1963),
        ('<ul class="liste-albums"><li><a href="#">12. 1984</a></li></ul>', None),
        ('<p>Prix conseillé : 1995 francs</p>', None),
    ],
)
def test_bedetheque_ne_retient_quune_annee_declaree(bedetheque, html, attendu):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(f"<html><body>{html}</body></html>", "html.parser")

    assert bedetheque.module.BedethequeScraper._serie_year(soup, None) == attendu
