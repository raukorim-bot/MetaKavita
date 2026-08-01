"""
BF55 — labels décoratifs ComicVine (résumés / covers) suivent UI_LANG.
"""
from scrapers.comicvine import ComicVineScraper


def test_comicvine_summary_labels_follow_ui_lang(monkeypatch):
    scraper = ComicVineScraper()

    monkeypatch.setattr(scraper, "get_ui_lang", lambda: "en")
    assert "Series" in scraper.t("lbl_series").format("Batman")
    assert "Issue" in scraper.t("lbl_album").format("Beyond")
    assert "Synopsis" in scraper.t("lbl_synopsis").format("text")
    assert "Série" not in scraper.t("lbl_series").format("Batman")
    assert scraper.t("cover_provider_series") == "ComicVine (Series)"
    assert scraper.t("unknown_title") == "Unknown"

    monkeypatch.setattr(scraper, "get_ui_lang", lambda: "fr")
    assert "Série" in scraper.t("lbl_series").format("Batman")
    assert "Album" in scraper.t("lbl_album").format("Beyond")
    assert scraper.t("cover_provider_series") == "ComicVine (Série)"
    assert scraper.t("unknown_title") == "Inconnu"
