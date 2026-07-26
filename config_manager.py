# Dans config_manager.py

import json
import logging
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
            # Plafond de tags poussés vers Kavita (env MAX_TAGS). Défaut 15. Pas d'UI.
            "MAX_TAGS": 15,
            # Plafond de genres (env MAX_GENRES). Défaut 5. Pas d'UI.
            "MAX_GENRES": 5,
            "DEEPL_API_KEY": "",
            "AZURE_API_KEY": "",
            "AZURE_REGION": "",
            "TARGET_LANG": "FR",
            "UI_LANG": "fr",
            "PUBLISHER_PREFERENCE": "LOCALIZED",
            # Titres localizedName : all (défaut multi) | prefer | none
            "LOCALIZED_TITLE_MODE": "all",
            "LOCALIZED_TITLE_LANGS": "",
            "PROVIDER_1": "MANGABAKA",
            "PROVIDER_2": "KITSU",
            "PROVIDER_3": "ANILIST",
            "COMIC_PROVIDER_1": "COMICVINE",
            "COMIC_PROVIDER_2": "ANILIST",
            "COMIC_PROVIDER_3": "NONE",
            "BOOK_PROVIDER_1": "GOOGLEBOOKS",
            "BOOK_PROVIDER_2": "OPENLIBRARY",
            "BOOK_PROVIDER_3": "NONE",
            "SMART_COMPLETION": False,
            # Comparaison des providers par score (meilleur match gagne) + exécution en
            # deux vagues. Si False : fallback classique (1er provider utile de la liste).
            "SMART_SCORING": True,
            # Baromètre de fiabilité : seuil d'acceptation des matches (défaut 0.60)
            "MATCH_THRESHOLD_CUSTOM": False,
            "MATCH_ACCEPT_THRESHOLD": 0.60,
            "AUTO_SYNC_INTERVAL": 0,
            "AUTO_COVER": False,
            "AUTO_READING_DIR": False,
            "TITLE_FALLBACK_TRANSLATION": False, # <-- NOUVEAU
            "RESET_CONTEXT_ON_FORCE": False,
            # C7 — stats ludiques sur /stats (ON par défaut, désactivable)
            "ENABLE_PLAYFUL_STATS": True,
            "ADMIN_PASSWORD": "",
            "SECRET_KEY": "",
            "WEBHOOK_TOKEN": ""
        }

        file_config = {}
        config_parse_failed = False
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                    config.update(file_config)
            except json.JSONDecodeError as e:
                config_parse_failed = True
                logging.error(
                    "[Config] config.json illisible (%s) — conservation du fichier corrompu ; "
                    "defaults en mémoire uniquement (pas d'écrasement automatique).",
                    e,
                )
                try:
                    bak = CONFIG_FILE + ".bak"
                    if os.path.exists(CONFIG_FILE):
                        # Ne remplace un .bak existant que s'il n'y en a pas encore
                        # pour cette session : on garde une copie du JSON cassé.
                        if not os.path.exists(bak):
                            os.replace(CONFIG_FILE, bak)
                            logging.error("[Config] Copie de sauvegarde écrite : %s", bak)
                except OSError as bak_err:
                    logging.error("[Config] Impossible de sauvegarder config.json.bak : %s", bak_err)

        needs_save = False
        if not config_parse_failed:
            if not config.get("SECRET_KEY"):
                config["SECRET_KEY"] = secrets.token_hex(24)
                needs_save = True
            if not config.get("WEBHOOK_TOKEN"):
                config["WEBHOOK_TOKEN"] = secrets.token_urlsafe(16)
                needs_save = True

            if needs_save:
                save_config(config)
        else:
            # Secrets éphémères en mémoire seulement — ne pas écraser le fichier corrompu
            if not config.get("SECRET_KEY"):
                config["SECRET_KEY"] = secrets.token_hex(24)
            if not config.get("WEBHOOK_TOKEN"):
                config["WEBHOOK_TOKEN"] = secrets.token_urlsafe(16)

        config["ADMIN_PASSWORD"] = file_config.get("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", config.get("ADMIN_PASSWORD", "")))

        for key in [
            "TRANSLATION_PROVIDER", "KAVITA_URL", "KAVITA_EXTERNAL_URL", "KAVITA_API_KEY", "DEEPL_API_KEY", "AZURE_API_KEY", "AZURE_REGION",
            "TARGET_LANG", "UI_LANG", "PUBLISHER_PREFERENCE",
            "LOCALIZED_TITLE_MODE", "LOCALIZED_TITLE_LANGS",
            "PROVIDER_1", "PROVIDER_2", "PROVIDER_3",
            "COMIC_PROVIDER_1", "COMIC_PROVIDER_2", "COMIC_PROVIDER_3",
            "BOOK_PROVIDER_1", "BOOK_PROVIDER_2", "BOOK_PROVIDER_3",
        ]:
            config[key] = file_config.get(key, os.getenv(key, config.get(key, "")))

        mode = (config.get("LOCALIZED_TITLE_MODE") or "all").strip().lower()
        config["LOCALIZED_TITLE_MODE"] = mode if mode in ("all", "prefer", "none") else "all"
        config["LOCALIZED_TITLE_LANGS"] = (config.get("LOCALIZED_TITLE_LANGS") or "").strip()

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

        config["MAX_TAGS"] = _parse_positive_int(
            file_config.get("MAX_TAGS", os.getenv("MAX_TAGS", config.get("MAX_TAGS", 15))),
            default=15,
            minimum=1,
            maximum=100,
        )

        config["MAX_GENRES"] = _parse_positive_int(
            file_config.get("MAX_GENRES", os.getenv("MAX_GENRES", config.get("MAX_GENRES", 5))),
            default=5,
            minimum=1,
            maximum=50,
        )

        for bool_key in [
            "AUTO_COVER", "AUTO_READING_DIR", "SMART_COMPLETION", "SMART_SCORING",
            "TITLE_FALLBACK_TRANSLATION", "RESET_CONTEXT_ON_FORCE", "ENABLE_PLAYFUL_STATS",
            "MATCH_THRESHOLD_CUSTOM",
        ]:
            config[bool_key] = file_config.get(bool_key, str(os.getenv(bool_key, config.get(bool_key, "False"))).lower() == "true")

        config["MATCH_ACCEPT_THRESHOLD"] = _parse_match_threshold(
            file_config.get(
                "MATCH_ACCEPT_THRESHOLD",
                os.getenv("MATCH_ACCEPT_THRESHOLD", config.get("MATCH_ACCEPT_THRESHOLD", 0.60)),
            )
        )

        return config


