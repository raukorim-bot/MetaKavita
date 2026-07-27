# Revue détaillée du code — MetaKavita (post-refactor)

> Document généré à la demande d'Amaury pour servir de « carte » du code après le
> refactor d'architecture. Chaque section couvre un fichier (ou un petit groupe de
> fichiers très liés) : son rôle, ce qu'il implique pour le reste de l'application,
> et — quand c'est pertinent — ses limites ou risques actuels.
>
> Ce document est un instantané. Il complète `DEVELOPER.md` (guide de contribution)
> et `kavita_api.md` (spécification de l'API Kavita) sans les remplacer.

---

## ⚠️ 0. Point critique — statut : jeton révoqué, fichier assaini

**`debug/debug_hardcover.py` contenait un jeton d'API Hardcover en clair** en ligne 12
(`API_TOKEN = "Bearer eyJhbGci..."`). Ce n'était pas un exemple factice : décoder le JWT révélait
un `sub` (identifiant utilisateur), un `applicationId`, un `iat` et un `exp` cohérents avec un
vrai jeton personnel Hardcover valide ~1 an.

Suivi :
1. ✅ Jeton révoqué côté Hardcover par Amaury.
2. ✅ Fichier assaini : `API_TOKEN` est désormais lu depuis `data/config.json`
   (`HARDCOVER_API_KEY`, la même clé que `scrapers/hardcover.py`) ou depuis la variable
   d'environnement `HARDCOVER_API_KEY`, plus aucun secret en dur dans le code.
3. ⏳ **Reste à vérifier par vous** : si ce fichier a déjà été poussé sur un dépôt distant
   (`git log --all -- debug/debug_hardcover.py`), le jeton (révoqué, donc sans risque
   d'exploitation, mais toujours visible) reste lisible dans l'historique tant qu'il n'est pas
   purgé (`git filter-repo` ou BFG Repo-Cleaner + force-push). Comme le jeton est déjà révoqué,
   cette étape n'est plus urgente en termes de sécurité, mais reste recommandée par hygiène du
   dépôt.

Le reste du document est au format « observation / recommandation », sans caractère bloquant.

---

## 1. Vue d'ensemble de l'architecture

Depuis le refactor, une requête HTTP traverse la pile ainsi :

```
Navigateur ──▶ app.py (assemblage Flask, middlewares, before_request)
                  │
                  ├─▶ routes/*.py (Blueprints : logique HTTP fine, pas de métier lourd)
                  │       │
                  │       ├─▶ services/enrichment_engine.py (orchestration scraping → Kavita)
                  │       ├─▶ services/background_tasks.py (files de synchro)
                  │       ├─▶ services/changelog_service.py (lecture CHANGELOG.md)
                  │       ├─▶ db_manager.py (SQLite : cache.db)
                  │       ├─▶ config_manager.py (data/config.json)
                  │       └─▶ kavita_api.py (client HTTP Kavita)
                  │
                  └─▶ sockets/handlers.py (Socket.IO : connexion, streaming de couvertures)

scrapers/*.py ──▶ chacun hérite de scrapers/base.py::BaseScraper, est auto-découvert par
                  scrapers/__init__.py::ScraperRegistry, et s'appuie sur scrapers/utils.py
                  (nettoyage de titres + matrice de scoring) pour choisir le meilleur candidat.
```

`app.py` ne contient plus aucune route ni logique métier : c'est un point d'assemblage. Toute la
logique « qu'est-ce qu'on fait avec une série » vit dans `services/enrichment_engine.py`. Toute la
logique « comment on parle à Kavita » vit dans `kavita_api.py`. Cette séparation est la base de
la maintenabilité gagnée par le refactor — voir section 12 de `DEVELOPER.md` pour la version
« guide de contribution » de cette même carte.

---

## 2. Cœur applicatif (racine du projet)

### `app.py`
Point d'entrée Flask. Responsabilités, dans l'ordre où elles apparaissent dans le fichier :
patch `eventlet` (obligatoire *avant* tout autre import réseau, sinon le monkey-patching
n'est pas fiable), création de l'objet `app`, `SECRET_KEY` depuis la config, initialisation de
`socketio`, middlewares `ProxyFix` + `ScriptNameStripper` (support reverse-proxy et sous-chemin
via `ROOT_PATH`), `init_db()`, configuration du logging (fichier + console + WebSocket via
`WebSocketLogHandler`), le garde `before_request::require_login`, l'enregistrement des 6
Blueprints, l'import de `sockets.handlers` (effet de bord uniquement — le module doit être
importé pour que les `@socketio.on(...)` s'enregistrent), le contexte global `app_version`, et
enfin `start_background_workers()`.

**Implication majeure** : `app` doit rester une variable de niveau module (contrainte imposée par
`CMD gunicorn ... app:app` dans le `Dockerfile`). Toute tentative de le transformer en factory
(`create_app()`) casserait le déploiement sans adapter aussi le `Dockerfile` et la commande
Gunicorn. `require_login` doit être tenu à jour manuellement à chaque ajout d'endpoint public
(actuellement whitelist : `auth.login`, `static`, `sync.webhook`) — c'est un point de friction
identifié : un oubli ici expose ou bloque silencieusement un futur endpoint.

### `extensions.py`
Un seul objet : `socketio = SocketIO()`, non initialisé. Existe uniquement pour couper le cycle
d'import `app.py ⇄ routes/ ⇄ sockets/` : ces derniers ont besoin de l'instance SocketIO sans avoir
besoin d'importer `app.py`. Pattern classique Flask (équivalent à `db = SQLAlchemy()` dans
beaucoup de projets Flask/SQLAlchemy).

### `config_manager.py`
Gère `data/config.json` : `load_config()` renvoie un dict avec des valeurs par défaut fusionnées
avec le fichier, puis avec les variables d'environnement pour une liste de clés précises. Génère
et persiste automatiquement `SECRET_KEY` et `WEBHOOK_TOKEN` au premier lancement s'ils sont
absents. Point notable : la boucle `for env_key, env_val in os.environ.items(): if
env_key.endswith("_API_KEY")...` capture *toute* variable d'environnement finissant par
`_API_KEY`, y compris celles ajoutées par un scraper personnalisé (`data/scrapers/`) sans
modification du code — c'est ce qui permet aux scrapers custom de définir leur propre clé API sans
toucher `config_manager.py`. `ADMIN_PASSWORD` a une règle de précédence particulière : le fichier
gagne sur l'environnement s'il est présent, ce qui est documenté mais reste une source d'erreur
utilisateur classique (« j'ai mis `ADMIN_PASSWORD` dans mon `docker-compose.yml` mais rien ne
change » → en général parce que `data/config.json` contient déjà une valeur, même vide).

### `db_manager.py`
Couche de persistance SQLite (`data/cache.db`, table unique `series_cache`). `_ensure_schema()`
fait des `ALTER TABLE ADD COLUMN` défensifs (avec `try/except` silencieux) pour permettre les
montées de version sans script de migration formel — fonctionne bien à cette échelle (une seule
table, peu de colonnes) mais ne passerait pas à l'échelle d'un schéma plus complexe. Expose deux
API pour écrire un override : `save_series_override(SeriesOverride)` (la voie moderne, préférée
par tout le nouveau code) et `save_forced_overrides(...)` (wrapper positionnel rétro-compatible,
gardé uniquement pour `debug_concurrency.py`). Toute nouvelle colonne de configuration par série
doit être ajoutée à la fois dans `_ensure_schema()`, dans `SeriesOverride` (`models.py`), et dans
`get_all_cached_data()` — ces trois points de synchronisation manuelle sont documentés en section
11.C de `DEVELOPER.md`.

### `models.py`
Un seul dataclass : `SeriesOverride` (id, ID/URL forcé, titre alternatif, provider forcé, champs
ciblés, préférence d'éditeur). Sert de contrat explicite entre `routes/series.py`,
`db_manager.py` et `services/enrichment_engine.py`. C'est directement la correction structurelle
du bug historique « `publisher_pref` lu dans le formulaire mais jamais transmis » : avec des
arguments nommés obligatoires, ce genre d'oubli devient visible à la relecture (et serait détecté
par un linter/type-checker), alors qu'il était invisible avec une signature positionnelle à 6
paramètres. `from_cache_dict()` est le point d'entrée pour reconstruire un override à partir d'une
ligne SQLite déjà chargée (utilisé par `routes/series.py::apply_series_cover`).

### `kavita_constants.py`
Centralise 3 choses qui étaient auparavant dupliquées dans `app.py` et certains scrapers :
`PUBLICATION_STATUS_MAP` / `AGE_RATING_MAP` (enums numériques attendus par l'API Kavita),
`RAW_STATUS_NORMALIZATION_MAP` + `normalize_provider_status()` (normalisation des statuts bruts
fournisseurs), et `FORMAT_KEYWORDS` + `resolve_kavita_format_enum()` (détection du sens de
lecture/format par mots-clés). Directement issu du bug MangaBaka (`"completed"` non reconnu) :
la centralisation empêche qu'un mapping soit mis à jour dans un fichier et oublié dans un autre.
Actuellement, seul `scrapers/mangabaka.py` utilise `normalize_provider_status()` — les autres
scrapers (Kitsu, MangaDex, Shikimori, MangaUpdates, MAL) ont chacun leur **propre** mapping de
statut inline, redondant avec celui-ci. Ce n'est pas un bug actif (chaque mapping local est
correct pour son fournisseur), mais c'est une dette : un nouveau statut brut à normaliser doit
aujourd'hui être ajouté indépendamment dans chaque scraper au lieu d'un seul endroit.

### `kavita_api.py`
Le client HTTP vers l'API Kavita — le fichier le plus « sensible » du projet, car chaque méthode
encode une leçon apprise sur le comportement interne (souvent non documenté) de Kavita :
- `authenticate()` : échange la clé API contre un JWT via `/api/Plugin/authenticate`.
- `_normalize_library_type()` : traduit les IDs/labels de type de bibliothèque Kavita (variables
  selon la version) vers `"Manga"/"Comic"/"Book"`, avec un cache mémoire par série
  (`_series_lib_type_cache`, attribut de **classe**, donc partagé par toutes les instances —
  intentionnel pour limiter les appels HTTP en traitement par lot, mais à garder en tête si un
  jour plusieurs instances Kavita distinctes cohabitent dans le même process).
- `update_series_metadata()` : implémente le protocole **Unlock → Write → Lock** en 2 passages
  (déverrouille tous les flags `*Locked`, écrit, puis re-verrouille) et assainit 6 clés système
  (`created`, `lastModified`, `totalCount`, `maxCount`, `pages`, `wordCount`) qui ne doivent
  jamais être ré-envoyées à Kavita — c'est la correction du crash critique
  `maxCount:-100000`. Cet assainissement est **centralisé ici**, donc protège tous les appelants
  (aujourd'hui uniquement `services/enrichment_engine.py`) sans qu'ils aient à y penser.
- `update_series_general()` : la méthode la plus commentée du fichier, avec la documentation
  complète du bug KOReader/Kamare (`localizedName` écrasé à `null` + verrous réinitialisés en cas
  de payload partiel). Récupère systématiquement l'état actuel via `GET /api/Series/{id}` avant
  d'écrire, pour ne jamais envoyer de payload partiel dangereux à cet endpoint précis.
- `upload_series_cover()` : téléchargement via `curl_cffi` (impersonation Chrome, nécessaire pour
  contourner Cloudflare sur certains hébergeurs d'images), conversion Base64 sans préfixe Data URI
  (le préfixe faisait planter Kavita avec « Invalid Filename »).
- `get_series_deep_metadata()` / `get_series_isbn()` : construisent le « contexte existant »
  (ISBN, auteurs, éditeur, année, genres) utilisé par `scrapers/utils.py::score_candidate()` pour
  ancrer la recherche externe sur ce que Kavita sait déjà.

Ce fichier est un candidat naturel à un futur test d'intégration contre une vraie instance Kavita
de test (`tests/test_kavita_api.py` couvre déjà la logique en mockant `requests`, mais rien ne
garantit aujourd'hui que le comportement réel de Kavita 0.8.x n'a pas changé entre deux versions).

### `metadata_fetcher.py`
Le moteur de cascade multi-fournisseurs (`fetch_metadata()`), indépendant de Flask et de Kavita.
Logique clé :
- `throttle_provider()` : rate-limiting par scraper basé sur `LAST_REQUEST_TIMES` (dict global au
  module) et l'attribut `rate_limit` de chaque scraper — attend uniquement le temps restant
  nécessaire, jamais un délai fixe. Le cycle lire→dormir→écrire est rendu atomique par un verrou
  **par `scraper.id`** (`_THROTTLE_LOCKS`), pas un verrou global : deux providers différents
  peuvent être throttlés en parallèle sans se ralentir mutuellement, alors que deux appels
  concurrents pour le *même* provider sont correctement sérialisés (voir
  `tests/test_metadata_fetcher_throttle.py`).
- `run_cascade()` : interroge **tous** les providers configurés (il n'y a jamais eu de sortie
  anticipée après le premier succès — coûteux en appels réseau, mais volontaire), puis effectue
  un **Smart Scoring** en deux temps :
  1. **Sélection par score** : chaque candidat accepté porte un score (`_match_score`, attaché
     par le scraper via `attach_match_score()`, voir `scrapers/utils.py`) ; le meilleur score
     gagne (`master_data`), l'égalité étant départagée par la position dans la liste de fallback.
     Si `smart_fusion=True`, les providers suivants complètent les champs manquants dans l'ordre
     du score décroissant (et non plus l'ordre brut de la liste), sans jamais écraser un champ
     déjà rempli. Un candidat sans `_match_score` (scraper non migré) est traité comme "juste
     accepté" (`MATCH_ACCEPT_THRESHOLD`).
  2. **Exécution en deux vagues** : le provider #1 tourne seul, séquentiellement, pour amorcer le
     contexte (ISBN/auteurs, injecté dans `existing_metadata`) ; les providers restants tournent
     ensuite **en parallèle** (`ThreadPoolExecutor`) contre un instantané figé de ce contexte
     enrichi. But : latence proche du plus lent des providers plutôt que la somme de tous, tout en
     conservant l'essentiel du bénéfice anti-homonyme de la cascade de contexte sur les séries
     sans métadonnées Kavita pré-existantes (voir DEVELOPER.md §6.D pour la discussion complète du
     compromis "tout parallèle" vs "deux vagues").
- 2ᵉ passage « traduction de secours » : si rien n'est trouvé et que l'option
  `TITLE_FALLBACK_TRANSLATION` est activée, retente la cascade (même logique deux-vagues +
  scoring) avec le titre traduit en anglais (langue pivot pour la plupart des API asiatiques).

Voir `tests/test_metadata_fetcher_smart_scoring.py` pour la suite de non-régression du scoring et
de la parallélisation (y compris une assertion de timing qui prouve que les providers #2+
s'exécutent bien en parallèle, pas séquentiellement).

### `translator.py`
Abstraction de traduction avec 3 moteurs (`translate_azure`, `translate_deepl`,
`translate_google`) et une fonction façade `translate_text()` qui gère le choix utilisateur avec
repli automatique vers Google en cas d'échec d'Azure/DeepL (mais pas l'inverse — Google est
toujours le filet de sécurité final). `translate_google()` utilise `googletrans` (bibliothèque non
officielle qui imite l'API web de Google Translate) : c'est un point de fragilité connu du projet
(non lié au refactor) — Google peut changer son endpoint interne à tout moment et casser
silencieusement cette dépendance, sans version officiellement « stable » de `googletrans` à
épingler avec confiance à long terme.

### `translations.py`
Dictionnaire `translations = {"fr": {...}, "en": {...}}` utilisé pour tout le texte d'interface
(templates, JS via `window.AppTranslations`, logs applicatifs formatés dans
`services/enrichment_engine.py` et `services/background_tasks.py`). Fichier plat sans logique,
mais volumineux (~400 lignes) : à surveiller si une 3ᵉ langue est ajoutée un jour — actuellement,
chaque scraper a *aussi* son propre mini-dictionnaire `translations` interne pour ses logs
(`fr`/`en` uniquement), ce qui duplique le principe mais avec un périmètre différent (logs de
scraping vs. UI globale).

---

## 3. `services/` — logique métier extraite de `app.py`

### `services/enrichment_engine.py`
Le cœur fonctionnel de l'application : `enrich_series(series_id, series_name, force_update)`.
Directement extrait de l'ancien `process_series_logic()`. Sans dépendance vers `app.py` ni
`routes/`, ce qui lui permet d'être appelé aussi bien depuis une route HTTP
(`routes/sync.py::force_sync`) que depuis un worker de fond
(`services/background_tasks.py::_worker`). Séquence : authentification Kavita → lecture des
métadonnées existantes → détection du type de bibliothèque → résolution de la requête de
recherche (ID forcé > titre alternatif > nom Kavita) → sélection des providers selon le type de
bibliothèque et les réglages utilisateur (avec auto-réparation si la config pointe vers un
provider invalide/désactivé) → détection auto de provider par URL/ID → appel de
`metadata_fetcher.fetch_metadata()` → application filtrée des champs selon `targeted_fields` →
envoi à Kavita (metadata, general, cover). Le point le plus subtil du fichier est la relecture
« fraîche » de `targeted_fields` juste avant l'upload de couverture (lignes ~322-336) : elle
protège un choix de couverture manuel effectué par l'utilisateur *pendant* qu'un traitement de
fond était déjà en cours — c'est la correction directe du bug de couverture écrasée qui a
initié toute cette série de sessions de debug.

Ce fichier fait ~350 lignes et concentre beaucoup de logique métier dense (12 étapes
d'application de champs). C'est un candidat naturel à une décomposition ultérieure (une fonction
par « famille de champs » : résumé/année/statut, staff, éditeur, weblinks...) si de nouveaux
champs continuent d'être ajoutés — pas urgent aujourd'hui, mais à surveiller.

### `services/background_tasks.py`
Deux threads démons lancés une seule fois par `start_background_workers()` (appelé depuis
`app.py` au chargement du module) : `_worker()` consomme `sync_queue` (alimentée par
`routes/sync.py` sur `/force-sync`, `/batch-sync`, `/webhook`) et appelle `enrich_series()` en
séquentiel ; `_auto_sync_worker()` boucle toutes les 30 secondes, vérifie si
`AUTO_SYNC_INTERVAL` est écoulé, et si oui : nettoie le cache orphelin, puis pousse dans la file
toutes les séries `PENDING` ou absentes du cache. Le commentaire du fichier est explicite sur la
contrainte de déploiement : `start_background_workers()` ne doit être appelé **qu'une seule fois
par process**, ce qui n'est garanti que si Gunicorn tourne avec `-w 1`. Une évolution vers
plusieurs workers dupliquerait les threads et provoquerait un traitement en double de chaque
série — c'est la limitation la plus structurante de toute l'architecture actuelle en matière de
scalabilité horizontale.

### `services/changelog_service.py`
Deux responsabilités : extraire le numéro de version depuis la première ligne `## [x.y.z]` de
`CHANGELOG.md` (`get_current_version()`, mise en cache mémoire process via `_cached_version` pour
ne parser le fichier qu'une fois) et convertir l'intégralité du changelog en HTML simple (gras,
italique, code, titres, listes) pour la modale « Nouveautés » de l'UI, sans dépendance à une
bibliothèque Markdown externe — le parseur ligne-par-ligne (`get_full_changelog_html()`) est
volontairement minimaliste et ne gère qu'un sous-ensemble de Markdown (suffisant pour le format
réellement utilisé dans `CHANGELOG.md`, mais fragile si la structure du fichier changeait
radicalement, ex : tableaux, blocs de code multi-lignes).

---

## 4. `routes/` — Blueprints HTTP

Chaque module ne contient que du câblage HTTP (parsing de `request`, appel à la couche
service/persistance, formatage de la réponse) — aucune logique métier n'y a été laissée
volontairement.

### `routes/auth.py` (`auth_bp`)
`/login` (GET/POST) et `/logout`. Comparaison du mot de passe avec `secrets.compare_digest`
(protection contre les attaques par timing) + `time.sleep(2)` en cas d'échec (ralentit le
brute-force). Si `ADMIN_PASSWORD` n'est pas configuré, `/login` redirige directement vers l'accueil
— l'authentification est donc **optionnelle et désactivée par défaut**, à la charge de
l'utilisateur de la configurer s'il expose l'instance publiquement.

### `routes/pages.py` (`pages_bp`)
`/` et `/stats`. `_prepare_index_data()` est la fonction la plus dense du blueprint : connexion à
Kavita, récupération des bibliothèques/séries, nettoyage du cache orphelin, fusion avec le cache
local, masquage des clés API (`safe_config`) avant de les passer au template, et préparation des
listes de providers par type de bibliothèque pour les menus déroulants de configuration. C'est
cette fonction qui répond aussi à l'appel AJAX `loadLibrary()` du frontend (`static/js/batch.js`)
puisque `/` accepte `?library_id=` et renvoie une page HTML complète dont seul le fragment
`.content` est réinjecté côté client.

### `routes/config.py` (`config_bp`)
`/save-config` et `/regenerate-webhook-token`. Le premier reconstruit l'objet config champ par
champ depuis `request.form`, avec une règle répétée pour chaque clé API (`si vide → on efface, si
== '********' → on ne touche pas, sinon → on remplace`) : cette règle permet à l'UI d'afficher les
clés API masquées sans jamais les renvoyer en clair au serveur lors d'une sauvegarde qui ne les
concerne pas. Chaque nouveau scraper avec `needs_api_key=True` est géré automatiquement par la
boucle `for s in ScraperRegistry.get_all()`, donc ce fichier n'a pas besoin d'être modifié quand un
scraper personnalisé avec clé API est ajouté dans `data/scrapers/`.

### `routes/series.py` (`series_bp`)
`/save-override`, `/toggle-ignore`, `/api/series/<id>/covers`, `/api/series/<id>/update-cover`.
`get_series_covers()` interroge tous les scrapers compatibles avec le type de bibliothèque **en
parallèle** via `ThreadPoolExecutor` (jusqu'à 8 workers) — c'est le chemin de repli HTTP utilisé
quand le WebSocket est indisponible côté client (voir `static/js/covers.js::fetchCovers`).
`apply_series_cover()` contient la même logique de protection de couverture manuelle que
`services/enrichment_engine.py` (retrait de `'cover'` de `targeted_fields`), dupliquée
intentionnellement ici car c'est le point d'écriture initial du choix utilisateur.

### `routes/sync.py` (`sync_bp`)
`/reset-errors`, `/force-sync`, `/batch-sync`, `/stop-batch`, `/export-errors`, `/webhook`.
`/webhook` est le seul endpoint public de l'application (whitelisté dans `app.py::require_login`)
: protégé par un jeton dédié (`WEBHOOK_TOKEN`, distinct du mot de passe admin) comparé avec
`secrets.compare_digest`. Accepte plusieurs variantes de clés JSON (`seriesId`/`SeriesId`/
`series_id`) pour rester compatible avec différentes conventions de casse envoyées par Kavita
selon la version. `batch_sync()` a une règle métier explicite et commentée : en mode « lot
global » (aucune case cochée), les séries `IGNORED` sont exclues ; en mode sélection explicite,
elles sont traitées même si `IGNORED` — un utilisateur qui coche une série ignorée le fait
volontairement.

### `routes/misc.py` (`misc_bp`)
`/api/proxy-image` et `/api/changelog`. Le proxy d'image est un point sensible en matière de
sécurité (SSRF) : validation via `url_allowlist.validate_proxied_image_url` + fetch via
`fetch_with_safe_redirects` (jusqu'à 3 hops, chaque hop re-validé ; refus des IPs privées /
localhost). La liste blanche de domaines est reconstruite dynamiquement à chaque requête via
`ScraperRegistry.get_all_proxy_domains()` (agrège `proxy_domains` de tous les scrapers, y
compris personnalisés). C'est un bon design (pas de liste à maintenir manuellement), mais cela
signifie aussi qu'un scraper personnalisé malveillant ou mal écrit dans `data/scrapers/` pourrait
légitimement élargir la surface de ce proxy à un domaine arbitraire — cohérent avec le principe
déjà documenté dans `CUSTOM_SCRAPERS.md` (« le code personnalisé s'exécute avec les pleins
pouvoirs, à la responsabilité de l'utilisateur qui l'installe »).

---

## 5. `sockets/handlers.py`

Pas de route Flask ici : le fichier décore directement `extensions.socketio` et doit être importé
une fois pour effet de bord (fait dans `app.py`, après `socketio.init_app(app)`).
`handle_connect()` rejette la connexion WebSocket si un mot de passe admin est configuré et que la
session n'est pas authentifiée (`disconnect()` immédiat) — cohérence avec la protection HTTP de
`require_login`. `handle_fetch_covers_stream()` est la version « streaming » de
`routes/series.py::get_series_covers()` : au lieu d'attendre tous les scrapers puis de répondre
une fois, chaque scraper émet son propre événement `cover_stream_data` dès qu'il a fini
(`socketio.start_background_task` par scraper + `socketio.sleep(0)` pour forcer le flush réseau
immédiat sous Eventlet). Améliore nettement la perception de rapidité côté UI (les premières
couvertures apparaissent avant que les scrapers les plus lents aient répondu) au prix d'une
implémentation dupliquée avec la version HTTP.

---

## 6. `scrapers/` — fournisseurs de métadonnées externes

### `scrapers/base.py`
`BaseScraper` (ABC) : définit le contrat que tout scraper doit respecter — `id`, `display_name`,
`supported_types`, `rate_limit`, `proxy_domains`, `has_direct_id_support`, `requires_proxy`,
`needs_api_key`, `uses_unified_scoring` (opt-in Smart Scoring, `False` par défaut — voir
`CUSTOM_SCRAPERS.md` §4 et `_safe_match_score()` dans `metadata_fetcher.py`), `translations`, et
les méthodes `fetch()` (abstraite), `fetch_covers()` (optionnel, retourne `[]` par défaut) et
`extract_id_from_url()` (optionnel, retourne `None` par défaut).
`t()` est un helper i18n local qui lit `UI_LANG` depuis la config et retombe sur `fr` puis sur la
clé brute si la traduction est absente — chaque scraper peut ainsi logger dans la langue de
l'utilisateur sans dépendre de `translations.py` (dictionnaire séparé, à but différent : logs de
scraping bruts vs. libellés d'interface).

### `scrapers/__init__.py` (`ScraperRegistry`)
Singleton chargé une seule fois à l'import du package (`ScraperRegistry.load_all()` exécuté au
niveau module, en toute fin de fichier). Découvre automatiquement (1) tous les fichiers `.py` du
dossier `scrapers/` (sauf `__init__.py`, `base.py`, `utils.py`) via `importlib.import_module`, et
(2) tous les fichiers `.py` de `data/scrapers/` (créé automatiquement s'il n'existe pas) via
`importlib.util.spec_from_file_location` — c'est le mécanisme qui permet d'ajouter un scraper
personnalisé en déposant simplement un fichier, sans redémarrer autrement qu'en relançant le
conteneur. `_extract_scrapers()` utilise `inspect.getmembers` pour ne retenir que les classes qui
héritent de `BaseScraper` : seules les classes `BaseScraper` définies dans le module sont
enregistrées (les anciens `mal.py` / `nautiljon.py` à fonctions seules, désormais **supprimés
BF36**, n'auraient de toute façon jamais été découverts).

**Audit de l'auto-découverte (2 correctifs appliqués, voir `tests/test_scraper_registry.py`) :**
1. `inspect.getmembers(module, inspect.isclass)` remonte *toutes* les classes visibles dans
   l'espace de noms du module, y compris celles simplement **importées** — un cas d'usage
   pourtant encouragé par `CUSTOM_SCRAPERS.md` (hériter d'un scraper officiel via
   `from scrapers.mangabaka import MangaBakaScraper`). Sans filtre, la classe importée était
   ré-instanciée et ré-enregistrée comme si elle était définie dans le fichier custom, en plus
   de la sous-classe elle-même. `_extract_scrapers()` filtre désormais sur
   `obj.__module__ == module.__name__` pour ne garder que les classes réellement définies dans
   le module scanné.
2. `self._scrapers[instance.id] = instance` écrasait silencieusement toute entrée existante en
   cas de collision d'id (un scraper `data/scrapers/` réutilisant l'id d'un officiel, ou de deux
   scrapers custom entre eux), sans aucune trace dans les logs. Une collision loggue maintenant
   un `⚠️ [Registry] L'id de scraper '...' est remplacé par ...` — le remplacement reste
   *volontairement* autorisé (c'est le mécanisme officiel de surcharge d'un scraper, documenté
   dans `CUSTOM_SCRAPERS.md` section "Dupliquer / étendre un scraper officiel existant"), mais
   n'est plus silencieux.

Un exemple historique de duplication communautaire était `data/scrapers/mangabaka_book.py`
(non versionné) : hériter de `MangaBakaScraper` pour ajouter `Book` sous un id distinct. Depuis
v1.6, le scraper officiel `mangabaka.py` expose déjà `supported_types = {"Manga", "Book"}` —
ce genre de fork n’est plus nécessaire sauf besoin d’un id / UX séparés.

Note annexe découverte pendant cet audit (hors périmètre du Registre lui-même) :
`metadata_fetcher.py::run_cascade()` filtre les fournisseurs avec
`if library_type not in scraper.supported_types and "Manga" not in scraper.supported_types`.
Le second membre du `and` a pour effet de ne **jamais** exclure un scraper dont
`supported_types` contient `"Manga"`, quel que soit le type de bibliothèque réellement demandé.
En pratique l'impact est nul tant que l'UI ne propose que les scrapers pertinents par type
(`ScraperRegistry.get_by_type()`), mais un fournisseur "Manga" configuré manuellement (JSON,
webhook) comme fournisseur Book/Comic serait exécuté silencieusement, sans le log
`log_scraper_type_bypass` normalement émis lors d'un forçage explicite de type.

### `scrapers/utils.py`
Boîte à outils partagée par (quasiment) tous les scrapers modernes : `clean_title()` (nettoyage
de titre par type de bibliothèque — retrait de numéros de tome, éditions spéciales, extensions de
fichier...), `normalize_str()` / `calculate_similarity()` (comparaison de titres tolérante aux
accents/casse/ponctuation, avec bonus pour les sous-chaînes), `extract_volume_number()` /
`convert_roman_vol()` (gestion des tomes en chiffres romains), et surtout `score_candidate()` :
la matrice de décision centrale qui score chaque candidat trouvé par un scraper (0.0 à 1.0) en
combinant similarité de titre, similarité d'auteur, correspondance ISBN (règle d'or, score = 1.0
immédiat), pénalités anti-homonyme/spin-off/guidebook, et bonus tome/éditeur/année/genres. Toute
modification de cette fonction affecte silencieusement la précision de **tous** les scrapers qui
l'utilisent — un changement ici mérite systématiquement de repasser par `debug/debug_scoring.py`
(20 cas limites) avant d'être considéré comme sûr.

**✅ Homogénéisation (audit du 25/07).** Cette section affirmait que `score_candidate()` était
utilisée par tous les scrapers — c'était faux jusqu'au 25/07 : **MangaDex, MangaUpdates,
Manga-News et Shikimori implémentaient chacun leur propre heuristique titre-seul**
(`calculate_similarity()` + pénalité de mots-clés manquants), **sans aucune vérification
d'auteur**, donc sans la protection anti-homonyme (catégorie A) de la matrice centralisée.
`debug/debug_scoring.py` ne pouvait pas détecter ce genre de régression : il appelle
`score_candidate()` directement avec des candidats forgés à la main, jamais le vrai `fetch()`
d'un scraper. Les 4 ont été migrés pour construire un candidat complet (avec staff) et passer
par `score_candidate()` comme les 5 autres — l'affirmation est donc désormais vraie pour les
**9 scrapers manga/comic/book qui font du matching par recherche** (les autres, comme
`kitsu.py`, `bedetheque.py` ou `comicvine.py`, ont leur propre logique de scoring dédiée,
documentée individuellement dans le panorama ci-dessous). Le détail technique de chaque
migration (comment le staff a été obtenu sans exploser le nombre de requêtes réseau) est dans
`DEVELOPER.md` section 11.B ; la preuve que le staff produit est bien dans la forme attendue
par `score_candidate()` est dans `tests/test_scraper_score_migration.py`.

**Seuil d'acceptation centralisé.** Le seuil au-delà duquel un score est accepté était recopié
en dur dans chaque fichier et avait dérivé sans qu'aucun test ne s'en aperçoive : `0.50` pour
la plupart, `0.60` pour Hardcover/OpenLibrary, et même `0.45` pour Manga-News/Shikimori. `0.50`
(et a fortiori `0.45`) a été testé en usage réel et générait trop de faux positifs
(homonymes/spin-offs acceptés à tort) — `0.60` est la valeur validée par ce test. Elle est
désormais centralisée dans `scrapers/utils.py::MATCH_ACCEPT_THRESHOLD` et importée par les 9
scrapers concernés (`tests/test_scoring_threshold.py` garde cette cohérence), au lieu d'un
literal par fichier qui peut dériver silencieusement.

**Smart Scoring (audit du 26/07).** `score_candidate()` calculait un score interne
(`best_score`) dans chaque scraper, mais celui-ci était systématiquement jeté avant de retourner
le candidat — `metadata_fetcher.py` ne pouvait donc comparer les résultats de plusieurs providers
qu'en se fiant à l'ordre brut de la liste de fallback, jamais à la qualité réelle du match. Un
helper `attach_match_score(candidate, score)` a été ajouté et est désormais appelé sur *chaque*
`return` d'un candidat accepté dans les 9 scrapers concernés (y compris les résolutions par ID
direct, qui attachent `1.0`), sous la clé `_match_score` (`MATCH_SCORE_KEY`). Voir
`metadata_fetcher.py` ci-dessus et `DEVELOPER.md` §6.D pour l'utilisation de ce score
(sélection du vainqueur, ordre de complétion `SMART_COMPLETION`).

**Sécurité scrapers communautaires.** `BaseScraper.uses_unified_scoring` (`False` par défaut)
permet à un scraper custom d'annoncer sa participation au Smart Scoring, sans y être forcé.
Le pipeline ne filtre jamais dessus : `_safe_match_score()` dans `metadata_fetcher.py` coerce/
clamp toute valeur absente ou mal formée (`None`, str, bool, NaN…), ce qui empêche un scraper
`data/scrapers/` mal écrit de faire planter le tri. Documenté dans `CUSTOM_SCRAPERS.md` §4.

### Scrapers individuels — panorama

| Fichier | Type(s) | ID requis | Particularité notable |
|---|---|---|---|
| `anilist.py` | Manga/Comic/Book | non | GraphQL officiel, très complet (staff, personnages, liens externes) |
| `mangabaka.py` | Manga/Book | non | Rapide, gère `publisher_pref` (VF/VO), normalise le statut via `kavita_constants` |
| `mangadex.py` | Manga | non | Pénalise les "oneshot" non demandés (ajustement local post-`score_candidate()`) ; staff déjà inclus dans la réponse de recherche via `includes[]`, aucune requête HTTP supplémentaire nécessaire |
| `mangaupdates.py` | Manga | non | Gère `publisher_pref`, contourne Cloudflare via `curl_cffi` ; réutilise `_parse_series_record()` sur les résultats de recherche (même forme que le détail) pour obtenir le staff sans requête HTTP en plus |
| `kitsu.py` | Manga | non | JSON:API, matching par substring + ratio |
| `mal.py` | Manga/Book | **oui** (Client ID) | API officielle v2 (`X-MAL-CLIENT-ID` / `MAL_API_KEY`) ; remplace Jikan |
| `shikimori.py` | Manga | non | Pré-filtre par titre (gratuit) avant de déclencher `/roles` (3ᵉ requête HTTP, staff) uniquement sur les candidats plausibles, pour limiter le coût de `score_candidate()` |
| `manganews.py` | Manga | non | Scraping HTML (VF), contourne Cloudflare ; pré-filtre par titre puis récupère la fiche détaillée (staff) des 3 meilleurs candidats seulement, pour limiter la charge sur le site |
| `bedetheque.py` | Comic (franco-belge) | non | Scraping HTML avec jeton CSRF, gère variantes d'articles ("Le", "La"...) |
| `bdtheque.py` | Comic (franco-belge) | non | **bdtheque.com** (pas bedetheque) : AJAX `/ajax/search/series/`, parse fiche `/series/{id}/{slug}` |
| `comicvine.py` | Comic | **oui** | 4 passes de recherche en cascade (volume → sans sous-titre → `/search` → issue), bonus/malus éditeurs US majeurs |
| `googlebooks.py` | Book/Comic | non (clé optionnelle) | Recherche prioritaire par ISBN Kavita |
| `hardcover.py` | Book/Comic | **oui** | GraphQL, expérimental (le nom de la classe le dit explicitement) |
| `openlibrary.py` | Book/Comic | non | Gère le cas des couvertures "disclaimer Google Books" en repli vers l'API Google Books |

**`scrapers/nautiljon.py` a été supprimé (v1.6.0 / BF36)** (jamais un `BaseScraper` enregistré).
L’ancien stub Jikan `mal.py` a été retiré puis **réécrit en v1.6.1** comme vrai `BaseScraper`
(`id=MAL`, API officielle v2 + header `X-MAL-CLIENT-ID` / config `MAL_API_KEY` = Client ID).
Les IDs MAL restent aussi récupérés en croisement via AniList / MangaBaka / etc.

---

## 7. `templates/` — rendu HTML (Jinja2)

### `templates/index.html`
Le tableau de bord principal. Après le refactor, ce fichier ne contient plus que : le `<head>`
(styles, variables JS globales `window.ROOT_PATH`/`window.APP_VERSION`/`window.AppTranslations`),
la structure générale (`topbar`, `dashboard-body`), et une série d'`{% include %}` vers les
partials ci-dessous, plus le chargement ordonné des 7 fichiers JS. La variable
`window.AppTranslations` est notable : elle duplique manuellement dans le JS un sous-ensemble des
clés de `translations.py` nécessaires côté client — toute nouvelle chaîne utilisée en JS doit être
ajoutée à la fois dans `translations.py` **et** dans ce bloc, sans garde-fou automatique
aujourd'hui (oubli silencieux → texte `undefined` affiché côté client).

### `templates/partials/_sidebar.html`
Panneau latéral : statistiques (barre de progression), stratégie de scraping (cases à cocher
`Smart Completion`, `Reset Context`...), export d'erreurs, logs live (`#log-console`, alimenté par
`static/js/websocket.js`), pied de page. Contient plusieurs `onchange="saveConfig()"` inline
directement sur des cases à cocher — ces réglages sont donc sauvegardés immédiatement à chaque
clic, sans bouton de validation dédié (comportement volontaire, cohérent avec le reste de l'UI).

### `templates/partials/_toolbar.html`
Barre d'outils au-dessus de la liste des séries : recherche texte, sélecteur de bibliothèque
(déclenche `loadLibrary()`, un remplacement AJAX partiel de `.content` sans rechargement complet
de page), filtre de statut, case "tout sélectionner", et actions de masse (déplier/replier tous
les panneaux d'options, tout sauvegarder).

### `templates/partials/_series_row.html`
Une ligne de série, incluse dans une boucle Jinja pour chaque série. Contient le panneau d'options
replié par défaut (`override-panel`) avec : titre alternatif, le « champ magique » provider + ID/
URL, le sélecteur segmenté VF/VO/Auto pour l'éditeur, et un `<details>` avec 12 cases à cocher
(une par famille de champs ciblés). Toute nouvelle famille de champ ciblable côté
`services/enrichment_engine.py::active_fields` doit être répercutée ici (case à cocher) **et**
dans `static/js/overrides.js`/`static/js/batch.js` (liste `fields = [...]` dupliquée à deux
endroits côté JS) — 3 points de synchronisation manuelle au total pour un nouveau champ ciblable.

### `templates/partials/_config_modal.html`, `_cover_modal.html`, `_changelog_modal.html`
Non relus intégralement pour cette revue mais confirmés fonctionnellement lors du refactor :
respectivement la modale de configuration globale (connexion Kavita, providers par type,
traduction, clés API), la modale de recherche/sélection manuelle de couverture (grille alimentée
en streaming par `static/js/covers.js`), et la modale « Nouveautés » alimentée dynamiquement par
`/api/changelog` (`services/changelog_service.py`).

### `templates/login.html` / `templates/stats.html`
Pages autonomes simples, sans dépendance aux fichiers JS modulaires (elles n'en ont pas besoin :
pas d'interactivité complexe). `stats.html` recalcule les mêmes statistiques que
`_prepare_index_data()` dans `routes/pages.py` — léger doublon de logique (une requête SQLite de
plus), sans conséquence pratique vu le volume de données concerné (quelques centaines/milliers de
séries au grand maximum).

---

## 8. `static/` — frontend

### `static/js/utils.js`
Chargé en premier. `getRootPath()` (support sous-chemin, utilisé par **tous** les autres fichiers
JS pour construire leurs URLs `fetch`), `toggleTheme()`, `togglePasswordVisibility()`. Volontairement
minimaliste.

### `static/js/websocket.js`
Établit la connexion Socket.IO globale (`var socket`, portée globale intentionnelle car réutilisée
par `covers.js`). Gère l'affichage des logs live et un mécanisme de « surlignage » heuristique des
séries en cours de traitement : parse les messages de log avec des regex (`▶️ [Titre] Début`, `[Titre]
✅/⏭️/❌/⚠️`) pour mettre à jour visuellement le badge de statut d'une ligne de série *sans*
rechargement de page ni round-trip HTTP dédié. C'est un couplage implicite fort entre le format
des messages de log (`translations.py`) et ce parseur JS : renommer un émoji ou changer la
structure d'un message de log dans `services/enrichment_engine.py` casserait silencieusement ce
highlighting (aucun test ne couvre ce lien).

### `static/js/overrides.js`
Panneaux d'options par série : dépliage individuel/global, lien rapide de recherche AniList
(nouvel onglet), `saveOverride()` (un seul override) et `saveAllOverrides()` (parcourt tous les
panneaux actuellement dépliés et clique leur bouton de sauvegarde avec un délai de 250ms entre
chaque, pour ne pas envoyer les requêtes en rafale).

### `static/js/covers.js`
Modale de recherche de couverture. `triggerCoverStream()` préfère le WebSocket
(`fetch_covers_stream`, alimenté par `sockets/handlers.py`) et retombe sur l'appel HTTP classique
(`fetchCovers()`, `routes/series.py::get_series_covers`) si le socket est déconnecté — bonne
robustesse en cas de coupure réseau partielle ou de proxy qui bloquerait les WebSockets.
`applyCover()` envoie le choix final à `/api/series/<id>/update-cover`.

### `static/js/config.js`
Modale de configuration globale. `toggleTranslationFields()` affiche conditionnellement les champs
DeepL/Azure. `handleProviderChange()` implémente une logique de « cascade sans doublon » : si
l'utilisateur choisit un provider déjà utilisé dans un autre rang (1/2/3), l'autre rang est
automatiquement remis à `NONE`, et si le rang 1 se retrouve vide, il est automatiquement rempli
avec le premier provider disponible non utilisé ailleurs — évite qu'un utilisateur configure
involontairement le même provider deux fois dans la cascade.

### `static/js/batch.js`
Le plus long fichier JS (~350 lignes). Filtrage/recherche de la liste (avec persistance dans
`localStorage`), sélection multiple, synchronisation unitaire (`syncSingle`, qui sauvegarde
d'abord l'override du panneau visible avant de lancer la sync — évite qu'un changement non
sauvegardé soit ignoré par le traitement), synchronisation par lot avec découpage en tranches de
50 séries (`launchBatch`, pour éviter un unique payload HTTP démesuré), chargement dynamique de
bibliothèque sans rechargement de page (`loadLibrary`, remplace `.content` via `fetch` + parsing
DOM), et gestion « ignorer » unitaire/en masse.

### `static/js/main.js`
Chargé en dernier. Orchestration au chargement (restauration des filtres depuis `localStorage`,
chargement différé de la bibliothèque sauvegardée) et logique de la modale changelog
(`checkChangelogPopup`, compare `window.APP_VERSION` à `localStorage['last_seen_version']` pour
n'afficher la modale automatiquement qu'une fois par nouvelle version).

**Remarque générale sur les 7 fichiers JS** : ils sont chargés en balises `<script>` classiques
(pas de bundler, pas de `type="module"`), donc toutes les fonctions vivent en portée globale et
l'ordre de chargement dans `index.html` **est** la gestion de dépendances — c'était le choix
explicite validé avec vous en amont du refactor (« frontend simple sans bundler »). Le compromis
est documenté en commentaire en tête de chaque fichier (« dépend de X, doit être chargé après Y »),
mais rien ne le fait respecter automatiquement : une réorganisation malheureuse des balises
`<script>` dans `index.html` casserait silencieusement une fonctionnalité (erreur uniquement visible
dans la console navigateur).

### `static/css/style.css`
Non intégralement relu pour cette revue (fichier de style pur, sans logique). Utilise des
variables CSS (`--primary`, `--bg-input`, etc.) référencées abondamment par les templates et JS
inline, avec support d'un thème clair/sombre piloté par `data-theme` sur `<html>`.

---

## 9. `tests/` — suite pytest (nouvelle depuis le refactor)

### `tests/conftest.py`
4 fixtures : `isolated_db` (redirige `db_manager.DATA_DIR`/`DB_FILE` vers un fichier temporaire
via `monkeypatch`, garantissant qu'aucun test ne touche jamais `data/cache.db` réel),
`flask_app` (app Flask minimale n'enregistrant que `series_bp`, pas l'app complète — donc plus
rapide et sans dépendance à Kavita/Socket.IO), `client` (test client Flask standard), et
`mock_kavita_api` (patch `KavitaAPI` au niveau classe via `pytest-mock` pour éliminer tout appel
réseau réel pendant les tests).

### `tests/test_db_manager.py`
4 tests, tous centrés sur la non-régression du bug `publisher_pref` (aller-retour
`SeriesOverride` ↔ SQLite, wrapper rétro-compatible, préservation lors d'une mise à jour, valeur
par défaut `GLOBAL`).

### `tests/test_kavita_api.py`
Le fichier de test le plus dense : classe `TestUpdateSeriesGeneral` (5 tests couvrant le
protocole GET-avant-POST, la non-régression du `null` sur `localizedName`, la préservation des
verrous `name`/`sortName`, l'écriture explicite verrouillée, et le court-circuit no-op) et
`TestUpdateSeriesMetadata` (test paramétré sur les 6 clés système à assainir + protocole
unlock/re-lock + arrêt si le premier appel échoue). Couvre directement les deux bugs les plus
critiques corrigés dans `kavita_api.py`.

### `tests/test_scraper_mangabaka.py`
Teste `normalize_provider_status()` (valeurs connues paramétrées, valeur inconnue → `None`, valeur
vide → `None`) et `MangaBakaScraper._build_candidate()` (mapping `"completed"` → `"FINISHED"`,
statut inconnu → `None`). Directe non-régression du bug MangaBaka original.

### `tests/test_routes_series.py`
Test de bout en bout (route Flask réelle → `db_manager` → SQLite temporaire) : persistance de
`publisher_pref` via `/save-override`, valeur par défaut si omis, et bascule `/toggle-ignore`.

**Couverture actuelle** : la suite couvre bien les régressions historiques ciblées (c'était
l'objectif de la Phase 0 du refactor), et s'est étendue depuis à `metadata_fetcher.py` — throttling
(`tests/test_metadata_fetcher_throttle.py`) et Smart Scoring / exécution en deux vagues
(`tests/test_metadata_fetcher_smart_scoring.py`) — ainsi qu'aux courses de `config_manager.py`
(`tests/test_config_manager_concurrency.py`) et `services/enrichment_engine.py`
(`tests/test_enrichment_concurrency.py`). Il reste à couvrir l'orchestration complète
de `enrich_series()` de bout en bout (au-delà du seul verrou anti-course) ainsi que la quasi-totalité
des scrapers individuels (`scrapers/*.py`, hors MangaBaka/MangaDex/MangaUpdates/Manga-News/Shikimori).
C'est une base solide à étendre plutôt qu'une couverture exhaustive — cohérent avec l'objectif
initial (« suite de non-régression », pas « couverture à 100% »).

---

## 10. Scripts de debug (racine + `debug/`)

Ces scripts ne font pas partie du chemin d'exécution de l'application (aucun n'est importé par
`app.py` ou les modules de production) ; ce sont des outils manuels d'investigation, exécutés à la
main pendant le développement.

- **Racine** : `debug_cover.py` (upload manuel de couverture avec logs `DEBUG` complets),
  `debug_concurrency.py` (100% standalone, sans Flask/Eventlet/requests, simule un serveur Kavita
  en mémoire pour reproduire la race condition de couverture), `debug_publisher.py` (dump brut de
  la réponse `publishers` de MangaUpdates/MangaBaka), `debug_ultime.py` (dump des payloads
  Kavita réels envoyés/reçus).
- **`debug/`** : suite plus récente et structurée (tous préfixent `sys.path` avec le dossier
  parent pour pouvoir importer les modules racine) — `debug_all.py` (test toutes bibliothèques),
  `debug_scoring.py` (20 cas limites pour `score_candidate()`, le plus utile à relancer après
  toute modification de `scrapers/utils.py`), `debug_manga_quality.py`/`debug_comic_quality.py`/
  `debug_book_quality.py` (cas de test par type de bibliothèque), `debug_fusion.py`/
  `debug_cascade.py`/`debug_engine.py` (cascade et fusion multi-providers),
  `debug_comic.py`/`debug_comicvine.py` (spécifiques BD/Comics), `debug_deep.py` (métadonnées
  profondes Kavita),   `debug_custom.py` (test avec la vraie config Kavita de l'utilisateur),
  `debug_hardcover.py` (voir section 0 — contenait un secret réel, désormais révoqué et retiré du
  code, lit maintenant `HARDCOVER_API_KEY` depuis `data/config.json`/l'environnement).

Aucun de ces scripts n'est exécuté par la CI ni par `pytest` (`pytest.ini` restreint `testpaths`
à `tests/`) — ils cohabitent avec la suite pytest sans s'y substituer, ce qui est cohérent avec
leur usage (exploration manuelle rapide vs. non-régression automatisée). Recommandation : au
minimum déplacer les 4 scripts de la racine dans `debug/` par cohérence, et envisager un
`debug/README.md` d'une dizaine de lignes expliquant quand utiliser quel script (certains se
recoupent fonctionnellement, ex. `debug_deep.py`/`debug_custom.py`/`debug_ultime.py`).

---

## 11. Fichiers de configuration et de déploiement

- **`Dockerfile`** : image `python:3.11-slim`, installe `requirements.txt` (uniquement — pas
  `requirements-dev.txt`, donc `pytest` n'est jamais présent dans l'image de production, ce qui
  est le comportement voulu), démarre avec `gunicorn --worker-class eventlet -w 1`. Le `-w 1`
  n'est pas un détail : c'est une contrainte dure imposée par `sync_queue` (file en mémoire
  process) et le cache `_series_lib_type_cache` — documentée en section 3 ci-dessus.
- **`requirements.txt`** : dépendances de production (Flask, Flask-SocketIO, requests,
  beautifulsoup4, curl-cffi, gunicorn, eventlet, googletrans). Versions toutes épinglées
  strictement (`==`), bon réflexe pour la reproductibilité des builds.
- **`requirements-dev.txt`** : `-r requirements.txt` + `pytest`/`pytest-mock`, séparé
  intentionnellement pour ne pas alourdir l'image Docker de production.
- **`pytest.ini`** : `pythonpath = .` (le projet n'étant pas packagé avec un `setup.py`/
  `pyproject.toml`, cette ligne est nécessaire pour que `import db_manager` etc. fonctionnent
  depuis `tests/`), `testpaths = tests`.
- **`.gitignore`** : exclut `data/` (config, cache, logs générés), `config.json`,
  `docker-compose.yml` (l'utilisateur est censé avoir le sien avec ses propres secrets),
  `cache.db`, `*.log`, environnements virtuels, caches Python. **Ne couvre pas** les scripts de
  `debug/` contenant potentiellement des secrets collés à la main — c'est exactement ce qui a
  permis au jeton Hardcover de la section 0 de rester trackable.
- **`.github/workflows/tests.yml`** : exécute `pytest --verbose` sur chaque push/PR vers `main`
  (Python 3.11, cache pip). Bonne première ligne de défense automatisée contre les régressions
  couvertes par la suite actuelle.
- **`.github/workflows/docker-publish.yml`** : build multi-architecture (`amd64`/`arm64` via QEMU
  + Buildx) et publication sur `ghcr.io/raukorim-bot/metakavita:latest` à chaque push sur `main`.
  Point notable : ce workflow ne dépend pas du succès de `tests.yml` (pas de `needs:` ni de
  condition croisée entre les deux workflows) — une image pourrait donc théoriquement être publiée
  sur `:latest` même si la suite de tests vient d'échouer sur le même commit. À évaluer si vous
  voulez un vrai « gate » qualité avant publication.

---

## 12. Documentation

- **`README.md`** : présentation utilisateur (installation, fonctionnalités, configuration des
  providers).
- **`DEVELOPER.md`** : guide de contribution, mis à jour pendant cette série de sessions avec la
  section 12 (carte de l'architecture modulaire post-refactor) — le pendant « guide » de ce
  document-ci, qui est plutôt un « instantané d'audit ».
- **`ROADMAP.md`** : suivi des fonctionnalités prévues/retirées (mentionne notamment le retrait de
  Nautiljon du routage par défaut, cohérent avec l'observation de la section 6).
- **`CHANGELOG.md`** : historique des versions, parsé programmatiquement par
  `services/changelog_service.py` — la structure du fichier (titres `##`, listes `-`/`*`) est donc
  un contrat implicite avec ce module, pas seulement de la documentation libre.
- **`CUSTOM_SCRAPERS.md`** : guide pour écrire/générer un scraper personnalisé (`BaseScraper`,
  `needs_api_key`, `rate_limit`, `score_candidate`, `attach_match_score`,
  `uses_unified_scoring`, `proxy_domains`). Cohérent avec le mécanisme de
  `scrapers/__init__.py` décrit en section 6 et avec le Smart Scoring (§ `metadata_fetcher.py`).
- **`kavita_api.md`** : spécification technique de l'intégration Kavita (Lock Guard, protocole
  2 passages, DTOs, enums, règles d'assainissement) — le document de référence pour tout
  changement dans `kavita_api.py`. Sa cohérence avec le code réel de `kavita_api.py` a été
  vérifiée pendant cette revue et n'a rien révélé de contradictoire.

---

## 13. Synthèse et recommandations priorisées

1. **✅ Fait — Sécurité** : jeton Hardcover révoqué et retiré du code (section 0). Reste optionnel :
   purger l'historique git si ce fichier a déjà été poussé sur un dépôt distant.
2. **🟠 Court terme — Nettoyage** : ~~supprimer ou réécrire `scrapers/mal.py` et
   `scrapers/nautiljon.py`~~ **fait (BF36)** ; ~~documenter les `proxy_domains` CDN
   (Google Books / ComicVine)~~ **fait (BF43)** ; regrouper les
   scripts de debug de la racine dans `debug/`.
3. **🟡 Moyen terme — Dette technique légère** :
   - Faire migrer les scrapers restants (Kitsu, MangaDex, Shikimori, MangaUpdates) vers
     `kavita_constants.normalize_provider_status()` au lieu de leur mapping de statut inline,
     pour finir la centralisation commencée avec MangaBaka.
   - Ajouter un `needs:` entre `docker-publish.yml` et `tests.yml` si vous voulez empêcher la
     publication d'une image dont les tests ont échoué.
   - **✅ Fait** — `metadata_fetcher.py` est désormais couvert (throttle + Smart Scoring/exécution
     parallèle, voir `tests/test_metadata_fetcher_throttle.py` et
     `tests/test_metadata_fetcher_smart_scoring.py`). Reste à étendre `services/enrichment_engine.py`
     au-delà du seul verrou anti-course (détection de type, protection de couverture manuelle).
4. **🟢 Vigilance continue (pas d'action immédiate requise)** :
   - Le déploiement à worker unique (`-w 1`) reste la limite structurante de toute la couche
     asynchrone (files en mémoire, caches de classe). À garder en tête si le volume de séries ou
     d'utilisateurs simultanés grossit significativement.
   - Les 3 points de synchronisation manuelle pour tout nouveau « champ ciblable » (case à cocher
     HTML, tableau JS dupliqué en 2 endroits, liste Python dans `enrichment_engine.py`) sont un
     terrain fertile à oublis futurs, du même type que celui qui a causé le bug `publisher_pref`
     — sans être urgent, un futur ticket pourrait envisager de générer ces 3 points depuis une
     unique source de vérité (ex : une liste Python exportée aussi en JSON pour le template/JS).
