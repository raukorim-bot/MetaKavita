"""
Mode léger : retirer de la barre latérale ce dont on ne se sert pas (C80).

Trois catégories peuvent quitter les options : la relecture manuelle,
l'Inventaire et l'enrichissement par tome. La règle qui tient tout le reste est
que **masquée veut dire éteinte**. Ce n'est pas une commodité : deux des trois
écrivent dans Kavita, et une fonctionnalité dont les réglages ne sont plus à
l'écran ne se commande plus. Laisser la relecture manuelle allumée sans sa
catégorie remplirait une file que rien ne viderait ; laisser la passe par tome
allumée laisserait son bouton d'écriture dans la barre d'outils sans le réglage
de fournisseur qui décide de ce qu'il écrit.

L'invariant est donc vérifié à trois endroits, parce qu'il peut se perdre à
trois endroits : à la lecture de la configuration (un `config.json` retouché à
la main, une variable d'environnement), à l'enregistrement (un formulaire
partiel) et à l'écran (l'interrupteur de la barre latérale doit se décocher sous
les yeux de l'utilisateur, non au rechargement suivant).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
CONFIG_JS = (ROOT / "static" / "js" / "config.js").read_text(encoding="utf-8")

SECTIONS = ("manual", "inventory", "volumes")
SHOW_KEYS = ("UI_SHOW_MANUAL_REVIEW", "UI_SHOW_INVENTORY", "UI_SHOW_VOLUMES")


def _css():
    return (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")


def _translations():
    from translations import translations

    return translations


# ===== L'invariant : masquée veut dire éteinte =====


@pytest.mark.parametrize(
    "show_key, feature_keys",
    [
        (
            "UI_SHOW_MANUAL_REVIEW",
            ("MANUAL_REVIEW_MODE", "MANUAL_REVIEW_SUPER", "MANUAL_REVIEW_COVER_PICK",
             "MANUAL_REVIEW_SOUNDS"),
        ),
        ("UI_SHOW_INVENTORY", ("LIBRARY_INVENTORY_ENABLED",)),
        ("UI_SHOW_VOLUMES", ("VOLUME_ENRICHMENT_ENABLED",)),
    ],
)
def test_hiding_a_section_switches_its_feature_off(show_key, feature_keys):
    from config_manager import apply_light_mode

    config = {key: True for key in feature_keys}
    config[show_key] = False

    apply_light_mode(config)

    assert all(config[key] is False for key in feature_keys)


def test_showing_a_section_changes_nothing():
    """Réafficher ne rallume pas, et n'éteint pas non plus : c'est l'utilisateur
    qui décide, avec l'interrupteur qui vient de réapparaître."""
    from config_manager import apply_light_mode

    config = {
        "UI_SHOW_MANUAL_REVIEW": True,
        "UI_SHOW_INVENTORY": True,
        "UI_SHOW_VOLUMES": True,
        "MANUAL_REVIEW_MODE": True,
        "LIBRARY_INVENTORY_ENABLED": True,
        "VOLUME_ENRICHMENT_ENABLED": False,
    }

    apply_light_mode(config)

    assert config["MANUAL_REVIEW_MODE"] is True
    assert config["LIBRARY_INVENTORY_ENABLED"] is True
    assert config["VOLUME_ENRICHMENT_ENABLED"] is False


def test_an_absent_key_counts_as_shown():
    """Une configuration d'avant cette version ne porte aucune des trois clés :
    elle ne doit rien perdre au passage."""
    from config_manager import apply_light_mode

    config = {"MANUAL_REVIEW_MODE": True, "LIBRARY_INVENTORY_ENABLED": True}

    apply_light_mode(config)

    assert config["MANUAL_REVIEW_MODE"] is True
    assert config["LIBRARY_INVENTORY_ENABLED"] is True


# ===== La lecture de la configuration =====


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    for key in SHOW_KEYS + ("MANUAL_REVIEW_MODE", "LIBRARY_INVENTORY_ENABLED",
                            "VOLUME_ENRICHMENT_ENABLED", "UI_LANG"):
        monkeypatch.delenv(key, raising=False)
    return config_manager


def test_the_three_sections_show_by_default(isolated_config):
    """Une mise à jour ne doit rien retirer à personne."""
    config = isolated_config.load_config()

    assert all(config[key] is True for key in SHOW_KEYS)


