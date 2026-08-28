"""
Interface de l'enrichissement par tome.

La fonctionnalité est éteinte par défaut : tant qu'elle l'est, aucun bouton
d'écriture ne doit apparaître — ni dans la barre d'outils, ni au pied de la
modale de rapport. Et quand elle est allumée, les clés lues par le JavaScript
doivent exister dans les deux langues, sans quoi l'utilisateur lit
« vol_apply_btn » sur un bouton.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "js" / "library_audit.js").read_text(encoding="utf-8")


def _translations():
    from translations import translations

    return translations


# ===== Traductions =====


def test_every_key_the_javascript_reads_exists_in_both_languages():
    """`tr.vol_xxx || 'fallback'` masque une clé absente derrière l'anglais du
    fallback : c'est ainsi que trois clés sont parties en production."""
    used = set(re.findall(r"\btr\.(vol_[a-z0-9_]+)", JS))
    used |= {
        "vol_field_" + f for f in ("title", "summary", "release_date", "isbn", "cover_url")
    }
    used |= {"vol_col_pick", "vol_col_unit", "vol_provider_label", "vol_unmatched"}
    used |= {"vol_reason_" + r for r in ("locked", "filled", "invalid")}

    assert used, "le module devrait lire des clés vol_*"
    for lang in ("fr", "en"):
        missing = sorted(k for k in used if k not in _translations()[lang])
        assert not missing, f"{lang} : clés manquantes {missing}"


def test_the_two_languages_declare_the_same_volume_keys():
    fr = {k for k in _translations()["fr"] if k.startswith(("vol_", "volume_"))}
    en = {k for k in _translations()["en"] if k.startswith(("vol_", "volume_"))}

    assert fr == en, f"écart FR/EN : {sorted(fr ^ en)}"


def test_the_keys_are_injected_into_the_page():
    """Sans l'injection, `window.AppTranslations` ne les porte pas et tous les
    libellés retombent sur leur fallback anglais."""
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "key.startswith('vol_')" in index


@pytest.mark.parametrize(
    "key",
    [
        "vol_library_confirm",
        "vol_preview_none_hint",
        "volume_enrichment_enabled_hint",
        "volume_force_overwrite_hint",
        "volume_enrich_credits_hint",
    ],
)
def test_the_explanatory_texts_are_not_placeholders(key):
    for lang in ("fr", "en"):
        text = _translations()[lang][key]
        assert len(text) > 30, f"{lang}/{key} : texte trop court pour expliquer quoi que ce soit"


# ===== Rendu conditionnel =====


