"""BF60 — labels covers Manga-News suivent UI_LANG."""
from scrapers.manganews import MangaNewsScraper


def test_manganews_cover_labels_follow_ui_lang(monkeypatch):
    scraper = MangaNewsScraper()

    monkeypatch.setattr(scraper, "get_ui_lang", lambda: "en")
    assert scraper.t("cover_provider_series") == "Manga-News (Series)"
    assert scraper.t("cover_provider_volume") == "Manga-News (Volume)"
    assert "Série" not in scraper.t("cover_provider_series")
    assert "Tome" not in scraper.t("cover_provider_volume")

    monkeypatch.setattr(scraper, "get_ui_lang", lambda: "fr")
    assert scraper.t("cover_provider_series") == "Manga-News (Série)"
    assert scraper.t("cover_provider_volume") == "Manga-News (Tome)"