def _parse_match_threshold(raw, default=0.60, minimum=0.30, maximum=1.00) -> float:
    """Seuil d'acceptation des matches, borné [0.30, 1.00]."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return max(minimum, min(maximum, value))


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


def get_max_tags(config=None) -> int:
    """Nombre max de tags poussés vers Kavita.

    Configurable via env / config.json `MAX_TAGS` (défaut 15, min 1, max 100).
    Pas d'exposition UI (réglage avancé / power-user).
    """
    if config is None:
        config = load_config()
    return _parse_positive_int(config.get("MAX_TAGS", 15), default=15, minimum=1, maximum=100)


def get_max_genres(config=None) -> int:
    """Nombre max de genres poussés vers Kavita.

    Configurable via env / config.json `MAX_GENRES` (défaut 5, min 1, max 50).
    Pas d'exposition UI (réglage avancé / power-user).
    """
    if config is None:
        config = load_config()
    return _parse_positive_int(config.get("MAX_GENRES", 5), default=5, minimum=1, maximum=50)


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


def get_kavita_plus_url(config=None) -> str:
    """Lien navigateur vers la page admin Kavita+ de *cette* instance.

    `{ui}/settings#admin-kavitaplus` via `get_kavita_ui_url()`.
    Si aucune URL UI n'est configurée, repli sur le wiki officiel Kavita+.
    """
    ui = get_kavita_ui_url(config)
    if ui:
        return f"{ui}/settings#admin-kavitaplus"
    return "https://wiki.kavitareader.com/kavita+/"


def save_config(data):
    with CONFIG_LOCK:
        if "MATCH_ACCEPT_THRESHOLD" in data:
            data["MATCH_ACCEPT_THRESHOLD"] = _parse_match_threshold(
                data.get("MATCH_ACCEPT_THRESHOLD")
            )
        if "MATCH_THRESHOLD_CUSTOM" in data:
            data["MATCH_THRESHOLD_CUSTOM"] = bool(data.get("MATCH_THRESHOLD_CUSTOM"))
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)