def test_a_hand_edited_config_cannot_leave_a_feature_running_out_of_reach(isolated_config):
    """Le cas qu'il faut absolument fermer : masquée et allumée à la fois, donc
    active sans aucun interrupteur sous la main pour l'arrêter."""
    with open(isolated_config.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "SECRET_KEY": "s", "WEBHOOK_TOKEN": "w",
            "UI_SHOW_MANUAL_REVIEW": False, "MANUAL_REVIEW_MODE": True,
            "UI_SHOW_VOLUMES": False, "VOLUME_ENRICHMENT_ENABLED": True,
        }, f)

    config = isolated_config.load_config()

    assert config["MANUAL_REVIEW_MODE"] is False
    assert config["VOLUME_ENRICHMENT_ENABLED"] is False


def test_the_environment_can_ask_for_a_light_interface(isolated_config, monkeypatch):
    """Même chemin que les autres booléens : utile pour un déploiement qui ne
    veut proposer ni Inventaire ni tomes à ses utilisateurs."""
    monkeypatch.setenv("UI_SHOW_INVENTORY", "false")

    config = isolated_config.load_config()

    assert config["UI_SHOW_INVENTORY"] is False
    assert config["LIBRARY_INVENTORY_ENABLED"] is False


# ===== L'enregistrement =====


@pytest.fixture
def config_client(tmp_path, monkeypatch, isolated_db):
    import config_manager
    from routes.config import config_bp

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    for key in ("KAVITA_URL", "KAVITA_API_KEY", "UI_LANG"):
        monkeypatch.delenv(key, raising=False)
    config_manager.save_config({
        "SECRET_KEY": "test-secret", "WEBHOOK_TOKEN": "wh",
        "KAVITA_URL": "", "KAVITA_API_KEY": "", "UI_LANG": "fr",
        "MANUAL_REVIEW_MODE": True, "LIBRARY_INVENTORY_ENABLED": True,
        "VOLUME_ENRICHMENT_ENABLED": True,
    })

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(config_bp)
    return app.test_client(), config_manager


def _saved(config_manager):
    with open(config_manager.CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def test_saving_a_hidden_section_writes_its_feature_off(config_client):
    client, cm = config_client

    res = client.post("/save-config", data={
        "UI_SHOW_VOLUMES": "false",
        # Envoyé comme le fait la page : le JavaScript décoche l'interrupteur de
        # la barre latérale avant d'enregistrer. L'invariant serveur est vérifié
        # par le test suivant, sur un formulaire qui prétend le contraire.
        "VOLUME_ENRICHMENT_ENABLED": "false",
    })

    assert res.status_code == 200
    saved = _saved(cm)
    assert saved["UI_SHOW_VOLUMES"] is False
    assert saved["VOLUME_ENRICHMENT_ENABLED"] is False


def test_a_form_that_hides_and_enables_at_once_is_settled_by_the_server(config_client):
    """Un formulaire peut être incohérent — onglet resté ouvert, script tiers,
    appel à la main. C'est le serveur qui tranche, pas le dernier champ lu."""
    client, cm = config_client

    res = client.post("/save-config", data={
        "UI_SHOW_INVENTORY": "false",
        "LIBRARY_INVENTORY_ENABLED": "true",
    })

    assert res.status_code == 200
    assert _saved(cm)["LIBRARY_INVENTORY_ENABLED"] is False


def test_a_partial_form_hides_nothing(config_client):
    """La barre latérale enregistre par bloc : un formulaire sans les trois cases
    ne doit pas masquer les trois sections."""
    client, cm = config_client

    res = client.post("/save-config", data={"AUTO_COVER": "true"})

    assert res.status_code == 200
    saved = _saved(cm)
    assert all(saved[key] is True for key in SHOW_KEYS)


def test_hiding_the_manual_review_empties_its_queue(config_client, mocker):
    """La file est purgée quand le mode s'éteint — c'était déjà le cas depuis la
    barre latérale, et masquer la section passe par le même chemin. Sans cela,
    des séries resteraient gelées en attente d'une relecture devenue injoignable.
    """
    client, cm = config_client
    purge = mocker.patch("services.manual_review.purge_all_reviews",
                         return_value={"deleted": 3})

    res = client.post("/save-config", data={
        "UI_SHOW_MANUAL_REVIEW": "false",
        "MANUAL_REVIEW_MODE": "true",
    })

    assert res.status_code == 200
    assert _saved(cm)["MANUAL_REVIEW_MODE"] is False
    purge.assert_called_once()


# ===== L'écran =====


def _render(config_extra=None):
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    env.globals["url_for"] = lambda endpoint, **kw: "/" + str(endpoint)
    config = {"LIBRARY_INVENTORY_ENABLED": True}
    config.update(config_extra or {})
    t = _translations()["fr"]
    return {
        "config_modal": env.get_template("partials/_config_modal.html").render(
            t=t, config=config, scrapers_with_keys=[], scraper_has_api_key={},
            all_libraries=[], disabled_library_ids=[], request={"script_root": ""},
        ),
        "sidebar": env.get_template("partials/_sidebar.html").render(
            t=t, config=config, libraries=[], stats={}, app_version="1.7.0",
            all_scrapers=[], providers={}, scraper_diag={}, volume_provider_choices=[],
        ),
    }


@pytest.mark.parametrize("section, key", list(zip(SECTIONS, SHOW_KEYS)))
def test_the_config_modal_offers_the_three_switches(section, key):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_render()["config_modal"], "html.parser")
    box = soup.find("input", id=f"config_ui_show_{'manual_review' if section == 'manual' else section}")

    assert box is not None, f"la case de la section {section} devrait exister"
    assert box.get("onchange") == f"onUiSectionToggle(this, '{section}')"
    assert box.has_attr("checked"), "affichée par défaut"


