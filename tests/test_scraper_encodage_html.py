"""
Encodage : la soupe se construit sur les octets, pas sur `res.text`.

Sur une réponse sans `charset` dans l'en-tête, `requests` suppose ISO-8859-1 et
`curl_cffi` suppose UTF-8 ; ni l'un ni l'autre ne lit le `<meta charset>` de la
page. En passant `res.text` à BeautifulSoup, la détection est court-circuitée et
c'est cette supposition qui gagne. Le cas `curl_cffi` est le plus grave : son
décodage se fait avec `errors="replace"`, donc les accents deviennent des U+FFFD
**irrécupérables** — écrits puis verrouillés dans Kavita.

En passant `res.content`, BeautifulSoup lit le `<meta charset>` et retombe juste
dans les deux cas. Le contre-exemple correct existait déjà : `babelio.py`.

Les fournisseurs français concernés sont tous des sites HTML sans API, où ce sont
justement les titres et les résumés qui portent les accents.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Titre volontairement chargé en accents, y compris une cédille et un tréma.
TITRE = "Le Génie des Alpages — Où ça ? Noël à l'Élysée"

_PAGE_UTF8 = (
    '<html><head><meta charset="utf-8"><title>{t}</title></head>'
    '<body><h1>{t}</h1></body></html>'
).format(t=TITRE).encode("utf-8")

_PAGE_LATIN1 = (
    '<html><head><meta charset="iso-8859-1"><title>{t}</title></head>'
    '<body><h1>{t}</h1></body></html>'
).format(t=TITRE.replace("—", "-")).encode("iso-8859-1")


class _ResponseSansCharset:
    """Réponse dont l'en-tête n'annonce PAS de charset.

    `text` reproduit la supposition du client HTTP : UTF-8 pour `curl_cffi`
    (avec `errors="replace"`, d'où les U+FFFD), ISO-8859-1 pour `requests`.
    """

    def __init__(self, content: bytes, suppose: str):
        self.status_code = 200
        self.headers = {"Content-Type": "text/html"}
        self.content = content
        self.url = "https://exemple.test/serie"
        self.text = content.decode(suppose, errors="replace")


# Les scrapers HTML et le nom de leur constructeur de soupe.
SCRAPERS_HTML = ["bedetheque", "planetebd", "decitre", "locg"]


def _module(nom: str):
    path = ROOT / "scrapers" / f"{nom}.py"
    spec = importlib.util.spec_from_file_location(f"scrapers.{nom}_encodage_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _classe_scraper(module):
    for attr in vars(module).values():
        if isinstance(attr, type) and attr.__name__.endswith("Scraper") and hasattr(attr, "id"):
            if getattr(attr, "id", None) and attr.__module__ == module.__name__:
                return attr
    raise AssertionError(f"aucune classe de scraper dans {module.__name__}")


@pytest.mark.parametrize("nom", SCRAPERS_HTML)
@pytest.mark.parametrize(
    ("page", "suppose"),
    [
        # Page UTF-8 servie à curl_cffi : sans charset annoncé, il suppose déjà
        # UTF-8 et s'en tire ; c'est le témoin.
        (_PAGE_UTF8, "utf-8"),
        # Page UTF-8 servie à requests : il suppose ISO-8859-1 et rend du mojibake.
        (_PAGE_UTF8, "iso-8859-1"),
        # Page ISO-8859-1 servie à curl_cffi : décodage UTF-8 impossible, les
        # accents deviennent des U+FFFD irrécupérables.
        (_PAGE_LATIN1, "utf-8"),
    ],
)
def test_les_accents_survivent_a_labsence_de_charset(nom, page, suppose):
    module = _module(nom)
    scraper = _classe_scraper(module)()
    res = _ResponseSansCharset(page, suppose)

    soup = scraper._soup(res)
    titre = soup.h1.get_text(strip=True)

    assert "\ufffd" not in titre, (
        f"[{nom}] caractère de remplacement dans « {titre} » : la soupe a été "
        "construite sur `res.text`, donc sur la supposition du client HTTP"
    )
    assert "Génie" in titre and "Élysée" in titre, (
        f"[{nom}] accents corrompus : « {titre} »"
    )


@pytest.mark.parametrize("nom", SCRAPERS_HTML)
def test_une_reponse_de_test_sans_octets_reste_lisible(nom):
    """Les doublures du dépôt (`MagicMock`, `SimpleNamespace`) n'exposent souvent
    que `.text` : le constructeur doit accepter ce repli, sinon BeautifulSoup
    recevrait un mock et les tests existants deviendraient illisibles."""

    class _Doublure:
        status_code = 200
        content = None
        text = "<html><body><h1>Astérix</h1></body></html>"

    module = _module(nom)
    scraper = _classe_scraper(module)()

    soup = scraper._soup(_Doublure())

    assert soup.h1.get_text(strip=True) == "Astérix"
