"""
ComicVine : barème de sélection d'un volume, et causes d'erreur API journalisées.

Deux défauts distincts, mesurés tous les deux :

1. Le bonus « éditeur majeur » valait 300 points contre 150 pour un titre
   exactement égal. Un « Scorpion » de chez Marvel battait donc « Le Scorpion »
   d'Editions Paquet — éditeur absent de `PRIMARY_PUBLISHERS`, comme Soleil,
   Ankama, Rue de Sèvres, Bamboo ou Vents d'Ouest. Le garde-fou final ne voit
   rien : il compare deux titres qui se ressemblent (0,95 ≥ 0,60). Résumé,
   couverture, éditeur, année et crédits d'un comic américain partaient sur une
   BD française avec un score affiché de 95 %, et MetaKavita posant les verrous
   Kavita, la correction automatique ultérieure était bloquée.

2. ComicVine répond **HTTP 200** à une clé révoquée comme à un quota dépassé, en
   plaçant la cause dans `status_code` et une liste `results` vide. Les passes de
   recherche voyaient zéro candidat, `fetch()` rendait None, et l'utilisateur
   lisait « aucun résultat » sans qu'aucune ligne de journal ne mentionne sa clé.

Le module est chargé depuis `scrapers/` (image du dépôt) et non via
`import scrapers.comicvine`, qui renvoie la copie installée dans
`data/scrapers/` — même précaution que `test_scraper_comicvine_issue_pass.py`.
"""

from __future__ import annotations

import importlib.util
import logging
import types
from pathlib import Path

import pytest

from scrapers.utils import (
    PROVIDER_ERROR_AUTH,
    PROVIDER_ERROR_QUOTA,
    provider_error_scope,
)


