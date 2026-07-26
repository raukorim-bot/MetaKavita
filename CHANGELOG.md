## [1.6.0] - 2026-07-26 (Modular Architecture, Smart Scoring, CORS, MangaBaka Book, MAX_TAGS/MAX_GENRES & Audit Hardening)

EN
### 🏗️ Full Backend & Frontend Architecture Refactor
* **Backend Modularization**: Split the former monolithic `app.py` into `constants.py`/`models.py` (shared data contracts), `services/` (`enrichment_engine.py`, `background_tasks.py`, `changelog_service.py`), Flask Blueprints under `routes/` (`auth`, `pages`, `config`, `series`, `sync`, `misc`), and `sockets/handlers.py`. `app.py` is now a thin composition root with zero business logic.
* **Frontend Modularization (No Bundler)**: Split the former monolithic `script.js` into 7 plain `<script>` files loaded in dependency order (`utils.js` → `websocket.js` → `overrides.js` → `covers.js` → `config.js` → `batch.js` → `main.js`), and `index.html` into reusable Jinja partials. Removed the now-fully-superseded legacy `static/js/script.js` file left over from the migration.
* **`SeriesOverride` Dataclass (`models.py`)**: Replaced long positional-argument persistence calls with an explicit, named-field dataclass to make any forgotten field immediately visible at the call site — the exact class of bug that had silently dropped the per-series Publisher Preference in earlier versions.
* **Non-Regression Test Suite**: Introduced a full `pytest` suite (`tests/`, `pytest.ini`, `requirements-dev.txt`, `tests/conftest.py`) with isolated SQLite/Flask/Kavita-mock fixtures, covering every historically-fixed critical bug plus all new fixes below. Added a GitHub Actions workflow (`.github/workflows/tests.yml`) to run it automatically on every push/PR.

### 🧠 Smart Scoring: Score-Based Provider Selection & Parallel Execution
* **UI Toggle (`SMART_SCORING`)**: Smart Scoring can be enabled/disabled from the scraping options sidebar (same block as Smart Completion). On = best match wins + two-wave parallel execution. Off = classic sequential fallback in provider list order.
* **Score-Based Winner Selection (`metadata_fetcher.py`, `scrapers/*.py`)**: The provider fallback cascade used to blindly keep whichever configured provider happened to be **first** in the user's priority list (`PROVIDER_1/2/3`) as the winner, even when a later provider had an objectively better match for that query — every provider was already being queried (there was never an early exit), the result was just discarded. Added `attach_match_score()` (`scrapers/utils.py`) so all 9 search-based scrapers now attach their own `score_candidate()` result to the returned candidate (direct ID/URL lookups attach `1.0`, having no ambiguity to score). `fetch_metadata()` now compares every accepted candidate's score and keeps the best one, ties broken by fallback-list position. When `SMART_COMPLETION` is enabled, gap-filling now follows this same score-descending order instead of the raw list order.
* **Two-Wave Parallel Execution**: Provider #1 still runs alone and sequentially first — its ISBN/authors are merged into `existing_metadata` for the anti-homonym protection to benefit later providers, which then all run **in parallel** (`ThreadPoolExecutor`) against a frozen snapshot of that enriched context, instead of one after another. Since the call volume is unchanged, this is a pure latency win (closer to the slowest single provider than to the sum of all of them) plus a match-quality win. Per-provider rate-limiting remains safe (already keyed by `scraper.id` with its own lock).
* Added `tests/test_metadata_fetcher_smart_scoring.py`, including a timing assertion proving providers after the first genuinely overlap in wall-clock time.
* **Community-Scraper Safety (`BaseScraper.uses_unified_scoring`, `_safe_match_score`)**: Added an opt-in class flag (`uses_unified_scoring = False` by default) so community scrapers can declare participation in Smart Scoring without being forced to. The pipeline never gates on this flag — instead `_safe_match_score()` coerces/clamps any missing or malformed `_match_score` (`None`, string, bool, NaN…) so a badly written community scraper can no longer crash enrichment. Documented in `CUSTOM_SCRAPERS.md`.

### 🧵 Concurrency & Race Condition Hardening
* **Per-Series Processing Lock (`services/enrichment_engine.py`)**: `enrich_series()` has two independent entry points that could run truly in parallel for the *same* series — the "Sync" button (`routes/sync.py::force_sync`, synchronous, outside the queue) and the background worker consuming the batch/webhook queue. A manual sync racing against a webhook for the same series could cause a lost update (including the cover). Added an in-memory per-`series_id` lock that immediately rejects concurrent processing of the same series instead of racing.
* **Config Lost-Update Race (`config_manager.py`, `routes/config.py`)**: `load_config()`/`save_config()` read/rewrote the entire `config.json` with no locking. Two overlapping settings saves (e.g. toggling two sidebar checkboxes in quick succession, each firing its own independent `/save-config` request) could silently drop one of the two changes. Added a re-entrant `CONFIG_LOCK` spanning the full read-modify-write cycle in both routes.
* **Scraper Rate-Limiter Race (`metadata_fetcher.py`)**: `throttle_provider()`'s check-then-sleep-then-update sequence on the shared `LAST_REQUEST_TIMES` dict was not atomic — two concurrent enrichments hitting the same provider (e.g. a manual "Sync" alongside a queued batch item) could both decide no wait was needed and fire near-simultaneously, risking provider rate-limit bans. Added a per-scraper lock making the whole cycle atomic without penalizing unrelated providers.

### 🦸 Scraper Auto-Discovery Audit & Scoring Unification
* **Registry Re-Registration Bug (`scrapers/__init__.py`)**: `_ScraperRegistry._extract_scrapers()` used `inspect.getmembers()`, which also picked up classes merely *imported* into a scraper file (e.g. a community scraper subclassing an official one) and re-registered them as if freshly defined. Now filters by `obj.__module__ == module.__name__` to only register classes actually defined in that module.
* **Silent Scraper ID Collisions**: Two scrapers claiming the same `id` used to silently overwrite one another in the registry. Now logs an explicit warning so accidental collisions are diagnosable.
* **Community Scraper Extension Example (`data/scrapers/mangabaka_book.py`)**: Added a documented inheritance example (subclassing `MangaBakaScraper` under a distinct id). Kept as a pedagogical sideload sample — official MangaBaka now ships Book/LN support natively (see below).
* **Centralized Match Acceptance Threshold (`scrapers/utils.py::MATCH_ACCEPT_THRESHOLD`)**: The score a candidate needs to be accepted used to be a literal duplicated in every scraper file — `0.50` for most, `0.60` for Hardcover/OpenLibrary, and even `0.45` for Manga-News/Shikimori. Real-world usage showed `0.50` (and `0.45` a fortiori) produced too many false positives (homonyms, spin-offs). Centralized to a single validated `0.60` constant imported by all 9 search-based scrapers.
* **4 Scrapers Migrated to the Unified Scoring Matrix**: `mangadex.py`, `mangaupdates.py`, `manganews.py`, and `shikimori.py` used to implement their own title-only similarity heuristic with **no author cross-check at all**, meaning the anti-homonym protection never applied to them. Each now builds a full candidate (including staff) and scores it through `score_candidate()`, like the other 5 scrapers — with per-scraper strategies to avoid extra HTTP calls (reusing search-result fields where possible, or bounding expensive detail fetches to the top few pre-filtered candidates).
* **MangaBaka API Hardening + Official Book/LN Support (thanks LazyGeniusMan)**: Search/direct fetch now request `schema=full`, pass MangaBaka `type` filters (`novel` for Book, manga/manhwa/manhua for Manga), parse unified `is_genre` tags, prefer `my_anime_list` source ids, and normalize link objects to URL strings. Official `supported_types` is now `{"Manga", "Book"}`.

### 🔐 CORS Allowed Origins (Docker)
* **`CORS_ALLOWED_ORIGINS`**: Comma-separated explicit origins (e.g. `https://metakavita.home.local.ltd`) applied to Flask HTTP and Socket.IO. Empty = Same-Origin only. `*` is rejected. Enables self-host HTTPS domains that were blocked by the previous Same-Origin Socket.IO setup. Does not replace reverse-proxy WebSocket upgrade configuration.
* **`KAVITA_EXTERNAL_URL` (thanks LazyGeniusMan)**: Optional public Kavita URL for browser UI links (series title → Kavita). `KAVITA_URL` remains the server-side API endpoint (e.g. `http://kavita:5000` on the Docker network). If external is empty, UI links fall back to `KAVITA_URL`.
* **`KAVITA_HTTP_TIMEOUT` + 2-pass soft-success (issue SqueezedByte)**: Kavita write timeout is now configurable via env/config (default **60s**, was hard-coded 35s). If metadata/general **write** succeeds but **RE-LOCK** times out or returns non-200, MetaKavita treats the update as success with a warning — avoiding false "Kavita refused the update" failures when data was already persisted. One lightweight **RE-LOCK-only retry** (0.5s pause, retry timeout capped at **20s**) tries to seal field locks without re-scraping or re-writing.
* **`debug/benchmark_batch.py`**: CLI wall-clock benchmark for a sequential force-batch with all heavy options forced on (Smart Scoring / Completion / title fallback / reset-on-force / auto-cover). Dry-run by default; `--live --i-know` for real Kavita writes.
* **`MAX_TAGS` (feedback LazyGeniusMan)**: Configurable cap on tags pushed to Kavita (env / `config.json`, default **15**, range 1–100). Applied in `enrichment_engine` and all official scrapers that previously hard-coded `[:15]`. No UI — advanced/power-user setting only. Documented for community scrapers in `CUSTOM_SCRAPERS.md` (`get_max_tags()`).
* **`MAX_GENRES`**: Configurable cap on genres pushed to Kavita (env / `config.json`, default **5**, range 1–50). Homogenized across dynamic-list scrapers + `enrichment_engine` safety net (`get_max_genres(config)`). No UI — see BF41.

### 🛡️ Application Code Audit Hardening
Full static audit of application code (routes, services, scrapers, Kavita API, frontend — excluding tests/docs/debug). Critical and High findings fixed in this release; optional empty `ADMIN_PASSWORD` (open LAN backoffice) is **intentional** and left unchanged.

