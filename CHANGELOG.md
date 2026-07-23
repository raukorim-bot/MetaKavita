# Changelog

# Changelog

## [1.5.6] - 2026-07-24 (The Permanent Cover Upload Hotfix)

EN
### 🐛 Bug Fixes
* **Kavita Cover Upload Data URI Fix (`kavita_api.py`)**: Formatted Base64 cover payloads with the full Data URI scheme (`data:image/jpeg;base64,...`). This ensures Kavita writes cover images physically to disk instead of temporarily holding them in RAM cache, resolving the issue where cover uploads reverted after 2 minutes.

FR
### 🐛 Correctifs
* **Correction de l'Envoi des Couvertures Kavita (`kavita_api.py`)** : Formatage du payload Base64 avec le schéma Data URI complet (`data:image/jpeg;base64,...`). Garantit que Kavita enregistre l'image physiquement sur le disque dur au lieu de la garder temporairement en RAM (résolution du bug où l'image s'annulait au bout de 2 minutes).

## [1.5.5] - 2026-07-23 (The Deep Extraction, High-Speed Engine & Scoring Precision Update)

EN
### ⚡ High-Speed Engine & Throttling Overhaul
* **Smart Per-Provider Rate Limiter (`metadata_fetcher.py`)**: Replaced hardcoded worker sleep delays (`1.5s`/`2.5s`) with a timestamp-based dynamic throttler (`LAST_REQUEST_TIMES`). Idle APIs respond instantly with zero artificial delay, executing 3-provider Smart Fusions in ~1.6s.
* **Unrestricted Provider Forcing (`templates/index.html`, `metadata_fetcher.py`)**: Unlocked all registered scrapers in the Magic Input dropdown, allowing users to force any metadata source regardless of library type or search string.

### ✨ Deep Metadata Extraction & Unified Scoring Matrix
* **Deep Kavita Metadata Extraction (`kavita_api.py`, `app.py`)**: Pre-fetches existing metadata from Kavita's database (sanitized ISBNs, authors, publisher, release year, genres) before querying external APIs to anchor searches and prevent false positives.
* **Unified Weighted Scoring Matrix (`scrapers/utils.py`)**:
  * *ISBN Golden Rule*: Instant 100% confidence match on exact ISBN.
  * *Anti-Homonym Author Mismatch Rule*: Implemented a strict `-50%` penalty if a candidate's author differs from Kavita's context (e.g., preventing manga adaptations from matching classical novels).
  * *Roman Numeral Volume Converter*: Automatically converts Roman volume numbers (e.g. `Tome II` -> `Tome 2`) before evaluating similarity.
  * *Anti-Spin-Off & Guidebook Filters*: Added `-35%` penalty for missing distinctive query words (*Lanfeust des Étoiles* vs *Troy*) and `-50%` penalty for noise keywords (`Guidebook`, `Fanbook`, `Artbook`).
  * *Volume 1 Anchoring*: Grants `+0.10` bonus to Volume 1/unnumbered editions while applying `-0.45` penalty to intermediate volumes.

### 🦸 New Scrapers & Core Enhancements
* **ComicVine Refactor (`scrapers/comicvine.py`)**:
  * Switched volume queries to structured `/volumes/?filter=name:` endpoint with explicit `field_list`.
  * Weighted candidate selection favoring primary US/European publishers (`DC Comics`, `Marvel`, `Image`, `Dargaud`) and issue count while heavily penalizing foreign translation houses.
  * **Issue #1 Creator & Summary Fallback**: Automatically queries Issue #1 when a Volume lacks staff or description, boosting summary length from 39 chars to 3,500+ chars.
* **New Scraper Integrations**:
  * **Hardcover (Experimental)**: Hasura GraphQL & Typesense search engine for books and graphic novels (`curl_cffi` Chrome impersonation).
  * **MangaDex**: Official REST API v5 integration with content rating filters, native AniList/MAL ID extraction, and oneshot scoring.
  * **MangaUpdates**: Official REST API v1 scraper with `hit_title` matching and BBCode text cleaning.
  * **Manga-News**: Franco-Belgian & French catalog scraper (`curl_cffi`) for VF publishers and HD artwork.
  * **Shikimori**: Fast REST JSON scraper with multilingual title matching and dedicated `/roles` staff parsing.
  * **Open Library**: Literature and novel provider powered by Internet Archive.
