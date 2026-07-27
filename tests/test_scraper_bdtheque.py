"""Tests scraper BDTheque.com (distinct de Bédéthèque / bedetheque.com)."""
from unittest.mock import MagicMock, patch

from scrapers.bdtheque import (
    BdthequeScraper,
    cover_url_from_couv,
    format_author_name,
    generate_search_queries,
)

SAMPLE_HTML = """
<html><body>
  <h1>Clifton</h1>
  <img class="cover" src="https://www.bdtheque.com/repupload/T/cover-clifton.jpg" />
  <p class="lead mt-3">Sous ses allures de BD humoristique, Clifton cache une bonne série policière.</p>
  <p>Harold Wilberforce Clifton troque parfois sa tenue de détective amateur.</p>
  <table class="table table-sm">
    <tr>
      <td>Scénario</td>
      <td><a href="/recherche/series/auteurs=De%20Groot%20%28Bob%29">De Groot (Bob)</a></td>
    </tr>
    <tr>
      <td>Dessin</td>
      <td><a href="/recherche/series/auteurs=Turk">Turk</a></td>
    </tr>
    <tr>
      <td>Couleurs</td>
      <td><a href="/recherche/series/auteurs=Denayer%20%28Liliane%29">Denayer (Liliane)</a></td>
    </tr>
    <tr>
      <td>Editeur / Collection</td>
      <td>
        <a href="/recherche/series/editeur=Le%20Lombard">Le Lombard</a>
        <a href="/recherche/series/collection=x">Tintin</a>
      </td>
    </tr>
    <tr>
      <td>Genre / Public / Type</td>
      <td>
        <a href="/recherche/series/genre=humour">Humour</a>
        <a href="/recherche/series/public=1">Ados - Adultes</a>
        <a href="/recherche/series/type=BD">BD</a>
      </td>
    </tr>
    <tr>
      <td>Date de parution</td>
      <td>Août <a href="/recherche/series/annee=1978">1978</a></td>
    </tr>
    <tr>
      <td>Statut histoire</td>
      <td><a href="/recherche/series/histoire=une-histoire-par-tome">Une histoire par tome</a> 24 tomes parus</td>
    </tr>
  </table>
</body></html>
"""

ONE_SHOT_HTML = """
<html><body>
  <h1>La Statue de Gilgamesh</h1>
  <img class="cover h-auto" src="images/placeholder.png"
       data-echo="https://www.bdtheque.com/repupload/T/83637-couverture-bd-la-statue-de-gilgamesh-tome-1.jpg" />
  <p class="lead">Inspirée de la plus ancienne épopée de l'humanité.</p>
  <table class="table table-sm">
    <tr><td>Scénario</td><td><a href="#">Guinin (Blaise)</a></td></tr>
    <tr><td>Dessin</td><td><a href="#">Pelosse (Louis)</a></td></tr>
    <tr><td>Editeur</td><td><a href="/recherche/series/editeur=Delcourt">Delcourt</a></td></tr>
    <tr>
      <td>Genre / Public / Type</td>
      <td>
        <a href="/recherche/series/genre=roman-graphique">Roman Graphique</a>
        <a href="/recherche/series/public=1">Ados - Adultes</a>
        <a href="/recherche/series/type=BD">BD</a>
      </td>
    </tr>
    <tr><td>Date de parution</td><td>19 Février <a href="#">2026</a></td></tr>
    <tr><td>Statut histoire</td><td><a href="/recherche/series/histoire=one-shot">One shot</a> 1 tome paru</td></tr>
  </table>
</body></html>
"""


def test_format_author_name():
    assert format_author_name("Macherot (Raymond)") == "Raymond Macherot"
    assert format_author_name("Turk") == "Turk"
    assert format_author_name("Indéterminé") == ""
    assert format_author_name("") == ""


def test_cover_url_from_couv():
    # Typeahead site : toujours sous /repupload/T/ pour les couvertures de série
    assert cover_url_from_couv("T_2375.JPG") == "https://www.bdtheque.com/repupload/T/T_2375.JPG"
    assert (
        cover_url_from_couv("83637-couverture-bd-la-statue-de-gilgamesh-tome-1.jpg")
        == "https://www.bdtheque.com/repupload/T/83637-couverture-bd-la-statue-de-gilgamesh-tome-1.jpg"
    )
    # Ne pas mapper un filename numérique vers /repupload/8/
    assert "repupload/8/" not in (cover_url_from_couv("83637-couverture.jpg") or "")
    assert cover_url_from_couv(None) is None


def test_generate_search_queries_strips_article():
    qs = generate_search_queries("La Statue de Gilgamesh")
    assert "La Statue de Gilgamesh" in qs
    assert "Statue de Gilgamesh" in qs


def test_extract_id_from_url_ignores_bedetheque():
    s = BdthequeScraper()
    assert s.extract_id_from_url("https://www.bdtheque.com/series/590/clifton") == "590/clifton"
    assert s.extract_id_from_url("https://www.bdtheque.com/series/590") == "590"
    assert s.extract_id_from_url("https://www.bedetheque.com/serie-590-BD-Clifton.html") is None
    assert s.extract_id_from_url("https://example.com/series/1") is None
    assert s.extract_id_from_url("") is None


