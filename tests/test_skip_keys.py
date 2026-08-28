"""C88 B0 — skip_keys empêche le hole-fill sans changer le défaut."""
from __future__ import annotations

import metadata_fetcher


def test_skip_keys_none_fills_summary_as_today():
    ordered = [
        ("TOP", {"title": "T", "summary": ""}),
        ("ALT", {"summary": "from alt", "genres": ["Action"]}),
    ]
    merged = metadata_fetcher.merge_candidates(ordered, smart_fusion=True)
    assert merged["summary"] == "from alt"
    assert merged["genres"] == ["Action"]


def test_skip_keys_blocks_summary_hole_fill():
    ordered = [
        ("TOP", {"title": "T", "summary": ""}),
        ("ALT", {"summary": "from alt", "genres": ["Action"]}),
    ]
    merged = metadata_fetcher.merge_candidates(
        ordered, smart_fusion=True, skip_keys={"summary"}
    )
    assert not merged.get("summary")
    assert merged["genres"] == ["Action"]
    assert "ALT" in merged.get("_fusion_providers", [])


def test_skip_keys_blocks_titles_merge():
    ordered = [
        ("TOP", {"title": "T", "summary": "s", "titles": [{"lang": "en", "value": "A"}]}),
        ("ALT", {"titles": [{"lang": "ja", "value": "B"}]}),
    ]
    merged = metadata_fetcher.merge_candidates(
        ordered, smart_fusion=True, skip_keys={"titles"}
    )
    langs = [t.get("lang") for t in (merged.get("titles") or [])]
    assert "ja" not in langs


def test_fetch_metadata_skip_keys_blocks_summary(monkeypatch):
    from types import SimpleNamespace

    from scrapers.utils import MATCH_SCORE_KEY

    def _blob(title, score, **extra):
        data = {"title": title, "summary": extra.pop("summary", f"s {title}"), MATCH_SCORE_KEY: score}
        data.update(extra)
        return data

    scrapers = {
        "BASE": SimpleNamespace(
            id="BASE",
            supported_types={"Manga"},
            rate_limit=0.0,
            extract_id_from_url=lambda url: None,
            fetch=lambda *a, **k: _blob("Base", 0.95, summary="", year=2020),
        ),
        "ALT": SimpleNamespace(
            id="ALT",
            supported_types={"Manga"},
            rate_limit=0.0,
            extract_id_from_url=lambda url: None,
            fetch=lambda *a, **k: _blob("Alt", 0.90, summary="from alt", genres=["Action"]),
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

    result, _ = metadata_fetcher.fetch_metadata(
        query="Series",
        providers_list=["BASE", "ALT"],
        smart_fusion=True,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
        skip_keys={"summary"},
    )
    assert result is not None
    assert not result.get("summary")
    assert result.get("genres") == ["Action"]
    ordered = [
        ("TOP", {"title": "T", "summary": "s", "titles": [{"lang": "en", "value": "A"}]}),
        ("ALT", {"titles": [{"lang": "ja", "value": "B"}]}),
    ]
    merged = metadata_fetcher.merge_candidates(
        ordered, smart_fusion=True, skip_keys={"titles"}
    )
    langs = [t.get("lang") for t in (merged.get("titles") or [])]
    assert "ja" not in langs