* **Resiliency & Bug Fixes**:
  * **Bédéthèque**: Fixed duplicate method signature causing fatal `.get()` crashes on lists.
  * **MangaBaka**: Added `(data.get('authors') or [])` guards against null JSON keys causing `TypeError`.
  * **Kavita Cache Invalidation**: Dynamically clears `_series_lib_type_cache` on batch runs, recognizing updated library types (including ID 5 `Comic Flexible`) without container restarts.

FR
### ⚡ Moteur Haute Performance & Throttling Dynamique
* **Rate-Limiter Intelligente par Horodatage (`metadata_fetcher.py`)** : Remplacement des pauses fixes dans `app.py` par un régulateur dynamique basé sur `time.time()`. Les API inactives répondent instantanément sans attente artificielle, exécutant les Smart Fusions de 3 sources en ~1,6s.
* **Forçage Libre des Fournisseurs (`templates/index.html`, `metadata_fetcher.py`)** : Déblocage de l'ensemble des scrapers dans le menu déroulant du Champ Magique pour permettre le forçage manuel de n'importe quelle source.

### ✨ Extraction Profonde & Matrice de Scoring
* **Extraction Profonde Kavita (`kavita_api.py`, `app.py`)** : Récupération en amont des données existantes (ISBN, auteurs, éditeur, année) avant le scraping pour ancrer les recherches.
* **Matrice de Scoring Unifiée (`scrapers/utils.py`)** :
  * *Règle d'or ISBN* : Match instantané à 100% sur ISBN exact.
  * *Règle Anti-Homonyme Auteur* : Pénalité de `-50%` si l'auteur du candidat diffère de l'auteur dans Kavita.
  * *Convertisseur de Chiffres Romains* : Conversion automatique des tomes (`Tome II` -> `Tome 2`).
  * *Filtres Anti-Spin-Off & Anti-Guidebook* : Pénalités ciblées sur les mots-clés manquants (`-35%`) ou parasites (`-50%` pour `Guidebook`/`Fanbook`).
  * *Ancrage Tome 1* : Bonus de `+0.10` pour les Tomes 1 et pénalité de `-0.45` sur les tomes intermédiaires.

### 🦸 Nouveaux Scrapers & Améliorations Core
* **Refonte Structurée ComicVine (`scrapers/comicvine.py`)** :
  * Bascule sur l'endpoint structuré `/volumes/?filter=name:` avec `field_list` explicite.
  * Priorisation des éditeurs originaux majeurs (`DC Comics`, `Marvel`, `Image`, `Dargaud`) et pénalisation des traducteurs étrangers.
  * Récupération automatique du résumé et des auteurs sur l'Issue #1 si la fiche série est pauvre (résumés propulsés de 39 à 3 500+ caractères).
* **Nouveaux Scrapers Intégrés** :
  * **Hardcover (Expérimental)** : Moteur GraphQL Hasura & Typesense pour livres et BDs.
  * **MangaDex** : API v5 avec filtres adulte, IDs externes et scoring.
  * **MangaUpdates** : API v1 avec nettoyage BBCode et matching `hit_title`.
  * **Manga-News** : Catalogue VF (`curl_cffi`) pour éditeurs français et couvertures HD.
  * **Shikimori** : API REST JSON multilingue avec extraction du staff via `/roles`.
  * **Open Library** : API Littérature d'Internet Archive.
* **Correctifs & Stabilité** :
  * **Bédéthèque** : Correction de la méthode `fetch()` écrasée par erreur.
  * **MangaBaka** : Sécurisation contre les clés `null` dans l'API JSON.
  * **Cache Kavita** : Purge automatique du cache au lancement des batchs pour reconnaître les changements de types de bibliothèques (ID 5 `Comic Flexible`) sans redémarrer Docker.

## [1.5.4] - 2026-07-22 (The "Smart Override" & Network Flexibility Update)

