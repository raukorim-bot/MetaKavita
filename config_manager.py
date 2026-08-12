# Dans config_manager.py

import json
import logging
import os
import secrets
import tempfile
import threading


def _resolve_data_dir() -> str:
    """Répertoire persistant (absolu) — ne dépend pas du cwd du process.

    Ordre : METAKAVITA_DATA_DIR → DATA_DIR → <repo>/data à côté de ce module.
    En Docker : /app/config_manager.py → /app/data (volume bind habituel).
    """
    env = (os.environ.get("METAKAVITA_DATA_DIR") or os.environ.get("DATA_DIR") or "").strip()
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))


DATA_DIR = _resolve_data_dir()
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

# Warning ADMIN_PASSWORD env : une fois par process (load_config est appelé souvent).
_admin_password_env_warned = False

_logged_config_path = False


def target_lang_from_ui_lang(ui_lang) -> str:
    """Derive metadata ``TARGET_LANG`` from effective ``UI_LANG`` (BF64).

    Mapping: ``en`` → ``EN``, ``fr`` → ``FR``. Any other non-empty UI tag is
    uppercased (e.g. ``es`` → ``ES``, ``pt-br`` → ``PT-BR``). Empty / missing → ``EN``.
    """
    raw = (ui_lang or "").strip()
    if not raw:
        return "EN"
    low = raw.lower()
    if low in ("en", "fr"):
        return low.upper()
    return raw.upper()


