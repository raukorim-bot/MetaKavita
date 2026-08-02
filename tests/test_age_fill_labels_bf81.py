"""BF81 — hentai/futanari → x18 (fill or escalate); AGE_RATING_MAP r18/x18 aliases."""

import logging
from types import SimpleNamespace

import metadata_fetcher
from scrapers.utils import MATCH_SCORE_KEY
from services.kavita_payload import build_kavita_payload


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


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def test_u1_empty_age_hentai_fills_x18():
    data = {"age_rating": "", "genres": ["Hentai"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == "x18"


def test_u2_missing_age_futanari_fills_x18():
    data = {"tags": ["Futanari"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == "x18"


def test_u3_suggestive_plus_hentai_escalates():
    data = {"age_rating": "suggestive", "genres": ["Hentai"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == "x18"


def test_u4_r18_plus_hentai_escalates():
    data = {"age_rating": "r18", "genres": ["Hentai"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == "x18"
    data2 = {"age_rating": "erotica", "tags": ["Futanari"]}
    assert metadata_fetcher.apply_explicit_label_age(data2)["age_rating"] == "x18"


def test_u5_mature_plus_hentai_escalates():
    data = {"age_rating": "mature", "genres": ["Hentai"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == "x18"


def test_u6_safe_plus_futanari_escalates():
    data = {"age_rating": "safe", "tags": ["Futanari"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == "x18"


def test_u7_already_x18_noop():
    data = {"age_rating": "x18", "genres": ["Hentai"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == "x18"
    data2 = {"age_rating": "pornographic", "genres": ["Hentai"]}
    assert metadata_fetcher.apply_explicit_label_age(data2)["age_rating"] == "pornographic"


def test_u8_ecchi_alone_no_fill():
    data = {"age_rating": "", "genres": ["Ecchi"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == ""


def test_u9_r18_without_hentai_unchanged():
    data = {"age_rating": "r18", "genres": ["Action"], "tags": ["Seinen"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == "r18"


def test_u10_aliases_payload_ints():
    r18 = build_kavita_payload({"age_rating": "r18", "summary": "x"}, {}, ["age"], {}, {}, True, 1)
    erotica = build_kavita_payload({"age_rating": "erotica", "summary": "x"}, {}, ["age"], {}, {}, True, 1)
    x18 = build_kavita_payload({"age_rating": "x18", "summary": "x"}, {}, ["age"], {}, {}, True, 1)
    porn = build_kavita_payload({"age_rating": "pornographic", "summary": "x"}, {}, ["age"], {}, {}, True, 1)
    assert r18["metadata"]["ageRating"] == 12
    assert erotica["metadata"]["ageRating"] == 12
    assert x18["metadata"]["ageRating"] == 14
    assert porn["metadata"]["ageRating"] == 14


def test_u11_none_data():
    assert metadata_fetcher.apply_explicit_label_age(None) is None


def test_u_hentai_manga_token():
    data = {"age_rating": "", "genres": ["Hentai Manga"]}
    assert metadata_fetcher.apply_explicit_label_age(data)["age_rating"] == "x18"


def test_is_explicit_adult_accepts_r18_x18():
    assert metadata_fetcher._is_explicit_adult({"age_rating": "r18"}) is True
    assert metadata_fetcher._is_explicit_adult({"age_rating": "x18"}) is True
    assert metadata_fetcher._is_explicit_adult({"age_rating": "mature"}) is False


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

def test_p1_fill_hentai_writes_x18():
    data = metadata_fetcher.apply_explicit_label_age(
        {"age_rating": "", "genres": ["Hentai"], "summary": "s"}
    )
    out = build_kavita_payload(data, {}, ["age"], {}, {}, True, 1)
    assert out["metadata"]["ageRating"] == 14
    assert out["metadata"]["ageRatingLocked"] is True


def test_p2_empty_no_labels_skips_age():
    out = build_kavita_payload({"age_rating": "", "summary": "s"}, {}, ["age"], {}, {}, True, 1)
    assert "ageRating" not in out["metadata"]


def test_p3_suggestive_plus_hentai_payload_14():
    data = metadata_fetcher.apply_explicit_label_age(
        {"age_rating": "suggestive", "genres": ["Hentai"], "summary": "s"}
    )
    out = build_kavita_payload(data, {}, ["age"], {}, {}, True, 1)
    assert out["metadata"]["ageRating"] == 14


def test_p4_r18_without_labels_payload_12():
    out = build_kavita_payload(
        {"age_rating": "r18", "genres": ["Action"], "summary": "s"},
        {},
        ["age"],
        {},
        {},
        True,
        1,
    )
    assert out["metadata"]["ageRating"] == 12


# ---------------------------------------------------------------------------
# fetch_metadata integration
# ---------------------------------------------------------------------------

def test_f1_single_provider_hentai_empty_age(monkeypatch):
    scrapers = {
        "MB": _make_scraper(
            "MB",
            lambda *a, **k: _useful("Kannagi", 1.0, "", genres=["Hentai"], tags=["Futanari"]),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {"UI_LANG": "en", "SMART_SCORING": True, "SMART_COMPLETION": False},
    )
    result, _ = metadata_fetcher.fetch_metadata(
        query="Kannagi",
        providers_list=["MB"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
    )
    assert result["age_rating"] == "x18"


def test_f2_classic_cascade_also_applies(monkeypatch):
    scrapers = {
        "MB": _make_scraper(
            "MB",
            lambda *a, **k: _useful("Kannagi", 0.5, "", genres=["Hentai"]),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {"UI_LANG": "en", "SMART_SCORING": False, "SMART_COMPLETION": False},
    )
    result, _ = metadata_fetcher.fetch_metadata(
        query="Kannagi",
        providers_list=["MB"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=False,
    )
    assert result["age_rating"] == "x18"


def test_f3_kannagi_tie_prefers_kitsu(monkeypatch, caplog):
    scrapers = {
        "MANGABAKA": _make_scraper(
            "MANGABAKA",
            lambda *a, **k: _useful("Kannagi", 1.0, "", genres=["Hentai"], tags=["Futanari"]),
        ),
        "KITSU": _make_scraper(
            "KITSU",
            lambda *a, **k: _useful(
                "Kannagi", 1.0, "suggestive", genres=["Comedy"], tags=["Fantasy"]
            ),
        ),
        "ANILIST": _make_scraper(
            "ANILIST",
            lambda *a, **k: _useful("Kannagi", 1.0, "pornographic", genres=["Hentai"]),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {"UI_LANG": "en", "SMART_SCORING": True, "SMART_COMPLETION": False},
    )
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
    assert "preferring safer match" in caplog.text
    assert "KITSU" in caplog.text


def test_f4_strict_higher_adult_still_wins(monkeypatch):
    scrapers = {
        "ADULT": _make_scraper(
            "ADULT",
            lambda *a, **k: _useful("Adult", 1.0, "x18", genres=["Hentai"]),
        ),
        "SAFE": _make_scraper(
            "SAFE",
            lambda *a, **k: _useful("Safe", 0.90, "suggestive"),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {"UI_LANG": "en", "SMART_SCORING": True, "SMART_COMPLETION": False},
    )
    result, _ = metadata_fetcher.fetch_metadata(
        query="Strict",
        providers_list=["ADULT", "SAFE"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
    )
    assert result["_provider_used"] == "ADULT"


def test_f5_return_candidates_card_has_x18(monkeypatch):
    scrapers = {
        "MB": _make_scraper(
            "MB",
            lambda *a, **k: _useful("Kannagi", 1.0, "", genres=["Hentai"]),
        ),
    }
    _install_fake_registry(monkeypatch, scrapers)
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {"UI_LANG": "en", "SMART_SCORING": True, "SMART_COMPLETION": False},
    )
    payload, _ = metadata_fetcher.fetch_metadata(
        query="Kannagi",
        providers_list=["MB"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
        return_candidates=True,
    )
    ages = [c.get("age_rating") for c in payload.get("above", [])]
    assert "x18" in ages
