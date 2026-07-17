# MetaKavita
<img width="1920" height="1080" alt="{6E249195-1237-4C12-A779-14CDBF1C981B}" src="https://github.com/user-attachments/assets/1db72309-5136-41b0-9e08-5a79f7760b8a" />

Outil d'automatisation conçu pour enrichir les métadonnées de ta bibliothèque [Kavita](https://kavitareader.com/). Il récupère automatiquement les informations (résumés, années, genres, tags, personnel) depuis [AniList](https://anilist.co/) et traduit les résumés via [DeepL](https://www.deepl.com/).

## ⚙️ Interface et Configuration

### Configuration initiale
*   **URL Kavita** : L'adresse de ton instance Kavita (ex: `http://host.docker.internal:5001`).
*   **Clé API Kavita** : Clé générée dans les paramètres de ton instance Kavita pour permettre au script d'interagir avec ta bibliothèque.
*   **Clé API DeepL** : Clé d'authentification pour le service de traduction.
*   **Langue de traduction** : Sélectionne la langue cible pour les résumés (Français, Anglais (US), Espagnol, Allemand).

> **Note** : N'oublie pas de cliquer sur "Sauvegarder les clés API" après chaque modification.

## 📚 Gestion des séries

### Synchronisation
*   **Liste des séries** : Affiche toutes les séries de la bibliothèque sélectionnée.
*   **Mettre à jour** : Déclenche manuellement la recherche et la mise à jour pour une série spécifique.
*   **Lancer le batch sur la sélection** : Applique le processus d'enrichissement à toutes les séries sélectionnées dans la liste.
*   **Forcer la mise à jour** : Si coché, écrase les métadonnées existantes sur Kavita, même si elles sont déjà présentes.

### Options avancées (par série)
En cliquant sur le bouton **"Options"** à côté d'une série, tu peux définir des paramètres de recherche spécifiques pour corriger les erreurs de correspondance :
*   **ID AniList** : Force l'utilisation d'un ID AniList précis (ex: `119161`).
*   **Titre alternatif de recherche** : Utilise un nom simplifié ou différent si le titre original ne donne aucun résultat.

### Filtres de bibliothèque
Le menu déroulant permet de filtrer l'affichage selon le statut des séries :
*   **À traiter** : Séries en attente de synchronisation.
*   **Complétées** : Séries déjà enrichies avec succès.
*   **Introuvables** : Séries ayant échoué lors de la recherche sur AniList.
*   **Amnistie Erreurs** : Bouton permettant de remettre toutes les séries "Introuvables" au statut "À traiter".

## ⚠️ Problèmes connus et points de vigilance

### Sécurité des données
*   **Fichiers confidentiels** : Le fichier `config.json` contient tes clés API en clair. Ne jamais le partager ou le pousser sur un dépôt public.
*   **Versionnage** : Ton `.gitignore` doit exclure `config.json` et `cache.db`.

### Connectivité
*   **Logs en temps réel** : La section "Live Logs" en bas de l'interface permet de suivre le déroulement des requêtes HTTP (ex: `200` OK) et le fonctionnement des WebSockets.
*   **Réseau** : Si le serveur est inaccessible, vérifie la configuration de ton hôte Docker (`host.docker.internal`).

### Limitations
*   **Quota DeepL** : Surveille tes crédits de traduction lors de l'utilisation intensive du mode batch.
*   **Vitesse** : Le script impose un délai de 1.5s entre chaque série traitée pour respecter les limites de l'API.

## 🛠️ Installation rapide
1. Utilise le `docker-compose.yml` fourni.
2. Configure tes clés API dans le fichier `config.json`.
3. Lance le conteneur : `docker-compose up -d`.

## Tech Stack
- **Backend** : Python 3.11, Flask, Flask-SocketIO.
- **Base de données** : SQLite.
- **Déploiement** : Docker (Alpine).