* **BF20. External IDs Partial `Series/update` Corruption**: `update_series_external_ids()` used to POST only `id` + AniList/MAL/MangaBaka IDs. Same Kavita quirk as the historical `localizedName` wipe — omitted fields can null alt titles and reset name locks. Now GET-snapshots the series and reinjects `name` / `sortName` / `localizedName` / locks / existing external IDs before overlaying new ones. Invalid non-numeric IDs are skipped (no crash).
* **BF21. Cover Upload SSRF Allowlist**: Manual/auto cover download now validates `http(s)` only, rejects credentials/localhost/link-local, requires a `proxy_domains` allowlist match, and refuses HTTP redirects (`allow_redirects=False`). Soft-fail with a clear message — never crashes enrichment.
* **BF22. Forced-ID `fallback_query` Was Dead**: `enrich_series` passed `fallback_query` (alt title / series name) but `fetch_metadata` never used it. After a failed forced ID/URL pass, MetaKavita now retries a title search automatically.
* **BF23. Comic/Book Provider Config Load/Save Asymmetry**: `COMIC_PROVIDER_*`, `BOOK_PROVIDER_*`, and `RESET_CONTEXT_ON_FORCE` were saved from the UI but missing from `load_config()` defaults and env override loops — Docker env for comic/book cascades and reset-on-force was ignored. Defaults + env wiring restored.
* **BF24. Cover Modal DOM XSS**: HTTP and Socket cover UIs interpolated remote `title` / `display_url` into `innerHTML`. Rebuilt with DOM APIs (`createElement` / `textContent`) so provider metadata cannot inject script into the admin session.
* **BF25. `/api/proxy-image` Redirect SSRF**: Proxy already had a domain allowlist but followed redirects by default and echoed upstream Content-Type. Now uses the shared allowlist helper, blocks redirects, and only serves safe `image/*` MIME types.
* **BF26. Silent `update_series_general` Failure**: Metadata success alone marked the series `COMPLETED` even when alt title / format write failed. General update result is now checked; partial failure is reported instead of a false success.
* **BF27. Characters Mapping Crash**: Enrichment assumed AniList GraphQL shape `c['node']['name']['full']` and could `KeyError` on custom/malformed character lists. Parsing is now defensive (dict/string variants; bad entries skipped).
* **C50. CSRF Protection + Session Cookie Hardening**: Session CSRF token (`csrf_utils.py`) validated on state-changing POSTs (header `X-CSRF-Token` or form field); frontend `utils.js` injects the header on all mutating `fetch` calls; login form includes a hidden token. Session cookie uses `SameSite=Lax` + `HttpOnly` (optional `SESSION_COOKIE_SECURE=1` behind HTTPS). Webhook remains token-auth exempt; pytest `TESTING` skips CSRF.
* **BF28. Changelog Modal Truncated by Unescaped `<script>`**: The Markdown→HTML renderer injected CHANGELOG text (e.g. `` `<script>` `` in the frontend modularization notes) into `innerHTML` without escaping. Browsers treated that as a real script tag and discarded the rest of the modal. Text is now HTML-escaped before inline Markdown formatting.

### 🛠️ Medium Audit Hardening
* **BF29. Unified Scoring for Kitsu / ComicVine / Bédéthèque**: These scrapers lacked `attach_match_score` / `uses_unified_scoring`, so Smart Scoring treated them as neutral `0.60`. They now use `score_candidate` + threshold like the other official scrapers.
* **BF30. `localizedName` Read from Wrong Kavita DTO**: `get_series_deep_metadata()` looked for `localizedName` on Series/metadata; it lives on `GET /api/Series/{id}`. Scoring now receives the real alt title when present.
* **BF31. Frontend Fetch Error Handling**: `syncSingle` / `proceedSyncSingle` / `saveConfig` / `applyCover` now check `res.ok` and restore UI on network/HTTP failure (no stuck spinners; override save must succeed before force-sync).
* **BF32. Sync Queue `task_done()`**: Background `_worker` now calls `task_done()` after each job so `unfinished_tasks` stays accurate (aligned with `stop_batch`).
* **BF33. Scraper HTTP Session Cleanup**: `bedetheque` / `manganews` / `hardcover` close their `Session` in `finally` after fetch/covers.
* **BF34. Corrupt `config.json` No Longer Silently Overwritten**: Parse failure logs loudly, optionally renames to `config.json.bak`, and skips auto-`save_config` that would wipe the broken file with defaults.
* **BF35. `TARGET_LANG` No Longer Forced Every Enrich**: Language is written only when Kavita has no language yet, or on `force_update` (still used for summary translation independently).
* **BF36. Dead MAL / Nautiljon Modules Removed**: Non-`BaseScraper` leftovers never registered by the registry; deleted.

### 🧹 Low Audit Polish
* **BF37. No Hardcoded `SECRET_KEY` Fallback**: Removed public `'kavita-secret-key'` default in `app.py`. If `SECRET_KEY` is still empty after `load_config()`, an ephemeral key is generated and an error is logged (sessions won't survive restart until `config.json` is fixed). Also fixed missing `import logging` in `config_manager.py`.
* **BF38. API Key Prefix No Longer Logged**: Kavita auth debug log no longer prints `api_key[:5]`.
* **BF39. Smart Scoring Double-Absorb Documented**: Wave-1 `absorb_candidate` before parallel wave-2 is intentional (context snapshot); final `apply_accepted` re-absorbs — comment added, behavior unchanged.
* **BF40. ComicVine `proxy_domains` Narrowed**: Dropped broad `gamespot.com`; keep `comicvine.gamespot.com` only.
* **BF41. `MAX_GENRES` / `get_max_genres()`**: Configurable genre cap (env / `config.json`, default **5**, range 1–50). Applied in scrapers with dynamic genre lists (Shikimori, Manga-News, MangaUpdates, Hardcover, OpenLibrary, AniList, MangaBaka, GoogleBooks, Bédéthèque) and as a safety net in `enrichment_engine` (`get_max_genres(config)`), mirroring `MAX_TAGS`. OpenLibrary build loop no longer hard-codes `5`. AniList tags now use `get_max_tags()`; MangaUpdates dropped the hard-coded `categories[:10]` so `MAX_TAGS` can take full effect. No UI.

### 🧭 Topbar Help Menu (About & Documentation)
* **C52. Help / About / Docs Dropdown**: Topbar Help menu (next to support links): in-app **About** modal (version, short blurb, GitHub / Issues / BMC), **Documentation** links to GitHub (`README`, `CUSTOM_SCRAPERS`, `DEVELOPER`, `ROADMAP` on `dev`), and **Release notes** reusing the changelog modal.
* **C52b. Kavita+ Support Positioning**: About modal encourages supporting Kavita first (Kavita+ / donations / Open Collective). Topbar shows **Kavita+** beside Buy me a coffee (equal visual weight). Kavita+ button opens this instance’s admin settings (`get_kavita_plus_url()` → `{KAVITA_EXTERNAL_URL|KAVITA_URL}/settings#admin-kavitaplus`, wiki fallback if unset).

### 🔧 Post-Audit Follow-ups
* **BF42. Credential-Safe Exception Logging**: Added `secure_logging.safe_exc_str` / `redact_secrets`. Kavita auth and ComicVine search errors no longer log raw `str(e)` (which could embed `?apiKey=` / `?api_key=` in urllib3 messages, including Live Logs).
* **BF43. Safe Cover Redirects + CDN Domains**: Cover upload and `/api/proxy-image` follow up to 3 redirects with each hop re-validated via `fetch_with_safe_redirects` (**supersedes** the strict “block all redirects” policy from BF21/BF25). Extended `proxy_domains` for Google Books (`googleusercontent.com`), MangaBaka (`api.mangabaka.org`), ComicVine (`static.comicvine.com`).
* **BF44. Block Private IPs in URL Allowlist**: `url_allowlist` now rejects RFC1918 / loopback / link-local / reserved literal IPs and `.local`/`.internal` suffixes (in addition to localhost / metadata).
* **BF45. Escape Closes Changelog**: Topbar Help Escape handler also closes the changelog modal.
* **Docs**: `CODE_REVIEW.md` updated — MAL/Nautiljon marked removed (BF36), not “dead files still present”.

### 🐛 Manual Cover vs. Auto-Cover Conflict Fixes
* **Per-Series Publisher Preference Persistence (`routes/series.py`)**: Fixed an issue where the `/save-override` endpoint failed to forward `publisher_pref` to persistence, which previously reset per-series choices back to `GLOBAL` in `cache.db`.
* **Stale Targeted-Fields Checkbox (`static/js/covers.js`)**: Applying a manual cover correctly unlocks it server-side (removes `cover` from `targeted_fields`), but the per-series "Cover" checkbox in the UI kept its stale checked state from page load. Clicking "Sync" or "Save" on that same series before a page reload would silently re-lock `cover` back into `targeted_fields`, undoing the protection and exposing the manual cover to being overwritten again. The checkbox is now unchecked immediately on a successful manual cover apply.
* **Manual Cover Silently Un-Ignoring / Re-Opening Series (`routes/series.py::apply_series_cover`)**: The cover-protection save reused `save_series_override()`, which *always* forces `status` back to `PENDING` (the correct behavior for the regular "Save Override" form, where the user is providing a better search hint). Reused verbatim for a cover-only change, this silently un-ignored `IGNORED` series (re-queuing them on the next auto-sync) and reset `COMPLETED`/`NOT_FOUND` series back to `PENDING`, skewing the dashboard stats. The original status is now explicitly restored right after.
* **Targeted-Fields Checkbox Substring Match (`templates/partials/_series_row.html`)**: Checkbox state was computed with `'field' in tf` on the raw comma-joined string — a substring test, not list membership. Harmless today (no current field name is a substring of another) but a latent trap for future field names. Now explicitly split into a real list before testing membership.

### 🔒 Security
* **Hardcoded Hardcover API Token Removed (`debug/debug_hardcover.py`)**: A live bearer token was committed directly into a debug script. Replaced with loading the key from the standard configuration system; the token was revoked and purged from the git history.
* **Cover SSRF / Proxy Hardening**: See BF21 / BF25 (initial allowlist) and BF43 / BF44 (`fetch_with_safe_redirects`, private IP block) — `url_allowlist.py`, cover upload + `/api/proxy-image`.
* **Cover UI XSS Hardening**: See BF24 (`static/js/covers.js`).
* **CSRF + Cookie Flags**: See C50 (`csrf_utils.py`, `utils.js`, `SameSite=Lax`).
* **Credential-safe exception logs**: See BF42 (`secure_logging.py`).

FR
### 🏗️ Refonte Complète de l'Architecture Backend & Frontend
* **Modularisation Backend**: Découpage de l'ancien `app.py` monolithique en `constants.py`/`models.py` (contrats de données partagés), `services/` (`enrichment_engine.py`, `background_tasks.py`, `changelog_service.py`), Blueprints Flask dans `routes/` (`auth`, `pages`, `config`, `series`, `sync`, `misc`) et `sockets/handlers.py`. `app.py` n'est plus qu'un point d'assemblage sans logique métier.
* **Modularisation Frontend (Sans Bundler)**: Découpage de l'ancien `script.js` monolithique en 7 fichiers `<script>` classiques chargés dans l'ordre de dépendance (`utils.js` → `websocket.js` → `overrides.js` → `covers.js` → `config.js` → `batch.js` → `main.js`), et de `index.html` en partials Jinja réutilisables. Suppression du fichier `static/js/script.js` devenu obsolète après la migration.
* **Dataclass `SeriesOverride` (`models.py`)** : Remplacement des appels de persistance à arguments positionnels par une dataclass explicite à champs nommés, rendant immédiatement visible tout champ oublié — exactement la classe de bug qui avait fait disparaître silencieusement la préférence d'éditeur par série dans une version antérieure.
* **Suite de Tests de Non-Régression** : Mise en place d'une suite `pytest` complète (`tests/`, `pytest.ini`, `requirements-dev.txt`, `tests/conftest.py`) avec fixtures isolées (SQLite temporaire, Flask minimal, mocks Kavita), couvrant tous les bugs critiques historiques ainsi que tous les correctifs ci-dessous. Ajout d'un workflow GitHub Actions (`.github/workflows/tests.yml`) pour l'exécuter automatiquement à chaque push/PR.

### 🧠 Smart Scoring : Sélection des Fournisseurs par Score & Exécution Parallèle
* **Interrupteur UI (`SMART_SCORING`)** : le Smart Scoring s'active/désactive depuis la sidebar Options de Scraping (même bloc que la Complétion intelligente). Activé = meilleur match + exécution en deux vagues. Désactivé = fallback classique séquentiel dans l'ordre de la liste.
* **Sélection du Vainqueur par Score (`metadata_fetcher.py`, `scrapers/*.py`)** : la cascade de fournisseurs retenait aveuglément comme vainqueur celui qui se trouvait **en premier** dans la liste de priorité de l'utilisateur (`PROVIDER_1/2/3`), même si un fournisseur suivant avait objectivement un meilleur match pour cette requête — tous les fournisseurs étaient déjà interrogés (aucune sortie anticipée n'a jamais existé), le résultat était simplement jeté. Ajout de `attach_match_score()` (`scrapers/utils.py`) pour que les 9 scrapers basés sur une recherche attachent désormais leur propre résultat de `score_candidate()` au candidat retourné (les résolutions directes par ID/URL attachent `1.0`, n'ayant par nature aucune ambiguïté à scorer). `fetch_metadata()` compare maintenant le score de chaque candidat accepté et retient le meilleur, l'égalité étant départagée par la position dans la liste de fallback. Quand `SMART_COMPLETION` est activé, le remplissage des champs manquants suit désormais ce même ordre décroissant par score plutôt que l'ordre brut de la liste.
* **Exécution en Deux Vagues Parallèles** : le fournisseur #1 tourne toujours seul et en premier, séquentiellement — son ISBN/ses auteurs sont fusionnés dans `existing_metadata` pour que la protection anti-homonyme en profite pour les fournisseurs suivants, qui tournent ensuite tous **en parallèle** (`ThreadPoolExecutor`) contre un instantané figé de ce contexte enrichi, au lieu de s'exécuter l'un après l'autre. Le volume d'appels étant inchangé, c'est un gain de latence pur (proche du fournisseur le plus lent plutôt que de la somme de tous) ainsi qu'un gain de qualité de matching. Le rate-limiting par fournisseur reste sûr (déjà indexé par `scraper.id` avec son propre verrou).
* Ajout de `tests/test_metadata_fetcher_smart_scoring.py`, incluant une assertion de timing prouvant que les fournisseurs après le premier se recouvrent bien réellement dans le temps.
* **Sécurité Scrapers Communautaires (`BaseScraper.uses_unified_scoring`, `_safe_match_score`)** : ajout d'un drapeau de classe opt-in (`uses_unified_scoring = False` par défaut) pour que les scrapers communautaires puissent déclarer leur participation au Smart Scoring sans y être forcés. Le pipeline ne bloque jamais sur ce drapeau — `_safe_match_score()` coerce/clamp toute valeur `_match_score` absente ou mal formée (`None`, chaîne, booléen, NaN…) pour qu'un scraper communautaire mal écrit ne puisse plus faire planter l'enrichissement. Documenté dans `CUSTOM_SCRAPERS.md`.

### 🧵 Fiabilisation contre les Races Conditions
* **Verrou par Série (`services/enrichment_engine.py`)** : `enrich_series()` avait deux points d'entrée indépendants pouvant s'exécuter en parallèle sur LA MÊME série — le bouton "Sync" (`routes/sync.py::force_sync`, synchrone, hors file) et le worker de fond consommant la file de batch/webhook. Un Sync manuel en concurrence avec un webhook pour cette série pouvait causer une perte de mise à jour (couverture y compris). Ajout d'un verrou en mémoire par `series_id` qui rejette immédiatement tout traitement concurrent de la même série.
* **Course "Lost Update" sur la Configuration (`config_manager.py`, `routes/config.py`)** : `load_config()`/`save_config()` relisaient/réécrivaient tout `config.json` sans aucun verrou. Deux sauvegardes de réglages qui se chevauchent (ex: deux cases à cocher changées coup sur coup, chacune déclenchant sa propre requête `/save-config`) pouvaient faire disparaître silencieusement l'un des deux changements. Ajout d'un `CONFIG_LOCK` ré-entrant englobant tout le cycle lire-modifier-écrire dans les deux routes concernées.
* **Course sur le Rate-Limiter des Scrapers (`metadata_fetcher.py`)** : la séquence lire-puis-dormir-puis-écrire de `throttle_provider()` sur le dict partagé `LAST_REQUEST_TIMES` n'était pas atomique — deux enrichissements concurrents visant le même fournisseur (ex: un "Sync" manuel en même temps qu'un item de batch) pouvaient tous les deux juger qu'aucune attente n'était nécessaire et partir presque simultanément, au risque d'un bannissement côté fournisseur. Ajout d'un verrou par scraper rendant tout le cycle atomique sans pénaliser les fournisseurs indépendants entre eux.

