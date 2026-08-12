"""
ComicVine : la passe « issue » doit scorer, pas prendre le premier résultat.

Les passes volume utilisent l'indice d'année extrait du nom Kavita
(`Batman (2011)`), la passe de repli par issue l'ignorait et retenait
`issue_results[0]`. Le volume parent de cette issue devenait le volume écrit, et
le garde-fou final n'y voit rien : `score_candidate` compare des titres qui sont
justement identiques d'un run à l'autre (« Batman » vs « Batman ») et l'année ne
vaut qu'un bonus de 0,03 — jamais une pénalité. Le run 1940 s'écrivait donc sur
un run 2011 avec un score de 1,0.

Le module est chargé depuis `scrapers/` (image du dépôt) et non via
`import scrapers.comicvine`, qui renvoie la copie installée dans
`data/scrapers/` — même précaution que `test_bugfix_p0_163.py`.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

_VOLUME_1940 = {"id": 796, "name": "Batman"}
_VOLUME_2011 = {"id": 42721, "name": "Batman"}

# Ordre volontaire : le run historique arrive en premier, comme chez ComicVine.
_ISSUE_RESULTS = [
    {
        "id": 1001,
        "name": "Batman",
        "issue_number": "241",
        "cover_date": "1972-05-01",
        "volume": _VOLUME_1940,
    },
    {
        "id": 2002,
        "name": "Batman",
        "issue_number": "1",
        "cover_date": "2011-11-01",
        "volume": _VOLUME_2011,
    },
]

_VOLUME_DETAILS = {
    796: {
        "id": 796,
        "name": "Batman",
        "start_year": "1940",
        "description": "Le run historique de Batman, publié à partir de 1940. " * 4,
        "publisher": {"name": "DC Comics"},
    },
    42721: {
        "id": 42721,
        "name": "Batman",
        "start_year": "2011",
        "description": "Le run New 52 de Batman, publié à partir de 2011. " * 4,
        "publisher": {"name": "DC Comics"},
    },
}


def _load_repo_scraper_module():
    path = Path(__file__).resolve().parents[1] / "scrapers" / "comicvine.py"
    spec = importlib.util.spec_from_file_location("scrapers.comicvine_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def comicvine(monkeypatch):
    """Aucun volume trouvé par titre : seule la passe issue peut répondre."""
    module = _load_repo_scraper_module()
    requested = []

    def fake_get(url, params=None, headers=None, timeout=None):
        params = params or {}
        requested.append(url)
        if "/api/volumes/" in url:
            return _Response({"status_code": 1, "results": []})
        if "/api/search/" in url:
            if params.get("resources") == "issue":
                return _Response({"status_code": 1, "results": _ISSUE_RESULTS})
            return _Response({"status_code": 1, "results": []})
        if "/api/volume/4050-" in url:
            vol_id = int(url.rsplit("4050-", 1)[1].strip("/"))
            return _Response({"status_code": 1, "results": _VOLUME_DETAILS[vol_id]})
        if "/api/issue/4000-" in url:
            issue_id = int(url.rsplit("4000-", 1)[1].strip("/"))
            issue = next(i for i in _ISSUE_RESULTS if i["id"] == issue_id)
            return _Response({"status_code": 1, "results": dict(issue, description="")})
        raise AssertionError(f"URL inattendue : {url}")

    monkeypatch.setattr(module, "requests", types.SimpleNamespace(get=fake_get))
    monkeypatch.setattr(module.time, "sleep", lambda *a: None)
    monkeypatch.setattr(module, "load_config", lambda: {"COMICVINE_API_KEY": "clef"})
    monkeypatch.setattr(module, "get_match_accept_threshold", lambda *a, **k: 0.6)
    return types.SimpleNamespace(
        scraper=module.ComicVineScraper(),
        requested=requested,
        module=module,
    )


def test_la_passe_issue_respecte_lannee_du_run(comicvine):
    result = comicvine.scraper.fetch("Batman (2011)", library_type="Comic")

    assert result is not None
    assert result["year"] == 2011, (
        "le run historique a été retenu : la passe issue prenait le premier "
        "résultat sans regarder l'année"
    )
    assert any("/api/volume/4050-42721" in u for u in comicvine.requested)
    assert not any("/api/volume/4050-796" in u for u in comicvine.requested)


def test_la_passe_issue_reste_stable_sans_indice_dannee(comicvine):
    """Sans année dans le nom Kavita, on garde l'ordre de pertinence ComicVine."""
    result = comicvine.scraper.fetch("Batman", library_type="Comic")

    assert result is not None
    assert result["year"] == 1940
    assert any("/api/volume/4050-796" in u for u in comicvine.requested)


def test_le_garde_fou_final_ne_regarde_pas_lannee(comicvine):
    """Pourquoi le bug était atteignable : le score final ne départage pas deux
    runs homonymes, il ne pénalise jamais un écart d'année."""
    from scrapers.utils import score_candidate

    candidat_1940 = {"title": "Batman", "alternative_titles": [], "year": 1940,
                     "genres": ["Comic Book"], "tags": ["Comics"]}
    score = score_candidate(candidat_1940, "Batman", {"year": 2011})

    assert score >= 0.6, "un run homonyme d'une autre décennie passe le seuil final"