def test_the_switches_reflect_a_hidden_section():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_render({"UI_SHOW_INVENTORY": False})["config_modal"], "html.parser")

    assert not soup.find("input", id="config_ui_show_inventory").has_attr("checked")
    assert soup.find("input", id="config_ui_show_volumes").has_attr("checked")


@pytest.mark.parametrize("section", SECTIONS)
def test_the_css_hides_a_category_the_sidebar_really_names(section):
    """La règle CSS visait `[data-so-cat="…"]` : si la barre latérale renommait
    une catégorie, le réglage ne masquerait plus rien, sans une erreur nulle
    part."""
    assert f'body[data-ui-hidden~="{section}"] .so-cat[data-so-cat="{section}"]' in _css()
    assert f'data-so-cat="{section}"' in _render()["sidebar"]


def test_the_page_says_which_sections_are_hidden():
    """Sans cet attribut sur le `<body>`, les règles CSS ci-dessus ne peuvent
    rien distinguer."""
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "data-ui-hidden=" in index
    for key in SHOW_KEYS:
        assert key in index


def test_hiding_a_section_switches_its_feature_off_on_screen_too():
    """Le serveur applique l'invariant, mais l'utilisateur doit le voir : sinon
    il découvre au rechargement suivant que sa relecture manuelle s'est arrêtée.
    """
    assert "function onUiSectionToggle" in CONFIG_JS
    assert "function turnUiSectionFeatureOff" in CONFIG_JS
    for element_id in ("sidebar_manual_review_mode", "sidebar_library_inventory",
                       "sidebar_volume_enrichment"):
        assert element_id in CONFIG_JS
    # Les attributs des deux fonctionnalités qui ont une surface dans la barre
    # d'outils : sans eux, le cartouche resterait jusqu'au rechargement.
    assert "setAttribute('data-inventory', '0')" in CONFIG_JS
    assert "setAttribute('data-volumes', '0')" in CONFIG_JS


def test_the_three_keys_leave_with_every_save():
    """Elles ne dépendent pas de la soumission de la modale : une bascule de la
    barre latérale enregistre aussi, et ne doit pas les perdre."""
    for key in SHOW_KEYS:
        assert key in CONFIG_JS


def test_showing_a_section_back_does_not_switch_its_feature_on():
    """`turnUiSectionFeatureOff` n'est appelée que dans un sens."""
    import re

    body = CONFIG_JS[CONFIG_JS.index("function onUiSectionToggle"):]
    body = body[:body.index("\n}")]

    assert re.search(r"if \(!show\) turnUiSectionFeatureOff", body)


# ===== Les textes =====


@pytest.mark.parametrize(
    "key",
    ["ui_light_title", "ui_light_desc", "ui_show_manual_review",
     "ui_show_manual_review_desc", "ui_show_inventory", "ui_show_inventory_desc",
     "ui_show_volumes", "ui_show_volumes_desc"],
)
def test_the_labels_exist_in_both_languages(key):
    for lang in ("fr", "en"):
        assert key in _translations()[lang], f"{lang} : clé {key} absente"


@pytest.mark.parametrize(
    "key",
    ["ui_light_desc", "ui_show_manual_review_desc", "ui_show_inventory_desc",
     "ui_show_volumes_desc"],
)
def test_each_description_says_what_hiding_costs(key):
    """Un réglage d'affichage qui éteint une fonctionnalité doit l'annoncer :
    c'est la seule raison pour laquelle ces textes existent."""
    for lang in ("fr", "en"):
        text = _translations()[lang][key]
        assert len(text) > 60, f"{lang}/{key} : trop court pour expliquer la conséquence"