### 🦸 Audit de l'Auto-Découverte des Scrapers & Unification du Scoring
* **Bug de Ré-enregistrement dans le Registre (`scrapers/__init__.py`)** : `_ScraperRegistry._extract_scrapers()` utilisait `inspect.getmembers()`, qui remontait aussi les classes simplement *importées* dans un fichier de scraper (ex: un scraper communautaire héritant d'un scraper officiel) et les ré-enregistrait comme si elles y étaient définies. Filtre désormais sur `obj.__module__ == module.__name__` pour n'enregistrer que les classes réellement définies dans ce module.
* **Collisions d'ID Silencieuses** : deux scrapers revendiquant le même `id` s'écrasaient silencieusement l'un l'autre dans le registre. Un avertissement explicite est désormais loggué pour rendre ces collisions diagnosticables.
* **Exemple d'Extension de Scraper Communautaire (`data/scrapers/mangabaka_book.py`)** : Exemple documenté d'héritage (sous-classe de `MangaBakaScraper` sous un id distinct). Conservé comme modèle pédagogique — MangaBaka officiel couvre désormais Book/LN nativement (voir ci-dessous).
* **Seuil d'Acceptation Centralisé (`scrapers/utils.py::MATCH_ACCEPT_THRESHOLD`)** : le score minimal pour accepter un candidat était recopié en dur dans chaque fichier — `0.50` pour la plupart, `0.60` pour Hardcover/OpenLibrary, et même `0.45` pour Manga-News/Shikimori. L'usage réel a montré que `0.50` (et a fortiori `0.45`) générait trop de faux positifs (homonymes, spin-offs). Centralisé en une constante unique validée à `0.60`, importée par les 9 scrapers concernés.
* **4 Scrapers Migrés vers la Matrice de Scoring Unifiée** : `mangadex.py`, `mangaupdates.py`, `manganews.py` et `shikimori.py` implémentaient chacun leur propre heuristique de similarité de titre, **sans aucune vérification d'auteur**, désactivant de fait la protection anti-homonyme pour eux. Chacun construit désormais un candidat complet (avec staff) et le passe par `score_candidate()`, comme les 5 autres — avec une stratégie propre à chacun pour éviter les appels HTTP supplémentaires.
* **Durcissement API MangaBaka + Support Book/LN Officiel (merci LazyGeniusMan)** : requêtes avec `schema=full`, filtre `type` MangaBaka (`novel` pour Book), parsing des tags `is_genre`, ids MAL via `my_anime_list`, et liens normalisés en URLs. `supported_types` officiel = `{"Manga", "Book"}`.

### 🔐 Origins CORS autorisées (Docker)
* **`CORS_ALLOWED_ORIGINS`** : origins explicites séparées par des virgules (ex: `https://metakavita.home.local.ltd`), appliquées à Flask HTTP et Socket.IO. Vide = Same-Origin uniquement. `*` est rejeté. Débloque les self-hosts HTTPS dont les sockets étaient bloqués par le Same-Origin. Ne remplace pas la config reverse-proxy d'upgrade WebSocket.
* **`KAVITA_EXTERNAL_URL` (merci LazyGeniusMan)** : URL publique optionnelle de Kavita pour les liens UI (titre de série → Kavita). `KAVITA_URL` reste l'endpoint API serveur (ex: `http://kavita:5000` sur le réseau Docker). Si l'URL externe est vide, les liens UI se rabattent sur `KAVITA_URL`.
* **`KAVITA_HTTP_TIMEOUT` + soft-success 2-pass (issue SqueezedByte)** : timeout d'écriture Kavita configurable (défaut **60s**, était 35s en dur). Si l'écriture metadata/général réussit mais le **RE-LOCK** timeout ou renvoie non-200, MetaKavita compte un succès avec warning — plus de faux "Kavita refused" quand les données sont déjà persistées. Un **retry léger du seul RE-LOCK** (pause 0,5s, timeout retry plafonné à **20s**) tente de sceller les verrous sans re-scrape ni re-écriture.
* **`debug/benchmark_batch.py`** : benchmark wall-clock d'un force-batch séquentiel avec options lourdes forcées (Smart Scoring / Completion / title fallback / reset-on-force / auto-cover). Dry-run par défaut ; `--live --i-know` pour écritures Kavita réelles.
* **`MAX_TAGS` (retour LazyGeniusMan)** : plafond configurable des tags poussés vers Kavita (env / `config.json`, défaut **15**, borné 1–100). Appliqué dans `enrichment_engine` et tous les scrapers officiels qui hard-codaient `[:15]`. Pas d'UI — réglage avancé uniquement. Documenté pour les scrapers communautaires dans `CUSTOM_SCRAPERS.md` (`get_max_tags()`).
* **`MAX_GENRES`** : plafond configurable des genres poussés vers Kavita (env / `config.json`, défaut **5**, borné 1–50). Homogénéisé sur les scrapers à listes dynamiques + filet `enrichment_engine` (`get_max_genres(config)`). Pas d'UI — voir BF41.

### 🛡️ Durcissement suite à l'Audit du Code Applicatif
Audit statique complet du code applicatif (routes, services, scrapers, API Kavita, frontend — hors tests/docs/debug). Findings Critical et High corrigés dans cette version ; le `ADMIN_PASSWORD` vide (backoffice LAN ouvert) reste un **choix volontaire** et n'a pas été modifié.

* **BF20. Corruption via POST partiel des IDs externes** : `update_series_external_ids()` n'envoyait que `id` + IDs AniList/MAL/MangaBaka. Même piège Kavita que l'ancien wipe de `localizedName` — les champs omis peuvent nullifier les titres alt et déverrouiller name/sortName. Snapshot GET + réinjection des champs/verrous/IDs existants avant overlay. IDs non numériques ignorés (pas de crash).
* **BF21. SSRF à l'upload de couverture** : téléchargement manuel/auto limité à `http(s)`, refus credentials/localhost/link-local, allowlist `proxy_domains`, refus des redirects. Soft-fail explicite — n'interrompt jamais l'enrichissement en exception.
* **BF22. `fallback_query` mort après ID forcé** : `enrich_series` passait `fallback_query` (titre alt / nom) mais `fetch_metadata` ne le lisait jamais. En cas d'échec ID/URL forcé, nouvelle tentative automatique en recherche titre.
* **BF23. Asymétrie load/save des providers Comic/Book** : `COMIC_PROVIDER_*`, `BOOK_PROVIDER_*` et `RESET_CONTEXT_ON_FORCE` étaient sauvegardés depuis l'UI mais absents des defaults / boucles env de `load_config()` — l'env Docker pour Comic/Book et le reset-on-force était ignorée. Defaults + câblage env rétablis.
* **BF24. XSS DOM de la modal couvertures** : les UIs HTTP/Socket interpolaient `title` / `display_url` distants dans `innerHTML`. Reconstruction via APIs DOM (`createElement` / `textContent`).
* **BF25. SSRF par redirect sur `/api/proxy-image`** : allowlist existante mais redirects suivis par défaut + Content-Type répercuté. Helper d'allowlist partagé, redirects bloqués, MIME `image/*` uniquement.
* **BF26. Échec silencieux de `update_series_general`** : le succès metadata seul marquait `COMPLETED` même si titre alt / format échouait. Le résultat de l'update général est désormais contrôlé.
* **BF27. Crash du mapping personnages** : l'enrichissement imposait la forme AniList `c['node']['name']['full']` et pouvait `KeyError`. Parsing défensif (dict/string ; entrées invalides ignorées).
* **C50. Protection CSRF + durcissement cookie de session** : jeton CSRF session (`csrf_utils.py`) validé sur les POST mutatifs (header `X-CSRF-Token` ou champ form) ; `utils.js` injecte le header sur tous les `fetch` mutatifs ; formulaire login avec champ caché. Cookie `SameSite=Lax` + `HttpOnly` (`SESSION_COOKIE_SECURE=1` optionnel derrière HTTPS). Webhook exempt (auth par jeton) ; `TESTING` pytest saute le CSRF.
* **BF28. Modale Changelog tronquée par un `<script>` non échappé** : le rendu Markdown→HTML injectait le texte du CHANGELOG (ex: `` `<script>` `` dans les notes de modularisation frontend) en `innerHTML` sans échappement. Le navigateur traitait ça comme une vraie balise script et jetait le reste de la modale. Le texte est désormais échappé HTML avant le formatage Markdown inline.

### 🛠️ Durcissement Audit — Findings Medium
* **BF29. Scoring unifié Kitsu / ComicVine / Bédéthèque** : ces scrapers n'avaient pas `attach_match_score` / `uses_unified_scoring` (score neutre 0.60). Ils passent désormais par `score_candidate` + seuil comme les autres officiels.
* **BF30. `localizedName` lu sur le mauvais DTO Kavita** : `get_series_deep_metadata()` cherchait `localizedName` dans Series/metadata ; il est sur `GET /api/Series/{id}`. Le scoring reçoit enfin le vrai titre alt.
* **BF31. Gestion d'erreur fetch frontend** : `syncSingle` / `proceedSyncSingle` / `saveConfig` / `applyCover` vérifient `res.ok` et restaurent l'UI en cas d'échec (plus de spinners bloqués ; save-override doit réussir avant force-sync).
* **BF32. `task_done()` sur la file de sync** : le `_worker` de fond appelle désormais `task_done()` après chaque job (aligné avec `stop_batch`).
* **BF33. Fermeture des Sessions HTTP scrapers** : `bedetheque` / `manganews` / `hardcover` ferment leur `Session` dans un `finally`.
* **BF34. `config.json` corrompu non écrasé silencieusement** : parse en échec → log + éventuel `config.json.bak`, pas de `save_config` auto qui écraserait le fichier cassé.
* **BF35. `TARGET_LANG` non forcé à chaque enrich** : langue écrite seulement si Kavita n'en a pas encore, ou en `force_update` (la traduction de résumé reste indépendante).
* **BF36. Modules morts MAL / Nautiljon supprimés** : fonctions hors `BaseScraper`, jamais enregistrées ; fichiers retirés.

### 🧹 Polish Audit — Findings Low
* **BF37. Plus de fallback `SECRET_KEY` hardcodé** : suppression du défaut public `'kavita-secret-key'` dans `app.py`. Si la clé est encore vide après `load_config()`, génération éphémère + log d'erreur. `import logging` manquant corrigé dans `config_manager.py`.
* **BF38. Préfixe de clé API plus logué** : le log debug d'auth Kavita n'affiche plus `api_key[:5]`.
* **BF39. Double absorb Smart Scoring documenté** : l'`absorb_candidate` vague-1 avant vague-2 parallèle est intentionnel ; commentaire ajouté, comportement inchangé.
* **BF40. `proxy_domains` ComicVine restreint** : retrait de `gamespot.com` large ; uniquement `comicvine.gamespot.com`.
* **BF41. `MAX_GENRES` / `get_max_genres()`** : plafond genres configurable (env / `config.json`, défaut **5**, borné 1–50). Appliqué aux scrapers à listes dynamiques (Shikimori, Manga-News, MangaUpdates, Hardcover, OpenLibrary, AniList, MangaBaka, GoogleBooks, Bédéthèque) et en filet dans `enrichment_engine` (`get_max_genres(config)`), miroir de `MAX_TAGS`. Boucle OpenLibrary sans hardcode `5`. Tags AniList via `get_max_tags()` ; MangaUpdates sans `categories[:10]` en dur pour laisser `MAX_TAGS` s'appliquer pleinement. Pas d'UI.

### 🧭 Menu Aide du topbar (À propos & Documentation)
* **C52. Menu Aide / À propos / Docs** : menu Aide du topbar (à côté des liens de soutien) : modal **À propos** in-app (version, texte court, liens GitHub / Issues / BMC), liens **Documentation** vers GitHub (`README`, `CUSTOM_SCRAPERS`, `DEVELOPER`, `ROADMAP` sur `dev`), et **Nouveautés** réutilisant la modal changelog.
* **C52b. Positionnement soutien Kavita+** : la modal À propos pousse d’abord le soutien à Kavita (Kavita+ / dons / Open Collective). Le topbar affiche **Kavita+** à côté de Buy me a coffee (même poids visuel). Le bouton ouvre les réglages admin de *cette* instance (`get_kavita_plus_url()` → `{KAVITA_EXTERNAL_URL|KAVITA_URL}/settings#admin-kavitaplus`, repli wiki si aucune URL).

### 🔧 Suivi post-audit
* **BF42. Logs d'exceptions sans fuite de clés** : `secure_logging.safe_exc_str` / `redact_secrets`. Auth Kavita et recherches ComicVine ne loguent plus `str(e)` brut (risque `?apiKey=` / `?api_key=` dans urllib3, y compris Live Logs).
* **BF43. Redirects couverture sécurisés + CDN** : upload couverture et `/api/proxy-image` suivent jusqu'à 3 redirects avec re-validation (`fetch_with_safe_redirects`) — **remplace** la politique stricte « aucun redirect » de BF21/BF25. `proxy_domains` élargis : Google Books (`googleusercontent.com`), MangaBaka (`api.mangabaka.org`), ComicVine (`static.comicvine.com`).
* **BF44. IPs privées bloquées dans l'allowlist** : refus RFC1918 / loopback / link-local / réservées et suffixes `.local`/`.internal`.
* **BF45. Escape ferme aussi le changelog** : le handler Escape du menu Aide ferme également la modal nouveautés.
* **Docs** : `CODE_REVIEW.md` — MAL/Nautiljon marqués comme **supprimés** (BF36).

### 🐛 Correctifs des Conflits Couverture Manuelle vs Auto-Cover
* **Persistance de la Préférence d'Éditeur par Série (`routes/series.py`)** : l'endpoint `/save-override` ne transmettait pas `publisher_pref` à la persistence, ce qui réinitialisait les choix par série à `GLOBAL` dans `cache.db`.
* **Case à Cocher des Champs Ciblés Périmée (`static/js/covers.js`)** : appliquer une couverture manuelle la protège bien côté serveur (retrait de `cover` de `targeted_fields`), mais la case "Couverture" du panneau par série gardait son état coché périmé depuis le chargement de la page. Cliquer sur "Sync" ou "Sauvegarder" sur cette même série avant un rechargement ré-introduisait silencieusement `cover` dans `targeted_fields`, annulant la protection. La case est désormais décochée immédiatement après une application réussie.
* **Couverture Manuelle Désignorant/Réouvrant Silencieusement des Séries (`routes/series.py::apply_series_cover`)** : la sauvegarde de protection réutilisait `save_series_override()`, qui force TOUJOURS le `status` à `PENDING` (comportement voulu pour le formulaire normal de sauvegarde d'override). Réutilisé tel quel pour un simple choix de couverture, cela désignorait silencieusement les séries `IGNORED` et réinitialisait les séries `COMPLETED`/`NOT_FOUND`, faussant les statistiques. Le statut d'origine est désormais explicitement restauré juste après.
* **Test de Sous-Chaîne sur les Cases à Cocher (`templates/partials/_series_row.html`)** : l'état des cases était calculé avec `'champ' in tf` sur la chaîne brute — un test de sous-chaîne, pas d'appartenance à une liste. Sans danger aujourd'hui mais une mine pour de futurs noms de champs. Découpage désormais explicite en liste avant le test.

### 🔒 Sécurité
* **Jeton API Hardcover Codé en Dur Supprimé (`debug/debug_hardcover.py`)** : un jeton bearer valide avait été commité directement dans un script de debug. Remplacé par un chargement depuis le système de configuration standard ; le jeton a été révoqué et purgé de l'historique git.
* **Durcissement SSRF couverture / proxy** : voir BF21 / BF25 (allowlist initiale) et BF43 / BF44 (`fetch_with_safe_redirects`, blocage IPs privées) — `url_allowlist.py`, upload couverture + `/api/proxy-image`.
* **Durcissement XSS UI couvertures** : voir BF24 (`static/js/covers.js`).
* **CSRF + flags cookie** : voir C50 (`csrf_utils.py`, `utils.js`, `SameSite=Lax`).
* **Logs d'exceptions sans fuite de clés** : voir BF42 (`secure_logging.py`).

## [1.5.8] - 2026-07-25 (The Kavita API Deep Compliance & KOReader Stability Update)

EN
### 🐛 Critical Bug Fixes
* **LocalizedName Corruption & KOReader/Kamare Crash Fix (`kavita_api.py`)**: `update_series_general()` now always fetches a series' full current state before writing (GET-merge-POST), preventing Kavita from silently nulling `LocalizedName` and force-unlocking `NameLocked`/`SortNameLocked`/`LocalizedNameLocked` on partial updates (e.g. format-only). Root cause of a reported KOReader "Kamare" plugin crash.
* **GET-Only System Fields Sanitization (`kavita_api.py`)**: Centralized sanitization in `update_series_metadata()` to strip computed/read-only properties (`totalCount`, `maxCount`, `pages`, `wordCount`) and prevent Entity Framework Core state-concurrency exceptions.
* **MangaBaka "Completed" Status Mapping (`scrapers/mangabaka.py`)**: Normalized MangaBaka's raw `completed` status to `FINISHED` so completed series no longer stay marked as "Ongoing".
* **`BaseScraper` Attribute Typo (`scrapers/base.py`)**: Fixed a typo (`eeds_api_key` instead of `needs_api_key`) on the base class' default attribute.

FR
### 🐛 Correctifs Critiques
* **Corruption LocalizedName & Crash KOReader/Kamare (`kavita_api.py`)** : `update_series_general()` récupère désormais systématiquement l'état complet de la série avant d'écrire (GET-fusion-POST), empêchant Kavita d'effacer silencieusement `LocalizedName` et de déverrouiller de force les locks de nom lors de mises à jour partielles. Cause racine d'un crash signalé sur l'extension KOReader "Kamare".
* **Purge des Clés Système Kavita (`kavita_api.py`)** : Suppression systématique des propriétés calculées (`totalCount`, `maxCount`, `pages`, `wordCount`) avant l'envoi des métadonnées pour éviter les exceptions Entity Framework Core.
* **Mappage du Statut "Terminé" MangaBaka (`scrapers/mangabaka.py`)** : Normalisation du statut brut `completed` de MangaBaka vers le statut interne `FINISHED` (les séries terminées ne restent plus bloquées en "En cours").
* **Typo d'Attribut `BaseScraper` (`scrapers/base.py`)** : Correction de `eeds_api_key` en `needs_api_key`.

## [1.5.7] - 2026-07-25 (The Community Scrapers, Publisher QoS & Kavita OpenAPI Compliance Update)

EN
### ✨ New Features & QoS
* **Community Scrapers Sideloading (`data/scrapers/`)**: MetaKavita now dynamically loads and integrates external Python scrapers dropped directly into the user-mapped `data/scrapers/` folder without rebuilding the Docker image. Custom scrapers automatically benefit from UI API Key generation and SSRF protection.
* **Publisher Localization Preference**: Added a global setting and an elegant per-series segmented toggle (`Auto` | `VF/VA` | `VO`) to let users prioritize Localized/Translated publishers (e.g., *Viz Media*, *Glénat*) or Original publishers (e.g., *Shueisha*, *Kodansha*).
* **Title Translation Fallback (Experimental)**: Added an optional safety net that automatically translates unfound localized titles to English to perform a second search pass.

### 🦸 Scraper Enhancements
* **MangaUpdates & MangaBaka Overhaul**: Upgraded parsers to actively categorize and extract both original and licensed publishers. Replaced standard `requests` in MangaUpdates with `curl_cffi` (`impersonate="chrome110"`) to seamlessly bypass Cloudflare anti-bot blocks.

### 🐛 Critical Bug Fixes & Kavita OpenAPI Deep Compliance
* **Kavita `publishers` Schema Mismatch Fix (`app.py`, `kavita_api.py`)**: Corrected the publisher payload key to plural `publishers` expecting an array of `PersonDto` objects (`[{"id": 0, "name": "Publisher"}]`), resolving an issue where Kavita silently discarded incoming publishers.
* **C# Lock Guard 2-Pass Transaction Protocol (`kavita_api.py`)**: Implemented an automated 2-pass sequence (`*Locked: False` ➔ write ➔ `*Locked: True`) across all metadata updates. This forces Kavita's C# backend to overwrite fields previously locked in its SQLite database without returning silent false-positives.
* **Plural Staff Lock Keys Standardized (`app.py`)**: Corrected all staff lock property names to match Kavita's C# singular OpenAPI spec (`writerLocked`, `characterLocked`, `publisherLocked`, etc.), ensuring authors and characters remain permanently locked after sync.
* **Permanent Cover Upload & C# Filename Binding (`kavita_api.py`)**: Fixed an HTTP 500 (`Invalid Filename`) exception on `POST /api/Upload/series` by passing `fileName` with dynamic extension detection (`.jpg`, `.png`, `.webp`) and `lockCover: True` alongside pure Base64 payloads.
* **Endpoint & Payload Separation (`app.py`, `kavita_api.py`)**: Strictly routed `summary` to `POST /api/Series/metadata` and `localizedName`/`format` to `POST /api/Series/update`.

### 🛠️ System, Code Health & Documentation
* **Bulletproof SQLite Schema Migrations (`db_manager.py`)**: Rewrote database initialization (`_ensure_schema`) to gracefully handle column additions one by one, preventing `sqlite3.OperationalError` crashes on container updates.
* **Custom Scraper Guide**: Added `CUSTOM_SCRAPERS.md` containing strict architecture rules and ready-to-use AI prompts ("Vibecoding") to build custom providers easily.

FR
### ✨ Nouvelles Fonctionnalités & QoS
* **Scrapers Communautaires Personnalisés (`data/scrapers/`)** : MetaKavita charge désormais dynamiquement les scripts Python déposés dans le volume utilisateur `data/scrapers/`. Permet d'ajouter des sites à la volée sans recompiler l'image Docker.
* **Préférence d'Éditeur (VF/VA vs VO)** : Ajout d'une option globale et d'un interrupteur par série (`Auto` | `VF/VA` | `VO`) permettant de prioriser l'éditeur localisé (ex: *Glénat*, *Kurokawa*) ou l'éditeur d'origine (ex: *Shueisha*, *Kodansha*).
* **Titre de Secours (Traduction Fallback Expérimentale)** : Ajout d'un filet de sécurité désactivable traduisant automatiquement un titre non-trouvé vers l'anglais pour relancer une seconde recherche sur les API internationales.

### 🦸 Améliorations Scrapers
* **MangaUpdates & MangaBaka** : Mise à jour des parseurs pour extraire, catégoriser et trier les éditeurs traduits et originaux. Intégration de `curl_cffi` (`impersonate="chrome110"`) sur MangaUpdates pour contourner les blocages anti-bot Cloudflare.

### 🐛 Correctifs Critiques & Conformité OpenAPI Kavita
* **Correction du Schéma `publishers` (`app.py`, `kavita_api.py`)** : Correction du nom de variable pour utiliser `publishers` au pluriel avec un tableau de `PersonDto` (`[{"id": 0, "name": "Éditeur"}]`), résolvant le problème où Kavita rejetait silencieusement la maison d'édition.
* **Protocole C# Lock Guard à 2 Passages (`kavita_api.py`)** : Implémentation d'une séquence automatique en 2 temps (`*Locked: False` ➔ écriture ➔ `*Locked: True`) sur toutes les mises à jour. Force le serveur C# de Kavita à écraser les champs déjà verrouillés en base de données sans faire de faux-positifs.
* **Normalisation des Verrous au Singulier (`app.py`)** : Alignement de tous les verrous du staff sur le schéma OpenAPI de Kavita (`writerLocked`, `characterLocked`, `publisherLocked`, etc.), garantissant que les auteurs restent définitivement verrouillés après synchronisation.
* **Upload de Couverture Permanent & Fix Erreur 500 (`kavita_api.py`)** : Résolution de l'exception HTTP 500 (`Invalid Filename`) sur `POST /api/Upload/series` grâce à l'envoi conjoint de `fileName` (avec extension dynamique `.jpg`, `.png`, `.webp`) et `lockCover: True` en Base64 pur.
* **Séparation Stricte des Endpoints (`app.py`, `kavita_api.py`)** : Routage du résumé vers `POST /api/Series/metadata` et des généralités (`localizedName`, `format`) vers `POST /api/Series/update`.

### 🛠️ Système, Qualité du Code & Documentation
* **Migrations SQLite Sécurisées (`db_manager.py`)** : Initialisation robuste (`_ensure_schema`) ajoutant les colonnes manquantes une par une pour empêcher les crashs HTTP 500 lors des mises à jour du conteneur.
* **Guide Scrapers Communautaires** : Ajout du fichier `CUSTOM_SCRAPERS.md` contenant les règles d'architecture et les prompts IA (Vibecoding) pour créer facilement de nouveaux scrapers.

## [1.5.6] - 2026-07-24 (The Permanent Cover Upload Hotfix)

EN
### 🐛 Bug Fixes
* **Pure Base64 Cover Payload (`kavita_api.py`)**: Fixed a critical bug (the "Phantom Cover" syndrome) where Kavita silently rejected image payloads, resulting in deleted covers upon hard browser refreshes. Removed the `Data URI` prefix (`data:image/jpeg;base64,...`) and reverted to pure Base64 strings, which allows Kavita's C# engine to correctly write and save the images permanently to the disk.

FR
### 🐛 Correctifs
* **Payload Base64 Pur (`kavita_api.py`)** : Résolution du bug critique des "couvertures fantômes" où Kavita rejetait silencieusement les images et finissait par les effacer du disque dur. Le payload a été corrigé pour envoyer une chaîne Base64 pure (sans préfixe *Data URI*), ce qui permet au moteur C# de Kavita de lire les octets et d'enregistrer l'image de manière permanente.

## [1.5.5] - 2026-07-23 (The Deep Extraction, High-Speed Engine & Scoring Precision Update)

EN
### ⚡ High-Speed Engine & Throttling Overhaul
* **Smart Per-Provider Rate Limiter (`metadata_fetcher.py`)**: Replaced hardcoded worker sleep delays (`1.5s`/`2.5s`) with a timestamp-based dynamic throttler (`LAST_REQUEST_TIMES`). Idle APIs respond instantly with zero artificial delay, executing 3-provider Smart Fusions in ~1.6s.
* **Unrestricted Provider Forcing (`templates/index.html`, `metadata_fetcher.py`)**: Unlocked all registered scrapers in the Magic Input dropdown, allowing users to force any metadata source regardless of library type or search string.

### ✨ Deep Metadata Extraction & Unified Scoring Matrix
* **Deep Kavita Metadata Extraction (`kavita_api.py`, `app.py`)**: Pre-fetches existing metadata from Kavita's database (sanitized ISBNs, authors, publisher, release year, genres) before querying external APIs to anchor searches and prevent false positives.
* **Unified Weighted Scoring Matrix (`scrapers/utils.py`)**:
  * *ISBN Golden Rule*: Instant 100% confidence match on exact ISBN.
  * *Anti-Homonym Author Mismatch Rule*: Implemented a strict `-50%` penalty if a candidate's author differs from Kavita's context (e.g., preventing manga adaptations from matching classical novels).
  * *Roman Numeral Volume Converter*: Automatically converts Roman volume numbers (e.g. `Tome II` -> `Tome 2`) before evaluating similarity.
  * *Anti-Spin-Off & Guidebook Filters*: Added `-35%` penalty for missing distinctive query words (*Lanfeust des Étoiles* vs *Troy*) and `-50%` penalty for noise keywords (`Guidebook`, `Fanbook`, `Artbook`).
  * *Volume 1 Anchoring*: Grants `+0.10` bonus to Volume 1/unnumbered editions while applying `-0.45` penalty to intermediate volumes.

### 🦸 New Scrapers & Core Enhancements
* **ComicVine Refactor (`scrapers/comicvine.py`)**:
  * Switched volume queries to structured `/volumes/?filter=name:` endpoint with explicit `field_list`.
  * Weighted candidate selection favoring primary US/European publishers (`DC Comics`, `Marvel`, `Image`, `Dargaud`) and issue count while heavily penalizing foreign translation houses.
  * **Issue #1 Creator & Summary Fallback**: Automatically queries Issue #1 when a Volume lacks staff or description, boosting summary length from 39 chars to 3,500+ chars.
* **New Scraper Integrations**:
  * **Hardcover (Experimental)**: Hasura GraphQL & Typesense search engine for books and graphic novels (`curl_cffi` Chrome impersonation).
  * **MangaDex**: Official REST API v5 integration with content rating filters, native AniList/MAL ID extraction, and oneshot scoring.
  * **MangaUpdates**: Official REST API v1 scraper with `hit_title` matching and BBCode text cleaning.
  * **Manga-News**: Franco-Belgian & French catalog scraper (`curl_cffi`) for VF publishers and HD artwork.
  * **Shikimori**: Fast REST JSON scraper with multilingual title matching and dedicated `/roles` staff parsing.
  * **Open Library**: Literature and novel provider powered by Internet Archive.
* **Resiliency & Bug Fixes**:
  * **Bédéthèque**: Fixed duplicate method signature causing fatal `.get()` crashes on lists.
  * **MangaBaka**: Added `(data.get('authors') or [])` guards against null JSON keys causing `TypeError`.
  * **Kavita Cache Invalidation**: Dynamically clears `_series_lib_type_cache` on batch runs, recognizing updated library types (including ID 5 `Comic Flexible`) without container restarts.

FR
### ⚡ Moteur Haute Performance & Throttling Dynamique
* **Rate-Limiter Intelligente par Horodatage (`metadata_fetcher.py`)** : Remplacement des pauses fixes dans `app.py` par un régulateur dynamique basé sur `time.time()`. Les API inactives répondent instantanément sans attente artificielle, exécutant les Smart Fusions de 3 sources en ~1,6s.
* **Forçage Libre des Fournisseurs (`templates/index.html`, `metadata_fetcher.py`)** : Déblocage de l'ensemble des scrapers dans le menu déroulant du Champ Magique pour permettre le forçage manuel de n'importe quelle source.

### ✨ Extraction Profonde & Matrice de Scoring
* **Extraction Profonde Kavita (`kavita_api.py`, `app.py`)** : Récupération en amont des données existantes (ISBN, auteurs, éditeur, année) avant le scraping pour ancrer les recherches.
* **Matrice de Scoring Unifiée (`scrapers/utils.py`)** :
  * *Règle d'or ISBN* : Match instantané à 100% sur ISBN exact.
  * *Règle Anti-Homonyme Auteur* : Pénalité de `-50%` si l'auteur du candidat diffère de l'auteur dans Kavita.
  * *Convertisseur de Chiffres Romains* : Conversion automatique des tomes (`Tome II` -> `Tome 2`).
  * *Filtres Anti-Spin-Off & Anti-Guidebook* : Pénalités ciblées sur les mots-clés manquants (`-35%`) ou parasites (`-50%` pour `Guidebook`/`Fanbook`).
  * *Ancrage Tome 1* : Bonus de `+0.10` pour les Tomes 1 et pénalité de `-0.45` sur les tomes intermédiaires.

### 🦸 Nouveaux Scrapers & Améliorations Core
* **Refonte Structurée ComicVine (`scrapers/comicvine.py`)** :
  * Bascule sur l'endpoint structuré `/volumes/?filter=name:` avec `field_list` explicite.
  * Priorisation des éditeurs originaux majeurs (`DC Comics`, `Marvel`, `Image`, `Dargaud`) et pénalisation des traducteurs étrangers.
  * Récupération automatique du résumé et des auteurs sur l'Issue #1 si la fiche série est pauvre (résumés propulsés de 39 à 3 500+ caractères).
* **Nouveaux Scrapers Intégrés** :
  * **Hardcover (Expérimental)** : Moteur GraphQL Hasura & Typesense pour livres et BDs.
  * **MangaDex** : API v5 avec filtres adulte, IDs externes et scoring.
  * **MangaUpdates** : API v1 avec nettoyage BBCode et matching `hit_title`.
  * **Manga-News** : Catalogue VF (`curl_cffi`) pour éditeurs français et couvertures HD.
  * **Shikimori** : API REST JSON multilingue avec extraction du staff via `/roles`.
  * **Open Library** : API Littérature d'Internet Archive.
* **Correctifs & Stabilité** :
  * **Bédéthèque** : Correction de la méthode `fetch()` écrasée par erreur.
  * **MangaBaka** : Sécurisation contre les clés `null` dans l'API JSON.
  * **Cache Kavita** : Purge automatique du cache au lancement des batchs pour reconnaître les changements de types de bibliothèques (ID 5 `Comic Flexible`) sans redémarrer Docker.

## [1.5.4] - 2026-07-22 (The "Smart Override" & Network Flexibility Update)

EN
### ✨ New Features & Core Architecture
* **Enhanced Webhook Endpoint (`force` & Token Rotation)**: The `/webhook` endpoint now supports a `"force": true` (or `"force_update": true`) parameter in its JSON/Form payload, as well as via URL query string (`?force=true`), allowing external scripts to trigger forced metadata overwrites. Added a read-only Webhook URL input in the Config Modal with a one-click token regeneration button.
* **Reverse Proxy & Subpath Support (C17)**: Full native support for hosting MetaKavita under custom URL subpaths (e.g., `https://domain.com/metakavita`). Configurable via the `ROOT_PATH` environment variable or proxy headers (`X-Forwarded-Prefix`). Dynamically prefixes client AJAX calls and WebSocket (`Socket.IO`) connections while maintaining strict Same-Origin CORS security.
* **Disable Translation Option (BF6)**: Added a "Disabled (Keep original)" option to the Translation Provider dropdown, allowing users to preserve scraped descriptions in their original language without querying external translation APIs.
* **The "Magic Input" (Smart URL Routing)**: The old "AniList ID" override field has been completely replaced by a universal Magic Input. You can now paste a direct URL from *any* supported provider (e.g., `https://mangabaka.org/1234` or a ComicVine link) directly into the field. MetaKavita will automatically detect the domain, extract the ID, and bypass the default cascade to scrape that exact page!
* **Context-Aware Magic Dropdown**: The provider dropdown next to the Magic Input now dynamically filters its options based on the Kavita library type (e.g., hiding ComicVine for Mangas), preventing invalid manual forcing.
* **Smart ID Match Engine**: If you paste a raw numerical ID or slug and leave the dropdown on "AUTO", the system will query compatible providers and intelligently validate the match by comparing the fetched title with your Kavita title (>50% similarity required). False positives are automatically rejected and the cascade continues safely!
* **Granular Scraping (Targeted Fields)**: Worried about overwriting a summary you manually edited in Kavita? Each series now features a hidden "⚙️ Targeted Fields" dropdown. You can granularly select exactly which data MetaKavita is allowed to update (Summary, Cover, Staff, Genres, Tags, Year, Status, Publisher, Age, Format, WebLinks, Alt Titles).
* **Self-Healing Configuration Engine**: MetaKavita now dynamically validates your search cascade. If you select a default provider that has been physically deleted from the `scrapers/` folder, the engine will automatically self-heal, warn you in the logs, and safely fallback to the next available scraper to prevent your batch queues from crashing.
* **Extended Kavita API Coverage**: The staff mapping engine has been expanded. MetaKavita now natively pushes `Editors`, `Letterers`, `Inkers`, and the localized `Language` directly into Kavita's database.

### 🐛 Bug Fixes & UI Improvements
* **Google Books Stability & Anchor Match**: Refactored `googlebooks.py` to evaluate up to 10 search results using title similarity scoring (`calculate_similarity`). Implemented a Volume 1 / Band 1 priority anchor for novel series (such as *Perry Rhodan Neo*) to prevent random description shifts during batch re-syncs. Rejects candidates below 50% similarity to allow clean cascade fallback.
* **Re-integrated English Target Language**: Fixed an oversight where English (`EN`) was missing from the target translation language selection dropdown (`TARGET_LANG`).
* **Strict ID Routing**: Fixed a major bug where searching by ID would accidentally trigger title searches on fallback providers, causing chaotic metadata fusion. IDs and URLs are now strictly routed as pure ID queries exclusively to supported scrapers.
* **Alternative Titles Crash**: Fixed a fatal `TypeError` (`expected str instance, NoneType found`) that crashed the server when fusing alternative titles containing `None` values from incomplete APIs (like Kitsu).
* **Visual Feedback on Mass Actions**: The "Save All Overrides" button now features an active loading state (`⏳ Saving in progress...`) and dynamically disables itself during processing to prevent UI freezing and server saturation.

FR
### ✨ Nouvelles Fonctionnalités & Architecture
* **Endpoint Webhook Enrichi (Option `force` & Régénération de jeton)** : L'endpoint `/webhook` accepte désormais un paramètre `"force": true` (ou `"force_update": true`) dans son payload JSON/Form, ainsi que par paramètre d'URL (`?force=true`), permettant aux scripts externes d'imposer un ré-enrichissement forcé. Ajout de l'affichage de l'URL Webhook dans la modal de configuration avec un bouton de régénération du jeton.
* **Support Reverse Proxy & Sous-dossiers / Subpath (C17)** : Support natif complet pour le déploiement derrière un sous-chemin d'URL (ex: `https://domaine.com/metakavita`). Configurable via la variable d'environnement `ROOT_PATH` ou les en-têtes proxy (`X-Forwarded-Prefix`). Adapte dynamiquement les requêtes AJAX et le tunnel WebSocket (`Socket.IO`) tout en conservant la sécurité CORS Same-Origin.
* **Option de Désactivation de la Traduction (BF6)** : Ajout d'une option "Désactivé (Conserver l'original)" dans le sélecteur de traduction pour sauvegarder les résumés dans leur langue d'origine sans faire appel aux API externes.
* **Le "Champ Magique" (Routage URL Intelligent)** : L'ancien champ d'ID AniList a été remplacé par un champ universel. Vous pouvez désormais coller l'URL directe d'une œuvre provenant de *n'importe quel* fournisseur supporté (ex: une URL Bédéthèque ou MangaBaka). MetaKavita détectera automatiquement le domaine, extraira l'ID et contournera la cascade pour scraper cette page précise !
* **Menu Déroulant Contextuel** : Le menu de forçage de fournisseur à côté du champ magique s'adapte désormais dynamiquement au type de bibliothèque Kavita (ex: masquage de ComicVine pour les Mangas), évitant les erreurs de forçage.
* **Moteur "Smart ID Match"** : Si vous saisissez un ID brut (ou slug) en laissant le fournisseur sur "AUTO", le système interrogera les sites compatibles et validera les résultats en comparant le nom de la série Kavita avec le nom trouvé par l'API (nécessite >50% de ressemblance). Les faux positifs sont rejetés et la cascade continue !
* **Scraping Granulaire (Champs Ciblés)** : Peur d'écraser un résumé que vous avez tapé à la main dans Kavita ? Chaque série dispose désormais d'un menu "⚙️ Champs Ciblés". Vous pouvez cocher/décocher individuellement les 12 métadonnées que MetaKavita est autorisé à modifier.
* **Auto-Réparation de la Configuration (Self-Healing)** : MetaKavita valide dynamiquement votre cascade de recherche. Si un fournisseur par défaut a été supprimé physiquement du dossier `scrapers/`, le moteur s'auto-répare, le signale dans les logs, et bascule sur le premier scraper disponible pour empêcher le crash de vos files d'attente.
* **Couverture API Kavita Étendue** : Le moteur de mapping du staff a été complété. MetaKavita reconnait et envoie désormais les `Éditeurs` (Staff), `Lettreurs`, `Encreurs`, ainsi que la `Langue` de localisation à Kavita.

### 🐛 Corrections de Bugs & Améliorations UI
* **Stabilisation & Ancrage Google Books** : Refonte de `googlebooks.py` pour évaluer jusqu'à 10 résultats via un score de similarité (`calculate_similarity`). Ajout d'un ancrage prioritaire sur le Tome 1 / Band 1 pour les séries de romans (ex: *Perry Rhodan Neo*) afin d'éviter le changement aléatoire de résumé lors des re-synchronisations. Rejet des résultats <50% de similarité pour basculer proprement sur la suite de la cascade.
* **Réintégration de l'Anglais en Langue Cible** : Correction d'un oubli où l'anglais (`EN`) manquait dans la liste déroulante des langues de traduction (`TARGET_LANG`).
* **Routage Strict des IDs** : Résolution d'un bug critique où la recherche par ID déclenchait accidentellement une recherche par titre sur les fournisseurs de secours, créant des fusions de métadonnées chaotiques. Les URLs et IDs sont désormais strictement routés.
* **Crash des Titres Alternatifs** : Correction d'une erreur fatale `TypeError` (`expected str instance, NoneType found`) qui faisait crasher le serveur lors de la fusion de titres alternatifs contenant des valeurs `None` (souvent renvoyées par Kitsu).
* **Feedback Visuel de Masse** : Le bouton "Tout sauvegarder d'un coup" affiche désormais un état de chargement dynamique (`⏳ Sauvegarde en cours...`) et se verrouille le temps du traitement pour éviter de saturer le serveur ou de freezer l'interface.

## [1.5.2] - 2026-07-21 (The Plug & Play Architecture Update)

EN
### 🐛 Bug Fixes & Refinements
* **Context-Aware Cover Fetching**: Fixed a regression where the manual cover search queried all scrapers blindly. The system now dynamically filters active scrapers based on the Kavita `library_type` (e.g., Manga, Comic) and passes this context to adapt the title cleaning rules (fixing the `unexpected keyword argument` crash).
* **Bédéthèque Spin-off Override Bug**: Fixed an issue where searching for a main series (e.g., "La Quête d'Ewilan") would return covers from its spin-offs (e.g., "Ellana") due to Bédéthèque's alphabetical sorting. Implemented an exact-match logic that delays the loop-break, evaluating all title variations (with and without articles) to guarantee the parent series is pushed to the top of the results.

### 🧱 Plug & Play Scraper Architecture
* **Auto-Discovery Registry**: Refactored the core engine to use a Registry pattern (`ScraperRegistry`). Scrapers are now dynamically loaded from the `scrapers/` folder on startup. Adding a new provider is now as simple as dropping a `.py` file.
* **Standardized Base Interface**: Introduced the `BaseScraper` abstract class, enforcing a strict contract (ID, display name, supported library types, rate limits, and proxy domains) for all metadata providers.
* **Dynamic UI Generation**: The global configuration modal (`index.html`) and the provider cascading logic now dynamically generate dropdowns and fallback rules based on currently active scrapers. No more hardcoding!
* **Decoupled Utilities**: Extracted `clean_title` logic into a dedicated `scrapers/utils.py` module to ensure adherence to the Single Responsibility Principle and prevent circular dependencies.

### New Provider: Bédéthèque Scraper
* **Full Integration**: Added a dedicated scraper for Bédéthèque, heavily optimized for Franco-Belgian Comics.
* **Anti-Bot & CSRF Bypass**: Leveraged `curl_cffi` and dynamic CSRF token extraction (`csrf_token_bel`) to seamlessly bypass Bédéthèque's aggressive anti-scraping firewalls.
* **Smart Summary Recovery**: Bédéthèque often leaves Series descriptions empty. The scraper intelligently falls back to the Tome 1 (Album) summary, and utilizes SEO `og:description` meta tags as a bulletproof extraction method if HTML structures change.
* **Surgical Staff Parsing**: Automatically identifies roles (Scénario, Dessin, Couleurs) and reformats author names from "Lastname, Firstname" to "Firstname Lastname" for a pristine display in Kavita.

🇫🇷
### 🐛 Corrections de Bugs & Améliorations
* **Recherche de Couvertures Contextuelle** : Correction d'une régression où la recherche manuelle d'images interrogeait tous les fournisseurs à l'aveugle. Le système filtre désormais dynamiquement les scrapers selon le type de bibliothèque (`Manga`, `Comic`, `Book`) et transmet ce contexte pour adapter le nettoyage du titre (ce qui corrige au passage l'erreur fatale `unexpected keyword argument`).
* **Bug d'Écrasement par les Spin-offs (Bédéthèque)** : Résolution d'un problème où la recherche d'une série principale (ex: "La Quête d'Ewilan") renvoyait les couvertures de son spin-off (ex: "Ellana") à cause du tri alphabétique natif de Bédéthèque. Ajout d'une logique de "match exact" qui évalue toutes les variations de titres (gestion des articles "Le", "La") pour garantir que la série mère remonte en première position.

