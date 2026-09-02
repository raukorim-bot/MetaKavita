# Métadonnées par tome et par album

[English](../en/volumes.md) · [Français](README.md)

← [Documentation](README.md)

Éteint par défaut (`VOLUME_ENRICHMENT_ENABLED`). Tant qu'il l'est, les boutons disparaissent et l'API répond 403. On l'allume depuis le bloc sidebar **Tomes et albums** (badge expérimental).

![Options de scraping — Tomes et albums](../../assets/docs-volumes-sidebar.png)

Là où l'[Inventaire](inventory.md) dit ce qui manque, ceci remplit ce qui est là.

Trois surfaces, qui ne se marchent pas dessus :

* **📑 Rapport de tomes** (sur la ligne de série) — inventaire seul : possédés vs attendu, ISBN manquants, attendu forcé, exclusion. Pied : **Rafraîchir**, lien **Atelier**, CSV / TXT.
* **Accès Atelier sur le Dashboard** — **Atelier** trône en évidence dans la barre supérieure sticky (`header.topbar`) ainsi que dans l'en-tête de la barre d'outils, avec son icône SVG dédiée et son thème sarcelle, pour ouvrir `/volumes` à tout moment (le rail ou la dernière série consultée charge la fiche sans sélection préalable requise). Passe automatique disponible sur les séries cochées, annulable. Honore les liens magiques déjà posés dans l'atelier. Pas de Champ Magique dans la barre.
* **Atelier** `GET /volumes` ou `GET /series/<id>/volumes` — page autonome (comme `/stats`). À l'ouverture : Kavita + Meta, **aucun scrape**. Interface moderne, compacte et haute densité d'information (hauteur de la fiche série divisée par deux, cartes de tomes allégées de plus de moitié permettant d'afficher 2 à 3 tomes simultanément). Formulaires et champs modernisés sur le modèle élégant de la Revue Manuelle et de « Ajuster avant envoi » (fond ardoise sombre `#141926`, coins arrondis à 8px, padding aéré, libellés en casse naturelle, fin du liseré jaune criard remplacé par une teinte ambrée très douce). Carte série (sarcelle) ≠ cartes tomes (orange). **Duplication série → tomes** : chaque champ compatible de la série dispose d'un micro-bouton `Vers tomes` permettant en 1 clic de propager sa valeur (scénario, dessin, staff, genres, tags, classification, résumé, langue) à tous les tomes chargés, avec marquage automatique en dirty et sauvegarde SQLite debouncée. Un bouton global **Dupliquer vers les tomes** dans la fiche série cascade l'ensemble des métadonnées communes renseignées d'un coup. Les cartes de tomes s'équipent de puces de statut modernes (`DONE`, `STAGED`, `PENDING`). Les champs courts (année, statut, âge, staff) se mettent à trois par ligne. Le staff en trop se range sous **Plus de champs (x complétés / y)** (le volet est mémorisé, avec compteur dynamique en direct). Le **Champ Magique** est un bandeau compact libellé, visible tout de suite (la touche Entrée lance directement la recherche). Le titre de série ouvre la fiche Kavita. La barre d'action sticky des tomes flotte élégamment en dark glassmorphism (compte de sélection, boutons groupés, envoi principal en dégradé orange). `/` pose le focus sur la recherche du rail ; ← → se grisent en bout de liste ; les fiches du rail sont compactées à 48 px (+15% de séries visibles). La barre de navigation supérieure intègre un bouton permanent **M'offrir un café** (☕) avec toast immédiat et cooldown supporter. L'overlay nagware supporter peut également apparaître rarement après des écritures réussies dans Kavita (variante `workshop_craft`, sous conditions strictes : lune de miel de 7 jours, seuil d'activité minimum de 10 éléments traités, maximum 1 à 2 fois par jour, pause honneur de 30 jours). Le journal live est à droite. Les jaquettes ont un relief de livre 2:3 valorisé et moderne (124×186 px pour la série, 104×156 px pour les tomes) et un bouton **Choisir** ; l'URL choisie part à l'envoi, pas via `/update-cover`. Édition sur place avec persistance automatique en brouillon pour la série et les tomes (debounced 500 ms, identifiants externes et modifications préservés en SQLite `_staged: True`, étanche face aux passes concurrentes, survit au rechargement F5 et à la navigation). Manual Review / Super Review (fiche ou tome) permettent d'ajuster les métadonnées (collecte multi-fournisseurs interrogeant l'ensemble des scrapers actifs pour ISBN et titre avec pré-sélection, navigation clavier dédiée avec Échap/Entrée/Flèches/chiffres 1–9/double-clic et miniatures de jaquettes, conservation du fournisseur d'origine, fusion de sources ou complétion manuelle par champ, prise en compte de l'ISBN saisi) en passant par les étapes de revue (choix, couverture, prévisualisation/édition) avant de stager la fiche à la confirmation ; elles n'écrivent **pas** Kavita. **Envoyer** un tome / la fiche / la sélection / tous les tomes est ce qui écrit, purgeant automatiquement les jaquettes stagées en cas de succès pour éviter leur résurrection au rechargement et invalidant les caches d'hygiène. L'envoi **écrase** les champs déjà remplis, verrous compris (une valeur vide, nom localisé compris, n'est jamais écrite). Reset = Meta + relecture Kavita, **pas** de rewind des écritures déjà dans Kavita. Reset d'un tome débloque aussi la reprise de la passe automatique pour cette série. Le rail reprend la recherche, la bibliothèque, le statut et « masquer les ignorés » du tableau de bord. Un clic charge la série à côté, sans recharger la page. Les jaquettes déjà dans Kavita sont gardées sur disque.

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
