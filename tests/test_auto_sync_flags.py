"""C96 T2 — job_flags, override Review, trous Auto-sync Auto."""
from __future__ import annotations

from services.auto_sync import job_flags, normalize_mode
from services.enrichment_engine import series_has_fillable_holes


def test_job_flags_auto_writes_even_with_sidebar_review():
    flags = job_flags({
        "AUTO_SYNC_MODE": "auto",
        "AUTO_SYNC_FORCE_UPDATE": False,
        "MANUAL_REVIEW_MODE": True,
        "CONFIRM_BEFORE_WRITE": True,
    })
    assert flags == {
        "force_auto": True,
        "force_update": False,
        "super_review": False,
        "manual_review_override": False,
    }


def test_job_flags_review_and_super():
    assert job_flags({"AUTO_SYNC_MODE": "review"})["manual_review_override"] is True
    assert job_flags({"AUTO_SYNC_MODE": "review"})["force_auto"] is False
    assert job_flags({"AUTO_SYNC_MODE": "super"})["super_review"] is True
    assert job_flags({"AUTO_SYNC_MODE": "super"})["force_update"] is False


def test_job_flags_force_update_only_in_auto():
    assert job_flags({
        "AUTO_SYNC_MODE": "auto", "AUTO_SYNC_FORCE_UPDATE": True,
    })["force_update"] is True
    assert job_flags({
        "AUTO_SYNC_MODE": "review", "AUTO_SYNC_FORCE_UPDATE": True,
    })["force_update"] is False


def test_normalize_mode_clamps():
    assert normalize_mode("AUTO") == "auto"
    assert normalize_mode("nope") == "auto"


def test_age_pending_is_a_hole():
    assert series_has_fillable_holes(
        {"summary": "x", "ageRating": 1}, ["summary", "age"]
    ) is True
    assert series_has_fillable_holes(
        {"summary": "x", "ageRating": 8, "genres": [{"title": "A"}],
         "tags": [{"title": "t"}], "releaseYear": 2000,
         "publicationStatus": 0, "publishers": [{"name": "P"}],
         "writers": [{"name": "W"}], "webLinks": "http://x", "language": "fr"},
        ["summary", "age", "genres", "tags", "year", "status",
         "publisher", "staff", "weblinks", "language"],
    ) is False


def test_empty_genres_is_a_hole_when_targeted():
    meta = {"summary": "x", "ageRating": 8, "genres": []}
    assert series_has_fillable_holes(meta, ["summary", "genres"]) is True
    assert series_has_fillable_holes(meta, ["summary"]) is False


def test_batch_skip_summary_unchanged_with_empty_genres(mocker, isolated_db):
    """Lot / clic : résumé présent → déjà à jour, même si les genres sont vides."""
    from kavita_api import KavitaAPI
    from services import enrichment_engine
    from test_comic_flexible import _base_config, _patch_kavita_basics

    mocker.patch.object(enrichment_engine, "load_config", return_value=_base_config())
    _patch_kavita_basics(mocker, isolated_db)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={
        "summary": "Already has a summary",
        "ageRating": 8,
        "genres": [],
        "tags": [],
        "webLinks": "",
        "language": "",
    })
    fetch = mocker.patch("metadata_fetcher.fetch_metadata")

    ok, msg, _used = enrichment_engine.enrich_series(
        52, "Already Done", force_update=False
    )
    assert ok is True
    assert msg == "Déjà à jour."
    fetch.assert_not_called()


