"""
Non-régression : fallback_query après échec d'ID forcé (H1).
"""
from metadata_fetcher import fetch_metadata


def test_forced_id_failure_retries_fallback_query(mocker):
    calls = []

    class FakeScraper:
        id = "FAKE"
        supported_types = {"Manga"}
        rate_limit = 0
        uses_unified_scoring = True

        def extract_id_from_url(self, url):
            return None

        def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
            calls.append({"query": query, "is_id": is_id})
            if is_id:
                return None
            return {
                "title": query,
                "summary": "ok",
                "genres": ["Action"],
                "_match_score": 0.9,
            }

    fake = FakeScraper()
    mocker.patch("metadata_fetcher.ScraperRegistry.get", return_value=fake)
    mocker.patch("metadata_fetcher.load_config", return_value={
        "UI_LANG": "fr",
        "SMART_SCORING": False,
        "TITLE_FALLBACK_TRANSLATION": False,
    })
    mocker.patch("metadata_fetcher.throttle_provider")

    data, used = fetch_metadata(
        "999999",
        ["FAKE"],
        smart_fusion=False,
        fallback_query="One Piece",
        library_type="Manga",
        is_forced_id=True,
        smart_scoring=False,
    )

    assert data is not None
    assert data["title"] == "One Piece"
    assert any(c["is_id"] is True and c["query"] == "999999" for c in calls)
    assert any(c["is_id"] is False and c["query"] == "One Piece" for c in calls)
