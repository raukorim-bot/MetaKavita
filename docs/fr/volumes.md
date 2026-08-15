# Métadonnées par tome et par album

[English](../en/volumes.md) · [Français](README.md)

← [Documentation](README.md)

Éteint par défaut (`VOLUME_ENRICHMENT_ENABLED`). Tant qu'il l'est, les boutons disparaissent et l'API répond 403. On l'allume depuis le bloc sidebar **Tomes et albums** (badge expérimental).

![Options de scraping — Tomes et albums](../../assets/docs-volumes-sidebar.png)

Là où l'[Inventaire](inventory.md) dit ce qui manque, ceci remplit ce qui est là. Le bloc toolbar **TOMES** (même bande que l'Inventaire) a **Enrichir les tomes sélectionnés** — mêmes cases que le batch de scraping.

Le **Rapport de tomes** d'une série (📑 sur la ligne) est partagé avec l'Inventaire : possédés vs attendu scrapé, statut de publication, ISBN manquants, tableau des tomes (✓ si résumé), **Attendu forcé** et **Exclure de l'inventaire**. Pied : **Rafraîchir**, **Enrichir les tomes**, CSV / TXT.

![Rapport de tomes](../../assets/docs-volume-report.png)

**Enrichir les tomes** montre ensuite ce qui serait écrit, tome par tome, avec une case sur chaque ligne — rien ne part tant que tu n'as pas appliqué.

Écrits dans cette première version : **titre d'album, résumé, date de parution, ISBN et couverture**, uniquement dans les champs vides. Un champ rempli à la main, ou verrouillé dans Kavita, n'est pas touché et dit pourquoi dans l'aperçu.

Une passe de bibliothèque prend place à côté d'Analyser, avec la même barre et le même Annuler.

Sources : ComicVine (cent numéros par requête), Bédéthèque et Planète BD (album par album), Manga-News pour les tomes VF, et, pour les tomes qui portent déjà un ISBN, Google Books puis Open Library puis Hardcover. Les crédits d'auteurs sont un interrupteur à part (`VOLUME_ENRICH_CREDITS`), éteint par défaut.

`VOLUME_FORCE_OVERWRITE` lève la règle de comblement le temps d'un run.

## One-shots

Un one-shot tient dans un fichier unique, sans numéro de tome. S'il porte un **ISBN**, MetaKavita part chez les fournisseurs d'ISBN. S'il n'a ni numéro ni ISBN, la série est écartée sans appel, et l'aperçu le dit. Une série dont tu n'as que le tome 1 est bel et bien enrichie.

## Mangas

Manga-News liste les tomes VF (titre, résumé, ISBN, date), une page par tome — devant sur une bibliothèque manga, dernier recours sur Comic (Flexible). MangaDex comble encore avec la vraie couverture de chaque tome (un appel pour la série) sans annuler le reste de la cascade. Les tomes qui portent déjà un ISBN sont cherchés sur Google Books, puis Open Library, puis Hardcover.

`VOLUME_ENRICH_EXPERIMENTAL` cherche sur Google Books par titre de série et numéro quand il n'y a ni ISBN ni fiche Manga-News. Le titre du candidat doit contenir le nom de la série *et* annoncer le numéro. Relis l'aperçu avant d'appliquer.

## Fournisseur imposé (`VOLUME_PROVIDER`)

Le menu distingue deux familles. Ceux qui *listent les albums d'une série* les ramènent tous en un appel. Ceux qui *identifient un tome par son ISBN* (Google Books, Open Library, Hardcover) travaillent tome par tome à partir de l'ISBN Kavita. Imposer l'un d'eux n'interroge que lui ; quand il n'a aucune prise, le journal le dit.

Masquer les tomes dans le [mode léger](dashboard.md#mode-léger) éteint aussi la passe.

Voir [Configuration](configuration.md) pour `VOLUME_NO_MANGA_FALLBACK` et les autres clés.
