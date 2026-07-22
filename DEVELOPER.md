# MetaKavita - Developer & Contribution Guide

This guide is designed for developers and AI assistants wishing to understand, maintain, or extend the MetaKavita codebase. 

---

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
   * [1. Global Architecture & Security](#1-global-architecture--security)
   * [2. Reverse Proxy & Subpath Architecture](#2-reverse-proxy--subpath-architecture-v154)
   * [3. Frontend Mechanics (V1.5.4)](#3-frontend-mechanics-v154)
   * [4. Scraper Factory & Auto-Discovery](#4-scraper-factory--auto-discovery-v152)
   * [5. Smart ID Match & Targeted Scraping](#5-smart-id-match--targeted-scraping-v154)
   * [6. Resilient Translation Pipeline](#6-resilient-translation-pipeline)
   * [7. AI-Powered Scraper Creation (Vibecoding)](#7-ai-powered-scraper-creation-vibecoding)
   * [8. API Keys & Third-Party Services](#8-api-keys--third-party-services)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)
   * [1. Architecture Globale & Sécurité](#1-architecture-globale--sécurité-1)
   * [2. Architecture Reverse Proxy & Sous-dossiers](#2-architecture-reverse-proxy--sous-dossiers-v154)
   * [3. Mécanismes Frontend (V1.5.4)](#3-mécanismes-frontend-v154-1)
   * [4. Scraper Factory & Auto-Découverte](#4-scraper-factory--auto-découverte-v152)
   * [5. Smart ID Match & Scraping Granulaire](#5-smart-id-match--scraping-granulaire-v154)
   * [6. Pipeline de Traduction Abstrait](#6-pipeline-de-traduction-abstrait)
   * [7. Création de Scrapers via IA (Vibecoding)](#7-création-de-scrapers-via-ia-vibecoding-1)
   * [8. Clés API & Services Tiers](#8-clés-api--services-tiers)

---

## 🇺🇸 English Developer Guide

### 1. Global Architecture & Security
MetaKavita is an asynchronous Python application powered by a **Gunicorn WSGI server** with **Eventlet** workers to support real-time WebSockets via Flask-SocketIO.

*   **Security Layer:** Global authentication is enforced via `@app.before_request`. Session cookies are configured as `HttpOnly` and `SameSite=Lax`.
*   **Timing Attack Protection:** The login system uses `secrets.compare_digest` to prevent timing analysis of passwords, paired with a brute-force delay on failure.
*   **SSRF Protection:** The `/api/proxy-image` route uses dynamic strict whitelisting. If you add a new scraper, **you must add its domain** to the `ALLOWED_PROXY_DOMAINS` list.
*   **Webhook Hardening:** Webhooks require a cryptographically secure `WEBHOOK_TOKEN` generated in `data/config.json`. The endpoint accepts flexible JSON/Form payloads (`seriesId`, `name`, and optional `"force": true` parameter) and features on-demand UI token rotation via POST `/regenerate-webhook-token`.
*   **API Keys Masking:** All sensitive API keys are censored with `********` on DOM generation to protect credentials from shoulder-surfing or browser extension scraping.

---

### 2. Reverse Proxy & Subpath Architecture (V1.5.4)

MetaKavita natively supports deployment under custom URL subpaths (e.g. `https://domain.com/metakavita`).

#### A. Backend WSGI Middleware Layer (`app.py`)
Reverse proxy headers (`X-Forwarded-Prefix`) are processed via Werkzeug's `ProxyFix`. In addition, if a user specifies an explicit subpath using the `ROOT_PATH` environment variable in Docker, a custom `ScriptNameStripper` WSGI middleware handles path rewriting:
```python
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

root_path = os.environ.get('ROOT_PATH', '')
if root_path:
    root_path = '/' + root_path.strip('/')
    class ScriptNameStripper(object):
        def __init__(self, wsgi_app, script_name):
            self.wsgi_app = wsgi_app
            self.script_name = script_name

        def __call__(self, environ, start_response):
            path_info = environ.get('PATH_INFO', '')
            if path_info.startswith(self.script_name):
                environ['SCRIPT_NAME'] = self.script_name
                environ['PATH_INFO'] = path_info[len(self.script_name):] or '/'
            return self.wsgi_app(environ, start_response)

    app.wsgi_app = ScriptNameStripper(app.wsgi_app, root_path)
```
* **Infrastructure Isolation:** `ROOT_PATH` is evaluated directly from environment variables on startup and is intentionally omitted from `config.json` and the UI to prevent user misconfiguration from breaking application access.

#### B. Client-Side Prefixing (`script.js` & Jinja)
In `templates/index.html`, Flask's `request.script_root` is exposed globally:
```html
<script>
    window.ROOT_PATH = "{{ request.script_root }}";
</script>
```
In `static/js/script.js`, all fetch endpoints, history pushStates, and Socket.IO connections use `window.ROOT_PATH`:
```javascript
const getRootPath = () => window.ROOT_PATH || '';
fetch(getRootPath() + '/save-override', { ... });
var socket = io({ path: getRootPath() + '/socket.io' });
```
Socket.IO uses standard Same-Origin security without requiring `cors_allowed_origins="*"`.

---

### 3. Frontend Mechanics (V1.5.4)

#### A. Hybrid AJAX Configuration Saving
To preserve ergonomics, persistent technical parameters sit inside `#configForm` in the settings Modal, while active scraping checkboxes are located in the sidebar.
*   **The Mechanism:** When `saveConfig()` is triggered in `script.js`, it serializes `#configForm` into a `FormData` object, manually queries the sidebar checkboxes, and appends them to the payload. This allows single-endpoint backend writing without reloads.

#### B. Workspace Persistence
Any change to filter inputs (status, library, search query) is stored in `localStorage` and automatically restored on load.
*   **Library Autoload:** If the user visits `/` and has a saved library ID in `localStorage`, the JS router automatically executes `loadLibrary()` to load the saved library without manual intervention.

#### C. Log Parsing & Active Highlighting
The WebSocket log receiver inside `script.js` parses incoming backend log messages in real-time.
*   **Highlight Trigger:** A regex detects `▶️ [Series Name] Début` / `Starting` log events, applies the `.is-processing` pulsing CSS class, and smooth-scrolls the active card into view.
*   **Resolution Trigger:** When finishing logs are received (`✅`, `❌`, `⚠️`), the `.is-processing` class is removed and badges are dynamically updated in-place.

---

### 4. Scraper Factory & Auto-Discovery (V1.5.2+)

Instead of a hardcoded map, MetaKavita uses an **Auto-Discovery Registry pattern**. On startup, `scrapers/__init__.py` scans the `scrapers/` folder and dynamically loads any class inheriting from `BaseScraper`. 

```python
# The BaseScraper Contract (V1.5.4+)
class BaseScraper(ABC):
    id: str = ""
    display_name: str = ""
    supported_types: Set[str] = set() # e.g., {"Manga", "Comic"}
    rate_limit: float = 1.0
    proxy_domains: List[str] = []
    has_direct_id_support: bool = False # Opt-in for Magic URL/ID parsing
    
    def extract_id_from_url(self, url: str) -> Optional[str]:
        return None # To be overridden if has_direct_id_support is True

    @abstractmethod
    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False): ...
    def fetch_covers(self, query: str, library_type: str = "Manga"): ...
```
*   **Self-Healing Routing:** The `ScraperRegistry` automatically validates user configurations. If a user configured a default provider that was later deleted from the folder, the backend self-heals and safely falls back to the next available loaded scraper.
*   **Contextual Title Cleaning:** The `clean_title` function in `scrapers/utils.py` cleans queries contextually based on the targeted media type (stripping leading zeros in comics, isolating "Title - Author" in books, etc.).

---

### 5. Smart ID Match & Targeted Scraping (V1.5.4)

MetaKavita V1.5.4 introduced a highly resilient engine to handle manual metadata forcing.

#### A. The Magic Input (Opt-in URL Routing)
Scrapers must explicitly declare `has_direct_id_support = True` to appear in the override dropdown. When a user pastes an HTTP URL, `app.py` queries all active scrapers via `extract_id_from_url(url)`. The scraper that successfully extracts the ID takes full control of the execution, entirely bypassing the search cascade.

#### B. The "Smart ID Match" Engine
If a user pastes a raw numerical ID (e.g., `12345`) while keeping the provider dropdown on "AUTO", the system cannot know which database this ID belongs to. 
The system will route the ID to compatible providers. Once data is fetched, `metadata_fetcher.py` uses the `calculate_similarity` function (from `scrapers/utils.py`) to compare the fetched title against the local Kavita title. **If the similarity score is below 50%, the data is rejected as a false positive**, and the system falls back to the next provider.

#### C. Granular Scraping
Users can now individually toggle 12 different metadata fields. These choices are passed as a comma-separated string to `app.py` (`active_fields`), which acts as an absolute gateway. A metadata field will never be locked and pushed to Kavita unless `if 'fieldname' in active_fields` evaluates to True.

---

### 6. Resilient Translation Pipeline
All translation operations are abstracted inside `translator.py` and utilize a multi-tier cascade to ensure high availability:

*   **Option NONE (Disabled):** Short-circuits the pipeline and returns cleaned raw text in its original scraped language.
*   **Tier 1: Microsoft Azure Translator** (F0 tier, 2M chars/month free) - Recommended primary engine.
*   **Tier 2: DeepL API** (Free tier, 1M chars lifetime limit) - Automatic fail-safe fallback.
*   **Tier 3: Google Translate ("Zero-Config" Fallback)** - Implemented using the unofficial [py-googletrans](https://github.com/ssut/py-googletrans) Python library. Requires no API key and acts as a free fallback.

---

### 7. AI-Powered Scraper Creation (Vibecoding)

Thanks to the **Plug & Play Auto-Discovery Architecture**, you never have to touch the core routing or HTML to add a new metadata source. Simply drop a `.py` file into the `scrapers/` folder.

#### The Ultimate AI Prompt Template
Copy and paste this prompt to your favorite LLM (Claude, ChatGPT, Cursor) to quickly generate a new compatible provider:

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
>     has_direct_id_support = True # Set to True if it can handle IDs or URLs directly
> 
>     def extract_id_from_url(self, url: str) -> Optional[str]:
>         # Example: if "mysite.com/manga/" in url: return url.split('/')[-1]
>         return None
> 
>     def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False) -> Optional[Dict[str, Any]]:
>         clean = clean_title(query, library_type=library_type)
>         # SCRAPING LOGIC HERE
>         # MUST return None if failed, or exactly this dictionary (title is MANDATORY for Smart Match validation):
>         '''
>         {
>             'title': 'str_original_title',     # MANDATORY
>             'alternative_titles': ['list'],    # Alternative names
>             'summary': 'str',                  # Description
>             'cover_url': 'str',                # Main cover image URL
>             'genres': ['list'],                # Main genres
>             'tags': ['list'],                  # Themes/tags (max 15)
>             'year': int,                       # Publication start year
>             'status': 'RELEASING/FINISHED/HIATUS/CANCELLED',
>             'staff': [{'role': 'Story/Art/Color/Translator/Editor/Letterer/Inker', 'node': {'name': {'full': 'Author Name'}}}],
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

---

### 8. API Keys & Third-Party Services
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
*   **Attaques Temporelles (Timing Attacks) :** Le système de connexion utilise `secrets.compare_digest`.
*   **Protection SSRF :** La route de proxy d'images `/api/proxy-image` utilise une liste blanche de domaines stricte. Si vous ajoutez un nouveau scraper, **vous devez ajouter son domaine** à la liste `ALLOWED_PROXY_DOMAINS`.
*   **Protection Webhook :** Authentification exigeant un jeton cryptographique (`WEBHOOK_TOKEN`) enregistré dans `data/config.json`. La route accepte des payloads souples (JSON/Form) avec gestion de l'option `"force": true` et propose la régénération de jeton via la route POST `/regenerate-webhook-token`.
*   **Censure de sécurité des clés :** Toutes les clés d'API sensibles sont remplacées par `********` lors de la génération du DOM pour protéger vos identifiants des regards indiscrets.

---

### 2. Architecture Reverse Proxy & Sous-dossiers (V1.5.4)

MetaKavita supporte le déploiement sous un sous-chemin personnalisé (ex: `https://domaine.com/metakavita`).

#### A. Couche Middleware WSGI Backend (`app.py`)
Les en-têtes proxy (`X-Forwarded-Prefix`) sont gérés par `ProxyFix`. En complément, si l'utilisateur spécifie une variable d'environnement `ROOT_PATH` dans Docker, un middleware `ScriptNameStripper` réécrit les routes WSGI :
```python
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

root_path = os.environ.get('ROOT_PATH', '')
if root_path:
    root_path = '/' + root_path.strip('/')
    class ScriptNameStripper(object):
        def __init__(self, wsgi_app, script_name):
            self.wsgi_app = wsgi_app
            self.script_name = script_name

        def __call__(self, environ, start_response):
            path_info = environ.get('PATH_INFO', '')
            if path_info.startswith(self.script_name):
                environ['SCRIPT_NAME'] = self.script_name
                environ['PATH_INFO'] = path_info[len(self.script_name):] or '/'
            return self.wsgi_app(environ, start_response)

    app.wsgi_app = ScriptNameStripper(app.wsgi_app, root_path)
```
* **Isolation de l'infrastructure :** `ROOT_PATH` est lu au démarrage depuis l'environnement Docker et n'apparaît volontairement ni dans `config.json` ni dans l'interface web pour éviter qu'une erreur de saisie ne bloque l'accès à l'application.

#### B. Préfixage Côté Client (`script.js` & Jinja)
Dans `templates/index.html`, la variable `request.script_root` est exposée au JS :
```html
<script>
    window.ROOT_PATH = "{{ request.script_root }}";
</script>
```
Dans `static/js/script.js`, tous les appels HTTP et WebSockets s'appuient sur `window.ROOT_PATH` :
```javascript
const getRootPath = () => window.ROOT_PATH || '';
fetch(getRootPath() + '/save-override', { ... });
var socket = io({ path: getRootPath() + '/socket.io' });
```
Socket.IO applique une sécurité Same-Origin standard sans nécessiter `cors_allowed_origins="*"`.

---

### 3. Mécanismes Frontend (V1.5.4)

#### A. Sauvegarde Hybride (AJAX)
Pour conserver une ergonomie propre, les paramètres techniques résident dans le formulaire `#configForm` de la Modal, tandis que les options de scraping stratégiques résident dans la sidebar.
*   **Fonctionnement :** Lorsque `saveConfig()` est exécutée, elle sérialise `#configForm`, récupère manuellement l'état des cases d'options latérales, et assemble le tout dans un unique payload AJAX vers `/save-config`. Cela permet un enregistrement transparent.

#### B. Persistance de l'Espace de Travail
Toute modification des filtres (bibliothèque, recherche, statut) est stockée dans le `localStorage` du navigateur pour être restaurée à la prochaine ouverture.

#### C. Suivi Live & Logs WebSockets
Le récepteur WebSocket de `script.js` analyse en direct le flux de logs.
*   **Détection :** Une expression régulière cherche le motif de démarrage, applique la classe CSS de pulsation `.is-processing` sur la ligne correspondante et force un défilement fluide (*smooth-scroll*).

---

### 4. Scraper Factory & Auto-Découverte (V1.5.2+)

Fini les dictionnaires codés en dur ! MetaKavita utilise désormais un **Pattern Registre par Auto-Découverte**. Au démarrage, `scrapers/__init__.py` scanne le dossier `scrapers/` et charge dynamiquement toutes les classes héritant de `BaseScraper`.

```python
# Le Contrat BaseScraper (V1.5.4+)
class BaseScraper(ABC):
    id: str = ""
    display_name: str = ""
    supported_types: Set[str] = set() # ex: {"Manga", "Comic"}
    rate_limit: float = 1.0
    proxy_domains: List[str] = []
    has_direct_id_support: bool = False # Active le support URL/ID Magique
    
    def extract_id_from_url(self, url: str) -> Optional[str]:
        return None # À surcharger si has_direct_id_support est True

    @abstractmethod
    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False): ...
    def fetch_covers(self, query: str, library_type: str = "Manga"): ...
```
* **Auto-Réparation :** Le `ScraperRegistry` valide dynamiquement la configuration. Si un scraper par défaut a été supprimé du disque par l'utilisateur, l'application le détecte, s'auto-répare et bascule sur le scraper suivant sans crasher.

---

### 5. Smart ID Match & Scraping Granulaire (V1.5.4)

MetaKavita V1.5.4 a introduit un moteur ultra-résilient pour la modification manuelle des œuvres.

#### A. Le Champ Magique (Routage URL)
Les scrapers doivent déclarer `has_direct_id_support = True` pour apparaître dans le menu déroulant avancé. Lorsqu'un utilisateur colle une URL, `app.py` interroge tous les scrapers via `extract_id_from_url(url)`. Celui qui parvient à extraire l'ID prend le contrôle exclusif de l'exécution et contourne la recherche habituelle.

#### B. Le Moteur "Smart ID Match"
Si un utilisateur colle un ID brut (ex: `12345`) en laissant le menu sur "AUTO", le système ne peut pas deviner à quelle base de données il appartient. Il va donc interroger les fournisseurs compatibles. Une fois la donnée récupérée, `metadata_fetcher.py` utilise la fonction `calculate_similarity` pour comparer le titre trouvé avec le titre Kavita. **Si la similarité est inférieure à 50%, la donnée est rejetée comme étant un "Faux Positif"** et le système passe au fournisseur suivant pour éviter de corrompre l'œuvre.

#### C. Scraping Granulaire
Les utilisateurs peuvent désormais cocher/décocher 12 champs de métadonnées spécifiques. Ces choix sont passés via la variable `active_fields` dans `app.py`, qui agit comme une douane absolue. Un champ ne sera envoyé à Kavita que si la condition `if 'champ' in active_fields` est remplie.

---

### 6. Pipeline de Traduction Abstrait
Toutes les opérations de traduction sont centralisées dans `translator.py` et utilisent une cascade à plusieurs niveaux :

*   **Option NONE (Désactivé) :** Intercepte le traitement et retourne le texte nettoyé dans sa langue d'origine.
*   **Niveau 1 : Microsoft Azure Translator** (F0, 2M caractères gratuits/mois) - Moteur principal recommandé.
*   **Niveau 2 : DeepL API** (1M caractères gratuits à vie) - Système de secours automatique.
*   **Niveau 3 : Google Translate ("Zero-Config")** - Implémenté via la librairie [py-googletrans](https://github.com/ssut/py-googletrans). Sans clé API et actif par défaut.

---

### 7. Création de Scrapers via IA (Vibecoding)

Grâce à l'**Architecture Plug & Play**, tu n'as plus jamais besoin de modifier le code de routage pour ajouter une source de métadonnées. Il te suffit de glisser un fichier `.py` dans le dossier `scrapers/`.

#### Le Prompt IA Ultime
Copie-colle ce texte à ton IA favorite (Claude, ChatGPT, Cursor) pour générer instantanément un fournisseur compatible :

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
>     has_direct_id_support = True # Mettre True si le site gère les ID/URLs directement
> 
>     def extract_id_from_url(self, url: str) -> Optional[str]:
>         # Exemple: if "monsite.com/manga/" in url: return url.split('/')[-1]
>         return None
> 
>     def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False) -> Optional[Dict[str, Any]]:
>         clean = clean_title(query, library_type=library_type)
>         # LOGIQUE DE SCRAPING ICI
>         # DOIT retourner None en cas d'échec, ou EXACTEMENT ce dictionnaire (le titre est OBLIGATOIRE) :
>         '''
>         {
>             'title': 'str_titre_original',     # OBLIGATOIRE (Pour le Smart Match)
>             'alternative_titles': ['list'],    # Noms alternatifs
>             'summary': 'str',                  # Résumé
>             'cover_url': 'str',                # URL de l'image de couverture
>             'genres': ['list'],                # Genres principaux
>             'tags': ['list'],                  # Thèmes/tags (max 15)
>             'year': int,                       # Année de début de publication
>             'status': 'RELEASING/FINISHED/HIATUS/CANCELLED',
>             'staff': [{'role': 'Story/Art/Color/Translator/Editor/Letterer/Inker', 'node': {'name': {'full': 'Prénom Nom'}}}],
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
> 2. Gère les exceptions proprement et retourne `None` (or une liste vide `[]` pour les couvertures) en cas d'erreur.
> 3. Utilise la fonction `clean_title` pour nettoyer la requête de l'utilisateur avant de chercher.
> Génère la classe du scraper complète."

---

### 8. Clés API & Services Tiers
Pour tester pleinement l'environnement de scraping, vous devrez générer des clés d'API personnelles pour les fournisseurs intégrés :
*   **DeepL API Free** : [DeepL Pro API](https://www.deepl.com/pro-api) (La clé doit se terminer par `:fx`)
*   **Azure Translator** : [Portail Azure](https://portal.azure.com/) (Niveau gratuit F0, 2M caractères/mois)
*   **ComicVine** : [API ComicVine](https://comicvine.gamespot.com/api/) (Nécessite un compte GameSpot gratuit)
*   **Google Books** : [Console Google Cloud](https://console.cloud.google.com/) (Activez l'"API Books" et générez une clé)