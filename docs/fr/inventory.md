# Inventaire

[English](../en/inventory.md) · [Français](README.md)

← [Documentation](README.md)

Allumé par défaut (`LIBRARY_INVENTORY_ENABLED`). Lecture seule : n'écrit aucune métadonnée de volume et ne fusionne jamais de séries. Décoche **Inventaire de la bibliothèque** dans la sidebar pour cacher le panneau ; le scraping et les métadonnées de série ne bougent pas.

![Options de scraping — Inventaire](../../assets/docs-inventory-sidebar.png)

Un panneau **Inventaire**, au-dessus de la liste, dit quelles séries sont incomplètes. **Analyser la bibliothèque** / **Analyse rapide** travaillent en arrière-plan : ils comptent les tomes (ou chapitres) dans Kavita, demandent à la cascade combien il devrait y en avoir, et regroupent les séries qui se ressemblent. **Détail des manquants** et **Détail des doublons** (ou le chip **Doublons**) ouvrent les listes.

![Panneau Inventaire — barre de santé, Manquants / Doublons / Sans id](../../assets/docs-inventory-health.png)

Tu obtiens :

* une barre de santé interactive (cliquer sur un segment ou une clé de légende filtre les séries sur le tableau de bord)
* des chips interactifs **Manquants / Doublons / Sans id / Exclues**
* une cartouche `N/M` colorée sur chaque ligne
* un rapport par série (numéros manquants pliés en intervalles)
* des exports CSV / TXT
* des groupes de doublons à ignorer

**Détail des manquants** (ou le chip **Manquants**) liste les séries sous l'attendu catalogue (1…N). La modale comprend :
* **Barre de filtres** (au-dessus du tableau) :
  * **Recherche rapide** : filtre instantanément les séries manquantes par titre au fil de la frappe.
  * **Filtres de statut** : basculez entre **Tous**, **Terminés** et **En cours** pour prioriser les séries complètes à compléter.
  * **Compteur dynamique** : affiche le nombre de séries visibles correspondant à vos critères.
* **En-têtes de colonnes triables** : cliquez sur **Série**, **État**, **Publication** ou **Manquants** pour trier par ordre croissant ou décroissant (`▲`/`▼`).
* **Lien direct Atelier des tomes** : bouton sarcelle en 1 clic sur chaque ligne ouvrant directement la série dans l'[Atelier des tomes](volumes.md) pour inspecter et enrichir les albums manquants.
* **Exclusion rapide réversible** : cliquez sur **Exclure** pour sortir immédiatement une série des calculs d'inventaire (avec confirmation), ou sur **Réinclure** pour la réintégrer, mettant à jour en temps réel les cartouches, cartes et compteurs d'hygiène.
* **Inclure les séries sans attendu (N/?)** ajoute les inconnues. **Rapport volumes** ouvre le [rapport par série](volumes.md). CSV / TXT en bas.

![Détail des manquants](../../assets/docs-missing-details.png)

**Détail des doublons** ouvre cette modale. Le **Seuil** (Souple 0.85 / Médium 0.92 / Strict 0.97) recalcule instantanément les groupes en mémoire sans nécessiter de nouvelle analyse ni de rescraping.
* **Barre d'outils par lot** (au-dessus de la liste) :
  * **Recherche rapide** : filtre instantanément les doublons par titre de série au fur et à mesure de votre frappe.
  * **🎯 Sélectionner tous les doublons** : coche en 1 clic toutes les copies secondaires/moins complètes dans l'ensemble des groupes, tout en laissant systématiquement décochée la copie recommandée la plus complète.
  * **Tout désélectionner** : décoche toutes les cases d'un coup.
  * **Compteur dynamique** : affiche en direct le nombre de copies marquées.