def _load_repo_scraper_module():
    path = Path(__file__).resolve().parents[1] / "scrapers" / "comicvine.py"
    spec = importlib.util.spec_from_file_location("scrapers.comicvine_scoring_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


cv = _load_repo_scraper_module()


class _Response:
    def __init__(self, payload, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        return self._payload


# ===== 1. Barème : « Le Scorpion » =====

# Cas mesuré : le candidat au titre exact est chez un éditeur franco-belge absent
# de `PRIMARY_PUBLISHERS`, le candidat approchant chez un éditeur qui y figure.
_SCORPION_EXACT = {
    "id": 111,
    "name": "Le Scorpion",
    "count_of_issues": 14,
    "publisher": {"name": "Editions Paquet"},
    "start_year": "2000",
}
_SCORPION_MARVEL = {
    "id": 222,
    "name": "Scorpion",
    "count_of_issues": 5,
    "publisher": {"name": "Marvel"},
    "start_year": "1975",
}


def test_un_titre_exact_bat_un_editeur_majeur():
    scraper = cv.ComicVineScraper()

    retenu = scraper._evaluate_volume_candidates(
        [_SCORPION_MARVEL, _SCORPION_EXACT], "Le Scorpion", library_type="Comic"
    )

    assert retenu is not None
    assert retenu["id"] == _SCORPION_EXACT["id"], (
        "le « Scorpion » de Marvel a été retenu pour « Le Scorpion » : le bonus "
        "éditeur de 300 points écrasait les 150 du titre exact"
    )


def test_lordre_des_resultats_ne_change_rien():
    """ComicVine trie par pertinence maison : le bon candidat peut arriver en
    second comme en premier, le barème doit trancher pareil."""
    scraper = cv.ComicVineScraper()

    for ordre in ([_SCORPION_EXACT, _SCORPION_MARVEL], [_SCORPION_MARVEL, _SCORPION_EXACT]):
        retenu = scraper._evaluate_volume_candidates(ordre, "Le Scorpion", library_type="Comic")
        assert retenu["id"] == _SCORPION_EXACT["id"]


def test_le_bonus_editeur_reste_sous_le_bonus_de_titre_exact():
    """Le rapport entre les deux primes est ce qui était faux : un éditeur connu
    est un indice de notoriété, pas une preuve d'identité."""
    assert cv.PRIMARY_PUBLISHER_BONUS < cv.EXACT_TITLE_BONUS
    assert cv.PRIMARY_PUBLISHER_BONUS <= 50.0


def test_le_nombre_dalbums_ne_peut_plus_ecraser_le_bareme():
    """À 1,5 point l'unité et sans plafond, un recueil de mille strips valait
    1500 points — plus que tout le reste réuni."""
    scraper = cv.ComicVineScraper()
    recueil = {
        "id": 333,
        "name": "Scorpion",
        "count_of_issues": 1000,
        "publisher": {"name": "Marvel"},
    }

    retenu = scraper._evaluate_volume_candidates(
        [recueil, _SCORPION_EXACT], "Le Scorpion", library_type="Comic"
    )

    assert retenu["id"] == _SCORPION_EXACT["id"]


def test_un_start_year_exact_bat_un_voisin_plus_long():
    """#40 : ±1 ne doit plus égaler l'année exacte. Un Avengers 2010 plus
    fourni ne doit pas gagner sur le run 2011 nommé dans Kavita."""
    scraper = cv.ComicVineScraper()
    vol_2011 = {
        "id": 2011,
        "name": "Avengers",
        "count_of_issues": 12,
        "publisher": {"name": "Marvel"},
        "start_year": "2011",
    }
    vol_2010 = {
        "id": 2010,
        "name": "Avengers",
        "count_of_issues": 200,
        "publisher": {"name": "Marvel"},
        "start_year": "2010",
    }
    vol_2012 = {
        "id": 2012,
        "name": "Avengers",
        "count_of_issues": 80,
        "publisher": {"name": "Marvel"},
        "start_year": "2012",
    }

    for ordre in (
        [vol_2010, vol_2012, vol_2011],
        [vol_2011, vol_2010, vol_2012],
        [vol_2012, vol_2010, vol_2011],
    ):
        retenu = scraper._evaluate_volume_candidates(
            ordre, "Avengers", year_hint=2011, library_type="Comic"
        )
        assert retenu["id"] == 2011, (
            f"le run {retenu.get('start_year')} a été retenu pour un hint 2011"
        )


def test_un_voisin_bat_un_run_lointain_quand_lannee_exacte_manque():
    """Sans volume à l'année pile, ±1 reste un indice contre 1940."""
    scraper = cv.ComicVineScraper()
    voisin = {
        "id": 2010,
        "name": "Batman",
        "count_of_issues": 18,
        "publisher": {"name": "DC Comics"},
        "start_year": "2010",
    }
    historique = {
        "id": 1940,
        "name": "Batman",
        "count_of_issues": 1000,
        "publisher": {"name": "DC Comics"},
        "start_year": "1940",
    }

    retenu = scraper._evaluate_volume_candidates(
        [historique, voisin], "Batman", year_hint=2011, library_type="Comic"
    )
    assert retenu["id"] == 2010


def test_le_bonus_editeur_ne_sapplique_pas_a_une_bibliotheque_manga():
    """Le catalogue ComicVine est celui du comic américain : sa notoriété
    d'éditeur ne dit rien de la pertinence d'un candidat pour une bibliothèque
    manga, où elle ne fait que remonter des homonymes Marvel / DC."""
    scraper = cv.ComicVineScraper()
    homonyme_us = {
        "id": 444,
        "name": "Monster",
        "count_of_issues": 6,
        "publisher": {"name": "Image"},
    }
    serie_japonaise = {
        "id": 555,
        "name": "Monster",
        "count_of_issues": 18,
        "publisher": {"name": "Shogakukan"},
    }

    retenu = scraper._evaluate_volume_candidates(
        [homonyme_us, serie_japonaise], "Monster", library_type="Manga"
    )

    assert retenu["id"] == serie_japonaise["id"], (
        "le bonus « éditeur majeur » a fait remonter un homonyme Image Comics "
        "dans une bibliothèque manga"
    )


# ===== 2. Erreurs API en HTTP 200 =====


@pytest.fixture
def comicvine(monkeypatch):
    """Toutes les requêtes rendent la même réponse : c'est la cause d'erreur, pas
    le chemin de recherche, qui est observée."""
    module = _load_repo_scraper_module()
    state = types.SimpleNamespace(response=None, calls=0)

    def fake_get(url, params=None, headers=None, timeout=None):
        state.calls += 1
        return state.response

    monkeypatch.setattr(module, "requests", types.SimpleNamespace(get=fake_get))
    monkeypatch.setattr(module, "load_config", lambda: {"COMICVINE_API_KEY": "clef"})
    monkeypatch.setattr(module, "get_match_accept_threshold", lambda *a, **k: 0.6)
    return types.SimpleNamespace(
        scraper=module.ComicVineScraper(), state=state, module=module
    )


# `status_code` ComicVine → (fragment attendu dans le journal, niveau, cause).
CAUSES_API = [
    (100, "Invalid API Key", logging.ERROR, PROVIDER_ERROR_AUTH),
    (107, "Rate Limit Exceeded", logging.WARNING, PROVIDER_ERROR_QUOTA),
]


@pytest.mark.parametrize(("status", "message", "niveau", "cause"), CAUSES_API)
def test_une_erreur_api_en_http_200_est_journalisee(comicvine, caplog, status, message, niveau, cause):
    comicvine.state.response = _Response(
        {"error": message, "status_code": status, "results": []}
    )

    with caplog.at_level(logging.WARNING):
        with provider_error_scope() as erreurs:
            result = comicvine.scraper.fetch("Le Scorpion", library_type="Comic")

    assert result is None
    assert any(str(status) in rec.getMessage() for rec in caplog.records), (
        f"code {status} ({message}) rendu en HTTP 200 : aucun journal ne mentionne "
        "la cause, l'utilisateur lit « aucun résultat »"
    )
    assert any(rec.levelno >= niveau for rec in caplog.records)
    assert cause in {e["kind"] for e in erreurs}, (
        "la cause n'est pas remontée à metadata_fetcher : impossible de "
        "distinguer une clé morte d'une série introuvable"
    )


def test_un_401_est_journalise_en_erreur(comicvine, caplog):
    comicvine.state.response = _Response({}, status_code=401)

    with caplog.at_level(logging.WARNING):
        with provider_error_scope() as erreurs:
            assert comicvine.scraper.fetch("Le Scorpion", library_type="Comic") is None

    assert any(rec.levelno >= logging.ERROR for rec in caplog.records), (
        "un 401 est une clé à corriger dans les paramètres, pas un avertissement"
    )
    assert PROVIDER_ERROR_AUTH in {e["kind"] for e in erreurs}


def test_un_429_signale_le_retry_after(comicvine, caplog):
    comicvine.state.response = _Response({}, status_code=429, headers={"Retry-After": "42"})

    with caplog.at_level(logging.WARNING):
        with provider_error_scope() as erreurs:
            assert comicvine.scraper.fetch("Le Scorpion", library_type="Comic") is None

    messages = " ".join(rec.getMessage() for rec in caplog.records)
    assert "429" in messages
    assert "42" in messages, "le délai annoncé par le serveur est l'information utile"
    assert PROVIDER_ERROR_QUOTA in {e["kind"] for e in erreurs}


def test_un_status_code_1_reste_une_reponse_exploitable(comicvine):
    """Le cas normal : `status_code` valant 1 est un succès ComicVine, il ne doit
    pas être confondu avec une cause d'erreur."""
    comicvine.state.response = _Response({"status_code": 1, "results": []})

    body = comicvine.scraper._api_json(comicvine.state.response)

    assert body is not None and body["results"] == []


def test_une_recherche_sans_resultat_ne_journalise_pas_derreur(comicvine, caplog):
    """L'inverse compte autant : une série vraiment introuvable ne doit pas
    inquiéter l'utilisateur sur sa clé API."""
    comicvine.state.response = _Response({"status_code": 1, "results": []})

    with caplog.at_level(logging.WARNING):
        with provider_error_scope() as erreurs:
            assert comicvine.scraper.fetch("Serie Inexistante", library_type="Comic") is None

    assert not erreurs
    assert not [rec for rec in caplog.records if rec.levelno >= logging.WARNING]
