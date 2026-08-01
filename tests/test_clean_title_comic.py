"""
BF54 — clean_title Comic doit retirer les années de run Kavita Flexible
("(YYYY)", "(2012-)") du titre de recherche, tout en les exposant via
extract_year_from_title pour le ranking ComicVine / score_candidate.
"""
import pytest

from scrapers.utils import apply_title_year_hint, clean_title, extract_year_from_title
from scrapers.comicvine import ComicVineScraper


@pytest.mark.parametrize(
    "raw, expected_clean, expected_year",
    [
        ("Batman (2025)", "Batman", 2025),
        ("Saga (2012-)", "Saga", 2012),
        ("Spawn (1992–)", "Spawn", 1992),
        ("Y: The Last Man", "Y: The Last Man", None),
        ("DC/Marvel: Batman/Deadpool (168592)", "DC/Marvel: Batman/Deadpool", None),
        ("Gold Digger (Antarctic Press, 1992–)", "Gold Digger", None),
        ("Blade Runner 2049", "Blade Runner 2049", None),
    ],
)
def test_comic_clean_title_strips_run_year(raw, expected_clean, expected_year):
    assert clean_title(raw, library_type="Comic") == expected_clean
    assert extract_year_from_title(raw) == expected_year


def test_manga_clean_title_unchanged_for_parens():
    """Branche Manga : tous les ( … ) partent ; pas de régression Flexible→Manga."""
    assert clean_title("Batman (2025)", library_type="Manga") == "Batman"
    assert clean_title("One Piece", library_type="Manga") == "One Piece"


def test_apply_title_year_hint_fills_missing_only():
    meta = {"year": None}
    apply_title_year_hint(meta, "Batman (2025)")
    assert meta["year"] == 2025

    meta2 = {"year": 1966}
    apply_title_year_hint(meta2, "Batman (2025)")
    assert meta2["year"] == 1966  # Kavita releaseYear wins


def test_comicvine_prefers_start_year_matching_hint():
    scraper = ComicVineScraper()
    volumes = [
        {"name": "Batman", "start_year": "1966", "count_of_issues": 50, "publisher": {"name": "DC Comics"}},
        {"name": "Batman", "start_year": "2025", "count_of_issues": 10, "publisher": {"name": "DC Comics"}},
    ]
    chosen = scraper._evaluate_volume_candidates(volumes, "Batman", year_hint=2025)
    assert chosen is not None
    assert str(chosen["start_year"]) == "2025"


def test_comicvine_without_hint_still_picks_a_volume():
    scraper = ComicVineScraper()
    volumes = [
        {"name": "Batman", "start_year": "1966", "count_of_issues": 50, "publisher": {"name": "DC Comics"}},
        {"name": "Batman", "start_year": "2025", "count_of_issues": 10, "publisher": {"name": "DC Comics"}},
    ]
    chosen = scraper._evaluate_volume_candidates(volumes, "Batman", year_hint=None)
    assert chosen is not None
    # Sans hint : plus d'issues + publisher → 1966 gagne (comportement historique).
    assert str(chosen["start_year"]) == "1966"
