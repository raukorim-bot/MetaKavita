# MetaKavita - Developer & Contribution Guide

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)

---

## 🇺🇸 English Developer Guide

This document is intended for developers who wish to understand the full architecture of MetaKavita, contribute to the project, or create a fork.

### 1. Global Architecture & Security
MetaKavita is a production-ready application running behind a **Gunicorn WSGI server** with **Eventlet** workers to support true asynchronous WebSockets.
* **Security Layer:** Global authentication is enforced via `@app.before_request`. Session cookies are `HttpOnly` and `SameSite=Lax`. WebSockets connections are validated on `connect`.
* **SSRF Protection:** The `/api/proxy-image` route uses dynamic strict whitelisting. If you add a new scraper, **you MUST add its domain** to the `ALLOWED_PROXY_DOMAINS` list in `metadata_fetcher.py`.
* **Webhook Token:** IP-based webhook protection fails behind reverse proxies. MetaKavita uses a cryptographically secure `WEBHOOK_TOKEN` generated in `config.json`.

### 2. The Regex Engine (`scrapers/__init__.py`)
The `clean_title()` function is centralized. It's a highly optimized Regex engine that automatically strips volume numbers, edition keywords (Omnibus, Perfect), scantrad tags, and stray dots, ensuring API search queries are squeaky clean. Always import it when creating a new provider: `from scrapers import clean_title`.

### 3. Kavita API Compliance
* **The `id: 0` Rule:** When sending lists of objects (Genres, Tags, Staff), Kavita expects each object to have `"id": 0`.
* **Locks:** Every field updated must be accompanied by its `Locked` boolean set to `true`.
* **External IDs:** AniList and MAL IDs are injected via the `/api/Series/update` route, whereas standard metadata (Summaries, WebLinks) goes to `/api/Series/metadata`.

### 4. Vibecoding: Add a Provider using an LLM (AI)
Copy and paste this prompt to your favorite LLM:

> "I am working on a Python project. I need a web scraper function named `fetch_myprovider(query)` that takes a string (a manga title). Import `clean_title` from `scrapers`. Search on **[INSERT WEBSITE NAME HERE]**. 
> The function MUST return `None` if it fails, or return exactly this dict structure:
> { 'summary': 'str', 'cover_url': 'str', 'genres': ['list'], 'tags': ['list'], 'year': int, 'status': 'RELEASING/FINISHED/HIATUS/CANCELLED', 'staff': [{'role': 'Story/Art/Color/Translator', 'node': {'name': {'full': 'Author Name'}}}], 'publisher': 'str', 'age_rating': 'safe/suggestive/pornographic', 'format': 'manga/webtoon/comic', 'url': 'str_url_of_the_page', 'anilist_id': int, 'mal_id': int }."

Add the function to `PROVIDERS_MAP` in `metadata_fetcher.py`, and you're done!

---

## 🇫🇷 Guide de Développement Français

Ce document s'adresse aux développeurs souhaitant comprendre l'architecture complète de MetaKavita.

### 1. Architecture Globale & Sécurité
MetaKavita tourne sur un serveur de production **Gunicorn WSGI** avec des workers **Eventlet** pour supporter les WebSockets de manière asynchrone.
* **Couche de Sécurité :** L'authentification globale empêche les attaques par force brute (délai de réponse) et temporelles (`compare_digest`). Les cookies sont `HttpOnly`.
* **Protection SSRF :** Le proxy d'images utilise une liste blanche stricte. Si vous ajoutez un nouveau scraper, **vous DEVEZ ajouter son domaine** à `ALLOWED_PROXY_DOMAINS` dans `metadata_fetcher.py`.
* **Webhook Token :** Le Webhook est sécurisé par un `WEBHOOK_TOKEN` généré dans le `config.json` pour éviter le spam d'API.

### 2. Le Moteur de Regex (`scrapers/__init__.py`)
La fonction `clean_title()` a été décentralisée. C'est un moteur Regex surpuissant qui nettoie les numéros de tomes, les mots-clés d'édition (Intégrale, Deluxe) et les extensions. Importez-la toujours pour vos nouveaux providers : `from scrapers import clean_title`.

### 3. Conformité API Kavita
* **La règle du `id: 0` :** Kavita exige que chaque objet d'une liste (Genres, Staff) possède `"id": 0`.
* **Les Verrous :** Chaque champ doit avoir son booléen `Locked` (ex: `summaryLocked: true`).
* **Identifiants Externes :** Les identifiants (AniListId) sont envoyés via la route `/api/Series/update`, contrairement au reste des métadonnées.

### 4. Vibecoding : Créer un Provider avec une IA (LLM)
Copie-colle ce "Prompt" à ton IA favorite :

> "Je travaille sur un projet Python. J'ai besoin d'une fonction de web scraping nommée `fetch_mon_site(query)` qui prend un nom de manga. Importe `clean_title` depuis `scrapers`. Fais une recherche sur **[NOM DU SITE]**.
> La fonction DOIT retourner `None` si elle échoue, ou retourner très exactement ce dictionnaire :
> { 'summary': 'str', 'cover_url': 'str', 'genres': ['liste'], 'tags': ['liste'], 'year': int, 'status': 'RELEASING/FINISHED/HIATUS/CANCELLED', 'staff': [{'role': 'Story/Art/Color/Translator', 'node': {'name': {'full': 'Nom'}}}], 'publisher': 'str', 'age_rating': 'safe/suggestive/pornographic', 'format': 'manga/webtoon/comic', 'url': 'str_url_de_la_page_trouvée', 'anilist_id': int, 'mal_id': int }."

Ajoute-le dans `PROVIDERS_MAP` (`metadata_fetcher.py`) et l'UI se mettra à jour !