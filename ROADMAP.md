# 🚀 MetaKavita - Roadmap & To-Do List

**Concept:** Metadata scraping and enrichment tool for Kavita (alternative to Komf), designed for lightweight, self-hosted deployment.
**Philosophy:** Lightweight, pragmatic, highly secure, and optimized for Manga, Comics & Literature.

---

## Sommaire / Table of Contents
1. [🇺🇸 English Roadmap](#-english-roadmap)
2. [🇫🇷 Feuille de Route Française](#-feuille-de-route-française)

---

## 🇺🇸 English Roadmap

### 🛠️ Part A: Foundations & Security (V1.3+)
- [x] **A1 to A6:** Secure API integration, Live Logs, 100% AJAX, Global Translation bridges, Responsive UI.
- [x] **A7 to A9:** Self-cleaning SQLite cache, explicit connection error indicators, Zero-Setup deployment.
- [x] **A10. Production WSGI Server:** Eventlet + Gunicorn asynchronous stack.
- [x] **A11. Global Security:** SSRF Protection on Image Proxy, Timing-Attack immune authentication (`secrets.compare_digest`), HttpOnly Session cookies, hidden API keys in DOM, Token-protected webhooks.

---

### 🏗️ Part B: Ergonomics & Interface Overhaul (V1.4.0 / V1.5.0)
- [x] **B1 to B6:** Mapped Genres, Tags, localized titles, and extended staff metadata (Writers, Pencillers, Colorists, Translators, Cover Artists) pushing to Kavita.
- [x] **B7 to B9:** "Ignored" series state, Auto-Sync Polling, Smart Fallback Routing, and Data Fusion (Smart Completion).
- [x] **B11. Global Authentication:** UI locking via `ADMIN_PASSWORD` container variable.
- [x] **B14 to B15:** Advanced Cover Selection Modal & MangaBaka V2 API.
- [x] **B16. Ultimate Regex Title Cleaner:** Decentralized `clean_title()` logic to filter out scantrad brackets, numbering, and edition suffixes.
- [x] **B17. Real-Time AJAX Search Bar:** Instant client-side filtering without reload.
- [x] **B18. Extended Metadata Mapping:** Publishers, Age Ratings, and Origin-based Auto-Reading direction.
- [x] **B19. External IDs & WebLinks:** Automatic mapping of native IDs and clickable direct WebLinks generation inside Kavita.
- [x] **B20. Split UI Architecture:** Moved all technical config inputs to an Admin Modal, keeping active execution strategy checkboxes visible in the left sidebar.
- [x] **B21. Manual Cover Search:** Enter custom queries directly inside the cover modal to find alternate images.
- [x] **B22. Live Processing Tracker (Pulsing Glow):** Automatically flashes the active sync item in purple (`.is-processing`) and smooth-scrolls it into view using WebSocket log parsing.
- [x] **B23. AniList Quick Lookup:** Magnolia button to open pre-filled searches on AniList in a new tab.
- [x] **B24. Persistent Workspace:** Automatically saves active library, status filter, hide ignored state, and search query into `localStorage` between sessions.

---

### 🐛 V1.4.x / V1.5.x Bug Fixes & Architecture Shifts
- [x] **BF1. Admin Password Env Var Override Bug:** Resolved the issue where clearing the admin password via `docker-compose.yml` failed. Implemented a prioritize-config-over-env logic in `config_manager.py`.
- [x] **BF2. Permanent Auth Cookie Cleansing:** Ensured a hard logout completely destroys the long-lived session cookie via `expires=0` to force clean logins when authentication states are modified.
- [x] **BF3. Bédéthèque Spin-off Override Bug**: Fixed an issue where searching for a main series (e.g., "La Quête d'Ewilan") would return covers from its spin-offs (e.g., "Ellana") due to Bédéthèque's alphabetical sorting. Implemented an exact-match logic that delays the loop-break, evaluating all title variations (with and without articles) to guarantee the parent series is pushed to the top of the results.
- [x] **BF4. Context-Aware Cover Fetching**: Fixed a regression where the manual cover search queried all scrapers blindly. The system now dynamically filters active scrapers based on the Kavita `library_type` (e.g., Manga, Comic) and passes this context to adapt the title cleaning rules (fixing the `unexpected keyword argument` crash).
- [x] **BF5. Publisher Metadata Parsing Fix:** Corrected an oversight where publisher metadata wasn't properly scraped and pushed to Kavita from certain active providers.
- [x] **BF6. Disable Translation Option:** Added a configuration setting (`NONE`) to disable the translation pipeline and preserve the original scraped language.
- [x] **BF7. Global App Version Jinja Context:** Render `app_version` directly from `CHANGELOG.md` in the UI to prevent hardcoding.
- [x] **BF8. Dynamic API Key Engine:** `BaseScraper` now supports `needs_api_key=True` to auto-generate forms, variables, and security logic dynamically.
- [x] **BF9. Decentralized Translations (i18n):** Scrapers now encapsulate their own translations via `self.t()`, removing the global `translations.py` bottleneck and preventing crash bugs.

---

### 🔮 Part C: Target Scrapers & New Features (V1.5.0+)

#### 1. New Providers (Completed V1.5.5)
- [x] **C1. MyAnimeList (MAL) Scraper:** Integrated the public and free **Jikan API v4** (no key required) to natively grab `MalId` and rich metadata, replacing Nautiljon.
- [x] **C2. MangaDex Scraper:** Integrated the official **MangaDex REST API v5** for rich metadata tags (themes like *Isekai*), content rating filters (`erotica`, `pornographic`), and candidate weighting against oneshot false positives.
- [x] **C3. Baka-Updates (MangaUpdates) Scraper:** Integrated the v1 REST API to retrieve associated alternative titles, `hit_title` matching, and keyword penalty scoring.
- [x] **C4. Kitsu Scraper:** Add Kitsu JSON:API as a reliable global fallback source.
- [x] **C5. Manga-News Scraper:** Implemented `curl_cffi` scraping of the French licensing catalog to retrieve official VF publishers (*Pika*, *Glénat*, *Kurokawa*), age recommendations, and `_large.webp` HD covers.
- [x] **C6. Scraper Bedethèque:** Scraping BeautifulSoup4 for Franco-Belgian comics.
- [x] **C23. Shikimori Scraper:** Integrated Shikimori REST JSON API with native `MalId` mapping, multilingual title matching, and `/roles` endpoint staff extraction.
- [x] **C24. Open Library Scraper:** Integrated Open Library / Internet Archive API for literature, novels, and comics with ISBN support, anti-429 rate-limiting retries, and Google PDF disclaimer page interceptor.
- [x] **C16. Hardcover Scraper:** Integrated the Hardcover Hasura GraphQL & Typesense endpoints as a metadata source for literature and graphic novels (Marked as Experimental).

#### 2. Advanced Features & Core Architecture
- [x] **C6. Western Comics & Books Support (B10):** Integrated Google Books API and Open Library as production-ready scrapers for Novels, Franco-Belgian BDs, and Western Comics.
- [x] **C14. Context-Aware Cover Search:** Dynamically filter the queried providers inside the manual cover selection modal based on the Kavita `libraryType` (Manga, Comic, Book). 
- [x] **C17. Reverse Proxy & Subpath Support:** Introduced `ROOT_PATH` environment variable and WSGI middleware to dynamically prefix application routes, allowing MetaKavita to run seamlessly behind reverse proxies (Nginx Proxy Manager, Traefik).
- [x] **C18. The "Magic Input" (Smart URL Routing):** Replaced static ID fields with a universal URL/ID parser. The UI now dynamically restricts compatible providers and securely routes direct page scraping.
- [x] **C19. Granular Scraping (Targeted Fields):** Built UI and backend support to individually toggle 12 Kavita metadata fields (Summary, Cover, Publisher, Staff, etc.).
- [x] **C20. Self-Healing Configuration Engine:** Dynamic validation of search cascades. Automatically falls back to the next available scraper if a user's configured default provider file is missing.
- [x] **C21. Smart ID Match Engine:** Implemented a title similarity validation engine (>50% ratio threshold) to prevent homonym corruption.
- [x] **C22. Extended Kavita API Mapping:** Added Editors, Letterers, Inkers, and Localized Language to Kavita payload mapping.
- [x] **C25. Live WebSocket Cover Streaming (*Progressive Loading*):** Real-time Socket.IO streaming of manual cover search results with Eventlet loop yielding (`socketio.sleep(0)`), status progress bar, and CSS fade-in transitions.
- [x] **C26. Smart Ignored & Amnesties Expansion:** Override `IGNORED` status for explicitly checked batch items, and reset both `NOT_FOUND` and `IGNORED` to `PENDING` via the Amnesties button.
- [x] **C28. Kavita Deep Metadata Extraction & Unified Scoring:** Pre-fetch existing file-level metadata (`authors`, `isbn`) from Kavita before scraping and use it in a centralized, weighted scoring matrix (Roman numeral conversion, anti-spin-off penalties, guidebook noise filters, author mismatch protections) to eliminate false positives.
- [x] **C34. Smart Per-Provider Rate Limiter & Dynamic Throttling:** Replaced hardcoded worker delays with a timestamp-based throttler (`LAST_REQUEST_TIMES`). Idle APIs query instantly with 0s delay, accelerating 3-provider Smart Fusions to ~1.6s.
- [x] **C36. Quality Benchmarking & Unit Testing Suite:** Created standalone diagnostic test scripts (`debug_all_scrapers.py`, `debug_scoring_20.py`, `debug_manga_quality.py`, `debug_comic_quality.py`, `debug_book_quality.py`) to stress-test 20 scoring edge cases and 56+ API quality checks with 0 crashes.
- [x] **C37. ComicVine Overhaul & Issue #1 Fallback:** Switched to structured `/volumes/?filter=name:` search, prioritizing primary US/European publishers (*DC*, *Marvel*, *Image*, *Dargaud*) while automatically retrieving Issue #1 descriptions and creator credits when volume descriptions are brief.
- [x] **C38. Unrestricted Provider Forcing:** Unlocked all registered scrapers in the Magic Input dropdown, allowing users to force any metadata provider on any series regardless of library type.

#### 🌟 3. Future Improvements & Backlog (To-Do List)
- [ ] **C29. Interactive Manual Batch Mode (QoS):** Add an "Automatic / Manual (QoS)" toggle for batch processing.
    - In Manual mode, the backend queries metadata providers and emits candidate choices over WebSockets.
    - The frontend opens an interactive selection modal and pauses the worker using `eventlet.event.Event`.
    - The user selects the exact match or skips, sending the decision back to resume the queue.
- [ ] **C30. Francophone Book Scrapers:** Integrate dedicated French literature sources (Babelio, SensCritique) without requiring API keys.
- [ ] **C31. Kavita Deduplication Tool:** Dedicated UI panel to detect and merge duplicate series or volumes in Kavita.
- [ ] **C32. Flask Blueprints Refactoring:** Modularize `app.py` into smaller domain routes (`routes/main.py`, `routes/api.py`, `routes/auth.py`).
- [ ] **C33. Browser Extension "MetaKavita Companion":** Floating widget overlay directly on top of the Kavita Web UI to trigger MetaKavita updates natively.
- [ ] **C35. Native "Comic (Flexible)" Support:** Build a dedicated hybrid cascade for Kavita's Library Type ID 5. Currently, it defaults to Comic or Manga behavior, but it should inherently support querying Comic providers first, then gracefully falling back to Manga providers if no matches are found.
- [ ] **C7. Playful Statistics Dashboard (B12):** Display fun metrics on the `/stats` page, such as estimated time saved, estimated DeepL Translation costs avoided, and provider usage charts.
- [ ] **C8. Resiliency & Rate-Limiting Control:** Add an automatic exponential backoff retry mechanism to prevent API blocks (429 errors) during very large batches.
- [ ] **C15. Title Translation Fallback:** When a search yields no results ("Not Found"), automatically translate the query into English and perform a second pass.

#### 🌐 4. Multi-Media & Resiliency (Completed V1.5.0)
- [x] **C9. Resilient Multi-API Translator:** Dedicated translation module (`translator.py`) combining Microsoft Azure Translator (Primary F0 tier) and DeepL (Fallback) with automatic switch upon HTTP quota errors.
- [x] **C10. Dynamic Library Routing & Factory Pattern:** Automatic extraction of Kavita library types (`Manga`, `Comic`, `Book`) coupled with a nested Factory pattern.
- [x] **C11. Hybrid ComicVine Scraper:** Built a two-step lookup cascade mapping individual album titles (Issues) and resolving parent volumes (Series).
- [x] **C12. Contextual Title Cleaning:** Tailored query cleaning logic in `scrapers/__init__.py` based on targeted media type.
- [x] **C13. Provider Purge (Nautiljon):** Completely removed Nautiljon from the default routing map due to abusive Cloudflare IP bans.

---

## 🇫🇷 Feuille de Route Française

### 🛠️ Partie A : Fondations & Sécurité (V1.3+)
- [x] **A1 à A6 :** Intégration de l'API, Live Logs, 100% AJAX, ponts de traductions globaux, UI adaptative.
- [x] **A7 à A9 :** Cache SQLite auto-nettoyant, écrans d'erreurs de connexion explicites, déploiement sans configuration.
- [x] **A10. Serveur WSGI de Production :** Migration vers l'architecture asynchrone Eventlet + Gunicorn.
- [x] **A11. Sécurité Globale :** Proxy d'images anti-SSRF, authentification immunisée contre les attaques temporelles (`compare_digest`), cookies HttpOnly, masquage des clés API, webhooks sécurisés par jeton.

---

### 🏗️ Partie B : Ergonomie & Refonte Visuelle (V1.4.0 / V1.5.0)
- [x] **B1 à B6 :** Mappage et verrouillage des Genres, Tags, titres localisés, et staff étendu (Scénaristes, Dessinateurs, Coloristes, Traducteurs, Artistes de couvertures) dans Kavita.
- [x] **B7 à B9 :** Statut "Ignoré", Polling d'Auto-Sync, routage de repli intelligent, et fusion des données (Complétion intelligente).
- [x] **B11. Authentification globale :** Verrouillage de l'interface par variable d'environnement `ADMIN_PASSWORD`.
- [x] **B14 à B15 :** Modal visuelle de sélection des couvertures & API MangaBaka V2.
- [x] **B16. Nettoyeur Regex Ultime :** Centralisation de `clean_title()` pour filtrer les numérotations, brackets de scantrad et mots-clés d'éditions.
- [x] **B17. Barre de recherche AJAX :** Filtrage instantané côté client sans rechargement de page.
- [x] **B18. Métadonnées Étendues :** Éditeurs, classification d'Âge, et sens de lecture automatique basé sur l'origine du média.
- [x] **B19. Identifiants & Liens Web :** Remplissage des ID natifs et génération automatique de WebLinks cliquables dans Kavita.
- [x] **B20. Refonte de l'Architecture UI :** Déplacement de la configuration technique dans une modal dédiée, préservant la sidebar pour les options stratégiques rapides.
- [x] **B21. Recherche Manuelle de Couvertures :** Saisie libre d'un titre alternatif directement dans la modal pour trouver des couvertures alternatives.
- [x] **B22. Suivi de Traitement Live (Pulsation Violette) :** Coloration dynamique et défilement automatique vers la ligne active (`.is-processing`) grâce à l'analyse des logs WebSockets.
- [x] **B23. Recherche d'ID Rapide (Quick Lookup) :** Bouton loupe ouvrant une recherche pré-remplie sur AniList dans un nouvel onglet.
- [x] **B24. Persistance de l'Espace de Travail :** Sauvegarde automatique des filtres (bibliothèque, recherche, statut, ignorés) dans le `localStorage`.

---

### 🐛 Corrections de Bugs V1.4.x / V1.5.x & Sécurité
- [x] **BF1. Bug de Surcharge de Mot de Passe en Env Var :** Résolution du problème où vider le mot de passe dans le `docker-compose.yml` échouait. Mise en place d'une priorité de configuration locale via `config.json`.
- [x] **BF2. Nettoyage de Session à la Déconnexion :** Le bouton de déconnexion détruit désormais entièrement le cookie de session longue durée (expiration forcée) pour forcer une ré-authentification propre.
- [x] **BF3. Recherche de Couvertures Contextuelle** : Correction d'une régression où la recherche manuelle d'images interrogeait tous les fournisseurs à l'aveugle. Le système filtre désormais dynamiquement les scrapers selon le type de bibliothèque.
- [x] **BF4. Bug d'Écrasement par les Spin-offs (Bédéthèque)** : Résolution d'un problème où la recherche d'une série principale renvoyait les couvertures de son spin-off à cause du tri alphabétique.
- [x] **BF5. Correction du Parsing des Éditeurs (Publisher) :** Résolution d'un oubli de parsing où le nom de l'éditeur n'était pas correctement extrait et envoyé vers Kavita.
- [x] **BF6. Option de Désactivation de la Traduction :** Ajout d'un paramètre de configuration (`NONE`) pour désactiver complètement le pipeline de traduction et conserver la langue d'origine scrapée.
- [x] **BF7. Contexte Jinja Global de Version :** Rendu de la variable `app_version` directement depuis `CHANGELOG.md` dans l'UI pour éviter de coder la version en dur.
- [x] **BF8. Moteur Dynamique de Clés API :** Support de `needs_api_key=True` dans `BaseScraper` pour auto-générer les champs de paramètres, les variables et la sécurité de manière dynamique.
- [x] **BF9. Traductions Décentralisées (i18n) :** Les scrapers encapsulent désormais leurs propres traductions via `self.t()`, purgeant `translations.py` pour prévenir les crashs liés aux clés manquantes.

---

### 🔮 Partie C : Scrapers Cibles & Nouvelles Fonctionnalités (V1.5.0+)

#### 1. Nouveaux Scrapers (Complétés V1.5.5)
- [x] **C1. Scraper MyAnimeList (MAL) :** Utilisation de l'API publique et gratuite **Jikan v4** (sans clé API) pour récupérer les descriptions et les ID MAL natifs.
- [x] **C2. Scraper MangaDex :** Intégration de l'API REST officielle **MangaDex v5** pour extraire les thèmes, résumés multilingues, filtres adultes (`erotica`, `pornographic`), et pénalité Oneshot.
- [x] **C3. Scraper Baka-Updates (MangaUpdates) :** Exploitation de l'API REST v1 pour importer les listes de titres associés, correspondance `hit_title` et scoring par mots-clés.
- [x] **C4. Scraper Kitsu :** Ajout de la source Kitsu comme repli international rapide.
- [x] **C5. Scraper Manga-News :** Scraping `curl_cffi` du catalogue VF pour récupérer l'éditeur français exact (*Pika*, *Glénat*, *Kurokawa*), les recommandations d'âges et les visuels HD (`_large.webp`).
- [x] **C6. Scraper Bédéthèque :** Scraping BeautifulSoup4 optimisé pour la bande dessinée franco-belge.
- [x] **C23. Scraper Shikimori :** API REST JSON avec évaluation multilingue (Romaji, Anglais, Japonais), mapping `MalId`, et extraction du staff via `/roles`.
- [x] **C24. Scraper Open Library :** API Internet Archive pour les romans, livres et BDs avec support des clés Work (`OL...W`) et ISBNs, pauses anti-429 et intercepteur de page d'avertissement Google PDF.
- [x] **C16. Scraper Hardcover :** Intégration des terminaux GraphQL Hasura & Typesense comme source de métadonnées pour la littérature et les romans graphiques (Marqué comme Expérimental).

#### 2. Fonctionnalités Avancées & Architecture Core
- [x] **C6. Support des BD Occidentales & Romans (B10) :** Intégration des APIs Google Books et Open Library pour enrichir les romans, les BD franco-belges et comics américains.
- [x] **C14. Recherche de Couvertures Contextuelle :** Filtrer dynamiquement les fournisseurs interrogés dans la modal selon le type de bibliothèque Kavita.
- [x] **C17. Support Reverse Proxy & Subpath :** Ajout de la variable `ROOT_PATH` et d'un middleware WSGI pour préfixer dynamiquement les routes de l'application.
- [x] **C18. Le "Champ Magique" (Routage URL Intelligent) :** Remplacement de l'ancien champ d'ID par un analyseur universel d'URL/ID.
- [x] **C19. Scraping Granulaire (Champs Ciblés) :** Prise en charge du ciblage individuel des 12 champs de métadonnées Kavita.
- [x] **C20. Auto-Réparation de la Configuration (Self-Healing) :** Validation dynamique des cascades de recherche avec bascule automatique si un fichier est manquant.
- [x] **C21. Moteur Smart ID Match :** Validateur par similarité de titre (>50%) lors des requêtes par ID brut.
- [x] **C22. Mappage API Kavita Étendu :** Ajout des Éditeurs (Staff), Lettreurs, Encreurs et de la Langue native dans la structure des requêtes vers Kavita.
- [x] **C25. Streaming de Couvertures par WebSockets (*Progressive Loading*) :** Envoi en direct au fil de l'eau via Socket.IO des images avec libération de boucle Eventlet (`socketio.sleep(0)`), bandeau de statut et animations CSS.
- [x] **C26. Forçage des Ignorés & Amnesties Élargies :** Traitement des séries ignorées cochées en batch et réinitialisation conjointe de `NOT_FOUND` et `IGNORED` vers `PENDING`.
- [x] **C28. Extraction Profonde des Métadonnées Kavita & Scoring Unifié :** Pré-récupérer les métadonnées existantes (`auteurs`, `ISBN`) avant le scraping pour alimenter une matrice de scoring centralisée et pondérée (convertisseur de chiffres romains, filtres anti-spin-off, anti-guidebook, et pénalité anti-homonymes d'auteurs).
- [x] **C34. Rate-Limiter Intelligente & Throttling Dynamique :** Remplacement des pauses fixes par un régulateur par horodatage (`LAST_REQUEST_TIMES`). Les API inactives répondent à 0s de délai, exécutant la Smart Fusion de 3 sources en ~1,6s.
- [x] **C36. Suite de Tests & Benchmarks Qualité :** Scripts unitaires autonomes (`debug_all_scrapers.py`, `debug_scoring_20.py`, `debug_manga_quality.py`, `debug_comic_quality.py`, `debug_book_quality.py`) pour tester 20 cas limites de scoring et 56+ requêtes de qualité API sans aucun crash Python.
- [x] **C37. Refonte ComicVine & Fallback Tome #1 :** Utilisation de l'endpoint structuré `/volumes/?filter=name:`, priorisation des éditeurs originaux majeurs (*DC*, *Marvel*, *Image*, *Dargaud*) et récupération du synopsis/staff sur l'Issue #1.
- [x] **C38. Forçage Libre des Fournisseurs :** Déblocage de l'ensemble des scrapers dans le menu déroulant du Champ Magique pour forcer n'importe quelle source.

#### 🌟 3. Améliorations Futures & Backlog (To-Do List)
- [ ] **C29. Mode Batch Manuel Interactif (QoS) :** Ajouter un sélecteur "Automatique / Manuel (QoS)" pour les traitements par lots.
    - En mode Manuel, le backend récupère les candidats et les envoie via WebSockets.
    - Le frontend affiche une modale de choix et met le worker en pause via `eventlet.event.Event`.
    - L'utilisateur valide le bon résultat ou passe, débloquant le worker pour le fichier suivant.
- [ ] **C30. Scrapers Littéraires Francophones :** Intégrer des sources spécialisées en littérature française (Babelio, SensCritique) sans clé API.
- [ ] **C31. Outil de Déduplication Kavita :** Panneau UI pour détecter et fusionner les doublons dans Kavita.
- [ ] **C32. Refonte Flask Blueprints :** Découpage de `app.py` en modules de routes distincts (`routes/main.py`, `routes/api.py`, `routes/auth.py`).
- [ ] **C33. Extension Navigateur "MetaKavita Companion" :** Widget flottant en surcouche directement sur l'interface Web de Kavita pour déclencher les mises à jour MetaKavita nativement.
- [ ] **C35. Support natif du type "Comic (Flexible)" :** Créer une cascade hybride dédiée pour le type de bibliothèque ID 5 de Kavita. Actuellement, MetaKavita le traite comme un Comic ou un Manga strict, mais il devrait pouvoir interroger les sites de Comics puis basculer intelligemment sur les sites de Mangas en cas d'échec pour refléter la nature "flexible" du dossier.
- [ ] **C7. Tableau de bord Statistiques ludique (B12) :** Ajout de métriques sur la page `/stats` (estimation du temps de recherche épargné, équivalent en euros économisé sur DeepL, graphiques de répartition par scrapers).
- [ ] **C8. Gestion de la Résilience d'API :** Système de retry automatique avec attente exponentielle pour contourner le rate limiting lors des très gros batchs.
- [ ] **C15. Traduction de Titre (Secours) :** Traduction automatique en anglais pour relancer une seconde passe en cas d'échec initial.

#### 🌐 4. Multi-Média & Résilience (Complété V1.5.0)
- [x] **C9. Traducteur Multi-API Résilient :** Couche d'abstraction (`translator.py`) combinant Microsoft Azure Translator (Primary F0) et DeepL (Fallback).
- [x] **C10. Routage Dynamique & Pattern Factory :** Extraction automatique du type de bibliothèque Kavita (`Manga`, `Comic`, `Book`) couplée à un aiguillage dynamique.
- [x] **C11. Scraper ComicVine Hybride :** Recherche adaptative par album (Issue) et résolution de la série parente (Volume).
- [x] **C12. Nettoyage Contextuel de Titre :** Logique de nettoyage adaptative selon le format du média.
- [x] **C13. Purge de Fournisseur (Nautiljon) :** Retrait définitif de Nautiljon du routage par défaut face aux blocages Cloudflare.