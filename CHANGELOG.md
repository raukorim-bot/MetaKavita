# Changelog

## [1.4.0] - 2026-07-19 (Ergonomic Revolution & Total UI Overhaul)

EN
### 🎨 Major UI & Ergonomics Overhaul
* **Settings Modal**: Moved all infrastructure and technical configuration inputs (Kavita URL/API, DeepL API, languages, auto-sync, fallback providers) into a clean, dedicated overlay Modal, completely uncluttering the left sidebar.
* **Scraping Strategy Sidebar**: Kept runtime scraping options (Smart Completion, Auto-Cover, Auto-Reading Direction, Force Update) directly visible in the left sidebar for instant workflow changes before batch sync.
* **Unified Central Toolbar**: Merged the library selector (`#lib_selector`) into the central toolbar alongside search and status filters. Searching, status filtering, and library switching are now in one unified horizontal line.
* **Consolidated Mass Execution Block**: Aligned the "Reset Errors / Amnistie" button inside the bottom batch action block, grouping all mass-level executions in a single clean row.
* **Search Input Specificity**: Constrained the search input's width using high-specificity CSS selectors, preventing overlap with the global save button on large screens.

### 📐 Added Ergonomic Features
* **Manual Cover Search**: Added a manual search bar inside the cover selection modal, allowing users to type and search alternate titles without closing the modal or modifying overrides.
* **Live Processing Highlight**: WebSocket logs now trigger an active glowing border/background animation (`.is-processing`) and automatically scroll the series currently being processed into view. Statut badges are updated live without page reload.
* **Workspace Persistence**: Filter selections (Library, Status, Search string, Hide Ignored state) are now saved automatically inside `localStorage` and restored upon loading the dashboard.
* **Quick ID Lookup**: Added a lookup magnifying button next to the AniList ID input field, opening a pre-filled AniList search in a new tab.

### 🐛 Bug Fixes
* Fixed an issue where completed or skipped series during batch runs displayed an `undefined` status badge inside the interface.

FR
### 🎨 Refonte Majeure de l'UI & Ergonomie
* **Modal de Configuration**: Déplacement de toute la configuration technique et d'infrastructure (URL/API Kavita, API DeepL, langues, auto-sync, cascade de fournisseurs) dans une modal d'administration dédiée, aérant complètement la barre latérale.
* **Options Stratégiques Visibles**: Conservation des cases d'exécution de scraping (fusion, sens de lecture, covers, mise à jour forcée) directement accessibles dans la barre latérale gauche pour un ajustement à la volée.
* **Toolbar Centrale Unifiée**: Intégration du sélecteur de bibliothèque directement dans la barre d'outils centrale. Le ciblage, le filtrage et la recherche s'effectuent désormais sur une seule et même ligne horizontale.
* **Grille d'Actions de Masse**: Alignement du bouton « Amnistie des erreurs » au bas de l'écran avec les autres boutons d'actions par lots (Lancer, Ignorer, Arrêter) pour une meilleure cohérence.
* **Taille de la barre de recherche**: Limitation étanche de la largeur de l'input de recherche pour éviter tout chevauchement ou étirement inesthétique contre le bouton de sauvegarde.

### 📐 Fonctionnalités d'Ergonomie Intégrées
* **Recherche Manuelle de Couvertures**: Ajout d'une barre de recherche interne dans la modal des couvertures pour interroger les bases de données avec d'autres titres à la volée.
* **Suivi de Traitement Live**: Les logs WebSocket déclenchent une animation de pulsation lumineuse violette (`.is-processing`) sur la ligne de la série active et la font défiler automatiquement à l'écran. Les badges de statut se mettent à jour en direct.
* **Persistance de l'Espace de Travail**: Sauvegarde automatique de tes filtres (Bibliothèque, Recherche, Statut, Ignorés) dans le `localStorage` pour retrouver ton tableau de bord identique après fermeture.
* **Recherche d'ID Rapide (Quick Lookup)**: Ajout d'un bouton loupe à côté du champ de saisie d'ID AniList pour ouvrir directement une recherche pré-remplie dans un nouvel onglet.

