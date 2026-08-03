"""Hotfixes on scrapers loaded by path (package or data/scrapers sideload)."""
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_custom(module_stem: str):
    """Plug-and-play load-by-path for tests.

    Resolve in order: ``scrapers/<stem>.py`` (image core), ``data/scrapers/``
    (runtime sideload), then ``tests/fixtures/scrapers/`` (committed CI fixture).
    Execute under an ephemeral module name so the harness never collides with
    Registry ``scrapers.*`` / ``custom_scrapers.*`` entries in ``sys.modules``.
    """
    candidates = (
        ROOT / "scrapers" / f"{module_stem}.py",
        ROOT / "data" / "scrapers" / f"{module_stem}.py",
        ROOT / "tests" / "fixtures" / "scrapers" / f"{module_stem}.py",
    )
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        pytest.skip(f"scraper not present: {module_stem}.py")
    mod_name = f"hotfix_under_test.{module_stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_load_custom_ignores_polluted_scrapers_namespace():
    """Even if sys.modules has a stub scrapers.<stem>, load-by-path still works."""
    stub = types.ModuleType("scrapers.webtoon")
    sys.modules["scrapers.webtoon"] = stub
    try:
        mod = _load_custom("webtoon")
        assert hasattr(mod, "WebtoonScraper")
        assert mod is not stub
        assert not hasattr(stub, "WebtoonScraper")
    finally:
        sys.modules.pop("scrapers.webtoon", None)


def test_decitre_isbn_from_offers_list():
    mod = _load_custom("decitre")
    s = mod.DecitreScraper()
    ld = {
        "@type": "Book",
        "name": "Le Petit Prince",
        "offers": [{"@type": "Offer", "gtin13": "9782070360024"}],
    }
    html = (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        "</head><body></body></html>"
    )
    session = MagicMock()
    res = MagicMock()
    res.status_code = 200
    res.text = html
    session.get.return_value = res

    cand = s._parse_product(
        session, "https://www.decitre.fr/livres/le-petit-prince-9782070360024.html"
    )
    assert cand is not None
    assert cand["isbn"] == "9782070360024"
    assert cand["title"] == "Le Petit Prince"


def test_webtoon_does_not_invent_status():
    mod = _load_custom("webtoon")
    s = mod.WebtoonScraper()
    html = """
    <html><head>
      <meta property="og:title" content="Solo Leveling" />
      <meta property="og:description" content="A summary" />
      <meta property="og:image" content="https://example.com/c.jpg" />
    </head><body></body></html>
    """
    session = MagicMock()
    res = MagicMock()
    res.status_code = 200
    res.text = html
    session.get.return_value = res

    cand = s._parse_title(
        session,
        "https://www.webtoons.com/en/action/solo-leveling/list?title_no=1",
    )
    assert cand is not None
    assert cand.get("title") == "Solo Leveling"
    assert "status" not in cand


def test_openbd_skips_fabricated_cover_url(monkeypatch):
    """Sans summary.cover, ne pas inventer cover.openbd.jp/{isbn}.jpg (souvent 404).

    openBD est community-only (pas dans scrapers/ image) : le runner CI n'a pas
    ``data/scrapers/``. Fixture commitée : ``tests/fixtures/scrapers/openbd.py``.
    """
    mod = _load_custom("openbd")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return [{
                "summary": {
                    "title": "Test Book",
                    "author": "Author",
                    "publisher": "Pub",
                    "pubdate": "2020-01-01",
                    "cover": "",
                }
            }]

    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp())
    cand = mod.OpenbdScraper()._get_isbn("9784088807232")
    assert cand is not None
    assert cand.get("cover_url") in (None, "")
    cover = cand.get("cover_url") or ""
    assert "cover.openbd.jp" not in cover


def test_planetebd_bare_id_probes_series_url():
    mod = _load_custom("planetebd")
    s = mod.PlanetebdScraper()
    session = MagicMock()
    probe_res = MagicMock()
    probe_res.status_code = 200
    probe_res.url = "https://www.planetebd.com/bd/series/asterix/123.html"
    session.get.return_value = probe_res
    session.headers = MagicMock()

    built = {
        "title": "Astérix",
        "summary": "",
        "cover_url": None,
        "genres": ["Comic"],
        "tags": [],
        "year": 1959,
        "staff": [],
        "format": "comic",
        "url": probe_res.url,
        "links": [probe_res.url],
    }

    with patch.object(mod, "requests") as req_mod:
        req_mod.Session.return_value = session
        with patch.object(s, "_candidate_from_series_or_album", return_value=built):
            result = s.fetch("123", library_type="Comic", is_id=True)

    assert result is not None
    assert result["title"] == "Astérix"
    session.get.assert_called()
    first_url = session.get.call_args[0][0]
    assert "/bd/series/s/123.html" in first_url
