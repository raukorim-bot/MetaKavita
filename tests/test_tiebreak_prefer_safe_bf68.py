"""BF68 — Auto score-tie prefers non-adult; MR/CBW paths."""

import logging
from types import SimpleNamespace

import pytest

import metadata_fetcher
from scrapers.utils import MATCH_SCORE_KEY


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    monkeypatch.setattr(metadata_fetcher, "LAST_REQUEST_TIMES", {})
    monkeypatch.setattr(metadata_fetcher, "_THROTTLE_LOCKS", {})
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {
            "UI_LANG": "en",
            "SMART_SCORING": True,
            "SMART_COMPLETION": False,
        },
    )


def _make_scraper(scraper_id, fetch_fn, supported_types=None, rate_limit=0.0):
    return SimpleNamespace(
        id=scraper_id,
        supported_types=supported_types or {"Manga"},
        rate_limit=rate_limit,
        extract_id_from_url=lambda url: None,
        fetch=fetch_fn,
    )


def _install_fake_registry(monkeypatch, scrapers_by_id):
    fake_registry = SimpleNamespace(get=lambda scraper_id: scrapers_by_id.get(scraper_id))
    monkeypatch.setattr(metadata_fetcher, "ScraperRegistry", fake_registry)


def _useful(title, score, age_rating=None, **extra):
    data = {
        "title": title,
        "summary": f"Summary for {title}",
        MATCH_SCORE_KEY: score,
    }
    if age_rating is not None:
        data["age_rating"] = age_rating
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def test_is_explicit_adult_helper():
    assert metadata_fetcher._is_explicit_adult({"age_rating": "pornographic"}) is True
    assert metadata_fetcher._is_explicit_adult({"age_rating": "Erotica"}) is True
    assert metadata_fetcher._is_explicit_adult({"age_rating": "suggestive"}) is False
    assert metadata_fetcher._is_explicit_adult({"age_rating": "safe"}) is False
    assert metadata_fetcher._is_explicit_adult({}) is False
    assert metadata_fetcher._is_explicit_adult(None) is False
    # BF77: empty age + unambiguous genre/tag tokens
    assert metadata_fetcher._is_explicit_adult({"genres": ["Hentai"], "tags": ["Futanari"]}) is True
    assert metadata_fetcher._is_explicit_adult({"genres": [], "tags": ["Comedy", "Futanari"]}) is True
    assert metadata_fetcher._is_explicit_adult({"genres": ["Hentai Manga"], "age_rating": ""}) is True
    assert metadata_fetcher._is_explicit_adult({"genres": ["Comedy"], "tags": ["Fantasy"]}) is False
    assert metadata_fetcher._is_explicit_adult({"genres": ["Ecchi"], "tags": ["Romance"]}) is False


def test_sort_key_prefers_non_adult_on_equal_score():
    """Unit: adult demotion only as secondary key after score."""
    entries = [
        (0, "ADULT", _useful("A", 1.0, "pornographic")),
        (1, "SAFE", _useful("B", 1.0, "suggestive")),
    ]
    entries.sort(
        key=lambda e: (
            -metadata_fetcher._safe_match_score(e[2]),
            1 if metadata_fetcher._is_explicit_adult(e[2]) else 0,
            e[0],
        )
    )
    assert entries[0][1] == "SAFE"


# ---------------------------------------------------------------------------
# NR-G — general cases unchanged
# ---------------------------------------------------------------------------

