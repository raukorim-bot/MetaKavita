# Inventaire

[English](../en/inventory.md) · [Français](README.md)

← [Documentation](README.md)

Allumé par défaut (`LIBRARY_INVENTORY_ENABLED`). Lecture seule : n'écrit aucune métadonnée de volume et ne fusionne jamais de séries. Décoche **Inventaire de la bibliothèque** dans la sidebar pour cacher le panneau ; le scraping et les métadonnées de série ne bougent pas.

![Options de scraping — Inventaire](../../assets/docs-inventory-sidebar.png)

Un panneau **Inventaire**, au-dessus de la liste, dit quelles séries sont incomplètes. **Analyser la bibliothèque** / **Analyse rapide** travaillent en arrière-plan : ils comptent les tomes (ou chapitres) dans Kavita, demandent à la cascade combien il devrait y en avoir, et regroupent les séries qui se ressemblent. **Détail des manquants** et **Détail des doublons** (ou le chip **Doublons**) ouvrent les listes.

![Panneau Inventaire — barre de santé, Manquants / Doublons / Sans id](../../assets/docs-toolbar-inventory.png)

Tu obtiens :

* une barre de santé
* des chips **Manquants / Doublons / Sans id**
* une cartouche `N/M` colorée sur chaque ligne
* un rapport par série (numéros manquants pliés en intervalles)
* des exports CSV / TXT
* des groupes de doublons à ignorer

**Détail des manquants** (ou le chip **Manquants**) liste les séries sous l'attendu catalogue (1…N) : **Série**, **État** (`N/M`, Δ manquants), **Publication**, **Manquants** (intervalles, ou `ch.` pour les chapitres), et un bouton **Exclure** rapide pour sortir immédiatement une série des calculs d'inventaire sans passer par Options. **Inclure les séries sans attendu (N/?)** ajoute les inconnues. **Rapport volumes** ouvre le [rapport par série](volumes.md). CSV / TXT en bas.

![Détail des manquants](../../assets/docs-missing-details.png)

**Détail des doublons** ouvre cette modale. Le **Seuil** (Souple 0.85 / Médium 0.92 / Strict 0.97) demande une nouvelle Analyse. Chaque groupe montre le score, les raisons de détection, et les décomptes réels de tomes et de chapitres pour chaque copie (`X tomes · Y ch.`), soulignés par un badge « 🌟 Recommandé (plus complet) » sur l'édition la plus fournie.
* Actions sur chaque copie : **Ouvrir Kavita**, **Pas un doublon**, **Ignorer**, et **Marquer comme traité** (archive les groupes résolus sans fausser la statistique des faux positifs ; les groupes ignorés/traités sont partagés entre bibliothèques individuelles et la vue « Tout »).
* Coche **Jeter** sur les copies en trop : une série au moins reste décochée par groupe, et une alerte de confirmation explicite vous avertit si vous cochez « Jeter » sur une copie plus complète que la copie conservée.
* **Chemin inconnu** : relance Analyser.

Le **Préfixe des chemins** (`INVENTORY_FOLDER_PATH_PREFIX`) est collé devant chaque chemin Kavita dans le script — ex. `/mnt/media` + `/comics/…` → `/mnt/media/comics/…` ou `C:/Media` sous Windows. La **Corbeille des doublons** (`INVENTORY_FOLDER_TRASH`) accepte aussi bien les chemins POSIX que Windows (`C:/...`, `D:\...`) et doit rester hors des bibliothèques Kavita. L'enregistrement de ces chemins met uniquement à jour les préférences de dossiers sans impacter les réglages globaux du serveur.
* **Format du script** : choisissez entre POSIX Bash (`.sh`) et Windows PowerShell (`.ps1`). Puis **Copier le script** ou **Télécharger (.sh / .ps1)** en mode `Corbeille (mv)` ou `Supprimer (rm -rf)`, plus exports CSV / TXT.
* **⚡ Déclencher le scan Kavita** : une fois le script exécuté sur votre serveur ou NAS, cliquez sur ce bouton directement dans la modale pour demander à Kavita d'actualiser la bibliothèque sans avoir à basculer sur l'interface Kavita.
* **Purge sécurisée des séries vides** : si le déplacement des fichiers a laissé une coquille de série vide dans Kavita (0 volume), MetaKavita la détecte et propose une purge en 1 clic (`/purge-empty`) directement dans la modale de rapport de volumes, en vérifiant formellement qu'aucun tome ni chapitre ne subsiste avant d'effacer la coquille.

![Modale Doublons](../../assets/docs-duplicates-modal.png)

MetaKavita n'exécute jamais ce script de déplacement de fichiers lui-même : les opérations sur disque restent entièrement sous votre contrôle.

L'attendu peut être forcé à la main (**Attendu forcé** dans le [rapport de tomes](volumes.md)), réutilisant instantanément le catalogue en cache sans scrape externe superflu. Une série qu'aucun catalogue ne connaîtra jamais peut être exclue des compteurs (**Exclure de l'inventaire**) tout en restant scrapée.

Désactive-le depuis la sidebar (catégorie **Inventaire**) : panneau, cartouches et API disparaissent. Masquer l'Inventaire dans le [mode léger](dashboard.md#mode-léger) l'éteint aussi.

Voir [Tomes](volumes.md) pour écrire les métadonnées d'album.