### 🧱 Architecture Scraper "Plug & Play"
* **Découverte Automatique (Registry)** : Refonte totale du cœur de l'application avec un pattern Registre (`ScraperRegistry`). Les scrapers sont désormais chargés dynamiquement au démarrage depuis le dossier `scrapers/`. Ajouter un nouveau site se résume à glisser un fichier python. Fin du hardcoding !
* **Interface Standardisée** : Création de la classe abstraite `BaseScraper` qui impose un contrat strict (ID, nom public, types de bibliothèques supportés, délais entre requêtes, domaines proxy anti-SSRF) à tous les fournisseurs.
* **Génération Dynamique de l'UI** : Les menus déroulants de la modale de configuration et le routage interne s'adaptent désormais dynamiquement aux scrapers détectés par le système.
* **Utilitaires Découplés** : Déplacement de la fonction de nettoyage `clean_title` vers un module autonome `scrapers/utils.py` pour un code plus propre et sans dépendances circulaires.

### 🇫🇷 Nouveau Fournisseur : Bédéthèque
* **Intégration Bédéthèque** : Ajout d'un scraper ultra-spécialisé pour la base de données de référence de la bande dessinée franco-belge.
* **Contournement Anti-Bot (CSRF)** : Utilisation de `curl_cffi` et récupération à la volée des jetons de sécurité HTTP (`csrf_token_bel`) pour esquiver les pare-feux et blocages IP restrictifs de Bédéthèque.
* **Récupération Intelligente des Résumés** : La page "Série" est souvent vide sur Bédéthèque. Le scraper est conçu pour piocher intelligemment le résumé sur l'Album (Tome 1) en cas d'échec. Il utilise également la balise SEO `og:description` comme méthode de secours absolue pour garantir un résultat.
* **Parsing Chirurgical du Staff** : Extraction précise des rôles (Scénario, Dessin, Couleurs) et reformatage automatique des noms d'auteurs ("Nom, Prénom" devient "Prénom Nom") pour un affichage esthétique dans Kavita.