def _render(config_extra):
    """Rend le tableau de bord avec la configuration donnée."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    # Les partials appellent `url_for` : hors application Flask, il faut le
    # fournir, sinon Jinja s'arrête sur la première URL statique venue.
    env.globals["url_for"] = lambda endpoint, **kw: "/" + str(endpoint)
    config = {"LIBRARY_INVENTORY_ENABLED": True}
    config.update(config_extra)
    t = _translations()["fr"]
    return {
        "toolbar": env.get_template("partials/_toolbar.html").render(
            t=t, config=config, hygiene_meta=None, hygiene_counts={}, libraries=[]
        ),
        "modal": env.get_template("partials/_library_audit_modal.html").render(
            t=t, config=config
        ),
        "sidebar": env.get_template("partials/_sidebar.html").render(
            t=t, config=config, libraries=[], stats={}, app_version="1.7.0",
            all_scrapers=[], providers={}, scraper_diag={},
            volume_provider_choices=[
                {"id": "COMICVINE", "display_name": "ComicVine", "kind": "index"},
                {"id": "MANGADEX", "display_name": "MangaDex", "kind": "index"},
                {"id": "GOOGLEBOOKS", "display_name": "Google Books", "kind": "unit"},
                {"id": "OPENLIBRARY", "display_name": "Open Library", "kind": "unit"},
            ],
        ),
    }


def test_nothing_shows_when_the_feature_is_off():
    """Rien à l'écran, mais par le CSS et non par le gabarit.

    Les deux surfaces d'écriture sont désormais rendues sans condition et masquées
    sur `data-volumes` — la barre latérale enregistre sans recharger, donc une
    condition de gabarit ne suivrait pas l'interrupteur. Ce qui garantit qu'elles
    n'apparaissent pas, c'est donc la règle CSS et l'attribut du `<body>`, et c'est
    cela qu'on vérifie ici. Le refus côté serveur, lui, ne dépend d'aucune des deux
    (403 tant que la fonctionnalité est éteinte, voir
    `tests/test_volume_enrichment_routes.py`).

    L'attribut du `<body>` est vérifié par
    `test_the_page_says_whether_the_enrichment_is_on`.
    """
    css = _css()

    assert 'body:not([data-volumes="1"]) #btnVolumePreview' in css
    assert (
        'body:not([data-volumes="1"]):not([data-volume-pass="running"]) .toolbar-group--volumes'
        in css
    ), "sans cette règle, décocher l'interrupteur laisse le cartouche à l'écran"


def test_the_buttons_show_when_the_feature_is_on():
    rendered = _render({"VOLUME_ENRICHMENT_ENABLED": True})

    assert 'id="btnVolumeEnrich"' in rendered["toolbar"]
    assert 'id="btnVolumeEnrichCancel"' in rendered["toolbar"]
    assert 'id="volumeEnrichProgress"' in rendered["toolbar"]
    assert 'id="btnVolumePreview"' in rendered["modal"]


# ===== Indépendance vis-à-vis de l'Inventaire =====
#
# Les deux fonctionnalités partageaient une surface d'affichage par accident
# d'implémentation : le rapport de tomes était né côté Inventaire. Décocher
# celui-ci masquait donc toute la passe par tome — boutons, barre de
# progression et bouton de rapport — alors que son propre interrupteur restait
# allumé dans la sidebar.


def _css():
    return (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")


def test_the_volume_controls_do_not_live_inside_the_inventory_panel():
    from bs4 import BeautifulSoup

    toolbar = _render({"VOLUME_ENRICHMENT_ENABLED": True})["toolbar"]
    soup = BeautifulSoup(toolbar, "html.parser")
    inventory = soup.find(id="inventoryPanel")
    volumes = soup.find(id="volumeEnrichPanel")

    assert inventory is not None and volumes is not None
    assert not inventory.find(id="btnVolumeEnrich"), "la passe ne doit pas loger chez l'Inventaire"
    assert not inventory.find(id="volumeEnrichProgress")
    assert volumes.find(id="btnVolumeEnrich") is not None
    assert volumes.find(id="btnVolumeEnrichCancel") is not None
    assert volumes.find(id="volumeEnrichProgress") is not None


def test_switching_the_inventory_off_no_longer_hides_the_volume_group():
    """L'Inventaire s'éteint par une règle CSS sur `.toolbar-group--hygiene` :
    le groupe des tomes ne doit pas porter cette classe."""
    toolbar = _render({"VOLUME_ENRICHMENT_ENABLED": True})["toolbar"]
    panel = toolbar[toolbar.index('id="volumeEnrichPanel"') - 120:]

    assert "toolbar-group--volumes" in panel
    assert 'body[data-inventory="0"] .toolbar-group--volumes' not in _css()


def test_the_report_button_survives_when_the_enrichment_is_on():
    """C'est l'unique chemin vers l'aperçu tome par tome : masqué avec
    l'Inventaire, la fonctionnalité devenait injoignable."""
    css = _css()

    assert 'body[data-inventory="0"]:not([data-volumes="1"]) .btn-audit-report' in css
    assert 'body[data-inventory="0"] .btn-audit-report' not in css


def test_the_page_says_whether_the_enrichment_is_on():
    """Sans cet attribut, la règle CSS ci-dessus ne peut rien distinguer."""
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "data-volumes=" in index
    assert "VOLUME_ENRICHMENT_ENABLED" in index


def test_the_report_modal_falls_back_to_the_kavita_only_detail():
    """Sans Inventaire, l'attendu de catalogue et les exports répondent 403 :
    la modale ne doit demander que le détail, sinon elle s'ouvre sur une erreur."""
    assert "_inventoryOff" in JS
    assert "_loadVolumeReportUnits" in JS


def test_the_force_switch_only_shows_alongside_the_feature():
    """Un interrupteur qui ne commande rien est un piège à clics.

    La condition a changé de camp : elle était portée par un `{% if %}` côté
    serveur, elle l'est maintenant par le CSS. La raison est que la barre latérale
    enregistre sans recharger la page — allumer l'enrichissement par tome ne
    révélait donc ce réglage qu'au chargement suivant, ce qui se lit comme un
    interrupteur qui ne fait rien.
    """
    on = _render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"]

    assert "sidebar_volume_force_overwrite" in on
    assert "so-needs-volumes" in on
    assert (
        ".scraping-options-body:not(:has(#sidebar_volume_enrichment:checked)) .so-needs-volumes"
        in _css()
    ), "sans cette règle, le réglage sensible s'afficherait sans son maître"


