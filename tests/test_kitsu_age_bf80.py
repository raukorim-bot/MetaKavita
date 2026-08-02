"""BF80 / #29 — Kitsu R ≠ R18; R maps to mature (Mature 17+), not pornographic."""

from scrapers.kitsu import KitsuScraper
from services.kavita_payload import build_kavita_payload


def _parse(attrs):
    scraper = KitsuScraper()
    return scraper._build_candidate({"id": "1", "attributes": attrs}, included=[])


def test_kitsu_r_is_mature_not_pornographic():
    """Made in Abyss-style: ageRating R, no guide → Mature 17+, not X18+."""
    data = _parse({"canonicalTitle": "Made in Abyss", "ageRating": "R", "ageRatingGuide": None})
    assert data["age_rating"] == "mature"
    payload = build_kavita_payload(
        data, {}, ["age"], {}, {}, True, 1,
    )
    assert payload["metadata"]["ageRating"] == 10
    assert payload["metadata"]["ageRatingLocked"] is True


def test_kitsu_r18_is_pornographic():
    data = _parse({"canonicalTitle": "Explicit", "ageRating": "R18"})
    assert data["age_rating"] == "pornographic"
    payload = build_kavita_payload(data, {}, ["age"], {}, {}, True, 1)
    assert payload["metadata"]["ageRating"] == 14


def test_kitsu_pg_g_unchanged():
    assert _parse({"ageRating": "PG"})["age_rating"] == "suggestive"
    assert _parse({"ageRating": "G"})["age_rating"] == "safe"


def test_kitsu_unknown_or_missing_age_omitted():
    assert _parse({"ageRating": ""})["age_rating"] == ""
    assert _parse({})["age_rating"] == ""
    assert _parse({"ageRating": "XYZ"})["age_rating"] == ""


def test_mature_not_explicit_adult_for_tiebreak():
    import metadata_fetcher
    assert metadata_fetcher._is_explicit_adult({"age_rating": "mature"}) is False
    assert metadata_fetcher._is_explicit_adult({"age_rating": "pornographic"}) is True
