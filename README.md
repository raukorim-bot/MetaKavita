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
#### Initial Setup
*   **Kavita URL**: The address of your Kavita instance (e.g., `http://host.docker.internal:5001`).
*   **Kavita API Key**: Key generated in Kavita's settings (Dashboard > 3rd Party Clients).
*   **DeepL API Key**: Authentication key for DeepL translation services.
*   **Translation Language**: Select the target language for your summaries.
*   **Metadata Source**: Choose between **AniList** (International) or **Nautiljon** (Francophone, with built-in Cloudflare bypass).

### 📊 Statistics Module
*   **Mini-Dashboard**: Real-time progress monitoring directly in the sidebar.
*   **Dedicated Page (`/stats`)**: Global view of your database health and caching status.

### 📚 Series Management
*   **Sync**: Update series manually or in batches (up to 50 at a time).
*   **Advanced Options**: Set specific AniList IDs or Nautiljon slugs to fix matching errors (e.g., `jujutsu-kaisen`).
*   **Filters**: Sort your library by status (Pending, Completed, Not Found).

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
#### Configuration initiale
*   **URL Kavita** : L'adresse de ton instance Kavita (ex: `http://host.docker.internal:5001`).
*   **Clé API Kavita** : Clé générée dans les paramètres de ton instance Kavita (Dashboard > 3rd Party Clients).
*   **Clé API DeepL** : Clé d'authentification pour le service de traduction DeepL.
*   **Langue de traduction** : Sélectionne la langue cible pour les résumés.
*   **Source de métadonnées** : Choix entre **AniList** (International) et **Nautiljon** (Francophone, avec contournement natif des protections Cloudflare).

### 📊 Module de Statistiques
*   **Mini-Dashboard** : Suivi en temps réel de la progression dans la barre latérale.
*   **Page dédiée (`/stats`)** : Vue globale de la santé de ta base de données et du cache.

### 📚 Gestion des séries
*   **Synchronisation** : Mise à jour manuelle ou par lots (batch par paquets de 50).
*   **Options avancées** : Définition d'IDs AniList ou de slugs Nautiljon (ex: `jujutsu-kaisen`) pour corriger les erreurs de correspondance.
*   **Filtres** : Tri de la bibliothèque par statut (À traiter, Complétées, Introuvables).

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
*   🇬🇧 The script enforces a **1.5s delay** between each API call to respect provider quotas and avoid IP bans. Use the "Live Logs" to monitor operations.
*   🇫🇷 Le script impose un délai de **1.5s** entre chaque appel API pour respecter les quotas et éviter les bannissements d'IP. Utilise les "Live Logs" pour surveiller les opérations.

### Tech Stack
- **Backend**: Python 3.11, Flask, Flask-SocketIO, Curl-Cffi, BeautifulSoup4.
- **Database**: SQLite.
- **Deployment**: Docker (Alpine).