EN
### ✨ New Features & Core Architecture
* **Enhanced Webhook Endpoint (`force` & Token Rotation)**: The `/webhook` endpoint now supports a `"force": true` (or `"force_update": true`) parameter in its JSON/Form payload, as well as via URL query string (`?force=true`), allowing external scripts to trigger forced metadata overwrites. Added a read-only Webhook URL input in the Config Modal with a one-click token regeneration button.
* **Reverse Proxy & Subpath Support (C17)**: Full native support for hosting MetaKavita under custom URL subpaths (e.g., `https://domain.com/metakavita`). Configurable via the `ROOT_PATH` environment variable or proxy headers (`X-Forwarded-Prefix`). Dynamically prefixes client AJAX calls and WebSocket (`Socket.IO`) connections while maintaining strict Same-Origin CORS security.
* **Disable Translation Option (BF6)**: Added a "Disabled (Keep original)" option to the Translation Provider dropdown, allowing users to preserve scraped descriptions in their original language without querying external translation APIs.
* **The "Magic Input" (Smart URL Routing)**: The old "AniList ID" override field has been completely replaced by a universal Magic Input. You can now paste a direct URL from *any* supported provider (e.g., `https://mangabaka.org/1234` or a ComicVine link) directly into the field. MetaKavita will automatically detect the domain, extract the ID, and bypass the default cascade to scrape that exact page!
* **Context-Aware Magic Dropdown**: The provider dropdown next to the Magic Input now dynamically filters its options based on the Kavita library type (e.g., hiding ComicVine for Mangas), preventing invalid manual forcing.
* **Smart ID Match Engine**: If you paste a raw numerical ID or slug and leave the dropdown on "AUTO", the system will query compatible providers and intelligently validate the match by comparing the fetched title with your Kavita title (>50% similarity required). False positives are automatically rejected and the cascade continues safely!
* **Granular Scraping (Targeted Fields)**: Worried about overwriting a summary you manually edited in Kavita? Each series now features a hidden "⚙️ Targeted Fields" dropdown. You can granularly select exactly which data MetaKavita is allowed to update (Summary, Cover, Staff, Genres, Tags, Year, Status, Publisher, Age, Format, WebLinks, Alt Titles).
* **Self-Healing Configuration Engine**: MetaKavita now dynamically validates your search cascade. If you select a default provider that has been physically deleted from the `scrapers/` folder, the engine will automatically self-heal, warn you in the logs, and safely fallback to the next available scraper to prevent your batch queues from crashing.
* **Extended Kavita API Coverage**: The staff mapping engine has been expanded. MetaKavita now natively pushes `Editors`, `Letterers`, `Inkers`, and the localized `Language` directly into Kavita's database.

### 🐛 Bug Fixes & UI Improvements
* **Google Books Stability & Anchor Match**: Refactored `googlebooks.py` to evaluate up to 10 search results using title similarity scoring (`calculate_similarity`). Implemented a Volume 1 / Band 1 priority anchor for novel series (such as *Perry Rhodan Neo*) to prevent random description shifts during batch re-syncs. Rejects candidates below 50% similarity to allow clean cascade fallback.
* **Re-integrated English Target Language**: Fixed an oversight where English (`EN`) was missing from the target translation language selection dropdown (`TARGET_LANG`).
* **Strict ID Routing**: Fixed a major bug where searching by ID would accidentally trigger title searches on fallback providers, causing chaotic metadata fusion. IDs and URLs are now strictly routed as pure ID queries exclusively to supported scrapers.
* **Alternative Titles Crash**: Fixed a fatal `TypeError` (`expected str instance, NoneType found`) that crashed the server when fusing alternative titles containing `None` values from incomplete APIs (like Kitsu).
* **Visual Feedback on Mass Actions**: The "Save All Overrides" button now features an active loading state (`⏳ Saving in progress...`) and dynamically disables itself during processing to prevent UI freezing and server saturation.

