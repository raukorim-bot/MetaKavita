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
- [x] **A11. Global Security:** SSRF Protection on Image Proxy,Timing-Attack immune authentication (`secrets.compare_digest`), HttpOnly Session cookies, hidden API keys in DOM, Token-protected webhooks.

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

### 🐛 Upcoming V1.4.x Bug Fixes & Security Hardening
- [ ] **BF1. Admin Password Env Var Override Bug:** Resolve the issue where clearing the admin password via `docker-compose.yml` fails and `ADMIN_PASSWORD` remains hardcoded in UI environment variables. Implement a prioritize-config-over-env logic or warning banner.
- [ ] **BF2. Permanent Auth Cookie Cleansing:** Ensure a hard logout completely destroys the long-lived session cookie to force clean logins when authentication states are modified.

---

### 🔮 Part C: Target Scrapers & New Features (V1.5.0+)

#### 1. New Manga Providers (Priority Integration)
- [ ] **C1. MyAnimeList (MAL) Scraper:** Integrate the public and free **Jikan API** (no key required) to natively grab `MalId` and completed English descriptions.
- [ ] **C2. MangaDex Scraper:** Integrate the official **MangaDex REST API** for rich metadata tags (themes like *Isekai*), localized descriptions, and extra cover artwork.
- [ ] **C3. Baka-Updates (MangaUpdates) Scraper:** Integrate the scanlation catalog to retrieve vast lists of alternative associated titles to auto-populate overrides.
- [ ] **C4. Kitsu Scraper:** Add Kitsu JSON:API as a reliable global fallback source.
- [ ] **C5. Manga-News Scraper:** Implement BeautifulSoup4 scraping of the French licensing catalog to retrieve official publisher credits, VF volumes count, and regional age recommendations.

#### 2. Advanced Features
- [ ] **C6. ISBN Western Comics & Books Support (B10):** Integrate Google Books or OpenLibrary APIs to allow metadata fetching for Franco-Belgian BDs and Western Comics using titles or ISBNs.
- [ ] **C7. Playful Statistics Dashboard (B12):** Display fun metrics on the `/stats` page, such as estimated time saved, estimated DeepL Translation costs avoided, and provider usage charts.
- [ ] **C8. Resiliency & Rate-Limiting Control:** Add an automatic exponential backoff retry mechanism to prevent API blocks (429 errors) during very large batches.

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

### 🐛 Corrections de Bugs V1.4.x & Sécurité
- [ ] **BF1. Bug de Surcharge de Mot de Passe en Env Var :** Résoudre le problème où vider le mot de passe dans le `docker-compose.yml` échoue si la variable d'environnement `ADMIN_PASSWORD` a déjà été activée `docker-compose.yml`. Mettre en place un avertissement ou une priorité de configuration locale.
- [ ] **BF2. Nettoyage de Session à la Déconnexion :** S'assurer que le bouton de déconnexion détruit entièrement le cookie de session longue durée pour forcer une ré-authentification propre.

---

### 🔮 Partie C : Scrapers Cibles & Nouvelles Fonctionnalités (V1.5.0+)

#### 1. Nouveaux Scrapers Manga (Priorité d'intégration)
- [ ] **C1. Scraper MyAnimeList (MAL) :** Utilisation de l'API publique et gratuite **Jikan** (sans clé API) pour récupérer les descriptions anglaises et les ID MAL natifs de Kavita.
- [ ] **C2. Scraper MangaDex :** Intégration de l'API REST officielle **MangaDex** pour extraire les thèmes, résumés multilingues natifs et couvertures de chapitres.
- [ ] **C3. Scraper Baka-Updates (MangaUpdates) :** Exploitation du catalogue pour importer d'importantes listes de titres associés afin d'auto-remplir les titres alternatifs.
- [ ] **C4. Scraper Kitsu :** Ajout de la source Kitsu comme repli international rapide.
- [ ] **C5. Scraper Manga-News :** Scraping BeautifulSoup4 du catalogue VF pour récupérer l'éditeur français exact, le nombre de volumes VF parus et les recommandations d'âges régionales.

#### 2. Fonctionnalités Avancées
- [ ] **C6. Support des BD Occidentales & Comics (B10) :** Intégration de Google Books et OpenLibrary pour enrichir les BD franco-belges et comics américains à l'aide de leur titre ou de leur ISBN.
- [ ] **C7. Tableau de bord Statistiques ludique (B12) :** Ajout de métriques amusantes sur la page `/stats` (estimation du temps de recherche épargné, équivalent en euros économisé sur DeepL, graphiques de répartition par scrapers).
- [ ] **C8. Gestion de la Résilience d'API :** Système de retry automatique avec attente exponentielle pour contourner le rate limiting lors des très gros batchs.