def test_auto_sync_auto_fills_empty_genres_despite_summary(mocker, isolated_db):
    """Auto-sync Auto : un trou ciblé (genres) empêche le skip résumé."""
    from kavita_api import KavitaAPI
    from services import enrichment_engine
    from test_comic_flexible import _base_config, _patch_kavita_basics

    mocker.patch.object(
        enrichment_engine, "load_config",
        return_value=_base_config(MANUAL_REVIEW_MODE=True),
    )
    _patch_kavita_basics(mocker, isolated_db)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={
        "summary": "Already has a summary",
        "ageRating": 8,
        "genres": [],
        "tags": [],
        "webLinks": "",
        "language": "",
    })
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="Manga")
    mocker.patch.object(KavitaAPI, "get_series", return_value=None)
    fetch = mocker.patch(
        "metadata_fetcher.fetch_metadata",
        return_value=(None, []),
    )

    ok, msg, _used = enrichment_engine.enrich_series(
        80, "Holey", force_update=False, force_auto=True
    )
    assert fetch.called
    assert msg != "Déjà à jour."


def test_manual_review_override_parks_even_if_sidebar_auto(mocker, isolated_db):
    from kavita_api import KavitaAPI
    from scrapers.base import BaseScraper
    from services import enrichment_engine

    class _MangaFake(BaseScraper):
        id = "MANGA_FAKE"
        display_name = "Manga Fake"
        supported_types = {"Manga"}
        has_direct_id_support = False

        def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
            return None

        def extract_id_from_url(self, url):
            return None

    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value={
            "KAVITA_URL": "http://kavita.local",
            "KAVITA_API_KEY": "fake",
            "UI_LANG": "fr",
            "TARGET_LANG": "FR",
            "PROVIDER_1": "MANGA_FAKE",
            "PROVIDER_2": "NONE",
            "PROVIDER_3": "NONE",
            "SMART_COMPLETION": False,
            "SMART_SCORING": False,
            "AUTO_COVER": False,
            "TRANSLATION_PROVIDER": "NONE",
            "MANUAL_REVIEW_MODE": False,
            "MANUAL_REVIEW_SUPER": False,
            "CONFIRM_BEFORE_WRITE": False,
            "LOCALIZED_TITLE_MODE": "all",
            "PUBLISHER_PREFERENCE": "LOCALIZED",
        },
    )
    mocker.patch.object(enrichment_engine, "get_all_cached_data",
                        side_effect=isolated_db.get_all_cached_data)
    mocker.patch.object(enrichment_engine, "update_status")
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI, "get_series_metadata",
        return_value={"summary": "", "genres": [], "tags": [], "webLinks": "", "language": ""},
    )
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="Manga")
    mocker.patch.object(KavitaAPI, "get_series_deep_metadata", return_value={
        "isbn": None, "authors": [], "publisher": None, "year": None,
        "genres": [], "localized_name": None,
    })
    mocker.patch.object(KavitaAPI, "get_cached_library_id", return_value=1)
    fake = _MangaFake()
    mocker.patch.object(
        enrichment_engine.ScraperRegistry, "get",
        side_effect=lambda pid: fake if pid == "MANGA_FAKE" else None,
    )
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[fake])
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_all", return_value=[fake])
    card = {
        "provider": "MANGA_FAKE", "title": "Park Me", "summary": "Hello",
        "genres": [], "tags": [], "staff": [], "_match_score": 0.9,
    }
    mocker.patch(
        "metadata_fetcher.fetch_metadata",
        return_value=({"above": [card], "below": [], "query": "Park Me"}, ["MANGA_FAKE"]),
    )
    parked = {}
    mocker.patch(
        "services.manual_review.begin_streaming_review",
        side_effect=lambda sid, name, **kwargs: parked.update(series_id=sid)
        or "rid-1",
    )
    mocker.patch("services.manual_review.append_streaming_candidate", return_value=None)
    mocker.patch(
        "services.manual_review.finalize_streaming_review",
        side_effect=lambda rid, sid, name, payload, **kwargs: parked.update(done=True) or rid,
    )
    mocker.patch("services.enrichment_engine.apply_kavita_payload")

    ok, msg, _used = enrichment_engine.enrich_series(
        81, "Park Me", force_update=True, manual_review_override=True
    )
    assert ok is True
    assert msg == "PENDING_REVIEW"
    assert parked.get("series_id") == 81
    assert parked.get("done") is True

