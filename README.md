# MetaKavita
<img width="1920" height="1080" alt="MetaKavita Dashboard" src="https://github.com/user-attachments/assets/1db72309-5136-41b0-9e08-5a79f7760b8a" />

## Sommaire / Table of Contents
1. [🇺🇸 English Documentation](#-english-documentation)
2. [🇫🇷 Documentation Française](#-documentation-française)
3. [⚠️ Notes & Tech Stack](#-notes--tech-stack)

---

## 🇺🇸 English Documentation

MetaKavita is an automation tool designed to enrich metadata for your [Kavita](https://kavitareader.com/) library. It automatically retrieves information (summaries, release years, genres, tags, extended staff, publishers, age ratings, alternative titles, web links, and external IDs) from multiple sources and translates summaries via [DeepL](https://www.deepl.com/).

### ⚙️ Interface and Configuration
*   **Live UI**: 100% AJAX interface (zero page reloads) with real-time logs, visually masked API keys, and explicit connection error screens.
*   **Real-time Search**: Instantly filter your hundreds of series using the built-in AJAX search bar.
*   **Smart Routing (Fallback)**: Define a main metadata source and up to two backups (e.g., MangaBaka > Nautiljon > AniList).
*   **Smart Completion (Data Fusion)**: If enabled, MetaKavita will patch incomplete metadata. It fetches *only* the missing fields from backup sources to create the ultimate metadata file!
*   **Global Security**: Password-protected UI with timing-attack prevention, HttpOnly session cookies, and dynamic SSRF whitelisting.

### 📚 Series & Cover Management
*   **Extended Metadata**: Fully supports Kavita's latest features (Translators, Colorists, Cover Artists, Web Links generation, Age Rating, Publisher).
*   **Auto Reading Direction**: Automatically categorizes Manga, Webtoon, or Comic reading directions based on origin.
*   **Cover Management**: Enable "Auto-Cover" in the settings, or use the built-in manual Modal to browse and select the best cover across all providers.

### 🤖 Auto-Sync & Webhook
MetaKavita can run entirely hands-free. By setting an interval in the configuration, a background task will poll Kavita for new series. Alternatively, you can use the built-in secure Webhook (`/webhook?token=YOUR_TOKEN`) directly inside Kavita for instant pushes.

### 🛠️ Installation (Docker)
1. **Clone the repository**:
   `git clone https://github.com/raukorim-bot/MetaKavita.git`
   `cd MetaKavita`

2. **Build and Launch Docker**:
   `docker compose up -d --build`

3. **Access the Dashboard**:
   Navigate to `http://localhost:5010`.

4. **Docker Environment Variables (Optional)**:
   You can inject these variables via `docker-compose.yml`:
   
   | Variable | Description | Default Value |
   | :--- | :--- | :--- |
   | `ADMIN_PASSWORD` | Secure your dashboard with a password. | *(Empty = No Auth)* |
   | `KAVITA_URL` | Your Kavita instance URL. | *(Empty)* |
   | `KAVITA_API_KEY` | Your Kavita API Key. | *(Empty)* |
   | `DEEPL_API_KEY` | Your DeepL Translation API Key. | *(Empty)* |
   | `TARGET_LANG` | Output language for summaries (`FR`, `EN`, `ES`...). | `FR` |
   | `UI_LANG` | Dashboard interface language (`fr` or `en`). | `fr` |
   | `PROVIDER_1` | Primary metadata source (`MANGABAKA`, `NAUTILJON`, `ANILIST`). | `MANGABAKA` |
   | `PROVIDER_2` | Fallback source 1. | `NAUTILJON` |
   | `SMART_COMPLETION`| Enable Data Fusion / Smart Patching (`true` or `false`). | `false` |
   | `AUTO_SYNC_INTERVAL`| Background polling interval in minutes (`0` to disable). | `0` |
   | `AUTO_COVER` | Automatically upload new covers to Kavita (`true` or `false`). | `false` |
   | `AUTO_READING_DIR` | Auto-detect and set Manga/Webtoon reading direction. | `false` |

---

## 🇫🇷 Documentation Française

MetaKavita est un outil d'automatisation conçu pour enrichir les métadonnées de ta bibliothèque [Kavita](https://kavitareader.com/). Il récupère automatiquement un maximum d'informations (résumés, années, genres, tags, staff étendu, éditeurs, âge conseillé, sens de lecture, liens externes) depuis plusieurs sources.

### ⚙️ Interface et Configuration
*   **Interface Live** : Expérience 100% AJAX avec streaming des logs, masquage des clés API, et recherche instantanée par titre.
*   **Routage Intelligent (Fallback)** : Définis une source principale et jusqu'à deux sources de secours.
*   **Complétion Intelligente (Fusion)** : Si activée, MetaKavita "bouchera les trous" de la source principale avec les données des sources de secours.
*   **Sécurité Globale** : Protection par mot de passe avec immunité contre les attaques temporelles, cookies HttpOnly, serveur WSGI Gunicorn de production, et proxy anti-SSRF.

### 📚 Gestion des Séries & Couvertures
*   **Métadonnées Étendues** : Support total des nouvelles fonctionnalités Kavita (Traducteurs, Coloristes, Sens de lecture auto, Liens Web cliquables).
*   **Couvertures (Covers)** : Module d'Auto-Cover intelligent ou gestionnaire visuel (Modal) manuel.
*   **Nettoyage Regex** : Le moteur de Regex ultra-puissant nettoie automatiquement les noms de dossiers capricieux (`01 - Titre`, `[Team] Manga`, `Perfect Edition`) pour garantir un taux de réussite maximal sur les API.

### 🤖 Auto-Sync & Webhook
MetaKavita peut fonctionner en tâche de fond via le Polling régulier, ou réagir instantanément si tu configures le Webhook sécurisé (`/webhook?token=TON_TOKEN`) directement dans Kavita.

### 🛠️ Installation (Docker)
1. **Cloner le dépôt** :
   `git clone https://github.com/raukorim-bot/MetaKavita.git`
   `cd MetaKavita`

2. **Construire et Lancer Docker** :
   `docker compose up -d --build`

3. **Accéder au Dashboard** :
   Rends-toi sur `http://localhost:5010`.

4. **Variables d'environnement Docker (Optionnel)** :
   
   | Variable | Description | Valeur par défaut |
   | :--- | :--- | :--- |
   | `ADMIN_PASSWORD` | Verrouille le dashboard par mot de passe. | *(Vide = Pas de MDP)* |
   | `KAVITA_URL` | L'URL de ton instance Kavita. | *(Vide)* |
   | `KAVITA_API_KEY` | Ta clé API Kavita. | *(Vide)* |
   | `DEEPL_API_KEY` | Ta clé API DeepL pour la traduction. | *(Vide)* |
   | `TARGET_LANG` | La langue des résumés générés (`FR`, `EN`, `ES`...). | `FR` |
   | `UI_LANG` | La langue de l'interface web (`fr` ou `en`). | `fr` |
   | `PROVIDER_1` | Source de métadonnées principale (`MANGABAKA`, `NAUTILJON`, `ANILIST`). | `MANGABAKA` |
   | `PROVIDER_2` | Source de secours 1. | `NAUTILJON` |
   | `SMART_COMPLETION`| Activer la Fusion des données (`true` ou `false`). | `false` |
   | `AUTO_SYNC_INTERVAL`| Intervalle de l'Auto-Sync en minutes (`0` pour désactiver).| `0` |
   | `AUTO_COVER` | Appliquer automatiquement les couvertures (`true` ou `false`). | `false` |
   | `AUTO_READING_DIR` | Adapter automatiquement le sens de lecture. | `false` |

---

## ⚠️ Notes & Tech Stack

*   **Security First :** La clé `SECRET_KEY` de l'application et le `WEBHOOK_TOKEN` sont auto-générés et cryptographiquement sécurisés lors du premier lancement. Ne les partagez jamais.
*   **Tech Stack :** Python 3.11, Flask, Gunicorn (Eventlet WSGI), Flask-SocketIO, Curl-Cffi, BeautifulSoup4, Regex.