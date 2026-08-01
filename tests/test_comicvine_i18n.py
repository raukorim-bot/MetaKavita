"""
BF55 — labels covers ComicVine suivent UI_LANG.
BF74 — summary ComicVine sans emoji / balises décoratives.
"""
from scrapers.comicvine import (
    ComicVineScraper,
    compose_summary_parts,
    html_to_summary_text,
)


def test_comicvine_cover_labels_follow_ui_lang(monkeypatch):
    scraper = ComicVineScraper()

    monkeypatch.setattr(scraper, "get_ui_lang", lambda: "en")
    assert scraper.t("cover_provider_series") == "ComicVine (Series)"
    assert scraper.t("unknown_title") == "Unknown"

    monkeypatch.setattr(scraper, "get_ui_lang", lambda: "fr")
    assert scraper.t("cover_provider_series") == "ComicVine (Série)"
    assert scraper.t("unknown_title") == "Inconnu"


def test_compose_summary_parts_no_decorative_labels():
    out = compose_summary_parts(
        "Since its start as X-Men (1991), the series has gone through various name changes.",
        "",
    )
    assert "📚" not in out
    assert "[Série" not in out
    assert "[Series" not in out
    assert "X-Men (1991)" in out


def test_compose_summary_parts_dedupes_and_joins():
    a = "Short volume deck."
    b = "Longer issue synopsis about the first arc."
    out = compose_summary_parts(a, b)
    assert out == f"{a}\n\n{b}"
    assert compose_summary_parts(a, a) == a
    assert compose_summary_parts(a, f"{a}\n\nextra") == f"{a}\n\nextra"


def test_html_to_summary_text_strips_noisy_sections():
    html = (
        "<p>Heroes assemble.</p>"
        "<h2>Collected Editions</h2><ul><li>Omnibus</li></ul>"
        "<p>3 issues in this volume</p>"
    )
    text = html_to_summary_text(html)
    assert "Heroes assemble" in text
    assert "Omnibus" not in text
    assert "issues in this volume" not in text


def test_comicvine_translations_no_summary_label_keys():
    scraper = ComicVineScraper()
    for lang in ("fr", "en"):
        keys = scraper.translations[lang]
        assert "lbl_series" not in keys
        assert "lbl_album" not in keys
        assert "lbl_synopsis" not in keys
