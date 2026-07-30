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
            "UI_LANG": "en",
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
            # Mode manuel C29 : scrape → file pending_reviews → review UI (défaut off)
            "MANUAL_REVIEW_MODE": False,
            # Après le pick : récap éditable (on) ou apply direct (off)
            "MANUAL_REVIEW_EDIT": True,
            # Batch auto (MR off) : park preview → édition → confirm avant écriture Kavita
            "CONFIRM_BEFORE_WRITE": False,
            # Sons optionnels (pick / confirm / skip) — défaut off
            "MANUAL_REVIEW_SOUNDS": False,
            # Super Review : tous les scrapers du type (lent) — défaut off
            "MANUAL_REVIEW_SUPER": False,
            # Phase couverture dans la modale MR (pick → cover → edit? → confirm)
            "MANUAL_REVIEW_COVER_PICK": False,
            # Baromètre de fiabilité : seuil d'acceptation des matches (défaut 0.60)
            "MATCH_THRESHOLD_CUSTOM": False,
            "MATCH_ACCEPT_THRESHOLD": 0.60,
            "AUTO_SYNC_INTERVAL": 0,
            # Dénylist d'IDs de bibliothèques Kavita (virgules). Vide = toutes actives.
            "DISABLED_LIBRARIES": "",
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

        # --- FUSION DE L'ENVIRONNEMENT -------------------------------------
        # Précédence : config.json > variable d'environnement > défaut.
        #
        # L'environnement SÈME donc ce que le fichier ne contient pas encore, il
        # ne l'écrase jamais. C'est ce qui permet de préconfigurer une instance
        # neuve depuis docker-compose sans renier la promesse « je le change dans
        # l'interface et ça reste changé » : dès qu'une clé est dans config.json,
        # c'est elle qui fait autorité, y compris contre la variable d'origine.
        #
        # ⚠️ CE BLOC DOIT RESTER AVANT LA GÉNÉRATION DES SECRETS, plus bas, qui
        # écrit config.json au premier démarrage. C'est l'inversion de ces deux
        # étapes qui rendait la TOTALITÉ des variables d'environnement inopérantes :
        # le fichier était écrit avec les défauts avant que l'environnement soit
        # lu, donc au démarrage suivant chaque clé existait déjà dans le fichier
        # et le repli `os.getenv` n'était plus jamais atteint. `UI_LANG`,
        # `KAVITA_URL`, `KAVITA_API_KEY`, `PROVIDER_1`, `MAX_TAGS`… étaient tous
        # ignorés en silence, y compris au tout premier démarrage — le seul moment
        # où ils avaient une chance de servir.

        # `ADMIN_PASSWORD` n'est volontairement PAS semé depuis l'environnement.
        # La clé est supprimée (l'accès est protégé par le compte créé au premier
        # démarrage) et n'est plus lue que pour la migration des installations qui
        # la contiennent encore, où elle sert de preuve de propriété sur l'écran de
        # setup. La semer aurait deux conséquences fâcheuses : réécrire un mot de
        # passe en clair sur le disque d'une installation neuve, et surtout rendre
        # `auth_manager.purge_legacy_admin_password()` inopérant — il vide la clé
        # dans config.json, mais la variable d'environnement la ferait réapparaître
        # au chargement suivant, donc l'écran de setup réclamerait indéfiniment une
        # preuve censée être à usage unique.
        config["ADMIN_PASSWORD"] = file_config.get("ADMIN_PASSWORD", "")
        if os.getenv("ADMIN_PASSWORD") and not config["ADMIN_PASSWORD"]:
            logging.warning(
                "[Config] ADMIN_PASSWORD est défini dans l'environnement mais cette "
                "variable est supprimée : l'accès est protégé par le compte créé au "
                "premier démarrage. Pour préconfigurer ce compte sans passer par "
                "l'écran de configuration, utilisez ADMIN_PASSWORD_HASH "
                "(cf. `python debug/hash_password.py`)."
            )

        for key in [
            "TRANSLATION_PROVIDER", "KAVITA_URL", "KAVITA_EXTERNAL_URL", "KAVITA_API_KEY", "DEEPL_API_KEY", "AZURE_API_KEY", "AZURE_REGION",
            "TARGET_LANG", "UI_LANG", "PUBLISHER_PREFERENCE",
            "LOCALIZED_TITLE_MODE", "LOCALIZED_TITLE_LANGS",
            "DISABLED_LIBRARIES",
            "PROVIDER_1", "PROVIDER_2", "PROVIDER_3",
            "COMIC_PROVIDER_1", "COMIC_PROVIDER_2", "COMIC_PROVIDER_3",
            "BOOK_PROVIDER_1", "BOOK_PROVIDER_2", "BOOK_PROVIDER_3",
        ]:
            config[key] = file_config.get(key, os.getenv(key, config.get(key, "")))

        mode = (config.get("LOCALIZED_TITLE_MODE") or "all").strip().lower()
        config["LOCALIZED_TITLE_MODE"] = mode if mode in ("all", "prefer", "none") else "all"
        config["LOCALIZED_TITLE_LANGS"] = (config.get("LOCALIZED_TITLE_LANGS") or "").strip()
        config["DISABLED_LIBRARIES"] = ",".join(
            sorted(parse_library_id_list(config.get("DISABLED_LIBRARIES")), key=_library_id_sort_key)
        )

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
            "MANUAL_REVIEW_MODE", "MANUAL_REVIEW_EDIT", "MANUAL_REVIEW_SOUNDS",
            "MANUAL_REVIEW_SUPER", "CONFIRM_BEFORE_WRITE", "MANUAL_REVIEW_COVER_PICK",
        ]:
            config[bool_key] = file_config.get(bool_key, str(os.getenv(bool_key, config.get(bool_key, "False"))).lower() == "true")

        config["MATCH_ACCEPT_THRESHOLD"] = _parse_match_threshold(
            file_config.get(
                "MATCH_ACCEPT_THRESHOLD",
                os.getenv("MATCH_ACCEPT_THRESHOLD", config.get("MATCH_ACCEPT_THRESHOLD", 0.60)),
            )
        )

        # --- SECRETS ET PREMIÈRE PERSISTANCE -------------------------------
        # Volontairement en DERNIER : l'écriture qui suit fige config.json, et
        # tout ce qui n'a pas encore été fusionné à cet instant serait figé à sa
        # valeur par défaut pour toujours (cf. l'avertissement plus haut).
        needs_save = False
        if not config_parse_failed:
            if not config.get("SECRET_KEY"):
                config["SECRET_KEY"] = secrets.token_hex(24)
                needs_save = True
            if not config.get("WEBHOOK_TOKEN"):
                config["WEBHOOK_TOKEN"] = secrets.token_urlsafe(16)
                needs_save = True

            if needs_save:
                # Premier démarrage : le fichier créé ici contient donc déjà les
                # valeurs demandées par l'environnement, qui deviennent du même
                # coup visibles et modifiables depuis l'interface web.
                save_config(config)
        else:
            # Secrets éphémères en mémoire seulement — ne pas écraser le fichier corrompu
            if not config.get("SECRET_KEY"):
                config["SECRET_KEY"] = secrets.token_hex(24)
            if not config.get("WEBHOOK_TOKEN"):
                config["WEBHOOK_TOKEN"] = secrets.token_urlsafe(16)

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


