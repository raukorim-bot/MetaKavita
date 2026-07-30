"""
C53 — non-régression enrichment : mode all / prefer / none + override série
pour Kavita `localizedName` (jamais Series.name).
"""
from models import SeriesOverride
from services import enrichment_engine
from kavita_api import KavitaAPI


def _base_config(**overrides):
    cfg = {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "fake",
        "UI_LANG": "fr",
        "TARGET_LANG": "FR",
        "MAX_GENRES": 5,
        "MAX_TAGS": 15,
        "PROVIDER_1": "FAKE",
        "PROVIDER_2": "NONE",
        "PROVIDER_3": "NONE",
        "SMART_COMPLETION": False,
        "SMART_SCORING": False,
        "AUTO_READING_DIR": False,
        "AUTO_COVER": False,
        "RESET_CONTEXT_ON_FORCE": False,
        "TRANSLATION_PROVIDER": "NONE",
        "DEEPL_API_KEY": "",
        "LOCALIZED_TITLE_MODE": "all",
        "LOCALIZED_TITLE_LANGS": "",
        "PUBLISHER_PREFERENCE": "LOCALIZED",
    }
    cfg.update(overrides)
    return cfg


def _provider_payload():
    return {
        "title": "One Piece",
        "summary": "S",
        "genres": ["Action"],
        "tags": [],
        "staff": [],
        "characters": [],
        "titles": [
            {"lang": "ja-ro", "value": "Wan Pisu"},
            {"lang": "en", "value": "One Piece"},
            {"lang": "ja", "value": "ワンピース"},
        ],
        "alternative_titles": ["Wan Pisu", "One Piece", "ワンピース"],
        "_provider_used": "FAKE",
    }


def _patch_enrichment(mocker, isolated_db, config, cache=None):
    mocker.patch.object(enrichment_engine, "load_config", return_value=config)
    mocker.patch("services.kavita_payload.get_max_genres", side_effect=lambda c=None: 5)
    mocker.patch("services.kavita_payload.get_max_tags", side_effect=lambda c=None: 15)
    mocker.patch.object(enrichment_engine, "get_all_cached_data", side_effect=isolated_db.get_all_cached_data)
    mocker.patch.object(enrichment_engine, "update_status")
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)

    class FakeScraper:
        id = "FAKE"
        display_name = "Fake"
        supported_types = {"Manga"}
        has_direct_id_support = False

        def extract_id_from_url(self, url):
            return None

    fake = FakeScraper()
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", return_value=fake)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[fake])
    mocker.patch("metadata_fetcher.fetch_metadata", return_value=(_provider_payload(), ["FAKE"]))

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={
        "summary": "", "genres": [], "tags": [], "webLinks": "", "language": "",
    })
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="Manga")
    mocker.patch.object(KavitaAPI, "get_series_deep_metadata", return_value={
        "isbn": None, "authors": [], "publisher": None, "year": None,
        "genres": [], "localized_name": None,
    })
    mocker.patch.object(KavitaAPI, "update_series_metadata", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)

    if cache:
        for sid, data in cache.items():
            isolated_db.save_series_override(SeriesOverride(series_id=sid, **data))


def test_enrichment_all_mode_joins_titles(mocker, isolated_db):
    captured = {}

    def _cap(sid, localized_name=None, format_val=None):
        captured["localized_name"] = localized_name
        return True, "ok", True

    _patch_enrichment(mocker, isolated_db, _base_config(LOCALIZED_TITLE_MODE="all"))
    mocker.patch.object(KavitaAPI, "update_series_general", side_effect=_cap)

    ok, _, _ = enrichment_engine.enrich_series(101, "One Piece", force_update=True)
    assert ok is True
    assert captured["localized_name"] == "Wan Pisu / One Piece / ワンピース"


def test_enrichment_prefer_mode_filters_langs(mocker, isolated_db):
    captured = {}

    def _cap(sid, localized_name=None, format_val=None):
        captured["localized_name"] = localized_name
        return True, "ok", True

    _patch_enrichment(
        mocker, isolated_db,
        _base_config(LOCALIZED_TITLE_MODE="prefer", LOCALIZED_TITLE_LANGS="en, ja"),
    )
    mocker.patch.object(KavitaAPI, "update_series_general", side_effect=_cap)

    ok, _, _ = enrichment_engine.enrich_series(102, "One Piece", force_update=True)
    assert ok is True
    assert captured["localized_name"] == "One Piece / ワンピース"


def test_enrichment_none_mode_skips_localized_name(mocker, isolated_db):
    called = {"general": False}

    def _cap(sid, localized_name=None, format_val=None):
        called["general"] = True
        called["localized_name"] = localized_name
        return True, "ok", True

    _patch_enrichment(mocker, isolated_db, _base_config(LOCALIZED_TITLE_MODE="none"))
    mocker.patch.object(KavitaAPI, "update_series_general", side_effect=_cap)

    ok, _, _ = enrichment_engine.enrich_series(103, "One Piece", force_update=True)
    assert ok is True
    # Sans format ni localizedName → update_series_general non appelé
    assert called["general"] is False


def test_enrichment_series_override_langs_beats_global_all(mocker, isolated_db):
    captured = {}

    def _cap(sid, localized_name=None, format_val=None):
        captured["localized_name"] = localized_name
        return True, "ok", True

    _patch_enrichment(
        mocker, isolated_db,
        _base_config(LOCALIZED_TITLE_MODE="all"),
        cache={104: {"alt_title_langs": "ja-ro"}},
    )
    mocker.patch.object(KavitaAPI, "update_series_general", side_effect=_cap)

    ok, _, _ = enrichment_engine.enrich_series(104, "One Piece", force_update=True)
    assert ok is True
    assert captured["localized_name"] == "Wan Pisu"