def test_the_cross_category_rule_is_anchored_above_the_categories():
    """`.so-anim-inner` habille aussi chaque panneau de catégorie. Ancrer la règle
    dessus la ferait s'appliquer au panneau « Écriture », qui ne contient pas le
    maître : le réglage serait masqué quoi qu'on coche. L'ancre doit englober les
    deux catégories."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"], "html.parser")
    anchor = soup.select_one(".scraping-options-body")

    assert anchor is not None
    assert anchor.select_one("#sidebar_volume_enrichment") is not None
    assert anchor.select_one(".so-needs-volumes") is not None
    assert ".so-anim-inner:not(:has(#sidebar_volume_enrichment" not in _css()


def test_turning_the_feature_on_shows_its_toolbar_group_without_a_reload():
    """`data-volumes` commande le groupe « Tomes » de la barre d'outils. Posé par
    le seul gabarit, il ne suivait pas l'interrupteur : la fonctionnalité
    s'allumait sans que ses boutons apparaissent. Même correctif que l'Inventaire."""
    on = _render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"]

    assert "onVolumeEnrichmentToggle(this)" in on
    assert "function onVolumeEnrichmentToggle" in JS
    assert "data-volumes" in JS
    # L'assertion qui manquait, et par laquelle le défaut est passé : les trois
    # ci-dessus étaient vertes alors que rien, dans le CSS, ne lisait l'attribut
    # que le JavaScript prenait soin de poser.
    assert ".toolbar-group--volumes" in _css()
    assert 'body:not([data-volumes="1"])' in _css()


def test_the_toolbar_group_is_not_gated_by_the_template():
    """Une condition de gabarit ne se réévalue qu'au chargement suivant, alors que
    la barre latérale enregistre sans recharger : gardé sous condition, le groupe
    n'était pas dans la page, et cocher l'interrupteur ne pouvait pas le faire
    apparaître. C'est le CSS qui masque, comme pour `#inventoryPanel`."""
    off = _render({"VOLUME_ENRICHMENT_ENABLED": False})["toolbar"]

    assert 'id="volumeEnrichPanel"' in off
    assert 'id="btnVolumeEnrich"' in off
    assert 'id="btnVolumeEnrichCancel"' in off
    assert 'id="btnVolumePreview"' in _render({"VOLUME_ENRICHMENT_ENABLED": False})["modal"]


def test_a_running_pass_keeps_its_cancel_button_on_screen():
    """Décocher l'interrupteur n'arrête pas une passe déjà partie — il ne commande
    que le départ, et la tâche de fond continue d'écrire. Masquer le groupe la
    laisserait tourner sans plus rien pour l'arrêter, puisque Annuler vit dedans."""
    assert ':not([data-volume-pass="running"]) .toolbar-group--volumes' in _css()
    assert "data-volume-pass" in JS, "le JavaScript doit poser l'attribut pendant la passe"
    assert "removeAttribute('data-volume-pass')" in JS, "et le retirer à la fin"


def test_the_dependent_settings_are_greyed_out_without_their_master():
    """Crédits, repli manga et fournisseur imposé ne commandent rien tant que
    l'enrichissement par tome est éteint : le bloc est grisé et inerte, et il dit
    pourquoi dans une note qui ne s'affiche que dans cet état."""
    css = _css()
    on = _render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"]

    assert "so-sub--volumes" in on
    assert "so-sub-note" in on
    assert ".so-cat-panel:not(:has(#sidebar_volume_enrichment:checked)) .so-sub--volumes" in css
    assert "pointer-events: none" in css
    # Le bloc grisé et l'interrupteur décoché portent chacun une opacité : sur des
    # éléments imbriqués elles se multiplient, et le libellé passe sous 0.3.
    assert (
        ".so-cat-panel:not(:has(#sidebar_volume_enrichment:checked)) "
        ".so-sub--volumes .so-switch:not(:has(input:checked))"
    ) in css, "sans cette règle, les libellés du bloc inerte sont illisibles"


