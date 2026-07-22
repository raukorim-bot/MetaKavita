# 🚀 MetaKavita - Roadmap & To-Do List

**Concept:** Metadata scraping and enrichment tool for Kavita (alternative to Komf), designed for lightweight, self-hosted deployment.
**Philosophy:** Lightweight, pragmatic, highly secure, and optimized for Manga & BD (Comics).

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

### 🏗️ Part B: Ergonomics & Interface Overhaul (V1.4.0)
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

### 🐛 V1.4.x / V1.5.0+ Bug Fixes & Security Hardening
- [x] **BF1. Admin Password Env Var Override Bug:** Resolved the issue where clearing the admin password via `docker-compose.yml` failed. Implemented a prioritize-config-over-env logic in `config_manager.py`.
- [x] **BF2. Permanent Auth Cookie Cleansing:** Ensured a hard logout completely destroys the long-lived session cookie via `expires=0` to force clean logins when authentication states are modified.
- [x] **BF3. Bédéthèque Spin-off Override Bug**: Fixed an issue where searching for a main series (e.g., "La Quête d'Ewilan") would return covers from its spin-offs (e.g., "Ellana") due to Bédéthèque's alphabetical sorting. Implemented an exact-match logic that delays the loop-break, evaluating all title variations (with and without articles) to guarantee the parent series is pushed to the top of the results.
- [x] **BF4. Context-Aware Cover Fetching**: Fixed a regression where the manual cover search queried all scrapers blindly. The system now dynamically filters active scrapers based on the Kavita `library_type` (e.g., Manga, Comic) and passes this context to adapt the title cleaning rules (fixing the `unexpected keyword argument` crash).
- [x] **BF5. Publisher Metadata Parsing Fix:** Corrected an oversight where publisher metadata wasn't properly scraped and pushed to Kavita from certain active providers.
- [x] **BF6. Disable Translation Option:** Added a configuration setting (`NONE`) to disable the translation pipeline and preserve the original scraped language.

---

### 🔮 Part C: Target Scrapers & New Features (V1.5.0+)

#### 1. New Providers (Priority Integration)
- [x] **C1. MyAnimeList (MAL) Scraper:** Integrated the public and free **Jikan API v4** (no key required) to natively grab `MalId` and rich metadata, replacing Nautiljon.
- [ ] **C2. MangaDex Scraper:** Integrate the official **MangaDex REST API** for rich metadata tags (themes like *Isekai*), localized descriptions, and extra cover artwork.
- [ ] **C3. Baka-Updates (MangaUpdates) Scraper:** Integrate the scanlation catalog to retrieve vast lists of alternative associated titles to auto-populate overrides.
- [x] **C4. Kitsu Scraper:** Add Kitsu JSON:API as a reliable global fallback source.
- [ ] **C5. Manga-News Scraper:** Implement BeautifulSoup4 scraping of the French licensing catalog to retrieve official publisher credits, VF volumes count, and regional age recommendations.
- [x] **C6. Scraper Bedethèque:** Scraping BeautifulSoup4 for Franco-Belgian comics.

#### 2. Advanced Features & Core Architecture
- [x] **C6. Western Comics & Books Support (B10):** Integrated the Google Books API as a production-ready scraper to allow metadata fetching for Novels, Franco-Belgian BDs, and Western Comics.
- [ ] **C7. Playful Statistics Dashboard (B12):** Display fun metrics on the `/stats` page, such as estimated time saved, estimated DeepL Translation costs avoided, and provider usage charts.
- [ ] **C8. Resiliency & Rate-Limiting Control:** Add an automatic exponential backoff retry mechanism to prevent API blocks (429 errors) during very large batches.
- [x] **C14. Context-Aware Cover Search:** Dynamically filter the queried providers inside the manual cover selection modal based on the Kavita `libraryType` (Manga, Comic, Book). 
- [ ] **C15. Title Translation Fallback:** When a search yields no results ("Not Found"), automatically translate the query into English and perform a second pass to maximize match rates for highly localized titles.
- [ ] **C16. Hardcover Scraper:** Integrate the Hardcover API as an additional metadata source to expand matching capabilities.
- [x] **C17. Reverse Proxy & Subpath Support:** Introduced `ROOT_PATH` environment variable and WSGI middleware to dynamically prefix application routes, allowing MetaKavita to run seamlessly behind reverse proxies (e.g., Nginx Proxy Manager, Traefik) on custom subpaths.
- [x] **C18. The "Magic Input" (Smart URL Routing):** Replaced static ID fields with a universal URL/ID parser. The UI now dynamically restricts compatible providers and securely routes direct page scraping to bypass false-positive search results.
- [x] **C19. Granular Scraping (Targeted Fields):** Built UI and backend support to individually toggle 12 Kavita metadata fields (Summary, Cover, Publisher, Staff, etc.), allowing users to prevent accidental overwrites of manually edited details.
- [x] **C20. Self-Healing Configuration Engine:** Dynamic validation of search cascades. Automatically falls back to the next available scraper if a user's configured default provider file is missing or deleted.
- [x] **C21. Smart ID Match Engine:** Implemented a title similarity validation engine (>50% ratio threshold). When searching via raw ID strings, the system cross-references the retrieved title with Kavita's title to prevent homonym corruption.
- [x] **C22. Extended Kavita API Mapping:** Added Editors, Letterers, Inkers, and Localized Language strictly to the Kavita payload mapping block.

