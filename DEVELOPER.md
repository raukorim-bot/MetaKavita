# MetaKavita - Developer & Contribution Guide

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)

---

## 🇺🇸 English Developer Guide

This document is intended for developers who wish to understand the full architecture of MetaKavita, contribute to the project, or create a fork.

### 1. Global Architecture & Tech Stack
MetaKavita is a lightweight, modular web application acting as a bridge between a Kavita server and various metadata APIs.
* **Backend:** Python 3.11 with the Flask framework (`app.py`, `Dockerfile`).
* **Database & Data:** SQLite3 (`data/cache.db`). The `data/` directory is automatically generated at startup, containing the config and logs. Includes an auto-cleanup function (`clean_orphaned_cache`) to drop entries deleted on Kavita's end.
* **Frontend:** Native HTML/CSS/JS (Vanilla). The UI is built to be a resilient SPA (Single Page Application) with zero page reloads via `fetch()`.
* **Real-Time:** `Flask-SocketIO` on the server and `socket.io.js` on the client for live streaming console logs.

### 2. Scrapers Logic & The "Smart Fusion" Algorithm
The scraping system features a dynamic routing engine:
* **PROVIDERS_MAP:** Located in `metadata_fetcher.py`, this dictionary maps string identifiers to scraper functions. The UI automatically reads this map to populate dropdowns, making the tool infinitely scalable.
* **Smart Completion (Fusion):** If a user enables this, the script fetches data from the primary provider. If keys are missing (e.g., `genres: []`), it will sequentially ping the fallback providers to patch the missing holes without overwriting existing data.
* **Dynamic Rate-Limiting:** The background worker adjusts its `time.sleep()` dynamically depending on how many providers were called during a Smart Fusion to avoid IP bans.

### 3. Kavita API Compliance (Important!)
Kavita's backend is built in C# and expects very specific payload formatting when updating metadata via `/api/Series/metadata`.
* **The `id: 0` Rule:** When sending lists of objects (like Genres, Tags, Writers, Pencillers, Characters), Kavita expects each object to have `"id": 0`. If you omit the ID or send Kavita's internal ID, the update might be silently ignored. Example: `[{"id": 0, "title": "Action"}]`.
* **Locks:** Every field updated must be accompanied by its corresponding `Locked` boolean set to `true` (e.g., `summaryLocked: true`), or Kavita will overwrite it during its own internal scan.

### 4. Vibecoding: Add a Provider using an LLM (AI)
Because MetaKavita's architecture is strictly standardized, you don't even need to code to add a new provider (like MangaDex, Babelio, Goodreads). You can use an AI (ChatGPT, Claude, etc.) to do it for you in one shot!

Just copy and paste this prompt to your favorite LLM:

> "I am working on a Python project. I need a web scraper function named `fetch_myprovider(query)` that takes a string (a manga or comic title) and searches for it on **[INSERT WEBSITE NAME HERE]**. 
> You can use `requests` and `BeautifulSoup4` (or `curl_cffi` if there is a Cloudflare protection).
> The function MUST return `None` if it fails, or return exactly this Python dictionary structure if it succeeds:
> { 'summary': 'string', 'cover_url': 'string or None', 'genres': ['list', 'of', 'strings'], 'tags': ['list', 'of', 'strings'], 'year': integer or None, 'status': 'RELEASING' or 'FINISHED' or 'HIATUS' or 'CANCELLED' or None, 'staff': [{'role': 'Story or Art', 'node': {'name': {'full': 'Author Name'}}}], 'characters': [], 'alternative_titles': ['list'] }."

Once the AI generates the code:
1. Save it in the `scrapers/` folder (e.g., `myprovider.py`).
2. Import it in `metadata_fetcher.py`.
3. Add it to the `PROVIDERS_MAP` dict (`"MYPROVIDER": fetch_myprovider`). The UI will update automatically!

---

## 🇫🇷 Guide de Développement Français

Ce document s'adresse aux développeurs souhaitant comprendre l'architecture complète de MetaKavita, y contribuer, ou créer un fork.