FR
### ✨ Nouvelles Fonctionnalités & Architecture
* **Endpoint Webhook Enrichi (Option `force` & Régénération de jeton)** : L'endpoint `/webhook` accepte désormais un paramètre `"force": true` (ou `"force_update": true`) dans son payload JSON/Form, ainsi que par paramètre d'URL (`?force=true`), permettant aux scripts externes d'imposer un ré-enrichissement forcé. Ajout de l'affichage de l'URL Webhook dans la modal de configuration avec un bouton de régénération du jeton.
* **Support Reverse Proxy & Sous-dossiers / Subpath (C17)** : Support natif complet pour le déploiement derrière un sous-chemin d'URL (ex: `https://domaine.com/metakavita`). Configurable via la variable d'environnement `ROOT_PATH` ou les en-têtes proxy (`X-Forwarded-Prefix`). Adapte dynamiquement les requêtes AJAX et le tunnel WebSocket (`Socket.IO`) tout en conservant la sécurité CORS Same-Origin.
* **Option de Désactivation de la Traduction (BF6)** : Ajout d'une option "Désactivé (Conserver l'original)" dans le sélecteur de traduction pour sauvegarder les résumés dans leur langue d'origine sans faire appel aux API externes.
* **Le "Champ Magique" (Routage URL Intelligent)** : L'ancien champ d'ID AniList a été remplacé par un champ universel. Vous pouvez désormais coller l'URL directe d'une œuvre provenant de *n'importe quel* fournisseur supporté (ex: une URL Bédéthèque ou MangaBaka). MetaKavita détectera automatiquement le domaine, extraira l'ID et contournera la cascade pour scraper cette page précise !
* **Menu Déroulant Contextuel** : Le menu de forçage de fournisseur à côté du champ magique s'adapte désormais dynamiquement au type de bibliothèque Kavita (ex: masquage de ComicVine pour les Mangas), évitant les erreurs de forçage.
* **Moteur "Smart ID Match"** : Si vous saisissez un ID brut (ou slug) en laissant le fournisseur sur "AUTO", le système interrogera les sites compatibles et validera les résultats en comparant le nom de la série Kavita avec le nom trouvé par l'API (nécessite >50% de ressemblance). Les faux positifs sont rejetés et la cascade continue !
* **Scraping Granulaire (Champs Ciblés)** : Peur d'écraser un résumé que vous avez tapé à la main dans Kavita ? Chaque série dispose désormais d'un menu "⚙️ Champs Ciblés". Vous pouvez cocher/décocher individuellement les 12 métadonnées que MetaKavita est autorisé à modifier.
* **Auto-Réparation de la Configuration (Self-Healing)** : MetaKavita valide dynamiquement votre cascade de recherche. Si un fournisseur par défaut a été supprimé physiquement du dossier `scrapers/`, le moteur s'auto-répare, le signale dans les logs, et bascule sur le premier scraper disponible pour empêcher le crash de vos files d'attente.
* **Couverture API Kavita Étendue** : Le moteur de mapping du staff a été complété. MetaKavita reconnait et envoie désormais les `Éditeurs` (Staff), `Lettreurs`, `Encreurs`, ainsi que la `Langue` de localisation à Kavita.

### 🐛 Corrections de Bugs & Améliorations UI
* **Stabilisation & Ancrage Google Books** : Refonte de `googlebooks.py` pour évaluer jusqu'à 10 résultats via un score de similarité (`calculate_similarity`). Ajout d'un ancrage prioritaire sur le Tome 1 / Band 1 pour les séries de romans (ex: *Perry Rhodan Neo*) afin d'éviter le changement aléatoire de résumé lors des re-synchronisations. Rejet des résultats <50% de similarité pour basculer proprement sur la suite de la cascade.
* **Réintégration de l'Anglais en Langue Cible** : Correction d'un oubli où l'anglais (`EN`) manquait dans la liste déroulante des langues de traduction (`TARGET_LANG`).
* **Routage Strict des IDs** : Résolution d'un bug critique où la recherche par ID déclenchait accidentellement une recherche par titre sur les fournisseurs de secours, créant des fusions de métadonnées chaotiques. Les URLs et IDs sont désormais strictement routés.
* **Crash des Titres Alternatifs** : Correction d'une erreur fatale `TypeError` (`expected str instance, NoneType found`) qui faisait crasher le serveur lors de la fusion de titres alternatifs contenant des valeurs `None` (souvent renvoyées par Kitsu).
* **Feedback Visuel de Masse** : Le bouton "Tout sauvegarder d'un coup" affiche désormais un état de chargement dynamique (`⏳ Sauvegarde en cours...`) et se verrouille le temps du traitement pour éviter de saturer le serveur ou de freezer l'interface.

## [1.5.2] - 2026-07-21 (The Plug & Play Architecture Update)