def test_the_providers_button_stays_out_of_the_dependent_block():
    """La cascade Fournisseurs sert aussi l'enrichissement par série : ce bouton
    doit rester cliquable quand l'enrichissement par tome est éteint, donc hors
    d'un bloc que le CSS rend inerte (`pointer-events: none`)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"], "html.parser")
    block = soup.select_one(".so-sub--volumes")

    assert block is not None, "le bloc dépendant devrait exister"
    assert block.select_one("#sidebar_volume_enrich_credits") is not None
    assert block.select_one(".so-btn-providers") is None, (
        "le bouton Fournisseurs deviendrait inerte avec le bloc"
    )
    assert soup.select_one(".so-cat-panel .so-btn-providers") is not None


def test_every_sidebar_switch_family_carries_its_colour():
    """Les autres catégories colorent leurs interrupteurs ; les tomes et
    l'inventaire étaient les seuls à ne rien porter, ce qui les faisait lire comme
    des réglages secondaires."""
    css = _css()
    on = _render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"]

    for variant in ("so-switch--volumes", "so-switch--lab", "so-switch--inventory"):
        assert variant in on, f"{variant} absent du gabarit"
        assert f".{variant} input:checked + .so-switch-track" in css, (
            f"{variant} n'a pas de couleur d'état actif"
        )


def test_the_help_modal_covers_the_volumes_category():
    """Le texte long vit dans la modale d'aide, comme pour les autres catégories.
    `scraping_help_volume_enrichment` existait dans les deux langues mais n'était
    lue par aucun gabarit : la section n'avait jamais été écrite, et les indices
    de la barre latérale avaient grossi pour compenser."""
    help_modal = (
        ROOT / "templates" / "partials" / "_scraping_options_help_modal.html"
    ).read_text(encoding="utf-8")

    for key in (
        "scraping_help_volume_enrichment",
        "scraping_help_volume_credits",
        "scraping_help_volume_no_manga_fallback",
        "scraping_help_volume_provider",
        "scraping_help_volume_experimental",
        "scraping_help_volume_force_overwrite",
    ):
        assert key in help_modal, f"{key} n'est lue par aucun gabarit"
        for lang in ("fr", "en"):
            assert len(_translations()[lang][key]) > 80, f"{lang}/{key} : trop court"


def test_no_help_text_is_left_orphaned():
    """Une clé d'aide que nul gabarit ne lit est un texte écrit pour personne."""
    templates = "\n".join(
        p.read_text(encoding="utf-8") for p in (ROOT / "templates").rglob("*.html")
    )
    declared = {k for k in _translations()["fr"] if k.startswith("scraping_help_")}
    orphans = sorted(k for k in declared if k not in templates)

    assert not orphans, f"clés d'aide jamais affichées : {orphans}"


def test_the_help_modal_has_one_section_per_sidebar_category():
    """L'Inventaire avait sa catégorie dans la barre latérale mais se retrouvait
    rangé sous « Écriture » dans l'aide, et les tomes n'y étaient nulle part."""
    help_modal = (
        ROOT / "templates" / "partials" / "_scraping_options_help_modal.html"
    ).read_text(encoding="utf-8")
    sidebar = _render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"]

    for key in ("scraping_cat_match", "scraping_cat_mapping", "scraping_cat_manual", "scraping_cat_write",
                "scraping_cat_inventory", "scraping_cat_volumes"):
        assert f"t.{key}" in help_modal, f"aucune section d'aide pour {key}"
        assert _translations()["fr"][key] in sidebar


def test_the_sidebar_hints_stay_short_enough_to_scan():
    """Sept indices de quatre lignes dans une colonne étroite se lisent comme un
    mur de texte, et l'interrupteur qu'ils expliquent s'y perd."""
    for lang in ("fr", "en"):
        for key in (
            "volume_enrichment_enabled_hint",
            "volume_enrich_credits_hint",
            "volume_enrich_experimental_hint",
            "volume_no_manga_fallback_hint",
            "volume_provider_forced_hint",
            "volume_provider_order_hint",
        ):
            text = _translations()[lang][key]
            assert len(text) <= 130, f"{lang}/{key} : {len(text)} caractères, à déplacer dans l'aide"


def test_the_hint_paragraphs_are_actually_styled():
    """`so-hint` existait dans le gabarit sans une seule règle CSS : sept
    paragraphes s'affichaient à la taille du texte courant, pesant plus lourd que
    les interrupteurs qu'ils expliquent."""
    css = _css()

    assert ".so-hint {" in css
    assert "so-hint" in _render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"]


def test_the_provider_controls_sit_with_the_other_harmless_settings():
    """Visibles même fonctionnalité éteinte, comme les crédits et l'expérimental.

    Seul le bloc rouge — l'écrasement — est conditionné, parce que lui seul peut
    détruire du travail fait à la main. Régler ses fournisseurs avant d'allumer la
    fonctionnalité est au contraire l'ordre naturel.
    """
    off = _render({"VOLUME_ENRICHMENT_ENABLED": False})["sidebar"]

    assert "sidebar_volume_provider" in off
    assert "sidebar_volume_no_manga_fallback" in off


