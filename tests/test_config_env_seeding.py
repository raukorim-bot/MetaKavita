"""
Non-régression : les variables d'environnement doivent réellement s'appliquer.

Elles étaient toutes ignorées en silence — `UI_LANG`, `KAVITA_URL`,
`KAVITA_API_KEY`, `PROVIDER_1`, `MAX_TAGS`… — parce que `load_config()` écrivait
`config.json` (pour y persister `SECRET_KEY` / `WEBHOOK_TOKEN`) AVANT de lire
l'environnement. Le fichier naissait donc rempli de valeurs par défaut, et à
partir du chargement suivant `file_config.get(key, os.getenv(key, ...))` trouvait
chaque clé dans le fichier : le repli `os.getenv` n'était plus jamais atteint.

Conséquence pratique : aucun moyen de préconfigurer une instance, alors que le
premier démarrage est précisément le moment où l'interface n'est pas encore
joignable (écran de création de compte, sélecteur de langue derrière le login).

La précédence retenue est `config.json` > environnement > défaut : l'environnement
sème ce que le fichier ne contient pas encore, sans jamais écraser un réglage
choisi dans l'interface.
"""
import json

import pytest


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    """`config_manager` redirigé vers un dossier jetable, environnement nettoyé.

    Le nettoyage n'est pas cosmétique : ces tests portent sur la lecture de
    `os.environ`, donc une variable présente sur la machine qui lance la suite
    changerait leur résultat.
    """
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_manager, "_admin_password_env_warned", False)
    for key in (
        "UI_LANG", "TARGET_LANG", "KAVITA_URL", "KAVITA_API_KEY",
        "PROVIDER_1", "MAX_TAGS", "MAX_GENRES", "SMART_COMPLETION",
        "ADMIN_PASSWORD", "AUTO_SYNC_INTERVAL",
    ):
        monkeypatch.delenv(key, raising=False)
    return config_manager


