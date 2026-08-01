"""BF76 — operational Live Logs and API messages follow UI_LANG."""

import logging

from translations import get_ui_translations, translations


def _bf76_keys(lang):
    keys = list(translations[lang])
    return keys[keys.index("msg_success"):]


def test_bf76_keys_have_exact_parity_and_nonempty_values():
    fr_keys = _bf76_keys("fr")
    en_keys = _bf76_keys("en")
    assert fr_keys == en_keys
    assert all(str(translations["fr"][key]).strip() for key in fr_keys)
    assert all(str(translations["en"][key]).strip() for key in en_keys)


def test_bf76_english_samples_are_english():
    t = get_ui_translations(ui_lang="en")
    assert "Smart Scoring" in t["log_smart_scoring_on"]
    assert "Configuration file" in t["log_config_unreadable_after_write"]
    assert "already processing" in t["msg_already_processing"].lower()


def test_enrichment_smart_scoring_log_follows_ui_lang(monkeypatch, caplog):
    from services import enrichment_engine
    import metadata_fetcher

    class FakeKavita:
        def __init__(self, *_args, **_kwargs):
            pass

        def authenticate(self):
            return True

        def get_series_metadata(self, _series_id):
            return {"summary": "", "genres": [], "tags": [], "webLinks": "", "language": ""}

        def get_library_type_for_series(self, _series_id):
            return "Manga"

        def get_series_deep_metadata(self, _series_id):
            return {"isbn": None, "authors": [], "publisher": None, "year": None, "genres": []}

    monkeypatch.setattr(
        enrichment_engine,
        "load_config",
        lambda: {
            "UI_LANG": "en",
            "KAVITA_URL": "http://kavita.local",
            "KAVITA_API_KEY": "key",
            "SMART_SCORING": True,
            "MANUAL_REVIEW_MODE": False,
        },
    )
    monkeypatch.setattr(enrichment_engine, "KavitaAPI", FakeKavita)
    monkeypatch.setattr(enrichment_engine, "get_all_cached_data", lambda: {})
    monkeypatch.setattr(enrichment_engine, "_providers_from_config", lambda *_args: ["TEST"])
    monkeypatch.setattr(metadata_fetcher, "fetch_metadata", lambda *_args, **_kwargs: (None, []))

    with caplog.at_level(logging.INFO):
        enrichment_engine.enrich_series(7601, "BF76", force_update=True)

    assert "Smart Scoring enabled (best score wins)." in caplog.text
    assert "meilleur score gagne" not in caplog.text
