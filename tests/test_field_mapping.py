"""C88 D0 — MappingPlan pur."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from services.field_mapping import (
    CASCADE,
    dropdown_providers,
    mapping_should_run,
    parse_mapping_default,
    parse_provider_map,
    resolve_mapping_plan,
    skip_keys_for_overrides,
    url_detect_should_pin_provider,
    usable_ids_for_fetch_type,
    wave_fetch_library_type,
)


def test_wave_fetch_library_type_never_comicflexible():
    assert wave_fetch_library_type("Manga") == "Manga"
    assert wave_fetch_library_type("Comic") == "Comic"
    assert wave_fetch_library_type("Book") == "Book"
    assert wave_fetch_library_type("ComicFlexible") == "Comic"
    assert wave_fetch_library_type("ComicFlexible", "comic") == "Comic"
    assert wave_fetch_library_type("ComicFlexible", "manga") == "Manga"
    assert "Flexible" not in wave_fetch_library_type("ComicFlexible", "manga")


def test_usable_ids_never_calls_get_by_type_comicflexible():
    comic = SimpleNamespace(id="COMICVINE", needs_api_key=False)
    manga = SimpleNamespace(id="ANILIST", needs_api_key=False)

    def fake_get_by_type(lib_type, **kwargs):
        assert lib_type != "ComicFlexible"
        if lib_type == "Comic":
            return [comic]
        if lib_type == "Manga":
            return [manga]
        return []

    with patch("services.field_mapping.ScraperRegistry") as registry:
        registry.get_by_type.side_effect = fake_get_by_type
        assert usable_ids_for_fetch_type({}, "Comic") == ["COMICVINE"]
        assert usable_ids_for_fetch_type({}, "Manga") == ["ANILIST"]
        plan = resolve_mapping_plan(
            {"FIELD_MAPPING_DEFAULT_COMICFLEXIBLE": "CASCADE"},
            "ComicFlexible",
            flexible_wave="comic",
        )
        assert plan.fetch_library_type == "Comic"
        manga_plan = resolve_mapping_plan({}, "ComicFlexible", flexible_wave="manga")
        assert manga_plan.fetch_library_type == "Manga"


def test_mapping_should_run_gates():
    on = {"FIELD_MAPPING_ENABLED": True, "UI_SHOW_FIELD_MAPPING": True}
    assert mapping_should_run(on, forced_provider="AUTO", manual_mode=False) is True
    assert mapping_should_run(on, forced_provider=None, manual_mode=False) is True
    assert mapping_should_run(on, forced_provider="MAL", manual_mode=False) is False
    assert mapping_should_run(on, forced_provider="AUTO", manual_mode=True) is False
    assert mapping_should_run(
        {"FIELD_MAPPING_ENABLED": False, "UI_SHOW_FIELD_MAPPING": True},
        forced_provider="AUTO",
        manual_mode=False,
    ) is False
    assert mapping_should_run(
        {"FIELD_MAPPING_ENABLED": True, "UI_SHOW_FIELD_MAPPING": False},
        forced_provider="AUTO",
        manual_mode=False,
    ) is False


def test_url_detect_does_not_pin_when_mapping_runs():
    on = {"FIELD_MAPPING_ENABLED": True, "UI_SHOW_FIELD_MAPPING": True}
    assert url_detect_should_pin_provider(on, manual_mode=False) is False
    assert url_detect_should_pin_provider(on, manual_mode=True) is True
    assert url_detect_should_pin_provider(
        {"FIELD_MAPPING_ENABLED": False, "UI_SHOW_FIELD_MAPPING": True},
        manual_mode=False,
    ) is True


def test_enrich_series_url_detect_consults_mapping_gate():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "services" / "enrichment_engine.py").read_text(
        encoding="utf-8"
    )
    assert "url_detect_should_pin_provider" in src


def test_mapping_noop_cascade_zero_overrides():
    with patch("services.field_mapping.usable_ids_for_fetch_type", return_value=["MAL", "ANILIST"]):
        plan = resolve_mapping_plan({}, "Manga")
        assert plan.default == CASCADE
        assert plan.overrides == {}
        assert plan.mapping_noop is True


def test_skip_titles_when_localized_name_overridden():
    keys = skip_keys_for_overrides({"localized_name": "ANILIST", "staff": "MAL"})
    assert "titles" in keys
    assert "localized_name" in keys
    assert "staff" in keys
    assert "writers" in keys


def test_parse_drops_title_format_and_unknown():
    parsed = parse_provider_map(
        {"title": "MAL", "format": "MAL", "cover": "ANILIST", "nope": "MAL"},
        allowed_fields=("cover", "staff"),
        allowed_providers=("ANILIST", "MAL"),
    )
    assert parsed == {"cover": "ANILIST"}
    assert parse_mapping_default("AUTO") == CASCADE
    assert parse_mapping_default("anilist") == "ANILIST"


def test_dropdown_providers_never_calls_comicflexible():
    comic = SimpleNamespace(id="COMICVINE", needs_api_key=False, display_name="ComicVine")
    manga = SimpleNamespace(id="ANILIST", needs_api_key=False, display_name="AniList")
    keyed = SimpleNamespace(id="MAL", needs_api_key=True, display_name="MAL")

    def fake_get_by_type(lib_type, **kwargs):
        assert lib_type != "ComicFlexible"
        if lib_type == "Comic":
            return [comic]
        if lib_type == "Manga":
            return [manga, keyed]
        return []

    with patch("services.field_mapping.ScraperRegistry") as registry:
        registry.get_by_type.side_effect = fake_get_by_type
        comic_items = dropdown_providers({}, "ComicFlexible")
        assert comic_items == [{"id": "COMICVINE", "display_name": "ComicVine"}]
        manga_items = dropdown_providers({}, "Manga")
        assert manga_items == [{"id": "ANILIST", "display_name": "AniList"}]
        with_key = dropdown_providers({"MAL_API_KEY": "abc"}, "Manga")
        assert {p["id"] for p in with_key} == {"ANILIST", "MAL"}
