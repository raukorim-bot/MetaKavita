## [1.3.3] - 2026-07-19 (Security & Metadata Overhaul)

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