def load_config():
    global _logged_config_path
    with CONFIG_LOCK:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)

        config = {
            "TRANSLATION_PROVIDER": "GOOGLE",
            "KAVITA_URL": "",
            # URL publique pour les liens UI (navigateur). Si vide → repli sur KAVITA_URL.
            # Utile en Docker : KAVITA_URL=http://kavita:5000 (réseau interne) et
            # KAVITA_EXTERNAL_URL=https://kavita.domain.tld (reverse proxy).
            "KAVITA_EXTERNAL_URL": "",
            "KAVITA_API_KEY": "",
            # Sous-chemin reverse-proxy (ex. /metakavita). Env ROOT_PATH prime au boot.
            "ROOT_PATH": "",
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
            # Aligned pair for fresh installs (BF64): English UI → English metadata.
            # If TARGET_LANG is absent from file and env, load_config() still derives
            # it from the effective UI_LANG via target_lang_from_ui_lang().
            "TARGET_LANG": "EN",
            "UI_LANG": "en",
            "PUBLISHER_PREFERENCE": "LOCALIZED",
            # Titres localizedName : all (défaut multi) | prefer | none
            "LOCALIZED_TITLE_MODE": "all",
            "LOCALIZED_TITLE_LANGS": "",
            "BOOK_PROVIDER_1": "GOOGLEBOOKS",
            "BOOK_PROVIDER_2": "OPENLIBRARY",
            "BOOK_PROVIDER_3": "BABELIO",
            "COMIC_PROVIDER_1": "COMICVINE",
            "COMIC_PROVIDER_2": "ANILIST",
            "COMIC_PROVIDER_3": "LOCG",
            "PROVIDER_1": "MANGABAKA",
            "PROVIDER_2": "KITSU",
            "PROVIDER_3": "ANILIST",
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
            # Hygiène doublons : seuil (défaut 0.92 ; presets 0.97 / 0.92 / 0.85)
            "DUP_THRESHOLD_CUSTOM": False,
            "DUP_ACCEPT_THRESHOLD": 0.92,
            "AUTO_SYNC_INTERVAL": 0,
            # Dénylist d'IDs exclus du polling auto-sync uniquement (virgules). Vide = auto-sync toutes.
            # Dashboard, batch manuel et webhook ne sont pas filtrés.
            "DISABLED_LIBRARIES": "",
            # Dénylist d'IDs de scrapers désactivés (virgules). Présents sur disque mais
            # exclus du registre « enabled » (Providers, enrichment). Manage peut les réactiver.
            "DISABLED_SCRAPERS": "",
            # Sync scrapers/ (image) → data/scrapers/ for is_core files on boot
            "AUTO_UPDATE_CORE_SCRAPERS": True,
            "AUTO_COVER": False,
            # Écrase les couvertures marquées comme choix manuel (cover_manual en
            # cache) au lieu de les épargner. Échappatoire de masse : un run
            # complet réécrit toutes les couvertures sans clic série par série.
            "COVER_FORCE_OVERWRITE": False,
            "AUTO_READING_DIR": False,
            "TITLE_FALLBACK_TRANSLATION": False, # <-- NOUVEAU
            "RESET_CONTEXT_ON_FORCE": False,
            # C7 — stats ludiques sur /stats (ON par défaut, désactivable)
            "ENABLE_PLAYFUL_STATS": True,
            "ADMIN_PASSWORD": "",
            "SECRET_KEY": "",
            "WEBHOOK_TOKEN": "",
            # C33 Companion: CSV d'origins HTTP(S) supplémentaires pour
            # frame-ancestors sur /companion/embed (chrome/moz-extension: toujours inclus).
            "COMPANION_FRAME_ANCESTORS": "",
            # C66 — Inventaire (manquants / doublons / sans id). Activé par défaut
            # pour ne rien changer aux installations existantes ; décoché, la
            # barre d'outils, les cartouches et les routes disparaissent, et le
            # dashboard économise deux lectures SQLite par rendu.
            "LIBRARY_INVENTORY_ENABLED": True,
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
                from translations import get_ui_translations
                _t = get_ui_translations(
                    ui_lang=os.getenv("UI_LANG") or config.get("UI_LANG")
                )
                logging.error(
                    _t.get(
                        "log_config_unreadable",
                        "[Config] config.json illisible (%s) — conservation du fichier corrompu ; "
                        "defaults en mémoire uniquement (pas d'écrasement automatique).",
                    ),
                    e,
                )
                try:
                    bak = CONFIG_FILE + ".bak"
                    if os.path.exists(CONFIG_FILE):
                        # Ne remplace un .bak existant que s'il n'y en a pas encore
                        # pour cette session : on garde une copie du JSON cassé.
                        if not os.path.exists(bak):
                            os.replace(CONFIG_FILE, bak)
                            logging.error(
                                _t.get("log_config_bak_written", "[Config] Copie de sauvegarde écrite : %s"),
                                bak,
                            )
                except OSError as bak_err:
                    logging.error(
                        _t.get("log_config_bak_failed", "[Config] Impossible de sauvegarder config.json.bak : %s"),
                        bak_err,
                    )

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
        global _admin_password_env_warned
        if (
            os.getenv("ADMIN_PASSWORD")
            and not config["ADMIN_PASSWORD"]
            and not _admin_password_env_warned
        ):
            # Une fois par démarrage : load_config() est appelé à chaque requête ;
            # répéter le WARNING remplissait Live Logs sans aider davantage.
            from translations import get_ui_translations
            _t = get_ui_translations(
                ui_lang=os.getenv("UI_LANG") or config.get("UI_LANG")
            )
            logging.warning(
                _t.get(
                    "log_config_admin_password_env",
                    "[Config] ADMIN_PASSWORD est encore défini dans l'environnement "
                    "(docker-compose / -e) mais cette variable est obsolète et ignorée. "
                    "Retirez-la de votre configuration : l'accès passe par le compte "
                    "créé au premier démarrage. Pour précréer ce compte sans /setup, "
                    "utilisez ADMIN_PASSWORD_HASH (cf. `python debug/hash_password.py`).",
                )
            )
            _admin_password_env_warned = True

        # Clés connexion : "" dans config.json ne doit pas bloquer un seed env
        # (ex. première sauvegarde UI avant de coller l'URL / la clé).
        _env_fallback_if_blank = frozenset({
            "KAVITA_URL", "KAVITA_EXTERNAL_URL", "KAVITA_API_KEY",
        })
        for key in [
            "TRANSLATION_PROVIDER", "KAVITA_URL", "KAVITA_EXTERNAL_URL", "KAVITA_API_KEY", "ROOT_PATH",
            "DEEPL_API_KEY", "AZURE_API_KEY", "AZURE_REGION",
            "TARGET_LANG", "UI_LANG", "PUBLISHER_PREFERENCE",
            "LOCALIZED_TITLE_MODE", "LOCALIZED_TITLE_LANGS",
            "DISABLED_LIBRARIES",
            "DISABLED_SCRAPERS",
            "PROVIDER_1", "PROVIDER_2", "PROVIDER_3",
            "COMIC_PROVIDER_1", "COMIC_PROVIDER_2", "COMIC_PROVIDER_3",
            "BOOK_PROVIDER_1", "BOOK_PROVIDER_2", "BOOK_PROVIDER_3",
        ]:
            file_val = file_config.get(key, None)
            if key in _env_fallback_if_blank and (file_val is None or (isinstance(file_val, str) and not file_val.strip())):
                config[key] = os.getenv(key, config.get(key, ""))
            else:
                config[key] = file_config.get(key, os.getenv(key, config.get(key, "")))

        # BF64 — TARGET_LANG absent from file and env → derive from effective UI_LANG.
        # Precedence stays config.json > env > derived default. An explicit empty
        # string in the file is preserved (do not invent a language). Existing
        # installs that already store TARGET_LANG are never overwritten.
        _target_in_file = "TARGET_LANG" in file_config
        _env_target = os.getenv("TARGET_LANG")
        _target_in_env = (
            _env_target is not None and str(_env_target).strip() != ""
        )
        if not _target_in_file and not _target_in_env:
            config["TARGET_LANG"] = target_lang_from_ui_lang(config.get("UI_LANG"))

        mode = (config.get("LOCALIZED_TITLE_MODE") or "all").strip().lower()
        config["LOCALIZED_TITLE_MODE"] = mode if mode in ("all", "prefer", "none") else "all"
        config["LOCALIZED_TITLE_LANGS"] = (config.get("LOCALIZED_TITLE_LANGS") or "").strip()
        config["DISABLED_LIBRARIES"] = ",".join(
            sorted(parse_library_id_list(config.get("DISABLED_LIBRARIES")), key=_library_id_sort_key)
        )
        config["DISABLED_SCRAPERS"] = format_disabled_scrapers(config.get("DISABLED_SCRAPERS"))

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
            "AUTO_COVER", "COVER_FORCE_OVERWRITE", "AUTO_READING_DIR", "SMART_COMPLETION", "SMART_SCORING",
            "TITLE_FALLBACK_TRANSLATION", "RESET_CONTEXT_ON_FORCE", "ENABLE_PLAYFUL_STATS",
            "MATCH_THRESHOLD_CUSTOM", "DUP_THRESHOLD_CUSTOM", "AUTO_UPDATE_CORE_SCRAPERS",
            "MANUAL_REVIEW_MODE", "MANUAL_REVIEW_EDIT", "MANUAL_REVIEW_SOUNDS",
            "MANUAL_REVIEW_SUPER", "CONFIRM_BEFORE_WRITE", "MANUAL_REVIEW_COVER_PICK",
            "LIBRARY_INVENTORY_ENABLED",
        ]:
            config[bool_key] = _resolve_bool(
                file_config, bool_key, default=bool(config.get(bool_key, False))
            )

        config["MATCH_ACCEPT_THRESHOLD"] = _parse_match_threshold(
            file_config.get(
                "MATCH_ACCEPT_THRESHOLD",
                os.getenv("MATCH_ACCEPT_THRESHOLD", config.get("MATCH_ACCEPT_THRESHOLD", 0.60)),
            )
        )
        config["DUP_ACCEPT_THRESHOLD"] = _parse_match_threshold(
            file_config.get(
                "DUP_ACCEPT_THRESHOLD",
                os.getenv("DUP_ACCEPT_THRESHOLD", config.get("DUP_ACCEPT_THRESHOLD", 0.92)),
            ),
            default=0.92,
            minimum=0.70,
            maximum=1.00,
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

        # Log chemin une fois UI_LANG résolu (visible Live Logs / docker).
        if not _logged_config_path:
            from translations import get_ui_translations
            _t = get_ui_translations(config=config)
            logging.info(
                _t.get("log_config_file", "[Config] Fichier de configuration : %s"),
                CONFIG_FILE,
            )
            _logged_config_path = True

        return config


def _resolve_bool(file_config: dict, key: str, default: bool = False) -> bool:
    """Booléen depuis config.json, sinon env, sinon défaut."""
    if key in file_config:
        val = file_config[key]
        if isinstance(val, bool):
            return val
        if val is None:
            return default
        return str(val).strip().lower() in ("1", "true", "yes", "on")
    env = os.getenv(key)
    if env is not None and str(env).strip() != "":
        return str(env).strip().lower() in ("1", "true", "yes", "on")
    return bool(default)


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
    """IDs exclus du **polling auto-sync** uniquement (`DISABLED_LIBRARIES`).

    Ne masque pas le dashboard, n'affecte pas le batch manuel ni le webhook.
    """
    if config is None:
        config = load_config()
    return parse_library_id_list(config.get("DISABLED_LIBRARIES"))


def is_library_enabled(library_id, config=None) -> bool:
    """True si la bibliothèque n'est pas dans DISABLED_LIBRARIES (auto-sync)."""
    if library_id is None or library_id == "":
        return True
    disabled = get_disabled_library_ids(config)
    if not disabled:
        return True
    return str(library_id) not in disabled


def format_disabled_libraries(ids) -> str:
    """Sérialise un iterable d'IDs en chaîne config DISABLED_LIBRARIES."""
    cleaned = parse_library_id_list(ids)
    return ",".join(sorted(cleaned, key=_library_id_sort_key))


def parse_scraper_id_list(value) -> set:
    """Parse une liste d'IDs scraper (virgules / points-virgules), normalisés en UPPER."""
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip().upper()
            if text and text != "NONE":
                parts.append(text)
        return set(parts)
    text = str(value).strip()
    if not text:
        return set()
    parts = []
    for chunk in text.replace(";", ",").split(","):
        chunk = chunk.strip().upper()
        if chunk and chunk != "NONE":
            parts.append(chunk)
    return set(parts)


def get_disabled_scraper_ids(config=None) -> set:
    """IDs de scrapers désactivés (`DISABLED_SCRAPERS`)."""
    if config is None:
        config = load_config()
    return parse_scraper_id_list(config.get("DISABLED_SCRAPERS"))


def is_scraper_enabled(scraper_id, config=None) -> bool:
    if not scraper_id:
        return True
    disabled = get_disabled_scraper_ids(config)
    if not disabled:
        return True
    return str(scraper_id).strip().upper() not in disabled


def format_disabled_scrapers(ids) -> str:
    """Sérialise un iterable d'IDs scraper en chaîne config DISABLED_SCRAPERS."""
    cleaned = parse_scraper_id_list(ids)
    return ",".join(sorted(cleaned))


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
    """Écrit config.json de façon atomique (tmp + replace) sous CONFIG_LOCK.

    Retourne le chemin absolu écrit. Relit le fichier après replace pour
    confirmer que KAVITA_* (et le reste) sont bien sur disque — un échec lève
    RuntimeError plutôt que de laisser l'UI croire que la modal a sauvé.
    """
    with CONFIG_LOCK:
        if "MATCH_ACCEPT_THRESHOLD" in data:
            data["MATCH_ACCEPT_THRESHOLD"] = _parse_match_threshold(
                data.get("MATCH_ACCEPT_THRESHOLD")
            )
        if "MATCH_THRESHOLD_CUSTOM" in data:
            data["MATCH_THRESHOLD_CUSTOM"] = bool(data.get("MATCH_THRESHOLD_CUSTOM"))
        if "DUP_ACCEPT_THRESHOLD" in data:
            data["DUP_ACCEPT_THRESHOLD"] = _parse_match_threshold(
                data.get("DUP_ACCEPT_THRESHOLD"),
                default=0.92,
                minimum=0.70,
                maximum=1.00,
            )
        if "DUP_THRESHOLD_CUSTOM" in data:
            data["DUP_THRESHOLD_CUSTOM"] = bool(data.get("DUP_THRESHOLD_CUSTOM"))
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)

        # Écriture atomique : open("w") tronque d'abord ; un JSON partiel + .bak
        # régénérait des secrets vides (symptôme « la modal n'écrit pas »).
        fd, tmp_path = tempfile.mkstemp(
            prefix="config.", suffix=".tmp.json", dir=DATA_DIR
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, CONFIG_FILE)
            tmp_path = None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError as chmod_err:
            logging.debug(
                "[Config] chmod 600 impossible sur %s (%s) — sans conséquence sur la "
                "sauvegarde, mais les permissions du fichier restent celles du système "
                "de fichiers.",
                CONFIG_FILE, chmod_err,
            )

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                disk = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            from translations import get_ui_translations
            t = get_ui_translations(config=data)
            raise RuntimeError(
                t.get("log_config_unreadable_after_write", "config.json illisible juste après écriture ({0}): {1}").format(CONFIG_FILE, exc)
            ) from exc

        for check_key in ("KAVITA_URL", "KAVITA_API_KEY", "SECRET_KEY", "WEBHOOK_TOKEN"):
            if check_key not in data:
                continue
            if disk.get(check_key) != data.get(check_key):
                from translations import get_ui_translations
                t = get_ui_translations(config=data)
                raise RuntimeError(
                    t.get("log_config_persist_mismatch", "Persistance échouée pour {0} dans {1} (mémoire ≠ disque).").format(check_key, CONFIG_FILE)
                )

        return CONFIG_FILE
