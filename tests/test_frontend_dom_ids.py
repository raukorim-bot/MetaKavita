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


def test_config_save_keeps_a_toast_across_reload():
    """Sauvegarder la modale ne recharge plus : le toast s'affiche sur place.
    Le toast doit vivre hors du `{% if libraries %}` (sinon une install neuve
    n'a nulle part où l'afficher). Changer la langue UI recharge encore, et
    réutilise le flag sessionStorage pour le toast d'après."""
    config = _read("static/js/config.js")
    utils = _read("static/js/utils.js")
    index = _read("templates/index.html")
    modal = _read("templates/partials/_config_modal.html")
    assert "function showAppToast(" in utils
    assert 'id="appToast"' in index
    after_toast = index.split('id="appToast"', 1)[1]
    assert "{% if libraries %}" not in after_toast.split("<script", 1)[0]
    onsubmit = modal.split("id=\"configForm\"", 1)[1].split(">", 1)[0]
    assert "saveConfig({ notify: true })" in onsubmit
    assert "reload" not in onsubmit
    assert modal.count("saveConfig({ reload: true })") == 1
    assert 'id="uiLangSelect"' in modal
    assert "config_saved" in config
    save_fn = config.split("function saveConfig(", 1)[1]
    assert "options.notify" in save_fn.split("const form", 1)[0] or "notify" in save_fn[:400]
    assert "showAppToast(savedMsg)" in save_fn
    reload_chunk = save_fn.split("window.location.reload()", 1)[0]
    assert "mk_config_saved" in reload_chunk
    assert "if (shouldReload)" in reload_chunk.split("mk_config_saved", 1)[0][-80:]
    before_flag = save_fn.split("mk_config_saved", 1)[0]
    assert "has_kavita_api_key" in before_flag
    assert "return;" in before_flag.split("has_kavita_api_key", 1)[1]
    silent_saves = config.split("function saveConfig(", 1)[0]
    assert silent_saves.count("saveConfig();") >= 1
    assert "mk_config_saved" not in silent_saves
    assert "notify: true" not in silent_saves