## [1.5.0] - 2026-07-20 (The Multi-Media & Resiliency Update)

EN
### 🚀 Kitsu Integration & Provider Purge
* **Kitsu JSON:API Integration**: Added `scrapers/kitsu.py` using the free, open, and blazing-fast Kitsu API (no API key required). It fetches incredibly rich metadata and completely replaces our initial tests with MyAnimeList/Jikan (which suffered from heavy 504 Gateway Timeouts).
* **Nautiljon Purge**: Due to highly aggressive Cloudflare IP banning policies and an archaic anti-scraping stance, Nautiljon has been completely removed from the default provider cascades and routing maps.

### 🌐 Zero-Config Translation & Resilient Pipeline
* **Zero-Config Google Translate**: Integrated `py-googletrans` (v4.0.0-rc1) to provide 100% free, unlimited translations out of the box without requiring any API keys. Azure and DeepL remain available for enterprise-grade stability, but Google Translate acts as the ultimate magic fallback.
* **Azure & DeepL Integration**: Integrated Microsoft Azure Translator as the primary translation engine (2M characters/month F0 free tier) with DeepL as an automatic fail-safe fallback in case of HTTP 403, 429, or 456 quota exceptions.
* **Azure Translator Hardening**: Added explicit payload and HTTP response debug logging to easily diagnose Microsoft Azure API rejections.

