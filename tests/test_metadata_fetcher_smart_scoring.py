"""
Non-régression : "Smart Scoring" dans `metadata_fetcher.py::fetch_metadata()`.

Avant ce correctif, le PREMIER provider de `providers_list` (l'ordre de
fallback configuré par l'utilisateur) qui dépassait le seuil d'acceptation
devenait systématiquement le "vainqueur" (`master_data`), sans jamais comparer
son score à celui des providers suivants — même si un provider #2/#3 avait un
bien meilleur match pour cette requête précise. La complétion (SMART_COMPLETION)
ne faisait, elle aussi, que remplir les champs vides dans l'ordre BRUT de la
liste, pas du plus fiable au moins fiable.

Ces tests vérifient :
- que le candidat au MEILLEUR score gagne, quelle que soit sa position dans
  `providers_list` ;
- qu'à score égal, l'ordre de fallback (position dans la liste) tranche ;
- qu'un candidat sans `_match_score` explicite (scraper communautaire non
  migré vers `score_candidate()`/`attach_match_score()`) est traité comme
  "juste accepté" (MATCH_ACCEPT_THRESHOLD) plutôt que de faire planter le tri ;
- que SMART_COMPLETION comble les champs manquants du meilleur score au moins
  bon, et non plus dans l'ordre brut de la liste ;
- que les providers après le premier tournent bien EN PARALLÈLE (et non plus
  séquentiellement), et que le contexte (ISBN) trouvé par le provider #1 est
  bien transmis à cette vague parallèle suivante.
"""
import threading
import time
from types import SimpleNamespace

import pytest

import metadata_fetcher
from scrapers.utils import MATCH_ACCEPT_THRESHOLD


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    """Évite toute interférence entre tests (horodatages de rate-limit partagés)
    et tout accès réseau/disque réel (config.json)."""
    monkeypatch.setattr(metadata_fetcher, "load_config", lambda: {
        "UI_LANG": "fr",
        "SMART_SCORING": True,
        "SMART_COMPLETION": False,
    })


def _make_scraper(scraper_id, fetch_fn, supported_types=None, rate_limit=0.0):
    return SimpleNamespace(
        id=scraper_id,
        supported_types=supported_types or {"Manga"},
        rate_limit=rate_limit,
        extract_id_from_url=lambda url: None,
        fetch=fetch_fn,
    )


def _install_fake_registry(monkeypatch, scrapers_by_id):
    fake_registry = SimpleNamespace(get=lambda scraper_id: scrapers_by_id.get(scraper_id))
    monkeypatch.setattr(metadata_fetcher, "ScraperRegistry", fake_registry)


def test_best_score_wins_regardless_of_provider_list_position(monkeypatch):
    def low_score_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Wrong Match", "summary": "Résumé A", "_match_score": 0.65}

    def high_score_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Right Match", "summary": "Résumé B", "_match_score": 0.95}

    scrapers = {
        "LOW_SCORE": _make_scraper("LOW_SCORE", low_score_fetch),
        "HIGH_SCORE": _make_scraper("HIGH_SCORE", high_score_fetch),
    }
    _install_fake_registry(monkeypatch, scrapers)

    result, used = metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["LOW_SCORE", "HIGH_SCORE"], smart_fusion=False,
        library_type="Manga", existing_metadata={}, smart_scoring=True,
    )

    assert result is not None
    assert result["_provider_used"] == "HIGH_SCORE", (
        "Le provider avec le meilleur score doit gagner, même s'il est en 2e position "
        "de la liste de fallback (ancien comportement : le 1er provider accepté gagnait "
        "toujours, sans comparaison de score)."
    )
    assert result["title"] == "Right Match"


def test_classic_fallback_keeps_first_provider_when_smart_scoring_disabled(monkeypatch):
    """SMART_SCORING=False : l'ordre de la liste prime, même si un provider suivant
    a un bien meilleur score."""
    def low_score_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "First Wins", "summary": "Résumé A", "_match_score": 0.65}

    def high_score_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Better Match Ignored", "summary": "Résumé B", "_match_score": 0.95}

    scrapers = {
        "LOW_SCORE": _make_scraper("LOW_SCORE", low_score_fetch),
        "HIGH_SCORE": _make_scraper("HIGH_SCORE", high_score_fetch),
    }
    _install_fake_registry(monkeypatch, scrapers)

    result, used = metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["LOW_SCORE", "HIGH_SCORE"], smart_fusion=False,
        library_type="Manga", existing_metadata={}, smart_scoring=False,
    )

    assert result is not None
    assert result["_provider_used"] == "LOW_SCORE"
    assert result["title"] == "First Wins"


