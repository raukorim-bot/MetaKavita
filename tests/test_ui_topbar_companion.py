"""
Barre du haut à deux menus, et encart d'installation du Companion (C81).

Trois choses se vérifient ici, et chacune s'est déjà cassée ailleurs de la même
façon :

1. **Deux menus voisins.** « Scrapers » installe et met à jour, « Aide » ne fait
   que lire. Tant qu'il n'y en avait qu'un, un seul `closeHelpMenu()` suffisait ;
   à deux, ouvrir l'un doit fermer l'autre, sinon les deux panneaux se
   superposent dans le coin droit.

2. **Des icônes qui existent.** Un `<use href="#mk-ico-…">` qui ne trouve pas son
   symbole n'émet aucune erreur : il ne dessine rien. Une faute de frappe dans un
   identifiant se voit donc à l'œil, en production, sur un bouton devenu muet —
   d'où le test qui confronte tous les `href` du dossier `templates/` aux
   symboles réellement déclarés dans le sprite.

3. **Un encart qui s'oublie et se retrouve.** La croix doit tenir d'un
   chargement à l'autre (sinon elle ne masque rien), et ne doit pas être un
   aller sans retour : le menu Aide le rappelle. Le dévoilement se fait pendant
   l'analyse du document, non au `DOMContentLoaded`, pour que celui qui a fermé
   l'encart ne le voie pas clignoter à chaque page.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
SPRITE = (ROOT / "templates" / "partials" / "_icons_sprite.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")

CHROME_ZIP = "metakavita-companion-chrome.zip"
FIREFOX_ZIP = "metakavita-companion-firefox.zip"
DISMISS_KEY = "mk_companion_card_dismissed"


@pytest.fixture(scope="module")
def index():
    return BeautifulSoup(INDEX, "html.parser")


def _translations():
    from translations import translations

    return translations


# ===== Les deux menus =====


@pytest.mark.parametrize(
    "button_id, dropdown_id",
    [("scrapersMenuBtn", "scrapersDropdown"), ("helpMenuBtn", "helpDropdown")],
)
def test_each_menu_button_announces_the_panel_it_opens(index, button_id, dropdown_id):
    """`aria-haspopup` et `aria-controls` ne sont pas décoratifs : c'est aussi
    `aria-expanded` que le CSS lit pour surligner le bouton et retourner le
    chevron."""
    btn = index.find("button", id=button_id)

    assert btn is not None
    assert btn["aria-haspopup"] == "true"
    assert btn["aria-controls"] == dropdown_id
    assert btn["aria-expanded"] == "false"
    assert f"toggleTopbarMenu(event, '{dropdown_id}')" in btn["onclick"]
    assert index.find("div", id=dropdown_id) is not None


@pytest.mark.parametrize("button_id", ["scrapersMenuBtn", "helpMenuBtn"])
def test_a_menu_button_looks_like_a_menu(index, button_id):
    """Le reproche de départ : rien ne disait qu'on pouvait cliquer. Un chevron,
    donc, et un libellé qui peut tomber sur petit écran — l'aria-label reste."""
    btn = index.find("button", id=button_id)

    carets = [u["href"] for u in btn.find_all("use") if u.get("href") == "#mk-ico-caret"]
    assert carets, "le bouton devrait porter un chevron"
    assert btn.find("span", class_="topbar-menu-label") is not None
    assert btn.get("aria-label"), "le libellé disparaît sous 720 px"


def test_the_scrapers_left_the_help_menu(index):
    """Le partage demandé : la gestion des scrapers a son propre menu, et n'est
    plus perdue au milieu de la documentation."""
    help_menu = index.find("div", id="helpDropdown")
    scrapers_menu = index.find("div", id="scrapersDropdown")

    help_hrefs = [a.get("href", "") for a in help_menu.find_all("a")]
    scraper_hrefs = [a.get("href", "") for a in scrapers_menu.find_all("a")]

    assert not [h for h in help_hrefs if "scrapers_manage" in h]
    assert [h for h in scraper_hrefs if "scrapers_manage.manage" in h]
    assert [h for h in scraper_hrefs if "scrapers_manage.store" in h]


def test_only_one_menu_stays_open():
    """Deux panneaux ancrés dans le même coin : sans fermeture préalable, ils se
    chevauchent."""
    body = MAIN_JS[MAIN_JS.index("function toggleTopbarMenu"):]
    body = body[:body.index("\n}")]

    assert "closeTopbarMenus()" in body
    assert "function closeTopbarMenus" in MAIN_JS


def test_a_click_outside_closes_the_menus():
    """La zone testée doit être celle qui existe : le sélecteur a suivi le
    renommage `.topbar-help` → `.topbar-menu`."""
    assert "closest('.topbar-menu')" in MAIN_JS
    assert ".topbar-help" not in MAIN_JS
    assert ".topbar-help" not in CSS, "sélecteur mort : plus aucun élément ne le porte"
    assert ".topbar-menu {" in CSS


def test_escape_closes_the_menus():
    escape = MAIN_JS[MAIN_JS.index("event.key === 'Escape'"):]

    assert "closeTopbarMenus()" in escape[:400]


def test_the_open_state_is_visible():
    """Le seul état conservé est `aria-expanded` ; le CSS en tire le surlignage
    et la rotation du chevron. S'il disparaît, le bouton ouvert redevient
    indistinct."""
    assert '.topbar-menu-btn[aria-expanded="true"]' in CSS
    assert re.search(
        r'\.topbar-menu-btn\[aria-expanded="true"\] \.mk-caret \{[^}]*rotate\(180deg\)',
        CSS,
        re.S,
    )


