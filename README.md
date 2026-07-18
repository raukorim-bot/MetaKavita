# MetaKavita
<img width="1920" height="1080" alt="MetaKavita Dashboard" src="https://github.com/user-attachments/assets/1db72309-5136-41b0-9e08-5a79f7760b8a" />

## Sommaire / Table of Contents
1. [🇺🇸 English Documentation](#-english-documentation)
2. [🇫🇷 Documentation Française](#-documentation-française)
3. [⚠️ Notes & Tech Stack](#-notes--tech-stack)

---

## 🇺🇸 English Documentation

MetaKavita is an automation tool designed to enrich metadata for your [Kavita](https://kavitareader.com/) library. It automatically retrieves information (summaries, release years, genres, tags, staff, alternative titles) from [AniList](https://anilist.co/) or [Nautiljon](https://www.nautiljon.com/) and translates summaries via [DeepL](https://www.deepl.com/).

### ⚙️ Interface and Configuration
*   **Live UI**: 100% AJAX interface (zero page reloads) with real-time logs and visually masked API keys for better security and flow.
*   **Bilingual**: Fully supported in both English and French.

#### Initial Setup
*   **Kavita URL**: The address of your Kavita instance (e.g., `http://host.docker.internal:5001`).
*   **Kavita API Key**: Key generated in Kavita's settings (Dashboard > 3rd Party Clients).
*   **DeepL API Key**: Authentication key for DeepL translation services.
*   **Translation Language**: Select the target language for your summaries.
*   **Metadata Source**: Choose between **AniList** (International) or **Nautiljon** (Francophone, with built-in Cloudflare bypass).
*   **Auto-Sync Interval**: Automate background synchronization every X minutes (Set to 0 to disable).

### 📊 Statistics Module
*   **Mini-Dashboard**: Real-time progress monitoring directly in the sidebar.
*   **Dedicated Page (`/stats`)**: Global view of your database health and caching status.

### 📚 Series Management
*   **Sync**: Update series manually or in batches (up to 50 at a time).
*   **Advanced Options**: Set specific AniList IDs or Nautiljon slugs to fix matching errors (e.g., `jujutsu-kaisen`).
*   **Filters**: Sort your library by status (Pending, Completed, Not Found, **Ignored**).
*   **Mass Actions**: Quickly ignore selections to prevent the tool from looping on unmatchable series or specific folders.

### 🤖 Auto-Sync (Background Polling)
MetaKavita can run entirely hands-free. By setting an interval in the configuration, a background task will poll Kavita for new series every X minutes. 
*   **Safe Execution**: To prevent IP bans from AniList or Nautiljon, the Auto-Sync will **only** process *new* or *pending* series. It will **never** loop indefinitely on series marked as `NOT_FOUND` or `IGNORED`.
*   **Retry Errors**: If you fixed your folder names in Kavita and want the Auto-Sync to try finding failed series again, simply click the **♻️ Reset Errors** button to revert them back to `PENDING`.

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

4. **Build and Launch**:
   Start the Docker container.
   `docker compose up -d --build`

5. **Access the Dashboard**:
   Open your browser and navigate to `http://localhost:5010` (or your server's IP address).

---

## 🇫🇷 Documentation Française

MetaKavita est un outil d'automatisation conçu pour enrichir les métadonnées de ta bibliothèque [Kavita](https://kavitareader.com/). Il récupère automatiquement les informations (résumés, années, genres, tags, personnel, titres alternatifs) depuis [AniList](https://anilist.co/) ou [Nautiljon](https://www.nautiljon.com/) et traduit les résumés via [DeepL](https://www.deepl.com/).

### ⚙️ Interface et Configuration
*   **Interface Live** : Expérience 100% AJAX (zéro rechargement) avec streaming des logs console en temps réel et masquage sécurisé des mots de passe.
*   **Bilingue** : Interface entièrement traduite en Français et Anglais.

#### Configuration initiale
*   **URL Kavita** : L'adresse de ton instance Kavita (ex: `http://host.docker.internal:5001`).
*   **Clé API Kavita** : Clé générée dans les paramètres de ton instance Kavita (Dashboard > 3rd Party Clients).
*   **Clé API DeepL** : Clé d'authentification pour le service de traduction DeepL.
*   **Langue de traduction** : Sélectionne la langue cible pour les résumés.
*   **Source de métadonnées** : Choix entre **AniList** (International) et **Nautiljon** (Francophone, avec contournement natif des protections Cloudflare).
*   **Intervalle Auto-Sync** : Automatise la synchronisation en tâche de fond toutes les X minutes (0 pour désactiver).

### 📊 Module de Statistiques
*   **Mini-Dashboard** : Suivi en temps réel de la progression dans la barre latérale.
*   **Page dédiée (`/stats`)** : Vue globale de la santé de ta base de données et du cache.

### 📚 Gestion des séries
*   **Synchronisation** : Mise à jour manuelle ou par lots (batch par paquets de 50).
*   **Options avancées** : Définition d'IDs AniList ou de slugs Nautiljon (ex: `jujutsu-kaisen`) pour corriger les erreurs de correspondance.
*   **Filtres** : Tri de la bibliothèque par statut (À traiter, Complétées, Introuvables, **Ignorées**).
*   **Actions de masse** : Possibilité d'ignorer rapidement toute une sélection pour empêcher l'outil de boucler indéfiniment sur des séries introuvables.

### 🤖 Auto-Sync (Tâche de fond)
MetaKavita peut fonctionner de manière totalement autonome. En définissant un intervalle dans la configuration, une tâche de fond interrogera Kavita pour récupérer les nouvelles séries toutes les X minutes.
*   **Exécution sécurisée** : Pour éviter le bannissement de votre IP par AniList ou Nautiljon, l'Auto-Sync ciblera **uniquement** les séries *nouvelles* ou *en attente*. Il ne bouclera **jamais** indéfiniment sur les séries "Introuvables" (`NOT_FOUND`) ou "Ignorées".
*   **Relancer les erreurs** : Si vous avez corrigé les noms de vos dossiers dans Kavita et souhaitez que l'Auto-Sync retente sa chance, cliquez simplement sur le bouton **♻️ Amnistie Erreurs** pour les repasser "En attente".

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

4. **Construire et Lancer** :
   Démarre le conteneur Docker.
   `docker compose up -d --build`

5. **Accéder au Dashboard** :
   Ouvre ton navigateur et rends-toi sur `http://localhost:5010` (ou l'IP de ton serveur).

---

## ⚠️ Notes & Tech Stack

### Security / Sécurité
*   🇬🇧 **Never share your `config.json`.** Keep it private. Ensure it is included in your `.gitignore`.
*   🇫🇷 **Ne partage jamais ton `config.json`.** Garde-le privé et vérifie qu'il est bien dans ton `.gitignore`.

### Scraping Limits / Limites de Scraping
*   🇬🇧 The script enforces a **dynamic delay** between each API call to strictly respect provider quotas and maximize speed (AniList: 1.0s, Nautiljon: 1.5s, MangaBaka: 2.5s). Use the "Live Logs" to monitor operations.
*   🇫🇷 Le script impose un **délai dynamique** entre chaque appel API pour maximiser la vitesse tout en respectant les quotas (AniList : 1.0s, Nautiljon : 1.5s, MangaBaka : 2.5s). Utilise les "Live Logs" pour surveiller les opérations.

### Tech Stack
- **Backend**: Python 3.11, Flask, Flask-SocketIO, Curl-Cffi, BeautifulSoup4.
- **Database**: SQLite.
- **Deployment**: Docker (Alpine).