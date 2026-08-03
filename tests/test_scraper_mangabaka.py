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


def test_mangabaka_proxy_domains_allow_cover_cdn_hosts():
    """Issue #31: cover upload refused images.mangabaka.dev (API still emits .dev CDN)."""
    domains = set(MangaBakaScraper.proxy_domains)
    assert "images.mangabaka.dev" in domains
    assert "cdn.mangabaka.dev" in domains
    assert "images.mangabaka.org" in domains
    assert "api.mangabaka.org" in domains


@pytest.mark.parametrize("url,expected", [
    ("https://mangabaka.org/353334", "353334"),
    ("https://www.mangabaka.org/353334/", "353334"),
    ("https://mangabaka.dev/353334", "353334"),
    ("https://api.mangabaka.org/v2/series/353334", "353334"),
    ("https://anilist.co/manga/1", None),
])
def test_mangabaka_extract_id_from_url(url, expected):
    assert MangaBakaScraper().extract_id_from_url(url) == expected


def test_mangabaka_cover_url_from_dev_cdn_passes_allowlist():
    from url_allowlist import validate_proxied_image_url

    ok, reason, domain = validate_proxied_image_url(
        "https://images.mangabaka.dev/e/a/a/8/e/9/e/f/d8bb/47e3/a6ad/4e45a525f383",
        MangaBakaScraper.proxy_domains,
    )
    assert ok is True, reason
    assert domain == "images.mangabaka.dev"


def test_mangabaka_pick_cover_prefers_native_raw():
    scraper = MangaBakaScraper()
    url = scraper._pick_cover_url({
        "raw": "https://images.mangabaka.dev/e/a/a/8/path",
        "x350": "https://cdn.mangabaka.dev/imgproxy/plain/x350@1/abc",
    })
    assert url == "https://images.mangabaka.dev/e/a/a/8/path"


def test_mangabaka_pick_cover_falls_back_to_imgproxy_when_raw_is_third_party():
    """API sometimes puts AniList CDN in raw — stay on MangaBaka imgproxy instead."""
    scraper = MangaBakaScraper()
    url = scraper._pick_cover_url({
        "raw": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/b1.jpg",
        "original": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/b1.jpg",
        "x350": "https://cdn.mangabaka.dev/imgproxy/plain/x350@1/abc",
        "x250": "https://cdn.mangabaka.dev/imgproxy/plain/x250@1/abc",
    })
    assert url == "https://cdn.mangabaka.dev/imgproxy/plain/x350@1/abc"


def test_mangabaka_pick_cover_rejects_third_party_only():
    scraper = MangaBakaScraper()
    assert scraper._pick_cover_url({
        "raw": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/b1.jpg",
    }) is None
    assert scraper._pick_cover_url("https://s4.anilist.co/x.jpg") is None


def test_mangabaka_build_candidate_uses_imgproxy_fallback_for_cover():
    scraper = MangaBakaScraper()
    candidate = scraper._build_candidate({
        "id": 1,
        "name": "Test",
        "cover": {
            "raw": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/b1.jpg",
            "x250": "https://cdn.mangabaka.dev/imgproxy/plain/x250@1/abc",
        },
    }, pub_pref="LOCALIZED")
    assert candidate["cover_url"] == "https://cdn.mangabaka.dev/imgproxy/plain/x250@1/abc"


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
