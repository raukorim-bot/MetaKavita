"""C88 F0–F2 — gate mapping + Auto fetch."""
from __future__ import annotations

from types import SimpleNamespace

from services.enrichment_engine import (
    attach_mapping_preview,
    fetch_auto_series_metadata,
    field_mapping_log_line,
    mapping_applies_here,
)
from services.field_mapping_fetch import WaveResult


def test_mapping_applies_here_false_when_disabled():
    assert mapping_applies_here(
        {"FIELD_MAPPING_ENABLED": False, "UI_SHOW_FIELD_MAPPING": True},
        forced_provider="AUTO",
        manual_mode=False,
    ) is False
    assert mapping_applies_here(
        {"FIELD_MAPPING_ENABLED": True, "UI_SHOW_FIELD_MAPPING": True},
        forced_provider="MAL",
        manual_mode=False,
    ) is False
    assert mapping_applies_here(
        {"FIELD_MAPPING_ENABLED": True, "UI_SHOW_FIELD_MAPPING": True},
        forced_provider="AUTO",
        manual_mode=True,
    ) is False


def test_fetch_auto_mapping_off_calls_fetch_metadata(mocker):
    fetch = mocker.patch(
        "metadata_fetcher.fetch_metadata",
        return_value=({"summary": "s", "_provider_used": "MAL"}, ["MAL"]),
    )
    data, used = fetch_auto_series_metadata(
        search_query="Q",
        providers_list=["MAL"],
        smart_completion=True,
        fetch_kwargs={"library_type": "Manga"},
        library_type="Manga",
        forced_provider="AUTO",
        config={"FIELD_MAPPING_ENABLED": False, "UI_SHOW_FIELD_MAPPING": False},
        series_name="Q",
        series_id=1,
        is_forced_id=False,
        existing_metadata={},
        smart_scoring=True,
        fallback_query=None,
        t={},
        label="Q",
    )
    assert fetch.call_count == 1
    assert data["summary"] == "s"
    assert used == ["MAL"]


def test_miss_plus_override_returns_assembled(mocker):
    mocker.patch(
        "services.enrichment_engine.mapping_applies_here",
        return_value=True,
    )
    mocker.patch(
        "services.field_mapping.resolve_mapping_plan",
        return_value=SimpleNamespace(fetch_library_type="Manga"),
    )
    mocker.patch(
        "services.field_mapping_fetch.run_mapping_wave",
        return_value=WaveResult(
            data={
                "summary": "from override",
                "cover_url": "http://anilist/c.jpg",
                "_provider_used": "ANILIST",
                "_field_sources": {"cover": "ANILIST"},
            },
            used=["ANILIST"],
            useful=True,
        ),
    )
    data, used = fetch_auto_series_metadata(
        search_query="Q",
        providers_list=["MAL"],
        smart_completion=True,
        fetch_kwargs={"library_type": "Manga"},
        library_type="Manga",
        forced_provider="AUTO",
        config={"FIELD_MAPPING_ENABLED": True, "UI_SHOW_FIELD_MAPPING": True},
        series_name="Q",
        series_id=1,
        is_forced_id=False,
        existing_metadata={},
        smart_scoring=True,
        fallback_query=None,
        t={},
        label="Q",
    )
    assert data["cover_url"] == "http://anilist/c.jpg"
    assert data["_field_sources"]["cover"] == "ANILIST"
    assert used == ["ANILIST"]


def test_field_mapping_log_and_preview():
    assembled = {
        "_provider_used": "MAL",
        "_field_sources": {"cover": "ANILIST", "staff": "MAL"},
    }
    line = field_mapping_log_line("X", assembled)
    assert "Base: MAL" in line
    assert "cover=ANILIST" in line
    preview = attach_mapping_preview({}, assembled)
    assert preview["_field_sources"]["cover"] == "ANILIST"
    assert preview["_field_picks"]["cover"] == ["ANILIST"]


def test_flexible_mapping_second_wave_on_miss(mocker):
    mocker.patch(
        "services.enrichment_engine.mapping_applies_here",
        return_value=True,
    )
    mocker.patch(
        "services.enrichment_engine._providers_from_config",
        side_effect=lambda cfg, lt, *a, **k: ["COMICVINE"] if lt == "Comic" else ["ANILIST"],
    )
    waves = []

    def fake_wave(plan, query, **kwargs):
        waves.append(plan.wave)
        if plan.wave == "comic":
            return WaveResult(data=None, used=["COMICVINE"], useful=False)
        return WaveResult(
            data={"summary": "manga", "_provider_used": "ANILIST"},
            used=["ANILIST"],
            useful=True,
        )

    mocker.patch("services.field_mapping_fetch.run_mapping_wave", side_effect=fake_wave)
    mocker.patch(
        "services.field_mapping.resolve_mapping_plan",
        side_effect=lambda cfg, lt, flexible_wave=None: SimpleNamespace(
            fetch_library_type="Comic" if flexible_wave == "comic" else "Manga",
            wave=flexible_wave,
        ),
    )
    data, used = fetch_auto_series_metadata(
        search_query="Q",
        providers_list=["COMICVINE"],
        smart_completion=True,
        fetch_kwargs={"library_type": "Comic"},
        library_type="ComicFlexible",
        forced_provider="AUTO",
        config={"FIELD_MAPPING_ENABLED": True, "UI_SHOW_FIELD_MAPPING": True},
        series_name="Q",
        series_id=1,
        is_forced_id=False,
        existing_metadata={},
        smart_scoring=True,
        fallback_query=None,
        t={"log_flexible_manga_fallback": "[{0}] fallback {1}"},
        label="Q",
    )
    assert waves == ["comic", "manga"]
    assert data["summary"] == "manga"
    assert "ANILIST" in used
    assembled = {
        "_provider_used": "MAL",
        "_field_sources": {"cover": "ANILIST", "staff": "MAL"},
    }
    line = field_mapping_log_line("X", assembled)
    assert "Base: MAL" in line
    assert "cover=ANILIST" in line
    preview = attach_mapping_preview({}, assembled)
    assert preview["_field_sources"]["cover"] == "ANILIST"
    assert preview["_field_picks"]["cover"] == ["ANILIST"]
