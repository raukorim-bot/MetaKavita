"""Fusion age hole-fill: BF69 adult block + BF102 non-adult Auto fill."""
import logging
from types import SimpleNamespace

import metadata_fetcher
from scrapers.utils import MATCH_SCORE_KEY


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


def _make_scraper(scraper_id, fetch_fn):
    return SimpleNamespace(
        id=scraper_id,
        supported_types={"Manga"},
        rate_limit=0.0,
        extract_id_from_url=lambda url: None,
        fetch=fetch_fn,
    )


def test_fusion_can_fill_auto_allows_non_adult_age():
    """BF102: Auto may fill safe/suggestive/mature; still blocks NSFW."""
    master = {"title": "A", "age_rating": ""}
    assert metadata_fetcher._fusion_can_fill(master, "age_rating", "suggestive") is True
    assert metadata_fetcher._fusion_can_fill(master, "age_rating", "safe") is True
    assert metadata_fetcher._fusion_can_fill(master, "age_rating", "mature") is True
    assert metadata_fetcher._fusion_can_fill(master, "age_rating", "pornographic") is False
    assert metadata_fetcher._fusion_can_fill(master, "age_rating", "r18") is False
    assert metadata_fetcher._fusion_can_fill(master, "age_rating", "x18") is False
    assert metadata_fetcher._fusion_can_fill(master, "genres", ["Action"]) is True


def test_fusion_can_fill_mr_allows_adult_age():
    master = {"title": "A", "age_rating": ""}
    assert (
        metadata_fetcher._fusion_can_fill(
            master, "age_rating", "pornographic", fill_age_rating=True
        )
        is True
    )


def test_fusion_can_fill_does_not_overwrite_existing_age():
    master = {"title": "A", "age_rating": "safe"}
    assert metadata_fetcher._fusion_can_fill(master, "age_rating", "suggestive") is False


def test_merge_candidates_does_not_backfill_adult_age():
    """Auto merge may fill genres; never adult age."""
    ordered = [
        ("SAFE", {"title": "Safe", "summary": "S", "age_rating": ""}),
        ("ADULT", {"title": "Adult", "age_rating": "pornographic", "genres": ["Adult"]}),
    ]
    merged = metadata_fetcher.merge_candidates(ordered, smart_fusion=True)
    assert merged["_provider_used"] == "SAFE"
    assert merged["age_rating"] == ""
    assert merged["genres"] == ["Adult"]
    assert "ADULT" in merged.get("_fusion_providers", [])


def test_merge_candidates_auto_fills_suggestive():
    ordered = [
        ("BASE", {"title": "Base", "summary": "S", "age_rating": ""}),
        ("MD", {"title": "MD", "age_rating": "suggestive", "genres": ["Drama"]}),
    ]
    merged = metadata_fetcher.merge_candidates(ordered, smart_fusion=True)
    assert merged["_provider_used"] == "BASE"
    assert merged.get("age_rating") == "suggestive"
    assert "MD" in merged.get("_fusion_providers", [])


def test_merge_candidates_auto_skips_adult_genres_onto_safe():
    ordered = [
        ("SAFE", {"title": "Safe", "summary": "S", "age_rating": ""}),
        ("ADULT", {"title": "Adult", "age_rating": "pornographic", "genres": ["Hentai"]}),
    ]
    merged = metadata_fetcher.merge_candidates(
        ordered, smart_fusion=True, skip_adult_label_fill=True
    )
    assert merged["_provider_used"] == "SAFE"
    assert merged.get("age_rating") in ("", None)
    assert not merged.get("genres")


def test_smart_completion_tie_keeps_empty_age_not_adult(monkeypatch, caplog):
    scrapers = {
        "SAFE": _make_scraper(
            "SAFE",
            lambda *a, **k: _useful("Safe Title", 1.0, ""),
        ),
        "ADULT": _make_scraper(
            "ADULT",
            lambda *a, **k: _useful("Adult Title", 1.0, "pornographic", genres=["X"]),
        ),
    }
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {"UI_LANG": "en", "SMART_SCORING": True, "SMART_COMPLETION": True},
    )
    monkeypatch.setattr(
        metadata_fetcher,
        "ScraperRegistry",
        SimpleNamespace(get=lambda sid: scrapers.get(sid)),
    )

    with caplog.at_level(logging.INFO):
        result, _ = metadata_fetcher.fetch_metadata(
            query="Tie",
            providers_list=["SAFE", "ADULT"],
            smart_fusion=True,
            library_type="Manga",
            existing_metadata={},
            smart_scoring=True,
        )

    assert result is not None
    assert result["_provider_used"] == "SAFE"
    assert result.get("age_rating") in ("", None)
    # Auto SMART_COMPLETION must not pull adult genres onto prefer-safe winner.
    assert "X" not in (result.get("genres") or [])
    assert "preferring safer match" in caplog.text or result.get("_score_tie")


def test_smart_completion_fills_suggestive_from_secondary(monkeypatch):
    scrapers = {
        "BASE": _make_scraper(
            "BASE",
            lambda *a, **k: _useful("Base Title", 0.95, ""),
        ),
        "MD": _make_scraper(
            "MD",
            lambda *a, **k: _useful("MD Title", 0.90, "suggestive"),
        ),
    }
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {"UI_LANG": "en", "SMART_SCORING": True, "SMART_COMPLETION": True},
    )
    monkeypatch.setattr(
        metadata_fetcher,
        "ScraperRegistry",
        SimpleNamespace(get=lambda sid: scrapers.get(sid)),
    )

    result, used = metadata_fetcher.fetch_metadata(
        query="Series",
        providers_list=["BASE", "MD"],
        smart_fusion=True,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
    )

    assert result is not None
    assert result["_provider_used"] == "BASE"
    assert result.get("age_rating") == "suggestive"
    assert "MD" in (result.get("_fusion_providers") or [])