def test_the_forced_provider_list_is_filled_by_the_page():
    """Le gabarit tolère la variable absente pour ne pas rendre une page en 500 ;
    c'est donc ici que le câblage se vérifie, sinon la liste serait vide sans que
    rien ne le signale."""
    pages = (ROOT / "routes" / "pages.py").read_text(encoding="utf-8")

    assert "volume_provider_choices=volume_provider_choices" in pages
    assert "list_volume_provider_choices()" in pages


def test_the_forced_provider_list_separates_the_two_families():
    """Un fournisseur par ISBN et un fournisseur d'index ne rendent pas la même
    chose : le premier ne connaît que les tomes qui portent un ISBN dans Kavita.
    Les mêler dans une liste plate ferait choisir Open Library pour une
    bibliothèque de comics scannés, où il ne rendra jamais rien."""
    on = _render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"]
    t = _translations()["fr"]

    assert f'<optgroup label="{t["volume_provider_group_index"]}">' in on
    assert f'<optgroup label="{t["volume_provider_group_unit"]}">' in on
    assert 'value="GOOGLEBOOKS"' in on, "les fournisseurs par ISBN doivent être proposables"
    assert 'value="OPENLIBRARY"' in on


def test_an_empty_family_shows_no_empty_group():
    """Un `<optgroup>` sans option affiche un intitulé grisé sous lequel il n'y a
    rien à choisir."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    env.globals["url_for"] = lambda endpoint, **kw: "/" + str(endpoint)
    sidebar = env.get_template("partials/_sidebar.html").render(
        t=_translations()["fr"],
        config={"VOLUME_ENRICHMENT_ENABLED": True, "LIBRARY_INVENTORY_ENABLED": True},
        libraries=[], stats={}, app_version="1.7.0",
        all_scrapers=[], providers={}, scraper_diag={},
        volume_provider_choices=[
            {"id": "GOOGLEBOOKS", "display_name": "Google Books", "kind": "unit"},
        ],
    )

    assert _translations()["fr"]["volume_provider_group_index"] not in sidebar
    assert 'value="GOOGLEBOOKS"' in sidebar


def test_the_forced_provider_list_offers_the_cascade_as_default():
    """Sans une entrée « laisser la cascade décider », le réglage serait à sens
    unique : on pourrait imposer un fournisseur, jamais revenir en arrière."""
    on = _render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"]

    assert 'value="AUTO"' in on
    assert _translations()["fr"]["volume_provider_auto"] in on


def test_the_master_switch_is_always_reachable():
    """Il faut bien pouvoir allumer la fonctionnalité : ce commutateur-là ne
    dépend pas de lui-même."""
    off = _render({"VOLUME_ENRICHMENT_ENABLED": False})["sidebar"]

    assert "sidebar_volume_enrichment" in off
    assert "sidebar_volume_enrich_credits" in off


# ===== Câblage =====


# ===== Portée de la passe =====
#
# Le bouton de la barre d'outils écrivait dans toutes les séries de la
# bibliothèque affichée : des heures d'écriture et des milliers de tomes pour un
# clic, sans moyen de restreindre. Il porte maintenant sur les séries cochées, la
# même sélection que le lot de scraping, avec la même case « Tout sélectionner »
# pour couvrir une bibliothèque entière.


def test_the_pass_only_takes_the_series_you_ticked():
    start = JS[JS.index("function startVolumeEnrich"):JS.index("function cancelVolumeEnrich")]

    assert "getFilteredSelectedIds" in start, "la sélection du lot est la seule source"
    assert "series_ids: ids" in start
    assert "JSON.stringify({})" not in start, "une requête vide vaut toute la bibliothèque"


def test_an_empty_selection_starts_nothing():
    """Sans cette garde, un clic sans sélection repartait sur la bibliothèque
    entière — exactement ce que la portée par sélection vient supprimer."""
    start = JS[JS.index("function startVolumeEnrich"):JS.index("function cancelVolumeEnrich")]
    guard = start[: start.index("window.confirm")]

    assert "if (!ids.length)" in guard
    assert "return" in guard
    assert "batch_empty" in guard, "même message que le bouton de lot dans ce cas"


def test_the_confirmation_says_how_many_series_are_taken():
    """« toute la bibliothèque » n'était plus vrai, et un nombre est la seule
    chose qui permette de rattraper une sélection involontaire avant l'écriture."""
    start = JS[JS.index("function startVolumeEnrich"):JS.index("function cancelVolumeEnrich")]

    assert "replace('{0}', ids.length)" in start
    for lang in ("fr", "en"):
        confirm = _translations()[lang]["vol_library_confirm"]
        title = _translations()[lang]["vol_library_title"]
        assert "{0}" in confirm, f"{lang} : la confirmation ne dit pas le nombre"
        assert "librar" in title.lower() or "biblioth" in title.lower(), (
            f"{lang} : l'infobulle doit dire comment couvrir une bibliothèque entière"
        )


