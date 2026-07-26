# 🚀 MetaKavita - Roadmap & To-Do List

**Concept:** Metadata scraping and enrichment tool for Kavita (alternative to Komf), designed for lightweight, self-hosted deployment.
**Philosophy:** Lightweight, pragmatic, highly secure, and optimized for Manga, Comics & Literature.

---

## Sommaire / Table of Contents
1. [🇺🇸 English Roadmap](#-english-roadmap)
2. [🇫🇷 Feuille de Route Française](#-feuille-de-route-française)

---

## 🇺🇸 English Roadmap

### 🔮 Backlog & Future Features (To-Do)
- [ ] **C29. Interactive Manual Batch Mode (QoS):** Add an "Automatic / Manual (QoS)" toggle for batch processing.
    - In Manual mode, the backend queries metadata providers and emits candidate choices over WebSockets.
    - The frontend opens an interactive selection modal and pauses the worker using `eventlet.event.Event`.
    - The user selects the exact match or skips, sending the decision back to resume the queue.
- [ ] **C30. Francophone Book Scrapers:** Integrate dedicated French literature sources (Babelio, SensCritique) without requiring API keys.
- [ ] **C31. Kavita Deduplication Tool:** Dedicated UI panel to detect and merge duplicate series or volumes in Kavita.
- [ ] **C33. Browser Extension "MetaKavita Companion":** Floating widget overlay directly on top of the Kavita Web UI to trigger MetaKavita updates natively.
- [ ] **C35. Native "Comic (Flexible)" Support:** Build a dedicated hybrid cascade for Kavita's Library Type ID 5. Currently, it defaults to Comic or Manga behavior, but it should inherently support querying Comic providers first, then gracefully falling back to Manga providers if no matches are found.
- [ ] **C7. Playful Statistics Dashboard (B12):** Display fun metrics on the `/stats` page, such as estimated time saved, estimated DeepL Translation costs avoided, and provider usage charts.
- [ ] **C8. Resiliency & Rate-Limiting Control:** Add an automatic exponential backoff retry mechanism to prevent API blocks (429 errors) during very large batches.
- [ ] **C39. Offline Scraper Mode (Local DB / Dumps):** Create a metadata provider capable of querying a local database export (e.g., massive SQLite/JSON dumps from AniList or OpenLibrary). Enables lightning-fast, 100% private enrichment without internet connectivity and absolute immunity to API rate-limiting.
- [ ] **C40. Support the Developer (Donations):** Add a non-intrusive "Buy Me a Coffee" or "Ko-fi" link in the GitHub README and the application's sidebar footer to allow the community to support the project.

---

### ✨ Latest Releases (v1.5.6 to v1.6.0)
- [x] **C32. Flask Blueprints Refactoring (v1.6.0):** Modularized the former monolithic `app.py` into Blueprints under `routes/`, plus `services/`, `models.py`, and a thin composition root.
- [x] **C45. Smart Scoring (v1.6.0):** Score-based provider winner selection + two-wave parallel execution (`SMART_SCORING` sidebar toggle), with community-scraper opt-in/`_safe_match_score` hardening.
- [x] **C46. CORS Allowed Origins (v1.6.0):** Docker env `CORS_ALLOWED_ORIGINS` (CSV explicit origins) for Flask HTTP + Socket.IO behind Traefik/HTTPS self-hosts.
- [x] **C48. KAVITA_EXTERNAL_URL (v1.6.0):** Separate public Kavita URL for browser UI links vs internal `KAVITA_URL` for Docker API calls (thanks LazyGeniusMan).
- [x] **BF19. Kavita Write Timeout & False-Negative RE-LOCK (v1.6.0):** Configurable `KAVITA_HTTP_TIMEOUT` (default 60s) for write POSTs; metadata/general 2-pass treats write-OK + RE-LOCK failure as soft success; one capped RE-LOCK-only retry (issue SqueezedByte).
- [x] **C49. Configurable MAX_TAGS (v1.6.0):** Env/`config.json` cap on tags written to Kavita (default 15, range 1–100); scrapers + enrichment use `get_max_tags()` — no UI (feedback LazyGeniusMan).
- [x] **BF20–BF41 + C50. Application Audit Hardening (v1.6.0):** Critical/High/Medium plus Low polish (no hardcoded SECRET_KEY fallback, API key not logged, ComicVine proxy_domains narrowed, `MAX_GENRES` / `get_max_genres()`). Optional empty `ADMIN_PASSWORD` left intentional.
- [x] **C51. Configurable MAX_GENRES (v1.6.0):** Env/`config.json` cap on genres (default 5, range 1–50); dynamic-list scrapers + `enrichment_engine` use `get_max_genres()` — no UI. Homogenized with AniList tags / MangaUpdates categories under `MAX_TAGS`.
- [x] **C52. Topbar Help Menu — About & Documentation (v1.6.0):** Help dropdown with About modal, GitHub doc links, changelog shortcut; Kavita+ support positioning (About copy + topbar Kavita+ beside BMC → instance `settings#admin-kavitaplus`).
- [x] **BF42–BF45. Post-Audit Follow-ups (v1.6.0):** Credential-safe exception logging; safe cover redirects + CDN `proxy_domains`; private IP block in `url_allowlist`; Escape closes changelog; CODE_REVIEW MAL/Nautiljon cleanup.
- [x] **C53. Localized Titles Policy (v1.6.0, issue #12):** Global `LOCALIZED_TITLE_MODE`/`LANGS` + per-series `alt_title_langs` for Kavita `localizedName` only (never rewrite `name`); structured `titles[]` on AniList/MangaDex/Kitsu; default remains multi-title `" / "` join.
- [x] **C47. MangaBaka Book/LN + API Hardening (v1.6.0):** Official MangaBaka Book support with `schema=full`, `type=novel` filter, and related parsing fixes (thanks LazyGeniusMan).
- [x] **BF18. Per-Series Publisher Preference Never Saved (v1.6.0):** The `/save-override` endpoint read the per-series Publisher toggle (`Auto`/`VF/VA`/`VO`) but never forwarded it to the database, silently resetting it to `GLOBAL` on every save. The per-series preference is now correctly persisted and respected by the scrapers.
- [x] **BF14. LocalizedName Corruption & KOReader/Kamare Crash Fix (v1.5.8):** `update_series_general()` now always fetches a series' full current state before writing, preventing Kavita from silently nulling `LocalizedName` and force-unlocking `NameLocked`/`SortNameLocked`/`LocalizedNameLocked` on partial updates (e.g. format-only). Root cause of a reported KOReader "Kamare" plugin crash.
- [x] **BF15. Metadata System-Field Leak (v1.5.8):** Centralized sanitization of GET-only computed fields (`totalCount`, `maxCount`, `pages`, `wordCount`) inside `update_series_metadata()`, preventing them from being echoed back into `POST /api/Series/metadata` and risking EF Core concurrency exceptions.
- [x] **BF16. MangaBaka "Completed" Status Mapping (v1.5.8):** Fixed MangaBaka's raw `completed` status never matching MetaKavita's internal `FINISHED` status key, which left completed series silently stuck as "Ongoing" in Kavita.
- [x] **BF17. `BaseScraper` Attribute Typo (v1.5.8):** Corrected `eeds_api_key` to `needs_api_key` on the base scraper class default attribute.
- [x] **C41. Community Scrapers Sideloading (v1.5.7):** MetaKavita now dynamically loads external Python scrapers dropped directly into the user-mapped `data/scrapers/` folder.
- [x] **C42. Publisher Localization Preference (v1.5.7):** Added an elegant per-series segmented toggle (`Auto` | `VF/VA` | `VO`) to let users prioritize Localized/Translated publishers or Original publishers.
- [x] **C15. Title Translation Fallback (v1.5.7):** Experimental safety net that automatically translates unfound localized titles to English to perform a second search pass. Highly useful for massive blind batches.
- [x] **C43. Bulletproof SQLite Schema Migrations (v1.5.7):** Rewrote the database initialization logic (`_ensure_schema`) to gracefully handle column additions one by one without container crashes.
- [x] **C44. Custom Scraper Guide & Vibecoding (v1.5.7):** Released `CUSTOM_SCRAPERS.md` containing strict integration rules and ready-to-use AI Prompts to help users generate their own scrapers.
- [x] **BF10. Pure Base64 Cover Payload (v1.5.6):** Fixed the "Phantom Cover" syndrome where Kavita silently rejected `Data URI` image payloads. Reverted to pure Base64 strings for permanent disk writes.
- [x] **BF11. WebSocket Race Condition & Priority (v1.5.6):** Implemented a `stream_id` token system for live cover streaming and restored manual input priority in the cover modal.
- [x] **BF12. Smart Auto-Cover Locking (v1.5.6):** Manually applying a cover from the modal now automatically unchecks the "Cover" targeted field to protect it from background sync overwrites.
- [x] **BF13. True Context Reset (ISBN Purge) (v1.5.6):** Fixed a critical oversight where forcing an update with "Context Reset" still retained the Kavita ISBN, causing persistent false-positive matches. The ISBN is now properly purged to guarantee a true clean slate.

---

### 📦 Archive: Advanced Features & Core Architecture (V1.5.0+)
- [x] **C1. MyAnimeList (MAL) Scraper:** Integrated the public and free Jikan API v4.
- [x] **C2. MangaDex Scraper:** Integrated the official MangaDex REST API v5 for rich metadata tags, content rating filters, and candidate weighting.
- [x] **C3. Baka-Updates (MangaUpdates) Scraper:** Integrated the v1 REST API to retrieve associated alternative titles and keyword penalty scoring.
- [x] **C4. Kitsu Scraper:** Add Kitsu JSON:API as a reliable global fallback source.
- [x] **C5. Manga-News Scraper:** Implemented `curl_cffi` scraping of the French licensing catalog.
- [x] **C6. Scraper Bedethèque:** Scraping BeautifulSoup4 for Franco-Belgian comics.
- [x] **C23. Shikimori Scraper:** Integrated Shikimori REST JSON API with native `MalId` mapping.
- [x] **C24. Open Library Scraper:** Integrated Open Library / Internet Archive API for literature with anti-429 rate-limiting retries.
- [x] **C16. Hardcover Scraper:** Integrated the Hardcover Hasura GraphQL & Typesense endpoints.
- [x] **C6. Western Comics & Books Support (B10):** Integrated Google Books API as production-ready scrapers for Novels.
- [x] **C14. Context-Aware Cover Search:** Dynamically filter the queried providers inside the manual cover selection modal based on the Kavita `libraryType`. 
- [x] **C17. Reverse Proxy & Subpath Support:** Introduced `ROOT_PATH` environment variable and WSGI middleware.
- [x] **C18. The "Magic Input" (Smart URL Routing):** Replaced static ID fields with a universal URL/ID parser.
- [x] **C19. Granular Scraping (Targeted Fields):** Built UI and backend support to individually toggle 12 Kavita metadata fields.
- [x] **C20. Self-Healing Configuration Engine:** Dynamic validation of search cascades.
- [x] **C21. Smart ID Match Engine:** Implemented a title similarity validation engine (>50% ratio threshold).
- [x] **C22. Extended Kavita API Mapping:** Added Editors, Letterers, Inkers, and Localized Language.
- [x] **C25. Live WebSocket Cover Streaming (*Progressive Loading*):** Real-time Socket.IO streaming of manual cover search results.
- [x] **C26. Smart Ignored & Amnesties Expansion:** Override `IGNORED` status for explicitly checked batch items, and reset both `NOT_FOUND` and `IGNORED` via the Amnesties button.
- [x] **C28. Kavita Deep Metadata Extraction & Unified Scoring:** Pre-fetch existing file-level metadata (`authors`, `isbn`) from Kavita to anchor a centralized scoring matrix.
- [x] **C34. Smart Per-Provider Rate Limiter & Dynamic Throttling:** Replaced hardcoded worker delays with a timestamp-based throttler (`LAST_REQUEST_TIMES`).
- [x] **C36. Quality Benchmarking & Unit Testing Suite:** Created standalone diagnostic test scripts to stress-test 20 scoring edge cases.
- [x] **C37. ComicVine Overhaul & Issue #1 Fallback:** Switched to structured `/volumes/?filter=name:` search prioritizing primary US/European publishers.
- [x] **C38. Unrestricted Provider Forcing:** Unlocked all registered scrapers in the Magic Input dropdown.
- [x] **C9. Resilient Multi-API Translator:** Dedicated translation module combining Microsoft Azure Translator and DeepL.
- [x] **C10. Dynamic Library Routing & Factory Pattern:** Automatic extraction of Kavita library types.
- [x] **C11. Hybrid ComicVine Scraper:** Built a two-step lookup cascade mapping individual album titles and resolving parent volumes.
- [x] **C12. Contextual Title Cleaning:** Tailored query cleaning logic based on targeted media type.
- [x] **C13. Provider Purge (Nautiljon):** Completely removed Nautiljon from the default routing map due to abusive Cloudflare IP bans.

### 🐛 Archive: Bug Fixes & Architecture Shifts (V1.4.x / V1.5.x)
- [x] **BF1. Admin Password Env Var Override Bug:** Resolved the issue where clearing the admin password via `docker-compose.yml` failed.
- [x] **BF2. Permanent Auth Cookie Cleansing:** Ensured a hard logout completely destroys the long-lived session cookie via `expires=0`.
- [x] **BF3. Bédéthèque Spin-off Override Bug**: Fixed an issue where searching for a main series would return covers from its spin-offs due to alphabetical sorting.
- [x] **BF4. Context-Aware Cover Fetching**: Fixed a regression where the manual cover search queried all scrapers blindly.
- [x] **BF5. Publisher Metadata Parsing Fix:** Corrected an oversight where publisher metadata wasn't properly scraped.
- [x] **BF6. Disable Translation Option:** Added a configuration setting (`NONE`) to disable the translation pipeline.
- [x] **BF7. Global App Version Jinja Context:** Render `app_version` directly from `CHANGELOG.md` in the UI.
- [x] **BF8. Dynamic API Key Engine:** `BaseScraper` now supports `needs_api_key=True` to auto-generate forms dynamically.
- [x] **BF9. Decentralized Translations (i18n):** Scrapers now encapsulate their own translations via `self.t()`.

### 🏗️ Archive: Ergonomics & Interface Overhaul (V1.4.0)
- [x] **B1 to B6:** Mapped Genres, Tags, localized titles, and extended staff metadata (Writers, Pencillers, Colorists, Translators, Cover Artists) pushing to Kavita.
- [x] **B7 to B9:** "Ignored" series state, Auto-Sync Polling, Smart Fallback Routing, and Data Fusion (Smart Completion).
- [x] **B11. Global Authentication:** UI locking via `ADMIN_PASSWORD` container variable.
- [x] **B14 to B15:** Advanced Cover Selection Modal & MangaBaka V2 API.
- [x] **B16. Ultimate Regex Title Cleaner:** Decentralized `clean_title()` logic.
- [x] **B17. Real-Time AJAX Search Bar:** Instant client-side filtering without reload.
- [x] **B18. Extended Metadata Mapping:** Publishers, Age Ratings, and Origin-based Auto-Reading direction.
- [x] **B19. External IDs & WebLinks:** Automatic mapping of native IDs and clickable direct WebLinks.
- [x] **B20. Split UI Architecture:** Moved all technical config inputs to an Admin Modal.
- [x] **B21. Manual Cover Search:** Enter custom queries directly inside the cover modal.
- [x] **B22. Live Processing Tracker (Pulsing Glow):** Automatically flashes the active sync item in purple (`.is-processing`).
- [x] **B23. AniList Quick Lookup:** Magnolia button to open pre-filled searches on AniList.
- [x] **B24. Persistent Workspace:** Automatically saves active library, status filter, hide ignored state, and search query.

### 🛠️ Archive: Foundations & Security (V1.3+)
- [x] **A1 to A6:** Secure API integration, Live Logs, 100% AJAX, Global Translation bridges, Responsive UI.
- [x] **A7 to A9:** Self-cleaning SQLite cache, explicit connection error indicators, Zero-Setup deployment.
- [x] **A10. Production WSGI Server:** Eventlet + Gunicorn asynchronous stack.
- [x] **A11. Global Security:** SSRF Protection on Image Proxy, Timing-Attack immune authentication (`secrets.compare_digest`), HttpOnly Session cookies, hidden API keys in DOM, Token-protected webhooks.

<br><br>

---

## 🇫🇷 Feuille de Route Française

### 🔮 Backlog & Fonctionnalités Futures (À Faire)
- [ ] **C29. Mode Batch Manuel Interactif (QoS) :** Ajouter un sélecteur "Automatique / Manuel (QoS)" pour les traitements par lots.
    - En mode Manuel, le backend récupère les candidats et les envoie via WebSockets.
    - Le frontend affiche une modale de choix et met le worker en pause via `eventlet.event.Event`.
    - L'utilisateur valide le bon résultat ou passe, débloquant le worker pour le fichier suivant.
- [ ] **C30. Scrapers Littéraires Francophones :** Intégrer des sources spécialisées en littérature française (Babelio, SensCritique) sans clé API.
- [ ] **C31. Outil de Déduplication Kavita :** Panneau UI pour détecter et fusionner les doublons dans Kavita.
- [ ] **C33. Extension Navigateur "MetaKavita Companion" :** Widget flottant en surcouche directement sur l'interface Web de Kavita pour déclencher les mises à jour MetaKavita nativement.
- [ ] **C35. Support natif du type "Comic (Flexible)" :** Créer une cascade hybride dédiée pour le type de bibliothèque ID 5 de Kavita. Actuellement, MetaKavita le traite comme un Comic ou un Manga strict, mais il devrait pouvoir interroger les sites de Comics puis basculer intelligemment sur les sites de Mangas en cas d'échec pour refléter la nature "flexible" du dossier.
- [ ] **C7. Tableau de bord Statistiques ludique (B12) :** Ajout de métriques sur la page `/stats` (estimation du temps de recherche épargné, équivalent en euros économisé sur DeepL, graphiques de répartition par scrapers).
- [ ] **C8. Gestion de la Résilience d'API :** Système de retry automatique avec attente exponentielle pour contourner le rate limiting lors des très gros batchs.
- [ ] **C39. Mode Scraper Hors-Ligne (Local DB / Dumps) :** Création d'un fournisseur de métadonnées interrogeant un export massif de base de données local (ex: dump SQLite/JSON d'AniList ou OpenLibrary). Permet un enrichissement ultra-rapide, 100% privé, sans connexion Internet et totalement immunisé contre le Rate-Limiting.
- [ ] **C40. Soutien au développeur (Dons) :** Ajouter un lien discret "Buy Me a Coffee" ou "Ko-fi" dans le README GitHub et le pied de page de l'interface pour permettre à la communauté de soutenir le projet.

---

### ✨ Dernières Nouveautés (v1.5.6 à v1.6.0)
- [x] **C32. Refonte Flask Blueprints (v1.6.0) :** Découpage de l'ancien `app.py` monolithique en Blueprints `routes/`, plus `services/`, `models.py`, et un point d'assemblage mince.
- [x] **C45. Smart Scoring (v1.6.0) :** Sélection du vainqueur par score + exécution en deux vagues (`SMART_SCORING`), avec opt-in scrapers communautaires / filet `_safe_match_score`.
- [x] **C46. Origins CORS autorisées (v1.6.0) :** Variable Docker `CORS_ALLOWED_ORIGINS` (CSV) pour Flask HTTP + Socket.IO derrière Traefik/HTTPS.
- [x] **C48. KAVITA_EXTERNAL_URL (v1.6.0) :** URL publique Kavita séparée pour les liens UI, vs `KAVITA_URL` interne pour les appels API Docker (merci LazyGeniusMan).
- [x] **BF19. Timeout d'écriture Kavita & faux négatif RE-LOCK (v1.6.0) :** `KAVITA_HTTP_TIMEOUT` configurable (défaut 60s) ; soft-success si écriture OK mais RE-LOCK échoue ; un retry plafonné du seul RE-LOCK (issue SqueezedByte).
- [x] **C49. MAX_TAGS configurable (v1.6.0) :** Plafond env/`config.json` des tags écrits dans Kavita (défaut 15, borné 1–100) ; scrapers + enrichissement via `get_max_tags()` — pas d'UI (retour LazyGeniusMan).
- [x] **BF20–BF41 + C50. Durcissement suite audit applicatif (v1.6.0) :** Critical/High/Medium + Low polish (plus de fallback SECRET_KEY hardcodé, clé API non loguée, proxy_domains ComicVine restreint, `MAX_GENRES` / `get_max_genres()`). `ADMIN_PASSWORD` vide laissé volontaire.
- [x] **C51. MAX_GENRES configurable (v1.6.0) :** Plafond env/`config.json` des genres (défaut 5, borné 1–50) ; scrapers à listes dynamiques + `enrichment_engine` via `get_max_genres()` — pas d'UI. Homogénéisé avec tags AniList / categories MangaUpdates sous `MAX_TAGS`.
- [x] **C52. Menu Aide topbar — À propos & Documentation (v1.6.0) :** menu Aide avec modal À propos, liens docs GitHub, raccourci nouveautés ; positionnement Kavita+ (texte À propos + bouton topbar à côté du café → `settings#admin-kavitaplus` de l’instance).
- [x] **BF42–BF45. Suivi post-audit (v1.6.0) :** logs sans fuite de clés ; redirects couverture + CDN ; blocage IPs privées ; Escape ferme le changelog ; CODE_REVIEW MAL/Nautiljon.
- [x] **C53. Politique des titres localisés (v1.6.0, issue #12) :** `LOCALIZED_TITLE_MODE`/`LANGS` globaux + `alt_title_langs` par série pour Kavita `localizedName` uniquement (jamais de réécriture de `name`) ; `titles[]` structurés AniList/MangaDex/Kitsu ; défaut = jointure multi-titres `" / "`.
- [x] **C47. MangaBaka Book/LN + Durcissement API (v1.6.0) :** Support Book officiel MangaBaka avec `schema=full`, filtre `type=novel`, et correctifs de parsing (merci LazyGeniusMan).
- [x] **BF18. Préférence d'Éditeur par Série Jamais Sauvegardée (v1.6.0) :** L'endpoint `/save-override` lisait bien l'interrupteur d'Éditeur par série (`Auto`/`VF/VA`/`VO`) mais ne le transmettait jamais à la base de données, le réinitialisant silencieusement à `GLOBAL` à chaque sauvegarde. La préférence par série est désormais correctement persistée et respectée par les scrapers.
- [x] **BF14. Correction Corruption LocalizedName & Crash KOReader/Kamare (v1.5.8) :** `update_series_general()` récupère désormais systématiquement l'état complet de la série avant d'écrire, empêchant Kavita d'effacer silencieusement `LocalizedName` et de déverrouiller de force `NameLocked`/`SortNameLocked`/`LocalizedNameLocked` lors de mises à jour partielles (ex: changement du seul format). Cause racine d'un crash signalé sur l'extension KOReader "Kamare".
- [x] **BF15. Fuite de Champs Système dans les Métadonnées (v1.5.8) :** Centralisation de l'assainissement des champs calculés en lecture seule (`totalCount`, `maxCount`, `pages`, `wordCount`) dans `update_series_metadata()`, évitant leur réinjection dans `POST /api/Series/metadata` et le risque d'exceptions de concurrence Entity Framework Core.
- [x] **BF16. Mapping du Statut "Terminé" MangaBaka (v1.5.8) :** Correction du statut brut `completed` de MangaBaka qui ne correspondait jamais à la clé interne `FINISHED`, laissant les séries terminées silencieusement bloquées en "En cours" dans Kavita.
- [x] **BF17. Typo d'Attribut `BaseScraper` (v1.5.8) :** Correction de `eeds_api_key` en `needs_api_key` sur l'attribut par défaut de la classe de base des scrapers.
- [x] **C41. Scrapers Communautaires Sideloadés (v1.5.7) :** Chargement dynamique des scripts Python déposés dans le volume utilisateur `data/scrapers/`. Permet d'ajouter des sites à la volée sans recompiler l'image Docker.
- [x] **C42. Préférence d'Éditeur (v1.5.7) :** Ajout d'un interrupteur segmenté par série (`Auto` | `VF/VA` | `VO`) pour prioriser l'éditeur localisé (ex: *Glénat*) ou l'éditeur d'origine (ex: *Shueisha*).
- [x] **C15. Titre de Secours (Fallback Expérimental) (v1.5.7) :** Filet de sécurité traduisant automatiquement un titre non-trouvé vers l'anglais pour relancer une seconde recherche sur les API.
- [x] **C43. Migrations SQLite Sécurisées (v1.5.7) :** Initialisation robuste (`_ensure_schema`) ajoutant les colonnes manquantes sans provoquer de crash HTTP 500.
- [x] **C44. Guide Scrapers & Vibecoding (v1.5.7) :** Publication de `CUSTOM_SCRAPERS.md` incluant les règles d'intégration et les Prompts IA prêts à l'emploi.
- [x] **BF10. Payload Base64 Pur (v1.5.6) :** Résolution du bug des "couvertures fantômes" où Kavita rejetait les images *Data URI*. Envoi en Base64 pur pour forcer l'écriture permanente sur le disque dur.
- [x] **BF11. Priorité & Race Condition WebSockets (v1.5.6) :** Ajout d'un jeton `stream_id` pour le chargement des couvertures et restauration de la priorité du texte saisi manuellement dans la modal.
- [x] **BF12. Verrouillage Anti-Écrasement (v1.5.6) :** Appliquer une couverture manuellement décoche désormais automatiquement le champ "Couverture" de la série pour la protéger contre les futures synchronisations.
- [x] **BF13. Véritable Purge du Contexte (ISBN) (v1.5.6) :** Correction critique purgeant réellement l'ISBN lors d'une réinitialisation de contexte pour éviter les boucles de faux-positifs lors du forçage de métadonnées.

---

### 📦 Archives : Scrapers Cibles & Nouvelles Fonctionnalités (V1.5.0+)
- [x] **C1. Scraper MyAnimeList (MAL) :** Intégration de l'API publique et gratuite Jikan v4.
- [x] **C2. Scraper MangaDex :** Intégration de l'API REST officielle MangaDex v5.
- [x] **C3. Scraper Baka-Updates (MangaUpdates) :** Exploitation de l'API REST v1.
- [x] **C4. Scraper Kitsu :** Ajout de la source Kitsu comme repli international rapide.
- [x] **C5. Scraper Manga-News :** Scraping `curl_cffi` du catalogue VF.
- [x] **C6. Scraper Bédéthèque :** Scraping BeautifulSoup4 optimisé pour la bande dessinée franco-belge.
- [x] **C23. Scraper Shikimori :** API REST JSON avec évaluation multilingue.
- [x] **C24. Scraper Open Library :** API Internet Archive pour les romans, livres et BDs.
- [x] **C16. Scraper Hardcover :** Intégration des terminaux GraphQL Hasura & Typesense.
- [x] **C6. Support des BD Occidentales & Romans (B10) :** Intégration de l'API Google Books.
- [x] **C14. Recherche de Couvertures Contextuelle :** Filtrer dynamiquement les fournisseurs interrogés dans la modal selon le type de bibliothèque Kavita.
- [x] **C17. Support Reverse Proxy & Subpath :** Ajout de la variable `ROOT_PATH` et d'un middleware WSGI.
- [x] **C18. Le "Champ Magique" (Routage URL Intelligent) :** Remplacement de l'ancien champ d'ID par un analyseur universel d'URL/ID.
- [x] **C19. Scraping Granulaire (Champs Ciblés) :** Prise en charge du ciblage individuel des 12 champs de métadonnées.
- [x] **C20. Auto-Réparation de la Configuration (Self-Healing) :** Validation dynamique des cascades de recherche.
- [x] **C21. Moteur Smart ID Match :** Validateur par similarité de titre (>50%).
- [x] **C22. Mappage API Kavita Étendu :** Ajout des Éditeurs (Staff), Lettreurs, Encreurs et de la Langue native.
- [x] **C25. Streaming de Couvertures par WebSockets (*Progressive Loading*) :** Envoi en direct au fil de l'eau via Socket.IO des images.
- [x] **C26. Forçage des Ignorés & Amnesties Élargies :** Traitement des séries ignorées cochées en batch et réinitialisation conjointe de `NOT_FOUND` et `IGNORED`.
- [x] **C28. Extraction Profonde des Métadonnées Kavita & Scoring Unifié :** Pré-récupérer les métadonnées existantes (`auteurs`, `ISBN`) avant le scraping.
- [x] **C34. Rate-Limiter Intelligente & Throttling Dynamique :** Remplacement des pauses fixes par un régulateur par horodatage (`LAST_REQUEST_TIMES`).
- [x] **C36. Suite de Tests & Benchmarks Qualité :** Scripts unitaires autonomes pour tester 20 cas limites de scoring.
- [x] **C37. Refonte ComicVine & Fallback Tome #1 :** Utilisation de l'endpoint structuré `/volumes/?filter=name:`.
- [x] **C38. Forçage Libre des Fournisseurs :** Déblocage de l'ensemble des scrapers dans le menu déroulant du Champ Magique.
- [x] **C9. Traducteur Multi-API Résilient :** Couche d'abstraction combinant Microsoft Azure Translator et DeepL.
- [x] **C10. Routage Dynamique & Pattern Factory :** Extraction automatique du type de bibliothèque Kavita.
- [x] **C11. Scraper ComicVine Hybride :** Recherche adaptative par album (Issue) et résolution de la série parente (Volume).
- [x] **C12. Nettoyage Contextuel de Titre :** Logique de nettoyage adaptative selon le format du média.
- [x] **C13. Purge de Fournisseur (Nautiljon) :** Retrait définitif de Nautiljon du routage par défaut face aux blocages Cloudflare.

### 🐛 Archives : Corrections de Bugs & Sécurité (V1.4.x / V1.5.x)
- [x] **BF1. Bug de Surcharge de Mot de Passe en Env Var :** Résolution du problème où vider le mot de passe dans le `docker-compose.yml` échouait.
- [x] **BF2. Nettoyage de Session à la Déconnexion :** Le bouton de déconnexion détruit désormais entièrement le cookie de session longue durée.
- [x] **BF3. Recherche de Couvertures Contextuelle** : Correction d'une régression où la recherche manuelle d'images interrogeait tous les fournisseurs.
- [x] **BF4. Bug d'Écrasement par les Spin-offs (Bédéthèque)** : Résolution d'un problème avec le tri alphabétique.
- [x] **BF5. Correction du Parsing des Éditeurs (Publisher) :** Résolution d'un oubli de parsing.
- [x] **BF6. Option de Désactivation de la Traduction :** Ajout d'un paramètre (`NONE`) pour désactiver complètement le pipeline de traduction.
- [x] **BF7. Contexte Jinja Global de Version :** Rendu de la variable `app_version` directement depuis `CHANGELOG.md`.
- [x] **BF8. Moteur Dynamique de Clés API :** Support de `needs_api_key=True` dans `BaseScraper`.
- [x] **BF9. Traductions Décentralisées (i18n) :** Les scrapers encapsulent désormais leurs propres traductions via `self.t()`.

### 🏗️ Archives : Ergonomie & Refonte Visuelle (V1.4.0 / V1.5.0)
- [x] **B1 à B6 :** Mappage et verrouillage des Genres, Tags, titres localisés, et staff étendu dans Kavita.
- [x] **B7 à B9 :** Statut "Ignoré", Polling d'Auto-Sync, routage de repli intelligent, et fusion des données.
- [x] **B11. Authentification globale :** Verrouillage de l'interface par variable d'environnement `ADMIN_PASSWORD`.
- [x] **B14 à B15 :** Modal visuelle de sélection des couvertures & API MangaBaka V2.
- [x] **B16. Nettoyeur Regex Ultime :** Centralisation de `clean_title()`.
- [x] **B17. Barre de recherche AJAX :** Filtrage instantané côté client sans rechargement de page.
- [x] **B18. Métadonnées Étendues :** Éditeurs, classification d'Âge, et sens de lecture automatique.
- [x] **B19. Identifiants & Liens Web :** Remplissage des ID natifs et génération automatique de WebLinks cliquables.
- [x] **B20. Refonte de l'Architecture UI :** Déplacement de la configuration technique dans une modal dédiée.
- [x] **B21. Recherche Manuelle de Couvertures :** Saisie libre d'un titre alternatif directement dans la modal.
- [x] **B22. Suivi de Traitement Live (Pulsation Violette) :** Coloration dynamique et défilement automatique vers la ligne active.
- [x] **B23. Recherche d'ID Rapide (Quick Lookup) :** Bouton loupe ouvrant une recherche pré-remplie sur AniList.
- [x] **B24. Persistance de l'Espace de Travail :** Sauvegarde automatique des filtres dans le `localStorage`.

### 🛠️ Archives : Fondations & Sécurité (V1.3+)
- [x] **A1 à A6 :** Intégration de l'API, Live Logs, 100% AJAX, ponts de traductions globaux, UI adaptative.
- [x] **A7 à A9 :** Cache SQLite auto-nettoyant, écrans d'erreurs de connexion explicites, déploiement sans configuration.
- [x] **A10. Serveur WSGI de Production :** Migration vers l'architecture asynchrone Eventlet + Gunicorn.
- [x] **A11. Sécurité Globale :** Proxy d'images anti-SSRF, authentification immunisée contre les attaques temporelles (`compare_digest`), cookies HttpOnly, masquage des clés API, webhooks sécurisés par jeton.