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
* **Database:** SQLite3 (`cache.db`). Includes an auto-cleanup function (`clean_orphaned_cache`) to drop entries deleted on Kavita's end.
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

### 4. How to Contribute (Add a Provider)
Adding a new provider is extremely simple thanks to the modular architecture:
1. Create a new file in the `scrapers/` folder (e.g., `mangadex.py`).
2. Your function must return a dict with these exact keys: `summary`, `cover_url`, `genres`, `tags`, `year`, `status`, `staff`, `characters`, and `alternative_titles`.
3. Import your function in `metadata_fetcher.py` and add it to the `PROVIDERS_MAP` dict.
4. That's it. The Frontend UI (dropdowns) and the Backend routing logic will adapt automatically!

---

## 🇫🇷 Guide de Développement Français

Ce document s'adresse aux développeurs souhaitant comprendre l'architecture complète de MetaKavita, y contribuer, ou créer un fork.

### 1. Architecture Globale & Stack Technique
MetaKavita est une application web modulaire faisant office de pont entre un serveur Kavita et diverses API de métadonnées.
* **Backend :** Python 3.11 avec Flask (`app.py`, `Dockerfile`).
* **Base de données :** SQLite3 (`cache.db`). Inclut une fonction d'auto-nettoyage (`clean_orphaned_cache`) pour purger les séries supprimées côté Kavita.
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

### 4. Comment Contribuer (Ajouter un Provider)
L'ajout d'une nouvelle source est trivial grâce à l'architecture modulaire :
1. Créez un nouveau script dans le dossier `scrapers/` (ex: `mangadex.py`).
2. Votre fonction doit retourner un dictionnaire avec ces clés strictes : `summary`, `cover_url`, `genres`, `tags`, `year`, `status`, `staff`, `characters`, et `alternative_titles`.
3. Importez votre fonction dans `metadata_fetcher.py` et ajoutez-la au dictionnaire `PROVIDERS_MAP`.
4. C'est terminé. L'interface HTML (menus déroulants) et la logique de Fallback du backend s'adapteront toutes seules en lisant la Map !