def test_the_backend_honours_an_explicit_selection():
    """La route lisait déjà `series_ids` : c'est le front qui n'en envoyait pas.
    Et une série nommée explicitement échappe au filtre de reprise — sans quoi
    cocher une série déjà traitée ne ferait rien du tout, ce qui se lit comme un
    bouton cassé."""
    routes = (ROOT / "routes" / "volume_enrichment.py").read_text(encoding="utf-8")
    job = (ROOT / "services" / "volume_enrichment" / "job.py").read_text(encoding="utf-8")

    assert 'payload.get("series_ids")' in routes
    assert "resume and not series_ids" in job


def test_the_switches_are_sent_by_save_config():
    """Un interrupteur affiché mais jamais transmis se remet à zéro au rechargement."""
    config_js = (ROOT / "static" / "js" / "config.js").read_text(encoding="utf-8")

    for key in (
        "VOLUME_ENRICHMENT_ENABLED",
        "VOLUME_FORCE_OVERWRITE",
        "VOLUME_ENRICH_CREDITS",
        "VOLUME_ENRICH_EXPERIMENTAL",
        "VOLUME_NO_MANGA_FALLBACK",
        # Une liste, pas une case : c'est sa valeur qui part, pas un booléen.
        "VOLUME_PROVIDER",
    ):
        assert key in config_js


def test_the_switches_are_read_back_by_the_config_route():
    routes = (ROOT / "routes" / "config.py").read_text(encoding="utf-8")

    for key in (
        "VOLUME_ENRICHMENT_ENABLED",
        "VOLUME_FORCE_OVERWRITE",
        "VOLUME_ENRICH_CREDITS",
        "VOLUME_ENRICH_EXPERIMENTAL",
        "VOLUME_NO_MANGA_FALLBACK",
        "VOLUME_PROVIDER",
    ):
        assert key in routes


def test_an_empty_preview_says_which_kind_of_empty_it_is():
    """Trois vides, trois causes, et un seul message jusqu'ici.

    « Aucun fournisseur ne connaît cette série » s'affichait aussi quand le
    fournisseur connaissait parfaitement la série mais que pas un de ses numéros
    d'albums ne recoupait ceux de Kavita — le cas constaté sur « Gaston Lagaffe »,
    dont l'Inventaire obtient pourtant 23 tomes attendus via ComicVine. Le message
    envoyait alors vérifier une clé d'API qui fonctionnait très bien.
    """
    assert "vol_preview_unmatched" in JS
    assert "counts" in JS and "matched" in JS
    # Le fournisseur est nommé dans le message : « ComicVine connaît la série,
    # mais… » se lit, « un fournisseur connaît la série » ne se vérifie pas.
    assert "{0}" in _translations()["fr"]["vol_preview_unmatched_hint"]
    assert "{0}" in _translations()["en"]["vol_preview_unmatched_hint"]


def test_the_proposed_cover_is_shown_not_described():
    """L'aperçu affichait « 🖼 » : on demandait à l'utilisateur de valider une
    couverture sans la lui montrer, alors que c'est le champ où l'erreur se voit
    d'un coup d'œil — et le seul que MangaDex apporte aux mangas."""
    assert "_volCoverCell" in JS
    assert "toDisplayCoverUrl" in JS, "hotlink refusé par MangaDex et ComicVine"
    assert ".vol-cover-thumb" in (ROOT / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )


def test_the_row_label_shows_the_number_the_match_was_made_on():
    """Un run de comics vit sous le volume 1 : afficher le tome donnerait
    cinquante lignes intitulées « 1 »."""
    assert "matched_on" in JS
    assert "matched_on" in (ROOT / "services" / "volume_enrichment" / "plan.py").read_text(
        encoding="utf-8"
    )


