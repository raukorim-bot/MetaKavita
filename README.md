# MetaKavita
<img width="1920" height="1080" alt="MetaKavita Dashboard" src="https://github.com/user-attachments/assets/1db72309-5136-41b0-9e08-5a79f7760b8a" />

## Sommaire / Table of Contents
1. [🇺🇸 English Documentation](#-english-documentation)
2. [🇫🇷 Documentation Française](#-documentation-française)
3. [⚠️ Notes & Tech Stack](#-notes--tech-stack)

---

## 🇺🇸 English Documentation

MetaKavita is an automation tool designed to enrich metadata for your [Kavita](https://kavitareader.com/) library. It automatically retrieves information (summaries, release years, genres, tags, staff, publishers, age ratings, alternative titles) from multiple sources and translates summaries via [DeepL](https://www.deepl.com/).

### ⚙️ Interface and Configuration
*   **Live UI**: 100% AJAX interface (zero page reloads) with real-time logs, visually masked API keys, and explicit connection error screens.
*   **Smart Routing (Fallback)**: Define a main metadata source and up to two backups (e.g., MangaBaka > Nautiljon > AniList). If the first fails, MetaKavita seamlessly asks the next one.
*   **Smart Completion (Data Fusion)**: If enabled, MetaKavita will patch incomplete metadata. If your main source finds the summary but is missing genres, the tool will fetch *only* the missing genres from the backup sources to create the ultimate metadata file!

### 📚 Series & Cover Management
*   **Mass Actions & Ignore Status**: Quickly ignore selections to prevent the tool from looping on unmatchable series or specific folders.
*   **Cover Management**: Enable "Auto-Cover" in the settings to automatically fetch and upload HD covers to Kavita, or use the built-in manual Modal to browse and select the best cover across all providers.

### 📊 Statistics & Cache Module
*   **Mini-Dashboard**: Real-time progress monitoring directly in the sidebar.
*   **Auto-Cleaning Cache**: The internal SQLite cache automatically detects if you delete a series in Kavita and purges ghost entries to keep your statistics perfectly accurate.

### 🤖 Auto-Sync (Background Polling)
MetaKavita can run entirely hands-free. By setting an interval in the configuration, a background task will poll Kavita for new series every X minutes while strictly respecting API rate limits (dynamic delays).

### 🛠️ Installation
Before launching the container, you must prepare the environment and craft the necessary configuration files.

1. **Clone the repository**:
   `git clone https://github.com/raukorim-bot/MetaKavita.git`
   `cd MetaKavita`

2. **Initialize the environment**:
   Run the setup script to create the required directories, cache database, and the dummy configuration file.
   `chmod +x setup.sh`
   `./setup.sh`

3. **Configure your API Keys**:
   Edit the freshly generated `config.json` file to include your personal API keys. Without this, the container might fail to interact with Kavita or DeepL.
   `nano config.json`

4. **Docker Environment Variables**:
   All configuration options can be modified directly in the Web UI. However, you can also inject them via your `docker-compose.yml` to initialize your `config.json`.
   
   | Variable | Description | Default Value |
   | :--- | :--- | :--- |
   | `KAVITA_URL` | Your Kavita instance URL (e.g., `http://192.168.1.50:5001`). | *(Empty)* |
   | `KAVITA_API_KEY` | Your Kavita API Key. | *(Empty)* |
   | `DEEPL_API_KEY` | Your DeepL Translation API Key. | *(Empty)* |
   | `TARGET_LANG` | Output language for summaries (e.g., `FR`, `EN`, `ES`). | `FR` |
   | `UI_LANG` | Dashboard interface language (`fr` or `en`). | `fr` |
   | `PROVIDER_1` | Primary metadata source (`MANGABAKA`, `NAUTILJON`, `ANILIST`). | `MANGABAKA` |
   | `PROVIDER_2` | Fallback source 1 (`NONE` to disable). | `NAUTILJON` |
   | `PROVIDER_3` | Fallback source 2 (`NONE` to disable). | `ANILIST` |
   | `SMART_COMPLETION`| Enable Data Fusion / Smart Patching (`true` or `false`). | `false` |
   | `AUTO_SYNC_INTERVAL`| Background polling interval in minutes (`0` to disable). | `0` |
   | `AUTO_COVER` | Automatically upload new covers to Kavita (`true` or `false`). | `false` |

5. **Build and Launch**:
   Start the Docker container.
   `docker compose up -d --build`

6. **Access the Dashboard**:
   Open your browser and navigate to `http://localhost:5010` (or your server's IP address).

---

## 🇫🇷 Documentation Française

MetaKavita est un outil d'automatisation conçu pour enrichir les métadonnées de ta bibliothèque [Kavita](https://kavitareader.com/). Il récupère automatiquement les informations (résumés, années, genres, tags, personnel, éditeurs, âge) depuis plusieurs sources et traduit les résumés via [DeepL](https://www.deepl.com/).

### ⚙️ Interface et Configuration
*   **Interface Live** : Expérience 100% AJAX (zéro rechargement) avec streaming des logs, masquage des clés et écrans explicites en cas d'erreur de connexion.
*   **Routage Intelligent (Fallback)** : Définis une source principale et jusqu'à deux sources de secours. Si la première échoue, l'outil interroge automatiquement la suivante.
*   **Complétion Intelligente (Fusion)** : Si activée, MetaKavita "bouchera les trous". Si ta source principale trouve le résumé mais pas les genres, l'outil ira chercher *uniquement* les genres manquants sur les autres sources pour créer la fiche parfaite !

### 📚 Gestion des Séries & Couvertures
*   **Statut "Ignoré" et Actions de Masse** : Possibilité d'ignorer rapidement toute une sélection pour empêcher l'outil de boucler indéfiniment sur des séries introuvables.
*   **Couvertures (Covers)** : Active l'option "Auto-Cover" pour appliquer automatiquement les couvertures HD trouvées, ou utilise le gestionnaire visuel (Modal) pour choisir manuellement la meilleure couverture parmi tous les fournisseurs.

### 📊 Module de Statistiques et Cache
*   **Mini-Dashboard** : Suivi en temps réel de la progression.
*   **Cache Auto-nettoyant** : Si tu supprimes une série directement dans Kavita, le cache SQLite de MetaKavita s'en rend compte et purge la "série fantôme" pour garder des statistiques justes.

### 🤖 Auto-Sync (Tâche de fond)
MetaKavita peut fonctionner de manière totalement autonome. En définissant un intervalle, une tâche de fond traitera les nouvelles séries tout en respectant scrupuleusement les quotas des API (délais dynamiques).

### 🛠️ Installation
Avant de lancer le conteneur, tu dois obligatoirement préparer l'environnement et crafter les fichiers de configuration.

1. **Cloner le dépôt** :
   `git clone https://github.com/raukorim-bot/MetaKavita.git`
   `cd MetaKavita`

2. **Initialiser l'environnement** :
   Lance le script de configuration pour créer les dossiers requis, la base de données de cache et le fichier de configuration vierge.
   `chmod +x setup.sh`
   `./setup.sh`

3. **Configurer tes clés API** :
   Édite le fichier `config.json` fraîchement créé pour y ajouter tes propres clés. Sans cela, le conteneur ne pourra pas communiquer avec Kavita ou DeepL.
   `nano config.json`

4. **Variables d'environnement Docker** :
   Tous ces paramètres peuvent être modifiés directement depuis l'interface web. Cependant, tu peux les déclarer dans ton `docker-compose.yml` pour initialiser la configuration de ton conteneur.
   
   | Variable | Description | Valeur par défaut |
   | :--- | :--- | :--- |
   | `KAVITA_URL` | L'URL de ton instance Kavita (ex: `http://192.168.1.50:5001`). | *(Vide)* |
   | `KAVITA_API_KEY` | Ta clé API Kavita. | *(Vide)* |
   | `DEEPL_API_KEY` | Ta clé API DeepL pour la traduction. | *(Vide)* |
   | `TARGET_LANG` | La langue des résumés générés (ex: `FR`, `EN`, `ES`). | `FR` |
   | `UI_LANG` | La langue de l'interface web (`fr` ou `en`). | `fr` |
   | `PROVIDER_1` | Source de métadonnées principale (`MANGABAKA`, `NAUTILJON`, `ANILIST`). | `MANGABAKA` |
   | `PROVIDER_2` | Source de secours 1 (`NONE` pour désactiver). | `NAUTILJON` |
   | `PROVIDER_3` | Source de secours 2 (`NONE` pour désactiver). | `ANILIST` |
   | `SMART_COMPLETION`| Activer la Fusion des données (`true` ou `false`). | `false` |
   | `AUTO_SYNC_INTERVAL`| Intervalle de l'Auto-Sync en minutes (`0` pour désactiver).| `0` |
   | `AUTO_COVER` | Activer l'envoi automatique des couvertures à Kavita (`true` ou `false`). | `false` |

5. **Construire et Lancer** :
   Démarre le conteneur Docker.
   `docker compose up -d --build`

6. **Accéder au Dashboard** :
   Ouvre ton navigateur et rends-toi sur `http://localhost:5010` (ou l'IP de ton serveur).

---

## ⚠️ Notes & Tech Stack

### Security / Sécurité
*   🇬🇧 **Never share your `config.json`.** Keep it private. Ensure it is included in your `.gitignore`.
*   🇫🇷 **Ne partage jamais ton `config.json`.** Garde-le privé et vérifie qu'il est bien dans ton `.gitignore`.

### Scraping Limits / Limites de Scraping
*   🇬🇧 The script enforces a **dynamic delay** between each API call to strictly respect provider quotas and maximize speed (AniList: 1.0s, Nautiljon: 1.5s, MangaBaka: 2.5s). 
*   🇫🇷 Le script impose un **délai dynamique** entre chaque appel API pour maximiser la vitesse tout en respectant les quotas (AniList : 1.0s, Nautiljon : 1.5s, MangaBaka : 2.5s).

### Tech Stack
- **Backend**: Python 3.11, Flask, Flask-SocketIO, Curl-Cffi, BeautifulSoup4.
- **Database**: SQLite (Self-cleaning algorithm).
- **Deployment**: Docker (Alpine).