def test_classic_fallback_completion_follows_list_order_not_score(monkeypatch):
    def first_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "T", "summary": "Base", "_match_score": 0.95}

    def second_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "T", "genres": ["FromSecond"], "year": 1999, "_match_score": 0.65}

    def third_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "T", "genres": ["FromThird"], "year": 2020, "_match_score": 0.90}

    scrapers = {
        "P1": _make_scraper("P1", first_fetch),
        "P2": _make_scraper("P2", second_fetch),
        "P3": _make_scraper("P3", third_fetch),
    }
    _install_fake_registry(monkeypatch, scrapers)

    result, used = metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["P1", "P2", "P3"], smart_fusion=True,
        library_type="Manga", existing_metadata={}, smart_scoring=False,
    )

    assert result["_provider_used"] == "P1"
    assert result["genres"] == ["FromSecond"], (
        "En fallback classique, P2 (2e de la liste) doit combler 'genres' avant P3, "
        "même si P3 a un meilleur score."
    )
    assert result["year"] == 1999


def test_tie_break_on_equal_score_uses_fallback_list_order(monkeypatch):
    def fetch_first(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "First", "summary": "S1", "_match_score": 0.80}

    def fetch_second(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Second", "summary": "S2", "_match_score": 0.80}

    scrapers = {
        "FIRST": _make_scraper("FIRST", fetch_first),
        "SECOND": _make_scraper("SECOND", fetch_second),
    }
    _install_fake_registry(monkeypatch, scrapers)

    result, used = metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["FIRST", "SECOND"], smart_fusion=False,
        library_type="Manga", existing_metadata={}, smart_scoring=True,
    )

    assert result["_provider_used"] == "FIRST", (
        "À score strictement égal, le provider le plus prioritaire de la liste de "
        "fallback (position la plus basse) doit gagner le départage."
    )


def test_candidate_without_explicit_score_defaults_to_accept_threshold(monkeypatch):
    """Un scraper communautaire non migré vers score_candidate() ne renvoie aucune clé
    `_match_score`. Il ne doit ni faire planter le tri, ni être injustement favorisé/
    défavorisé : il est traité comme "juste accepté" (MATCH_ACCEPT_THRESHOLD)."""
    def no_score_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Legacy Match", "summary": "Résumé Legacy"}  # pas de _match_score

    def scored_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Scored Match", "summary": "Résumé Scoré", "_match_score": MATCH_ACCEPT_THRESHOLD + 0.30}

    scrapers = {
        "NO_SCORE": _make_scraper("NO_SCORE", no_score_fetch),
        "SCORED": _make_scraper("SCORED", scored_fetch),
    }
    _install_fake_registry(monkeypatch, scrapers)

    result, used = metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["NO_SCORE", "SCORED"], smart_fusion=False,
        library_type="Manga", existing_metadata={}
    )

    assert result["_provider_used"] == "SCORED", (
        "Un candidat explicitement mieux scoré doit l'emporter sur un candidat sans "
        "score (traité comme juste accepté, pas comme automatiquement gagnant)."
    )


@pytest.mark.parametrize("bad_score", [None, "not-a-number", True, False, [], {}, float("nan")])
def test_malformed_match_score_does_not_crash_pipeline(monkeypatch, bad_score):
    """Filet de sécurité pour les scrapers communautaires : un `_match_score` mal formé
    ne doit JAMAIS faire planter le tri Smart Scoring (TypeError / comparaison invalide)."""
    def bad_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Broken Custom", "summary": "S", "_match_score": bad_score}

    def good_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Good Official", "summary": "S2", "_match_score": 0.90}

    scrapers = {
        "BAD": _make_scraper("BAD", bad_fetch),
        "GOOD": _make_scraper("GOOD", good_fetch),
    }
    _install_fake_registry(monkeypatch, scrapers)

    result, used = metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["BAD", "GOOD"], smart_fusion=False,
        library_type="Manga", existing_metadata={}
    )

    assert result is not None
    assert result["_provider_used"] == "GOOD"