### 🎨 Translation UI & Settings Reorganization
* **Dynamic Translation Provider UI**: Added a clean dropdown in the settings modal to select the active translation engine (Google, Azure, DeepL). Irrelevant API key fields are now dynamically hidden to reduce UI clutter.
* **Settings Modal Reorganization**: Improved the Global Configuration layout using semantic CSS columns to neatly group Provider API Keys under Kavita's connection settings.

### 🧩 Dynamic Routing & Scraper Factory
* **Scraper Factory Pattern**: Refactored `PROVIDERS_MAP` in `metadata_fetcher.py` into a nested map structure indexed by Kavita's exact library types (`Manga`, `Comic`, `Book`). Implemented a resilient fallback system in `get_scraper_engine` to handle mismatched requests.
* **Kavita Library Type Extraction**: Updated `kavita_api.py` to extract the `type` property of libraries and map them to standard string representations (`Manga`, `Comic`, `Book`). Added an in-memory cache to prevent redundant API calls during batch syncing.
* **Global Server Batch Support**: Enhanced `/batch-sync` execution to allow full server syncing. If no specific library is selected, the system dynamically iterates through all libraries and routes them according to their individual library types.

### 🦸 Hybrid ComicVine Scraper (Ultimate)
* **Two-Step Resolution Flow**: Implemented `scrapers/comicvine.py` using a dual-request approach (Volume Search ➡️ Fallback to Issue Search ➡️ Resolve Parent Volume ➡️ Fetch detailed metadata) to resolve French/European BD albums.
* **String Similarity Validator**: Integrated a hybrid scoring engine (`difflib.SequenceMatcher` + Token intersection) to strictly validate search results and drastically reduce false-positive matches on vaguely similar titles.
* **In-Memory Homonym Recovery**: Designed an automatic fallback search that sorts homonym volumes by issue count and pulls metadata from highly populated entries (e.g. Gaston 2009) if the resolved entry is an empty reissue stub.
* **Noisy HTML Pruning**: Added a custom HTML stripper to automatically delete structural wiki sections ("Publishers", "Collected Editions") that cluttered the final summary.
* **Komf-Aligned Credits Mapping**: Standardized artist and author role matching (`person_credits`) to align with Komf's mapping rules, populating Kavita's extended staff fields.

