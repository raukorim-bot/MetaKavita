# MetaKavita

MetaKavita is an automated metadata enricher and manager for [Kavita](https://kavitareader.com/). It scrapes summaries, release years, publication status, genres, tags, staff members, publishers, age ratings, and reading directions from public sources, translates summaries with DeepL, and pushes them directly into your Kavita instance.

---

## Sommaire / Table of Contents
1. [🇺🇸 English Documentation](#-english-documentation)
   * [User Interface & Ergonomics](#-user-interface--ergonomics)
   * [Enriched Metadata Fields](#-enriched-metadata-fields)
   * [Installation (Zero-Effort & Source)](#-installation)
   * [Configuration Variables](#-configuration-variables)
   * [Auto-Sync & Webhooks](#-auto-sync--webhooks)
2. [🇫🇷 Documentation Française](#-documentation-française)
   * [Interface Utilisateur & Ergonomie](#-interface-utilisateur--ergonomie)
   * [Métadonnées Enrichies](#-métadonnées-enrichies)
   * [Installation (Zéro-Effort & Sources)](#-installation-1)
   * [Variables de Configuration](#-variables-de-configuration)
   * [Auto-Sync & Webhooks](#-auto-sync--webhooks-1)
3. [⚠️ Notes & Tech Stack](#-notes--tech-stack)

---

## 🇺🇸 English Documentation

### 🎨 User Interface & Ergonomics (V1.4.0)

MetaKavita has been completely redesigned in version 1.4.0 to separate background configuration from daily operational strategy.

#### 1. Main Dashboard & Workspace Persistence
The interface uses a 100% AJAX layout with zero page reloads. The left sidebar handles active strategic options, while the main panel presents your library. Thanks to local storage persistence, the dashboard automatically remembers your selected library, status filter, hide ignored state, and search query between sessions.

![MetaKavita Main Dashboard](./assets/dashboard.png)

#### 2. Clean, Dual-Form Architecture (Modal + Sidebar)
Technical infrastructure fields are isolated inside the **Global Configuration Modal** (accessible via the ⚙️ Config button in the topbar), preserving your workspace from configuration clutter.
The left sidebar contains only the **Scraping Options** card for quick tactical switches (Smart Completion, Auto-Covers, Auto-Reading Direction, Force Update) and the download button for your error reports.

![Global Configuration Modal](./assets/config_modal.png)
![Scraping Options Card](./assets/scraping_options.png)

#### 3. Unified Filtering & Central Toolbar
The Library Selector, Search bar, and Status Filter are consolidated into a single horizontal toolbar. This puts all target controls on one cohesive line.
To the right, the **Expand/Collapse All** (`📐`) button allows you to toggle open all individual overrides panels for fast mass editing, next to the **Save All Overrides** button.

![Central Toolbar](./assets/toolbar.png)

#### 4. Advanced Per-Series Controls & Quick Lookup
Each series has an advanced Options panel. If a series is unmatched, click the search icon (`🔍`) next to the AniList ID field to open a pre-filled AniList search in a new tab to find the ID.

![Override & Advanced Panel](./assets/override_panel.png)

#### 5. Manual & Smart Cover Management
You can enable auto-cover replacement or browse covers manually. The manual cover modal includes a **manual search input**, allowing you to enter alternate or translated titles on the fly to find correct covers without modifying your database.

![Cover Selection Modal](./assets/cover_modal.png)

#### 6. Live Processing Tracker & WS Logs
During batch execution, the active series being processed pulses with a glowing purple outline (`.is-processing`) and automatically scrolls into view. Badge statuses update dynamically on completion. The console displays real-time logs streamed via WebSockets.

![Live Logs Card](./assets/terminal.png)

#### 7. Global Authentication
The entire application can be locked behind a secure login screen with Timing-Attack immunity and brute-force delays.

![Active Lock Screen](./assets/login.png)

---

### 📚 Enriched Metadata Fields

MetaKavita maps and automatically locks the following metadata fields directly into Kavita's database structure:

| Category | Metadata Fields | Mapped Source Details |
| :--- | :--- | :--- |
| **Core Details** | Localized Name / Alternative Titles | Joins localized titles with a `" / "` separator |
| | Summary / Description | Scraped in source language, translated via DeepL |
| | Release Year | Publication start year |
| | Publication Status | Maps to native codes: Ongoing, On Hiatus, Completed, Cancelled |
| **Collections & Lore** | Genres | Comprehensive mapping from visited sources |
| | Tags | Top 15 thematic categories |
| | Characters | Rich character lists populated in Kavita |
| **Staff & Editing** | Writers | Original Story authors & Scriptwriters |
| | Pencillers | Illustrators & Artists |
| | Colorists | Coloring staff |
| | Translators | Translation credits / Localization groups |
| | Cover Artists | Original cover artists |
| | Publisher | Official licensing publisher |
| **Classifications** | Reading Direction (Format) | Automatically set to Left-to-Right, Right-to-Left, or Vertical |
| | Age Rating | Maps to native ratings: Safe, Suggestive, Erotica, Pornographic |
| **External IDs** | External Platform IDs | Saves `AniListId`, `MalId`, and `MangaBakaId` |
| | Web Links | Builds active clickable direct URLs to official series pages |

---

### 🚀 Installation

#### Option A: Pull pre-built image (Zero-Effort - Recommended)
No cloning required. Create a `docker-compose.yml` file anywhere on your server with the following content:

```yaml
services:
  metakavita:
    image: ghcr.io/raukorim-bot/metakavita:latest
    container_name: metakavita
    restart: unless-stopped
    ports:
      - "5010:5010"
    environment:
      - ADMIN_PASSWORD=your_secure_password
    volumes:
      - ./data:/app/data
```
Run `docker compose up -d` to launch the dashboard instantly on `http://localhost:5010`.

#### Option B: Build from Source
If you want to modify the code or run a custom build:
```bash
git clone https://github.com/raukorim-bot/MetaKavita.git
cd MetaKavita
docker compose up -d --build
```

---

### ⚙️ Configuration Variables

| Variable | Description | Default Value |
| :--- | :--- | :--- |
| `ADMIN_PASSWORD` | Secures the dashboard with a password. | *(Empty = No Auth)* |
| `KAVITA_URL` | Your Kavita instance URL. | *(Empty)* |
| `KAVITA_API_KEY` | Your Kavita API Key. | *(Empty)* |
| `DEEPL_API_KEY` | Your DeepL Translation API Key. | *(Empty)* |
| `TARGET_LANG` | Output language for summaries (`FR`, `EN`, `ES`...). | `FR` |
| `UI_LANG` | Dashboard interface language (`fr` or `en`). | `fr` |
| `PROVIDER_1` | Primary metadata source (`MANGABAKA`, `NAUTILJON`, `ANILIST`). | `MANGABAKA` |
| `PROVIDER_2` | Fallback source 1. | `NAUTILJON` |
| `PROVIDER_3` | Fallback source 2. | `ANILIST` |
| `SMART_COMPLETION`| Enable Data Fusion / Smart Patching (`true` or `false`). | `false` |
| `AUTO_SYNC_INTERVAL`| Background polling interval in minutes (`0` to disable). | `0` |
| `AUTO_COVER` | Automatically upload new covers to Kavita (`true` or `false`). | `false` |
| `AUTO_READING_DIR` | Auto-detect and set Manga/Webtoon reading direction. | `false` |

---

### 🤖 Auto-Sync & Webhooks

#### 1. Background Polling (Auto-Sync)
Setting `AUTO_SYNC_INTERVAL` to a value higher than `0` schedules a background task that regularly checks for new or pending series.

#### 2. Real-Time Webhook
For immediate enrichment upon import, configure a Webhook in Kavita pointing to your instance:
`http://<your-metakavita-ip>:5010/webhook?token=<YOUR_WEBHOOK_TOKEN>`
*(The secure `WEBHOOK_TOKEN` is automatically generated inside `data/config.json` on first launch).*

---

## 🇫🇷 Documentation Française

### 🎨 Interface Utilisateur & Ergonomie (V1.4.0)

MetaKavita a été entièrement repensé dans sa version 1.4.0 pour séparer la configuration technique de la stratégie de scraping opérationnelle.

#### 1. Tableau de Bord & Persistance de l'Espace de Travail
L'interface utilise une structure 100% AJAX (zéro rechargement de page). La barre latérale gauche gère la stratégie active tandis que le panneau central affiche tes œuvres. Grâce au stockage local (`localStorage`), le tableau de bord se souvient automatiquement de tes filtres (bibliothèque sélectionnée, tri de statut, barre de recherche et masquage des ignorés) d'une session à l'autre.

![Tableau de bord MetaKavita](./assets/dashboard.png)

#### 2. Architecture Double-Formulaire (Modal + Sidebar)
Les champs d'infrastructure technique sont isolés dans la **Configuration Globale** (accessible via le bouton ⚙️ Config dans la barre supérieure), protégeant ton espace de travail de l'encombrement.
La barre latérale ne contient plus que la carte **Options de Scraping** (Fusion intelligente, Auto-Covers, Sens de lecture auto, Mise à jour forcée) et l'export des erreurs.

![Modal de Configuration Globale](./assets/config_modal.png)
![Options de Scraping](./assets/scraping_options.png)

#### 3. Filtrage Unifié & Toolbar Centrale
Le sélecteur de bibliothèque, la barre de recherche et le filtre de statut sont regroupés dans une seule barre d'outils centrale. Toutes les commandes de ciblage se situent ainsi sur une même ligne horizontale cohérente.
À droite, le bouton **Déplier/Replier tout** (`📐`) permet de basculer l'affichage de tous les panneaux individuels pour des corrections rapides, aux côtés du bouton de sauvegarde globale.

![Barre d'outils centrale](./assets/toolbar.png)

#### 4. Contrôles de Séries & Recherche d'ID rapide
Chaque série dispose d'un volet d'options avancées. Si une œuvre n'est pas trouvée, un clic sur l'icône de recherche (`🔍`) à côté du champ d'ID AniList ouvre une recherche AniList pré-remplie dans un nouvel onglet pour trouver l'ID.

![Options avancées de séries](./assets/override_panel.png)

#### 5. Gestion de Couvertures Manuelle & Intelligente
Tu peux activer l'auto-cover ou choisir tes couvertures visuellement. La modal intègre une **barre de recherche manuelle** permettant de saisir un titre alternatif ou traduit à la volée pour trouver des images sans modifier ta base de données.

![Modal de choix des couvertures](./assets/cover_modal.png)

#### 6. Suivi Live & Logs WebSockets
Pendant l'exécution d'un lot, la série en cours de traitement clignote avec une pulsation violette (`.is-processing`) et défile automatiquement à l'écran. Les badges de statut se mettent à jour dynamiquement. La console affiche en temps réel les logs envoyés via WebSockets.

![Terminal de logs](./assets/terminal.png)

#### 7. Authentification Globale
L'application peut être verrouillée par un écran de connexion sécurisé contre les attaques temporelles et par force brute.

![Écran de verrouillage](./assets/login.png)

---

### 📚 Métadonnées Enrichies

MetaKavita traite et verrouille automatiquement les champs de métadonnées suivants directement dans la structure de données de Kavita :

| Catégorie | Métadonnée Kavita | Détails de la source mappée |
| :--- | :--- | :--- |
| **Identité** | Titre Localisé / Alternatif | Assemble les titres alternatifs officiels séparés par `" / "` |
| | Résumé / Description | Récupère le résumé d'origine et le traduit via DeepL |
| | Année de sortie | Année de début de publication |
| | Statut de publication | Mappe vers les statuts natifs : En cours, En pause, Terminé, Abandonné |
| **Thématiques** | Genres | Liste complète des genres récupérés |
| | Thèmes (Tags) | Les 15 catégories thématiques les plus importantes |
| | Personnages | Liste enrichie des personnages secondaires |
| **Staff & Édition** | Scénaristes (Writers) | Auteur de l'œuvre d'origine / Scénaristes |
| | Dessinateurs (Pencillers) | Illustrateurs et artistes principaux |
| | Coloristes | Équipe de colorisation |
| | Traducteurs | Groupes de scantrad / Traducteurs officiels |
| | Dessinateurs de couverture | Artistes des couvertures originales |
| | Éditeur (Publisher) | Éditeur officiel licencié |
| **Classifications** | Sens de lecture (Format) | Configuré automatiquement en Gauche-à-Droite, Droite-à-Gauche ou Vertical |
| | Classification d'Âge | Mappage natif : Sûr (Safe), Suggestif, Érotique, Pornographique |
| **ID & Liens** | Identifiants Plateformes | Renseigne directement `AniListId`, `MalId` et `MangaBakaId` |
| | Liens Web (WebLinks) | Génère des URL directes pour afficher les icônes cliquables dans Kavita |

---

### 🚀 Installation

#### Option A : Télécharger l'image pré-compilée (Zéro effort - Recommandé)
Aucun clonage de dépôt n'est requis. Crée simplement un fichier `docker-compose.yml` sur ton serveur contenant ce bloc :

```yaml
services:
  metakavita:
    image: ghcr.io/raukorim-bot/metakavita:latest
    container_name: metakavita
    restart: unless-stopped
    ports:
      - "5010:5010"
    environment:
      - ADMIN_PASSWORD=votre_mot_de_passe_securise
    volumes:
      - ./data:/app/data
```
Lance la commande `docker compose up -d` pour exécuter instantanément MetaKavita sur `http://localhost:5010`.

#### Option B : Compiler depuis les sources
Idéal si tu souhaites modifier le code ou exécuter une build personnalisée :
```bash
git clone https://github.com/raukorim-bot/MetaKavita.git
cd MetaKavita
docker compose up -d --build
```

---

### ⚙️ Variables de Configuration

| Variable | Description | Valeur par défaut |
| :--- | :--- | :--- |
| `ADMIN_PASSWORD` | Sécurise l'interface par mot de passe. | *(Vide = Pas d'Auth)* |
| `KAVITA_URL` | L'URL de ton instance Kavita. | *(Vide)* |
| `KAVITA_API_KEY` | Ta clé API Kavita. | *(Vide)* |
| `DEEPL_API_KEY` | Ta clé API DeepL pour la traduction. | *(Vide)* |
| `TARGET_LANG` | Langue cible des résumés (`FR`, `EN`, `ES`...). | `FR` |
| `UI_LANG` | Langue de l'interface MetaKavita (`fr` ou `en`). | `fr` |
| `PROVIDER_1` | Source de métadonnées principale (`MANGABAKA`, `NAUTILJON`, `ANILIST`). | `MANGABAKA` |
| `PROVIDER_2` | Source de secours 1. | `NAUTILJON` |
| `PROVIDER_3` | Source de secours 2. | `ANILIST` |
| `SMART_COMPLETION`| Activer la fusion des données (`true` ou `false`). | `false` |
| `AUTO_SYNC_INTERVAL`| Intervalle d'Auto-Sync en minutes (`0` pour désactiver). | `0` |
| `AUTO_COVER` | Envoyer automatiquement les couvertures à Kavita (`true` ou `false`). | `false` |
| `AUTO_READING_DIR` | Configurer automatiquement le sens de lecture. | `false` |

---

### 🤖 Auto-Sync & Webhooks

#### 1. Planification en arrière-plan (Auto-Sync)
Si `AUTO_SYNC_INTERVAL` est supérieur à `0`, MetaKavita vérifie périodiquement la présence de nouvelles séries ou de fiches en attente pour lancer leur enrichissement.

#### 2. Webhook temps réel
Pour un enrichissement instantané à l'import, configure un Webhook dans Kavita pointant vers MetaKavita :
`http://<ton-ip-metakavita>:5010/webhook?token=<TON_WEBHOOK_TOKEN>`
*(Le jeton sécurisé `WEBHOOK_TOKEN` est généré automatiquement dans `data/config.json` au premier lancement).*

---

## ⚠️ Notes & Tech Stack

*   **Security First :** `SECRET_KEY` and `WEBHOOK_TOKEN` are cryptographically generated on first launch. Keep them private.
*   **Tech Stack :** Python 3.11, Flask, Gunicorn (Eventlet WSGI), Flask-SocketIO, Curl-Cffi, BeautifulSoup4, Regex.