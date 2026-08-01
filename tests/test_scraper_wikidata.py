"""
Tests Wikidata scraper : mapping claims, extract_id, live mocké.
"""
from unittest.mock import patch

from scrapers.wikidata import WikidataScraper
from scrapers.wikidata_map import (
    commons_file_url,
    entity_to_candidate,
    normalize_qid,
)


SAMPLE_ENTITY = {
    "id": "Q12345",
    "labels": {
        "en": {"language": "en", "value": "Attack on Titan"},
        "fr": {"language": "fr", "value": "L'Attaque des Titans"},
        "ja": {"language": "ja", "value": "進撃の巨人"},
    },
    "descriptions": {
        "en": {"language": "en", "value": "Japanese manga series"},
    },
    "aliases": {
        "en": [{"language": "en", "value": "Shingeki no Kyojin"}],
    },
    "claims": {
        "P31": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": {"id": "Q8274"}, "type": "wikibase-entityid"},
                }
            }
        ],
        "P577": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {
                        "value": {"time": "+2009-09-09T00:00:00Z", "precision": 11},
                        "type": "time",
                    },
                }
            }
        ],
        "P50": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": {"id": "Q999"}, "type": "wikibase-entityid"},
                }
            }
        ],
        "P123": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": {"id": "Q888"}, "type": "wikibase-entityid"},
                }
            }
        ],
        "P18": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": "Attack on Titan vol1 cover.jpg", "type": "string"},
                }
            }
        ],
        "P212": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": "978-4-06-384276-0", "type": "string"},
                }
            }
        ],
        "P8729": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": "53390", "type": "string"},
                }
            }
        ],
        "P4087": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": "81345", "type": "string"},
                }
            }
        ],
    },
}


def test_normalize_qid_variants():
    assert normalize_qid("Q42") == "Q42"
    assert normalize_qid("q42") == "Q42"
    assert normalize_qid("https://www.wikidata.org/wiki/Q42") == "Q42"
    assert normalize_qid("42") == "Q42"
    assert normalize_qid("") is None


def test_commons_file_url_encodes_spaces():
    url = commons_file_url("Foo Bar.jpg")
    assert "Special:FilePath/" in url
    assert "Foo" in url


def test_entity_to_candidate_mapping():
    cand = entity_to_candidate(
        SAMPLE_ENTITY,
        label_lookup={"Q999": "Hajime Isayama", "Q888": "Kodansha"},
        library_type="Manga",
    )
    assert cand is not None
    assert cand["title"] == "Attack on Titan"
    assert cand["year"] == 2009
    assert cand["publisher"] == "Kodansha"
    assert cand["staff"][0]["node"]["name"]["full"] == "Hajime Isayama"
    assert cand["isbn"] == "9784063842760"
    assert cand["anilist_id"] == 53390
    assert cand["mal_id"] == 81345
    assert cand["wikidata_id"] == "Q12345"
    assert "commons.wikimedia.org" in cand["cover_url"]
    assert any(t["lang"] == "fr" for t in cand["titles"])


def test_resolve_cover_none_without_p18():
    """Sans P18 Wikidata, pas de fallback externe — cover_url reste None."""
    from scrapers.wikidata_map import resolve_cover_url

    entity = {
        "id": "Q1",
        "claims": {
            "P212": [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "datavalue": {"value": "978-0-441-17271-9", "type": "string"},
                    }
                }
            ]
        },
    }
    assert resolve_cover_url(entity) is None


def test_extract_id_from_url():
    s = WikidataScraper()
    assert s.extract_id_from_url("https://www.wikidata.org/wiki/Q12345") == "Q12345"
    assert s.extract_id_from_url("Q99") == "Q99"
    assert s.extract_id_from_url("https://anilist.co/manga/1") is None


def test_scraper_metadata_contract():
    s = WikidataScraper()
    assert s.id == "WIKIDATA"
    assert s.supported_types == {"Manga", "Comic", "Book"}
    assert s.has_direct_id_support is True
    assert s.uses_unified_scoring is True
    assert s.needs_api_key is False


@patch.object(WikidataScraper, "_wbgetentities")
@patch.object(WikidataScraper, "_label_lookup", return_value={"Q999": "Hajime Isayama", "Q888": "Kodansha"})
def test_fetch_direct_id_live(mock_labels, mock_wb):
    mock_wb.return_value = {"Q12345": SAMPLE_ENTITY}
    s = WikidataScraper()
    result = s.fetch("Q12345", library_type="Manga", is_id=True)
    assert result is not None
    assert result["wikidata_id"] == "Q12345"
    assert result["_match_score"] == 1.0
    assert result["title"] == "Attack on Titan"
