"""BF186 — la barre latérale ne doit pas se dérouler au chargement.

Le panneau Options n'avait pas `open` dans le HTML. `main.js` l'ouvrait au
`DOMContentLoaded`, après tous les scripts du bas de page, et
`::details-content` interpolait `block-size` 0 → auto : un déroulement de
0,28 s. L'état doit être posé pendant l'analyse (comme l'encart Companion),
et la transition coupée jusqu'au premier paint (`html.mk-boot`).
"""
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_options_accordion_starts_open_in_the_markup():
    sidebar = _read("templates/partials/_sidebar.html")
    assert 'id="scrapingOptionsDetails" open>' in sidebar


def test_accordion_state_is_restored_during_parse_not_after_scripts():
    sidebar = _read("templates/partials/_sidebar.html")
    main_js = _read("static/js/main.js")
    assert "mk_scraping_options_open" in sidebar
    assert "mk_scraping_cat_open" in sidebar
    assert "mk_sidebar_scroll" in sidebar
    assert sidebar.index('id="scrapingOptionsDetails"') < sidebar.index("mk_scraping_options_open")
    assert sidebar.index("mk_scraping_options_open") < sidebar.index("</aside>")
    assert "mk_scraping_options_open" in main_js
    assert "mk_sidebar_scroll" in main_js
    assert "function snapshotSidebarUi" in main_js
    assert "function applySidebarUiMemory" in main_js
    assert "pagehide" in main_js
    bind = main_js.split("function restoreScrapingOptionsOpenState", 1)[1]
    assert "if (!restoring) snapshotSidebarUi()" in bind
    assert "applySidebarUiMemory()" in bind.split("restoring = false", 1)[0]


def test_first_paint_skips_details_content_transition():
    index = _read("templates/index.html")
    css = _read("static/css/style.css")
    html_tag = index.split("<html", 1)[1].split(">", 1)[0]
    assert 'class="mk-boot"' in html_tag
    assert "classList.remove('mk-boot')" in index
    assert "html.mk-boot .scraping-options-details::details-content" in css
    assert "html.mk-boot .so-cat::details-content" in css
    boot_block = css.split("html.mk-boot .scraping-options-details::details-content", 1)[1]
    boot_block = boot_block.split(".scraping-options-body", 1)[0]
    assert "transition: none" in boot_block