def test_the_preview_uses_the_states_it_asks_the_database_for():
    """`plan["states"]` coûte une lecture en base à chaque aperçu. Calculé et
    jamais lu, c'était une dépense pour rien ; lu, il dit à l'utilisateur quelles
    unités la passe précédente n'a pas réussi à écrire."""
    assert "plan.states" in JS or "states[" in JS, "les états doivent servir ou disparaître"
    assert "'FAILED'" in JS or '"FAILED"' in JS
    assert "vol_state_failed_hint" in JS


def test_a_refused_cover_is_said_and_not_only_logged():
    """Le compte de réussites seul laisserait croire que tout est passé.

    L'avertissement arrive désormais avec la progression, l'écriture étant passée
    en tâche de fond : c'est `payload.errors` qu'il faut lire, plus la réponse
    HTTP, qui ne rend que le démarrage."""
    assert "vol_apply_warning" in JS
    assert "payload.errors" in JS
    for lang in ("fr", "en"):
        assert "{0}" in _translations()[lang].get("vol_apply_warning", "")


# ===== Écriture d'une série en tâche de fond =====
#
# Le bouton « Écrire les tomes cochés » tenait la requête ouverte pendant toute
# l'écriture : « Écriture en cours… » figé, aucune progression, rien pour
# arrêter, et une modale fermée par lassitude ne disait plus jamais ce qu'il
# était advenu. La route rend maintenant un démarrage, et c'est la progression
# Socket.IO qui conclut.


def test_le_bouton_d_une_serie_ne_lit_plus_le_verdict_dans_la_reponse():
    """Une réponse qui ne porte plus le résultat ne doit plus être lue comme
    telle : `data.counts` était le verdict de l'écriture synchrone."""
    apply_block = JS[JS.index("function applyVolumeEnrich"):JS.index("function _setVolumeEnrichRunningUi")]

    assert "started" in apply_block or "success" in apply_block
    assert "data.counts" not in apply_block
    assert "vol_apply_started" in apply_block


def test_la_progression_distingue_une_serie_d_une_bibliotheque():
    """Une passe de bibliothèque compte des séries, l'écriture d'une série compte
    des tomes : le même libellé pour les deux mentirait sur l'un des deux."""
    progress = JS[JS.index("function _onVolumeEnrichProgress"):]

    assert "payload.series_id" in progress
    assert "vol_apply_progress" in progress
    assert "vol_library_running" in progress


def test_le_bouton_de_la_modale_suit_l_etat_de_la_tache():
    """Deux boutons commandent la même tâche de fond : l'un ne peut pas rester
    cliquable pendant que l'autre tourne, et l'aperçu rouvert pendant une
    écriture ne doit pas proposer un clic voué au 409."""
    assert "volApplyBtn" in JS
    assert "_volumeEnrichRunning" in JS


def test_l_annulation_vaut_pour_les_deux_portees():
    """Le bouton Annuler de la barre d'outils passe par la route commune : une
    écriture de série lancée depuis la modale doit s'arrêter avec lui."""
    assert "/api/volume-enrich/cancel" in JS


def test_the_experimental_switch_is_reachable_and_explained():
    """Une recherche sans identifiant doit s'annoncer comme telle."""
    sidebar = (ROOT / "templates" / "partials" / "_sidebar.html").read_text(encoding="utf-8")

    assert "sidebar_volume_enrich_experimental" in sidebar
    for lang in ("fr", "en"):
        hint = _translations()[lang].get("volume_enrich_experimental_hint", "")
        assert len(hint) > 80, f"{lang} : l'explication doit dire le risque"


def test_the_progress_event_is_wired_to_the_socket():
    """Sans l'écouteur, la barre resterait à zéro pendant toute la passe."""
    websocket = (ROOT / "static" / "js" / "websocket.js").read_text(encoding="utf-8")

    assert "volume_enrich_progress" in websocket
    assert "_onVolumeEnrichProgress" in websocket
    assert "window._onVolumeEnrichProgress" in JS


def test_every_api_call_goes_through_the_root_path():
    """MetaKavita derrière un proxy en sous-chemin : une URL absolue répond 404
    (c'est BF117, qui avait mis tout l'inventaire hors service)."""
    volume_calls = [
        line for line in JS.splitlines() if "fetch(" in line and "volume-enrich" in line
    ]

    assert volume_calls, "le module devrait appeler les routes d'enrichissement"
    for call in volume_calls:
        assert "getRootPath()" in call, f"URL sans getRootPath() : {call.strip()}"


