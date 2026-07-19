# MetaKavita - Developer & Contribution Guide

This guide is designed for developers and AI assistants wishing to understand, maintain, or extend the MetaKavita codebase. 

---

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
   * [Global Architecture & Security](#1-global-architecture--security)
   * [Frontend Mechanics (V1.4.0)](#2-frontend-mechanics-v140)
   * [Scraper Pipeline & Fallback Query Routing](#3-scraper-pipeline--fallback-query-routing)
   * [AI-Powered Scraper Creation (Vibecoding)](#4-ai-powered-scraper-creation-vibecoding)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)
   * [Architecture Globale & Sécurité](#1-architecture-globale--sécurité)
   * [Mécanismes Frontend (V1.4.0)](#2-mécanismes-frontend-v140)
   * [Pipeline de Scraping & Routage de Repli](#3-pipeline-de-scraping--routage-de-repli)
   * [Création de Scrapers via IA (Vibecoding)](#4-création-de-scrapers-via-ia-vibecoding)

---

## 🇺🇸 English Developer Guide

### 1. Global Architecture & Security
MetaKavita is a production-ready asynchronous Python application running behind a **Gunicorn WSGI server** with **Eventlet** workers to support real-time WebSockets via Flask-SocketIO.

*   **Security Layer:** Global authentication is enforced via `@app.before_request`. Session cookies are configured as `HttpOnly` and `SameSite=Lax`.
*   **Timing Attack Protection:** The login system uses `secrets.compare_digest` to prevent timing analysis of passwords, paired with a brute-force delay on failure.
*   **SSRF Protection:** The `/api/proxy-image` route uses dynamic strict whitelisting. If you add a new scraper, **you must add its domain** to the `ALLOWED_PROXY_DOMAINS` list in `metadata_fetcher.py`.
*   **Webhook Hardening:** Webhooks require a cryptographically secure `WEBHOOK_TOKEN` generated in `config.json`.

---

### 2. Frontend Mechanics (V1.4.0)

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

### 3. Scraper Pipeline & Fallback Query Routing

When a batch is run, `app.py` passes the `forced_id` (if set) as `search_query` and the clean folder/alternate title as `fallback_query` to `fetch_metadata()`.

```python
# Mapped query routing inside metadata_fetcher.py
is_id = str(query).isdigit()
if is_id:
    # Numeric IDs (like AniList IDs) are only sent to AniList
    provider_query = query if p == "ANILIST" else fallback_query
else:
    provider_query = query
```
*   **The Logic:** This prevents numeric AniList IDs from being queried in text-only REST APIs like MangaBaka or scrapers like Nautiljon, eliminating mismatched searches.
*   **Early-Break Bypass for Identities:** Even if `smart_completion` is disabled (meaning standard metadata fields like summary, year, genres are not merged), the pipeline **never breaks early** for external identity fields. It visits all active providers to aggregate and merge all possible IDs (`anilist_id`, `mal_id`, `mangabaka_id`) and clickable WebLinks.

---

### 4. AI-Powered Scraper Creation (Vibecoding)

If you are writing a new metadata provider (scraper) using an AI assistant (LLM), you can streamline the process immensely. 

**Vibecoding Tip:** Feed one of our existing scraper files (like `scrapers/mangabaka.py` or `scrapers/anilist.py`) directly into the LLM context first. This teaches the AI our parsing structure, import layout, and error-handling patterns, allowing it to generate extremely accurate code on the first try.

#### The AI Prompt Template
Copy and paste this prompt to your favorite LLM:

> "I am working on a Python project. I need a web scraper function named `fetch_myprovider(query)` that takes a string (a manga title or ID).
> 
> Here is my project context:
> - Centralized regex title cleaning is available: `from scrapers import clean_title`.
> - The target site is **[INSERT WEBSITE NAME OR API ENDPOINT HERE]**.
> - The function MUST return `None` if it fails, or return exactly this dict structure:
> 
> ```python
> {
>     'summary': 'str',                  # Description
>     'cover_url': 'str',                # URL of the main cover image
>     'genres': ['list'],                # Mapped genres list
>     'tags': ['list'],                  # Top themes/tags (max 15)
>     'year': int,                       # Publication start year
>     'status': 'RELEASING/FINISHED/HIATUS/CANCELLED',
>     'staff': [{'role': 'Story/Art/Color/Translator', 'node': {'name': {'full': 'Author Name'}}}],
>     'publisher': 'str',                # Official publisher
>     'age_rating': 'safe/suggestive/pornographic',
>     'format': 'manga/webtoon/comic',   # Country-of-origin context
>     'url': 'str_url_of_the_page',      # Direct link to the matched series page
>     'anilist_id': int,                 # If available
>     'mal_id': int,                     # If available
>     'mangabaka_id': int,               # If available
>     'links': ['list_of_urls']          # Additional reference links (e.g. MangaDex, Kitsu)
> }
> ```
> 
> Please generate the scraper using this exact format."

Once generated, drop the file into `scrapers/`, import it, and register it in `metadata_fetcher.py`'s `PROVIDERS_MAP` to automatically expose it in the Global Configuration Modal.

---

## 🇫🇷 Guide de Développement Français

### 1. Architecture Globale & Sécurité
MetaKavita est une application Python asynchrone fonctionnant derrière un **serveur WSGI Gunicorn** couplé à des workers **Eventlet** pour supporter les WebSockets en temps réel via Flask-SocketIO.

*   **Authentification :** Sécurisée au niveau global via `@app.before_request`. Les cookies de session sont configurés en `HttpOnly` et `SameSite=Lax`.
*   **Attaques Temporelles (Timing Attacks) :** Le système de connexion utilise `secrets.compare_digest` pour empêcher l'analyse du temps de réponse lors de la comparaison des mots de passe.
*   **Protection SSRF :** La route de proxy d'images `/api/proxy-image` utilise une liste blanche de domaines stricte. Si vous ajoutez un nouveau scraper, **vous devez ajouter son domaine** à la liste `ALLOWED_PROXY_DOMAINS` dans `metadata_fetcher.py`.
*   **Sécurisation Webhook :** L'endpoint webhook exige la clé cryptographique `WEBHOOK_TOKEN` générée dans `config.json`.

---

### 2. Mécanismes Frontend (V1.4.0)

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

### 3. Pipeline de Scraping & Routage de Repli

Lors d'une synchronisation, `app.py` transmet l'ID forcé (si configuré) comme `search_query` et le titre nettoyé de la série comme `fallback_query` à `fetch_metadata()`.

```python
# Routage intelligent de la requête dans metadata_fetcher.py
is_id = str(query).isdigit()
if is_id:
    # Un ID numérique n'est envoyé qu'à AniList
    provider_query = query if p == "ANILIST" else fallback_query
else:
    provider_query = query
```
*   **Intérêt :** Cela évite qu'un ID numérique AniList ne soit envoyé par erreur sur les API REST textuelles de MangaBaka ou de Nautiljon, éliminant ainsi les faux positifs.
*   **Compilation d'Identités :** Même si l'option `smart_completion` est désactivée (empêchant la fusion des résumés, genres, etc.), le pipeline **ne s'interrompt jamais** lors de la collecte des identifiants et des liens web. Il parcourt l'ensemble des providers de la liste pour fusionner et construire la liste de liens cliquables la plus complète possible.

---

### 4. Création de Scrapers via IA (Vibecoding)

Si tu développes un nouveau scraper avec l'aide d'un assistant IA (LLM), tu peux grandement accélérer le processus.

**Astuce de Vibecoding :** Injecte directement le code d'un de nos scrapers existants (comme `scrapers/mangabaka.py` ou `scrapers/anilist.py`) dans le contexte de ton LLM. Cela permettra à l'IA de comprendre instantanément notre structure d'importation, nos méthodes de parsing BeautifulSoup4, et notre gestion des erreurs, garantissant un code fonctionnel dès le premier essai.

#### Le Prompt de Référence IA
Copie-colle ce prompt dans ton modèle d'IA favori :

> "Je travaille sur un projet Python. J'ai besoin d'une fonction de web scraping nommée `fetch_mon_site(query)` qui prend un nom de manga ou un ID.
> 
> Voici les détails de mon projet :
> - Une fonction de nettoyage de titre centralisée est disponible : `from scrapers import clean_title`.
> - Le site cible est **[NOM DU SITE OU ENDPOINT D'API]**.
> - La fonction DOIT retourner `None` si elle échoue, ou retourner très exactement ce dictionnaire :
> 
> ```python
> {
>     'summary': 'str',                  # Résumé / Description
>     'cover_url': 'str',                # URL de l'image de couverture
>     'genres': ['liste'],               # Liste des genres mappés
>     'tags': ['liste'],                 # Liste des catégories/thèmes (max 15)
>     'year': int,                       # Année de début de publication
>     'status': 'RELEASING/FINISHED/HIATUS/CANCELLED',
>     'staff': [{'role': 'Story/Art/Color/Translator', 'node': {'name': {'full': 'Nom'}}}],
>     'publisher': 'str',                # Éditeur officiel
>     'age_rating': 'safe/suggestive/pornographic',
>     'format': 'manga/webtoon/comic',   # Type/Origine de l'œuvre
>     'url': 'str_url_de_la_page',      # Lien direct vers la fiche de l'œuvre
>     'anilist_id': int,                 # Si disponible
>     'mal_id': int,                     # Si disponible
>     'mangabaka_id': int,               # Si disponible
>     'links': ['liste_d_urls']          # Liens de référence alternatifs (ex: MangaDex, Kitsu)
> }
> ```
> 
> Génère le scraper en respectant scrupuleusement ce format."

Une fois ton fichier généré, place-le dans `scrapers/`, importe-le, et enregistre-le dans le `PROVIDERS_MAP` de `metadata_fetcher.py` pour l'exposer automatiquement dans l'UI.