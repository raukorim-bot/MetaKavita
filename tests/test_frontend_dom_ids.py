"""
Un identifiant DOM qui n'existe nulle part ne fait aucun bruit (BF146).

`license_nag.js` cherchait `opt_super_manual_review` pour savoir si le Mode
Super est actif ; la case s'appelle `sidebar_manual_review_super` depuis
toujours. `getElementById` rend `null`, le `if (el)` l'avale, et le repli
`localStorage` interrogeait une clé que rien n'écrit dans tout le dépôt : la
variante « super_glow » n'était jamais éligible et ses trois traductions
`nag_*_super`, pourtant injectées, ne s'affichaient jamais. Aucune erreur en
console, aucun test rouge — d'où ce garde-fou sur les sources.
"""
import os
import re

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _all_templates():
    out = []
    for base, _dirs, files in os.walk(os.path.join(_ROOT, "templates")):
        for name in files:
            if name.endswith(".html"):
                with open(os.path.join(base, name), encoding="utf-8") as fh:
                    out.append(fh.read())
    return out


def test_le_nagware_lit_des_identifiants_qui_existent_vraiment():
    src = _read("static/js/license_nag.js")
    ids = set(re.findall(r"getElementById\(\s*[\"']([\w-]+)[\"']", src))
    assert ids, "aucun identifiant lu : le motif de recherche a dû changer"

    templates = _all_templates()
    for dom_id in sorted(ids):
        assert any(f'id="{dom_id}"' in tpl for tpl in templates), (
            f"license_nag.js interroge #{dom_id}, qu'aucun gabarit ne pose : "
            "le nagware se contentera silencieusement d'un null"
        )


def test_le_mode_super_est_lu_au_meme_endroit_par_toute_l_interface():
    """La sidebar est la seule source de vérité du Mode Super : le nagware doit
    la lire exactement comme la modale de review et la sauvegarde de config."""
    nag = _read("static/js/license_nag.js")
    review = _read("static/js/manual_review.js")
    config = _read("static/js/config.js")

    assert "sidebar_manual_review_super" in nag
    assert "sidebar_manual_review_super" in review
    assert "sidebar_manual_review_super" in config
    assert "opt_super_manual_review" not in nag, (
        "identifiant fantôme : personne ne le pose, rien ne l'écrit en localStorage"
    )