def test_candidate_without_explicit_score_still_wins_alone(monkeypatch):
    """S'il n'y a aucun autre candidat, l'absence de `_match_score` ne doit pas
    empêcher le seul candidat trouvé de devenir le vainqueur."""
    def no_score_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Legacy Match", "summary": "Résumé Legacy"}

    scrapers = {"NO_SCORE": _make_scraper("NO_SCORE", no_score_fetch)}
    _install_fake_registry(monkeypatch, scrapers)

    result, used = metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["NO_SCORE"], smart_fusion=False,
        library_type="Manga", existing_metadata={}
    )

    assert result is not None
    assert result["_provider_used"] == "NO_SCORE"


def test_smart_completion_fills_gaps_from_highest_to_lowest_score(monkeypatch):
    """`providers_list` est délibérément dans le désordre par rapport aux scores, pour
    prouver que le remplissage suit l'ordre de SCORE et non l'ordre brut de la liste."""
    def high_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "T", "summary": "Résumé du champion", "_match_score": 0.95}

    def med_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "T", "genres": ["MedGenre"], "year": 2020, "_match_score": 0.70}

    def low_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "T", "genres": ["LowGenre"], "year": 1999, "_match_score": 0.65}

    scrapers = {
        "P_LOW": _make_scraper("P_LOW", low_fetch),
        "P_MED": _make_scraper("P_MED", med_fetch),
        "P_HIGH": _make_scraper("P_HIGH", high_fetch),
    }
    _install_fake_registry(monkeypatch, scrapers)

    # Ordre de fallback INVERSE de l'ordre des scores : P_LOW est en position #1
    # (aurait gagné avec l'ancien comportement "premier accepté = vainqueur").
    result, used = metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["P_LOW", "P_MED", "P_HIGH"], smart_fusion=True,
        library_type="Manga", existing_metadata={}
    )

    assert result["_provider_used"] == "P_HIGH", "Le meilleur score doit rester la base."
    assert result["genres"] == ["MedGenre"], (
        "P_MED (score 0.70) doit combler 'genres' avant P_LOW (score 0.65), même si "
        "P_LOW est prioritaire dans la liste de fallback brute."
    )
    assert result["year"] == 2020, "Idem pour 'year' : comblé par P_MED avant P_LOW."
    assert result["_fusion_providers"] == ["P_MED"], (
        "P_LOW ne doit plus rien avoir à combler : 'genres' et 'year' ont déjà été "
        "remplis par P_MED (meilleur score) avant que P_LOW ne soit examiné dans la boucle."
    )


def test_providers_after_the_first_run_in_parallel_not_sequentially(monkeypatch):
    starts = {}
    ends = {}
    lock = threading.Lock()

    def make_fetch(name, delay):
        def _fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
            with lock:
                starts[name] = time.time()
            time.sleep(delay)
            with lock:
                ends[name] = time.time()
            return {"title": name, "summary": "S", "_match_score": 0.70}
        return _fetch

    delay = 0.3
    scrapers = {
        "P1": _make_scraper("P1", make_fetch("P1", delay)),
        "P2": _make_scraper("P2", make_fetch("P2", delay)),
        "P3": _make_scraper("P3", make_fetch("P3", delay)),
    }
    _install_fake_registry(monkeypatch, scrapers)

    t0 = time.time()
    result, used = metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["P1", "P2", "P3"], smart_fusion=False,
        library_type="Manga", existing_metadata={}
    )
    elapsed = time.time() - t0

    assert result is not None
    # 3 appels séquentiels de 0.3s ≈ 0.9s. P1 seul (0.3s) + P2/P3 en parallèle (0.3s) ≈ 0.6s.
    assert elapsed < (delay * 3) - 0.15, (
        f"Exécution trop lente ({elapsed:.2f}s) : la vague 2 (P2/P3) ne semble plus "
        "s'exécuter en parallèle."
    )
    assert starts.keys() == {"P1", "P2", "P3"}
    assert abs(starts["P2"] - starts["P3"]) < 0.15, (
        "P2 et P3 doivent démarrer quasiment au même instant (vague parallèle)."
    )
    assert starts["P2"] >= ends["P1"] - 0.05, (
        "P2 doit démarrer seulement après que P1 (vague séquentielle) ait terminé."
    )


