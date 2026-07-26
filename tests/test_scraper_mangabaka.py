"""
Non-régression : MangaBaka renvoie un statut brut en minuscules ("completed",
"releasing", "hiatus", "cancelled") qui ne correspondait à aucune clé du
mapping de statut historiquement inline dans app.py (qui attendait "FINISHED").
Résultat en production : les séries terminées scrapées via MangaBaka restaient
silencieusement marquées "En cours" dans Kavita.

Le mapping vit maintenant dans kavita_constants.normalize_provider_status(),
utilisé à la fois par scrapers/mangabaka.py et potentiellement par d'autres
fournisseurs à l'avenir.
"""
import pytest

from kavita_constants import normalize_provider_status
from scrapers.mangabaka import MangaBakaScraper


def test_mangabaka_supports_manga_and_book():
    assert MangaBakaScraper.supported_types == {"Manga", "Book"}


@pytest.mark.parametrize("raw_status,expected", [
    ("completed", "FINISHED"),
    ("Completed", "FINISHED"),
    ("finished", "FINISHED"),
    ("releasing", "RELEASING"),
    ("ongoing", "RELEASING"),
    ("hiatus", "HIATUS"),
    ("cancelled", "CANCELLED"),
    ("canceled", "CANCELLED"),
])
def test_normalize_provider_status_known_values(raw_status, expected):
    assert normalize_provider_status(raw_status) == expected


def test_normalize_provider_status_unknown_value_returns_none():
    assert normalize_provider_status("some_unknown_status") is None


def test_normalize_provider_status_empty_value_returns_none():
    assert normalize_provider_status(None) is None
    assert normalize_provider_status("") is None


def test_mangabaka_build_candidate_maps_completed_to_finished():
    scraper = MangaBakaScraper()

    candidate = scraper._build_candidate({
        "id": 123,
        "name": "One Piece",
        "status": "completed",
    }, pub_pref="LOCALIZED")

    assert candidate is not None
    assert candidate["status"] == "FINISHED"


def test_mangabaka_build_candidate_unknown_status_is_none():
    scraper = MangaBakaScraper()

    candidate = scraper._build_candidate({
        "id": 123,
        "name": "Some Series",
        "status": "totally_unknown",
    }, pub_pref="LOCALIZED")

    assert candidate is not None
    assert candidate["status"] is None


def test_mangabaka_schema_full_splits_genres_and_tags_via_is_genre():
    scraper = MangaBakaScraper()
    candidate = scraper._build_candidate({
        "id": 1,
        "name": "Test",
        "tags": [
            {"name": "Action", "is_genre": True},
            {"name": "Time Travel", "is_genre": False},
            {"name": "Drama", "is_genre": True},
        ],
        "source": {
            "anilist": {"id": 10},
            "my_anime_list": {"id": 20},
        },
        "links": [{"url": "https://example.com/a"}, "https://example.com/b"],
        "type": "novel",
    }, pub_pref="LOCALIZED")

    assert candidate["genres"] == ["Action", "Drama"]
    assert candidate["tags"] == ["Time Travel"]
    assert candidate["anilist_id"] == 10
    assert candidate["mal_id"] == 20
    assert candidate["links"] == ["https://example.com/a", "https://example.com/b"]
    assert candidate["format"] == "book"


def test_mangabaka_legacy_separate_genres_tags_still_work():
    scraper = MangaBakaScraper()
    candidate = scraper._build_candidate({
        "id": 2,
        "name": "Legacy",
        "genres": [{"name": "Comedy"}, "Romance"],
        "tags": [{"name": "School"}, "Slice of Life"],
        "source": {"mal": {"id": 99}},
    }, pub_pref="LOCALIZED")

    assert candidate["genres"] == ["Comedy", "Romance"]
    assert candidate["tags"] == ["School", "Slice of Life"]
    assert candidate["mal_id"] == 99


def test_mangabaka_search_passes_type_and_schema_full(monkeypatch):
    scraper = MangaBakaScraper()
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"data": []}

    def fake_get(url, params=None, timeout=10):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr("scrapers.mangabaka.requests.get", fake_get)
    monkeypatch.setattr("scrapers.mangabaka.load_config", lambda: {})

    assert scraper.fetch("Some LN", library_type="Book") is None
    assert captured["params"]["schema"] == "full"
    assert captured["params"]["type"] == "novel"

    assert scraper.fetch("Some Manga", library_type="Manga") is None
    assert captured["params"]["type"] == ["manga", "manhwa", "manhua"]