### 1. Architecture Globale & Stack Technique
MetaKavita est une application web modulaire faisant office de pont entre un serveur Kavita et diverses API de métadonnées.
* **Backend :** Python 3.11 avec Flask (`app.py`, `Dockerfile`).
* **Base de données & Données :** SQLite3 (`data/cache.db`). Le dossier `data/` est auto-généré au lancement et contient la configuration et les logs. Inclut une fonction d'auto-nettoyage (`clean_orphaned_cache`) pour purger les séries supprimées côté Kavita.
* **Frontend :** HTML/CSS/JS natif (Vanilla). Conçu pour réagir comme une SPA (Single Page Application) ultra-fluide via l'utilisation de `fetch()`.
* **Temps Réel :** `Flask-SocketIO` côté serveur pour la diffusion en direct des logs de la console vers l'interface.

### 2. Logique des Scrapers & Algorithme de "Fusion"
Le système de scraping possède un moteur de routage dynamique :
* **PROVIDERS_MAP :** Situé dans `metadata_fetcher.py`, ce dictionnaire relie le nom d'un provider à sa fonction Python. Le Frontend lit automatiquement ce registre pour construire l'interface, rendant le système parfaitement évolutif (scalable).
* **Complétion Intelligente (Fusion) :** Si activée, le script interroge la source principale. S'il manque des données (ex: pas de genres), le script interrogera silencieusement les sources de secours pour "boucher les trous" sans jamais écraser la donnée de base.
* **Rate-Limiting Dynamique :** Le délai de sécurité `time.sleep()` de la tâche de fond s'adapte automatiquement selon le nombre de sources sollicitées par l'algorithme de Fusion pour éviter un ban IP.

### 3. Conformité API Kavita (Important !)
Le backend de Kavita (C#) exige un formatage de payload très strict lors de la mise à jour des métadonnées via l'endpoint `/api/Series/metadata`.
* **La règle du `id: 0` :** Lors de l'envoi de listes d'objets (Genres, Tags, Staff, Characters), Kavita exige que chaque objet possède `"id": 0`. Si vous l'omettez, la mise à jour sera silencieusement ignorée. Exemple : `[{"id": 0, "title": "Action"}]`.
* **Les Verrous (Locks) :** Chaque champ mis à jour doit être accompagné de son booléen `Locked` défini sur `true` (ex: `summaryLocked: true`), sinon Kavita écrasera vos données lors de son prochain scan interne.

### 4. Vibecoding : Créer un Provider avec une IA (LLM)
Grâce à l'architecture ultra standardisée de MetaKavita, tu n'as même pas besoin de savoir coder pour ajouter une nouvelle source de métadonnées (Babelio, MangaDex, etc.). Tu peux demander à une IA (ChatGPT, Claude...) de le faire pour toi en un seul message !

Copie-colle simplement ce "Prompt" à ton IA favorite :

> "Je travaille sur un projet Python. J'ai besoin d'une fonction de web scraping nommée `fetch_mon_site(query)` qui prend une chaîne de caractères (un nom de manga/BD) et effectue une recherche sur **[INSÉRER LE NOM DU SITE ICI]**.
> Tu peux utiliser `requests` et `BeautifulSoup4` (ou `curl_cffi` si le site est sous Cloudflare).
> La fonction DOIT retourner `None` si elle échoue, ou retourner très exactement ce format de dictionnaire Python si elle réussit :
> { 'summary': 'string', 'cover_url': 'string or None', 'genres': ['liste', 'de', 'strings'], 'tags': ['liste', 'de', 'strings'], 'year': entier (ex: 2024) ou None, 'status': 'RELEASING' ou 'FINISHED' ou 'HIATUS' ou 'CANCELLED' ou None, 'staff': [{'role': 'Story ou Art', 'node': {'name': {'full': 'Nom Auteur'}}}], 'characters': [], 'alternative_titles': ['liste'] }."

Une fois que l'IA t'a généré le code :
1. Sauvegarde-le dans le dossier `scrapers/` (ex: `monsite.py`).
2. Importe-le dans `metadata_fetcher.py`.
3. Ajoute-le dans le dictionnaire `PROVIDERS_MAP` (`"MONSITE": fetch_mon_site`). L'interface Web se mettra à jour toute seule !