EN
### 🐛 Bug Fixes & Refinements
* **Context-Aware Cover Fetching**: Fixed a regression where the manual cover search queried all scrapers blindly. The system now dynamically filters active scrapers based on the Kavita `library_type` (e.g., Manga, Comic) and passes this context to adapt the title cleaning rules (fixing the `unexpected keyword argument` crash).
* **Bédéthèque Spin-off Override Bug**: Fixed an issue where searching for a main series (e.g., "La Quête d'Ewilan") would return covers from its spin-offs (e.g., "Ellana") due to Bédéthèque's alphabetical sorting. Implemented an exact-match logic that delays the loop-break, evaluating all title variations (with and without articles) to guarantee the parent series is pushed to the top of the results.

### 🧱 Plug & Play Scraper Architecture
* **Auto-Discovery Registry**: Refactored the core engine to use a Registry pattern (`ScraperRegistry`). Scrapers are now dynamically loaded from the `scrapers/` folder on startup. Adding a new provider is now as simple as dropping a `.py` file.
* **Standardized Base Interface**: Introduced the `BaseScraper` abstract class, enforcing a strict contract (ID, display name, supported library types, rate limits, and proxy domains) for all metadata providers.
* **Dynamic UI Generation**: The global configuration modal (`index.html`) and the provider cascading logic now dynamically generate dropdowns and fallback rules based on currently active scrapers. No more hardcoding!
* **Decoupled Utilities**: Extracted `clean_title` logic into a dedicated `scrapers/utils.py` module to ensure adherence to the Single Responsibility Principle and prevent circular dependencies.

### New Provider: Bédéthèque Scraper
* **Full Integration**: Added a dedicated scraper for Bédéthèque, heavily optimized for Franco-Belgian Comics.
* **Anti-Bot & CSRF Bypass**: Leveraged `curl_cffi` and dynamic CSRF token extraction (`csrf_token_bel`) to seamlessly bypass Bédéthèque's aggressive anti-scraping firewalls.
* **Smart Summary Recovery**: Bédéthèque often leaves Series descriptions empty. The scraper intelligently falls back to the Tome 1 (Album) summary, and utilizes SEO `og:description` meta tags as a bulletproof extraction method if HTML structures change.
* **Surgical Staff Parsing**: Automatically identifies roles (Scénario, Dessin, Couleurs) and reformats author names from "Lastname, Firstname" to "Firstname Lastname" for a pristine display in Kavita.

🇫🇷
### 🐛 Corrections de Bugs & Améliorations
* **Recherche de Couvertures Contextuelle** : Correction d'une régression où la recherche manuelle d'images interrogeait tous les fournisseurs à l'aveugle. Le système filtre désormais dynamiquement les scrapers selon le type de bibliothèque (`Manga`, `Comic`, `Book`) et transmet ce contexte pour adapter le nettoyage du titre (ce qui corrige au passage l'erreur fatale `unexpected keyword argument`).
* **Bug d'Écrasement par les Spin-offs (Bédéthèque)** : Résolution d'un problème où la recherche d'une série principale (ex: "La Quête d'Ewilan") renvoyait les couvertures de son spin-off (ex: "Ellana") à cause du tri alphabétique natif de Bédéthèque. Ajout d'une logique de "match exact" qui évalue toutes les variations de titres (gestion des articles "Le", "La") pour garantir que la série mère remonte en première position.

### 🧱 Architecture Scraper "Plug & Play"
* **Découverte Automatique (Registry)** : Refonte totale du cœur de l'application avec un pattern Registre (`ScraperRegistry`). Les scrapers sont désormais chargés dynamiquement au démarrage depuis le dossier `scrapers/`. Ajouter un nouveau site se résume à glisser un fichier python. Fin du hardcoding !
* **Interface Standardisée** : Création de la classe abstraite `BaseScraper` qui impose un contrat strict (ID, nom public, types de bibliothèques supportés, délais entre requêtes, domaines proxy anti-SSRF) à tous les fournisseurs.
* **Génération Dynamique de l'UI** : Les menus déroulants de la modale de configuration et le routage interne s'adaptent désormais dynamiquement aux scrapers détectés par le système.
* **Utilitaires Découplés** : Déplacement de la fonction de nettoyage `clean_title` vers un module autonome `scrapers/utils.py` pour un code plus propre et sans dépendances circulaires.

