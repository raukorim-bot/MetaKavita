# MetaKavita - Developer & Contribution Guide

This guide is designed for developers and AI assistants wishing to understand, maintain, or extend the MetaKavita codebase. 

---

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
   * [1. Global Architecture & Security](#1-global-architecture--security)
   * [2. High-Speed Throttling & Rate-Limiting Architecture](#2-high-speed-throttling--rate-limiting-architecture)
   * [3. Reverse Proxy & Subpath Architecture](#3-reverse-proxy--subpath-architecture)
   * [4. Frontend Mechanics & WebSocket Stream IDs](#4-frontend-mechanics--websocket-stream-ids)
   * [5. Sideloading Scrapers & Auto-Discovery Registry](#5-sideloading-scrapers--auto-discovery-registry)
   * [6. Deep Extraction, Publisher QoS & Unified Scoring](#6-deep-extraction-publisher-qos--unified-scoring)
   * [7. Active Scraper Ecosystem (V1.5.7)](#7-active-scraper-ecosystem-v157)
   * [8. Resilient Translation & Title Fallback](#8-resilient-translation--title-fallback)
   * [9. AI-Powered Scraper Creation (Vibecoding)](#9-ai-powered-scraper-creation-vibecoding)
   * [10. Quality Benchmarking & Debugging Suite](#10-quality-benchmarking--debugging-suite)
   * [11. Critical Pitfalls & Contribution Workflow](#11-critical-pitfalls--contribution-workflow)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)
   * [1. Architecture Globale & Sécurité](#1-architecture-globale--sécurité-1)
   * [2. Moteur de Throttling & Régulation Dynamique](#2-moteur-de-throttling--régulation-dynamique-1)
   * [3. Architecture Reverse Proxy & Sous-dossiers](#3-architecture-reverse-proxy--sous-dossiers-1)
   * [4. Mécanismes Frontend & Jetons WebSockets](#4-mécanismes-frontend--jetons-websockets-1)
   * [5. Sideloading de Scrapers & Auto-Découverte](#5-sideloading-de-scrapers--auto-découverte-1)
   * [6. Extraction Profonde, QoS Éditeurs & Scoring](#6-extraction-profonde-qos-éditeurs--scoring-1)
   * [7. Écosystème des Scrapers Actifs (V1.5.7)](#7-écosystème-des-scrapers-actifs-v157-1)
   * [8. Traduction Résiliente & Titre de Secours](#8-traduction-résiliente--titre-de-secours-1)
   * [9. Création de Scrapers via IA (Vibecoding)](#9-création-de-scrapers-via-ia-vibecoding-1)
   * [10. Suite de Tests & Débogage Qualité](#10-suite-de-tests--débogage-qualité-1)
   * [11. Pièges Critiques & Flux de Contribution](#11-pièges-critiques--flux-de-contribution-1)

---

## 🇺🇸 English Developer Guide

### 1. Global Architecture & Security
MetaKavita is an asynchronous Python application powered by a **Gunicorn WSGI server** with **Eventlet** workers to support real-time WebSockets via Flask-SocketIO.

*   **Security Layer:** Global authentication is enforced via `@app.before_request`. Session cookies are configured as `HttpOnly` and `SameSite=Lax`. Timing attacks are prevented using `secrets.compare_digest`.
*   **SSRF Protection:** The `/api/proxy-image` route uses dynamic strict whitelisting via `ScraperRegistry.get_all_proxy_domains()`, which inherently protects even dynamically sideloaded community scrapers.
*   **Webhook Hardening:** Webhooks require a cryptographically secure `WEBHOOK_TOKEN` generated in `data/config.json`.
*   **Safe SQLite Schema Migrations:** Database updates in `db_manager.py` use a safe `_ensure_schema` method that handles `sqlite3.OperationalError` gracefully per column, preventing fatal container crashes when introducing new features.
*   **Pure Base64 Kavita Uploads:** Kavita requires cover uploads to be sent as pure Base64 byte strings (`kavita_api.py`). Prepending `Data URI` schemas (`data:image/jpeg;base64,...`) results in silent Kavita C# backend failures (the "Phantom Cover" syndrome).

---

### 2. High-Speed Throttling & Rate-Limiting Architecture
MetaKavita eliminates hardcoded thread sleep delays in favor of a **Timestamp-Based Dynamic Throttler** (`LAST_REQUEST_TIMES`).
Idle APIs respond instantly with zero artificial delay, executing 3-provider Smart Fusions in ~1.6s. High-volume batch requests throttle each scraper strictly according to its declared `rate_limit` (e.g., 0.2s for MangaBaka, 1.0s for AniList) at maximum theoretical throughput, providing immunity against HTTP 429 errors.

---

### 3. Reverse Proxy & Subpath Architecture
MetaKavita natively supports deployment under custom URL subpaths (e.g. `https://domain.com/metakavita`).
Reverse proxy headers (`X-Forwarded-Prefix`) are processed via Werkzeug's `ProxyFix`. In addition, if a user specifies an explicit subpath using the `ROOT_PATH` environment variable in Docker, a custom `ScriptNameStripper` WSGI middleware handles path rewriting. Client-side, `window.ROOT_PATH` dynamically prefixes all AJAX calls.

---

### 4. Frontend Mechanics & WebSocket Stream IDs

#### A. Live Cover Streaming & Race Conditions
Manual cover searches stream image results live over WebSockets via `socketio.start_background_task` and `socketio.sleep(0)`.
To prevent **Race Conditions** where slow scrapers from a previous search resolve late and pollute the user's currently active search, MetaKavita uses a chronological `stream_id` token. The client explicitly rejects any incoming WS frame that doesn't carry the latest `stream_id`.

#### B. Smart Auto-Cover Locking
When a user manually selects a cover from the modal, the client instantly triggers an AJAX call to uncheck the specific "Cover" checkbox in the series override panel. This locks the manual choice and protects it from being overwritten by global `AUTO_COVER` tasks during the next batch.

---

### 5. Sideloading Scrapers & Auto-Discovery Registry

MetaKavita features a **Dual-Sourced Auto-Discovery Registry** (`ScraperRegistry`). 
On startup, `scrapers/__init__.py` scans two distinct locations and uses `importlib.util` to dynamically load classes inheriting from `BaseScraper`:
1.  **Internal Core Scrapers:** Located in the Docker image (`/app/scrapers/`).
2.  **Community Sideloaded Scrapers:** Located in the user-mounted volume (`/app/data/scrapers/`).

If a custom scraper declares `needs_api_key = True`, MetaKavita will dynamically generate a password input in the UI Config Modal and load its value without requiring any frontend code modification.

---

### 6. Deep Extraction, Publisher QoS & Unified Scoring

#### A. Deep Extraction & True Context Reset
Before querying external APIs, MetaKavita fetches the existing metadata already stored in Kavita (Sanitized ISBN, Authors).
If a user triggers a **Context Reset** (`RESET_CONTEXT_ON_FORCE = True`), MetaKavita explicitly purges the ISBN from the local context. This is crucial because the ISBN is evaluated as a 100% Golden Rule match. If a corrupted ISBN remains in Kavita, no force update can bypass it.

#### B. Unified Weighted Scoring Matrix (`scrapers/utils.py`)
Scrapers build candidate dictionaries and evaluate them using `score_candidate`:
1.  **ISBN Golden Rule**: Exact sanitized ISBN match = 1.0 (100%).
2.  **Anti-Homonym Penalty**: If Kavita context has an author and candidate author similarity is `< 0.35`, a `-50%` penalty is applied.
3.  **Anti-Spin-Off Filters**: Missing distinctive query words penalizes the score by `-35%`.
4.  **Volume 1 Anchoring**: Grants `+0.10` bonus to Volume 1 while inflicting `-0.45` penalty to intermediate volumes.

#### C. Publisher Preference QoS
Users can dictate whether they want Localized Publishers (*Viz Media*, *Glénat*) or Original Japanese Publishers (*Shueisha*). 
This is handled via a global variable `PUBLISHER_PREFERENCE` and overridden individually per series using a Segmented UI Toggle. The value is injected directly into `existing_metadata['publisher_pref']` for scrapers to read during extraction.

---

### 7. Active Scraper Ecosystem (V1.5.7)

| Scraper ID | Provider Name | Types | Key Features |
| :--- | :--- | :--- | :--- |
| `ANILIST` | AniList | Manga, Comic, Book | GraphQL API, spin-off penalties, native `AniListId` mapping. |
| `BEDETHEQUE` | Bédéthèque | Comic | Franco-Belgian BD scraper, `curl_cffi` CSRF bypass. |
| `COMICVINE` | ComicVine | Comic | API Key required. Primary publisher weighting, Issue #1 fallback. |
| `GOOGLEBOOKS` | Google Books | Book, Comic | API Key required. Dynamic `langRestrict`, ISBN targeting. |
| `HARDCOVER` | Hardcover (Exp) | Book, Comic | API Key required. Hasura GraphQL API & Typesense search. |
| `KITSU` | Kitsu | Manga | JSON:API integration, no API key required. |
| `MANGANEWS` | Manga-News | Manga | VF French catalog scraper, extracts HD webp covers. |
| `MANGABAKA` | MangaBaka | Manga | Null-safe JSON parsing, Publisher Preference support. |
| `MANGADEX` | MangaDex | Manga | Content rating filters (`erotica`), oneshot penalties. |
| `MANGAUPDATES`| MangaUpdates | Manga | `hit_title` matching, Publisher Preference support. |
| `OPENLIBRARY` | Open Library | Book, Comic | ISBN support, anti-429 retries, Google Disclaimer bypass. |
| `SHIKIMORI` | Shikimori | Manga | Multilingual title matching, `/roles` staff extraction. |

---

### 8. Resilient Translation & Title Fallback
Translations are managed in `translator.py` with an auto-failover pipeline (Azure -> DeepL -> Google).
**Title Translation Fallback:** If a search query yields no results, MetaKavita can automatically translate the localized query to English (the pivot language for APIs like MangaDex and AniList) and run a second scraping cascade.

---

### 9. AI-Powered Scraper Creation (Vibecoding)
Creating a custom scraper requires strict adherence to the `BaseScraper` contract. 
Please refer to the `CUSTOM_SCRAPERS.md` file located at the root of the project for the exact "Vibecoding" AI Prompts to help the community build and sideload custom providers.

---

### 10. Quality Benchmarking & Debugging Suite
Developers can run standalone unit test scripts located at the project root (`debug_all_scrapers.py`, `debug_scoring_20.py`, `debug_manga_quality.py`) to validate engine features and API compliance without needing a running Kavita server. Cover uploads can be traced using `debug_cover.py`.

---

### 11. Critical Pitfalls & Contribution Workflow

This section codifies real production bugs found and fixed during deep audits of the codebase. Read it **before** modifying `app.py`, `kavita_api.py`, `db_manager.py`, or any scraper.

#### A. Docker-First Development — There Is No Hot-Reload
MetaKavita runs exclusively inside a Docker container (Gunicorn + Eventlet), with `data/` mounted as a persistent volume for `cache.db` and `config.json`. Editing a `.py` file on disk has **zero effect** until the image is rebuilt and the container restarted. The single most common cause of "I fixed it but it's still broken" reports is a stale image. Before investigating a regression that "should" already be resolved by a prior code change, always confirm the container was actually rebuilt.

#### B. Kavita's API Is Not a Typical REST API — Read `kavita_api.md` First
Before touching any code path that calls into `kavita_api.py`, read `kavita_api.md` end-to-end. Two rules are non-negotiable and have both caused real, user-facing production incidents:

1. **Never send a partial payload to `POST /api/Series/update`.** Kavita's `SeriesController`/`UpdateSeriesDto` has **no null-guard** on several fields — `localizedName` in particular. If your update logic only intends to change `format`, but omits `localizedName` from the JSON body, Kavita's C# backend deserializes the missing key as `null`, **overwrites** the existing value in the database, and additionally **resets** `nameLocked` / `sortNameLocked` / `localizedNameLocked` to `false` — even though those fields were never meant to be touched. This exact regression silently corrupted alternate titles for real users and crashed a third-party OPDS client (KOReader's "Kamare" plugin), which assumed `localizedName` would always be a string and choked on the resulting `null`. **The mandatory fix pattern:** always `GET /api/Series/{id}` first, merge your intended change into the *complete* current state, and only then `POST` the full object back. See `KavitaAPI.update_series_general()` for the reference implementation of this GET-merge-POST pattern.
2. **Sanitize GET-only / computed fields before every `POST`.** Properties like `created`, `lastModified`, `totalCount`, `maxCount`, `pages`, and `wordCount` are returned by Kavita's `GET` endpoints but must never be echoed back in a `POST` body — doing so risks triggering Entity Framework Core concurrency exceptions server-side. This sanitization is centralized **once** inside `KavitaAPI.update_series_metadata()`. Do not re-implement a partial version of it ad-hoc in `app.py` or inside a scraper — that exact kind of duplication (only stripping `created`/`lastModified` in one place while forgetting `maxCount`/`totalCount`) is how a `maxCount: -100000` payload once reached Kavita and crashed a sync.
3. **Respect the 2-pass Lock Guard protocol** (`Unlock → Write → Lock`, documented in `kavita_api.md` §1.B/1.C) whenever your code needs to overwrite a field the user may have manually locked in Kavita's UI.

#### C. Trace New Settings Through the *Entire* Chain, Not Just One File
The per-series Publisher Preference toggle (`VF/VA` vs `VO`, v1.5.7) shipped with fully correct code in the HTML template, the JS payload builder, both scrapers' extraction logic, *and* the SQLite schema — yet was completely inert in practice, because a single Flask route (`/save-override`) read the submitted value into a local variable and then simply never forwarded it to `save_forced_overrides()`. No single file was wrong in isolation; the bug only existed in the gap between files. **Whenever you add or touch a per-series or global setting, manually trace it end-to-end**: HTML input → `script.js` payload construction → Flask route parameter extraction → `db_manager.py` write → `db_manager.py` read → `existing_metadata` construction in `app.py` → scraper consumption. A fast way to catch this class of bug is to grep every call site of the persistence function (e.g. `save_forced_overrides(`) and diff the argument list against the function signature.

#### D. Centralize, Don't Duplicate, Sanitization & Mapping Logic
Several bugs in this codebase share the same root cause: a rule (a status enum mapping, a payload sanitization rule, a lock-flag convention) gets implemented once in a helper function, then partially re-implemented "just in case" in a caller, and the two definitions silently drift apart over time (e.g. MangaBaka's raw `"completed"` status never matching the internal `"FINISHED"` key expected by `app.py`). Prefer adding new logic exactly once — in `kavita_api.py` for anything Kavita-payload-shaped, or `scrapers/utils.py` for anything scraper-contract-shaped — and make every call site depend on that single source of truth instead of re-deriving it locally.

#### E. Testing Without a Live Kavita Instance
Use the standalone `debug_*.py` scripts at the project root to validate logic changes before touching a real server:
* `debug_all_scrapers.py` / `debug_scoring_20.py` / `debug_manga_quality.py`: scoring engine and scraper-contract regression tests.
* `debug_publisher.py`: dumps the raw `publishers` payload from the MangaBaka/MangaUpdates APIs and runs the `LOCALIZED`/`ORIGINAL` extraction logic side-by-side to verify the Publisher Preference feature.
* `debug_cover.py` / `debug_concurrency.py`: cover upload payload shape validation and cache race-condition checks.

When fixing a bug, extend one of these scripts (or add a new one) to reproduce it first — it's the fastest way to confirm a fix is real without a full Docker rebuild and manual click-through in the Kavita UI.

#### F. Documentation Is Part of the Change
Every user-facing fix or feature must be reflected in **both** `CHANGELOG.md` (bilingual EN/FR, semantically versioned — the topmost `## [X.Y.Z]` header is parsed automatically by `app.py::get_app_version()` to drive the version number shown in the UI) and `ROADMAP.md` (bilingual short-form `BFxx`/`Cxx` entries). Keep the two in sync: every `BF`/`C` number referenced in `ROADMAP.md`'s "Latest Releases" section should correspond to a detailed entry in `CHANGELOG.md`, and the version range shown at the top of that section should always match the newest `CHANGELOG.md` entry.

<br><br>

---

## 🇫🇷 Guide de Développement Français

### 1. Architecture Globale & Sécurité
MetaKavita est une application Python asynchrone fonctionnant derrière un serveur **WSGI Gunicorn** couplé à des workers **Eventlet** pour supporter les WebSockets en temps réel.

*   **Sécurité :** L'authentification utilise `secrets.compare_digest` contre les attaques temporelles. Les webhooks exigent un jeton cryptographique (`WEBHOOK_TOKEN`).
*   **Protection SSRF :** Le proxy d'images `/api/proxy-image` utilise une liste blanche dynamique qui protège automatiquement les scrapers communautaires ajoutés par les utilisateurs.
*   **Migrations SQLite Sécurisées :** Le `db_manager.py` met à jour les colonnes de la BDD une par une en interceptant silencieusement les erreurs `sqlite3.OperationalError` pour éviter les crashs de conteneur 500.
*   **Upload Kavita en Base64 Pur :** Le moteur C# de Kavita refuse les uploads d'images commençant par le schéma `Data URI`. L'envoi doit impérativement se faire en chaîne de caractères Base64 pure pour être écrit de manière permanente sur le disque dur.

---

### 2. Moteur de Throttling & Régulation Dynamique
Les pauses fixes ont été remplacées par un **Régulateur Dynamique par Horodatage (`LAST_REQUEST_TIMES`)**. Les API inactives répondent à 0.0s de délai, exécutant une fusion de 3 sources en ~1,6s. Lors d'un batch, le système régule parfaitement chaque source à sa vitesse maximale théorique (`rate_limit`).

---

### 3. Architecture Reverse Proxy & Sous-dossiers
Le système gère les sous-chemins (ex: `https://domaine.com/metakavita`) via `ProxyFix` pour récupérer les headers `X-Forwarded-Prefix` et un middleware `ScriptNameStripper`. Côté frontend, `window.ROOT_PATH` préfixe toutes les routes.

---

### 4. Mécanismes Frontend & Jetons WebSockets

#### A. WebSockets et Race Conditions
Le streaming de couvertures envoie les images au fil de l'eau. Pour éviter qu'un scraper lent d'une ancienne recherche ne vienne polluer une nouvelle recherche, le système génère un jeton chronologique `stream_id` pour chaque frappe. Le navigateur rejette silencieusement les images dont le jeton est périmé.

#### B. Verrouillage Anti-Écrasement
Appliquer une couverture manuellement via l'interface envoie un second signal AJAX qui décoche la case "Couverture" dans les options de la série. Cela protège la série en empêchant l'option globale `AUTO_COVER` de l'écraser lors des batchs ultérieurs.

---

### 5. Sideloading de Scrapers & Auto-Découverte

MetaKavita utilise un Registre à **Double Source**. Au démarrage, `importlib.util` est utilisé pour charger dynamiquement des classes héritant de `BaseScraper` situées dans :
1.  **Dossier Core :** `/app/scrapers/` (Code officiel).
2.  **Dossier Utilisateur :** `/app/data/scrapers/` (Sideloading communautaire).

Si le fichier déposé par un utilisateur déclare `needs_api_key = True`, MetaKavita va automatiquement générer le champ d'enregistrement dans l'Interface Graphique (UI) et gérer sa sauvegarde !

---

### 6. Extraction Profonde, QoS Éditeurs & Scoring

#### A. Extraction & Purge du Contexte (ISBN)
Avant de scraper, MetaKavita extrait silencieusement les données Kavita actuelles. Si l'utilisateur clique sur **Force Update + Reset Contexte**, MetaKavita purge totalement l'ISBN local. Puisque l'ISBN déclenche un match garanti à 100%, purger l'ISBN est le seul moyen de corriger une série victime de faux-positifs en boucle.

#### B. Matrice de Scoring Unifiée (`scrapers/utils.py`)
Les scrapers passent leurs résultats dans `score_candidate` :
1.  **Règle d'or de l'ISBN** : 100% de match.
2.  **Pénalité Anti-Homonyme** : Auteurs différents = `-50%`.
3.  **Filtres Spin-Offs** : Mots-clés manquants = `-35%`.
4.  **Ancrage Tome 1** : Bonus de `+0.10` pour le T1, et pénalité de `-0.45` sur les tomes intermédiaires.

#### C. Qualité de Service (QoS) : Éditeur
L'utilisateur peut imposer la récupération de l'éditeur traduit (ex: *Kurokawa*) ou de l'éditeur d'origine (ex: *Shueisha*). Ce paramètre est injecté localement via l'interrupteur UI directement dans `existing_metadata['publisher_pref']`.

---

### 7. Écosystème des Scrapers Actifs (V1.5.7)

| Identifiant | Nom Public | Spécificités & Fonctionnalités |
| :--- | :--- | :--- |
| `ANILIST` | AniList | API GraphQL, scoring des candidats contre les spin-offs. |
| `BEDETHEQUE` | Bédéthèque | Contournement CSRF `curl_cffi`, match exact de séries franco-belges. |
| `COMICVINE` | ComicVine | API Key. Recherche `filter=name:`, priorisation des éditeurs majeurs. |
| `GOOGLEBOOKS` | Google Books | API Key. Replis dynamiques par langue (`langRestrict`), ISBN. |
| `HARDCOVER` | Hardcover (Exp) | API Key. GraphQL Hasura + Moteur Typesense. |
| `KITSU` | Kitsu | JSON:API, rapide, sans clé requise. |
| `MANGANEWS` | Manga-News | Catalogue VF, extrait l'éditeur FR et les visuels HD (webp). |
| `MANGABAKA` | MangaBaka | Null-safe, support de la Préférence d'Éditeur. |
| `MANGADEX` | MangaDex | Filtres adultes (`erotica`), pénalités Oneshot. |
| `MANGAUPDATES`| MangaUpdates | Scraping par `hit_title`, support de la Préférence d'Éditeur. |
| `OPENLIBRARY` | Open Library | Clés Work (`OL...W`) & ISBNs, contournement Disclaimer Google Books. |
| `SHIKIMORI` | Shikimori | API Multilingue, extraction `/roles` du staff. |

---

### 8. Traduction Résiliente & Titre de Secours
Toutes les traductions sont gérées par `translator.py` avec bascule automatique en cas de quotas dépassés.
L'option **Titre de Secours (Fallback)** permet de traduire automatiquement le nom de l'œuvre (ex: *L'Attaque des Titans*) vers l'anglais pour relancer une seconde cascade de recherche sur les API internationales si la première échoue.

---

### 9. Création de Scrapers via IA (Vibecoding)
Pour permettre à la communauté de créer ses propres scrapers, veuillez vous référer au fichier **`CUSTOM_SCRAPERS.md`** situé à la racine du projet. Il contient le contrat absolu d'intégration et les Prompts IA ("Vibecoding") pour générer un scraper valide en 5 minutes.

---

### 10. Suite de Tests & Débogage Qualité
Des scripts de tests unitaires autonomes (`debug_all_scrapers.py`, `debug_scoring_20.py`, `debug_manga_quality.py`) permettent d'auditer 20 cas limites de scoring mathématique et les performances sans nécessiter d'instance Kavita. L'envoi physique d'image peut être traqué via `debug_cover.py`.

---

### 11. Pièges Critiques & Flux de Contribution

Cette section formalise des bugs réels de production identifiés et corrigés lors d'audits approfondis du code. À lire **avant** de modifier `app.py`, `kavita_api.py`, `db_manager.py`, ou un scraper.

#### A. Développement "Docker-First" — Pas de Hot-Reload
MetaKavita s'exécute exclusivement dans un conteneur Docker (Gunicorn + Eventlet), avec `data/` monté en volume persistant pour `cache.db` et `config.json`. Modifier un fichier `.py` sur le disque n'a **strictement aucun effet** tant que l'image n'a pas été reconstruite et le conteneur redémarré. La cause la plus fréquente d'un "j'ai corrigé mais ça ne marche toujours pas" est une image Docker obsolète. Avant d'enquêter sur une régression qui "devrait" déjà être résolue par un correctif précédent, vérifiez toujours que le conteneur a bien été reconstruit.

#### B. L'API Kavita N'est Pas une API REST Classique — Lire `kavita_api.md` en Priorité
Avant de toucher à un chemin de code qui appelle `kavita_api.py`, lisez intégralement `kavita_api.md`. Deux règles sont non négociables et ont chacune provoqué un incident réel côté utilisateur :

1. **Ne jamais envoyer de payload partiel à `POST /api/Series/update`.** Le `SeriesController`/`UpdateSeriesDto` de Kavita n'a **aucune protection contre les valeurs nulles** sur plusieurs champs — notamment `localizedName`. Si votre logique de mise à jour ne vise à changer que `format` mais omet `localizedName` du corps JSON, le backend C# de Kavita désérialise la clé manquante en `null`, **écrase** la valeur existante en base, et **réinitialise en plus** `nameLocked` / `sortNameLocked` / `localizedNameLocked` à `false` — alors même que ces champs n'étaient pas censés être touchés. Cette régression exacte a silencieusement corrompu les titres alternatifs d'utilisateurs réels et fait planter un client OPDS tiers (l'extension "Kamare" de KOReader), qui supposait que `localizedName` serait toujours une chaîne de caractères et s'est bloqué sur le `null` résultant. **Le motif de correction obligatoire :** toujours faire un `GET /api/Series/{id}` en premier, fusionner le changement voulu dans l'état actuel *complet*, puis seulement ensuite renvoyer l'objet entier en `POST`. Voir `KavitaAPI.update_series_general()` pour l'implémentation de référence de ce motif GET-fusion-POST.
2. **Assainir les champs GET-uniquement / calculés avant chaque `POST`.** Des propriétés comme `created`, `lastModified`, `totalCount`, `maxCount`, `pages` et `wordCount` sont renvoyées par les endpoints `GET` de Kavita mais ne doivent jamais être réinjectées dans un corps `POST` — cela risque de déclencher des exceptions de concurrence d'état côté Entity Framework Core. Cet assainissement est centralisé **une seule fois** dans `KavitaAPI.update_series_metadata()`. Ne réimplémentez pas une version partielle de cette logique dans `app.py` ou dans un scraper — c'est exactement ce type de duplication (ne retirer que `created`/`lastModified` à un endroit en oubliant `maxCount`/`totalCount`) qui a un jour laissé passer un payload `maxCount: -100000` vers Kavita et fait planter une synchronisation.
3. **Respecter le protocole de verrouillage à 2 passages** (`Unlock → Write → Lock`, documenté dans `kavita_api.md` §1.B/1.C) chaque fois que votre code doit écraser un champ que l'utilisateur a pu verrouiller manuellement dans l'interface de Kavita.

#### C. Tracer un Nouveau Réglage sur *Toute* la Chaîne, Pas Seulement un Fichier
L'interrupteur de Préférence d'Éditeur par série (`VF/VA` vs `VO`, v1.5.7) a été livré avec un code entièrement correct dans le template HTML, la construction du payload JS, la logique d'extraction des deux scrapers, *et* le schéma SQLite — et pourtant il n'avait strictement aucun effet en pratique, car une seule route Flask (`/save-override`) lisait la valeur soumise dans une variable locale puis oubliait tout simplement de la transmettre à `save_forced_overrides()`. Aucun fichier n'était fautif isolément ; le bug n'existait que dans l'interstice entre les fichiers. **Chaque fois que vous ajoutez ou modifiez un réglage par série ou global, tracez-le manuellement de bout en bout** : champ HTML → construction du payload dans `script.js` → extraction du paramètre dans la route Flask → écriture dans `db_manager.py` → lecture dans `db_manager.py` → construction de `existing_metadata` dans `app.py` → consommation par le scraper. Un moyen rapide de détecter cette classe de bug consiste à rechercher tous les appels de la fonction de persistance (ex : `save_forced_overrides(`) et à comparer la liste d'arguments avec la signature de la fonction.

#### D. Centraliser, Ne Pas Dupliquer, la Logique d'Assainissement et de Mapping
Plusieurs bugs de ce code partagent la même cause racine : une règle (un mapping d'énumération de statut, une règle d'assainissement de payload, une convention de verrou) est implémentée une fois dans une fonction utilitaire, puis partiellement réimplémentée "par précaution" dans un appelant, et les deux définitions divergent silencieusement avec le temps (ex : le statut brut `"completed"` de MangaBaka qui ne correspondait jamais à la clé interne `"FINISHED"` attendue par `app.py`). Privilégiez l'ajout d'une nouvelle règle à un seul endroit — dans `kavita_api.py` pour tout ce qui concerne le format des payloads Kavita, ou `scrapers/utils.py` pour tout ce qui concerne le contrat des scrapers — et faites dépendre chaque site d'appel de cette source unique de vérité plutôt que de la redériver localement.

#### E. Tester Sans Instance Kavita en Ligne
Utilisez les scripts autonomes `debug_*.py` à la racine du projet pour valider un changement de logique avant de toucher un vrai serveur :
* `debug_all_scrapers.py` / `debug_scoring_20.py` / `debug_manga_quality.py` : tests de non-régression du moteur de scoring et du contrat des scrapers.
* `debug_publisher.py` : extrait le payload brut `publishers` des API MangaBaka/MangaUpdates et exécute la logique d'extraction `LOCALIZED`/`ORIGINAL` en parallèle pour vérifier la fonctionnalité de Préférence d'Éditeur.
* `debug_cover.py` / `debug_concurrency.py` : validation du format du payload d'upload de couverture et détection des races conditions du cache.

Lors de la correction d'un bug, étendez l'un de ces scripts (ou créez-en un nouveau) pour le reproduire d'abord — c'est le moyen le plus rapide de confirmer qu'un correctif fonctionne réellement, sans reconstruction Docker complète ni parcours manuel dans l'interface Kavita.

#### F. La Documentation Fait Partie du Correctif
Chaque correctif ou fonctionnalité visible par l'utilisateur doit être répercuté à la fois dans `CHANGELOG.md` (bilingue EN/FR, versionné sémantiquement — le premier en-tête `## [X.Y.Z]` est analysé automatiquement par `app.py::get_app_version()` pour piloter le numéro de version affiché dans l'UI) et dans `ROADMAP.md` (entrées courtes bilingues `BFxx`/`Cxx`). Gardez les deux synchronisés : chaque numéro `BF`/`C` référencé dans la section "Dernières Nouveautés" de `ROADMAP.md` doit correspondre à une entrée détaillée dans `CHANGELOG.md`, et la plage de versions affichée en haut de cette section doit toujours correspondre à la plus récente entrée de `CHANGELOG.md`.