### 📖 Production Google Books Scraper
* **Full Implementation**: Replaced the testing stub with a production-ready Google Books API scraper to fetch rich metadata for Novels and Western/European Comics (ISBN-compatible).
* **Dynamic Internationalization**: Google Books searches (`langRestrict`) are now dynamically bound to the user's `TARGET_LANG` configuration, ensuring native language summaries whenever possible.
* **API Key Support**: Added `GOOGLEBOOKS_API_KEY` to the global configuration to prevent HTTP 429 (Too Many Requests) limits on self-hosted instances.

### 🧹 Contextual Title Cleaning
* **Clean Title Contexts**: Adapted `clean_title` to clean queries based on library types. Comics/BDs safely strip noise leading zeros (e.g., `04 ` or `04 - `) while preserving issue/tome numbering. Books isolate `"Title - Author"` splits cleanly.

### 🐛 Bug Fixes
* **Metadata Corruption Lock (Age & Format)**: Fixed a logic bug in `app.py` where `ageRatingLocked` and `formatLocked` were forcefully applied to Kavita even when scrapers returned unmapped/unknown values, which silently erased existing database values.
* **MangaBaka Silent Crash**: Fixed a `NoneType` iteration bug that silently killed the Smart Completion fusion when MangaBaka returned null tags.
* **Auto-Reading Direction Deduction**: MangaBaka now safely and intelligently deduces the Reading Format (Manga vs Webtoon) by inspecting its own tags/genres if the API doesn't explicitly provide it.
* **Env Var Override Lock**: Fixed an issue where Docker environment variables (like `ADMIN_PASSWORD`) would override the user's manual UI changes upon container restart. `config.json` now acts as the absolute source of truth.
* **Hard Logout Cleansing**: Secured the `/logout` route to physically destroy the session cookie (`expires=0`) on the client side, ensuring a clean re-authentication state.

FR
### 🚀 Intégration de Kitsu & Purge de Nautiljon
* **Intégration Kitsu JSON:API** : Ajout de `scrapers/kitsu.py` exploitant l'API publique de Kitsu (sans clé requise et ultra-rapide). Récupère des métadonnées riches et remplace nos essais avortés avec MyAnimeList/Jikan (qui souffrait d'erreurs 504 en boucle).
* **Retraite de Nautiljon** : Face aux bannissements IP abusifs et imprévisibles de leur pare-feu Cloudflare, Nautiljon a été totalement éradiqué du routage et des cascades par défaut.

### 🌐 Google Translate "Zero-Config" & Résilience
* **Google Translate (Gratuit)** : Intégration de `py-googletrans` (v4.0.0-rc1) offrant des traductions 100% gratuites et illimitées dès l'installation, sans aucune clé d'API requise. Azure et DeepL restent disponibles pour une stabilité maximale, mais Google prendra le relais de manière transparente !
* **Intégration d'Azure & DeepL** : Ajout de Microsoft Azure Translator comme moteur principal (F0, 2M de caractères gratuits par mois) avec bascule automatique vers DeepL en cas d'erreur de quota.
* **Fiabilisation Azure Translator** : Ajout de logs de diagnostic explicites (taille du payload, région, requêtes brutes) pour tracer et comprendre instantanément les rejets de l'API Microsoft.

### 🎨 UI du Traducteur & Réorganisation
* **Sélecteur Dynamique de Traduction** : Ajout d'un menu déroulant intuitif dans la configuration pour choisir son moteur de traduction (Google, Azure, DeepL). Les champs de clés API inutiles sont masqués dynamiquement pour épurer l'interface.
* **Réorganisation de la Modal** : Amélioration de la grille CSS pour regrouper proprement les clés d'API des fournisseurs de métadonnées juste sous les identifiants Kavita.

