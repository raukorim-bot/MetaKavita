# Variables de configuration

[English](../en/configuration.md) · [Français](README.md)

← [Documentation](README.md)

La plupart des réglages ci-dessous se retrouvent aussi dans la **Configuration globale** (⚙️ Config) : URL et clé Kavita, clés des providers, traduction, langues et planification.

![Modal Configuration globale](../../assets/docs-config-modal.png)

*MetaKavita dispose d'un moteur de clés d'API dynamique (Zero-Hardcode). Tout scraper déclarant `needs_api_key = True` écoutera automatiquement sa variable d'environnement et affichera son champ de saisie dans l'UI.*

> **Précédence : `config.json` > variable d'environnement > défaut.** Une variable d'environnement **sème** un réglage que le fichier de configuration ne contient pas encore — elle n'écrase jamais un réglage que vous avez déjà modifié dans l'interface web. Au premier démarrage, les variables que vous avez posées sont écrites dans `config.json` : elles prennent donc effet *et* deviennent modifiables depuis l'interface, qui a le dernier mot ensuite.

| Variable | Description | Valeur par défaut |
| :--- | :--- | :--- |
| `ADMIN_USERNAME` | Nom du compte amorcé depuis `ADMIN_PASSWORD_HASH`. Ignoré si un compte existe déjà. | `admin` |
| `ADMIN_PASSWORD_HASH` | Mot de passe pré-haché servant à créer le premier compte au démarrage, sans passer par l'écran de configuration. À générer avec `python debug/hash_password.py`. Ignoré dès qu'un compte existe : il ne peut donc jamais écraser un mot de passe réel. Une valeur qui n'est pas un hachage — un mot de passe en clair, par exemple — est refusée avec une erreur dans le journal, plutôt que de créer un compte qu'aucun mot de passe n'ouvre. | *(Vide)* |
| `TRUSTED_PROXY_COUNT` | `1` (défaut) fait confiance aux en-têtes `X-Forwarded-*` d'un reverse proxy. **Mettre `0` si MetaKavita est joignable directement**, sinon l'en-tête est fourni par le client et le verrouillage *par IP* peut être esquivé en le faisant varier. Un plafond global (20 échecs de connexion par quart d'heure, toutes adresses confondues) s'applique dans toutes les configurations : la force brute reste donc bornée quoi qu'il arrive — mais lorsqu'il se déclenche, l'écran de connexion est verrouillé pour tout le monde, vous compris. | `1` |
| ~~`ADMIN_PASSWORD`~~ | **Supprimé.** Remplacé par la création de compte au premier démarrage. Si une valeur subsiste dans `config.json`, l'écran de configuration la demande une dernière fois comme preuve que vous aviez déjà accès à cette instance — une mise à jour ne laisse donc jamais une instance protégée à la disposition du premier arrivé sur `/setup`. Elle est effacée dès que votre compte est créé. Perdue ? Videz cette ligne dans `data/config.json` puis rechargez la page. | — |
| `PUID` / `PGID` | UID et GID sous lesquels tourne l'application, et propriétaires de tout le contenu de `/app/data`. À renseigner avec le propriétaire de votre dossier `./data` monté (`id -u` / `id -g`) s'il n'est pas `1000:1000`. Le conteneur ne démarre en root que le temps de les appliquer, puis abandonne ses privilèges. | `1000` / `1000` |
| `ROOT_PATH` | Sous-chemin d'URL lors de l'exposition derrière un reverse proxy (ex: `/metakavita`). L’env prime sur la valeur sauvée au setup/`config.json`. Redémarrage requis après changement. | *(Vide)* |
| `CORS_ALLOWED_ORIGINS` | Origins CORS explicites séparées par des virgules (HTTP + Socket.IO), ex: `https://metakavita.home.local.ltd`. Vide = Same-Origin uniquement. `*` est rejeté. Ne remplace pas une config reverse-proxy correcte pour l'upgrade WebSocket. | *(Vide)* |
| `KAVITA_URL` | URL Kavita **vue depuis le conteneur MetaKavita** — jamais `localhost`. Ex. : `http://host.docker.internal:5001` (Kavita publié sur l'hôte), `http://kavita:5000` (même réseau Docker), ou une URL publique `https://…`. Une chaîne vide dans `config.json` ne bloque pas le seed env pour cette clé. | *(Vide)* |
| `KAVITA_EXTERNAL_URL` | URL publique optionnelle de Kavita pour les liens UI (ex: `https://kavita.domain.tld`). Si vide, repli sur `KAVITA_URL`. | *(Vide)* |
| `KAVITA_HTTP_TIMEOUT` | Timeout HTTP (secondes) pour les **écritures** Kavita (métadonnées / update série / couverture). Montez à `90`–`120` sur HDD ou gros force-update. | `60` |
| `MAX_TAGS` | Nombre max de tags écrits dans Kavita (scrapers + filet `enrichment_engine`). Env / `config.json` uniquement — pas d'UI. Borné 1–100. | `15` |
| `MAX_GENRES` | Nombre max de genres écrits dans Kavita (scrapers + filet `enrichment_engine`). Env / `config.json` uniquement — pas d'UI. Borné 1–50. | `5` |
| `KAVITA_API_KEY` | Ta clé API Kavita. | *(Vide)* |
| `TRANSLATION_PROVIDER` | Moteur de traduction actif (`GOOGLE`, `DEEPL`, `AZURE`, ou `NONE` pour désactiver). | `GOOGLE` |
| `AZURE_API_KEY` | Ta clé d'API Microsoft Azure Translator (Moteur principal). | *(Vide)* |
| `AZURE_REGION` | Ta région Azure Translator (ex: `francecentral`). | *(Vide)* |
| `DEEPL_API_KEY` | Ta clé API DeepL pour la traduction (Repli de secours). | *(Vide)* |
| `TARGET_LANG` | Langue cible des résumés (`FR`, `EN`...). Modifie dynamiquement la langue de recherche Google Books ! Absent du fichier et de l'env → dérivé de `UI_LANG` (`en`→`EN`, `fr`→`FR`). | `EN` |
| `UI_LANG` | Langue de l'interface MetaKavita (`fr` ou `en`). Sur une install neuve, tu peux forcer `UI_LANG=fr` dans Compose avant d'ouvrir l'UI. La langue se change aussi dans Config sans devoir remplir Kavita d'abord. | `en` |
| `PUBLISHER_PREFERENCE` | Préférer les Éditeurs Traduits/Licenciés (`LOCALIZED`) ou d'origine Japonaise (`ORIGINAL`). | `LOCALIZED` |
| `LOCALIZED_TITLE_MODE` | Construction de Kavita `localizedName` : `all` (joindre les titres uniques avec `" / "`), `prefer` (filtre/ordre via `LOCALIZED_TITLE_LANGS`), `none` (ne pas écrire). Ne réécrit jamais Series `name`. Aussi dans la modal Config. | `all` |
| `LOCALIZED_TITLE_LANGS` | Tags BCP-47-ish séparés par des virgules en mode `prefer` (ex. `en, ja-ro, ja`). Ordre = priorité. Override par série via `alt_title_langs`. | *(Vide)* |
| `PROVIDER_1` | Source de métadonnées principale Manga (`MANGABAKA`, `KITSU`, `ANILIST`, `MAL`, `MANGADEX`, `MANGAUPDATES`, `MANGANEWS`, `SHIKIMORI`, plus Magasin ex. `WIKIDATA`). | `MANGABAKA` |
| `MAL_API_KEY` | **Client ID** MyAnimeList (pas un token secret) depuis https://myanimelist.net/apiconfig — envoyé en `X-MAL-CLIENT-ID`. | _(vide)_ |
| `PROVIDER_2` | Source de secours 1 Manga. | `KITSU` |
| `PROVIDER_3` | Source de secours 2 Manga. | `ANILIST` |
| `COMIC_PROVIDER_1`| Source de métadonnées principale Comic (`BEDETHEQUE`, `BDTHEQUE`, `COMICVINE`, `GOOGLEBOOKS`, `OPENLIBRARY`, `HARDCOVER`, `ANILIST`, plus Magasin ex. `WIKIDATA`). | `COMICVINE` |
| `COMIC_PROVIDER_2`| Source de secours 1 Comic. | `ANILIST` |
| `COMIC_PROVIDER_3`| Source de secours 2 Comic. | `NONE` |
| `BOOK_PROVIDER_1` | Source de métadonnées principale Roman (`GOOGLEBOOKS`, `OPENLIBRARY`, `HARDCOVER`, `ANILIST`, `MANGABAKA`, `MAL`, plus Magasin ex. `WIKIDATA`). | `GOOGLEBOOKS` |
| `BOOK_PROVIDER_2` | Source de secours 1 Roman. | `OPENLIBRARY` |
| `BOOK_PROVIDER_3` | Source de secours 2 Roman. | `NONE` |
| `SMART_SCORING`   | Activer le Smart Scoring — meilleur match (`true` ou `false`). Off = fallback classique par ordre de liste. | `true` |
| `MATCH_THRESHOLD_CUSTOM` | Déverrouiller le seuil de match personnalisé (Baromètre de fiabilité). Off = toujours `0.60`. | `false` |
| `MATCH_ACCEPT_THRESHOLD` | Seuil d'acceptation si custom ON (`0.30`–`1.00`). Ignoré si custom OFF. | `0.60` |
| `ENABLE_PLAYFUL_STATS` | Afficher le tableau `/stats` ludique (Chart.js + cartes fun). | `true` |
| `SMART_COMPLETION`| Activer la fusion des données (`true` ou `false`). Auto peut combler l’âge `safe`/`suggestive`/`mature` depuis un secondaire ; jamais un âge NSFW. Champ ciblé **Âge** requis pour écrire Kavita. | `false` |
| `MANUAL_REVIEW_MODE` | Gare les candidats en `PENDING_REVIEW` pour pick/édition/confirm au lieu d’écrire automatiquement dans Kavita. Interrupteur sidebar. Désactiver purge la file. | `false` |
| `MANUAL_REVIEW_EDIT` | Après le pick, affiche un formulaire d’édition avant l’écriture Kavita. | `true` |
| `MANUAL_REVIEW_SUPER` | Super Review : interroge tous les scrapers utilisables (pas seulement les 3 slots). Nécessite le mode manuel. | `false` |
| `MANUAL_REVIEW_SOUNDS` | Sons UI courts sur pick / confirm / skip. | `false` |
| `TITLE_FALLBACK_TRANSLATION`| Expérimental : Traduit le titre non-trouvé en anglais pour relancer une seconde recherche. | `false` |
| `AUTO_SYNC_INTERVAL`| Intervalle d'Auto-Sync en minutes (`0` pour désactiver). | `0` |
| `DISABLED_LIBRARIES` | IDs exclus du **polling auto-sync** uniquement (dénylist, virgules). Vide = auto-sync toutes. Dashboard, batch manuel et webhook non filtrés. | _(vide)_ |
| `AUTO_COVER` | Envoyer automatiquement les couvertures à Kavita (`true` ou `false`). | `false` |
| `COVER_FORCE_OVERWRITE` | Autoriser les scrapes automatiques à écraser les couvertures choisies à la main (cartouche 🔒). Laissez décoché pour les conserver. | `false` |
| `LIBRARY_INVENTORY_ENABLED` | Afficher le panneau Inventaire (tomes / chapitres manquants, doublons, séries sans id externe). | `true` |
| `INVENTORY_FOLDER_PATH_PREFIX` | Préfixe POSIX collé devant le `folderPath` Kavita dans le script bash (ex. `/mnt/media`). Se règle dans la modale Doublons. Vide = chemin Kavita tel quel. | _(vide)_ |
| `INVENTORY_FOLDER_TRASH` | Dossier POSIX de corbeille pour le script `mv` généré, hors des roots Kavita (ex. `/mnt/media/corbeille-doublons`). Se règle dans la modale Doublons. | _(vide)_ |
| `VOLUME_ENRICHMENT_ENABLED` | Écrire les métadonnées de chaque tome / album (titre, résumé, date, ISBN, couverture). Éteint, les boutons disparaissent et l'API répond 403. | `false` |
| `VOLUME_FORCE_OVERWRITE` | Autoriser l'enrichissement par tome à écraser les champs déjà remplis ou verrouillés dans Kavita. Laissez décoché pour ne combler que les vides. | `false` |
| `VOLUME_ENRICH_CREDITS` | Récupérer aussi les crédits d'auteurs par album — une requête fournisseur de plus par tome. | `false` |
| `VOLUME_ENRICH_EXPERIMENTAL` | Pour les mangas sans liste de tomes chez un fournisseur ni ISBN : chercher chaque tome sur Google Books par titre de série et numéro. Le titre et le numéro du résultat sont revérifiés avant écriture, mais aucun identifiant ne garantit qu'il s'agit du bon tome. | `false` |
| `VOLUME_PROVIDER` | N'interroger qu'un seul fournisseur pour les tomes, cascade écartée. Retenu seulement là où ce fournisseur sait servir la bibliothèque : imposer un fournisseur de comics ne prive pas vos bibliothèques manga de fournisseur. Vide = laisser la cascade décider. | _(vide)_ |
| `VOLUME_NO_MANGA_FALLBACK` | Sur une bibliothèque **Comic (Flexible)**, ne plus retomber sur les fournisseurs manga après les fournisseurs comics. Utile quand vous n'y rangez que de la bande dessinée ; sans effet sur les autres types. | `false` |
| `UI_SHOW_MANUAL_REVIEW` | Afficher les réglages de la relecture manuelle dans la barre latérale. Décoché, la catégorie disparaît **et** le mode s'éteint, file d'attente vidée. | `true` |
| `UI_SHOW_INVENTORY` | Afficher les réglages de l'Inventaire dans la barre latérale. Décoché, la catégorie disparaît **et** l'Inventaire s'éteint. | `true` |
| `UI_SHOW_VOLUMES` | Afficher les réglages de l'enrichissement par tome dans la barre latérale. Décoché, la catégorie disparaît **et** la passe s'éteint. | `true` |
---
