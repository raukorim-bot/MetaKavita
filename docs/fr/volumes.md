# Métadonnées par tome et par album

[English](../en/volumes.md) · [Français](README.md)

← [Documentation](README.md)

Éteint par défaut (`VOLUME_ENRICHMENT_ENABLED`). Tant qu'il l'est, les boutons disparaissent et l'API répond 403. On l'allume depuis le bloc sidebar **Tomes et albums** (badge expérimental).

![Options de scraping — Tomes et albums](../../assets/docs-volumes-sidebar.png)

Là où l'[Inventaire](inventory.md) dit ce qui manque, ceci remplit ce qui est là.

Trois surfaces, qui ne se marchent pas dessus :

* **📑 Rapport de tomes** (sur la ligne de série) — inventaire seul : possédés vs attendu, ISBN manquants, attendu forcé, exclusion. Pied : **Rafraîchir**, lien **Atelier**, CSV / TXT.
* **Accès Atelier sur le Dashboard** — **Atelier** trône en évidence dans la barre supérieure sticky (`header.topbar`) ainsi que dans l'en-tête de la barre d'outils, avec son icône SVG dédiée et son thème sarcelle, pour ouvrir `/volumes` à tout moment (le rail ou la dernière série consultée charge la fiche sans sélection préalable requise). Passe automatique disponible sur les séries cochées, annulable. Honore les liens magiques déjà posés dans l'atelier. Pas de Champ Magique dans la barre.
* **Atelier** `GET /volumes` ou `GET /series/<id>/volumes` — page autonome (comme `/stats`). À l'ouverture : Kavita + Meta, **aucun scrape**. Carte série (sarcelle) ≠ cartes tomes (orange). Les champs **vides** sont ambre, mais **gardent le même ordre**. Les champs courts (année, statut, âge, staff) se mettent à trois par ligne. Le staff en trop se range sous **Plus de champs (x complétés / y)** (le volet est mémorisé, avec compteur dynamique en direct). Le **Champ Magique** est une ligne libellée, visible tout de suite (la touche Entrée lance directement la recherche). Le titre de série ouvre la fiche Kavita. La barre des tomes reste à l'écran (compte de sélection, envoi). `/` pose le focus sur la recherche du rail ; ← → se grisent en bout de liste. La barre de navigation supérieure intègre un bouton permanent **M'offrir un café** (☕) avec toast immédiat et cooldown supporter. L'overlay nagware supporter peut également apparaître rarement après des écritures réussies dans Kavita (variante `workshop_craft`, sous conditions strictes : lune de miel de 7 jours, seuil d'activité minimum de 10 éléments traités, maximum 1 à 2 fois par jour, pause honneur de 30 jours). Le journal live est à droite. Les jaquettes ont un relief de livre 2:3 et un bouton **Choisir** ; l'URL choisie part à l'envoi, pas via `/update-cover`. Édition sur place avec persistance automatique en brouillon (survit au rechargement F5). Manual Review / Super Review (fiche ou tome) permettent d'ajuster les métadonnées (candidat simple avec pré-sélection et miniatures de jaquettes, fusion de sources ou complétion manuelle par champ, prise en compte de l'ISBN saisi) en passant par les étapes de revue (choix, couverture, prévisualisation/édition) avant de stager la fiche à la confirmation ; elles n'écrivent **pas** Kavita. **Envoyer** un tome / la fiche / la sélection / tous les tomes est ce qui écrit. L'envoi **écrase** les champs déjà remplis, verrous compris (une valeur vide, nom localisé compris, n'est jamais écrite). Reset = Meta + relecture Kavita, **pas** de rewind des écritures déjà dans Kavita. Reset d'un tome rouvre aussi cette unité pour la passe automatique. Le rail reprend la recherche, la bibliothèque, le statut et « masquer les ignorés » du tableau de bord. Un clic charge la série à côté, sans recharger la page. Les jaquettes déjà dans Kavita sont gardées sur disque.

![Rapport de tomes](../../assets/docs-volume-report.png)

Écrits : **titre d'album, résumé, date de parution, ISBN et couverture**, uniquement dans les champs vides sauf Force. Un champ rempli à la main, ou verrouillé dans Kavita, n'est pas touché.

Une passe de bibliothèque prend place à côté d'Analyser, avec la même barre et le même Annuler.

Sources : ComicVine (cent numéros par requête, `fetch_volume` pour une issue), Bédéthèque et Planète BD (crawl ciblé : seuls les tomes possédés sont ouverts, `should_cancel` dans la boucle), Manga-News pour les tomes VF (titres alternatifs Kavita en premier), Metron (liste d'issues paginée), et, pour les tomes qui portent déjà un ISBN, Google Books puis Open Library puis Hardcover puis openBD s'il est installé. Manga-Sanctuary, dès qu'il déclare `fetch_volume_index`, se place juste derrière Manga-News. Les crédits d'auteurs sont un interrupteur à part (`VOLUME_ENRICH_CREDITS`), éteint par défaut.

`VOLUME_FORCE_OVERWRITE` lève la règle de comblement le temps d'un run.

## One-shots

Un one-shot tient dans un fichier unique, sans numéro de tome. S'il porte un **ISBN**, MetaKavita part chez les fournisseurs d'ISBN. S'il n'a ni numéro ni ISBN, la passe automatique l'écarte — sauf si l'atelier a déjà collé un Champ Magique. Une série dont tu n'as que le tome 1 est bel et bien enrichie.

## Mangas

Manga-News liste les tomes VF (titre, résumé, ISBN, date), une page par tome **possédé** — devant sur une bibliothèque manga, dernier recours sur Comic (Flexible). Un index HTML qui touche son plafond n'arrête plus la cascade : MangaDex est encore consulté pour les jaquettes manquantes. Annuler pendant un index déjà assez couvrant le garde et ne part pas ensuite chercher MangaDex. Les tomes qui portent déjà un ISBN sont cherchés sur Google Books, puis Open Library, Hardcover, openBD.

`VOLUME_ENRICH_EXPERIMENTAL` cherche sur Google Books par titre de série et numéro quand il n'y a ni ISBN ni fiche Manga-News. Le titre du candidat doit contenir le nom de la série *et* annoncer le numéro. Relis l'aperçu avant d'appliquer.

## Fournisseur imposé (`VOLUME_PROVIDER`)

Le menu distingue deux familles. Ceux qui *listent les albums d'une série* les ramènent tous en un appel. Ceux qui *identifient un tome par son ISBN* (Google Books, Open Library, Hardcover) travaillent tome par tome à partir de l'ISBN Kavita. Imposer l'un d'eux n'interroge que lui ; quand il n'a aucune prise, le journal le dit.

Masquer les tomes dans le [mode léger](dashboard.md#mode-léger) éteint aussi la passe.

Voir [Configuration](configuration.md) pour `VOLUME_NO_MANGA_FALLBACK` et les autres clés.
