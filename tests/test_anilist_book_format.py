"""AniList Book cascade only accepts Media format NOVEL."""
from scrapers.anilist import AnilistScraper


def test_library_allows_book_requires_novel():
    s = AnilistScraper()
    assert s._library_allows({"format": "NOVEL"}, "Book") is True
    assert s._library_allows({"format": "MANGA"}, "Book") is False
    assert s._library_allows({"format": "ONE_SHOT"}, "Book") is False
    assert s._library_allows({"format": "MANGA"}, "Manga") is True
    assert s._library_allows({"format": "MANGA"}, "Comic") is True
    assert s._library_allows({}, "Manga") is True


def test_build_candidate_novel_sets_book_format():
    s = AnilistScraper()
    cand = s._build_candidate(
        {
            "id": 1,
            "idMal": None,
            "title": {"romaji": "Dune LN", "english": "Dune", "native": None},
            "description": "x",
            "coverImage": {"extraLarge": None},
            "format": "NOVEL",
            "genres": [],
            "tags": [],
            "startDate": {"year": 1965},
            "status": "FINISHED",
            "isAdult": False,
            "countryOfOrigin": "US",
            "staff": {"edges": []},
            "characters": {"edges": []},
            "externalLinks": [],
        }
    )
    assert cand["format"] == "book"
    assert cand["age_rating"] == ""