### 🇫🇷 Nouveau Fournisseur : Bédéthèque
* **Intégration Bédéthèque** : Ajout d'un scraper ultra-spécialisé pour la base de données de référence de la bande dessinée franco-belge.
* **Contournement Anti-Bot (CSRF)** : Utilisation de `curl_cffi` et récupération à la volée des jetons de sécurité HTTP (`csrf_token_bel`) pour esquiver les pare-feux et blocages IP restrictifs de Bédéthèque.
* **Récupération Intelligente des Résumés** : La page "Série" est souvent vide sur Bédéthèque. Le scraper est conçu pour piocher intelligemment le résumé sur l'Album (Tome 1) en cas d'échec. Il utilise également la balise SEO `og:description` comme méthode de secours absolue pour garantir un résultat.
* **Parsing Chirurgical du Staff** : Extraction précise des rôles (Scénario, Dessin, Couleurs) et reformatage automatique des noms d'auteurs ("Nom, Prénom" devient "Prénom Nom") pour un affichage esthétique dans Kavita.

## [1.5.0] - 2026-07-20 (The Multi-Media & Resiliency Update)

EN
### 🚀 Kitsu Integration & Provider Purge
* **Kitsu JSON:API Integration**: Added `scrapers/kitsu.py` using the free, open, and blazing-fast Kitsu API (no API key required). It fetches incredibly rich metadata and completely replaces our initial tests with MyAnimeList/Jikan (which suffered from heavy 504 Gateway Timeouts).
* **Nautiljon Purge**: Due to highly aggressive Cloudflare IP banning policies and an archaic anti-scraping stance, Nautiljon has been completely removed from the default provider cascades and routing maps.

### 🌐 Zero-Config Translation & Resilient Pipeline
* **Zero-Config Google Translate**: Integrated `py-googletrans` (v4.0.0-rc1) to provide 100% free, unlimited translations out of the box without requiring any API keys. Azure and DeepL remain available for enterprise-grade stability, but Google Translate acts as the ultimate magic fallback.
* **Azure & DeepL Integration**: Integrated Microsoft Azure Translator as the primary translation engine (2M characters/month F0 free tier) with DeepL as an automatic fail-safe fallback in case of HTTP 403, 429, or 456 quota exceptions.
* **Azure Translator Hardening**: Added explicit payload and HTTP response debug logging to easily diagnose Microsoft Azure API rejections.

### 🎨 Translation UI & Settings Reorganization
* **Dynamic Translation Provider UI**: Added a clean dropdown in the settings modal to select the active translation engine (Google, Azure, DeepL). Irrelevant API key fields are now dynamically hidden to reduce UI clutter.
* **Settings Modal Reorganization**: Improved the Global Configuration layout using semantic CSS columns to neatly group Provider API Keys under Kavita's connection settings.

### 🧩 Dynamic Routing & Scraper Factory
* **Scraper Factory Pattern**: Refactored `PROVIDERS_MAP` in `metadata_fetcher.py` into a nested map structure indexed by Kavita's exact library types (`Manga`, `Comic`, `Book`). Implemented a resilient fallback system in `get_scraper_engine` to handle mismatched requests.
* **Kavita Library Type Extraction**: Updated `kavita_api.py` to extract the `type` property of libraries and map them to standard string representations (`Manga`, `Comic`, `Book`). Added an in-memory cache to prevent redundant API calls during batch syncing.
* **Global Server Batch Support**: Enhanced `/batch-sync` execution to allow full server syncing. If no specific library is selected, the system dynamically iterates through all libraries and routes them according to their individual library types.

### 🦸 Hybrid ComicVine Scraper (Ultimate)
* **Two-Step Resolution Flow**: Implemented `scrapers/comicvine.py` using a dual-request approach (Volume Search ➡️ Fallback to Issue Search ➡️ Resolve Parent Volume ➡️ Fetch detailed metadata) to resolve French/European BD albums.
* **String Similarity Validator**: Integrated a hybrid scoring engine (`difflib.SequenceMatcher` + Token intersection) to strictly validate search results and drastically reduce false-positive matches on vaguely similar titles.
* **In-Memory Homonym Recovery**: Designed an automatic fallback search that sorts homonym volumes by issue count and pulls metadata from highly populated entries (e.g. Gaston 2009) if the resolved entry is an empty reissue stub.
* **Noisy HTML Pruning**: Added a custom HTML stripper to automatically delete structural wiki sections ("Publishers", "Collected Editions") that cluttered the final summary.
* **Komf-Aligned Credits Mapping**: Standardized artist and author role matching (`person_credits`) to align with Komf's mapping rules, populating Kavita's extended staff fields.

