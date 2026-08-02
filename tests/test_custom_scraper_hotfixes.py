"""Hotfixes on local custom scrapers (data/scrapers — gitignored but loaded at runtime)."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_custom(module_stem: str):
    """Load from core `scrapers/` first (C60+), else sideload `data/scrapers/`."""
    core = ROOT / "scrapers" / f"{module_stem}.py"
    path = core if core.is_file() else ROOT / "data" / "scrapers" / f"{module_stem}.py"
    if not path.is_file():
        pytest.skip(f"scraper not present: {path}")
    mod_name = (
        f"scrapers.{module_stem}"
        if path.parent.name == "scrapers"
        else f"custom_scrapers.{module_stem}"
    )
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


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
