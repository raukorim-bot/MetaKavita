## [1.3.0] - 2026-07-19

### ✨ Nouvelles Fonctionnalités
* **Routage Intelligent (Fallback) :** Il est désormais possible de définir une hiérarchie de recherche avec 3 "Slots" (Source de base, Secours 1, Secours 2). Si la source principale échoue, l'outil interroge silencieusement la suivante.
* **Complétion Intelligente (Fusion de données) :** Une nouvelle option "🧩" permet de combiner les forces des API. Si votre source principale trouve un manga mais qu'il manque le résumé ou les genres, MetaKavita ira chercher *uniquement* les données manquantes sur les sources secondaires pour combler les trous sans jamais écraser la base !
* **Cache Auto-Nettoyant (Anti-Fantômes) :** Si vous supprimez une série dans Kavita, la base de données interne de MetaKavita s'en rend compte au prochain scan et purge automatiquement le cache. Vos statistiques (`Complété`, `Introuvable`, etc.) restent ainsi parfaitement exactes.

### 🎨 Améliorations UI/UX
* **Interface d'Erreur Explicite :** Fini l'écran vide et muet si votre clé API Kavita est fausse ou expirée. Un bel écran avec une icône de prise débranchée (🔌) s'affiche désormais au centre de l'écran avec les instructions pour réparer la connexion.
* **Menus déroulants fluides :** La sélection de l'ordre des Providers empêche intelligemment les doublons. Si vous assignez une source déjà utilisée, l'interface résout le conflit et décale les choix automatiquement et sans friction (pas de boutons grisés bloquants).
* **Sidebar élargie :** La barre latérale passe de 320px à 380px pour offrir plus d'espace visuel au nouveau tableau de bord de configuration.

### 🛠️ Sous le capot (Dev & Infra)
* **Architecture "Plug & Play" (PROVIDERS_MAP) :** Refonte totale du routeur de scrapers. L'ajout d'une nouvelle API se fait maintenant en une seule ligne de code dans un dictionnaire. L'interface Web se met à jour dynamiquement en lisant ce dictionnaire.
* **Rate-Limiting Dynamique :** Lors d'une "Fusion", la tâche de fond calcule le délai de pause (`sleep`) en prenant en compte le quota le plus strict parmi toutes les API appelées pour éviter le bannissement d'IP.
* **Vibecoding Guide :** Ajout d'une section dans le `DEVELOPER.md` fournissant un "Prompt IA" pré-conçu permettant de générer de nouveaux scrapers (Providers) avec ChatGPT ou Claude, sans même savoir coder.
* **Variables Docker :** Toutes les variables d'environnement supportées ont été documentées en détail dans le README et le docker-compose d'exemple.