# ===== Les icônes =====


def _declared_symbols():
    return set(re.findall(r'<symbol id="(mk-ico-[a-z-]+)"', SPRITE))


def _referenced_symbols():
    refs = set()
    for path in (ROOT / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        refs.update(re.findall(r'<use href="#(mk-ico-[a-z-]+)"', text))
    return refs


def test_every_icon_used_is_declared():
    """Un `<use>` orphelin ne dessine rien et ne dit rien : c'est un bouton vide
    en production."""
    missing = sorted(_referenced_symbols() - _declared_symbols())

    assert not missing, f"symboles absents du sprite : {missing}"


def test_the_sprite_is_read_before_the_bar_that_uses_it():
    """`<use>` ne résout pas un symbole déclaré plus bas avant la fin de
    l'analyse : le sprite passait après la barre du haut, dont les icônes sont
    visibles au premier rendu."""
    assert INDEX.index("_icons_sprite.html") < INDEX.index('class="topbar"')


# ===== L'encart Companion =====


def test_the_card_offers_the_two_browsers(index):
    """Aucun des deux n'est le chemin recommandé : c'est celui qu'on a déjà."""
    card = index.find("aside", id="companionCard")

    assert card is not None
    hrefs = [a["href"] for a in card.find_all("a", class_="companion-dl")]
    assert len(hrefs) == 2
    assert any(CHROME_ZIP in h for h in hrefs)
    assert any(FIREFOX_ZIP in h for h in hrefs)


def test_the_help_menu_opens_the_user_guides(index):
    """Le README racine n'est plus le guide : Aide pointe vers docs/en ou
    docs/fr selon la langue de l'interface. L'encart Companion garde le
    mode opératoire complet sous companion/README.md."""
    help_menu = index.find("div", id="helpDropdown")
    hrefs = [a.get("href", "") for a in help_menu.find_all("a")]

    assert any("docs/" in h and h.endswith("/README.md") for h in hrefs)
    assert any("docs/" in h and h.endswith("/companion.md") for h in hrefs)
    assert not any(h.rstrip('"').endswith("/blob/dev/README.md") for h in hrefs)


def test_the_card_links_the_install_guide(index):
    """L'extension s'installe à la main : deux zips sans le mode opératoire ne
    servent à rien."""
    card = index.find("aside", id="companionCard")
    guide = card.find("a", class_="companion-card-guide")

    assert guide is not None
    assert guide["href"].endswith("companion/README.md")
    assert guide.get("target") == "_blank"


def test_the_card_can_be_closed(index):
    card = index.find("aside", id="companionCard")
    close = card.find("button", class_="companion-card-close")

    assert close is not None
    assert "dismissCompanionCard()" in close["onclick"]
    assert close.get("aria-label"), "une croix sans nom n'est rien pour un lecteur d'écran"


def test_closing_the_card_outlives_the_page():
    """Une croix qui ne tient pas jusqu'au chargement suivant ne masque rien."""
    assert "localStorage.setItem(COMPANION_CARD_KEY, '1')" in MAIN_JS
    assert f"'{DISMISS_KEY}'" in MAIN_JS


def test_the_card_hides_itself_before_being_painted(index):
    """Rendu masqué puis dévoilé pendant l'analyse : dans l'autre sens, celui qui
    l'a fermé le verrait clignoter à chaque chargement."""
    card = index.find("aside", id="companionCard")

    assert card.has_attr("hidden")
    reveal = INDEX[INDEX.index('id="companionCard"'):]
    reveal = reveal[:reveal.index("</script>")]
    assert DISMISS_KEY in reveal
    assert "el.hidden = false" in reveal
    assert "DOMContentLoaded" not in reveal


def test_the_help_menu_brings_the_card_back(index):
    """Sinon la croix est un aller sans retour, et l'adresse des deux zips n'est
    plus nulle part dans l'interface."""
    btn = index.find("button", id="helpCompanionCardBtn")

    assert btn is not None
    assert "showCompanionCard()" in btn["onclick"]
    assert "function showCompanionCard" in MAIN_JS
    assert "localStorage.removeItem(COMPANION_CARD_KEY)" in MAIN_JS


def test_the_card_never_pushes_the_page_when_hidden():
    """`display: flex` gagnerait contre l'attribut `hidden` sans cette règle."""
    assert ".companion-card[hidden]" in CSS
    assert re.search(r"\.companion-card\[hidden\] \{[^}]*display: none !important", CSS, re.S)


# ===== Les textes =====


@pytest.mark.parametrize(
    "key",
    ["scrapers_menu", "scrapers_menu_hint", "scrapers_menu_group_manage",
     "companion_card_title", "companion_card_body", "companion_card_guide",
     "companion_card_chrome", "companion_card_firefox", "companion_card_zip",
     "companion_card_dismiss", "companion_card_reopen"],
)
def test_the_labels_exist_in_both_languages(key):
    for lang in ("fr", "en"):
        assert key in _translations()[lang], f"{lang} : clé {key} absente"


def test_the_card_says_the_extension_is_sideloaded():
    """Elle n'est pas sur les stores : l'annoncer évite le rapport de bug « le
    lien ne mène pas à une page d'extension »."""
    for lang, needle in (("fr", "main"), ("en", "sideload")):
        assert needle in _translations()[lang]["companion_card_body"].lower()
