"""
Review manuelle : la flèche droite doit passer par `showCurrentReview()`.

`showCurrentReview()` est le seul endroit qui détecte `state ===
"awaiting_confirm"` (ou l'auto-confirm) pour restaurer le panneau d'édition, les
sources de fusion et le preview parqué. Le handler `ArrowRight` forçait
`setPhase("pick")` + `renderCandidates()` : l'utilisateur retombait sur la liste
de candidats d'une série pour laquelle il avait déjà choisi un fournisseur, et
devait tout refaire. Il ne remettait pas non plus `baselinePreview` à `null`,
contrairement à `goToPrevReview()` : le preview de la série précédente restait
en mémoire.

Le frontend est vérifié sur les sources, comme `test_frontend_root_path.py`.
"""

from __future__ import annotations

import os
import re

_JS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "static", "js", "manual_review.js")
)


def _read():
    with open(_JS, encoding="utf-8") as fh:
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


def test_les_deux_sens_de_navigation_sont_symetriques():
    src = _read()
    suivant = _function_body(src, "goToNextReview")
    precedent = _function_body(src, "goToPrevReview")

    for body, sens in ((suivant, "goToNextReview"), (precedent, "goToPrevReview")):
        assert "showCurrentReview()" in body, (
            f"{sens} n'appelle pas showCurrentReview() : le panneau affiché peut "
            "ne pas correspondre à l'état stocké (awaiting_confirm)"
        )
        assert "baselinePreview = null" in body, (
            f"{sens} garde le preview de la série précédente en mémoire"
        )
        assert "selectedProvider = null" in body
        assert "includeProviders = []" in body


def test_la_fleche_droite_delegue_la_navigation():
    src = _read()
    handler = src[src.index('e.key === "ArrowRight"'):]
    handler = handler[:handler.index('e.key === "ArrowLeft"')]

    assert "goToNextReview()" in handler
    assert 'setPhase("pick")' not in handler, (
        "la flèche droite force encore la phase pick : une série déjà pointée "
        "en awaiting_confirm réouvrirait sa liste de candidats"
    )
    assert "renderCandidates()" not in handler


def test_la_borne_de_fin_de_file_est_conservee():
    """Sur la dernière review, la flèche droite ne doit rien faire."""
    body = _function_body(_read(), "goToNextReview")
    assert re.search(r"currentIndex\s*>=\s*queue\.length\s*-\s*1", body), (
        "goToNextReview doit s'arrêter à la dernière review de la file"
    )