def _saved_file(config_manager):
    with open(config_manager.CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# L'environnement sème une installation neuve
# ---------------------------------------------------------------------------

def test_environment_seeds_a_fresh_install(config_env, monkeypatch):
    monkeypatch.setenv("UI_LANG", "fr")
    monkeypatch.setenv("KAVITA_URL", "http://kavita.example:5000")
    monkeypatch.setenv("PROVIDER_1", "ANILIST")
    monkeypatch.setenv("MAX_TAGS", "42")
    monkeypatch.setenv("SMART_COMPLETION", "true")

    config = config_env.load_config()

    assert config["UI_LANG"] == "fr"
    assert config["KAVITA_URL"] == "http://kavita.example:5000"
    assert config["PROVIDER_1"] == "ANILIST"
    assert config["MAX_TAGS"] == 42
    assert config["SMART_COMPLETION"] is True


def test_seeded_values_are_written_to_the_file(config_env, monkeypatch):
    """La cause racine, testée directement : le fichier créé au premier démarrage
    doit contenir ce que l'environnement a demandé, pas les valeurs par défaut.

    C'est aussi ce qui rend ces réglages visibles et modifiables dans l'interface
    web, qui n'affiche que le contenu de `config.json`.
    """
    monkeypatch.setenv("UI_LANG", "fr")
    monkeypatch.setenv("MAX_TAGS", "42")

    config_env.load_config()

    saved = _saved_file(config_env)
    assert saved["UI_LANG"] == "fr"
    assert saved["MAX_TAGS"] == 42


def test_the_variable_still_applies_on_the_second_read(config_env, monkeypatch):
    """La régression exacte rapportée : la première lecture retournait bien la
    valeur de l'environnement, mais toutes les suivantes retombaient sur le
    fichier figé — et `app.py` appelle `load_config()` à l'import, donc c'est la
    deuxième lecture qui sert la première requête."""
    monkeypatch.setenv("UI_LANG", "fr")
    monkeypatch.setenv("PROVIDER_1", "ANILIST")

    first = config_env.load_config()
    second = config_env.load_config()

    assert first["UI_LANG"] == second["UI_LANG"] == "fr"
    assert first["PROVIDER_1"] == second["PROVIDER_1"] == "ANILIST"


def test_a_key_absent_from_an_existing_file_is_still_seeded(config_env, monkeypatch):
    """Une clé introduite par une nouvelle version n'est pas dans le `config.json`
    des installations existantes : l'environnement doit encore pouvoir la semer."""
    config_env.save_config({"SECRET_KEY": "k", "WEBHOOK_TOKEN": "w"})
    monkeypatch.setenv("MAX_TAGS", "42")

    assert config_env.load_config()["MAX_TAGS"] == 42


# ---------------------------------------------------------------------------
# …mais n'écrase jamais un réglage déjà choisi
# ---------------------------------------------------------------------------

def test_the_file_wins_over_the_environment(config_env, monkeypatch):
    """Sinon quelqu'un qui a posé `UI_LANG=en` dans compose il y a un an, puis
    choisi le français dans l'interface, repasserait en anglais au redémarrage."""
    monkeypatch.setenv("UI_LANG", "en")
    config_env.save_config({"UI_LANG": "fr", "SECRET_KEY": "k", "WEBHOOK_TOKEN": "w"})

    assert config_env.load_config()["UI_LANG"] == "fr"


def test_blank_kavita_url_in_file_still_accepts_env_seed(config_env, monkeypatch):
    """Sauvegarder la langue UI avant de coller Kavita écrit ``KAVITA_URL: ""``
    dans le fichier — sans ce repli, l'env Compose ne pourrait plus sémencer."""
    monkeypatch.setenv("KAVITA_URL", "http://host.docker.internal:5001")
    monkeypatch.setenv("KAVITA_API_KEY", "from-env")
    config_env.save_config({
        "KAVITA_URL": "",
        "KAVITA_API_KEY": "   ",
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
    })

    config = config_env.load_config()
    assert config["KAVITA_URL"] == "http://host.docker.internal:5001"
    assert config["KAVITA_API_KEY"] == "from-env"


def test_non_blank_kavita_url_in_file_still_wins(config_env, monkeypatch):
    monkeypatch.setenv("KAVITA_URL", "http://from-env:5000")
    config_env.save_config({
        "KAVITA_URL": "http://from-ui:5000",
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
    })

    assert config_env.load_config()["KAVITA_URL"] == "http://from-ui:5000"


def test_a_ui_change_survives_a_restart_with_the_variable_still_set(config_env, monkeypatch):
    """Le parcours complet : semé par l'environnement, puis changé dans l'UI, le
    changement doit tenir alors que la variable est toujours là."""
    monkeypatch.setenv("UI_LANG", "fr")

    config = config_env.load_config()
    assert config["UI_LANG"] == "fr"

    config["UI_LANG"] = "en"
    config_env.save_config(config)

    assert config_env.load_config()["UI_LANG"] == "en"


# ---------------------------------------------------------------------------
# ADMIN_PASSWORD : clé supprimée, volontairement non semée
# ---------------------------------------------------------------------------

def test_admin_password_is_not_seeded_from_the_environment(config_env, caplog, monkeypatch):
    """La semer réécrirait un mot de passe en clair sur le disque d'une
    installation neuve, et rendrait surtout la purge de l'écran de setup
    inopérante : la variable ferait réapparaître la valeur à chaque lecture, donc
    la preuve de propriété serait réclamée indéfiniment."""
    monkeypatch.setenv("ADMIN_PASSWORD", "hunter2")

    with caplog.at_level("WARNING"):
        config = config_env.load_config()

    assert config["ADMIN_PASSWORD"] == ""
    assert _saved_file(config_env)["ADMIN_PASSWORD"] == ""
    assert "ADMIN_PASSWORD_HASH" in caplog.text, (
        "l'utilisateur doit être orienté vers la variable qui fonctionne, sinon "
        "il croit son instance protégée alors qu'elle attend une création de compte"
    )
    assert "hunter2" not in caplog.text
    # Message pédagogique : invite à retirer la variable obsolète de la compose.
    joined = " ".join(caplog.messages).lower()
    assert "obsolete" in joined or "obsolète" in joined
    assert "remove" in joined or "retirez" in joined


def test_admin_password_env_warning_is_once_per_process(config_env, caplog, monkeypatch):
    """BF95 — load_config() est chaud ; un WARNING à chaque appel inondait Live Logs."""
    monkeypatch.setenv("ADMIN_PASSWORD", "hunter2")

    with caplog.at_level("WARNING"):
        config_env.load_config()
        config_env.load_config()
        config_env.load_config()

    warnings = [
        r for r in caplog.records
        if r.levelno >= 30 and "ADMIN_PASSWORD" in r.getMessage()
    ]
    assert len(warnings) == 1


def test_an_admin_password_already_in_the_file_is_preserved(config_env):
    """La migration en dépend : c'est la preuve de propriété exigée par /setup."""
    config_env.save_config({
        "ADMIN_PASSWORD": "legacy-plaintext",
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
    })

    assert config_env.load_config()["ADMIN_PASSWORD"] == "legacy-plaintext"


# ---------------------------------------------------------------------------
# BF64 — TARGET_LANG dérivé de UI_LANG quand absent (file > env > dérivé)
# ---------------------------------------------------------------------------

def test_fresh_seed_derives_target_lang_from_default_ui_lang(config_env):
    """Install neuve sans env : UI_LANG=en → TARGET_LANG=EN (plus de FR silencieux)."""
    config = config_env.load_config()
    assert config["UI_LANG"] == "en"
    assert config["TARGET_LANG"] == "EN"
    saved = _saved_file(config_env)
    assert saved["TARGET_LANG"] == "EN"
    assert saved["UI_LANG"] == "en"


def test_missing_target_lang_derives_from_env_ui_lang_fr(config_env, monkeypatch):
    monkeypatch.setenv("UI_LANG", "fr")
    config = config_env.load_config()
    assert config["UI_LANG"] == "fr"
    assert config["TARGET_LANG"] == "FR"


def test_missing_target_lang_derives_from_file_ui_lang(config_env):
    config_env.save_config({
        "UI_LANG": "fr",
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
    })
    assert config_env.load_config()["TARGET_LANG"] == "FR"


def test_existing_target_lang_in_file_is_preserved(config_env, monkeypatch):
    """Pas de migration : un TARGET_LANG=FR explicite reste FR même avec UI_LANG=en."""
    monkeypatch.setenv("UI_LANG", "en")
    config_env.save_config({
        "UI_LANG": "en",
        "TARGET_LANG": "FR",
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
    })
    assert config_env.load_config()["TARGET_LANG"] == "FR"


def test_env_target_lang_wins_over_ui_lang_derivation(config_env, monkeypatch):
    monkeypatch.setenv("UI_LANG", "en")
    monkeypatch.setenv("TARGET_LANG", "ES")
    config = config_env.load_config()
    assert config["UI_LANG"] == "en"
    assert config["TARGET_LANG"] == "ES"


def test_file_target_lang_wins_over_env(config_env, monkeypatch):
    monkeypatch.setenv("TARGET_LANG", "EN")
    config_env.save_config({
        "TARGET_LANG": "FR",
        "UI_LANG": "fr",
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
    })
    assert config_env.load_config()["TARGET_LANG"] == "FR"


def test_target_lang_from_ui_lang_helper():
    import config_manager as cm
    assert cm.target_lang_from_ui_lang("en") == "EN"
    assert cm.target_lang_from_ui_lang("fr") == "FR"
    assert cm.target_lang_from_ui_lang("ES") == "ES"
    assert cm.target_lang_from_ui_lang("pt-br") == "PT-BR"
    assert cm.target_lang_from_ui_lang("") == "EN"
    assert cm.target_lang_from_ui_lang(None) == "EN"
