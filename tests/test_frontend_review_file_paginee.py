"""
Review manuelle : la vue liste ne doit pas mentir sur ce qu'elle montre.

`loadQueue()` appelait `/api/manual-reviews` sans `limit` : la limite serveur par
défaut (200) s'appliquait, alors que la pastille affiche le total réel
(`count_pending_reviews()`). Après un gros lot en mode review manuelle, la liste
et le compteur se contredisaient — et, plus grave, une fois les 200 traitées la
modale annonçait le récap « tout est fait » alors que des centaines de séries
attendaient encore en base.

La page est désormais demandée explicitement, sa troncature est dite à l'écran, et
l'épuisement d'une page va chercher la suivante au lieu de conclure. Charger toute
la file d'un coup était l'autre option : chaque review transporte ses cartes
candidates (résumés compris), l'ouverture de la modale sur une grosse
bibliothèque en aurait souffert.

Le frontend est vérifié sur les sources, comme `test_frontend_root_path.py`.
"""

from __future__ import annotations

import os
import re

_JS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "static", "js", "manual_review.js")
)
_MODAL = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "templates", "partials", "_manual_review_modal.html"
    )
)


def _read(path=_JS):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _function_body(src, name):
    start = src.index("function " + name)
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError(f"corps de {name} introuvable")


def test_la_file_est_demandee_avec_une_taille_de_page_explicite():
    body = _function_body(_read(), "loadQueue")

    assert "limit=" in body, (
        "sans `limit`, la limite serveur par défaut s'applique en silence : la "
        "liste plafonne à 200 alors que la pastille annonce le total réel"
    )
    assert re.search(r"QUEUE_PAGE_SIZE", body)


def test_une_page_tronquee_est_annoncee_a_lecran():
    src = _read()
    assert "queueTruncated" in _function_body(src, "loadQueue")
    assert "mrListTruncated" in _function_body(src, "renderListPanel")
    assert 'id="mrListTruncated"' in _read(_MODAL)


def test_une_page_epuisee_charge_la_suivante_avant_de_conclure():
    body = _function_body(_read(), "showRecapIfEmpty")

    assert "queueTruncated" in body and "loadQueue()" in body, (
        "la file locale vidée déclenchait le récap « tout est fait » alors que "
        "la base contenait encore les reviews suivantes"
    )


def test_les_libelles_de_troncature_existent_dans_les_deux_langues():
    from translations import translations

    for lang in ("fr", "en"):
        assert translations[lang]["mr_list_truncated"]


def test_la_cle_de_troncature_est_injectee_dans_le_js():
    """Les clés `mr_*` ne sont pas injectées par boucle : sans la ligne dans
    index.html, le libellé retomberait sur son défaut français."""
    html = _read(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates", "index.html"))
    )
    assert "mr_list_truncated" in html