### 📖 Production Google Books Scraper
* **Full Implementation**: Replaced the testing stub with a production-ready Google Books API scraper to fetch rich metadata for Novels and Western/European Comics (ISBN-compatible).
* **Dynamic Internationalization**: Google Books searches (`langRestrict`) are now dynamically bound to the user's `TARGET_LANG` configuration, ensuring native language summaries whenever possible.
* **API Key Support**: Added `GOOGLEBOOKS_API_KEY` to the global configuration to prevent HTTP 429 (Too Many Requests) limits on self-hosted instances.

### 🧹 Contextual Title Cleaning
* **Clean Title Contexts**: Adapted `clean_title` to clean queries based on library types. Comics/BDs safely strip noise leading zeros (e.g., `04 ` or `04 - `) while preserving issue/tome numbering. Books isolate `"Title - Author"` splits cleanly.

### 🐛 Bug Fixes
* **Metadata Corruption Lock (Age & Format)**: Fixed a logic bug in `app.py` where `ageRatingLocked` and `formatLocked` were forcefully applied to Kavita even when scrapers returned unmapped/unknown values, which silently erased existing database values.
* **MangaBaka Silent Crash**: Fixed a `NoneType` iteration bug that silently killed the Smart Completion fusion when MangaBaka returned null tags.
* **Auto-Reading Direction Deduction**: MangaBaka now safely and intelligently deduces the Reading Format (Manga vs Webtoon) by inspecting its own tags/genres if the API doesn't explicitly provide it.
* **Env Var Override Lock**: Fixed an issue where Docker environment variables (like `ADMIN_PASSWORD`) would override the user's manual UI changes upon container restart. `config.json` now acts as the absolute source of truth.
* **Hard Logout Cleansing**: Secured the `/logout` route to physically destroy the session cookie (`expires=0`) on the client side, ensuring a clean re-authentication state.

FR
### 🚀 Intégration de Kitsu & Purge de Nautiljon
* **Intégration Kitsu JSON:API** : Ajout de `scrapers/kitsu.py` exploitant l'API publique de Kitsu (sans clé requise et ultra-rapide). Récupère des métadonnées riches et remplace nos essais avortés avec MyAnimeList/Jikan (qui souffrait d'erreurs 504 en boucle).
* **Retraite de Nautiljon** : Face aux bannissements IP abusifs et imprévisibles de leur pare-feu Cloudflare, Nautiljon a été totalement éradiqué du routage et des cascades par défaut.

### 🌐 Google Translate "Zero-Config" & Résilience
* **Google Translate (Gratuit)** : Intégration de `py-googletrans` (v4.0.0-rc1) offrant des traductions 100% gratuites et illimitées dès l'installation, sans aucune clé d'API requise. Azure et DeepL restent disponibles pour une stabilité maximale, mais Google prendra le relais de manière transparente !
* **Intégration d'Azure & DeepL** : Ajout de Microsoft Azure Translator comme moteur principal (F0, 2M de caractères gratuits par mois) avec bascule automatique vers DeepL en cas d'erreur de quota.
* **Fiabilisation Azure Translator** : Ajout de logs de diagnostic explicites (taille du payload, région, requêtes brutes) pour tracer et comprendre instantanément les rejets de l'API Microsoft.

### 🎨 UI du Traducteur & Réorganisation
* **Sélecteur Dynamique de Traduction** : Ajout d'un menu déroulant intuitif dans la configuration pour choisir son moteur de traduction (Google, Azure, DeepL). Les champs de clés API inutiles sont masqués dynamiquement pour épurer l'interface.
* **Réorganisation de la Modal** : Amélioration de la grille CSS pour regrouper proprement les clés d'API des fournisseurs de métadonnées juste sous les identifiants Kavita.

### 🧩 Routage Dynamique & Scraper Factory
* **Architecture Scraper Factory** : Restructuration de `PROVIDERS_MAP` en dictionnaire imbriqué indexé par type exact de bibliothèque Kavita (`Manga`, `Comic`, `Book`). Implémentation d'un système de repli résilient vers les mangas en cas d'erreur.
* **Détection du Type de Bibliothèque** : Extraction de la propriété `type` des bibliothèques Kavita avec mise en cache mémoire pour optimiser les appels d'API.
* **Support du Batch Global** : Amélioration de la file d'attente `/batch-sync` pour lancer une synchronisation à l'échelle du serveur entier. En l'absence de sélection, le système traite l'intégralité du serveur en appliquant le routage dynamique à la volée.