* Chaque groupe montre le score, les raisons de détection, et les décomptes réels de tomes et de chapitres pour chaque copie (`X tomes · Y ch.`), soulignés par un badge « 🌟 Recommandé (plus complet) » lorsqu'une différence réelle existe. La comparaison se fait en **tomes équivalents** : une copie que Kavita ne connaît qu'en chapitres est mesurée à sa juste valeur plutôt que traitée comme vide. Le nombre de chapitres qu'un tome représente suit la convention du **type de bibliothèque** : environ dix pour un manga, six pour un comic (un recueil rassemble à peu près six numéros), vingt-cinq pour un roman ou un light novel. Une bibliothèque dont Kavita n'annonce pas le type, ou un groupe qui en mêlerait deux, retombe sur la convention manga. Une série rangée en 364 chapitres l'emporte donc sur une copie d'un tome unique, et l'alerte de confirmation comme la sélection 🎯 suivent la même mesure.
* Actions sur chaque copie : **Ouvrir Kavita**, **Pas un doublon**, **Ignorer**, et **Marquer comme traité** (archive les groupes résolus sans fausser la statistique des faux positifs ; les groupes ignorés/traités sont partagés entre bibliothèques individuelles et la vue « Tout »).
* **Vue des doublons archivés** (bouton `📦` en en-tête) : consultez l'ensemble des paires écartées, ignorées ou traitées, et cliquez sur **Restaurer** (`↩️`) pour réintégrer n'importe quelle paire dans la file des doublons en 1 clic.
* Coche **Jeter** sur les copies en trop : une série au moins reste décochée par groupe, et une alerte de confirmation explicite vous avertit si vous cochez « Jeter » sur une copie plus complète que la copie conservée.
* **Chemin inconnu** : relance Analyser.

Le **Préfixe des chemins** (`INVENTORY_FOLDER_PATH_PREFIX`) est collé devant chaque chemin Kavita dans le script — ex. `/mnt/media` + `/comics/…` → `/mnt/media/comics/…` ou `C:/Media` sous Windows. La **Corbeille des doublons** (`INVENTORY_FOLDER_TRASH`) accepte aussi bien les chemins POSIX que Windows (`C:/...`, `D:\...`) et doit rester hors des bibliothèques Kavita. L'enregistrement de ces chemins met uniquement à jour les préférences de dossiers sans impacter les réglages globaux du serveur.
* **Format du script** : choisissez entre POSIX Bash (`.sh`) et Windows PowerShell (`.ps1`). Les scripts sont durcis pour un copier-coller sans risque dans le terminal (`set -u` sous Bash, `$ErrorActionPreference = "Continue"` sous PowerShell).
* **Aperçu du script en direct** : un bloc dépliable (`📜 Aperçu du script en direct`) affiche en temps réel le code prêt à copier ou lancer au fur et à mesure que vous ajustez les sélections.
* **Scan Kavita à la fin** : cochez cette case pour ajouter automatiquement les commandes de rafraîchissement d'API Kavita (curl ou `Invoke-RestMethod`) à la fin du script, réunissant nettoyage des fichiers sur disque et rescan Kavita en une seule exécution dans votre terminal. **Votre clé API n'est jamais écrite dans le script** : il la lit dans l'environnement de votre terminal. Exportez-la avant de lancer ce bloc — `export KAVITA_API_KEY="votre-clé"` sous Bash, `$env:KAVITA_API_KEY = "votre-clé"` sous PowerShell — sans quoi le script sautera poliment le rescan en vous le disant. Ainsi la clé ne transite ni par le presse-papier, ni par le fichier téléchargé, ni par l'historique de vos commandes.
* **Mise à la corbeille sans écrasement** : quand deux doublons portent un dossier du même nom, le script ne remplace jamais celui qui attend déjà dans la corbeille. Il annonce le saut (`SKIP  … already present in the trash folder`) et poursuit — renommez ou videz la corbeille, puis relancez. Bash et PowerShell se comportent à l'identique.
* **Copier / Télécharger** : copiez directement dans le presse-papier avec confirmation toast ou téléchargez le fichier script.
* **⚡ Déclencher le scan Kavita** : vous pouvez également déclencher le scan manuellement en 1 clic via ce bouton dédié.
* **Purge sécurisée des séries vides** : si le déplacement des fichiers a laissé une coquille de série vide dans Kavita (0 volume), MetaKavita la détecte et propose une purge en 1 clic (`/purge-empty`) directement dans la modale de rapport de volumes, en vérifiant formellement qu'aucun tome ni chapitre ne subsiste avant d'effacer la coquille.

![Modale Doublons](../../assets/docs-duplicates-modal.png)

MetaKavita n'exécute jamais ce script de déplacement de fichiers lui-même : les opérations sur disque restent entièrement sous votre contrôle.

L'attendu peut être forcé à la main (**Attendu forcé** dans le [rapport de tomes](volumes.md)), réutilisant instantanément le catalogue en cache sans scrape externe superflu. Une série qu'aucun catalogue ne connaîtra jamais peut être exclue des compteurs (**Exclure de l'inventaire**) tout en restant scrapée.

Désactive-le depuis la sidebar (catégorie **Inventaire**) : panneau, cartouches et API disparaissent. Masquer l'Inventaire dans le [mode léger](dashboard.md#mode-léger) l'éteint aussi.

Voir [Tomes](volumes.md) pour écrire les métadonnées d'album.