### 🧩 Routage Dynamique & Scraper Factory
* **Architecture Scraper Factory** : Restructuration de `PROVIDERS_MAP` en dictionnaire imbriqué indexé par type exact de bibliothèque Kavita (`Manga`, `Comic`, `Book`). Implémentation d'un système de repli résilient vers les mangas en cas d'erreur.
* **Détection du Type de Bibliothèque** : Extraction de la propriété `type` des bibliothèques Kavita avec mise en cache mémoire pour optimiser les appels d'API.
* **Support du Batch Global** : Amélioration de la file d'attente `/batch-sync` pour lancer une synchronisation à l'échelle du serveur entier. En l'absence de sélection, le système traite l'intégralité du serveur en appliquant le routage dynamique à la volée.

### 🦸 Scraper ComicVine Hybride (Ultime)
* **Recherche en Deux Étapes** : Interrogation des volumes, puis des issues (albums) en cas d'échec pour remonter vers la série parente. Résout les albums franco-belges orphelins.
* **Validateur de Similarité** : Implémentation d'un algorithme de score hybride (`difflib` + intersection de mots-clés) pour écarter rigoureusement les faux-positifs lors des recherches floues de l'API.
* **Résolution d'Homonymes Vides** : Tri des homonymes par nombre de tomes décroissant pour extraire la description d'une édition majeure rédigée si l'édition active est vide.
* **Nettoyage HTML Anti-Bruit** : Suppression automatique des sections wiki structurelles (Éditeurs, Éditions compilées, etc.) qui polluaient le résumé final.
* **Mappage de Staff** : Normalisation de la récupération du staff créateur pour alimenter proprement les rôles dans Kavita (Scénario, Dessin, Couleur, etc.).

### 📖 Scraper Google Books de Production
* **Implémentation Complète** : Remplacement du bouchon de test par un scraper Google Books officiel, capable d'enrichir les Romans et les BD européennes (via la catégorie Comic).
* **Internationalisation Dynamique** : Les recherches Google Books (`langRestrict`) s'adaptent désormais automatiquement à la `Langue de traduction` choisie par l'utilisateur pour trouver la bonne édition.
* **Support de Clé API** : Ajout du champ `GOOGLEBOOKS_API_KEY` pour éviter l'erreur HTTP 429 (Trop de requêtes) inhérente aux serveurs auto-hébergés.

### 🧹 Nettoyage Contextuel de Titres
* **Nettoyage Adaptatif** : Ajustement de `clean_title` selon le format du média. La catégorie Comics nettoie proprement les préfixes de tri sans casser les œuvres aux noms chiffrés. Les romans isolent les structures `"Titre - Auteur"`.

### 🐛 Corrections de Bugs
* **Corruption de Métadonnées Kavita** : Correction d'un bug critique dans `app.py` où les champs `ageRatingLocked` et `formatLocked` étaient verrouillés à vide si un scraper renvoyait une valeur inconnue, écrasant ainsi les données préexistantes de Kavita.
* **Crash Silencieux MangaBaka** : Résolution d'une erreur `NoneType` qui annulait silencieusement la fusion intelligente (Smart Completion) lorsque l'API renvoyait des tags vides.
* **Sens de Lecture Automatique** : Le scraper MangaBaka déduit désormais intelligemment le format de lecture (Webtoon vs Manga) en analysant ses propres mots-clés.
* **Verrouillage des Variables d'Environnement** : Correction d'un bug où les variables Docker (ex: `ADMIN_PASSWORD`) écrasaient la configuration de l'utilisateur au redémarrage. Le fichier `config.json` a désormais la priorité absolue.
* **Nettoyage de Session** : Sécurisation de la route `/logout` qui force désormais l'expiration physique du cookie de session côté navigateur.

---

## [1.4.0] - 2026-07-19 (Ergonomic Revolution & Total UI Overhaul)

EN
### 🎨 Major UI & Ergonomics Overhaul
* **Settings Modal**: Moved all infrastructure and technical configuration inputs (Kavita URL/API, DeepL API, languages, auto-sync, fallback providers) into a clean, dedicated overlay Modal, completely uncluttering the left sidebar.
* **Scraping Strategy Sidebar**: Kept runtime scraping options (Smart Completion, Auto-Cover, Auto-Reading Direction, Force Update) directly visible in the left sidebar for instant workflow changes before batch sync.
* **Unified Central Toolbar**: Merged the library selector (`#lib_selector`) into the central toolbar alongside search and status filters. Searching, status filtering, and library switching are now in one unified horizontal line.
* **Consolidated Mass Execution Block**: Aligned the "Reset Errors / Amnistie" button inside the bottom batch action block, grouping all mass-level executions in a single clean row.
* **Search Input Specificity**: Constrained the search input's width using high-specificity CSS selectors, preventing overlap with the global save button on large screens.

### 📐 Added Ergonomic Features
* **Manual Cover Search**: Added a manual search bar inside the cover selection modal, allowing users to type and search alternate titles without closing the modal or modifying overrides.
* **Live Processing Highlight**: WebSocket logs now trigger an active glowing border/background animation (`.is-processing`) and automatically scroll the series currently being processed into view. Statut badges are updated live without page reload.
* **Workspace Persistence**: Filter selections (Library, Status, Search string, Hide Ignored state) are now saved automatically inside `localStorage` and restored upon loading the dashboard.
* **Quick ID Lookup**: Added a lookup magnifying button next to the AniList ID input field, opening a pre-filled AniList search in a new tab.

### 🐛 Bug Fixes
* Fixed an issue where completed or skipped series during batch runs displayed an `undefined` status badge inside the interface.

FR
### 🎨 Refonte Majeure de l'UI & Ergonomie
* **Modal de Configuration**: Déplacement de toute la configuration technique et d'infrastructure (URL/API Kavita, API DeepL, langues, auto-sync, cascade de fournisseurs) dans une modal d'administration dédiée, aérant complètement la barre latérale.
* **Options Stratégiques Visibles**: Conservation des cases d'exécution de scraping (fusion, sens de lecture, covers, mise à jour forcée) directement accessibles dans la barre latérale gauche pour un ajustement à la volée.
* **Toolbar Centrale Unifiée**: Intégration du sélecteur de bibliothèque directement dans la barre d'outils centrale. Le ciblage, le filtrage et la recherche s'effectuent désormais sur une seule et même ligne horizontale.
* **Grille d'Actions de Masse**: Alignement du bouton « Amnistie des erreurs » au bas de l'écran avec les autres boutons d'actions par lots (Lancer, Ignorer, Arrêter) pour une meilleure cohérence.
* **Taille de la barre de recherche**: Limitation étanche de la largeur de l'input de recherche pour éviter tout chevauchement ou étirement inesthétique contre le bouton de sauvegarde.

### 📐 Fonctionnalités d'Ergonomie Intégrées
* **Recherche Manuelle de Couvertures**: Ajout d'une barre de recherche interne dans la modal des couvertures pour interroger les bases de données avec d'autres titres à la volée.
* **Suivi de Traitement Live**: Les logs WebSocket déclenchent une animation de pulsation lumineuse violette (`.is-processing`) sur la ligne de la série active et la font défiler automatiquement à l'écran. Les badges de statut se mettent à jour en direct.
* **Persistance de l'Espace de Travail**: Sauvegarde automatique de tes filtres (Bibliothèque, Recherche, Statut, Ignorés) dans le `localStorage` pour retrouver ton tableau de bord identique après fermeture.
* **Recherche d'ID Rapide (Quick Lookup)**: Ajout d'un bouton loupe à côté du champ de saisie d'ID AniList pour ouvrir directement une recherche pré-remplie dans un nouvel onglet.

### 🐛 Corrections de Bugs
* Correction d'un bug d'affichage où le badge de statut affichait la valeur textuelle `undefined` lors des sauts de séries déjà enrichies durant un batch.

---

## [1.3.2] - 2026-07-19 (Security & Metadata Overhaul)

EN
### 🛡️ Major Security Audit
* **WSGI Production Server:** Dropped Werkzeug in favor of a robust Gunicorn + Eventlet architecture for production readiness.
* **Global Authentication:** The dashboard can now be locked using the `ADMIN_PASSWORD` Docker variable. Features strict immunity against Timing Attacks (`secrets.compare_digest`) and Brute-Force delays.
* **SSRF Proxy Protection:** The image proxy is now locked behind a strict domain Whitelist (`ALLOWED_PROXY_DOMAINS`), ignoring port bypasses.
* **Webhook Hardening:** Webhook calls are now secured via a cryptographically generated `WEBHOOK_TOKEN`, making it safe to use behind Reverse Proxies.
* **Hidden API Keys:** API keys are physically hidden from the DOM / HTML source code and preserved safely upon saving other settings.

### 🧩 Ultimate Regex Cleaner
* **Centralized Logic:** Title cleaning logic is now decoupled in `scrapers/__init__.py`.
* **Advanced Stripping:** The engine strips stray dots, `[Team]` prefixes, edition keywords (`Omnibus`, `Perfect Edition`), and volume numbers (`01 - Title`), improving the API match rate.

### 📚 Extended Kavita Metadata
* **Rich Staff & Lore:** MetaKavita now pushes Publishers, Age Ratings, Colorists, Translators, and Cover Artists to Kavita.
* **External IDs & WebLinks:** Automatically populates Kavita's native `AniListId`, `MalId`, and `MangaBakaId`. Auto-generates clickable UI WebLinks to display official provider icons right under the manga title!
* **Reading Direction:** New toggle to automatically adapt the reading direction (Manga, Webtoon, Comic) based on the country of origin.

### 🎨 UI Improvements
* **AJAX Search Bar:** Find any series instantly without scrolling.

FR
### 🛡️ Audit de Sécurité Majeur
* **Serveur de Production WSGI :** Abandon de Werkzeug au profit d'une architecture Gunicorn + Eventlet robuste.
* **Authentification Globale :** L'interface peut être verrouillée via la variable `ADMIN_PASSWORD`. Inclut une immunité contre les attaques temporelles et un délai anti-force-brute.
* **Protection Proxy SSRF :** Le proxy d'images est verrouillé par une liste blanche dynamique, insensible aux contournements par port.
* **Webhook Sécurisé :** Les appels Webhook exigent désormais un `WEBHOOK_TOKEN` cryptographique, sécurisant l'usage derrière un Reverse Proxy.
* **Clés API Invisibles :** Les clés API n'apparaissent plus dans le code source HTML (DOM).

### 🧩 Nettoyeur Regex Ultime
* **Logique Centralisée :** Le nettoyage des titres est désormais un module indépendant (`scrapers/__init__.py`).
* **Filtrage Avancé :** Le moteur supprime les points, les préfixes de scantrad, les mots-clés (`Intégrale`, `Deluxe Edition`) et les numéros de dossiers complexes, propulsant le taux de réussite des API.

### 📚 Métadonnées Kavita Étendues
* **Staff et Détails :** MetaKavita gère désormais les Éditeurs, la classification d'Âge, les Coloristes, Traducteurs, et Artistes de Couverture.
* **IDs et Liens Externes :** Remplissage automatique des champs `AniListId`, `MalId`, et `MangaBakaId`. Génération de WebLinks cliquables pour afficher les icônes officielles dans Kavita !
* **Sens de Lecture :** Nouvelle option permettant d'adapter automatiquement le sens de lecture (Manga, Webtoon) selon l'origine de l'œuvre.

### 🎨 Améliorations UI
* **Barre de recherche AJAX :** Filtrez vos centaines de séries instantanément en temps réel.