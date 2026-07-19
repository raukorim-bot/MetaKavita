# 🚀 MetaKavita - Roadmap & To-Do List

**Concept :** Outil de scraping et d'enrichissement de métadonnées pour Kavita (alternative à Komf), pensé pour le *vibecoding* et l'auto-hébergement.
**Philosophie :** Léger, pragmatique, hautement sécurisé et orienté manga/BD.

---

## 🛠️ Partie A : Fondations & Sécurité (V1.3+)
- [x] **A1 à A6 :** Sécurisation API, Live Logs, 100% AJAX, Traductions globales, UI Responsive.
- [x] **A7 à A9 :** Cache auto-nettoyant, UI explicite en cas d'erreur de clé, Déploiement Zero-Setup.
- [x] **A10. Architecture de Prod (WSGI) :** Migration vers Gunicorn + Eventlet.
- [x] **A11. Sécurité Globale :** Protection SSRF sur le Proxy, authentification avec prévention d'attaques temporelles, Session HTTPOnly, masquage des clés API dans le DOM, Webhook protégé par Token asymétrique.

---

## 🏗️ Partie B : Nouvelles fonctionnalités (V1.4)
- [x] **B7 à B9 :** Statut "Ignoré", Auto-Sync, Routage Intelligent (Fallback) et Complétion (Fusion de métadonnées).
- [x] **B11. Authentification globale :** Verrouillage de l'UI par variable Docker `ADMIN_PASSWORD`.
- [x] **B14 à B15 :** Gestions avancée des couvertures (Covers) et API MangaBaka V2.
- [x] **B16. Nettoyage avancé des titres (Regex) :** Le module centralisé `clean_title()` filtre désormais parfaitement les préfixes (`01 -`), les éditions (`Omnibus`, `Perfect`) et les artefacts de dossiers.
- [x] **B17. Barre de recherche AJAX :** Filtrage instantané des centaines de séries dans l'UI sans rechargement.
- [x] **B18. Métadonnées Étendues Kavita :** Prise en charge de l'Éditeur, de la classification d'Âge, des Coloristes/Traducteurs, et du format (Manga/Webtoon) optionnel.
- [x] **B19. Liens et IDs Externes :** Injection des AniListId, MalId et MangaBakaId directement dans la série, et auto-génération des WebLinks cliquables.
- [ ] **B10. Support des BD (Provider ISBN) :** Ajouter la recherche via ISBN (Google Books API, etc.) pour cibler parfaitement les comics/BD européennes.
- [ ] **B12. Dashboard de Statistiques ludique :** Temps sauvé, Braquage DeepL estimé en euros.

---

## 🔮 Partie C : Prochaines étapes
- [ ] **C1. Nouveau Scraper : MyAnimeList (MAL)** : Créer un provider dédié pour concurrencer AniList.
- [ ] **C2. Nouveau Scraper : ComicVine** : Essentiel pour les amateurs de comics US.
- [ ] **C3. Refonte de la Configuration :** Déplacer la configuration grandissante vers une fenêtre modale ou une page `/settings`.