"""`AUTO_READING_DIR` — option retirée, et qui doit le rester.

L'option promettait d'imposer le sens de lecture (droite-à-gauche pour les
mangas) aux séries écrites dans Kavita. Elle n'a jamais rien écrit : côté
Kavita le sens de lecture est `AppUserPreferences.ReadingDirection`, une
préférence par utilisateur, et aucun endpoint ne permet de l'imposer série par
série. `UpdateSeriesDto` n'a d'ailleurs jamais porté `Format` / `FormatLocked`
(vérifié de la 0.4.2 à `develop`) : la clé était ignorée en silence, Kavita
répondait 200 et rien n'était enregistré.

Deux garanties sont vérifiées ici :

1. l'option ne réapparaît nulle part dans le code de production — case,
   valeur par défaut, lecture de formulaire, envoi JavaScript ou libellé ;
2. une installation existante, dont le `config.json` contient encore la clé,
   continue de démarrer normalement.
"""
import json
import os

import pytest
from flask import Flask

import auth_manager
from routes.auth import auth_bp
from translations import translations

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Jetons interdits : la clé de configuration et le préfixe de ses libellés
# (`auto_reading_dir`, `scraping_help_auto_reading_dir`, l'id DOM
# `sidebar_auto_reading_dir`).
_TOKENS = ("AUTO_READING_DIR", "auto_reading_dir")

_SCANNED_SUFFIXES = (".py", ".js", ".html")

# `tests/` porte encore la clé dans des configurations factices d'autres
# domaines (elle y est inerte) ; `debug/` et `data/` ne sont pas du code livré ;
# CHANGELOG / ROADMAP en gardent la trace historique, c'est leur rôle.
_SKIPPED_DIRS = frozenset({
    ".git", ".bf140_backup", ".pytest_cache", ".ruff_cache", "__pycache__",
    "data", "debug", "logs", "node_modules", "tests", "venv", ".venv",
})


def _production_sources():
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIPPED_DIRS]
        for name in filenames:
            if name.endswith(_SCANNED_SUFFIXES):
                yield os.path.join(dirpath, name)


def test_aucune_source_de_production_ne_mentionne_encore_l_option():
    coupables = []
    scannes = 0
    for path in _production_sources():
        scannes += 1
        with open(path, encoding="utf-8", errors="replace") as fh:
            contenu = fh.read()
        for token in _TOKENS:
            if token in contenu:
                coupables.append(f"{os.path.relpath(path, _ROOT)} ({token})")

    # Un parcours qui ne trouve plus rien à lire serait vert sans rien garantir.
    assert scannes > 100, f"seulement {scannes} fichiers parcourus : le parcours est cassé"

    assert coupables == [], (
        "L'option de sens de lecture est réapparue : "
        + ", ".join(sorted(coupables))
        + ". Kavita ne permet pas d'imposer un sens de lecture à une série "
        "(c'est une préférence par utilisateur) : remettre l'option, c'est "
        "remettre une promesse que le produit ne peut pas tenir."
    )


@pytest.mark.parametrize("langue", ("fr", "en"))
def test_les_libelles_de_l_option_ne_survivent_dans_aucune_langue(langue):
    """Une clé que plus aucun gabarit ne lit est du bruit à traduire à vie."""
    assert "auto_reading_dir" not in translations[langue]
    assert "scraping_help_auto_reading_dir" not in translations[langue]


def test_les_deux_dictionnaires_restent_a_parite():
    assert set(translations["fr"]) == set(translations["en"])


# ---------------------------------------------------------------------------
# Compatibilité des installations existantes
# ---------------------------------------------------------------------------

@pytest.fixture
def config_herite(tmp_path, monkeypatch):
    """`config.json` d'une installation qui avait coché l'option."""
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    (tmp_path / "config.json").write_text(
        json.dumps({
            "AUTO_READING_DIR": True,
            "KAVITA_URL": "http://kavita.test",
            "KAVITA_API_KEY": "clef",
            "AUTO_COVER": True,
            "UI_LANG": "fr",
            "SECRET_KEY": "secret-de-test",
            "WEBHOOK_TOKEN": "jeton-de-test",
        }),
        encoding="utf-8",
    )
    return config_manager


def test_une_config_portant_encore_la_cle_se_charge_sans_broncher(config_herite):
    """Le chargement recopie le fichier tel quel (`config.update(file_config)`) :
    une clé inconnue est reconduite en mémoire, sans validation ni erreur, et
    plus personne ne la lit. Aucune migration n'est donc nécessaire — la clé
    reste sur le disque comme un résidu inerte, y compris après une sauvegarde."""
    config = config_herite.load_config()

    assert config["KAVITA_URL"] == "http://kavita.test"
    assert config["AUTO_COVER"] is True
    assert config["AUTO_READING_DIR"] is True, (
        "la clé inconnue doit être reconduite sans provoquer d'erreur"
    )

    config_herite.save_config(config)
    relu = config_herite.load_config()
    assert relu["KAVITA_URL"] == "http://kavita.test"
    assert relu["AUTO_COVER"] is True


def test_le_wizard_demarre_sur_une_config_heritee_sans_reproposer_l_option(
    config_herite, isolated_db, monkeypatch
):
    """Preuve de bout en bout : l'application rend son assistant d'installation
    au-dessus d'un `config.json` qui contient encore la clé, et la case n'y est
    plus."""
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    auth_manager.reset_lockout_state()

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(auth_bp)

    res = app.test_client().get("/setup")

    assert res.status_code == 200
    html = res.data.decode("utf-8", errors="replace")
    assert "setupForm" in html
    assert "AUTO_READING_DIR" not in html
