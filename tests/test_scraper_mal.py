"""Tests scraper MyAnimeList (API officielle v2)."""
from unittest.mock import patch

from scrapers.mal import MalScraper, MANGA_FIELDS


SAMPLE_NODE = {
    "id": 2,
    "title": "Berserk",
    "main_picture": {
        "medium": "https://cdn.myanimelist.net/images/manga/1/157931.jpg",
        "large": "https://cdn.myanimelist.net/images/manga/1/157931l.jpg",
    },
    "alternative_titles": {
        "synonyms": ["Berserk: The Prototype"],
        "en": "Berserk",
        "ja": "ベルセルク",
    },
    "start_date": "1989-08-25",
    "synopsis": "Guts, a former mercenary now known as the Black Swordsman...",
    "media_type": "manga",
    "status": "currently_publishing",
    "genres": [{"id": 1, "name": "Action"}, {"id": 8, "name": "Drama"}],
    "nsfw": "white",
    "authors": [
        {
            "node": {"id": 1868, "first_name": "Kentaro", "last_name": "Miura"},
            "role": "Story & Art",
        }
    ],
    "serialization": [{"node": {"id": 17, "name": "Young Animal"}}],
}


def test_extract_id_from_url():
    s = MalScraper()
    assert s.extract_id_from_url("https://myanimelist.net/manga/2/Berserk") == "2"
    assert s.extract_id_from_url("https://myanimelist.net/manga/2") == "2"
    assert s.extract_id_from_url("https://example.com/manga/2") is None
    assert s.extract_id_from_url("") is None


def test_build_candidate_maps_fields():
    s = MalScraper()
    cand = s._build_candidate(SAMPLE_NODE)
    assert cand is not None
    assert cand["title"] == "Berserk"
    assert cand["mal_id"] == 2
    assert cand["year"] == 1989
    assert cand["status"] == "RELEASING"
    assert cand["publisher"] == "Young Animal"
    assert cand["format"] == "manga"
    assert cand["age_rating"] == "safe"
    assert "Action" in cand["genres"]
    assert any(st["node"]["name"]["full"] == "Kentaro Miura" for st in cand["staff"])
    assert cand["cover_url"].endswith("157931l.jpg")
    assert "ベルセルク" in cand["alternative_titles"]


def test_map_age_bf56_omit_when_nsfw_absent():
    s = MalScraper()
    assert s._map_age(None) is None
    assert s._map_age("") is None
    assert s._map_age("white") == "safe"
    assert s._map_age("gray") == "suggestive"
    assert s._map_age("black") == "pornographic"
    node = dict(SAMPLE_NODE)
    del node["nsfw"]
    cand = s._build_candidate(node)
    assert cand["age_rating"] == ""


def test_media_ok_filters_novels_for_manga_lib():
    s = MalScraper()
    assert s._media_ok("manga", "Manga") is True
    assert s._media_ok("light_novel", "Manga") is False
    assert s._media_ok("light_novel", "Book") is True
    assert s._media_ok("manga", "Book") is False


def test_fetch_requires_client_id():
    s = MalScraper()
    with patch("scrapers.mal.load_config", return_value={}):
        assert s.fetch("Berserk") is None


def test_fetch_by_id_mocked():
    s = MalScraper()
    with patch("scrapers.mal.load_config", return_value={"MAL_API_KEY": "test-client"}):
        with patch.object(s, "_get", return_value=SAMPLE_NODE) as get_mock:
            result = s.fetch("2", is_id=True)
            assert result is not None
            assert result["mal_id"] == 2
            assert result["_match_score"] == 1.0
            get_mock.assert_called_once()
            path, client_id, params = get_mock.call_args[0]
            assert path == "/manga/2"
            assert client_id == "test-client"
            assert params.get("fields") == MANGA_FIELDS


def test_fetch_search_scores_and_threshold():
    s = MalScraper()
    search_payload = {"data": [{"node": SAMPLE_NODE}]}
    with patch("scrapers.mal.load_config", return_value={"MAL_API_KEY": "test-client"}):
        with patch.object(s, "_get", return_value=search_payload):
            with patch("scrapers.mal.score_candidate", return_value=0.95):
                with patch("scrapers.mal.get_match_accept_threshold", return_value=0.60):
                    result = s.fetch("Berserk", library_type="Manga")
                    assert result is not None
                    assert result["title"] == "Berserk"
                    assert result["_match_score"] == 0.95


def test_fetch_search_rejects_below_threshold():
    s = MalScraper()
    search_payload = {"data": [{"node": SAMPLE_NODE}]}
    with patch("scrapers.mal.load_config", return_value={"MAL_API_KEY": "test-client"}):
        with patch.object(s, "_get", return_value=search_payload):
            with patch("scrapers.mal.score_candidate", return_value=0.40):
                with patch("scrapers.mal.get_match_accept_threshold", return_value=0.60):
                    assert s.fetch("Berserk") is None


def test_fetch_covers_mocked():
    s = MalScraper()
    payload = {
        "data": [{
            "node": {
                "id": 2,
                "title": "Berserk",
                "media_type": "manga",
                "main_picture": {"large": "https://cdn.myanimelist.net/x.jpg"},
            }
        }]
    }
    with patch("scrapers.mal.load_config", return_value={"MAL_API_KEY": "test-client"}):
        with patch.object(s, "_get", return_value=payload):
            covers = s.fetch_covers("Berserk")
            assert len(covers) == 1
            assert covers[0]["provider"] == "MyAnimeList"
            assert covers[0]["url"].endswith("x.jpg")
