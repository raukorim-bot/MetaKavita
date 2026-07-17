# MetaKavita
<img width="1920" height="1080" alt="{6E249195-1237-4C12-A779-14CDBF1C981B}" src="https://github.com/user-attachments/assets/1db72309-5136-41b0-9e08-5a79f7760b8a" />

Outil d'automatisation conçu pour enrichir les métadonnées de ta bibliothèque [Kavita](https://kavitareader.com/). Il récupère automatiquement les informations (résumés, années, genres, tags, personnel, titres alternatifs) depuis [AniList](https://anilist.co/) ou [Nautiljon](https://www.nautiljon.com/) et traduit les résumés via [DeepL](https://www.deepl.com/).

## ⚙️ Interface et Configuration

### Configuration initiale
*   **URL Kavita** : L'adresse de ton instance Kavita (ex: `http://host.docker.internal:5001`).
*   **Clé API Kavita** : Clé générée dans les paramètres de ton instance Kavita pour permettre au script d'interagir avec ta bibliothèque.
*   **Clé API DeepL** : Clé d'authentification pour le service de traduction.
*   **Langue de traduction** : Sélectionne la langue cible pour les résumés (Français, Anglais, Espagnol, Allemand, etc.).
*   **Source de métadonnées** : Permet de choisir entre **AniList** (International) et **Nautiljon** (Francophone, avec contournement natif des protections Cloudflare et jeton de recherche ST).

## 📊 Module de Statistiques
L'application intègre un suivi en temps réel de l'état de ton catalogue :
*   **Mini-Dashboard** : Directement visible dans la barre latérale gauche pour suivre la proportion de séries enrichies, en attente ou introuvables via une jauge de progression.
*   **Page dédiée (`/stats`)** : Un panneau de contrôle global offrant une vision macro de la santé de ta base de données cache.

## 📚 Gestion des séries

### Synchronisation
*   **Liste des séries** : Affiche toutes les séries de la bibliothèque sélectionnée avec un **compteur dynamique d'éléments restants** ajusté automatiquement selon tes filtres.
*   **Mettre à jour** : Déclenche manuellement la recherche, la sauvegarde automatique des surcharges et la mise à jour pour une série spécifique.
*   **Lancer le batch sur la sélection** : Applique le processus d'enrichissement par paquets de 50 à toutes les séries cochées, avec suivi de l'avancement et décompte des éléments restants dans la console de logs.
*   **Forcer la mise à jour** : Si coché, écrase les métadonnées existantes sur Kavita, même si elles sont déjà présentes.

### Options avancées (par série)
En cliquant sur le bouton **"Options"** à côté d'une série, tu peux définir des paramètres de recherche spécifiques pour corriger les erreurs de correspondance :
*   **ID AniList / Slug Nautiljon** : Force l'utilisation d'un ID numérique précis pour AniList ou du slug textuel de l'URL pour Nautiljon (ex: `jujutsu-kaisen`).
*   **Titre alternatif de recherche** : Utilise un nom simplifié ou différent si le titre original ne donne aucun résultat.

### Filtres de bibliothèque
Le menu déroulant permet de filtrer l'affichage selon le statut des séries :
*   **À traiter** : Séries en attente de synchronisation.
*   **Complétées** : Séries déjà enrichies avec succès.
*   **Introuvables** : Séries ayant échoué lors de la recherche sur les providers.
*   **Amnistie Erreurs** : Bouton permettant de remettre toutes les séries "Introuvables" au statut "À traiter".

## ⚠️ Problèmes connus et points de vigilance

### Sécurité des données
*   **Fichiers confidentiels** : Le fichier `config.json` contient tes clés API en clair. Ne jamais le partager ou le pousser sur un dépôt public.
*   **Versionnage** : Ton `.gitignore` doit exclure `config.json` et `cache.db`.

### Connectivité et Scraping
*   **Logs en temps réel** : La section "Live Logs" permet de suivre minutieusement le déroulement des requêtes, le statut des paquets du mode Batch et les blocages éventuels.
*   **Bypass Cloudflare** : Le scraper Nautiljon utilise une émulation de session sécurisée (`curl_cffi`). En cas de changement de structure de leur côté, surveille les logs du terminal.

### Limitations
*   **Quota DeepL** : Surveille tes crédits de traduction lors de l'utilisation intensive du mode batch.
*   **Vitesse** : Le script impose un délai de sécurité de 1.5s entre chaque appel d'API pour éviter les bans IP et respecter les quotas des providers.

## 🛠️ Installation rapide
1. Utilise le `docker-compose.yml` fourni.
2. Configure tes clés API dans le fichier `config.json`.
3. Lance le conteneur : `docker-compose up -d --build`.

## Tech Stack
- **Backend** : Python 3.11, Flask, Flask-SocketIO, Curl-Cffi, BeautifulSoup4.
- **Base de données** : SQLite.
- **Déploiement** : Docker (Alpine).
