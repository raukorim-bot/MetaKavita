"""
Non-régression : le seuil d'acceptation d'un candidat scoré était recopié en dur (literal)
dans chaque scraper — `0.50` pour la plupart, `0.60` pour Hardcover/OpenLibrary, et même `0.45`
pour Manga-News/Shikimori. `0.50` (et a fortiori `0.45`) a été testé en usage réel et générait
trop de faux positifs (homonymes, spin-offs acceptés à tort) ; `0.60` est la valeur validée.
Elle est maintenant centralisée dans `scrapers/utils.py::MATCH_ACCEPT_THRESHOLD` (défaut 0.60)
et lue à l'exécution via `get_match_accept_threshold()` (Baromètre de fiabilité).

Historiquement, MangaDex/MangaUpdates/Manga-News/Shikimori avaient chacun leur propre
heuristique titre-seul (sans comparaison d'auteur, donc sans protection anti-homonyme). Ils ont
depuis été migrés pour construire un candidat complet (avec staff) et appeler `score_candidate()`
comme les 5 autres scrapers — voir `tests/test_scraper_score_migration.py` pour la preuve que
leur staff est bien dans la forme attendue par la matrice unifiée. Les scrapers concernés sont
donc désormais homogènes : ce test vérifie que chacun importe le getter partagé plutôt
qu'un literal recopié qui pourrait dériver silencieusement.
"""
import importlib

from scrapers.utils import MATCH_ACCEPT_THRESHOLD

# Scrapers officiels qui appellent score_candidate() pour évaluer leurs candidats.
SCORE_CANDIDATE_MODULES = [
    "scrapers.mangabaka",
    "scrapers.anilist",
    "scrapers.googlebooks",
    "scrapers.hardcover",
    "scrapers.openlibrary",
    "scrapers.mangadex",
    "scrapers.mangaupdates",
    "scrapers.manganews",
    "scrapers.shikimori",
    "scrapers.kitsu",
    "scrapers.comicvine",
    "scrapers.bedetheque",
    "scrapers.wikidata",
    "scrapers.mal",
]


def test_match_accept_threshold_is_the_validated_value():
    assert MATCH_ACCEPT_THRESHOLD == 0.60


def test_all_score_candidate_scrapers_import_shared_threshold_getter():
    for module_name in SCORE_CANDIDATE_MODULES:
        module = importlib.import_module(module_name)
        assert hasattr(module, "get_match_accept_threshold"), (
            f"{module_name} doit importer scrapers.utils.get_match_accept_threshold "
            "au lieu de comparer à un literal / à la constante seule."
        )


def test_all_score_candidate_scrapers_actually_import_score_candidate():
    """Garde-fou léger contre une régression qui reviendrait à une heuristique maison sans
    passer par la matrice unifiée (le bug corrigé pour ces 4 scrapers)."""
    for module_name in SCORE_CANDIDATE_MODULES:
        module = importlib.import_module(module_name)
        assert hasattr(module, "score_candidate"), (
            f"{module_name} doit importer scrapers.utils.score_candidate."
        )


def test_all_score_candidate_scrapers_import_attach_match_score():
    """Sans attach_match_score(), le Smart Scoring retombe sur un score neutre et les
    scrapers officiels perdraient silencieusement leur avantage comparatif."""
    for module_name in SCORE_CANDIDATE_MODULES:
        module = importlib.import_module(module_name)
        assert hasattr(module, "attach_match_score"), (
            f"{module_name} doit importer scrapers.utils.attach_match_score."
        )


def test_all_score_candidate_scrapers_declare_uses_unified_scoring():
    """Les scrapers officiels basés sur score_candidate() doivent déclarer
    `uses_unified_scoring = True` sur leur classe (contrat BaseScraper)."""
    from scrapers import ScraperRegistry

    expected_ids = {
        "MANGABAKA", "ANILIST", "GOOGLEBOOKS", "HARDCOVER", "OPENLIBRARY",
        "MANGADEX", "MANGAUPDATES", "MANGANEWS", "SHIKIMORI",
        "KITSU", "COMICVINE", "BEDETHEQUE", "BDTHEQUE", "WIKIDATA", "MAL",
    }
    for scraper_id in expected_ids:
        scraper = ScraperRegistry.get(scraper_id)
        assert scraper is not None, f"Scraper officiel {scraper_id} introuvable dans le registre"
        assert getattr(scraper, "uses_unified_scoring", False) is True, (
            f"{scraper_id} doit déclarer uses_unified_scoring = True"
        )


def test_base_scraper_defaults_uses_unified_scoring_to_false():
    """Un scraper communautaire qui n'opt-in pas explicitement doit rester compatible
    (False par défaut) sans casser le pipeline."""
    from scrapers.base import BaseScraper

    assert BaseScraper.uses_unified_scoring is False
