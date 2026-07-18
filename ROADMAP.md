# 🚀 MetaKavita - Roadmap & To-Do List

**Concept :** Outil de scraping et d'enrichissement de métadonnées pour Kavita (alternative à Komf), pensé pour le *vibecoding* et l'auto-hébergement.
**Philosophie :** Léger, pragmatique (polling au lieu de websockets), et orienté manga/BD.

---

## 🛠️ Partie A : Corrections et "Quality of Life" (UI/UX)
*Le but : Rendre l'existant robuste, fluide et visuellement propre avant d'ajouter de la complexité.*

- [x] **A1 à A6 :** Sécurisation API, Live Logs, 100% AJAX, Traductions globales.

---

## 🏗️ Partie B : Nouvelles fonctionnalités (V2)
*Le but : Rendre l'outil autonome ("mains libres"), compatible BD, et ajouter une couche de fun.*

- [x] **B7. Statut "À ignorer" :** Création d'un 4ème statut pour empêcher l'outil de boucler indéfiniment sur une série introuvable, avec case pour les masquer visuellement.
- [x] **B8. Le Polling (Automatisation) :** Thread en tâche de fond qui interroge Kavita toutes les X minutes pour récupérer et traiter les nouveaux ajouts de façon totalement transparente (avec respect strict des Rate Limits : 1s/1.5s/2.5s).
- [x] **B14. Images de couverture (Covers) :** Téléchargement et application des couvertures (Option auto globale ou Pop-up Modal manuel avec Proxy Anti-Hotlink).
- [x] **B15. Provider "MangaBaka" :** Implémentation de l'API V2 de MangaBaka (Rapide, données enrichies : Éditeurs, Classification d'âge, Couvertures HD).
- [ ] **B9. Hiérarchie des sites (Fallback) :** Implémenter une cascade de requêtes. Exemple : Chercher d'abord sur MangaBaka -> si échec, Nautiljon -> si échec, AniList.
- [ ] **B10. Support des BD (Provider ISBN) :** Ajouter la recherche via ISBN (via Google Books API, OpenLibrary ou Babelio) pour cibler parfaitement les comics et BD européennes.
- [ ] **B11. Authentification globale (Désactivable) :**
  - Mettre en place un mot de passe pour l'accès web (variables Docker `AUTH_ENABLED`, `ADMIN_PASSWORD`).
- [ ] **B12. Dashboard de Statistiques :**
  - Stats sérieuses (succès/échecs par provider).
  - Stats ludiques (Temps sauvé, Braquage DeepL, etc.).
- [ ] **B13. Barre de progression globale :** Ajouter une barre de chargement au-dessus des Live Logs pour suivre visuellement l'avancée du batch.