def test_parse_series_html_clifton():
    s = BdthequeScraper()
    cand = s._parse_series_html(
        SAMPLE_HTML, "590/clifton", "https://www.bdtheque.com/series/590/clifton"
    )
    assert cand is not None
    assert cand["title"] == "Clifton"
    assert cand["year"] == 1978
    assert cand["status"] == "RELEASING"
    assert cand["publisher"] == "Le Lombard"
    assert "Humour" in cand["genres"]
    assert cand["cover_url"].endswith("cover-clifton.jpg")
    assert any(st["node"]["name"]["full"] == "Bob De Groot" for st in cand["staff"])
    assert any(st["node"]["name"]["full"] == "Turk" for st in cand["staff"])
    assert any(st["node"]["name"]["full"] == "Liliane Denayer" for st in cand["staff"])
    assert cand["bdtheque_id"] == "590/clifton"
    assert "BDTheque" in cand["tags"]


def test_parse_one_shot_status_and_relative_cover():
    s = BdthequeScraper()
    cand = s._parse_series_html(
        ONE_SHOT_HTML,
        "26735/la-statue-de-gilgamesh",
        "https://www.bdtheque.com/series/26735/la-statue-de-gilgamesh",
    )
    assert cand["status"] == "FINISHED"
    assert cand["year"] == 2026
    assert cand["publisher"] == "Delcourt"
    # data-echo, pas le placeholder.png
    assert cand["cover_url"] == (
        "https://www.bdtheque.com/repupload/T/83637-couverture-bd-la-statue-de-gilgamesh-tome-1.jpg"
    )
    assert "placeholder" not in cand["cover_url"]
    assert any(st["node"]["name"]["full"] == "Blaise Guinin" for st in cand["staff"])


def test_fetch_covers_uses_provider_key_and_t_folder():
    s = BdthequeScraper()
    ajax = [
        {
            "id": "26735/la-statue-de-gilgamesh",
            "nom": "La Statue de Gilgamesh",
            "nomvo": "",
            "couv": "83637-couverture-bd-la-statue-de-gilgamesh-tome-1.jpg",
            "note": "3",
        },
        {
            "id": "1/autre",
            "nom": "Autre série",
            "nomvo": "",
            "couv": "T_1.JPG",
            "note": "1",
        },
    ]
    with patch("scrapers.bdtheque.requests.Session"):
        with patch.object(s, "_ajax_search", return_value=ajax):
            covers = s.fetch_covers("La Statue de Gilgamesh", library_type="Comic")
    assert covers
    assert covers[0]["provider"] == s.display_name
    assert "source" not in covers[0]
    assert covers[0]["url"].startswith("https://www.bdtheque.com/repupload/T/")
    assert "repupload/8/" not in covers[0]["url"]
    # Match exact prioritaire → une seule cover (pas le fallback « Autre »)
    assert len(covers) == 1
    assert covers[0]["title"] == "La Statue de Gilgamesh"


def test_fetch_by_id_mocked():
    s = BdthequeScraper()
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.text = SAMPLE_HTML
    mock_res.url = "https://www.bdtheque.com/series/590/clifton"

    with patch("scrapers.bdtheque.requests.Session") as sess_cls:
        session = sess_cls.return_value
        session.get.return_value = mock_res
        result = s.fetch("590/clifton", is_id=True)
        assert result is not None
        assert result["title"] == "Clifton"
        assert result["_match_score"] == 1.0


def test_fetch_search_scores_and_threshold():
    s = BdthequeScraper()
    ajax = [{"id": "590/clifton", "nom": "Clifton", "nomvo": "", "couv": "T_2375.JPG", "note": "3.1"}]
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.text = SAMPLE_HTML
    mock_res.url = "https://www.bdtheque.com/series/590/clifton"

    with patch("scrapers.bdtheque.requests.Session") as sess_cls:
        session = sess_cls.return_value
        session.get.return_value = mock_res
        with patch.object(s, "_ajax_search", return_value=ajax):
            with patch("scrapers.bdtheque.score_candidate", return_value=0.92):
                with patch("scrapers.bdtheque.get_match_accept_threshold", return_value=0.60):
                    result = s.fetch("Clifton", library_type="Comic")
                    assert result is not None
                    assert result["title"] == "Clifton"
                    assert result["_match_score"] == 0.92


def test_fetch_search_below_threshold_returns_none():
    s = BdthequeScraper()
    ajax = [{"id": "1/x", "nom": "Autre", "nomvo": "", "couv": "", "note": "1"}]
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.text = SAMPLE_HTML
    mock_res.url = "https://www.bdtheque.com/series/1/x"

    with patch("scrapers.bdtheque.requests.Session") as sess_cls:
        session = sess_cls.return_value
        session.get.return_value = mock_res
        with patch.object(s, "_ajax_search", return_value=ajax):
            with patch("scrapers.bdtheque.score_candidate", return_value=0.40):
                with patch("scrapers.bdtheque.get_match_accept_threshold", return_value=0.60):
                    assert s.fetch("Clifton") is None


def test_registry_loads_bdtheque():
    from scrapers import ScraperRegistry

    scraper = ScraperRegistry.get("BDTHEQUE")
    assert scraper is not None
    assert scraper.id == "BDTHEQUE"
    assert "Comic" in scraper.supported_types
    assert scraper.uses_unified_scoring is True
    # Pas de collision avec Bédéthèque
    assert ScraperRegistry.get("BEDETHEQUE") is not None
    assert ScraperRegistry.get("BEDETHEQUE").id != scraper.id
