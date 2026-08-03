"""BF62 — business silent `except Exception: pass` emit logging.debug + safe_exc_str."""
import logging

from secure_logging import safe_exc_str


def test_comicvine_cover_search_logs_debug(monkeypatch, caplog):
    from scrapers.comicvine import ComicVineScraper

    scraper = ComicVineScraper()
    monkeypatch.setattr(
        "scrapers.comicvine.load_config",
        lambda: {"COMICVINE_API_KEY": "cv-test-key"},
    )
    monkeypatch.setattr(
        "scrapers.comicvine.requests.get",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cv cover boom")),
    )

    with caplog.at_level(logging.DEBUG):
        covers = scraper.fetch_covers("Batman", library_type="Comic")

    assert covers == []
    assert "ComicVine cover search failed" in caplog.text
    assert "RuntimeError: cv cover boom" in caplog.text
    assert "cv-test-key" not in caplog.text


def test_googlebooks_cover_search_logs_debug(monkeypatch, caplog):
    from scrapers.googlebooks import GoogleBooksScraper

    scraper = GoogleBooksScraper()
    monkeypatch.setattr(
        "scrapers.googlebooks.load_config",
        lambda: {"GOOGLEBOOKS_API_KEY": "gb-test-key"},
    )
    monkeypatch.setattr(
        "scrapers.googlebooks.requests.get",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gb cover boom")),
    )

    with caplog.at_level(logging.DEBUG):
        covers = scraper.fetch_covers("Dune", library_type="Book")

    assert covers == []
    assert "GoogleBooks cover search failed" in caplog.text
    assert "RuntimeError: gb cover boom" in caplog.text


def test_mangabaka_format_type_logs_debug(caplog):
    from scrapers.mangabaka import MangaBakaScraper

    class _Boom:
        def __str__(self):
            raise RuntimeError("mb format boom")

    scraper = MangaBakaScraper()
    data = {
        "name": "Solo Leveling",
        # Non-matching type so detection falls through to tags/genres join.
        "type": "unknown",
        "tags": [{"name": _Boom()}],
        "genres": [],
        "authors": [],
        "artists": [],
        "publishers": [],
        "source": {},
        "links": [],
        "status": "completed",
    }

    with caplog.at_level(logging.DEBUG):
        candidate = scraper._build_candidate(data)

    assert candidate is not None
    assert "MangaBaka format_type detection failed" in caplog.text
    assert "RuntimeError: mb format boom" in caplog.text
    # Format detection failed → format stays None, candidate still built.
    assert candidate.get("format") is None


def test_enrichment_orphan_purge_logs_debug(mocker, isolated_db, caplog):
    from services import enrichment_engine
    from kavita_api import KavitaAPI

    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value={
            "KAVITA_URL": "http://kavita.local",
            "KAVITA_API_KEY": "k",
            "UI_LANG": "fr",
            "MANUAL_REVIEW_MODE": False,
        },
    )
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI,
        "get_series_metadata",
        return_value={
            "summary": "Already has a summary",
            "ageRating": 8,
            "genres": [],
            "tags": [],
            "webLinks": "",
            "language": "",
        },
    )
    mocker.patch.object(enrichment_engine, "_emit_series_status")
    mocker.patch(
        "db_manager.delete_pending_by_series",
        side_effect=RuntimeError("purge boom"),
    )

    with caplog.at_level(logging.DEBUG):
        ok, msg, used = enrichment_engine.enrich_series(
            62, "Orphan Log", force_update=False
        )

    assert ok is True
    assert msg == "Déjà à jour."
    assert "orphan pending_review purge failed" in caplog.text
    assert "RuntimeError: purge boom" in caplog.text


def test_safe_exc_str_shape_used_in_debug_messages():
    """Sanity: debug formatting uses the same safe_exc_str contract as scrapers."""
    rendered = safe_exc_str(RuntimeError("x?api_key=SECRET123"))
    assert "SECRET123" not in rendered
    assert "RuntimeError" in rendered
