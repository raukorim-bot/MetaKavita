"""
MangaUpdates : un match validé ne doit pas être jeté si le détail échoue.

La recherche `/v1/series/search` renvoie un `record` de même forme que
`/v1/series/{id}` : le candidat complet (résumé, staff, éditeur) est donc déjà
construit et scoré en mémoire quand la seconde requête part. Or l'API est
derrière Cloudflare (`impersonate="chrome110"`) : un 403/429/5xx sur le détail
renvoyait `None`, et les logs affichaient « Match validé (ID, 87 %) » suivi
d'aucune contribution du provider.

Le module est chargé depuis `scrapers/` (image du dépôt) et non via
`import scrapers.mangaupdates`, qui renvoie la copie installée dans
`data/scrapers/` — même précaution que `test_bugfix_p0_163.py`.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

_RECORD = {
    "series_id": 12345,
    "title": "Vinland Saga",
    "description": "Thorfinn part en mer.",
    "year": "2005",
    "completed": True,
    "authors": [{"name": "Makoto Yukimura", "type": "Author"}],
    "genres": [{"genre": "Seinen"}],
    "image": {"url": {"original": "https://www.mangaupdates.com/cover.jpg"}},
    "publishers": [{"publisher_name": "Kodansha", "type": "Original"}],
}


def _load_repo_scraper_module():
    path = Path(__file__).resolve().parents[1] / "scrapers" / "mangaupdates.py"
    # Nom qualifié `scrapers.*` : le fichier fait `from .utils import ...`.
    spec = importlib.util.spec_from_file_location("scrapers.mangaupdates_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture
def mangaupdates(monkeypatch):
    """Scraper prêt à l'emploi : recherche OK, détail piloté par le test."""
    module = _load_repo_scraper_module()
    calls = {"search": 0, "detail": 0}

    def fake_post(url, json=None, headers=None, timeout=None, impersonate=None):
        calls["search"] += 1
        return _Response(200, {"results": [{"record": _RECORD, "hit_title": "Vinland Saga"}]})

    def install_detail(handler):
        def fake_get(url, headers=None, timeout=None, impersonate=None):
            calls["detail"] += 1
            return handler(url)

        monkeypatch.setattr(
            module, "requests", types.SimpleNamespace(post=fake_post, get=fake_get)
        )

    monkeypatch.setattr(module, "load_config", lambda: {})
    monkeypatch.setattr(module, "get_match_accept_threshold", lambda: 0.6)
    return types.SimpleNamespace(
        scraper=module.MangaUpdatesScraper(),
        calls=calls,
        install_detail=install_detail,
    )


def test_un_match_valide_survit_a_un_detail_cloudflare(mangaupdates):
    mangaupdates.install_detail(lambda url: _Response(403))

    result = mangaupdates.scraper.fetch("Vinland Saga")

    assert mangaupdates.calls["detail"] == 1, "le détail reste tenté en premier"
    assert result is not None, "candidat validé jeté à cause du seul appel de détail"
    assert result["title"] == "Vinland Saga"
    assert result["summary"] == "Thorfinn part en mer."
    assert result["publisher"] == "Kodansha"
    assert result["_match_score"] >= 0.6, "le score validé doit suivre le candidat de repli"


def test_un_match_valide_survit_a_une_exception_reseau(mangaupdates):
    def _boom(url):
        raise RuntimeError("Connection reset by peer")

    mangaupdates.install_detail(_boom)

    result = mangaupdates.scraper.fetch("Vinland Saga")

    assert result is not None, "une coupure réseau sur le détail perdait le match"
    assert result["title"] == "Vinland Saga"


def test_le_detail_reste_prioritaire_quand_il_repond(mangaupdates):
    """Le repli ne doit pas court-circuiter la donnée de détail, plus complète."""
    detail = dict(_RECORD, description="Résumé long et complet issu du détail.")
    mangaupdates.install_detail(lambda url: _Response(200, detail))

    result = mangaupdates.scraper.fetch("Vinland Saga")

    assert result is not None
    assert result["summary"] == "Résumé long et complet issu du détail."


def test_un_score_sous_le_seuil_reste_refuse(mangaupdates):
    """Le repli ne doit pas transformer un non-match en contribution."""
    mangaupdates.install_detail(lambda url: _Response(403))

    result = mangaupdates.scraper.fetch("Un Titre Totalement Different")

    assert result is None
    assert mangaupdates.calls["detail"] == 0, "détail appelé alors qu'aucun match n'est validé"