### 🐛 Corrections de Bugs
* Correction d'un bug d'affichage où le badge de statut affichait la valeur textuelle `undefined` lors des sauts de séries déjà enrichies durant un batch.

---

## [1.3.2] - 2026-07-19 (Security & Metadata Overhaul)

EN
### 🛡️ Major Security Audit
* **WSGI Production Server:** Dropped Werkzeug in favor of a robust Gunicorn + Eventlet architecture for production readiness.
* **Global Authentication:** The dashboard can now be locked using the `ADMIN_PASSWORD` Docker variable. Features strict immunity against Timing Attacks (`secrets.compare_digest`) and Brute-Force delays.
* **SSRF Proxy Protection:** The image proxy is now locked behind a strict domain Whitelist (`ALLOWED_PROXY_DOMAINS`), ignoring port bypasses.
* **Webhook Hardening:** Webhook calls are now secured via a cryptographically generated `WEBHOOK_TOKEN`, making it safe to use behind Reverse Proxies.
* **Hidden API Keys:** API keys are physically hidden from the DOM / HTML source code and preserved safely upon saving other settings.

### 🧩 Ultimate Regex Cleaner
* **Centralized Logic:** Title cleaning logic is now decoupled in `scrapers/__init__.py`.
* **Advanced Stripping:** The engine flawlessly strips stray dots, `[Team]` prefixes, edition keywords (`Omnibus`, `Perfect Edition`), and volume numbers (`01 - Title`), catapulting the API match rate to near 100%.

### 📚 Extended Kavita Metadata
* **Rich Staff & Lore:** MetaKavita now pushes Publishers, Age Ratings, Colorists, Translators, and Cover Artists to Kavita.
* **External IDs & WebLinks:** Automatically populates Kavita's native `AniListId`, `MalId`, and `MangaBakaId`. Auto-generates clickable UI WebLinks to display official provider icons right under the manga title!
* **Reading Direction:** New toggle to automatically adapt the reading direction (Manga, Webtoon, Comic) based on the country of origin.

### 🎨 UI Improvements
* **AJAX Search Bar:** Find any series instantly without scrolling.

FR
### 🛡️ Audit de Sécurité Majeur
* **Serveur de Production WSGI :** Abandon de Werkzeug au profit d'une architecture Gunicorn + Eventlet robuste.
* **Authentification Globale :** L'interface peut être verrouillée via la variable `ADMIN_PASSWORD`. Inclut une immunité contre les attaques temporelles et un délai anti-force-brute.
* **Protection Proxy SSRF :** Le proxy d'images est verrouillé par une liste blanche dynamique, insensible aux contournements par port.
* **Webhook Sécurisé :** Les appels Webhook exigent désormais un `WEBHOOK_TOKEN` cryptographique, sécurisant l'usage derrière un Reverse Proxy.
* **Clés API Invisibles :** Les clés API n'apparaissent plus dans le code source HTML (DOM).

### 🧩 Nettoyeur Regex Ultime
* **Logique Centralisée :** Le nettoyage des titres est désormais un module indépendant (`scrapers/__init__.py`).
* **Filtrage Avancé :** Le moteur supprime les points capricieux, les préfixes de scantrad, les mots-clés (`Intégrale`, `Deluxe Edition`) et les numéros de dossiers complexes, propulsant le taux de réussite des API.

### 📚 Métadonnées Kavita Étendues
* **Staff et Détails :** MetaKavita gère désormais les Éditeurs, la classification d'Âge, les Coloristes, Traducteurs, et Artistes de Couverture.
* **IDs et Liens Externes :** Remplissage automatique des champs `AniListId`, `MalId`, et `MangaBakaId`. Génération de WebLinks cliquables pour afficher les icônes officielles dans Kavita !
* **Sens de Lecture :** Nouvelle option permettant d'adapter automatiquement le sens de lecture (Manga, Webtoon) selon l'origine de l'œuvre.

### 🎨 Améliorations UI
* **Barre de recherche AJAX :** Filtrez vos centaines de séries instantanément en temps réel.