### 🦸 Scraper ComicVine Hybride (Ultime)
* **Recherche en Deux Étapes** : Interrogation des volumes, puis des issues (albums) en cas d'échec pour remonter vers la série parente. Résout les albums franco-belges orphelins.
* **Validateur de Similarité** : Implémentation d'un algorithme de score hybride (`difflib` + intersection de mots-clés) pour écarter rigoureusement les faux-positifs lors des recherches floues de l'API.
* **Résolution d'Homonymes Vides** : Tri des homonymes par nombre de tomes décroissant pour extraire la description d'une édition majeure rédigée si l'édition active est vide.
* **Nettoyage HTML Anti-Bruit** : Suppression automatique des sections wiki structurelles (Éditeurs, Éditions compilées, etc.) qui polluaient le résumé final.
* **Mappage de Staff** : Normalisation de la récupération du staff créateur pour alimenter proprement les rôles dans Kavita (Scénario, Dessin, Couleur, etc.).

### 📖 Scraper Google Books de Production
* **Implémentation Complète** : Remplacement du bouchon de test par un scraper Google Books officiel, capable d'enrichir les Romans et les BD européennes (via la catégorie Comic).
* **Internationalisation Dynamique** : Les recherches Google Books (`langRestrict`) s'adaptent désormais automatiquement à la `Langue de traduction` choisie par l'utilisateur pour trouver la bonne édition.
* **Support de Clé API** : Ajout du champ `GOOGLEBOOKS_API_KEY` pour éviter l'erreur HTTP 429 (Trop de requêtes) inhérente aux serveurs auto-hébergés.

### 🧹 Nettoyage Contextuel de Titres
* **Nettoyage Adaptatif** : Ajustement de `clean_title` selon le format du média. La catégorie Comics nettoie proprement les préfixes de tri sans casser les œuvres aux noms chiffrés. Les romans isolent les structures `"Titre - Auteur"`.

### 🐛 Corrections de Bugs
* **Corruption de Métadonnées Kavita** : Correction d'un bug critique dans `app.py` où les champs `ageRatingLocked` et `formatLocked` étaient verrouillés à vide si un scraper renvoyait une valeur inconnue, écrasant ainsi les données préexistantes de Kavita.
* **Crash Silencieux MangaBaka** : Résolution d'une erreur `NoneType` qui annulait silencieusement la fusion intelligente (Smart Completion) lorsque l'API renvoyait des tags vides.
* **Sens de Lecture Automatique** : Le scraper MangaBaka déduit désormais intelligemment le format de lecture (Webtoon vs Manga) en analysant ses propres mots-clés.
* **Verrouillage des Variables d'Environnement** : Correction d'un bug où les variables Docker (ex: `ADMIN_PASSWORD`) écrasaient la configuration de l'utilisateur au redémarrage. Le fichier `config.json` a désormais la priorité absolue.
* **Nettoyage de Session** : Sécurisation de la route `/logout` qui force désormais l'expiration physique du cookie de session côté navigateur.

---

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
* **Advanced Stripping:** The engine strips stray dots, `[Team]` prefixes, edition keywords (`Omnibus`, `Perfect Edition`), and volume numbers (`01 - Title`), improving the API match rate.

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
* **Filtrage Avancé :** Le moteur supprime les points, les préfixes de scantrad, les mots-clés (`Intégrale`, `Deluxe Edition`) et les numéros de dossiers complexes, propulsant le taux de réussite des API.

### 📚 Métadonnées Kavita Étendues
* **Staff et Détails :** MetaKavita gère désormais les Éditeurs, la classification d'Âge, les Coloristes, Traducteurs, et Artistes de Couverture.
* **IDs et Liens Externes :** Remplissage automatique des champs `AniListId`, `MalId`, et `MangaBakaId`. Génération de WebLinks cliquables pour afficher les icônes officielles dans Kavita !
* **Sens de Lecture :** Nouvelle option permettant d'adapter automatiquement le sens de lecture (Manga, Webtoon) selon l'origine de l'œuvre.

### 🎨 Améliorations UI
* **Barre de recherche AJAX :** Filtrez vos centaines de séries instantanément en temps réel.