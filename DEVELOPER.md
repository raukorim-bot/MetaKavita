# MetaKavita - Developer & Contribution Guide

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)

---

## 🇺🇸 English Developer Guide

This document is intended for developers who wish to understand the full architecture of MetaKavita, contribute to the project, or create a fork for their own needs.

### 1. Global Architecture & Tech Stack
MetaKavita is a lightweight, modular web application acting as a bridge between a Kavita server and various metadata APIs.
* **Backend:** Python 3.11 with the Flask framework (`app.py`, `Dockerfile`).
* **Database:** SQLite3 (`cache.db`) for local persistence of processing statuses (`PENDING`, `COMPLETED`, `NOT_FOUND`, `IGNORED`) and user manual overrides (`db_manager.py`).
* **Frontend:** Native HTML/CSS/JS (Vanilla) via Jinja2 templates (`index.html`, `stats.html`, `script.js`, `style.css`). No heavy frameworks like React or Vue.
* **Real-Time:** `Flask-SocketIO` on the server and `socket.io.js` on the client for live streaming console logs directly to the web UI.
* **Automation (Polling):** A pragmatic background thread runs independently to poll the Kavita API every X minutes, fetching new series and placing them in a processing queue (`sync_queue`) without requiring complex WebSocket connections to Kavita.

### 2. Frontend Structure (UI/UX)
The interface is designed to be fully dynamic, mimicking a Single Page Application (SPA):
* **100% AJAX:** All actions (saving configs, single sync, mass ignoring, batch sync) use the JS `fetch()` API. The page never reloads during standard use.
* **Themes:** Supports light and dark modes natively via a `data-theme` attribute. The dark mode matches Kavita's aesthetic.
* **Translations (i18n):** Real-time translation mapping. Handled backend-side via `translations.py`.
* **Security & QoL:** API keys are visually masked (password fields with toggle eyes). 

### 3. Scrapers Logic (Providers)
The scraping system is built to bypass modern protections while cleaning data upstream:
* **Title Cleaning:** Before searching, a regex-based function strips brackets, parentheses, and volume numbers to maximize match rates (`anilist.py`).
* **AniList Module:** Uses official GraphQL queries (`https://graphql.anilist.co`). Supports text search and direct ID overrides.
* **Nautiljon Module:** Uses the `curl_cffi` library with browser impersonation (`impersonate="safari15_5"`) to bypass Cloudflare anti-bot checks. It first extracts a security token (`st`) from the homepage before submitting the search query, then parses with `BeautifulSoup4`.
* **Translation Layer:** DeepL API integration (`metadata_fetcher.py`) automatically translates summaries to the user's target language, with robust error handling for API quotas and limits.

### 4. Initialization and Deployment
To set up a clean dev or prod environment, a bash script (`setup.sh`) is provided:
1. Creates an empty `metakavita.log` file.
2. Creates an empty `cache.db` SQLite database.
3. Generates a blank `config.json`.
4. Recommended to run via Docker (`docker compose up --build -d`).

### 5. How to Contribute
If you want to add a new metadata Provider:
1. Create a new file in the `scrapers/` folder.
2. Ensure your main function returns a dictionary containing strictly these keys: `summary`, `genres`, `tags`, `year`, `status`, `staff`, `characters`, and `alternative_titles`.
3. Integrate your scraper into the `fetch_metadata` router function inside `metadata_fetcher.py`.
4. Add the corresponding `<option>` tag in the `index.html` template dropdown.

---

## 🇫🇷 Guide de Développement Français

Ce document s'adresse aux développeurs souhaitant comprendre l'architecture complète de MetaKavita, contribuer au projet, ou créer un fork pour leurs propres besoins.

### 1. Architecture Globale & Stack Technique
MetaKavita est une application web modulaire et légère faisant office de pont entre un serveur Kavita et diverses API de métadonnées.
* **Backend :** Python 3.11 avec le framework Flask (`app.py`, `Dockerfile`).
* **Base de données :** SQLite3 (`cache.db`) pour la persistance locale des statuts de traitement (`PENDING`, `COMPLETED`, `NOT_FOUND`, `IGNORED`) et des écrasements manuels de l'utilisateur (`db_manager.py`).
* **Frontend :** HTML/CSS/JS natif (Vanilla) via des templates Jinja2 (`index.html`, `stats.html`, `script.js`, `style.css`).
* **Temps Réel :** `Flask-SocketIO` côté serveur et `socket.io.js` côté client pour la diffusion en direct des logs de la console vers l'interface web.
* **Automatisation (Polling) :** Un thread (tâche de fond) pragmatique s'exécute de façon autonome pour interroger l'API Kavita toutes les X minutes. Il récupère les nouvelles séries et les place dans la file d'attente (`sync_queue`), évitant d'avoir à gérer des connexions WebSockets complexes avec Kavita.

### 2. Structure du Frontend (UI/UX)
L'interface est conçue pour être réactive et se comporter comme une "Single Page Application" (SPA) :
* **100% AJAX :** Toutes les actions (sauvegarde, synchronisation unitaire ou par lots, ignorance de masse) utilisent l'API `fetch()`. La page ne se recharge jamais en usage standard.
* **Thèmes :** Gestion native du mode clair et sombre via l'attribut `data-theme`. Le mode sombre est pensé pour s'intégrer visuellement avec Kavita.
* **Traductions (i18n) :** Dictionnaire géré côté backend (`translations.py`) et mappé sur le frontend en direct.
* **Sécurité & QoL :** Les champs contenant des clés API sont masqués visuellement (champs mot de passe avec bouton œil).

### 3. Logique des Scrapers (Providers)
Le système de scraping est conçu pour contourner les protections modernes tout en nettoyant les données en amont :
* **Nettoyage des Titres :** Avant chaque recherche textuelle, une fonction Regex nettoie le titre de la série en supprimant le contenu entre parenthèses ou crochets, et les numéros de volumes (`anilist.py`).
* **Module AniList :** Interroge l'API officielle via des requêtes GraphQL ciblées (`https://graphql.anilist.co`). Supporte la recherche par nom et par ID direct.
* **Module Nautiljon :** Utilise la bibliothèque `curl_cffi` en usurpant l'empreinte d'un navigateur (`impersonate="safari15_5"`) pour contourner les protections antibot Cloudflare. Extrait un jeton de sécurité (`st`) sur l'accueil avant de soumettre la recherche, puis parse via `BeautifulSoup4`.
* **Couche de Traduction :** Intégration de l'API DeepL (`metadata_fetcher.py`) pour traduire automatiquement les résumés dans la langue cible, avec gestion stricte des quotas et erreurs API.

### 4. Initialisation et Déploiement
Pour configurer un environnement de développement ou de production, un script d'initialisation (`setup.sh`) est fourni :
1. Création d'un fichier `metakavita.log` vide.
2. Création d'une base de données SQLite `cache.db` vide.
3. Génération d'un fichier `config.json` initial.
4. Lancement recommandé via Docker (`docker compose up --build -d`).

### 5. Comment Contribuer
Si vous souhaitez ajouter un nouveau fournisseur de métadonnées (Provider) :
1. Créez un nouveau fichier dans le dossier `scrapers/`.
2. Assurez-vous que votre fonction retourne un dictionnaire contenant strictement ces clés : `summary`, `genres`, `tags`, `year`, `status`, `staff`, `characters`, et `alternative_titles`.
3. Intégrez votre scraper dans la fonction routeur `fetch_metadata` du fichier `metadata_fetcher.py`.
4. Ajoutez l'option correspondante dans le menu déroulant (`<option>`) du template `index.html`.