def test_nr_g4_single_adult_candidate_wins_no_tiebreak_log(monkeypatch, caplog):
    """NR-G4: sole accepted adult candidate wins; no prefer_safe log."""
    scrapers = {
        "ONLY": _make_scraper(
            "ONLY",
            lambda *a, **k: _useful("Adult Solo", 0.95, "pornographic"),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)

    with caplog.at_level(logging.INFO):
        result, _ = metadata_fetcher.fetch_metadata(
            query="Solo",
            providers_list=["ONLY"],
            smart_fusion=False,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
        )

    assert result["_provider_used"] == "ONLY"
    assert result["age_rating"] == "pornographic"
    assert not result.get("_score_tie")
    assert "preferring safer match" not in caplog.text
    assert "match plus safe" not in caplog.text


def test_nr_g5_strict_higher_score_wins_even_if_adult(monkeypatch, caplog):
    """NR-G5: strict higher score wins; adult OK when not a tie."""
    scrapers = {
        "ADULT_HIGH": _make_scraper(
            "ADULT_HIGH",
            lambda *a, **k: _useful("Adult High", 1.0, "pornographic"),
        ),
        "SAFE_LOW": _make_scraper(
            "SAFE_LOW",
            lambda *a, **k: _useful("Safe Low", 0.90, "suggestive"),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)

    with caplog.at_level(logging.INFO):
        result, _ = metadata_fetcher.fetch_metadata(
            query="Strict",
            providers_list=["ADULT_HIGH", "SAFE_LOW"],
            smart_fusion=False,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
        )

    assert result["_provider_used"] == "ADULT_HIGH"
    assert "preferring safer match" not in caplog.text


def test_nr_g5_suggestive_beats_lower_adult(monkeypatch, caplog):
    scrapers = {
        "SAFE_HIGH": _make_scraper(
            "SAFE_HIGH",
            lambda *a, **k: _useful("Safe High", 1.0, "suggestive"),
        ),
        "ADULT_LOW": _make_scraper(
            "ADULT_LOW",
            lambda *a, **k: _useful("Adult Low", 0.95, "pornographic"),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)

    with caplog.at_level(logging.INFO):
        result, _ = metadata_fetcher.fetch_metadata(
            query="Strict2",
            providers_list=["ADULT_LOW", "SAFE_HIGH"],
            smart_fusion=False,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
        )

    assert result["_provider_used"] == "SAFE_HIGH"
    assert "preferring safer match" not in caplog.text


def test_nr_g6_tie_all_non_adult_uses_provider_order(monkeypatch, caplog):
    """NR-G6: equal scores, all non-adult → fallback idx order."""
    scrapers = {
        "FIRST": _make_scraper(
            "FIRST",
            lambda *a, **k: _useful("First", 1.0, "suggestive"),
        ),
        "SECOND": _make_scraper(
            "SECOND",
            lambda *a, **k: _useful("Second", 1.0, "safe"),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)

    with caplog.at_level(logging.INFO):
        result, _ = metadata_fetcher.fetch_metadata(
            query="TieSafe",
            providers_list=["FIRST", "SECOND"],
            smart_fusion=False,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
        )

    assert result["_provider_used"] == "FIRST"
    assert result.get("_score_tie") is True
    assert "preferring safer match" not in caplog.text


def test_nr_g7_tie_all_adult_uses_provider_order(monkeypatch, caplog):
    """NR-G7: equal scores, all adult → fallback idx; no prefer_safe log."""
    scrapers = {
        "FIRST": _make_scraper(
            "FIRST",
            lambda *a, **k: _useful("First", 1.0, "pornographic"),
        ),
        "SECOND": _make_scraper(
            "SECOND",
            lambda *a, **k: _useful("Second", 1.0, "erotica"),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)

    with caplog.at_level(logging.INFO):
        result, _ = metadata_fetcher.fetch_metadata(
            query="TieAdult",
            providers_list=["FIRST", "SECOND"],
            smart_fusion=False,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
        )

    assert result["_provider_used"] == "FIRST"
    assert result.get("_score_tie") is True
    assert "preferring safer match" not in caplog.text


def test_nr_g9_cbw_without_tie_uses_confirm(mocker, isolated_db):
    """NR-G9: CBW without _score_tie → create_confirm_from_auto."""
    from services import enrichment_engine
    from kavita_api import KavitaAPI
    from test_comic_flexible import _base_config, _MangaFake

    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value=_base_config(
            CONFIRM_BEFORE_WRITE=True,
            MANUAL_REVIEW_MODE=False,
            SMART_SCORING=True,
            PROVIDER_1="MANGA_FAKE",
        ),
    )
    mocker.patch("services.kavita_payload.get_max_genres", side_effect=lambda c=None: 5)
    mocker.patch("services.kavita_payload.get_max_tags", side_effect=lambda c=None: 15)
    mocker.patch.object(enrichment_engine, "get_all_cached_data", side_effect=isolated_db.get_all_cached_data)
    mocker.patch.object(enrichment_engine, "update_status")
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={
        "summary": "", "genres": [], "tags": [], "webLinks": "", "language": "",
    })
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="Manga")
    mocker.patch.object(KavitaAPI, "get_series_deep_metadata", return_value={
        "isbn": None, "authors": [], "publisher": None, "year": None,
        "genres": [], "localized_name": None,
    })
    mocker.patch.object(KavitaAPI, "get_cached_library_id", return_value=1)

    manga = _MangaFake()
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", return_value=manga)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[manga])
    mocker.patch(
        "metadata_fetcher.fetch_metadata",
        return_value=(
            {
                "_provider_used": "MANGA_FAKE",
                "title": "Solo",
                "summary": "s",
                MATCH_SCORE_KEY: 0.9,
            },
            ["MANGA_FAKE"],
        ),
    )
    confirm = mocker.patch(
        "services.manual_review.create_confirm_from_auto",
        return_value="rid-confirm",
    )
    review = mocker.patch(
        "services.manual_review.create_review_from_candidates",
        return_value="rid-review",
    )
    mocker.patch.object(enrichment_engine, "_emit_series_status")

    ok, msg, used = enrichment_engine.enrich_series(70, "Solo", force_update=True)

    assert ok is True
    assert msg == "PENDING_REVIEW"
    confirm.assert_called_once()
    review.assert_not_called()


def test_nr_g11_classic_cascade_no_score_tie_flag(monkeypatch):
    """NR-G11: SMART_SCORING off → no _score_tie / adult tie-break."""
    scrapers = {
        "FIRST": _make_scraper(
            "FIRST",
            lambda *a, **k: _useful("First", 0.5, "pornographic"),
        ),
        "SECOND": _make_scraper(
            "SECOND",
            lambda *a, **k: _useful("Second", 1.0, "suggestive"),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)

    result, _ = metadata_fetcher.fetch_metadata(
        query="Classic",
        providers_list=["FIRST", "SECOND"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=False,
    )

    assert result["_provider_used"] == "FIRST"
    assert "_score_tie" not in result
    assert "_tie_review_payload" not in result


# ---------------------------------------------------------------------------
# NR-P — particular cases
# ---------------------------------------------------------------------------

def test_nr_p3_tie_adult_plus_safe_prefers_safe_and_logs(monkeypatch, caplog):
    """NR-P3: equal score adult+safe → safe wins + prefer_safe log."""
    scrapers = {
        "ADULT": _make_scraper(
            "ADULT",
            lambda *a, **k: _useful("Adult Tie", 1.0, "pornographic"),
        ),
        "SAFE": _make_scraper(
            "SAFE",
            lambda *a, **k: _useful("Safe Tie", 1.0, "suggestive"),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)

    with caplog.at_level(logging.INFO):
        result, _ = metadata_fetcher.fetch_metadata(
            query="MixedTie",
            providers_list=["ADULT", "SAFE"],
            smart_fusion=False,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
        )

    assert result["_provider_used"] == "SAFE"
    assert result.get("_score_tie") is True
    assert result.get("_tie_review_payload")
    assert "preferring safer match" in caplog.text
    assert "SAFE" in caplog.text


def test_nr_p6_kannagi_mangabaka_hentai_tags_demoted(monkeypatch, caplog):
    """BF77 / #25 residual: empty age + Hentai/Futanari demotes like pornographic.

    Replays Kannagi: MangaBaka (mirror, no age) + Kitsu (suggestive) + AniList
    (pornographic) all at 1.00 — Auto must pick Kitsu, not MangaBaka.
    """
    scrapers = {
        "MANGABAKA": _make_scraper(
            "MANGABAKA",
            lambda *a, **k: _useful(
                "Kannagi",
                1.0,
                "",
                genres=["Hentai"],
                tags=["Futanari"],
            ),
        ),
        "KITSU": _make_scraper(
            "KITSU",
            lambda *a, **k: _useful(
                "Kannagi",
                1.0,
                "suggestive",
                genres=["Comedy"],
                tags=["Fantasy", "Harem"],
            ),
        ),
        "ANILIST": _make_scraper(
            "ANILIST",
            lambda *a, **k: _useful(
                "Kannagi",
                1.0,
                "pornographic",
                genres=["Hentai"],
                tags=["Futanari"],
            ),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)

    with caplog.at_level(logging.INFO):
        result, _ = metadata_fetcher.fetch_metadata(
            query="Kannagi",
            providers_list=["MANGABAKA", "KITSU", "ANILIST"],
            smart_fusion=False,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
        )

    assert result["_provider_used"] == "KITSU"
    assert result.get("age_rating") == "suggestive"
    assert result.get("_score_tie") is True
    assert "preferring safer match" in caplog.text
    assert "KITSU" in caplog.text
    assert "preferring safer match (MANGABAKA)" not in caplog.text


def test_nr_p4_return_candidates_keeps_adult_and_neutral_order(monkeypatch):
    """NR-P4: MR path — both cards present; display sort without adult demotion."""
    scrapers = {
        "ADULT": _make_scraper(
            "ADULT",
            lambda *a, **k: _useful("Adult Card", 1.0, "pornographic"),
        ),
        "SAFE": _make_scraper(
            "SAFE",
            lambda *a, **k: _useful("Safe Card", 1.0, "suggestive"),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)

    payload, used = metadata_fetcher.fetch_metadata(
        query="MR",
        providers_list=["ADULT", "SAFE"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
        return_candidates=True,
    )

    above = payload["above"]
    providers = [c["provider"] for c in above]
    assert "ADULT" in providers
    assert "SAFE" in providers
    # Neutral sort (-score, idx): ADULT idx=0 before SAFE idx=1 at equal score.
    assert providers[0] == "ADULT"
    assert providers[1] == "SAFE"


def test_nr_p5_cbw_score_tie_uses_review_not_confirm(mocker, isolated_db):
    """NR-P5: CBW + _score_tie → create_review_from_candidates, not confirm."""
    from services import enrichment_engine
    from kavita_api import KavitaAPI
    from test_comic_flexible import _base_config, _MangaFake

    tie_payload = {
        "above": [
            {"provider": "SAFE", "score": 1.0, "title": "Safe"},
            {"provider": "ADULT", "score": 1.0, "title": "Adult"},
        ],
        "below": [],
        "query": "Tie",
    }
    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value=_base_config(
            CONFIRM_BEFORE_WRITE=True,
            MANUAL_REVIEW_MODE=False,
            SMART_SCORING=True,
            PROVIDER_1="MANGA_FAKE",
        ),
    )
    mocker.patch("services.kavita_payload.get_max_genres", side_effect=lambda c=None: 5)
    mocker.patch("services.kavita_payload.get_max_tags", side_effect=lambda c=None: 15)
    mocker.patch.object(enrichment_engine, "get_all_cached_data", side_effect=isolated_db.get_all_cached_data)
    mocker.patch.object(enrichment_engine, "update_status")
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={
        "summary": "", "genres": [], "tags": [], "webLinks": "", "language": "",
    })
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="Manga")
    mocker.patch.object(KavitaAPI, "get_series_deep_metadata", return_value={
        "isbn": None, "authors": [], "publisher": None, "year": None,
        "genres": [], "localized_name": None,
    })
    mocker.patch.object(KavitaAPI, "get_cached_library_id", return_value=1)

    manga = _MangaFake()
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", return_value=manga)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[manga])
    mocker.patch(
        "metadata_fetcher.fetch_metadata",
        return_value=(
            {
                "_provider_used": "SAFE",
                "_score_tie": True,
                "_tie_review_payload": tie_payload,
                "title": "Safe Tie",
                "summary": "s",
                MATCH_SCORE_KEY: 1.0,
            },
            ["SAFE", "ADULT"],
        ),
    )
    confirm = mocker.patch(
        "services.manual_review.create_confirm_from_auto",
        return_value="rid-confirm",
    )
    review = mocker.patch(
        "services.manual_review.create_review_from_candidates",
        return_value="rid-review",
    )
    mocker.patch.object(enrichment_engine, "_emit_series_status")

    ok, msg, used = enrichment_engine.enrich_series(99, "Tie Series", force_update=True)

    assert ok is True
    assert msg == "PENDING_REVIEW"
    review.assert_called_once()
    confirm.assert_not_called()
    assert review.call_args[0][2]["above"][0]["provider"] == "SAFE"
