"""Hardcover ISBN Typesense hits must enter candidate_docs (not log-only)."""
from unittest.mock import MagicMock, patch

from scrapers.hardcover import HardcoverScraper


def test_isbn_hits_appended_and_returned():
    scraper = HardcoverScraper()
    isbn_doc = {
        "title": "Dune",
        "description": "Sand",
        "release_year": 1965,
        "isbn_13": "9780441172719",
        "author_names": ["Frank Herbert"],
        "slug": "dune",
        "id": 42,
        "image": {"url": "https://img.hardcover.app/dune.jpg"},
    }
    isbn_payload = {
        "data": {
            "search": {
                "results": {
                    "hits": [{"document": isbn_doc}],
                }
            }
        }
    }

    mock_session = MagicMock()
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = isbn_payload
    mock_session.post.return_value = mock_res

    with patch("scrapers.hardcover.load_config", return_value={"HARDCOVER_API_KEY": "tok"}):
        with patch("scrapers.hardcover.requests.Session", return_value=mock_session):
            with patch.object(
                scraper,
                "_build_candidate",
                return_value={
                    "title": "Dune",
                    "summary": "Sand",
                    "year": 1965,
                    "staff": [{"role": "Story", "node": {"name": {"full": "Frank Herbert"}}}],
                    "isbn": "9780441172719",
                },
            ):
                result = scraper.fetch(
                    "Dune",
                    library_type="Book",
                    is_id=False,
                    existing_metadata={"isbn": "9780441172719"},
                )

    assert result is not None
    assert result["title"] == "Dune"
    mock_session.post.assert_called()
    # ISBN path should not fall through to a second title search when hits exist
    assert mock_session.post.call_count == 1
