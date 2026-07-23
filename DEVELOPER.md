# MetaKavita - Developer & Contribution Guide

This guide is designed for developers and AI assistants wishing to understand, maintain, or extend the MetaKavita codebase. 

---

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
   * [1. Global Architecture & Security](#1-global-architecture--security)
   * [2. High-Speed Throttling & Rate-Limiting Architecture](#2-high-speed-throttling--rate-limiting-architecture)
   * [3. Reverse Proxy & Subpath Architecture](#3-reverse-proxy--subpath-architecture)
   * [4. Frontend Mechanics & Live Console Sanitization](#4-frontend-mechanics--live-console-sanitization)
   * [5. Scraper Factory, Auto-Discovery & Dynamic APIs](#5-scraper-factory-auto-discovery--dynamic-apis)
   * [6. Deep Extraction, Unified Scoring & Overrides](#6-deep-extraction-unified-scoring--overrides)
   * [7. Active Scraper Ecosystem (V1.5.5)](#7-active-scraper-ecosystem-v155)
   * [8. Resilient Translation Pipeline](#8-resilient-translation-pipeline)
   * [9. AI-Powered Scraper Creation (Vibecoding)](#9-ai-powered-scraper-creation-vibecoding)
   * [10. Quality Benchmarking & Debugging Suite](#10-quality-benchmarking--debugging-suite)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)
   * [1. Architecture Globale & Sécurité](#1-architecture-globale--sécurité-1)
   * [2. Moteur de Throttling & Régulation Dynamique](#2-moteur-de-throttling--régulation-dynamique-1)
   * [3. Architecture Reverse Proxy & Sous-dossiers](#3-architecture-reverse-proxy--sous-dossiers-1)
   * [4. Mécanismes Frontend & Nettoyage de la Console](#4-mécanismes-frontend--nettoyage-de-la-console-1)
   * [5. Scraper Factory, Auto-Découverte & APIs Dynamiques](#5-scraper-factory-auto-découverte--apis-dynamiques-1)
   * [6. Extraction Profonde, Scoring Unifié & Forçages](#6-extraction-profonde-scoring-unifié--forçages-1)
   * [7. Écosystème des Scrapers Actifs (V1.5.5)](#7-écosystème-des-scrapers-actifs-v155-1)
   * [8. Pipeline de Traduction Abstrait](#8-pipeline-de-traduction-abstrait-1)
   * [9. Création de Scrapers via IA (Vibecoding)](#9-création-de-scrapers-via-ia-vibecoding-1)
   * [10. Suite de Tests & Débogage Qualité](#10-suite-de-tests--débogage-qualité-1)

---

## 🇺🇸 English Developer Guide

### 1. Global Architecture & Security
MetaKavita is an asynchronous Python application powered by a **Gunicorn WSGI server** with **Eventlet** workers to support real-time WebSockets via Flask-SocketIO.

*   **Security Layer:** Global authentication is enforced via `@app.before_request`. Session cookies are configured as `HttpOnly` and `SameSite=Lax`.
*   **Timing Attack Protection:** The login system uses `secrets.compare_digest` to prevent timing analysis of passwords, paired with a brute-force delay on failure.
*   **SSRF Protection:** The `/api/proxy-image` route uses dynamic strict whitelisting via `ScraperRegistry.get_all_proxy_domains()`.
*   **Webhook Hardening:** Webhooks require a cryptographically secure `WEBHOOK_TOKEN` generated in `data/config.json`. The endpoint accepts flexible JSON/Form payloads (`seriesId`, `name`, and optional `"force": true` parameter) and features on-demand UI token rotation via POST `/regenerate-webhook-token`.
*   **API Keys Masking:** All sensitive API keys are censored with `********` on DOM generation to protect credentials from shoulder-surfing or browser extension scraping.
*   **Kavita API Resiliency:** Interactions with Kavita feature robust 30-second timeouts to handle heavy DB re-indexing during batches, safely unwrap payloads wrapped inside unexpected `[{...}]` JSON arrays, and automatically invalidate the in-memory `_series_lib_type_cache` on batch starts so updated library types (such as ID 5 `Comic Flexible`) are detected without container restarts.

---

### 2. High-Speed Throttling & Rate-Limiting Architecture

MetaKavita v1.5.5 eliminates hardcoded thread sleep delays (`time.sleep(1.5)` / `time.sleep(2.5)`) in favor of a **Timestamp-Based Dynamic Throttler** (`LAST_REQUEST_TIMES`) in `metadata_fetcher.py`.

#### A. How the Throttler Works (`throttle_provider`)
Before executing any scraper `fetch()`, `metadata_fetcher.py` calculates the time elapsed since that specific scraper was last called:
```python
elapsed = current_time - LAST_REQUEST_TIMES.get(scraper.id, 0.0)
if elapsed < scraper.rate_limit:
    time.sleep(scraper.rate_limit - elapsed)
LAST_REQUEST_TIMES[scraper.id] = time.time()
```

#### B. Architectural Advantages
1. **Zero Delay for Idle APIs:** If an API has not been called recently, `elapsed >= rate_limit`, resulting in **0.0s delay**.
2. **Lightning-Fast Smart Fusion:** When cascading across 3 distinct providers (e.g. `MANGABAKA` -> `KITSU` -> `ANILIST`), all 3 providers execute sequentially with **zero artificial pauses**, executing complete 3-provider fusions in ~1.6 seconds.
3. **Batch Immunity Against HTTP 429:** High-volume batch requests throttle each scraper strictly according to its declared `rate_limit` (e.g., 0.2s for MangaBaka, 1.0s for AniList, 1.2s for ComicVine) at maximum theoretical throughput.

---

### 3. Reverse Proxy & Subpath Architecture

MetaKavita natively supports deployment under custom URL subpaths (e.g. `https://domain.com/metakavita`).

#### A. Backend WSGI Middleware Layer (`app.py`)
Reverse proxy headers (`X-Forwarded-Prefix`) are processed via Werkzeug's `ProxyFix`. In addition, if a user specifies an explicit subpath using the `ROOT_PATH` environment variable in Docker, a custom `ScriptNameStripper` WSGI middleware handles path rewriting.

#### B. Client-Side Prefixing (`script.js` & Jinja)
In `templates/index.html`, Flask's `request.script_root` is exposed globally (`window.ROOT_PATH`). In `static/js/script.js`, all fetch endpoints and Socket.IO connections use `getRootPath()`.

---

### 4. Frontend Mechanics & Live Console Sanitization

#### A. Live WebSocket Cover Streaming (*Progressive Loading*)
Manual cover searches stream image results live over WebSockets as each provider responds, rather than blocking until all scrapers finish.
*   **Backend Mechanism (`app.py`)**: When `@socketio.on('fetch_covers_stream')` receives a query, it spawns parallel greenlets via `socketio.start_background_task`. Once a provider finishes, it emits `cover_stream_data` and executes **`socketio.sleep(0)`** to yield control to Eventlet's cooperative scheduler, forcing TCP frame flushing.

#### B. Live UI Console Sanitization
The `WebSocketLogHandler` inside `app.py` actively filters out `[DEBUG]` messages (such as heavy raw JSON payloads being pushed to Kavita) before emitting them to the UI. This ensures the dashboard's "Live Logs" terminal remains clean, human-readable, and purely focused on operational progress, while full debug traces are still safely logged to the physical `data/metakavita.log` file.

---

### 5. Scraper Factory, Auto-Discovery & Dynamic APIs

MetaKavita uses an **Auto-Discovery Registry pattern**. On startup, `scrapers/__init__.py` scans the `scrapers/` folder and dynamically loads any class inheriting from `BaseScraper`.

*   **Dynamic API Keys (Zero-Hardcode):** If a scraper sets `needs_api_key = True`, the core engine automatically provisions `[ID]_API_KEY`, loads it from `config.json` or `os.environ`, censors it (`********`), and generates the HTML input in the Settings Modal dynamically.
*   **Unrestricted Provider Forcing:** In `templates/index.html` and `metadata_fetcher.py`, users can manually force *any* registered scraper on any series via the Magic Input dropdown, bypassing library type restrictions.
*   **Decentralized Translations (i18n):** Scrapers encapsulate their own logs and error messages in a `translations` dictionary, accessed via `self.t("key")`.

---

### 6. Deep Extraction, Unified Scoring & Overrides

MetaKavita v1.5.5 introduces a major paradigm shift for handling complex metadata (like Novels and Comic series) through context-aware searching.

#### A. Kavita Deep Extraction & Context Propagation
Before querying external APIs, `kavita_api.py` fetches the `existing_metadata` already stored in Kavita for the series (Sanitized ISBN, Authors, Publisher, Release Year, Genres, Localized Name).
* This context is passed down to `metadata_fetcher.py`.
* Scrapers use it to perform exact ID searches (e.g., querying `isbn:12345`).
* During **Smart Fusion**, if a scraper discovers an ISBN or an author, it dynamically injects it into the `existing_metadata` context before passing it to the next fallback scraper in the cascade!

#### B. Unified Weighted Scoring Matrix (`scrapers/utils.py`)
Individual scrapers format API payloads into candidate dictionaries and evaluate them using `score_candidate(candidate, search_query, existing_metadata)`:
1.  **ISBN Golden Rule**: Exact sanitized ISBN match = **100% (1.0)** instant score.
2.  **Title & Author Core**: **60%** Title string similarity + **40%** dynamic Author surname intersection (`calculate_author_similarity`).
3.  **Anti-Homonym Author Mismatch Penalty**: If Kavita context has an author and the candidate provides an author, but similarity is `< 0.35`, a strict **`-50%` penalty** is applied (preventing manga adaptations from replacing classical novels like *Les Misérables*).
4.  **Roman Numeral Volume Converter**: Automatically converts Roman volume numbers (`Tome II` -> `Tome 2`) before calculating string similarity.
5.  **Anti-Spin-Off & Guidebook Filters**: Applies a **`-35%` penalty** if key distinctive query words are missing (*Lanfeust des Étoiles* vs *Troy*) and a **`-50%` penalty** for noise keywords (`Guidebook`, `Fanbook`, `Artbook`) unless explicitly requested.
6.  **Volume 1 Anchoring**: Grants **`+0.10` bonus** to Volume 1/unnumbered editions while inflicting **`-0.45` penalty** to intermediate volumes (e.g., Tome 12) when searching for a global Series.

#### C. Smart Overrides & Force Update Context
*   **Granular Scraping**: Users can selectively lock 12 individual metadata fields via checkboxes in the UI.
*   **Force Update Context Reset**: A UI setting (`RESET_CONTEXT_ON_FORCE`) determines if clicking "Force Update" should retain the existing Kavita Author/ISBN context, or completely wipe it to break a negative feedback loop caused by previous false-positive scrapes.

---

### 7. Active Scraper Ecosystem (V1.5.5)

| Scraper ID | Provider Name | Types | Key Features |
| :--- | :--- | :--- | :--- |
| `ANILIST` | AniList | Manga, Comic, Book | GraphQL API, candidate scoring against spin-offs, native `AniListId` & `MAL` mapping. |
| `BEDETHEQUE` | Bédéthèque | Comic | Franco-Belgian BD scraper via `curl_cffi` CSRF bypass, exact series title match logic. |
| `COMICVINE` | ComicVine | Comic | API Key required. Structured `/volumes/?filter=name:` search, primary publisher weighting (*DC Comics*, *Marvel*, *Dargaud*), Issue #1 summary/staff fallback. |
| `GOOGLEBOOKS` | Google Books | Book, Comic | API Key required. Dynamic `langRestrict` fallbacks, ISBN targeting, anti-empty summary bonus. |
| `HARDCOVER` | Hardcover (Exp) | Book, Comic | API Key required. Hasura GraphQL API & Typesense search, Chrome impersonation. |
| `KITSU` | Kitsu | Manga | JSON:API integration, no API key required, fast response times. |
| `MANGANEWS` | Manga-News | Manga | VF French catalog scraper (`curl_cffi`), extracts VF publishers (*Pika*, *Glénat*, *Kurokawa*). |
| `MANGABAKA` | MangaBaka | Manga | REST API v2, native `MangaBakaId` mapping, null-safe JSON payload parsing. |
| `MANGADEX` | MangaDex | Manga | API v5, content rating filters (`erotica`), `AniList`/`MAL` ID extraction, oneshot penalty. |
| `MANGAUPDATES`| MangaUpdates | Manga | REST API v1, `hit_title` matching, candidate keyword penalty scoring. |
| `OPENLIBRARY` | Open Library | Book, Comic | Internet Archive literature API, Work key & ISBN support, anti-429 retries. |
| `SHIKIMORI` | Shikimori | Manga | REST JSON API, multilingual title matching, native `MalId` mapping, `/roles` staff extraction. |

---

### 8. Resilient Translation Pipeline
Translation operations sit inside `translator.py`:
*   **Option NONE (Disabled):** Preserves original text without modification.
*   **Tier 1: Microsoft Azure Translator** (F0 tier, 2M chars/month free).
*   **Tier 2: DeepL API** (Free tier, 1M chars lifetime limit).
*   **Tier 3: Google Translate ("Zero-Config" Fallback)** (Unofficial `py-googletrans` library).

---

### 9. AI-Powered Scraper Creation (Vibecoding)

To add a new metadata source, drop a `.py` file into the `scrapers/` folder implementing `BaseScraper`.

#### AI Prompt Template
> "Act as an Expert Python Developer. I am building a metadata scraper for an application using an Auto-Discovery Registry. You just need to create a class inheriting from `BaseScraper`.
> Contract to implement:
> ```python
> from typing import Dict, Any, List, Optional, Set
> from scrapers.base import BaseScraper
> from scrapers.utils import clean_title, score_candidate
> 
> class MyNewScraper(BaseScraper):
>     id = "UNIQUE_ID"
>     display_name = "Public Name"
>     supported_types = {"Manga"} # "Manga", "Comic", or "Book"
>     rate_limit = 1.0
>     proxy_domains = ["domain.com"]
>     has_direct_id_support = True
>     needs_api_key = False # Set True if your provider requires an API Key
> 
>     translations = {
>         "fr": {"search": "Recherche sur MyProvider : {0}"},
>         "en": {"search": "Searching MyProvider: {0}"}
>     }
> 
>     def extract_id_from_url(self, url: str) -> Optional[str]:
>         return None
> 
>     def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
>         clean = clean_title(query, library_type=library_type)
>         
>         # 1. Query your API.
>         # 2. Build standardized candidate dictionaries matching the expected Kavita payload.
>         # 3. Use score_candidate(candidate, clean, existing_metadata) on each result.
>         # 4. Return the candidate with the highest score IF score >= 0.50. Otherwise return None.
>         
>         # Expected Candidate Dictionary structure:
>         '''
>         {
>             'title': 'str_original_title',     # MANDATORY for Scoring
>             'alternative_titles': ['list'],
>             'summary': 'str',
>             'cover_url': 'str',
>             'genres': ['list'],
>             'tags': ['list'],                  # max 15
>             'year': int,
>             'status': 'RELEASING/FINISHED/HIATUS/CANCELLED',
>             'staff': [{'role': 'Story/Art/Color/Translator/Editor/Letterer/Inker', 'node': {'name': {'full': 'Author Name'}}}],
>             'publisher': 'str',
>             'age_rating': 'safe/suggestive/pornographic',
>             'format': 'manga/webtoon/comic/book',
>             'url': 'str_url_of_the_page',
>             'isbn': 'str_numbers_only'         # Crucial for Books!
>         }
>         '''
>         pass
> 
>     def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
>         # MUST return list of dicts: [{"provider": self.display_name, "title": "Album Title", "url": "Image URL"}]
>         pass
> ```"

---

### 10. Quality Benchmarking & Debugging Suite

Developers can run standalone unit test scripts located at the project root to validate engine features without needing a running Kavita server:

*   **`debug_all_scrapers.py`**: Executes direct non-cascaded searches across all 12 registered scrapers to verify basic API connectivity and signature compliance.
*   **`debug_scoring.py` / `debug_scoring_20.py`**: Runs a 20-case edge-case stress test against `scrapers/utils.py` (Roman numerals, spin-offs, guidebooks, author mismatches, ISBN formatting).
*   **`debug_engine.py`**: Validates Smart Fusion logic, multi-provider fallback cascades, and WebSocket multithreaded cover fetching timings.
*   **`debug_manga_quality.py` / `debug_comic_quality.py` / `debug_book_quality.py`**: Category-specific quality audits checking summary character length, staff extraction count, format detection (`webtoon` vs `manga`), publishers, and platform IDs.

---

## 🇫🇷 Guide de Développement Français

### 1. Architecture Globale & Sécurité
MetaKavita est une application Python asynchrone fonctionnant derrière un **serveur WSGI Gunicorn** couplé à des workers **Eventlet** pour supporter les WebSockets en temps réel via Flask-SocketIO.

*   **Authentification :** Sécurisée au niveau global via `@app.before_request`. Les cookies de session sont configurés en `HttpOnly` et `SameSite=Lax`.
*   **Attaques Temporelles (Timing Attacks) :** Le système de connexion utilise `secrets.compare_digest`.
*   **Protection SSRF :** La route de proxy d'images `/api/proxy-image` utilise une liste blanche dynamique.
*   **Protection Webhook :** Authentification exigeant un jeton cryptographique (`WEBHOOK_TOKEN`) enregistré dans `data/config.json`. 
*   **Censure de sécurité des clés :** Toutes les clés d'API sensibles sont masquées par `********` lors de la génération du DOM HTML.
*   **Résilience de l'API Kavita :** Les communications HTTP avec Kavita intègrent un timeout étendu de 30 secondes, désencapsulent automatiquement les tableaux JSON `[{...}]` inattendus, et purgent dynamiquement le cache mémoire `_series_lib_type_cache` au lancement des batchs pour prendre en compte immédiatement les changements de types de bibliothèques (comme l'ID 5 `Comic Flexible`) sans redémarrer le conteneur Docker.

---

### 2. Moteur de Throttling & Régulation Dynamique

La version 1.5.5 remplace les pauses fixes (`1.5s` / `2.5s`) par un **Régulateur Dynamique par Horodatage (`LAST_REQUEST_TIMES`)** centralisé dans `metadata_fetcher.py`.

#### A. Fonctionnement (`throttle_provider`)
Avant chaque appel à la méthode `fetch()` d'un scraper, le moteur calcule le temps écoulé depuis son dernier appel :
```python
elapsed = temps_actuel - LAST_REQUEST_TIMES.get(scraper.id, 0.0)
if elapsed < scraper.rate_limit:
    time.sleep(scraper.rate_limit - elapsed)
LAST_REQUEST_TIMES[scraper.id] = time.time()
```

#### B. Avantages
1. **Zéro Attente sur les API Inactives :** Si une API n'a pas été appelée récemment, le délai est de **0.0 seconde**.
2. **Smart Fusion Instantanée :** Lors d'une cascade sur 3 fournisseurs différents (`MANGABAKA` -> `KITSU` -> `ANILIST`), les 3 API répondent à la suite sans aucune pause artificielle (fusion réalisée en ~1,6s).
3. **Protection HTTP 429 en Batch :** Les traitements par lots régulent chaque source à sa vitesse maximale théorique (`MangaBaka` = 0,2s, `AniList` = 1,0s, `ComicVine` = 1,2s).

---

### 3. Architecture Reverse Proxy & Sous-dossiers

MetaKavita supporte le déploiement sous un sous-chemin personnalisé (ex: `https://domaine.com/metakavita`).

#### A. Couche Middleware WSGI Backend (`app.py`)
Les en-têtes proxy (`X-Forwarded-Prefix`) sont gérés par `ProxyFix`. En complément, si l'utilisateur spécifie une variable d'environnement `ROOT_PATH` dans Docker, un middleware `ScriptNameStripper` réécrit les routes WSGI en interne.

#### B. Préfixage Côté Client (`script.js` & Jinja)
Dans `templates/index.html`, la variable `request.script_root` est exposée au JS (`window.ROOT_PATH`). Dans `static/js/script.js`, tous les appels HTTP et WebSockets utilisent dynamiquement `getRootPath()`.

---

### 4. Mécanismes Frontend & Nettoyage de la Console

#### A. Streaming de Couvertures par WebSockets (*Progressive Loading*)
La recherche manuelle d'images envoie désormais les résultats en direct au fil de l'eau dès qu'un provider répond, sans bloquer l'interface, en utilisant `socketio.start_background_task` et en forçant le flush des trames TCP avec `socketio.sleep(0)`.

#### B. Filtrage du Terminal Live Logs
La classe `WebSocketLogHandler` filtre dynamiquement les messages de niveau `[DEBUG]` (qui contiennent d'énormes payloads JSON bruts envoyés à Kavita) avant de les émettre sur le réseau WebSocket. Cela garantit que la console "Live Logs" de l'interface reste épurée et lisible, tout en conservant les logs complets dans le fichier `data/metakavita.log`.

---

### 5. Scraper Factory, Auto-Découverte & APIs Dynamiques

MetaKavita utilise un **Pattern Registre par Auto-Découverte**. Au démarrage, `scrapers/__init__.py` scanne le dossier `scrapers/` et charge dynamiquement toutes les classes héritant de `BaseScraper`.

*   **Clés API Dynamiques (Zero-Hardcode) :** Mettre `needs_api_key = True` dans un scraper ordonne au système de lire/sauvegarder automatiquement `[ID]_API_KEY`, de le censurer (`********`), et de générer l'input HTML dans la modale de l'interface sans écrire une seule ligne de code frontal.
*   **Forçage Libre des Fournisseurs :** Dans `templates/index.html` et `metadata_fetcher.py`, le menu déroulant du Champ Magique propose l'intégralité des scrapers pour forcer manuellement n'importe quelle source.
*   **Traductions Décentralisées :** Chaque scraper héberge son dictionnaire `translations = {"fr": {...}}` et utilise `self.t("clé")`.

---

### 6. Extraction Profonde, Scoring Unifié & Forçages

La version 1.5.5 introduit un changement d'architecture majeur pour la précision des fiches complexes (Romans et séries fleuves).

#### A. Extraction Profonde (Kavita Deep Extraction)
Avant de lancer le scraping, `kavita_api.py` extrait silencieusement les données déjà présentes dans la base de données de l'œuvre Kavita ciblée (ISBN nettoyé, Auteurs, Éditeur, Année de sortie).
* Ce "contexte" est envoyé aux scrapers via le paramètre `existing_metadata`.
* Durant une **Fusion Intelligente (Smart Fusion)**, si un scraper de secours trouve l'ISBN, ce dernier est immédiatement injecté dans le contexte global pour aider les scrapers restants à cibler précisément la page exacte du livre !

#### B. Matrice de Scoring Unifiée (`scrapers/utils.py`)
Les scrapers transmettent leurs candidats à la fonction `score_candidate(candidate, search_query, existing_metadata)` :
1.  **Règle d'or de l'ISBN** : Match exact d'ISBN nettoyé = **100% (1.0)**.
2.  **Duo Titre & Auteur** : **60%** Titre + **40%** Auteurs (`calculate_author_similarity`).
3.  **Règle Anti-Homonyme Auteur** : Pénalité de **`-50%`** si les auteurs du candidat et de Kavita diffèrent (`author_sim < 0.35`).
4.  **Convertisseur de Chiffres Romains** : Conversion automatique (`Tome II` -> `Tome 2`) avant le calcul de similarité.
5.  **Filtres Anti-Spin-Off & Anti-Guidebook** : Pénalité de **`-35%`** si un mot-clé du titre est absent (*Lanfeust des Étoiles* vs *Troy*) et pénalité de **`-50%`** pour les mots parasites (`Guidebook`, `Fanbook`, `Artbook`).
6.  **Ancrage Tome 1** : Bonus de **`+0.10`** pour le Tome 1/édition sans numéro, et pénalité de **`-0.45`** sur les tomes intermédiaires lors de la recherche de la série mère.

#### C. Forçage Avancé (Smart Overrides)
*   **Scraping Granulaire** : 12 champs de métadonnées peuvent être verrouillés indépendamment via des cases à cocher dans l'interface (Résumé, Couvertures, Staff, Editeur, etc.).
*   **Purge du Contexte (Reset Context)** : Une option permet d'effacer le contexte actuel de Kavita lors d'un forçage pour repartir d'une page blanche.

---

### 7. Écosystème des Scrapers Actifs (V1.5.5)

| Identifiant | Nom Public | Types | Spécificités & Fonctionnalités |
| :--- | :--- | :--- | :--- |
| `ANILIST` | AniList | Manga, Comic, Book | API GraphQL, scoring des candidats contre les spin-offs, mapping natif `AniListId` & `MAL`. |
| `BEDETHEQUE` | Bédéthèque | Comic | Scraper BD franco-belge via `curl_cffi` (contournement CSRF), match exact de titres. |
| `COMICVINE` | ComicVine | Comic | API Key requise. Recherche structurée `/volumes/?filter=name:`, priorisation des éditeurs majeurs (*DC Comics*, *Marvel*, *Dargaud*), fallback de résumé/staff sur l'Issue #1. |
| `GOOGLEBOOKS` | Google Books | Book, Comic | API Key requise. Métadonnées internationales, replis de langue, bonus anti-résumé vide. |
| `HARDCOVER` | Hardcover (Exp) | Book, Comic | API Key requise. Requêtes Hasura GraphQL + Typesense, impersonation Chrome. |
| `KITSU` | Kitsu | Manga | API JSON:API, sans clé requise, réponses rapides. |
| `MANGANEWS` | Manga-News | Manga | Catalogue VF (`curl_cffi`), extraction des éditeurs français (*Pika*, *Glénat*, *Kurokawa*), visuels HD. |
| `MANGABAKA` | MangaBaka | Manga | API REST v2, mapping `MangaBakaId`, sécurisation contre les clés `null` dans l'API JSON. |
| `MANGADEX` | MangaDex | Manga | API v5, filtres adultes (`erotica`), extraction IDs `AniList`/`MAL`, pénalité Oneshot. |
| `MANGAUPDATES`| MangaUpdates | Manga | API REST v1, correspondance par `hit_title`, scoring par mots-clés, nettoyeur BBCode. |
| `OPENLIBRARY` | Open Library | Book, Comic | API Littérature Internet Archive, clés Work (`OL...W`) & ISBNs, pause anti-429. |
| `SHIKIMORI` | Shikimori | Manga | API REST JSON, évaluation multilingue (Romaji, Anglais, Japonais), mapping `MalId`, extraction du staff via `/roles`. |

---

### 8. Pipeline de Traduction Abstrait
Toutes les traductions sont centralisées dans `translator.py` :
*   **Option NONE (Désactivé) :** Conserve le texte brut d'origine sans modification.
*   **Niveau 1 : Microsoft Azure Translator** (F0, 2M caractères gratuits/mois).
*   **Niveau 2 : DeepL API** (1M caractères gratuits à vie).
*   **Niveau 3 : Google Translate ("Zero-Config")** (Librairie `py-googletrans`).

---

### 9. Création de Scrapers via IA (Vibecoding)

Pour ajouter une nouvelle source de métadonnées, il suffit de glisser un fichier `.py` dans le dossier `scrapers/` qui implémente `BaseScraper`.

#### Le Prompt IA Ultime
> "Agis en tant que Développeur Python Expert. Je construis un scraper de métadonnées pour mon application utilisant un Registre par Auto-Découverte. Tu dois juste créer une classe qui hérite de `BaseScraper`.
> Contrat à implémenter :
> ```python
> from typing import Dict, Any, List, Optional, Set
> from scrapers.base import BaseScraper
> from scrapers.utils import clean_title, score_candidate
> 
> class MyNewScraper(BaseScraper):
>     id = "UNIQUE_ID"
>     display_name = "Nom Public"
>     supported_types = {"Manga"} # "Manga", "Comic", ou "Book"
>     rate_limit = 1.0
>     proxy_domains = ["domaine.com"]
>     has_direct_id_support = True
>     needs_api_key = False # Mettre True si une clé API est requise
> 
>     translations = {
>         "fr": {"search": "Recherche sur MyProvider : {0}"},
>         "en": {"search": "Searching MyProvider: {0}"}
>     }
> 
>     def extract_id_from_url(self, url: str) -> Optional[str]:
>         return None
> 
>     def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
>         clean = clean_title(query, library_type=library_type)
>         
>         # 1. Interroge ton API web.
>         # 2. Construit une liste de candidats standardisés (format Kavita ci-dessous).
>         # 3. Passe chaque candidat dans la moulinette score_candidate(candidate, clean, existing_metadata).
>         # 4. Retourne le candidat ayant le meilleur score SI ET SEULEMENT SI le score >= 0.50 (50%).
>         
>         # Format OBLIGATOIRE du dictionnaire candidat à retourner en cas de succès :
>         '''
>         {
>             'title': 'str_titre_original',     # OBLIGATOIRE pour le Scoring !
>             'alternative_titles': ['list'],
>             'summary': 'str',
>             'cover_url': 'str',
>             'genres': ['list'],
>             'tags': ['list'],                  # max 15
>             'year': int,
>             'status': 'RELEASING/FINISHED/HIATUS/CANCELLED',
>             'staff': [{'role': 'Story/Art/Color/Translator/Editor/Letterer/Inker', 'node': {'name': {'full': 'Prénom Nom'}}}],
>             'publisher': 'str',
>             'age_rating': 'safe/suggestive/pornographic',
>             'format': 'manga/webtoon/comic/book',
>             'url': 'str_url_of_the_page',
>             'isbn': 'str_chiffres_uniquement'  # Crucial pour la détection des livres !
>         }
>         '''
>         pass
> 
>     def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
>         # DOIT retourner une liste de dicts : [{"provider": self.display_name, "title": "Titre Album", "url": "URL Image"}]
>         pass
> ```"

---

### 10. Suite de Tests & Débogage Qualité

Les développeurs peuvent exécuter des scripts de tests unitaires autonomes situés à la racine du projet pour valider les composants sans nécessiter d'instance Kavita en cours d'exécution :

*   **`debug_all_scrapers.py`** : Exécute des recherches directes sans cascade sur l'ensemble des 12 scrapers enregistrés pour vérifier la connectivité API et la conformité des signatures.
*   **`debug_scoring.py` / `debug_scoring_20.py`** : Exécute le banc d'essai de 20 cas limites sur la matrice de scoring dans `scrapers/utils.py` (chiffres romains, spin-offs, guidebooks, incompatibilités d'auteurs, ISBNs).
*   **`debug_engine.py`** : Valide la Smart Fusion, les cascades de repli et le temps d'exécution du multithreading de couvertures.
*   **`debug_manga_quality.py` / `debug_comic_quality.py` / `debug_book_quality.py`** : Audits de qualité par catégorie analysant la longueur des résumés, le nombre d'auteurs extraits, la détection des formats (`webtoon` vs `manga`), les éditeurs et la présence d'ISBNs ou d'IDs de plateformes.