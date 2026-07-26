"""
C53 — sélection de Kavita `localizedName` (mode all / prefer / none + override série).

V1 : on ne réécrit jamais Series.name ; multi-titres joints par " / " restent le défaut.
"""
from localized_titles import (
    entries_from_provider,
    merge_title_entries,
    normalize_lang_tag,
    parse_lang_list,
    resolve_effective_title_policy,
    resolve_localized_name,
)


SAMPLE = {
    "titles": [
        {"lang": "ja-ro", "value": "One Piece"},
        {"lang": "en", "value": "One Piece"},
        {"lang": "ja", "value": "ワンピース"},
        {"lang": "fr", "value": "One Piece"},
    ],
    "alternative_titles": ["One Piece", "ワンピース", "Wan Pîsu"],
}


def test_normalize_lang_aliases():
    assert normalize_lang_tag("en_jp") == "ja-ro"
    assert normalize_lang_tag("EN-JP") == "ja-ro"
    assert normalize_lang_tag("romaji") == "ja-ro"
    assert normalize_lang_tag("jpn") == "ja"
    assert normalize_lang_tag("eng") == "en"


def test_parse_lang_list_dedupes_and_orders():
    assert parse_lang_list("en, ja-ro, en, JA") == ["en", "ja-ro", "ja"]
    assert parse_lang_list("") == []
    assert parse_lang_list("  en;ja-ro  ") == ["en", "ja-ro"]


def test_entries_prefer_structured_titles():
    entries = entries_from_provider(SAMPLE)
    assert entries[0] == ("ja-ro", "One Piece")
    assert ("ja", "ワンピース") in entries
    # Doublon de valeur "One Piece" (en) ignoré après ja-ro
    values = [v for _, v in entries]
    assert values.count("One Piece") == 1


def test_entries_fallback_to_flat_alternative_titles():
    entries = entries_from_provider({"alternative_titles": ["A", "B", "A"]})
    assert entries == [("", "A"), ("", "B")]


def test_resolve_all_joins_unique_titles():
    # Doublons de valeur cross-lang dédupliqués (en == ja-ro "One Piece")
    result = resolve_localized_name(SAMPLE, mode="all")
    assert result == "One Piece / ワンピース"


def test_resolve_prefer_orders_by_lang_list():
    data = {
        "titles": [
            {"lang": "ja-ro", "value": "Wan Pisu"},
            {"lang": "en", "value": "One Piece"},
            {"lang": "ja", "value": "ワンピース"},
        ]
    }
    assert resolve_localized_name(data, mode="prefer", langs=["en", "ja-ro"]) == "One Piece / Wan Pisu"
    assert resolve_localized_name(data, mode="prefer", langs=["ja"]) == "ワンピース"


def test_resolve_prefer_no_match_falls_back_to_all():
    data = {"titles": [{"lang": "ja", "value": "テスト"}]}
    assert resolve_localized_name(data, mode="prefer", langs=["en"]) == "テスト"


def test_resolve_none_returns_none():
    assert resolve_localized_name(SAMPLE, mode="none") is None


def test_resolve_prefer_empty_langs_behaves_like_all():
    data = {
        "titles": [
            {"lang": "en", "value": "English"},
            {"lang": "ja", "value": "日本語"},
        ]
    }
    assert resolve_localized_name(data, mode="prefer", langs=[]) == "English / 日本語"


def test_merge_title_entries_dedupes():
    a = [{"lang": "en", "value": "Foo"}, {"lang": "ja", "value": "バー"}]
    b = [{"lang": "en_jp", "value": "Foo"}, {"lang": "fr", "value": "Fou"}]
    merged = merge_title_entries(a, b)
    assert merged == [
        {"lang": "en", "value": "Foo"},
        {"lang": "ja", "value": "バー"},
        {"lang": "fr", "value": "Fou"},
    ]


def test_effective_policy_series_override_forces_prefer():
    mode, langs = resolve_effective_title_policy(
        {"LOCALIZED_TITLE_MODE": "all", "LOCALIZED_TITLE_LANGS": "fr"},
        series_alt_title_langs="en, ja-ro",
    )
    assert mode == "prefer"
    assert langs == ["en", "ja-ro"]


def test_effective_policy_empty_override_inherits_global():
    mode, langs = resolve_effective_title_policy(
        {"LOCALIZED_TITLE_MODE": "prefer", "LOCALIZED_TITLE_LANGS": "en,ja"},
        series_alt_title_langs="",
    )
    assert mode == "prefer"
    assert langs == ["en", "ja"]


def test_effective_policy_invalid_mode_defaults_all():
    mode, langs = resolve_effective_title_policy(
        {"LOCALIZED_TITLE_MODE": "weird", "LOCALIZED_TITLE_LANGS": ""},
        None,
    )
    assert mode == "all"
    assert langs == []
