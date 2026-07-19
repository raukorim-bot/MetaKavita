# 🚀 MetaKavita - Roadmap & To-Do List

**Concept :** Outil de scraping et d'enrichissement de métadonnées pour Kavita (alternative à Komf), pensé pour le *vibecoding* et l'auto-hébergement.
**Philosophie :** Léger, pragmatique (polling au lieu de websockets), et orienté manga/BD.

---

## 🛠️ Partie A : Corrections et "Quality of Life" (UI/UX & Infra)
*Le but : Rendre l'existant robuste, fluide, visuellement propre et facile à installer.*

- [x] **A1 à A6 :** Sécurisation API, Live Logs, 100% AJAX, Traductions globales, UI Responsive.
- [x] **A7. Nettoyage des séries fantômes :** Le cache SQLite se purge automatiquement des séries supprimées dans Kavita pour garder des statistiques justes.
- [x] **A8. UI d'Erreur API :** Affichage d'un écran clair dans l'UI principale en cas d'erreur de connexion à Kavita (clés erronées ou serveur injoignable).
- [x] **A9. Déploiement "Zero-Setup" :** Suppression du fichier `setup.sh`. Refonte de l'arborescence pour que Python génère automatiquement le dossier `data/` au premier lancement du conteneur Docker.

---

## 🏗️ Partie B : Nouvelles fonctionnalités (V2)
*Le but : Rendre l'outil autonome ("mains libres"), compatible BD, et ajouter une couche de fun.*

- [x] **B7. Statut "À ignorer" :** Création d'un 4ème statut pour empêcher l'outil de boucler indéfiniment.
- [x] **B8. Le Polling (Automatisation) :** Thread en tâche de fond qui interroge Kavita avec respect strict des Rate Limits.
- [x] **B9. Hiérarchie des sites (Fallback) & Fusion :** Implémentation d'une cascade de requêtes (Source 1 > 2 > 3) avec une option de "Complétion intelligente" (Smart Fusion) pour boucher les trous de métadonnées.
- [x] **B14. Images de couverture (Covers) :** Téléchargement et application auto ou via modal manuel avec proxy anti-hotlink.
- [x] **B15. Provider "MangaBaka" :** Implémentation de l'API V2 de MangaBaka (Données enrichies, ultra-rapide).
- [ ] **B10. Support des BD (Provider ISBN) :** Ajouter la recherche via ISBN (Google Books API, etc.) pour cibler parfaitement les comics/BD européennes.
- [ ] **B11. Authentification globale (Désactivable) :** Mettre en place un mot de passe pour l'accès web (variables Docker `AUTH_ENABLED`, `ADMIN_PASSWORD`).
- [ ] **B12. Dashboard de Statistiques :** Stats sérieuses et ludiques (Temps sauvé, Braquage DeepL).
- [ ] **B13. Barre de progression globale :** Ajouter une barre de chargement au-dessus des Live Logs pour suivre visuellement l'avancée du batch.
- [ ] **B16. Nettoyage avancé des titres :** Améliorer l'algorithme de nettoyage (Regex/Lexical) pour maximiser le taux de "match" avec les API (ex: nettoyage des `01`, `Tome 2`, `[Edition Deluxe]`).
- [ ] **B17. Refonte de la Configuration (UX) :** Déplacer la configuration grandissante vers une fenêtre modale dédiée ou une page `/settings` pour épurer l'interface principale.
- [ ] **B18. Interface Réactive (WebSockets DOM) :** Mettre à jour visuellement les badges (En Attente -> Complété/Erreur) en temps réel pendant qu'un batch tourne en fond, sans forcer l'utilisateur à rafraîchir la page.