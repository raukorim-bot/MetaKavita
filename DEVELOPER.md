# MetaKavita - Developer & Contribution Guide

This guide is designed for developers and AI assistants wishing to understand, maintain, or extend the MetaKavita codebase. 

---

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
   * [1. Global Architecture & Security](#1-global-architecture--security)
   * [2. Frontend Mechanics (V1.5.0)](#2-frontend-mechanics-v150)
   * [3. Scraper Factory & Dynamic Category Routing](#3-scraper-factory--dynamic-category-routing)
   * [4. Resilient Translation Pipeline](#4-resilient-translation-pipeline)
   * [5. AI-Powered Scraper Creation (Vibecoding)](#5-ai-powered-scraper-creation-vibecoding)
   * [6. API Keys & Third-Party Services](#6-api-keys--third-party-services)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)
   * [1. Architecture Globale & Sécurité](#1-architecture-globale--sécurité-1)
   * [2. Mécanismes Frontend (V1.5.0)](#2-mécanismes-frontend-v150-1)
   * [3. Scraper Factory & Routage Dynamique](#3-scraper-factory--routage-dynamique)
   * [4. Pipeline de Traduction Abstrait](#4-pipeline-de-traduction-abstrait)
   * [5. Création de Scrapers via IA (Vibecoding)](#5-création-de-scrapers-via-ia-vibecoding-1)
   * [6. Clés API & Services Tiers](#6-clés-api--services-tiers)

---

## 🇺🇸 English Developer Guide

### 1. Global Architecture & Security
MetaKavita is an asynchronous Python application powered by a **Gunicorn WSGI server** with **Eventlet** workers to support real-time WebSockets via Flask-SocketIO.

*   **Security Layer:** Global authentication is enforced via `@app.before_request`. Session cookies are configured as `HttpOnly` and `SameSite=Lax`.
*   **Timing Attack Protection:** The login system uses `secrets.compare_digest` to prevent timing analysis of passwords, paired with a brute-force delay on failure.
*   **SSRF Protection:** The `/api/proxy-image` route uses dynamic strict whitelisting. If you add a new scraper, **you must add its domain** to the `ALLOWED_PROXY_DOMAINS` list in `metadata_fetcher.py`.
*   **Webhook Hardening:** Webhooks require a cryptographically secure `WEBHOOK_TOKEN` generated in `config.json`.
*   **API Keys Masking:** All sensitive API keys (`KAVITA_API_KEY`, `DEEPL_API_KEY`, `AZURE_API_KEY`, `COMICVINE_API_KEY`, `GOOGLEBOOKS_API_KEY`) are censored with `********` on DOM generation to protect credentials from shoulder-surfing or browser extension scraping.

---

### 2. Frontend Mechanics (V1.5.0)

#### A. Hybrid AJAX Configuration Saving
To preserve ergonomics, persistent technical parameters sit inside `#configForm` in the settings Modal, while active scraping checkboxes (smart completion, auto cover, reading direction, force update) are located in the sidebar.
*   **The Mechanism:** When `saveConfig()` is triggered in `script.js`, it serializes `#configForm` into a `FormData` object, manually queries the sidebar checkboxes, and appends them to the payload. This allows single-endpoint backend writing without reloads.

#### B. Workspace Persistence
Any change to filter inputs (status, library, search query) is stored in `localStorage` and automatically restored on load.
*   **Library Autoload:** If the user visits `/` and has a saved library ID in `localStorage`, the JS router automatically executes `loadLibrary()` to load the saved library without manual intervention.

#### C. Log Parsing & Active Highlighting
The WebSocket log receiver inside `script.js` parses incoming backend log messages in real-time.
*   **Highlight Trigger:** A regex detects `▶️ [Series Name] Début` / `Starting` log events, locates the corresponding list item, applies the `.is-processing` pulsing CSS class, and smooth-scrolls the active card into view.
*   **Resolution Trigger:** When finishing logs are received (matching standard ending symbols like `✅`, `❌`, `⚠️`), the `.is-processing` class is removed and badges are dynamically updated in-place.

---

### 3. Auto-Discovery Registry & Dynamic Routing (V1.5.2+)

MetaKavita automatically queries the Kavita API to detect library categories (`Manga = 0`, `Comic = 1`, `Book = 2`).

Instead of a hardcoded map, MetaKavita now uses an **Auto-Discovery Registry pattern**. On startup, `scrapers/__init__.py` scans the `scrapers/` folder and dynamically loads any class inheriting from `BaseScraper`. 

```python
# The BaseScraper Contract
class BaseScraper(ABC):
    id: str = ""
    display_name: str = ""
    supported_types: Set[str] = set() # e.g., {"Manga", "Comic"}
    rate_limit: float = 1.0
    proxy_domains: List[str] = []
    
    @abstractmethod
    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False): ...
    def fetch_covers(self, query: str, library_type: str = "Manga"): ...
```
*   **Dynamic UI & Routing:** The UI dropdowns and the backend routing (metadata_fetcher.py) automatically query ScraperRegistry.get_by_type(library_type) to generate fallback cascades and route requests without any hardcoded logic.
*   **Contextual Title Cleaning:** The clean_title function in scrapers/utils.py cleans queries contextually based on the targeted media type (stripping leading zeros in comics, isolating "Title - Author" in books, etc.).

> **📜 Historical Note on Nautiljon & MyAnimeList (MAL)**: You might notice the absence of the French provider *Nautiljon*. Their admins are from another era and are terrified of their processors heating up, resulting in abusive Cloudflare IP bans. We initially replaced it with the MyAnimeList Jikan API (`scrapers/mal.py`), but that story will end badly too: MAL is aggressively blocking Jikan's servers, causing constant 504 Gateway Timeouts, and the public Jikan API is shutting down. We left `mal.py` in the codebase for users who self-host a Jikan instance, but the default reliable engine is now **Kitsu** thanks to their glorious JSON:API.

*   **Scraper Engine Selection**: The function `get_scraper_engine(library_type, provider_name)` selects the correct scraper according to the library type. If a requested provider is missing from the specific category, it automatically falls back to default Manga providers.
*   **Contextual Title Cleaning**: The `clean_title` function in `scrapers/__init__.py` cleans queries contextually:
    *   *Manga*: Normalizes names, removes scanlation brackets, and strips volume/chapter suffixes.
    *   *Comic*: Safely cleans leading sorting prefixes (e.g., `04 ` or `04 - `) while preserving internal volume and issue numbering (e.g. protecting titles like *100 Bullets*).
    *   *Book*: Automatically isolates `"Title - Author"` and `"Author - Title"` splits.

---

### 4. Resilient Translation Pipeline
All translation operations are abstracted inside `translator.py` and utilize a 3-tier cascade to ensure 100% success rate.

*   **Tier 1: Microsoft Azure Translator** (F0 tier, 2M chars/month free) - Recommended primary engine.
*   **Tier 2: DeepL API** (Free tier, 1M chars lifetime limit) - Excellent automatic fail-safe.
*   **Tier 3: Google Translate ("Zero-Config" Fallback)** - Implemented using the unofficial [py-googletrans](https://github.com/ssut/py-googletrans) Python library (specifically version `4.0.0-rc1` to bypass recent API changes). It requires absolutely NO API key and acts as the ultimate free fallback out-of-the-box if no keys are provided or if the paid APIs crash.

---

### 5. AI-Powered Scraper Creation (Vibecoding)

Thanks to the new **Plug & Play Auto-Discovery Architecture** (v1.5.2+), you never have to touch the core application routing, HTML, or configurations to add a new metadata source. You simply drop a `.py` file into the `scrapers/` folder.

If you are using an AI assistant (ChatGPT, Claude, Claude-Dev, Cursor) to write a new scraper, you can use the following "Vibecoding" prompt. It gives the LLM the exact interface contract to follow.

#### The Ultimate AI Prompt Template
Copy and paste this prompt to your favorite LLM:

> "Act as an Expert Python Developer. I am building a metadata scraper for an application.
> I need you to write a new scraper for the website **[INSERT WEBSITE NAME OR API HERE]**.
> 
> My application uses an Auto-Discovery Registry. You just need to create a class that inherits from `BaseScraper`. Do not write any external routing code.
> 
> Here is the exact `BaseScraper` contract you must implement:
> ```python
> from typing import Dict, Any, List, Optional, Set
> from scrapers.base import BaseScraper
> from scrapers.utils import clean_title
> import logging
> 
> class MyNewScraper(BaseScraper):
>     id = "UNIQUE_ID" # e.g., "MANGADEX"
>     display_name = "Public Name (Format)" # e.g., "MangaDex (API)"
>     supported_types = {"Manga"} # Can be "Manga", "Comic", or "Book"
>     rate_limit = 1.0 # Delay in seconds between requests
>     proxy_domains = ["domain.com"] # Domains allowed for image proxy
> 
>     def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False) -> Optional[Dict[str, Any]]:
>         clean = clean_title(query, library_type=library_type)
>         # SCRAPING LOGIC HERE
>         # MUST return None if failed, or exactly this dictionary:
>         '''
>         {
>             'summary': 'str',                  # Description
>             'cover_url': 'str',                # Main cover image URL
>             'genres': ['list'],                # Main genres
>             'tags': ['list'],                  # Themes/tags (max 15)
>             'year': int,                       # Publication start year
>             'status': 'RELEASING/FINISHED/HIATUS/CANCELLED',
>             'staff': [{'role': 'Story/Art/Color/Translator', 'node': {'name': {'full': 'Author Name'}}}],
>             'publisher': 'str',                # Official publisher
>             'age_rating': 'safe/suggestive/pornographic',
>             'format': 'manga/webtoon/comic/book',
>             'url': 'str_url_of_the_page',      # Direct link to the series page
>             'links': ['list_of_urls']          # Additional reference links
>         }
>         '''
>         pass
> 
>     def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
>         # SCRAPING LOGIC FOR COVERS ONLY
>         # MUST return a list of dicts: [{"provider": self.display_name, "title": "Album Title", "url": "Image URL"}]
>         pass
> ```
> 
> **Important rules:**
> 1. Use `curl_cffi` (requests) or standard `requests`, and `BeautifulSoup` if HTML parsing is needed.
> 2. Handle exceptions gracefully and return `None` (or an empty list `[]` for covers) on failure.
> 3. Use `clean_title` to format the user's query before searching.
> Please generate the complete scraper class."

Once generated, name the file `myscraper.py`, drop it into the `scrapers/` folder, and restart the server. MetaKavita will automatically detect it, add it to the UI settings, and route requests to it! (perhaps you need to debug it ;) )

---

### 6. API Keys & Third-Party Services
To fully test and run the scraping environment, you might need to generate personal API keys for the integrated providers:
*   **DeepL API Free**: [DeepL Pro API](https://www.deepl.com/pro-api) (Key must end with `:fx`)
*   **Azure Translator**: [Azure Portal](https://portal.azure.com/) (F0 Free Tier, 2M chars/month)
*   **ComicVine**: [ComicVine API](https://comicvine.gamespot.com/api/) (Requires a free GameSpot account)
*   **Google Books**: [Google Cloud Console](https://console.cloud.google.com/) (Enable "Books API" and generate an API key)

---

## 🇫🇷 Guide de Développement Français

### 1. Architecture Globale & Sécurité
MetaKavita est une application Python asynchrone fonctionnant derrière un **serveur WSGI Gunicorn** couplé à des workers **Eventlet** pour supporter les WebSockets en temps réel via Flask-SocketIO.

*   **Authentification :** Sécurisée au niveau global via `@app.before_request`. Les cookies de session sont configurés en `HttpOnly` et `SameSite=Lax`.
*   **Attaques Temporelles (Timing Attacks) :** Le système de connexion utilise `secrets.compare_digest` pour empêcher l'analyse du temps de réponse lors de la comparaison des mots de passe.
*   **Protection SSRF :** La route de proxy d'images `/api/proxy-image` utilise une liste blanche de domaines stricte. Si vous ajoutez un nouveau scraper, **vous devez ajouter son domaine** à la liste `ALLOWED_PROXY_DOMAINS` dans `metadata_fetcher.py`.
*   **Sécurisation Webhook :** L'endpoint webhook exige la clé cryptographique `WEBHOOK_TOKEN` générée dans `config.json`.
*   **Censure de sécurité des clés :** Toutes les clés d'API sensibles (`KAVITA_API_KEY`, `DEEPL_API_KEY`, `AZURE_API_KEY`, `COMICVINE_API_KEY`, `GOOGLEBOOKS_API_KEY`) sont remplacées par `********` lors de la génération du DOM pour protéger vos identifiants des regards indiscrets et des extensions de navigateur malveillantes.

---

### 2. Mécanismes Frontend (V1.5.0)

#### A. Sauvegarde Hybride (AJAX)
Pour conserver une ergonomie propre, les paramètres techniques résident dans le formulaire `#configForm` de la Modal, tandis que les options de scraping stratégiques (fusion intelligente, auto cover, sens de lecture, mise à jour forcée) résident dans la sidebar.
*   **Fonctionnement :** Lorsque la fonction `saveConfig()` est exécutée, elle sérialise `#configForm`, récupère manuellement l'état des cases d'options latérales, et assemble le tout dans un unique payload AJAX vers `/save-config`. Cela permet un enregistrement transparent sans recharger la page.

#### B. Persistance de l'Espace de Travail
Toute modification des filtres (bibliothèque, recherche, statut, masquage des ignorés) est stockée dans le `localStorage` du navigateur.
*   **Auto-chargement :** Si l'utilisateur visite `/` et possède un ID de bibliothèque mémorisé, le routeur JS exécute automatiquement `loadLibrary()` pour restaurer instantanément sa session de travail.

#### C. Suivi Live & Logs WebSockets
Le récepteur WebSocket de `script.js` analyse en direct le flux de logs renvoyé par la file d'attente asynchrone du serveur.
*   **Détection de Début :** Une expression régulière cherche le motif `▶️ [Nom de la série] Début` / `Starting`, applique la classe CSS de pulsation `.is-processing` sur la ligne correspondante et force un défilement fluide (*smooth-scroll*) vers celle-ci.
*   **Détection de Fin :** À la réception des icônes de fin de tâche (`✅`, `❌`, `⚠️`), la classe de pulsation est retirée et le badge de statut se met à jour dynamiquement.

---

### 3. Auto-Découverte (Registry) & Routage Dynamique (V1.5.2+)

L'application interroge Kavita pour détecter le type exact de la bibliothèque (`Manga = 0`, `Comic = 1`, `Book = 2`).

Fini les dictionnaires codés en dur ! MetaKavita utilise désormais un **Pattern Registre par Auto-Découverte**. Au démarrage, `scrapers/__init__.py` scanne le dossier `scrapers/` et charge dynamiquement toutes les classes héritant de `BaseScraper`.

```python
# Le Contrat BaseScraper
class BaseScraper(ABC):
    id: str = ""
    display_name: str = ""
    supported_types: Set[str] = set() # ex: {"Manga", "Comic"}
    rate_limit: float = 1.0
    proxy_domains: List[str] = []
    
    @abstractmethod
    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False): ...
    def fetch_covers(self, query: str, library_type: str = "Manga"): ...
```
* **Routage & UI Dynamiques :** Les menus déroulants de l'interface et le moteur de recherche (metadata_fetcher.py) interrogent ScraperRegistry.get_by_type(library_type) pour s'adapter aux scrapers installés sans aucune modification manuelle.
* **Nettoyage Contextuel de Titre :** La fonction clean_title dans scrapers/utils.py s'adapte au format de l'œuvre (suppression des zéros de tri pour les comics, isolation "Titre - Auteur" pour les livres, etc.).

> **📜 Note historique sur Nautiljon et MyAnimeList (MAL)** : Vous remarquerez l'absence du fournisseur francophone *Nautiljon*. Leurs administrateurs sont d'un autre temps et paniquent à l'idée que leurs processeurs chauffent, distribuant des bans IP Cloudflare à tour de bras. Nous l'avions remplacé par MyAnimeList via l'API Jikan (`scrapers/mal.py`), mais l'histoire finit mal : MAL bloquant agressivement les serveurs de Jikan (erreurs 504), l'API publique ferme bientôt. Le fichier `mal.py` reste dans le code pour ceux qui auto-hébergent Jikan, mais le moteur par défaut est désormais **Kitsu** avec sa superbe API JSON ouverte et gratuite.

*   **Sélection de Scraper** : La fonction `get_scraper_engine(library_type, provider_name)` résout le scraper à appeler dans `PROVIDERS_MAP` selon la catégorie de l'œuvre. Si le fournisseur est absent de cette catégorie, elle applique un repli automatique vers les scrapers Manga généraux.
*   **Nettoyage Contextuel de Titre** : La fonction `clean_title` dans `scrapers/__init__.py` s'adapte au format de l'œuvre :
    *   *Manga* : Normalise, retire les balises de scantrad et supprime les suffixes de tomes ou volumes.
    *   *Comic* : Nettoie proprement les préfixes de tri (ex: `"04 Le bureau..."` devient `"Le bureau..."`) tout en protégeant les œuvres aux noms chiffrés (ex: *100 Bullets*).
    *   *Book* : Isole proprement les structures `"Titre - Auteur"` et `"Auteur - Titre"`.

---

### 4. Pipeline de Traduction Abstrait
Toutes les opérations de traduction sont centralisées dans `translator.py` et utilisent une cascade à 3 niveaux pour garantir 100% de réussite.

*   **Niveau 1 : Microsoft Azure Translator** (F0, 2M caractères gratuits/mois) - Moteur principal recommandé.
*   **Niveau 2 : DeepL API** (1M caractères gratuits à vie) - Excellent système de secours automatique.
*   **Niveau 3 : Google Translate ("Zero-Config")** - Implémenté de manière non officielle via la librairie Python [py-googletrans](https://github.com/ssut/py-googletrans) (plus précisément la version `4.0.0-rc1`). Il ne nécessite AUCUNE clé API et s'exécute magiquement par défaut à l'installation, ou prend le relais si les quotas Azure/DeepL explosent.

---

### 5. Création de Scrapers via IA (Vibecoding)

Grâce à la nouvelle **Architecture Plug & Play par Auto-Découverte** (v1.5.2+), tu n'as plus jamais besoin de modifier le code de routage, le HTML ou les configurations de l'application pour ajouter une source de métadonnées. Il te suffit de glisser un fichier `.py` dans le dossier `scrapers/`.

Si tu utilises une IA (ChatGPT, Claude, Cursor) pour écrire un nouveau scraper, utilise le prompt de "Vibecoding" suivant. Il fournit au LLM le contrat d'interface exact à respecter.

#### Le Prompt IA Ultime
Copie-colle ce texte à ton IA favorite :

> "Agis en tant que Développeur Python Expert. Je construis un scraper de métadonnées pour mon application.
> J'ai besoin que tu écrives un scraper pour le site **[INSÉRER LE NOM DU SITE OU DE L'API ICI]**.
> 
> Mon application utilise un système de Registre par Auto-Découverte. Tu dois juste créer une classe qui hérite de `BaseScraper`. N'écris aucun code de routage externe.
> 
> Voici le contrat exact de `BaseScraper` que tu dois implémenter :
> ```python
> from typing import Dict, Any, List, Optional, Set
> from scrapers.base import BaseScraper
> from scrapers.utils import clean_title
> import logging
> 
> class MyNewScraper(BaseScraper):
>     id = "UNIQUE_ID" # ex: "MANGADEX"
>     display_name = "Nom Public (Format)" # ex: "MangaDex (API)"
>     supported_types = {"Manga"} # Peut inclure "Manga", "Comic", ou "Book"
>     rate_limit = 1.0 # Délai en secondes entre deux requêtes
>     proxy_domains = ["domaine.com"] # Domaines autorisés pour le proxy d'images
> 
>     def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False) -> Optional[Dict[str, Any]]:
>         clean = clean_title(query, library_type=library_type)
>         # LOGIQUE DE SCRAPING ICI
>         # DOIT retourner None en cas d'échec, ou EXACTEMENT ce dictionnaire :
>         '''
>         {
>             'summary': 'str',                  # Résumé
>             'cover_url': 'str',                # URL de l'image de couverture
>             'genres': ['list'],                # Genres principaux
>             'tags': ['list'],                  # Thèmes/tags (max 15)
>             'year': int,                       # Année de début de publication
>             'status': 'RELEASING/FINISHED/HIATUS/CANCELLED',
>             'staff': [{'role': 'Story/Art/Color/Translator', 'node': {'name': {'full': 'Prénom Nom'}}}],
>             'publisher': 'str',                # Éditeur officiel
>             'age_rating': 'safe/suggestive/pornographic',
>             'format': 'manga/webtoon/comic/book',
>             'url': 'str_url_of_the_page',      # Lien direct vers la page de l'œuvre
>             'links': ['list_of_urls']          # Liens de références
>         }
>         '''
>         pass
> 
>     def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
>         # LOGIQUE DE SCRAPING DES COUVERTURES ICI
>         # DOIT retourner une liste de dictionnaires : [{"provider": self.display_name, "title": "Titre Album", "url": "URL Image"}]
>         pass
> ```
> 
> **Règles importantes :**
> 1. Utilise `curl_cffi` (requests) ou le `requests` standard, et `BeautifulSoup` si tu dois parser du HTML.
> 2. Gère les exceptions proprement et retourne `None` (ou une liste vide `[]` pour les couvertures) en cas d'erreur.
> 3. Utilise la fonction `clean_title` pour nettoyer la requête de l'utilisateur avant de chercher.
> Génère la classe du scraper complète."

Une fois le code généré, nomme le fichier `mon_scraper.py`, place-le dans le dossier `scrapers/`, et redémarre le serveur. MetaKavita le détectera automatiquement, l'ajoutera aux paramètres de l'UI et routera les requêtes vers lui ! (Il faudra peut-être que tu le débuggues un peu ;) )

*---

### 6. Clés API & Services Tiers
Pour tester pleinement l'environnement de scraping, vous devrez générer des clés d'API personnelles pour les fournisseurs intégrés :
*   **DeepL API Free** : [DeepL Pro API](https://www.deepl.com/pro-api) (La clé doit se terminer par `:fx`)
*   **Azure Translator** : [Portail Azure](https://portal.azure.com/) (Niveau gratuit F0, 2M caractères/mois)
*   **ComicVine** : [API ComicVine](https://comicvine.gamespot.com/api/) (Nécessite un compte GameSpot gratuit)
*   **Google Books** : [Console Google Cloud](https://console.cloud.google.com/) (Activez l'"API Books" et générez une clé)