#### 🌐 3. Multi-Media & Resiliency (Completed V1.5.0)
- [x] **C9. Resilient Multi-API Translator:** Dedicated translation module (`translator.py`) combining Microsoft Azure Translator (Primary F0 tier) and DeepL (Fallback) with automatic switch upon HTTP quota errors.
- [x] **C10. Dynamic Library Routing & Factory Pattern:** Automatic extraction of Kavita library types (`Manga`, `Comic`, `Book`) coupled with a nested Factory pattern to route requests dynamically to category-specific scrapers.
- [x] **C11. Hybrid ComicVine Scraper:** Built a two-step lookup cascade mapping individual album titles (Issues) and resolving parent volumes (Series) with automatic in-memory homonym summary recovery and noisy HTML cleaning.
- [x] **C12. Contextual Title Cleaning:** Tailored query cleaning logic in `scrapers/__init__.py` based on the targeted media type (safely stripping leading zeros in comics while preserving issue numbers).
- [x] **C13. Provider Purge (Nautiljon):** Completely removed Nautiljon from the default routing map because their admins are terrified of their processors heating up, resulting in abusive Cloudflare IP bans. Switched to robust, open APIs instead.

---

## 🇫🇷 Feuille de Route Française

### 🛠️ Partie A : Fondations & Sécurité (V1.3+)
- [x] **A1 à A6 :** Intégration de l'API, Live Logs, 100% AJAX, ponts de traductions globaux, UI adaptative.
- [x] **A7 à A9 :** Cache SQLite auto-nettoyant, écrans d'erreurs de connexion explicites, déploiement sans configuration.
- [x] **A10. Serveur WSGI de Production :** Migration vers l'architecture asynchrone Eventlet + Gunicorn.
- [x] **A11. Sécurité Globale :** Proxy d'images anti-SSRF, authentification immunisée contre les attaques temporelles (`compare_digest`), cookies HttpOnly, masquage des clés API, webhooks sécurisés par jeton.

---

### 🏗️ Partie B : Ergonomie & Refonte Visuelle (V1.4.0)
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

### 🐛 Corrections de Bugs V1.4.x / V1.5.0+ & Sécurité
- [x] **BF1. Bug de Surcharge de Mot de Passe en Env Var :** Résolution du problème où vider le mot de passe dans le `docker-compose.yml` échouait. Mise en place d'une priorité de configuration locale via `config.json`.
- [x] **BF2. Nettoyage de Session à la Déconnexion :** Le bouton de déconnexion détruit désormais entièrement le cookie de session longue durée (expiration forcée) pour forcer une ré-authentification propre.
- [x] **BF3. Recherche de Couvertures Contextuelle** : Correction d'une régression où la recherche manuelle d'images interrogeait tous les fournisseurs à l'aveugle. Le système filtre désormais dynamiquement les scrapers selon le type de bibliothèque (`Manga`, `Comic`, `Book`) et transmet ce contexte pour adapter le nettoyage du titre (ce qui corrige au passage l'erreur fatale `unexpected keyword argument`).
- [x] **BF4. Bug d'Écrasement par les Spin-offs (Bédéthèque)** : Résolution d'un problème où la recherche d'une série principale (ex: "La Quête d'Ewilan") renvoyait les couvertures de son spin-off (ex: "Ellana") à cause du tri alphabétique natif de Bédéthèque. Ajout d'une logique de "match exact" qui évalue toutes les variations de titres (gestion des articles "Le", "La") pour garantir que la série mère remonte en première position.
- [x] **BF5. Correction du Parsing des Éditeurs (Publisher) :** Résolution d'un oubli de parsing où le nom de l'éditeur n'était pas correctement extrait et envoyé vers Kavita sur certains fournisseurs actifs.
- [x] **BF6. Option de Désactivation de la Traduction :** Ajout d'un paramètre de configuration (`NONE`) pour désactiver complètement le pipeline de traduction et conserver la langue d'origine scrapée.

---

### 🔮 Partie C : Scrapers Cibles & Nouvelles Fonctionnalités (V1.5.0+)

