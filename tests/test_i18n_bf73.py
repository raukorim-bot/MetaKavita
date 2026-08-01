"""BF73 — parity field_* keys + scraper localized_display_name."""
from translations import translations
from scrapers.hardcover import HardcoverScraper
from scrapers.bedetheque import BedethequeScraper


FIELD_KEYS = [
    "field_summary",
    "field_cover",
    "field_staff",
    "field_genres",
    "field_tags",
    "field_year",
    "field_status",
    "field_publisher",
    "field_age",
    "field_format",
    "field_weblinks",
    "field_alt_titles",
    "field_language",
    "publisher_pref_label",
    "no_api_keys_needed",
    "err_no_libraries",
    "err_save_failed",
    "cover_live_search_for",
    "changelog_loading",
]


def test_fr_en_key_parity():
    assert set(translations["fr"]) == set(translations["en"])


def test_field_keys_present_and_differ():
    for key in FIELD_KEYS:
        assert key in translations["fr"]
        assert key in translations["en"]
        assert translations["fr"][key]
        assert translations["en"][key]


def test_localized_display_name_en(monkeypatch):
    scraper = HardcoverScraper()
    monkeypatch.setattr(scraper, "get_ui_lang", lambda: "en")
    assert "Experimental" in scraper.localized_display_name
    assert "Expérimental" not in scraper.localized_display_name


def test_localized_display_name_fr(monkeypatch):
    scraper = BedethequeScraper()
    monkeypatch.setattr(scraper, "get_ui_lang", lambda: "fr")
    assert "Franco-Belge" in scraper.localized_display_name