@pytest.mark.parametrize("raw,expected", [
    (None, MATCH_ACCEPT_THRESHOLD),
    ("oops", MATCH_ACCEPT_THRESHOLD),
    (True, MATCH_ACCEPT_THRESHOLD),
    ([], MATCH_ACCEPT_THRESHOLD),
    (0.95, 0.95),
    ("0.80", 0.80),
    (1.5, 1.0),
    (-0.2, 0.0),
])
def test_safe_match_score_coerces_and_clamps(raw, expected):
    assert metadata_fetcher._safe_match_score({"_match_score": raw}) == expected
    assert metadata_fetcher._safe_match_score({}) == MATCH_ACCEPT_THRESHOLD


def test_first_provider_context_is_shared_with_the_parallel_wave(monkeypatch):
    """L'ISBN trouvé par le provider #1 (vague séquentielle) doit être visible dans
    `existing_metadata` reçu par les providers de la vague parallèle suivante."""
    captured = {}

    def p1_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "A", "summary": "S", "isbn": "9780000000001", "_match_score": 0.90}

    def p2_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        captured["p2_existing_isbn"] = (existing_metadata or {}).get("isbn")
        return {"title": "B", "summary": "S2", "_match_score": 0.80}

    scrapers = {
        "P1": _make_scraper("P1", p1_fetch),
        "P2": _make_scraper("P2", p2_fetch),
    }
    _install_fake_registry(monkeypatch, scrapers)

    metadata_fetcher.fetch_metadata(
        query="Query", providers_list=["P1", "P2"], smart_fusion=False,
        library_type="Manga", existing_metadata={}
    )

    assert captured.get("p2_existing_isbn") == "9780000000001", (
        "Le contexte (ISBN) trouvé par le provider #1 doit être transmis à la vague "
        "parallèle suivante, pour préserver la protection anti-homonyme sur les séries "
        "sans métadonnées Kavita pré-existantes."
    )


def test_return_candidates_parallel_when_scoring_is_off(monkeypatch):
    """Manual / Super Review : vague 2 parallèle même si Smart Scoring est off."""
    lock = threading.Lock()
    starts = {}
    ends = {}

    def make_fetch(name, delay):
        def _fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
            with lock:
                starts[name] = time.time()
            time.sleep(delay)
            with lock:
                ends[name] = time.time()
            return {"title": name, "summary": "S", "_match_score": 0.70}
        return _fetch

    delay = 0.25
    scrapers = {
        "P1": _make_scraper("P1", make_fetch("P1", delay)),
        "P2": _make_scraper("P2", make_fetch("P2", delay)),
        "P3": _make_scraper("P3", make_fetch("P3", delay)),
    }
    _install_fake_registry(monkeypatch, scrapers)

    t0 = time.time()
    result, used = metadata_fetcher.fetch_metadata(
        query="Query",
        providers_list=["P1", "P2", "P3"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=False,
        return_candidates=True,
    )
    elapsed = time.time() - t0
    assert isinstance(result, dict)
    assert set(used) == {"P1", "P2", "P3"}
    assert elapsed < (delay * 3) - 0.15
    assert abs(starts["P2"] - starts["P3"]) < 0.15
    assert starts["P2"] >= ends["P1"] - 0.05


def test_cascade_blobs_are_attached_for_mapping_reuse(monkeypatch):
    def p1_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "A", "summary": "from P1", "_match_score": 0.70}

    def p2_fetch(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "B", "summary": "from P2", "cover_url": "http://p2.jpg", "_match_score": 0.90}

    scrapers = {
        "P1": _make_scraper("P1", p1_fetch),
        "P2": _make_scraper("P2", p2_fetch),
    }
    _install_fake_registry(monkeypatch, scrapers)

    result, used = metadata_fetcher.fetch_metadata(
        query="Query",
        providers_list=["P1", "P2"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
    )
    blobs = (result or {}).get("_cascade_blobs") or {}
    assert set(used) >= {"P2"}
    assert "P2" in blobs
    assert blobs["P2"]["blob"]["cover_url"] == "http://p2.jpg"
    assert blobs["P2"]["is_id"] is False
    assert blobs["P2"]["query"] == "Query"