#### 1. Nouveaux Scrapers (Priorité d'intégration)
- [x] **C1. Scraper MyAnimeList (MAL) :** Utilisation de l'API publique et gratuite **Jikan v4** (sans clé API) pour récupérer les descriptions et les ID MAL natifs, remplaçant définitivement Nautiljon.
- [ ] **C2. Scraper MangaDex :** Intégration de l'API REST officielle **MangaDex** pour extraire les thèmes, résumés multilingues natifs et couvertures de chapitres.
- [ ] **C3. Scraper Baka-Updates (MangaUpdates) :** Exploitation du catalogue pour importer d'importantes listes de titres associés afin d'auto-remplir les titres alternatifs.
- [x] **C4. Scraper Kitsu :** Ajout de la source Kitsu comme repli international rapide.
- [ ] **C5. Scraper Manga-News :** Scraping BeautifulSoup4 du catalogue VF pour récupérer l'éditeur français exact, le nombre de volumes VF parus et les recommandations d'âges régionales.
- [x] **C6. Scraper Bédéthèque :** Scraping BeautifulSoup4 optimisé pour la bande dessinée franco-belge.

#### 2. Fonctionnalités Avancées & Architecture Core
- [x] **C6. Support des BD Occidentales & Romans (B10) :** Intégration de l'API Google Books en scraper de production pour enrichir les romans, les BD franco-belges et comics américains (compatible catégories Comic et Book).
- [ ] **C7. Tableau de bord Statistiques ludique (B12) :** Ajout de métriques amusantes sur la page `/stats` (estimation du temps de recherche épargné, équivalent en euros économisé sur DeepL, graphiques de répartition par scrapers).
- [ ] **C8. Gestion de la Résilience d'API :** Système de retry automatique avec attente exponentielle pour contourner le rate limiting lors des très gros batchs.
- [x] **C14. Recherche de Couvertures Contextuelle :** Filtrer dynamiquement les fournisseurs interrogés dans la modal de sélection d'images selon le type exact de la bibliothèque Kavita (Manga, Comic, Livre). 
- [ ] **C15. Traduction de Titre (Secours) :** Lorsqu'une recherche échoue ("Introuvable"), traduire automatiquement le titre en anglais et relancer une seconde passe pour maximiser les correspondances d'œuvres très localisées.
- [ ] **C16. Scraper Hardcover :** Intégration de l'API Hardcover comme nouvelle source de métadonnées pour élargir les correspondances.
- [x] **C17. Support Reverse Proxy & Subpath :** Ajout de la variable d'environnement `ROOT_PATH` et d'un middleware WSGI pour préfixer dynamiquement les routes de l'application et exposer proprement MetaKavita derrière un reverse proxy (Nginx Proxy Manager, Traefik).
- [x] **C18. Le "Champ Magique" (Routage URL Intelligent) :** Remplacement de l'ancien champ d'ID AniList statique par un analyseur universel d'URL. L'UI filtre dynamiquement les fournisseurs compatibles et route l'URL directement pour contourner les faux positifs de recherche.
- [x] **C19. Scraping Granulaire (Champs Ciblés) :** Prise en charge (UI/Backend) du ciblage individuel des 12 champs de métadonnées Kavita (Résumé, Cover, Éditeur, etc.) pour éviter d'écraser des informations éditées manuellement.
- [x] **C20. Auto-Réparation de la Configuration (Self-Healing) :** Validation dynamique des cascades de recherche. Bascule automatique et transparente vers un autre scraper disponible si l'utilisateur supprime physiquement un fichier provider par défaut.
- [x] **C21. Moteur Smart ID Match :** Implémentation d'un validateur par similarité de titre (>50%). Lors d'une requête par ID brut, le système croise le titre récupéré avec le titre Kavita pour éviter de corrompre la base de données avec des mangas homonymes.
- [x] **C22. Mappage API Kavita Étendu :** Ajout des Éditeurs (Staff), Lettreurs, Encreurs et de la Langue native dans la structure des requêtes vers Kavita.

#### 🌐 3. Multi-Média & Résilience (Complété V1.5.0)
- [x] **C9. Traducteur Multi-API Résilient :** Couche d'abstraction (`translator.py`) combinant Microsoft Azure Translator (Moteur principal F0) et DeepL (Secours automatique en cas de quota dépassé).
- [x] **C10. Routage Dynamique & Pattern Factory :** Extraction automatique du type de bibliothèque Kavita (`Manga`, `Comic`, `Book`) couplée à un aiguillage dynamique des requêtes vers les scrapers spécifiques.
- [x] **C11. Scraper ComicVine Hybride :** Recherche adaptative par album (Issue) et résolution de la série parente (Volume) avec extraction de couverture spécifique d'album, fusion des résumés et filtrage des résidus HTML (anti-bruit).
- [x] **C12. Nettoyage Contextuel de Titre :** Logique de nettoyage adaptative dans `scrapers/__init__.py` selon le format du média (retrait propre des zéros de tri dans les comics).
- [x] **C13. Purge de Fournisseur (Nautiljon) :** Retrait définitif de Nautiljon du routage par défaut. Leurs administrateurs ont apparemment trop peur que leurs processeurs chauffent et abusent des bans IP Cloudflare. Place aux vraies APIs ouvertes et robustes.