def _library_id_sort_key(value: str):
    s = str(value)
    return (0, int(s)) if s.isdigit() else (1, s.lower())


def parse_library_id_list(raw) -> set:
    """Parse une liste d'IDs biblio (virgules / points-virgules / espaces) → set[str]."""
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set)):
        return {str(x).strip() for x in raw if str(x).strip()}
    text = str(raw).strip()
    if not text:
        return set()
    parts = []
    for chunk in text.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return set(parts)


def get_disabled_library_ids(config=None) -> set:
    """IDs de bibliothèques Kavita exclus de la sync / UI (dénylist)."""
    if config is None:
        config = load_config()
    return parse_library_id_list(config.get("DISABLED_LIBRARIES"))


def is_library_enabled(library_id, config=None) -> bool:
    """True si la bibliothèque n'est pas dans DISABLED_LIBRARIES."""
    if library_id is None or library_id == "":
        return True
    disabled = get_disabled_library_ids(config)
    if not disabled:
        return True
    return str(library_id) not in disabled


def filter_enabled_libraries(libraries, config=None) -> list:
    """Conserve uniquement les bibliothèques absentes de la dénylist."""
    if not libraries:
        return []
    disabled = get_disabled_library_ids(config)
    if not disabled:
        return list(libraries)
    return [lib for lib in libraries if str(lib.get("id")) not in disabled]


def format_disabled_libraries(ids) -> str:
    """Sérialise un iterable d'IDs en chaîne config DISABLED_LIBRARIES."""
    cleaned = parse_library_id_list(ids)
    return ",".join(sorted(cleaned, key=_library_id_sort_key))


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

        # Restrict the file to its owner (0600).
        #
        # config.json is the single most sensitive file the application owns: it holds
        # SECRET_KEY (forging a session cookie is game over), WEBHOOK_TOKEN, the Kavita
        # API key, and every translation-provider key. It is created with the process
        # umask, which on a default Docker image means 0644 — world-readable. On a NAS
        # this directory is usually a bind mount that other containers and other users
        # can see, so "readable by anyone on the host" is a realistic exposure, not a
        # theoretical one.
        #
        # Applied on every save rather than only at creation, because a file restored
        # from a backup, copied from another host, or written by an older version will
        # otherwise keep its permissive mode forever.
        #
        # Deliberately best-effort: chmod is a no-op on Windows and fails outright on
        # some CIFS/SMB and FAT-backed bind mounts. Losing the hardening there is
        # acceptable; losing the user's configuration because a chmod raised is not, so
        # this must never be allowed to propagate.
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError as chmod_err:
            logging.debug(
                "[Config] chmod 600 impossible sur %s (%s) — sans conséquence sur la "
                "sauvegarde, mais les permissions du fichier restent celles du système "
                "de fichiers.",
                CONFIG_FILE, chmod_err,
            )