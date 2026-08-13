"""
Deux régressions frontend faciles à réintroduire, vérifiées sur les sources :

1. i18n — le JS lit `window.AppTranslations.<clé>` avec une valeur de repli en
   dur. Une clé oubliée dans `templates/index.html` ne casse rien : elle affiche
   simplement le repli, donc de l'anglais dans une UI française (et l'inverse).
   Rien ne le signalait.
2. échappement HTML — quatre helpers coexistaient, dont deux n'échappaient pas
   l'apostrophe alors que des attributs sont construits en quotes simples. Ils
   délèguent désormais tous à `escapeHtmlText` (utils.js).
"""
import os
import re

from translations import translations

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# Clés lues par le JS et injectées à la main dans index.html. Le bloc `audit_*`
# est injecté en boucle, il n'a pas besoin d'être listé ici.
_KEYS_READ_BY_JS = [
    "options",
    "processing",
    "mr_kbd_act_cover_continue",
    "mr_kbd_act_cover_skip",
    "companion_wait_timeout",
    "action_ok",
    "action_fail",
    "seal_locks_fail",
    "cover_release_fail",
    # Bandeau de collecte et compteur « sous le seuil » : traduits dans les deux
    # langues mais jamais injectés, donc toujours rendus par leur repli — et les
    # deux replis ne sont même pas écrits dans la même langue.
    "mr_streaming",
    "mr_hidden_below",
]


def test_the_keys_read_by_the_js_exist_in_both_languages():
    for key in _KEYS_READ_BY_JS:
        assert translations["fr"].get(key), f"clé française manquante : {key}"
        assert translations["en"].get(key), f"clé anglaise manquante : {key}"


def test_the_dashboard_injects_every_key_the_js_reads():
    index = _read("templates/index.html")
    for key in _KEYS_READ_BY_JS:
        assert re.search(rf"^\s*{key}:", index, re.M), (
            f"'{key}' est lue par le JS mais absente de window.AppTranslations : "
            "l'UI affichera la valeur de repli, dans la mauvaise langue"
        )


def test_the_diagnostics_page_translates_its_cover_count():
    """`${result.covers.count} cover(s)` était le seul libellé du fichier écrit en
    dur : « 3 cover(s) » au milieu d'une interface française."""
    diag = _read("static/js/diagnostics.js")

    assert not re.search(r"\$\{[^}]*covers\.count[^}]*\}\s*cover\(s\)", diag), (
        "libellé de couverture toujours écrit en dur"
    )
    for lang in ("fr", "en"):
        assert translations[lang].get("diag_covers_count"), f"clé manquante en {lang}"


def test_the_diagnostics_page_injects_every_key_its_js_reads():
    """`diagnostics.js` a son propre dictionnaire, `window.DIAG_I18N`, monté clé
    par clé par son gabarit. Une clé absente du gabarit ne lève rien : `t()` rend
    son repli, écrit en anglais dans un fichier par ailleurs traduit — passer un
    libellé par `t()` sans l'injecter ne le traduit donc pas."""
    keys = set(re.findall(r"\bt\(\s*\"([a-z0-9_]+)\"", _read("static/js/diagnostics.js")))
    template = _read("templates/diagnostics.html")

    assert keys, "aucune clé lue : le motif de recherche a dû changer"
    for key in sorted(keys):
        assert f"'{key}':" in template, (
            f"diagnostics.js lit DIAG_I18N.{key}, que le gabarit n'injecte pas : "
            "le repli en dur restera affiché"
        )


def test_the_shared_escape_helper_covers_the_single_quote():
    utils = _read("static/js/utils.js")
    body = utils.split("function escapeHtmlText")[1].split("}")[0]
    for needle in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert needle in body, f"escapeHtmlText n'échappe pas {needle}"


def test_no_module_reimplements_its_own_escaping():
    """Un helper local est autorisé, mais il doit déléguer à utils.js."""
    for rel in (
        "static/js/library_audit.js",
        "static/js/manual_review.js",
        "static/js/scraper_hub.js",
        "static/js/series_list.js",
    ):
        src = _read(rel)
        assert "escapeHtmlText" in src, f"{rel} n'utilise pas l'échappement partagé"
        assert "&quot;" not in src, (
            f"{rel} réimplémente un échappement local : les divergences "
            "(apostrophe oubliée) sont exactement ce qu'on veut éviter"
        )


def test_the_row_buttons_do_not_hardcode_their_result_label():
    """Un libellé littéral reste toléré en valeur de repli (`T.action_ok || '…'`),
    jamais en affectation directe : c'est celle-ci qui trahissait la langue."""
    batch = _read("static/js/batch.js")

    literals = re.findall(r"innerText\s*=\s*[\"'](?:✅|❌)[^\"']*[\"']", batch)

    assert literals == [], f"libellés en dur assignés directement : {literals}"
    assert "action_fail" in batch and "action_ok" in batch
