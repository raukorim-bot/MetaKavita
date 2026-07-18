# 🚀 MetaKavita - Roadmap & To-Do List

**Concept :** Outil de scraping et d'enrichissement de métadonnées pour Kavita (alternative à Komf), pensé pour le *vibecoding* et l'auto-hébergement.
**Philosophie :** Léger, pragmatique (polling au lieu de websockets), et orienté manga/BD.

---

## 🛠️ Partie A : Corrections et "Quality of Life" (UI/UX)
*Le but : Rendre l'existant robuste, fluide et visuellement propre avant d'ajouter de la complexité.*

- [x] **A1. Sécuriser l'affichage des clés API :** Passer les champs de configuration des clés (DeepL, etc.) en type `password` avec une petite icône "œil" pour masquer/afficher.
- [x] **A2. Fixer l'UI du bandeau :** Corriger le CSS du bandeau principal qui est actuellement coupé/mal affiché.
- [x] **A3. Debug DeepL :** Ajouter des logs d'erreur explicites côté serveur et côté interface si l'API DeepL rejette la requête (quota dépassé, mauvaise clé).
- [x] **A4. Interface 100% dynamique (Live/AJAX) :** Passer tous les boutons et formulaires en Javascript (`fetch`) pour éviter les rechargements de page intempestifs lors d'un changement de paramètre.
- [x] **A5. Compteur de Batch :** Réintégrer le nombre d'éléments restants à traiter dans les live logs lors du lancement d'un traitement par lot.
- [x] **A6. Traduction globale :** Faire une passe sur le dictionnaire de traduction pour corriger les objets ou textes qui sont restés dans la mauvaise langue.

---

## 🏗️ Partie B : Nouvelles fonctionnalités (V2)
*Le but : Rendre l'outil autonome ("mains libres"), compatible BD, et ajouter une couche de fun.*

- [ ] **B7. Statut "À ignorer" :** Créer un 4ème statut (en plus de "à traiter", "confirmé", "en erreur") pour empêcher l'outil de boucler indéfiniment sur une série introuvable.
- [ ] **B8. Le Polling (Automatisation) :** Développer un thread en tâche de fond qui interroge l'API Kavita (ex: toutes les 30 min) pour récupérer et traiter les nouveaux ajouts de façon totalement transparente.
- [ ] **B9. Hiérarchie des sites (Fallback) :** Implémenter une cascade de requêtes. Exemple : Chercher d'abord sur Nautiljon -> si échec, chercher sur AniList + traduction DeepL -> si échec, passer en "Erreur" ou "À ignorer".
- [ ] **B10. Support des BD (Provider ISBN) :** Ajouter la recherche via ISBN (via Google Books API, OpenLibrary ou Babelio) pour cibler parfaitement les comics et BD européennes.
- [ ] **B11. Authentification globale (Désactivable) :**
  - Mettre en place un mot de passe pour l'accès web.
  - Géré via les variables d'environnement Docker (`AUTH_ENABLED`, `ADMIN_PASSWORD`).
  - *Troll feature :* Si l'authentification est active mais sans mot de passe défini, générer un mot de passe aléatoire dans la console Docker pour forcer la lecture des logs.
- [ ] **B12. Dashboard de Statistiques :**
  - *Stats sérieuses :* Nombre de tentatives, succès, échecs, pourcentages filtrés par provider (Nautiljon, AniList...).
  - *Stats ludiques (pour la rétention) :*
    - "Braquage DeepL" (Caractères traduits sur le dos de l'API gratuite).
    - "Temps de vie sauvé" (Temps estimé gagné par rapport à un scraping manuel).
    - "Taux d'impatience" (Nombre de clics inutiles sur les boutons).
    - "Index Hipster" (Ratio mainstream vs oeuvres obscures).
    - "Mur de la honte" (Les séries les plus introuvables d'internet).
    - "Connexions troll" (Échecs de connexion sur la page d'accueil).
- [ ] **B13. Barre de progression globale :** Ajouter une barre de chargement au-dessus ou à côté des Live Logs pour suivre visuellement l'avancée du traitement de masse, et rendre la fenêtre de logs redimensionnable.