# DEVELOPER.md - Guide de Contribution à MetaKavita

Ce document s'adresse aux développeurs souhaitant comprendre l'architecture complète de MetaKavita, contribuer au projet, ou créer un fork pour leurs propres besoins.

## 1. Architecture Globale & Stack Technique

MetaKavita est une application web modulaire faisant office de pont entre un serveur Kavita et diverses API de métadonnées. 

La stack technique s'articule autour de :
* **Backend :** Python 3.11 avec le framework Flask[cite: 2, 9].
* **Base de données :** SQLite3 (`cache.db`) pour la persistance locale des statuts de traitement et des écrasements manuels de l'utilisateur[cite: 5].
* **Frontend :** HTML/CSS/JS natif (Vanilla) via des templates Jinja2[cite: 16, 17].
* **Temps Réel :** `Flask-SocketIO` côté serveur et `socket.io.js` côté client pour la diffusion en direct des logs de la console vers l'interface web[cite: 2, 17].

## 2. Structure du Frontend (UI/UX)

L'interface est conçue pour être légère et réactive sans nécessiter de framework JavaScript lourd (type React ou Vue) :
* **Thèmes :** Le design gère nativement le mode clair et le mode sombre via l'attribut `data-theme`[cite: 15, 16]. Le mode sombre (par défaut) est pensé pour s'intégrer visuellement avec l'interface de Kavita[cite: 15, 17].
* **Traductions (i18n) :** L'interface est traduisible en temps réel. Le dictionnaire actuel (géré dans `translations.py`) supporte le Français (`fr`) et l'Anglais (`en`)[cite: 12].
* **Asynchronisme :** Toutes les actions de synchronisation (unitaire ou par lots) utilisent l'API `fetch()` en Javascript pour communiquer avec les routes `/force-sync` et `/batch-sync` sans recharger la page[cite: 16].
* **Statistiques :** Un tableau de bord dédié (`stats.html`) permet de visualiser graphiquement la répartition des statuts de la base de données (complétées, en attente, introuvables)[cite: 18].

## 3. Logique des Scrapers (Providers)

Le système de scraping est conçu pour contourner les protections modernes tout en nettoyant les données en amont :
* **Nettoyage des Titres :** Avant chaque recherche textuelle, une fonction basée sur des expressions régulières (Regex) nettoie le titre de la série en supprimant les contenus entre parenthèses ou crochets, ainsi que les mentions de volumes (ex: "Vol. 1" ou "Tome 12")[cite: 13].
* **Module AniList :** Interroge l'API officielle via des requêtes GraphQL ciblées (`https://graphql.anilist.co`). Il supporte à la fois la recherche par nom et par ID direct[cite: 13].
* **Module Nautiljon :** Utilise la bibliothèque `curl_cffi` en usurpant l'empreinte d'un navigateur (`impersonate="safari15_5"`) pour contourner les protections antibot[cite: 14]. Le scraper charge d'abord la page d'accueil pour extraire un jeton de sécurité (`st`) indispensable avant de soumettre la recherche[cite: 14]. Les données sont ensuite parsées via `BeautifulSoup`[cite: 14].

## 4. Initialisation et Déploiement

Pour configurer un environnement de développement ou de production propre, un script d'initialisation Bash est fourni[cite: 11].

Ce script prépare l'environnement de la façon suivante :
1. Création d'un fichier `metakavita.log` vide s'il n'existe pas[cite: 11].
2. Création d'une base de données `cache.db` vide[cite: 11].
3. Génération d'un fichier `config.json` initial contenant un objet JSON vide `{}`[cite: 11].
4. Lancement recommandé via Docker avec la commande `docker compose up --build -d`[cite: 11].

## 5. Comment Contribuer

Si vous souhaitez ajouter un nouveau fournisseur de métadonnées (Provider) :
1. Créez un nouveau fichier dans le dossier des scrapers.
2. Assurez-vous que votre fonction retourne un dictionnaire contenant strictement ces clés : `summary`, `genres`, `tags`, `year`, `status`, `staff`, `characters`, et `alternative_titles`[cite: 14].
3. Intégrez votre scraper dans la fonction routeur `fetch_metadata` du fichier `metadata_fetcher.py`[cite: 1].
4. Ajoutez l'option correspondante dans le menu déroulant du template `index.html`[cite: 17].