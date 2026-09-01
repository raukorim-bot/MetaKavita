"""Babelio — recherche par sitemaps babmap_N.xml, hors réseau.

Le module est chargé depuis `scrapers/` (image du dépôt) et non via
`import scrapers.babelio`, qui renvoie la copie installée dans
`data/scrapers/` — même précaution que `tests/test_scraper_http_cadence.py`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_babelio():
    path = ROOT / "scrapers" / "babelio.py"
    spec = importlib.util.spec_from_file_location("scrapers.babelio_sitemap_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


babelio_mod = _load_babelio()
BabelioScraper = babelio_mod.BabelioScraper
parse_babmap_xml = babelio_mod.parse_babmap_xml
rank_sitemap_hits = babelio_mod.rank_sitemap_hits
reset_sitemap_state_for_tests = babelio_mod.reset_sitemap_state_for_tests
sitemap_looks_blocked = babelio_mod.sitemap_looks_blocked
split_slug_for_query = babelio_mod.split_slug_for_query

SAMPLE_SITEMAP = """<?xml version="1.0" encoding="ISO-8859-1"?>
<urlset xmlns="http://www.google.com/schemas/sitemap/0.84">
  <url><loc>https://www.babelio.com/livres/Pynchon-Vineland/1496</loc></url>
  <url><loc>https://www.babelio.com/livres/de-Saint-Exupery-Le-Petit-Prince/36712</loc></url>
  <url><loc>https://www.babelio.com/livres/Webster-Saint-Exupery-vie-et-mort-du-Petit-Prince/29183</loc></url>
  <url><loc>https://www.babelio.com/livres/Desarthe-Petit-Prince-Pouf/40066</loc></url>
</urlset>
""".encode("iso-8859-1")


@pytest.fixture(autouse=True)
def _isolated_sitemap_cache(tmp_path, monkeypatch):
    reset_sitemap_state_for_tests()
    monkeypatch.setattr(babelio_mod, "_CACHE_DIR_OVERRIDE", tmp_path / "sitemaps")
    monkeypatch.setattr(
        "services.provider_throttle.throttle_provider",
        lambda *a, **k: None,
    )
    yield
    reset_sitemap_state_for_tests()
    monkeypatch.setattr(babelio_mod, "_CACHE_DIR_OVERRIDE", None)


def test_parse_babmap_extracts_livres_locs():
    rows = parse_babmap_xml(SAMPLE_SITEMAP)
    assert (36712, "de-Saint-Exupery-Le-Petit-Prince") in rows
    assert len(rows) == 4


def test_captcha_html_is_treated_as_blocked_sitemap():
    html = b"<html><body>captcha Access denied</body></html>"
    assert sitemap_looks_blocked(html) is True
    assert sitemap_looks_blocked(SAMPLE_SITEMAP) is False


def test_slug_split_puts_petit_prince_in_the_title():
    title, author = split_slug_for_query(
        "de-Saint-Exupery-Le-Petit-Prince", "Le Petit Prince"
    )
    assert "Petit" in title and "Prince" in title
    assert "Exupery" in author or "Saint" in author


def test_rank_prefers_the_book_over_the_biography():
    rows = parse_babmap_xml(SAMPLE_SITEMAP)
    hits = rank_sitemap_hits(rows, "Le Petit Prince")
    assert hits
    assert hits[0]["babelio_id"].endswith("/36712")
    assert hits[0]["_score"] >= 0.60


def test_search_downloads_babmap_not_homepage_or_recherche():
    scraper = BabelioScraper()
    session = MagicMock()
    xml = MagicMock(status_code=200, content=SAMPLE_SITEMAP)
    session.get.return_value = xml

    hits = scraper._search(session, "Le Petit Prince")

    assert hits
    assert hits[0]["babelio_id"].endswith("/36712")
    urls = [c.args[0] for c in session.get.call_args_list]
    assert urls
    assert all("babmap_" in u and u.endswith(".xml") for u in urls)
    assert not any(u.rstrip("/").endswith("babelio.com") for u in urls)
    assert not any("/recherche" in u for u in urls)
    # Un match dans babmap_1 : on ne tire pas les 36 autres.
    assert urls == ["https://www.babelio.com/babmap_1.xml"]


def test_search_uses_disk_cache_on_the_second_call():
    scraper = BabelioScraper()
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200, content=SAMPLE_SITEMAP)

    scraper._search(session, "Le Petit Prince")
    n_first = session.get.call_count
    session.get.reset_mock()
    hits = scraper._search(session, "Le Petit Prince")

    assert hits
    assert session.get.call_count == 0
    assert n_first == 1


def test_isbn_search_does_not_download_sitemaps():
    scraper = BabelioScraper()
    session = MagicMock()
    hits = scraper._search(session, "9782070612758")
    assert hits == []
    session.get.assert_not_called()
    session.post.assert_not_called()


def test_sitemap_403_stops_without_html_search():
    scraper = BabelioScraper()
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=403, content=b"denied")
    session.post.return_value = MagicMock(status_code=403, content=b"denied")

    hits = scraper._search(session, "Le Petit Prince")

    assert hits == []
    session.post.assert_not_called()
    assert session.get.call_count == 1


def test_broken_mock_response_does_not_walk_all_maps():
    scraper = BabelioScraper()
    session = MagicMock()
    # status_code non-entier : ne pas interpréter le mock comme un 200, ni
    # enchaîner babmap_1..37 à 3 s l'un.
    session.get.return_value = MagicMock()

    hits = scraper._search(session, "Le Petit Prince")

    assert hits == []
    assert session.get.call_count == 1
    session.post.assert_not_called()


def test_numeric_magic_id_does_not_crawl_sitemaps():
    scraper = BabelioScraper()
    session = MagicMock()
    assert scraper._candidate_from_sitemap_id(session, "36712", "Le Petit Prince") is None
    session.get.assert_not_called()
    session.post.assert_not_called()
