"""BF56 — Age safeguarding: do not invent/under-rate age_rating before lock."""
from scrapers.bdtheque import BdthequeScraper
from services.kavita_payload import build_kavita_payload
from kavita_constants import AGE_RATING_MAP


def test_bdtheque_parse_age_adult_is_erotica_not_teen():
    s = BdthequeScraper()
    assert s._parse_age("Érotique") == "erotica"
    assert s._parse_age("Adulte") == "erotica"
    assert s._parse_age("Pour adultes") == "erotica"
    assert AGE_RATING_MAP[s._parse_age("Érotique")] == 12  # R18+


def test_bdtheque_parse_age_ados_adultes_is_suggestive():
    """« Ados - Adultes » contains 'adulte' but is Teen+, not R18."""
    s = BdthequeScraper()
    assert s._parse_age("Ados - Adultes") == "suggestive"
    assert AGE_RATING_MAP["suggestive"] == 8


def test_bdtheque_parse_age_tout_public_and_unknown():
    s = BdthequeScraper()
    assert s._parse_age("Tout public") == "safe"
    assert s._parse_age("Jeunesse") == "safe"
    assert s._parse_age("") is None
    assert s._parse_age("Label inconnu XYZ") is None


def test_bdtheque_clifton_sample_gets_suggestive():
    from tests.test_scraper_bdtheque import SAMPLE_HTML

    s = BdthequeScraper()
    cand = s._parse_series_html(
        SAMPLE_HTML, "590/clifton", "https://www.bdtheque.com/series/590/clifton"
    )
    assert cand["age_rating"] == "suggestive"


def test_payload_skips_empty_age_rating():
    """Omitting age must not lock ageRating on Kavita."""
    result = build_kavita_payload(
        provider_data={"title": "X", "age_rating": "", "summary": "hello"},
        metadata={"seriesId": 1},
        active_fields=["age", "summary"],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    out_meta = result["metadata"]
    assert "ageRating" not in out_meta
    assert out_meta.get("ageRatingLocked") is not True


def test_payload_writes_erotica_from_bdtheque_vocab():
    result = build_kavita_payload(
        provider_data={"title": "X", "age_rating": "erotica"},
        metadata={"seriesId": 1},
        active_fields=["age"],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert result["metadata"]["ageRating"] == 12
    assert result["metadata"]["ageRatingLocked"] is True
