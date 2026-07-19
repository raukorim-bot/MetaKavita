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

### 🛠️ Installation (Zero-Setup)
Thanks to its auto-generating architecture, deploying MetaKavita is as easy as starting the container!

1. **Clone the repository**:
   `git clone https://github.com/raukorim-bot/MetaKavita.git`
   `cd MetaKavita`

2. **Build and Launch Docker**:
   Start the Docker container. It will automatically generate a `data/` folder containing your `config.json`, database, and logs.
   `docker compose up -d --build`

3. **Access the Dashboard**:
   Open your browser and navigate to `http://localhost:5010` (or your server's IP address). You can safely configure all your API keys directly from the Web UI!

4. **Docker Environment Variables (Optional)**:
   If you prefer configuring the app via your `docker-compose.yml` instead of the Web UI, you can inject these variables:
   
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

### 🛠️ Installation (Zero-Setup)
Grâce à son architecture auto-générée, déployer MetaKavita est aussi simple que de lancer le conteneur ! Plus de script `setup.sh` requis.

1. **Cloner le dépôt** :
   `git clone https://github.com/raukorim-bot/MetaKavita.git`
   `cd MetaKavita`

2. **Construire et Lancer Docker** :
   Démarre le conteneur. Il génèrera automatiquement un dossier `/data` contenant ton `config.json`, la base de données et les logs.
   `docker compose up -d --build`

3. **Accéder au Dashboard** :
   Ouvre ton navigateur et rends-toi sur `http://localhost:5010` (ou l'IP de ton serveur). Tu peux configurer toutes tes clés API en toute sécurité directement depuis l'interface web !

4. **Variables d'environnement Docker (Optionnel)** :
   Si tu préfères initialiser ton conteneur sans utiliser l'interface web, tu peux déclarer ces variables dans ton `docker-compose.yml`.
   
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

---

## ⚠️ Notes & Tech Stack

### Security / Sécurité
*   🇬🇧 **Never share your `data/config.json`.** Keep it private. Ensure the `data/` folder is included in your `.gitignore`.
*   🇫🇷 **Ne partage jamais ton `data/config.json`.** Garde-le privé et vérifie que le dossier `data/` est bien dans ton `.gitignore`.

### Scraping Limits / Limites de Scraping
*   🇬🇧 The script enforces a **dynamic delay** between each API call to strictly respect provider quotas and maximize speed (AniList: 1.0s, Nautiljon: 1.5s, MangaBaka: 2.5s). 
*   🇫🇷 Le script impose un **délai dynamique** entre chaque appel API pour maximiser la vitesse tout en respectant les quotas (AniList : 1.0s, Nautiljon : 1.5s, MangaBaka : 2.5s).

### Tech Stack
- **Backend**: Python 3.11, Flask, Flask-SocketIO, Curl-Cffi, BeautifulSoup4.
- **Database**: SQLite (Self-cleaning algorithm).
- **Deployment**: Docker (Alpine).