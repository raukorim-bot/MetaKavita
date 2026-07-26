# Dans config_manager.py

import json
import os
import secrets
import threading

DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# --- GARDE ANTI-COURSE (LOST UPDATE) ---
# `load_config()` relit TOUT config.json, un appelant modifie en mémoire quelques
# clés, puis `save_config()` réécrit le fichier ENTIER. Sans verrou, deux
# requêtes concurrentes (ex: deux cases à cocher de la sidebar changées coup sur
# coup, chacune déclenchant son propre POST /save-config indépendant — voir
# static/js/config.js::saveConfig() — ou une régénération de jeton webhook en
# même temps qu'un autre changement) peuvent s'entrelacer : la seconde relit le
# fichier avant que la première ait écrit, puis écrase le fichier entier à
# partir de cet état périmé, faisant disparaître silencieusement le premier
# changement. `CONFIG_LOCK` est un RLock (ré-entrant) : `load_config()` peut
# légitimement appeler `save_config()` en interne (génération de SECRET_KEY/
# WEBHOOK_TOKEN au premier démarrage) sans se bloquer lui-même, et les routes
# HTTP (`routes/config.py`) l'utilisent pour englober tout leur cycle
# lire-modifier-écrire, pas seulement l'écriture finale.
CONFIG_LOCK = threading.RLock()


def load_config():
    with CONFIG_LOCK:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

        config = {
            "TRANSLATION_PROVIDER": "GOOGLE",
            "KAVITA_URL": "",
            # URL publique pour les liens UI (navigateur). Si vide → repli sur KAVITA_URL.
            # Utile en Docker : KAVITA_URL=http://kavita:5000 (réseau interne) et
            # KAVITA_EXTERNAL_URL=https://kavita.domain.tld (reverse proxy).
            "KAVITA_EXTERNAL_URL": "",
            "KAVITA_API_KEY": "",
            # Timeout HTTP (secondes) pour les écritures Kavita (POST metadata / update / cover).
            # Env Docker : KAVITA_HTTP_TIMEOUT=90 pour HDD / gros force-update. Défaut 60.
            "KAVITA_HTTP_TIMEOUT": 60,
            "DEEPL_API_KEY": "",
            "AZURE_API_KEY": "",
            "AZURE_REGION": "",
            "TARGET_LANG": "FR",
            "UI_LANG": "fr",
            "PUBLISHER_PREFERENCE": "LOCALIZED",
            "PROVIDER_1": "MANGABAKA",
            "PROVIDER_2": "KITSU",
            "PROVIDER_3": "ANILIST",
            "SMART_COMPLETION": False,
            # Comparaison des providers par score (meilleur match gagne) + exécution en
            # deux vagues. Si False : fallback classique (1er provider utile de la liste).
            "SMART_SCORING": True,
            "AUTO_SYNC_INTERVAL": 0,
            "AUTO_COVER": False,
            "AUTO_READING_DIR": False,
            "TITLE_FALLBACK_TRANSLATION": False, # <-- NOUVEAU
            "ADMIN_PASSWORD": "",
            "SECRET_KEY": "",
            "WEBHOOK_TOKEN": ""
        }

        file_config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                    config.update(file_config)
            except json.JSONDecodeError:
                pass

        needs_save = False
        if not config.get("SECRET_KEY"):
            config["SECRET_KEY"] = secrets.token_hex(24)
            needs_save = True
        if not config.get("WEBHOOK_TOKEN"):
            config["WEBHOOK_TOKEN"] = secrets.token_urlsafe(16)
            needs_save = True

        if needs_save:
            save_config(config)

        config["ADMIN_PASSWORD"] = file_config.get("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", config.get("ADMIN_PASSWORD", "")))

        for key in [
            "TRANSLATION_PROVIDER", "KAVITA_URL", "KAVITA_EXTERNAL_URL", "KAVITA_API_KEY", "DEEPL_API_KEY", "AZURE_API_KEY", "AZURE_REGION",
            "TARGET_LANG", "UI_LANG", "PUBLISHER_PREFERENCE", "PROVIDER_1", "PROVIDER_2", "PROVIDER_3"
        ]:
            config[key] = file_config.get(key, os.getenv(key, config.get(key, "")))

        for env_key, env_val in os.environ.items():
            if env_key.endswith("_API_KEY") and env_key not in config:
                config[env_key] = env_val

        if "AUTO_SYNC_INTERVAL" in file_config:
            config["AUTO_SYNC_INTERVAL"] = file_config["AUTO_SYNC_INTERVAL"]
        else:
            try:
                config["AUTO_SYNC_INTERVAL"] = int(os.getenv("AUTO_SYNC_INTERVAL", config.get("AUTO_SYNC_INTERVAL", 0)))
            except ValueError:
                config["AUTO_SYNC_INTERVAL"] = 0

        config["KAVITA_HTTP_TIMEOUT"] = _parse_positive_int(
            file_config.get("KAVITA_HTTP_TIMEOUT", os.getenv("KAVITA_HTTP_TIMEOUT", config.get("KAVITA_HTTP_TIMEOUT", 60))),
            default=60,
            minimum=5,
            maximum=600,
        )

        # --- NOUVEAU : Ajout de la clé dans la boucle des booléens ---
        for bool_key in ["AUTO_COVER", "AUTO_READING_DIR", "SMART_COMPLETION", "SMART_SCORING", "TITLE_FALLBACK_TRANSLATION"]:
            config[bool_key] = file_config.get(bool_key, str(os.getenv(bool_key, config.get(bool_key, "False"))).lower() == "true")

        return config


def _parse_positive_int(raw, default=60, minimum=5, maximum=600) -> int:
    """Parse un entier borné (timeouts HTTP, etc.). Valeurs invalides → default."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < minimum or value > maximum:
        return default
    return value


def get_kavita_http_timeout(config=None) -> int:
    """Timeout (secondes) pour les POST d'écriture vers Kavita.

    Configurable via env / config.json `KAVITA_HTTP_TIMEOUT` (défaut 60, min 5, max 600).
    Les GET de lecture gardent leurs timeouts fixes plus courts.
    """
    if config is None:
        config = load_config()
    return _parse_positive_int(config.get("KAVITA_HTTP_TIMEOUT", 60), default=60)


def get_kavita_ui_url(config=None) -> str:
    """URL Kavita destinée au navigateur (liens série dans l'UI).

    Préfère `KAVITA_EXTERNAL_URL` (URL publique / reverse proxy) ; si absente,
    repli sur `KAVITA_URL` (comportement historique, setups mono-URL).
    Les appels API serveur doivent continuer à utiliser uniquement `KAVITA_URL`.
    """
    if config is None:
        config = load_config()
    external = (config.get("KAVITA_EXTERNAL_URL") or "").strip().rstrip("/")
    if external:
        return external
    return (config.get("KAVITA_URL") or "").strip().rstrip("/")


def save_config(data):
    with CONFIG_LOCK:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)