def test_the_library_pass_asks_for_confirmation():
    """Une écriture sur des milliers de tomes ne part pas sur un clic distrait."""
    assert "window.confirm" in JS
    assert "vol_library_confirm" in JS


# ===== L'étiquette « expérimental » =====
#
# Ces deux fonctionnalités sont jeunes : l'Inventaire déduit un attendu de
# catalogues qui se contredisent, et la passe par tome écrit dans Kavita à partir
# de ce qu'un fournisseur veut bien lister. Le dire à un seul endroit ne prévient
# que ceux qui y passent — d'où la même étiquette dans les trois surfaces où ces
# fonctionnalités sont nommées.


def _help_modal():
    return (ROOT / "templates" / "partials" / "_scraping_options_help_modal.html").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("titre", ["scraping_cat_inventory", "scraping_cat_volumes"])
def test_les_deux_sections_de_la_sidebar_sont_marquees_experimentales(titre):
    from bs4 import BeautifulSoup

    sidebar = _render({"VOLUME_ENRICHMENT_ENABLED": True})["sidebar"]
    t = _translations()["fr"]
    soup = BeautifulSoup(sidebar, "html.parser")

    resume = next(
        (s for s in soup.select("summary.so-cat-summary") if t[titre] in s.get_text()),
        None,
    )
    assert resume is not None, f"la catégorie {titre} devrait exister"
    tag = resume.select_one(".lab-tag")
    assert tag is not None, f"{titre} devrait porter l'étiquette expérimentale"
    assert t["badge_experimental"] in tag.get_text()


@pytest.mark.parametrize("panneau", ["inventoryPanel", "volumeEnrichPanel"])
def test_les_deux_groupes_de_la_barre_d_outils_sont_marques_experimentaux(panneau):
    from bs4 import BeautifulSoup

    toolbar = _render({"VOLUME_ENRICHMENT_ENABLED": True})["toolbar"]
    soup = BeautifulSoup(toolbar, "html.parser")

    groupe = soup.find(id=panneau)
    assert groupe is not None
    tag = groupe.select_one(".lab-tag")
    assert tag is not None, f"{panneau} devrait porter l'étiquette expérimentale"
    assert _translations()["fr"]["badge_experimental"] in tag.get_text()


def test_l_aide_porte_la_meme_etiquette_sur_les_memes_sections():
    """L'aide est lue par ceux qui hésitent : c'est là que l'avertissement compte
    le plus, et c'est la surface qu'on oublie."""
    from bs4 import BeautifulSoup

    t = _translations()["fr"]
    # Le gabarit est lu tel quel : les titres y sont des clés, ce qui suffit à
    # dire quelles sections portent l'étiquette.
    soup = BeautifulSoup(_help_modal(), "html.parser")
    marquees = [
        h.get_text()
        for h in soup.select("h4.scraping-help-section-title")
        if h.select_one(".lab-tag")
    ]

    assert len(marquees) == 3, f"trois sections attendues, trouvé {marquees}"
    for cle in ("scraping_cat_mapping", "scraping_cat_inventory", "scraping_cat_volumes"):
        assert any(cle in titre for titre in marquees), f"{cle} sans étiquette"
    assert t["badge_experimental"] and t["badge_experimental_hint"]


def test_la_modale_de_rapport_porte_l_etiquette():
    """C'est la fenêtre depuis laquelle l'écriture part : l'avertissement doit y
    être, pas seulement dans les réglages qu'on traverse une fois."""
    from bs4 import BeautifulSoup

    modal = _render({"VOLUME_ENRICHMENT_ENABLED": True})["modal"]
    soup = BeautifulSoup(modal, "html.parser")
    titre = soup.find(id="volumeReportTitle")

    assert titre is not None
    assert titre.select_one(".lab-tag") is not None


def test_l_etiquette_existe_dans_les_deux_langues_et_explique_le_risque():
    for lang in ("fr", "en"):
        t = _translations()[lang]
        assert t["badge_experimental"], f"{lang} : libellé manquant"
        assert len(t["badge_experimental_hint"]) > 40, f"{lang} : l'infobulle doit dire pourquoi"


def test_l_etiquette_reprend_l_ambre_de_l_interrupteur_experimental():
    """Ni le vert des fonctions établies, ni le rouge de ce qui détruit : la même
    teinte que `so-switch--lab`, faute de quoi le code couleur ne veut plus rien
    dire."""
    css = _css()
    bloc = css[css.index(".lab-tag {"):]
    bloc = bloc[: bloc.index("}")]

    assert "var(--warning)" in bloc
