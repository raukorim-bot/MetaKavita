"""
Bédéthèque : une page d'erreur ne doit pas être analysée comme une fiche.

Les deux `session.get` de la fiche (album puis série) partaient directement dans
BeautifulSoup sans regarder le code HTTP : un 404, un 503 ou une page de
maintenance était parsé comme une fiche, le `<h1>` de la page d'erreur devenait
le titre récupéré et le statut de publication gardait son défaut `FINISHED`. Le
garde-fou `has_useful_data` de `fetch_metadata` finissait par écarter le candidat
vide, mais la vraie cause — le fournisseur a répondu 503 — n'était journalisée
nulle part : le diagnostic était impossible.

Le module est chargé depuis `scrapers/` (image du dépôt) et non via
`import scrapers.bedetheque`, qui renvoie la copie installée dans
`data/scrapers/` — même précaution que `test_bugfix_p0_163.py`.
"""

from __future__ import annotations

import importlib.util
import logging
import types
from pathlib import Path

import pytest

_MAINTENANCE = """
<html><body><h1>Site en maintenance</h1>
<div class="synopsis">Nous revenons dans quelques minutes, merci de votre patience.</div>
</body></html>
"""


def _load_repo_scraper_module():
    path = Path(__file__).resolve().parents[1] / "scrapers" / "bedetheque.py"
    spec = importlib.util.spec_from_file_location("scrapers.bedetheque_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class _Session:
    def __init__(self, status_code):
        self._status = status_code
        self.urls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.urls.append(url)
        return _Response(_MAINTENANCE, self._status)

    def close(self):
        pass


@pytest.fixture
def bedetheque(monkeypatch):
    module = _load_repo_scraper_module()
    sessions = []

    def session_factory(**kwargs):
        session = _Session(session_factory.status)
        sessions.append(session)
        return session

    session_factory.status = 503
    monkeypatch.setattr(module, "requests", types.SimpleNamespace(Session=session_factory))
    monkeypatch.setattr(module.time, "sleep", lambda *a: None)
    monkeypatch.setattr(module, "get_max_genres", lambda *a, **k: 5)
    monkeypatch.setattr(module, "get_max_tags", lambda *a, **k: 15)
    return types.SimpleNamespace(
        scraper=module.BedethequeScraper(),
        factory=session_factory,
        sessions=sessions,
    )


def test_une_page_album_en_erreur_ne_devient_pas_une_fiche(bedetheque, caplog):
    with caplog.at_level(logging.WARNING):
        result = bedetheque.scraper.fetch(
            "https://www.bedetheque.com/album-1234-BD-Test.html",
            library_type="Comic",
            is_id=True,
        )

    assert result is None, "la page de maintenance a été retenue comme une fiche"
    assert any("503" in rec.getMessage() for rec in caplog.records), (
        "le code HTTP n'est journalisé nulle part : la cause réelle est perdue"
    )


def test_une_page_serie_en_erreur_ne_fournit_ni_titre_ni_statut(bedetheque, caplog):
    bedetheque.factory.status = 404
    with caplog.at_level(logging.WARNING):
        result = bedetheque.scraper.fetch(
            "https://www.bedetheque.com/serie-42-BD-Test.html",
            library_type="Comic",
            is_id=True,
        )

    assert result is None, (
        "le <h1> de la page 404 est sorti en titre, avec le statut FINISHED par défaut"
    )
    assert any("404" in rec.getMessage() for rec in caplog.records)
