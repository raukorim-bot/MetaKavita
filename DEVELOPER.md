# MetaKavita - Developer & Contribution Guide

This guide is designed for developers and AI assistants wishing to understand, maintain, or extend the MetaKavita codebase. 

---

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
   * [1. Global Architecture & Security](#1-global-architecture--security)
   * [2. High-Speed Throttling & Rate-Limiting Architecture](#2-high-speed-throttling--rate-limiting-architecture)
   * [3. Reverse Proxy & Subpath Architecture](#3-reverse-proxy--subpath-architecture)
   * [4. Frontend Mechanics, Batch QoS & WebSockets](#4-frontend-mechanics-batch-qos--websockets)
   * [5. Sideloading Scrapers & Auto-Discovery Registry](#5-sideloading-scrapers--auto-discovery-registry)
   * [6. Deep Extraction, Publisher QoS & Unified Scoring](#6-deep-extraction-publisher-qos--unified-scoring)
   * [7. Active Scraper Ecosystem (V1.5.7)](#7-active-scraper-ecosystem-v157)
   * [8. Resilient Translation & Title Fallback](#8-resilient-translation--title-fallback)
   * [9. AI-Powered Scraper Creation (Vibecoding)](#9-ai-powered-scraper-creation-vibecoding)
   * [10. Quality Benchmarking & Debugging Suite](#10-quality-benchmarking--debugging-suite)
   * [11. Critical Pitfalls & Contribution Workflow](#11-critical-pitfalls--contribution-workflow)
   * [12. Modular Architecture (Post-Refactor Module Map)](#12-modular-architecture-post-refactor-module-map)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)
   * [1. Architecture Globale & Sécurité](#1-architecture-globale--sécurité-1)
   * [2. Moteur de Throttling & Régulation Dynamique](#2-moteur-de-throttling--régulation-dynamique-1)
   * [3. Architecture Reverse Proxy & Sous-dossiers](#3-architecture-reverse-proxy--sous-dossiers-1)
   * [4. Frontend, QoS Batch & WebSockets](#4-frontend-qos-batch--websockets-1)
   * [5. Sideloading de Scrapers & Auto-Découverte](#5-sideloading-de-scrapers--auto-découverte-1)
   * [6. Extraction Profonde, QoS Éditeurs & Scoring](#6-extraction-profonde-qos-éditeurs--scoring-1)
   * [7. Écosystème des Scrapers Actifs (V1.5.7)](#7-écosystème-des-scrapers-actifs-v157-1)
   * [8. Traduction Résiliente & Titre de Secours](#8-traduction-résiliente--titre-de-secours-1)
   * [9. Création de Scrapers via IA (Vibecoding)](#9-création-de-scrapers-via-ia-vibecoding-1)
   * [10. Suite de Tests & Débogage Qualité](#10-suite-de-tests--débogage-qualité-1)
   * [11. Pièges Critiques & Flux de Contribution](#11-pièges-critiques--flux-de-contribution-1)
   * [12. Architecture Modulaire (Plan des Modules Post-Refactor)](#12-architecture-modulaire-plan-des-modules-post-refactor-1)

---

## 🇺🇸 English Developer Guide

### 1. Global Architecture & Security
MetaKavita is an asynchronous Python application powered by a **Gunicorn WSGI server** with **Eventlet** workers to support real-time WebSockets via Flask-SocketIO.

*   **Security Layer:** Global authentication is enforced via `@app.before_request`. Session cookies are configured as `HttpOnly` and `SameSite=Lax` (optional `SESSION_COOKIE_SECURE=1` behind HTTPS). Timing attacks are prevented using `secrets.compare_digest`. CSRF tokens (`csrf_utils.py`) are validated on state-changing POSTs; the frontend injects `X-CSRF-Token` on mutating `fetch` calls. `SECRET_KEY` is generated on first boot — never a public hardcoded fallback.
*   **SSRF Protection:** Shared allowlist helper (`url_allowlist.py`) for cover downloads and `/api/proxy-image` — http(s) only, no credentials/localhost/private IPs, up to 3 redirects with each hop re-validated (`fetch_with_safe_redirects`), safe `image/*` MIME. Domain lists come from `ScraperRegistry.get_all_proxy_domains()` (covers community scrapers too).
*   **Credential-safe logging:** Use `secure_logging.safe_exc_str()` / `redact_secrets()` when logging exceptions that may include authenticated URLs (Kavita `apiKey`, ComicVine `api_key`, etc.) — never log raw `str(e)` after such calls.
*   **Webhook Hardening:** Webhooks require a cryptographically secure `WEBHOOK_TOKEN` generated in `data/config.json` (CSRF-exempt; token auth only).
*   **Safe SQLite Schema Migrations:** Database updates in `db_manager.py` use a safe `_ensure_schema` method that handles `sqlite3.OperationalError` gracefully per column, preventing fatal container crashes when introducing new features.
*   **Pure Base64 Kavita Uploads:** Kavita requires cover uploads to be sent as pure Base64 byte strings (`kavita_api.py`). Prepending `Data URI` schemas (`data:image/jpeg;base64,...`) results in silent Kavita C# backend failures (the "Phantom Cover" syndrome).

---

### 2. High-Speed Throttling & Rate-Limiting Architecture
MetaKavita eliminates hardcoded thread sleep delays in favor of a **Timestamp-Based Dynamic Throttler** (`LAST_REQUEST_TIMES`).
Idle APIs respond instantly with zero artificial delay, executing 3-provider Smart Fusions in ~1.6s. High-volume batch requests throttle each scraper strictly according to its declared `rate_limit` (e.g., 0.2s for MangaBaka, 1.0s for AniList) at maximum theoretical throughput, providing immunity against HTTP 429 errors.

---

### 3. Reverse Proxy, Subpath & CORS Architecture
MetaKavita natively supports deployment under custom URL subpaths (e.g. `https://domain.com/metakavita`).
Reverse proxy headers (`X-Forwarded-Prefix`) are processed via Werkzeug's `ProxyFix`. In addition, if a user specifies an explicit subpath using the `ROOT_PATH` environment variable in Docker, a custom `ScriptNameStripper` WSGI middleware handles path rewriting. Client-side, `window.ROOT_PATH` dynamically prefixes all AJAX calls.

**CORS whitelist (Docker env `CORS_ALLOWED_ORIGINS`)** — for self-host HTTPS domains (e.g. `https://….local.ltd`) where Same-Origin alone blocks Socket.IO / cross-origin AJAX. Comma-separated **explicit** origins only; empty = Same-Origin (no broad CORS). Applied to both Flask HTTP (`after_request` + OPTIONS preflight, with credentials) and `socketio.init_app(cors_allowed_origins=…)`. `*` is rejected. This does **not** replace reverse-proxy WebSocket upgrade (`Upgrade` / `Connection`) configuration — see `cors_config.py` and `app.py`.

**`KAVITA_URL` vs `KAVITA_EXTERNAL_URL`** — API calls always use `KAVITA_URL` (safe for Docker-internal hostnames like `http://kavita:5000`). Browser series links use `get_kavita_ui_url()` (`config_manager.py`), which prefers `KAVITA_EXTERNAL_URL` (public reverse-proxy URL) and falls back to `KAVITA_URL` when unset. The topbar/About **Kavita+** button uses `get_kavita_plus_url()` → `{ui}/settings#admin-kavitaplus` (wiki fallback if no UI URL is configured).

**`KAVITA_HTTP_TIMEOUT`** — seconds for Kavita **write** POSTs (metadata 2-pass, series update 2-pass, cover upload). Default `60`. Env or `config.json`. If pass 1 (write) succeeds and pass 2 (re-lock) times out, `update_series_metadata` / `update_series_general` return soft success with a warning log.

**`MAX_TAGS`** — max tags pushed to Kavita. Default `15` (clamped 1–100). Env or `config.json` only — **not** in the Config modal. Use `get_max_tags(config=None)` from `config_manager` in scrapers (`tags[:get_max_tags()]`) and in `services/enrichment_engine.py` when building the Kavita payload (`get_max_tags(config)`).

**`MAX_GENRES`** — max genres pushed to Kavita. Default `5` (clamped 1–50). Env or `config.json` only — **not** in the Config modal. Use `get_max_genres(config=None)` in scrapers (`genres[:get_max_genres()]`) and in `services/enrichment_engine.py` when building the Kavita payload (`get_max_genres(config)`).

---

### 4. Frontend Mechanics, Batch QoS & WebSockets

#### A. Live Cover Streaming
Manual cover searches stream image results live over WebSockets via `socketio.start_background_task` and `socketio.sleep(0)`.
Frames are filtered client-side by `series_id`. A chronological `stream_id` token (reject stale frames from a previous search on the same series) is the intended hardening documented historically for BF11 — **not yet implemented** in `covers.js` / `sockets/handlers.py`; do not assume it is present when debugging race conditions.

#### B. Smart Auto-Cover Locking
When a user manually selects a cover from the modal, the client instantly triggers an AJAX call to uncheck the specific "Cover" checkbox in the series override panel. This locks the manual choice and protects it from being overwritten by global `AUTO_COVER` tasks during the next batch.

#### C. Batch selection persist & auto-uncheck (v1.6.1)
* `static/js/batch.js` — `saveBatchSelection()` / `restoreBatchSelection()` store checked series IDs in `localStorage` under `mk_batch_selection:{libraryId|all}`. Filters hide rows without unchecking them.
* `static/js/websocket.js` — on enrichment success (✅ / ⏭️), `uncheckSeriesForBatchResume()` clears the checkbox and updates storage.

#### D. Ephemeral batch targeted-fields mask (v1.6.1)
* Sidebar checkboxes `.batch-field-cb` → `getBatchTargetedFieldsMask()` (null if all 12 checked).
* `POST /batch-sync` may include `targeted_fields`; worker unpacks a 3- or 4-tuple and passes `targeted_fields_override` to `enrich_series()`.
* `resolve_active_fields()` in `services/enrichment_engine.py` — override primes over the series cache for that run only (write filter; providers are still fully scraped).

#### E. Lifetime stats & live KPIs (v1.6.1 / C7)
* SQLite `lifetime_stats` keys: `series_enriched`, `matches_won`, `series_missed` via `record_enrichment_telemetry` / `record_enrichment_miss`.
* After record, `_broadcast_enrichment_stats` emits Socket.IO `enrichment_stats` with absolute `lifetime` + deltas.
* Topbar KPIs + session counter (`sessionStorage` key `mk_session_processed`) in `websocket.js`. Playful `/stats` uses `services/stats_service.py` + Chart.js.

#### F. Batch progress bar (v1.6.1)
* `services/background_tasks.py` — `broadcast_batch_progress(remaining, active=…)` on each worker start; `{remaining: 0}` when the queue empties; `{stopped: true}` on `drain_sync_queue()` / `/stop-batch`.
* `static/js/batch.js` — `showBatchProgress(ids.length)` at launch; `applyBatchProgressPayload()` computes `done = total - remaining - (active ? 1 : 0)`.
* `static/js/websocket.js` — listens for Socket.IO `batch_progress`.

#### G. Reliability barometer (v1.6.1)
* Config keys `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD` (clamped `[0.30, 1.00]`).
* Runtime threshold: `scrapers/utils.py::get_match_accept_threshold()` (custom off → always `0.60`). Official scrapers + `_safe_match_score` / `attach_match_score` fallbacks use the getter.

---

### 5. Sideloading Scrapers & Auto-Discovery Registry

MetaKavita features a **Dual-Sourced Auto-Discovery Registry** (`ScraperRegistry`). 
On startup, `scrapers/__init__.py` scans two distinct locations and uses `importlib.util` to dynamically load classes inheriting from `BaseScraper`:
1.  **Internal Core Scrapers:** Located in the Docker image (`/app/scrapers/`).
2.  **Community Sideloaded Scrapers:** Located in the user-mounted volume (`/app/data/scrapers/`).

If a custom scraper declares `needs_api_key = True`, MetaKavita will dynamically generate a password input in the UI Config Modal and load its value without requiring any frontend code modification.

---

### 6. Deep Extraction, Publisher QoS & Unified Scoring

#### A. Deep Extraction & True Context Reset
Before querying external APIs, MetaKavita fetches the existing metadata already stored in Kavita (Sanitized ISBN, Authors).
If a user triggers a **Context Reset** (`RESET_CONTEXT_ON_FORCE = True`), MetaKavita explicitly purges the ISBN from the local context. This is crucial because the ISBN is evaluated as a 100% Golden Rule match. If a corrupted ISBN remains in Kavita, no force update can bypass it.

#### B. Unified Weighted Scoring Matrix (`scrapers/utils.py`)
Scrapers build candidate dictionaries and evaluate them using `score_candidate`:
1.  **ISBN Golden Rule**: Exact sanitized ISBN match = 1.0 (100%).
2.  **Anti-Homonym Penalty**: If Kavita context has an author and candidate author similarity is `< 0.35`, a `-50%` penalty is applied.
3.  **Anti-Spin-Off Filters**: Missing distinctive query words penalizes the score by `-35%`.
4.  **Volume 1 Anchoring**: Grants `+0.10` bonus to Volume 1 while inflicting `-0.45` penalty to intermediate volumes.

The score returned by `score_candidate()` is only useful relative to a shared acceptance
threshold: `scrapers/utils.py::MATCH_ACCEPT_THRESHOLD` (currently `0.60`). It used to be a
literal duplicated in every scraper file (`0.50` for most, `0.60` for Hardcover/OpenLibrary,
even `0.45` for Manga-News/Shikimori) — `0.50` (and a fortiori `0.45`) was tested in real-world
usage and produced too many false positives (homonyms/spin-offs wrongly accepted), so `0.60` is
now the single validated value, centralized so every scraper stays in sync.

**All 9 search-based scrapers now call `score_candidate()`.** `mangadex.py`, `mangaupdates.py`,
`manganews.py` and `shikimori.py` used to implement their own title-only heuristic with no
author cross-check at all — meaning the anti-homonym protection (category A) never applied to
them. Each was migrated to build a *complete* candidate (including `staff`) before scoring:
- `mangadex.py`: the search endpoint already returns author/artist via `includes[]=author,artist`,
  so building the full candidate per search result costs zero extra HTTP calls. A MangaDex-specific
  "oneshot" penalty (no equivalent in the shared matrix) is still applied as a local adjustment
  on top of the `score_candidate()` result.
- `mangaupdates.py`: the search endpoint's `record` has the same shape as the detail endpoint
  (same `authors`/`associated`/`publishers` keys), so `_parse_series_record()` is reused directly
  on search results — no extra HTTP call needed either.
- `shikimori.py`: staff requires a 3rd HTTP call per candidate (`/roles`). To bound the cost, a
  cheap title-only pre-filter (no extra request) runs first; `/roles` is only fetched for
  candidates that clear it.
- `manganews.py`: HTML search results carry no author at all (only title + URL); fetching the
  detail page (which has staff) for every result would multiply requests against a
  Cloudflare-protected site. Instead, the top **3** candidates by cheap title pre-filter get
  their detail page fetched and scored via `score_candidate()` — a bounded compromise between
  match accuracy and site load.

See `tests/test_scraper_score_migration.py` for proof that each scraper's staff output is in the
shape `score_candidate()` expects.

#### C. Publisher Preference QoS
Users can dictate whether they want Localized Publishers (*Viz Media*, *Glénat*) or Original Japanese Publishers (*Shueisha*). 
This is handled via a global variable `PUBLISHER_PREFERENCE` and overridden individually per series using a Segmented UI Toggle. The value is injected directly into `existing_metadata['publisher_pref']` for scrapers to read during extraction.

#### C2. Localized Titles Policy (`localized_titles.py`, issue #12 / C53)
Kavita `localizedName` is built from provider `titles[{lang,value}]` (fallback: flat `alternative_titles`). Global modes via `LOCALIZED_TITLE_MODE` (`all` | `prefer` | `none`) and optional `LOCALIZED_TITLE_LANGS`. Per-series `alt_title_langs` (non-empty) forces `prefer` for that series. **Series `name` is never rewritten** — V1 scope is `localizedName` only. Default `all` keeps the historical multi-title `" / "` join. AniList / MangaDex / Kitsu emit structured titles; Smart Completion merges via `merge_title_entries`.

#### D. Smart Scoring: Score-Based Selection & Two-Wave Parallel Execution (`metadata_fetcher.py`)
Controlled by the sidebar toggle `SMART_SCORING` (same Options card as `SMART_COMPLETION`).
Default is **on**. When **off**, MetaKavita restores the classic sequential fallback: first useful
provider in list order wins; Smart Completion (if enabled) fills gaps in that same list order,
with no score comparison and no parallel wave.

Before v1.6, `fetch_metadata()`'s cascade already queried **every** configured provider for every
series (there was never an early exit after the first success) — but it blindly kept whichever
provider happened to be **first** in the user's fallback list (`PROVIDER_1/2/3`) as the winner,
even when a later provider had an objectively better match for that specific query. Subsequent
providers only contributed via `SMART_COMPLETION` gap-filling, in raw list order.

Two independent improvements were made on top of the unified scoring matrix (§6.B):

1. **Score-based winner selection.** Every scraper that calls `score_candidate()` now attaches its
   own winning score to the returned dict via `attach_match_score()` (key `_match_score`, see
   `scrapers/utils.py`). Direct ID/URL lookups (`is_id=True`) attach `1.0` — an explicit
   identifier lookup has no ambiguity to score. `fetch_metadata()` collects every accepted
   candidate, then sorts them by score descending (ties broken by original fallback-list
   position) before picking a winner. If `SMART_COMPLETION` is enabled, gap-filling now follows
   this same score-descending order instead of the raw list order — the most trustworthy
   candidate's fields win a "which value fills this gap" contest, not the one that merely
   happened to run first. A candidate with no `_match_score` (e.g. a community scraper not yet
   migrated to `score_candidate()`) is treated as "just barely accepted"
   (`MATCH_ACCEPT_THRESHOLD`) rather than crashing the sort or being unfairly favored.
2. **Two-wave execution.** Provider #1 still runs alone and sequentially first; whatever ISBN/
   authors it finds are merged into `existing_metadata` and handed to the *remaining* providers,
   which then run **in parallel** (`ThreadPoolExecutor`) against a frozen snapshot of that
   enriched context. This is a deliberate compromise, not a naive "fire everything at t=0":
   running everything in parallel from the start would lose the existing context-cascading
   benefit (provider #1's ISBN/authors feeding `score_candidate()`'s ISBN Golden Rule and
   anti-homonym penalty for providers #2/#3), which matters most on "cold" series with little or
   no pre-existing Kavita metadata. Per-provider rate-limiting (`throttle_provider()`) is already
   keyed by `scraper.id` with its own lock (see §3 below), so parallelizing *different* providers
   never violates any individual provider's `rate_limit`. No scraper instance mutates `self`
   during `fetch()`, so running distinct provider singletons concurrently is safe.

Since call volume is unchanged (every configured provider was already being queried), this is
purely a latency win (`max()` instead of `sum()` of the non-P1 providers' round-trips) plus a
quality win (best match wins, not first match). See
`tests/test_metadata_fetcher_smart_scoring.py` for the full regression suite, including a timing
assertion proving providers #2+ actually overlap in wall-clock time.

**Community scrapers:** `BaseScraper.uses_unified_scoring` defaults to `False` (opt-in). Declaring
`uses_unified_scoring = True` is documentary — the pipeline never gates on it. Safety comes from
`_safe_match_score()` in `metadata_fetcher.py`, which coerces/clamps any missing or malformed
`_match_score` so a community scraper that forgets `attach_match_score()` (or returns garbage)
cannot crash enrichment. See `CUSTOM_SCRAPERS.md` §4.

---

### 7. Active Scraper Ecosystem (V1.5.7)

| Scraper ID | Provider Name | Types | Key Features |
| :--- | :--- | :--- | :--- |
| `ANILIST` | AniList | Manga, Comic, Book | GraphQL API, spin-off penalties, native `AniListId` mapping. |
| `BEDETHEQUE` | Bédéthèque | Comic | Franco-Belgian BD scraper, `curl_cffi` CSRF bypass. |
| `COMICVINE` | ComicVine | Comic | API Key required. Primary publisher weighting, Issue #1 fallback. |
| `GOOGLEBOOKS` | Google Books | Book, Comic | API Key required. Dynamic `langRestrict`, ISBN targeting. |
| `HARDCOVER` | Hardcover (Exp) | Book, Comic | API Key required. Hasura GraphQL API & Typesense search. |
| `KITSU` | Kitsu | Manga | JSON:API integration, no API key required. |
| `MANGANEWS` | Manga-News | Manga | VF French catalog scraper, extracts HD webp covers. |
| `MANGABAKA` | MangaBaka | Manga, Book | `schema=full`, `type` filter (novel for Book), Publisher Preference support. |
| `MANGADEX` | MangaDex | Manga | Content rating filters (`erotica`), oneshot penalties. |
| `MANGAUPDATES`| MangaUpdates | Manga | `hit_title` matching, Publisher Preference support. |
| `OPENLIBRARY` | Open Library | Book, Comic | ISBN support, anti-429 retries, Google Disclaimer bypass. |
| `SHIKIMORI` | Shikimori | Manga | Multilingual title matching, `/roles` staff extraction. |
| `WIKIDATA` | Wikidata | Manga, Comic, Book | SPARQL + Entity API; Magic Input Q-id; shared `wikidata_map`. |

---

### 8. Resilient Translation & Title Fallback
Translations are managed in `translator.py` with an auto-failover pipeline (Azure -> DeepL -> Google).
**Title Translation Fallback:** If a search query yields no results, MetaKavita can automatically translate the localized query to English (the pivot language for APIs like MangaDex and AniList) and run a second scraping cascade.

---

### 9. AI-Powered Scraper Creation (Vibecoding)
Creating a custom scraper requires strict adherence to the `BaseScraper` contract. 
Please refer to the `CUSTOM_SCRAPERS.md` file located at the root of the project for the exact "Vibecoding" AI Prompts to help the community build and sideload custom providers.

---

### 10. Quality Benchmarking & Debugging Suite
Developers can run standalone unit test scripts located at the project root (`debug_all_scrapers.py`, `debug_scoring_20.py`, `debug_manga_quality.py`) to validate engine features and API compliance without needing a running Kavita server. Cover uploads can be traced using `debug_cover.py`.

**Batch wall-clock benchmark (all heavy options on):** `python debug/benchmark_batch.py --limit 10` — sequential enrich like the real worker, with Smart Scoring / Smart Completion / title fallback / reset-on-force / auto-cover forced on. Prompts interactively for the **Kavita API token** (getpass). Default is **dry-run** (real scrape + translation, Kavita writes mocked). Use `--live --i-know` only when you intentionally want force-updates written to Kavita.

Since the architecture refactor, there is also an automated **pytest** suite under `tests/` (see §12 below) that runs on every push/PR via `.github/workflows/tests.yml`. Unlike the `debug_*.py` scripts (interactive, opinion-based exploration scripts meant to be read and extended by a human), `tests/` is a fast, mocked, CI-enforced regression net targeted specifically at bugs that have already bitten this project once (`publisher_pref` disappearing, Kavita payload sanitization, MangaBaka status mapping) — it must stay green at all times. Run it locally with `pip install -r requirements-dev.txt && pytest`.

---

### 11. Critical Pitfalls & Contribution Workflow

This section codifies real production bugs found and fixed during deep audits of the codebase. Read it **before** modifying `app.py`, `kavita_api.py`, `db_manager.py`, or any scraper.

#### A. Docker-First Development — There Is No Hot-Reload
MetaKavita runs exclusively inside a Docker container (Gunicorn + Eventlet), with `data/` mounted as a persistent volume for `cache.db` and `config.json`. Editing a `.py` file on disk has **zero effect** until the image is rebuilt and the container restarted. The single most common cause of "I fixed it but it's still broken" reports is a stale image. Before investigating a regression that "should" already be resolved by a prior code change, always confirm the container was actually rebuilt.

#### B. Kavita's API Is Not a Typical REST API — Read `kavita_api.md` First
Before touching any code path that calls into `kavita_api.py`, read `kavita_api.md` end-to-end. Two rules are non-negotiable and have both caused real, user-facing production incidents:

1. **Never send a partial payload to `POST /api/Series/update`.** Kavita's `SeriesController`/`UpdateSeriesDto` has **no null-guard** on several fields — `localizedName` in particular. If your update logic only intends to change `format`, but omits `localizedName` from the JSON body, Kavita's C# backend deserializes the missing key as `null`, **overwrites** the existing value in the database, and additionally **resets** `nameLocked` / `sortNameLocked` / `localizedNameLocked` to `false` — even though those fields were never meant to be touched. This exact regression silently corrupted alternate titles for real users and crashed a third-party OPDS client (KOReader's "Kamare" plugin), which assumed `localizedName` would always be a string and choked on the resulting `null`. **The mandatory fix pattern:** always `GET /api/Series/{id}` first, merge your intended change into the *complete* current state, and only then `POST` the full object back. See `KavitaAPI.update_series_general()` for the reference implementation of this GET-merge-POST pattern.
2. **Sanitize GET-only / computed fields before every `POST`.** Properties like `created`, `lastModified`, `totalCount`, `maxCount`, `pages`, and `wordCount` are returned by Kavita's `GET` endpoints but must never be echoed back in a `POST` body — doing so risks triggering Entity Framework Core concurrency exceptions server-side. This sanitization is centralized **once** inside `KavitaAPI.update_series_metadata()`. Do not re-implement a partial version of it ad-hoc in `app.py` or inside a scraper — that exact kind of duplication (only stripping `created`/`lastModified` in one place while forgetting `maxCount`/`totalCount`) is how a `maxCount: -100000` payload once reached Kavita and crashed a sync.
3. **Respect the 2-pass Lock Guard protocol** (`Unlock → Write → Lock`, documented in `kavita_api.md` §1.B/1.C) whenever your code needs to overwrite a field the user may have manually locked in Kavita's UI.

#### C. Trace New Settings Through the *Entire* Chain, Not Just One File
The per-series Publisher Preference toggle (`VF/VA` vs `VO`, v1.5.7) shipped with fully correct code in the HTML template, the JS payload builder, both scrapers' extraction logic, *and* the SQLite schema — yet was completely inert in practice, because a single Flask route (`/save-override`) read the submitted value into a local variable and then simply never forwarded it to `save_forced_overrides()`. No single file was wrong in isolation; the bug only existed in the gap between files. **Whenever you add or touch a per-series or global setting, manually trace it end-to-end**: HTML input → `script.js` payload construction → Flask route parameter extraction → `db_manager.py` write → `db_manager.py` read → `existing_metadata` construction in `app.py` → scraper consumption. A fast way to catch this class of bug is to grep every call site of the persistence function (e.g. `save_forced_overrides(`) and diff the argument list against the function signature.

#### D. Centralize, Don't Duplicate, Sanitization & Mapping Logic
Several bugs in this codebase share the same root cause: a rule (a status enum mapping, a payload sanitization rule, a lock-flag convention) gets implemented once in a helper function, then partially re-implemented "just in case" in a caller, and the two definitions silently drift apart over time (e.g. MangaBaka's raw `"completed"` status never matching the internal `"FINISHED"` key expected by `app.py`). Prefer adding new logic exactly once — in `kavita_api.py` for anything Kavita-payload-shaped, or `scrapers/utils.py` for anything scraper-contract-shaped — and make every call site depend on that single source of truth instead of re-deriving it locally.

#### E. Testing Without a Live Kavita Instance
Use the standalone `debug_*.py` scripts at the project root to validate logic changes before touching a real server:
* `debug_all_scrapers.py` / `debug_scoring_20.py` / `debug_manga_quality.py`: scoring engine and scraper-contract regression tests.
* `debug_publisher.py`: dumps the raw `publishers` payload from the MangaBaka/MangaUpdates APIs and runs the `LOCALIZED`/`ORIGINAL` extraction logic side-by-side to verify the Publisher Preference feature.
* `debug_cover.py` / `debug_concurrency.py`: cover upload payload shape validation and cache race-condition checks.
* `debug/benchmark_batch.py`: sequential batch wall-clock with all heavy options forced on (`--limit`, `--library-id`, `--ids`; dry-run by default; `--live --i-know` for real Kavita writes).

When fixing a bug, extend one of these scripts (or add a new one) to reproduce it first — it's the fastest way to confirm a fix is real without a full Docker rebuild and manual click-through in the Kavita UI.

#### F. Documentation Is Part of the Change
Every user-facing fix or feature must be reflected in **both** `CHANGELOG.md` (bilingual EN/FR, semantically versioned — the topmost `## [X.Y.Z]` header is parsed automatically by `services/changelog_service.py::get_app_version()` to drive the version number shown in the UI) and `ROADMAP.md` (bilingual short-form `BFxx`/`Cxx` entries). Keep the two in sync: every `BF`/`C` number referenced in `ROADMAP.md`'s "Latest Releases" section should correspond to a detailed entry in `CHANGELOG.md`, and the version range shown at the top of that section should always match the newest `CHANGELOG.md` entry.

### 12. Modular Architecture (Post-Refactor Module Map)
Starting with the architecture refactor, `app.py` is a thin ~130-line assembly point only: Flask/SocketIO instantiation, middlewares (`ProxyFix`, `ScriptNameStripper`), logging bootstrap, the global `require_login` gate, Blueprint registration, and starting the background workers. All business logic lives in dedicated modules:

*   **`kavita_constants.py`**: single source of truth for Kavita enum mappings (`PUBLICATION_STATUS_MAP`, `AGE_RATING_MAP`, `resolve_kavita_format_enum()`) and raw-provider-status normalization (`normalize_provider_status()`, used by `scrapers/mangabaka.py`). Add new enum mappings here, never inline in a route or scraper.
*   **`models.py`**: `SeriesOverride` dataclass, the typed contract for per-series overrides (forced ID/provider, alternative title, targeted fields, publisher preference, `alt_title_langs`). Prefer `db_manager.save_series_override(SeriesOverride(...))` (named fields) over the legacy positional `save_forced_overrides(...)` wrapper in any new code — this is a direct, structural mitigation for the class of bug described in §11.C.
*   **`extensions.py`**: the shared `socketio = SocketIO()` instance (created without an app, `init_app(app)`'d once in `app.py`). Import from here — never from `app.py` — in any module that needs to emit events or declare `@socketio.on(...)` handlers, to avoid circular imports.
*   **`services/enrichment_engine.py`**: `enrich_series(series_id, series_name, force_update, targeted_fields_override=None)`, the extracted former `process_series_logic()`. Pure orchestration — scraping, field mapping, Kavita calls, lifetime telemetry broadcast — with zero dependency on Flask or `app.py`.
*   **`services/background_tasks.py`**: the daemon workers (`sync_queue` consumer + periodic auto-sync poller) and `start_background_workers()`, called once from `app.py` at import time (unchanged single-worker-process behavior, required for Gunicorn `-w 1`). Queue items are 3-tuples `(id, name, force)` or 4-tuples with ephemeral `targeted_fields`.
*   **`services/stats_service.py`**: playful `/stats` metrics + Chart.js payload from lifetime counters + cache snapshot.
*   **`services/changelog_service.py`**: `get_app_version()` / `get_current_version()` (cached) / `get_full_changelog_html()`. Imported independently by both `app.py` (global template context) and `routes/misc.py` (`/api/changelog`) — importing from here instead of from each other avoids a circular import.
*   **`routes/*.py`**: one Flask Blueprint per domain — `auth` (`/login`, `/logout`), `pages` (`/`, `/stats`), `config` (`/save-config`, `/regenerate-webhook-token`), `series` (`/save-override`, `/toggle-ignore`, cover search/apply), `sync` (`/force-sync`, `/batch-sync`, `/stop-batch`, `/reset-errors`, `/export-errors`, `/webhook`), `misc` (`/api/proxy-image`, `/api/changelog`).
*   **`sockets/handlers.py`**: the two Socket.IO event handlers (`connect`, `fetch_covers_stream`), registered by decorating the shared `extensions.socketio` instance; imported once for side effects from `app.py`.
*   **`static/js/*.js`**: the former monolithic `script.js` is now 7 plain `<script>` files loaded in dependency order (`utils.js` → `websocket.js` → `overrides.js` → `covers.js` → `config.js` → `batch.js` → `main.js`). No bundler and no `type="module"` on purpose: templates rely on inline `onclick="..."` handlers, which require every function to stay in the global scope.
*   **`templates/partials/*.html`**: the former monolithic `index.html` is now a thin shell that `{% include %}`s six Jinja partials — `_sidebar.html`, `_toolbar.html`, `_series_row.html`, `_config_modal.html`, `_cover_modal.html`, `_changelog_modal.html` — one per self-contained UI region. Edit the relevant partial directly instead of scrolling through a single 600+ line template.
*   **`tests/`**: the pytest safety net (`conftest.py` fixtures + domain tests such as `test_db_manager.py`, `test_kavita_api.py`, `test_playful_stats.py`, `test_batch_targeted_fields.py`, `test_comic_flexible.py`, `test_scraper_mangabaka.py`, `test_routes_series.py`, `test_max_tags.py`, `test_max_genres.py`, `test_scraper_max_caps.py`, `test_audit_c1_c3.py`, `test_fallback_query.py`, `test_metadata_fetcher_smart_scoring.py`, …). Fixtures never touch the real `data/` folder or the network — `isolated_db` monkeypatches `db_manager.DB_FILE`/`DATA_DIR` to a `tmp_path` SQLite file, `flask_app`/`client` build a minimal Flask app registering only `routes/series.py` (not the full `app.py`, to avoid spinning up real background workers/logging), and `mock_kavita_api` stubs out every `KavitaAPI` network method. See §10. Also note shared helpers: `url_allowlist.py`, `csrf_utils.py`, `cors_config.py`.

⚠️ **Blueprint endpoint names changed.** Flask always prefixes a Blueprint route's endpoint with the Blueprint's name (e.g. the `login` view in `routes/auth.py`, registered on the `auth` Blueprint, becomes endpoint `auth.login` — there is no way to opt out of this prefixing). Every `url_for(...)` call and the `request.endpoint in [...]` whitelist in `app.py::require_login()` were updated accordingly (`auth.login`, `pages.index`, `pages.stats`, `auth.logout`, `sync.export_errors`, `sync.webhook`). **If you rename a Blueprint or move a route to a different Blueprint, grep for its old endpoint string across `app.py` and every `.html` template before assuming `url_for()` still resolves.**

<br><br>

---

## 🇫🇷 Guide de Développement Français

### 1. Architecture Globale & Sécurité
MetaKavita est une application Python asynchrone fonctionnant derrière un serveur **WSGI Gunicorn** couplé à des workers **Eventlet** pour supporter les WebSockets en temps réel.

*   **Sécurité :** L'authentification utilise `secrets.compare_digest` contre les attaques temporelles. Les webhooks exigent un jeton cryptographique (`WEBHOOK_TOKEN`). CSRF sur les POST mutatifs (`csrf_utils.py` + header frontend). `SECRET_KEY` générée au boot — pas de fallback public hardcodé.
*   **Protection SSRF :** Allowlist partagée (`url_allowlist.py`) pour upload de couvertures et `/api/proxy-image` (http(s), pas d'IPs privées, jusqu'à 3 redirects re-validés, MIME image). Les `proxy_domains` des scrapers (y compris communautaires) alimentent la liste.
*   **Logs sans fuite de clés :** utiliser `secure_logging.safe_exc_str()` / `redact_secrets()` pour les exceptions susceptibles de contenir des URLs authentifiées (ne jamais logger `str(e)` brut après ces appels).
*   **Migrations SQLite Sécurisées :** Le `db_manager.py` met à jour les colonnes de la BDD une par une en interceptant silencieusement les erreurs `sqlite3.OperationalError` pour éviter les crashs de conteneur 500.
*   **Upload Kavita en Base64 Pur :** Le moteur C# de Kavita refuse les uploads d'images commençant par le schéma `Data URI`. L'envoi doit impérativement se faire en chaîne de caractères Base64 pure pour être écrit de manière permanente sur le disque dur.

---

### 2. Moteur de Throttling & Régulation Dynamique
Les pauses fixes ont été remplacées par un **Régulateur Dynamique par Horodatage (`LAST_REQUEST_TIMES`)**. Les API inactives répondent à 0.0s de délai, exécutant une fusion de 3 sources en ~1,6s. Lors d'un batch, le système régule parfaitement chaque source à sa vitesse maximale théorique (`rate_limit`).

---

### 3. Architecture Reverse Proxy, Sous-dossiers & CORS
Le système gère les sous-chemins (ex: `https://domaine.com/metakavita`) via `ProxyFix` pour récupérer les headers `X-Forwarded-Prefix` et un middleware `ScriptNameStripper`. Côté frontend, `window.ROOT_PATH` préfixe toutes les routes.

**Whitelist CORS (env Docker `CORS_ALLOWED_ORIGINS`)** — pour les self-hosts HTTPS (ex: `https://….local.ltd`) où le Same-Origin seul bloque Socket.IO / AJAX cross-origin. Origins **explicites** séparées par des virgules ; vide = Same-Origin. Appliquée à Flask HTTP (`after_request` + preflight OPTIONS, avec credentials) et à `socketio.init_app(cors_allowed_origins=…)`. `*` est rejeté. Cela ne remplace **pas** la config reverse-proxy d'upgrade WebSocket (`Upgrade` / `Connection`) — voir `cors_config.py` et `app.py`.

**`KAVITA_URL` vs `KAVITA_EXTERNAL_URL`** — les appels API utilisent toujours `KAVITA_URL` (hostname Docker interne OK, ex: `http://kavita:5000`). Les liens série du navigateur passent par `get_kavita_ui_url()` (`config_manager.py`), qui préfère `KAVITA_EXTERNAL_URL` (URL publique / reverse proxy) et se rabat sur `KAVITA_URL` si elle est vide. Le bouton **Kavita+** (topbar / À propos) utilise `get_kavita_plus_url()` → `{ui}/settings#admin-kavitaplus` (repli wiki si aucune URL UI).

**`KAVITA_HTTP_TIMEOUT`** — secondes pour les POST d'**écriture** Kavita (metadata 2-pass, update série 2-pass, upload couverture). Défaut `60`. Env ou `config.json`. Si le passage 1 (écriture) réussit et le passage 2 (re-lock) timeout, `update_series_metadata` / `update_series_general` renvoient un soft-success avec warning en log.

**`MAX_TAGS`** — nombre max de tags poussés vers Kavita. Défaut `15` (borné 1–100). Env ou `config.json` uniquement — **pas** dans la modal Config. Utiliser `get_max_tags(config=None)` depuis `config_manager` dans les scrapers (`tags[:get_max_tags()]`) et dans `services/enrichment_engine.py` pour le payload Kavita (`get_max_tags(config)`).

**`MAX_GENRES`** — nombre max de genres poussés vers Kavita. Défaut `5` (borné 1–50). Env ou `config.json` uniquement — **pas** dans la modal Config. Utiliser `get_max_genres(config=None)` dans les scrapers (`genres[:get_max_genres()]`) et dans `services/enrichment_engine.py` pour le payload Kavita (`get_max_genres(config)`).

---

### 4. Frontend, QoS Batch & WebSockets

#### A. Streaming de couvertures
Les recherches manuelles de couvertures streamment les images via `socketio.start_background_task` et `socketio.sleep(0)`.
Les frames sont filtrées côté client par `series_id`. Un jeton chronologique `stream_id` (rejeter les frames d’une recherche précédente sur la même série) est le durcissement historiquement documenté pour BF11 — **pas encore implémenté** dans `covers.js` / `sockets/handlers.py` ; ne pas l’assumer en debug de courses.

#### B. Verrouillage Anti-Écrasement
Appliquer une couverture manuellement via l'interface envoie un second signal AJAX qui décoche la case "Couverture" dans les options de la série. Cela protège la série en empêchant l'option globale `AUTO_COVER` de l'écraser lors des batchs ultérieurs.

#### C. Persistance de sélection & décochage auto (v1.6.1)
* `static/js/batch.js` — `saveBatchSelection()` / `restoreBatchSelection()` stockent les IDs cochés dans `localStorage` sous `mk_batch_selection:{libraryId|all}`. Les filtres masquent sans décocher.
* `static/js/websocket.js` — en cas de succès (✅ / ⏭️), `uncheckSeriesForBatchResume()` décoche et met à jour le stockage.

#### D. Masque éphémère de champs ciblés batch (v1.6.1)
* Cases sidebar `.batch-field-cb` → `getBatchTargetedFieldsMask()` (null si les 12 sont cochées).
* `POST /batch-sync` peut inclure `targeted_fields` ; le worker dépile un 3- ou 4-tuple et passe `targeted_fields_override` à `enrich_series()`.
* `resolve_active_fields()` dans `services/enrichment_engine.py` — l’override prime sur le cache série pour ce run uniquement (filtre d’écriture ; les providers sont toujours scrapés en entier).

#### E. Stats lifetime & KPI live (v1.6.1 / C7)
* Clés SQLite `lifetime_stats` : `series_enriched`, `matches_won`, `series_missed` via `record_enrichment_telemetry` / `record_enrichment_miss`.
* Après enregistrement, `_broadcast_enrichment_stats` émet Socket.IO `enrichment_stats` (lifetime absolu + deltas).
* KPI topbar + compteur session (`sessionStorage` `mk_session_processed`) dans `websocket.js`. `/stats` ludique via `services/stats_service.py` + Chart.js.

#### F. Barre de progression batch (v1.6.1)
* `services/background_tasks.py` — `broadcast_batch_progress(remaining, active=…)` à chaque démarrage worker ; `{remaining: 0}` quand la file est vide ; `{stopped: true}` sur `drain_sync_queue()` / `/stop-batch`.
* `static/js/batch.js` — `showBatchProgress(ids.length)` au lancement ; `applyBatchProgressPayload()` calcule `done = total - remaining - (active ? 1 : 0)`.
* `static/js/websocket.js` — écoute Socket.IO `batch_progress`.

#### G. Baromètre de fiabilité (v1.6.1)
* Clés config `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD` (clamp `[0.30, 1.00]`).
* Seuil runtime : `scrapers/utils.py::get_match_accept_threshold()` (custom off → toujours `0.60`). Scrapers officiels + fallbacks `_safe_match_score` / `attach_match_score` via le getter.

---

### 5. Sideloading de Scrapers & Auto-Découverte

MetaKavita utilise un Registre à **Double Source**. Au démarrage, `importlib.util` est utilisé pour charger dynamiquement des classes héritant de `BaseScraper` situées dans :
1.  **Dossier Core :** `/app/scrapers/` (Code officiel).
2.  **Dossier Utilisateur :** `/app/data/scrapers/` (Sideloading communautaire).

Si le fichier déposé par un utilisateur déclare `needs_api_key = True`, MetaKavita va automatiquement générer le champ d'enregistrement dans l'Interface Graphique (UI) et gérer sa sauvegarde !

---

### 6. Extraction Profonde, QoS Éditeurs & Scoring

#### A. Extraction & Purge du Contexte (ISBN)
Avant de scraper, MetaKavita extrait silencieusement les données Kavita actuelles. Si l'utilisateur clique sur **Force Update + Reset Contexte**, MetaKavita purge totalement l'ISBN local. Puisque l'ISBN déclenche un match garanti à 100%, purger l'ISBN est le seul moyen de corriger une série victime de faux-positifs en boucle.

#### B. Matrice de Scoring Unifiée (`scrapers/utils.py`)
Les scrapers passent leurs résultats dans `score_candidate` :
1.  **Règle d'or de l'ISBN** : 100% de match.
2.  **Pénalité Anti-Homonyme** : Auteurs différents = `-50%`.
3.  **Filtres Spin-Offs** : Mots-clés manquants = `-35%`.
4.  **Ancrage Tome 1** : Bonus de `+0.10` pour le T1, et pénalité de `-0.45` sur les tomes intermédiaires.

Le score renvoyé par `score_candidate()` n'a de sens que comparé à un seuil d'acceptation
partagé : `scrapers/utils.py::MATCH_ACCEPT_THRESHOLD` (actuellement `0.60`). Cette valeur était
autrefois un literal dupliqué dans chaque fichier de scraper (`0.50` pour la plupart, `0.60`
pour Hardcover/OpenLibrary, et même `0.45` pour Manga-News/Shikimori) — `0.50` (et a fortiori
`0.45`) a été testé en usage réel et générait trop de faux positifs (homonymes/spin-offs
acceptés à tort), donc `0.60` est désormais la seule valeur validée, centralisée pour que tous
les scrapers restent synchronisés.

**Les 9 scrapers basés sur une recherche appellent désormais `score_candidate()`.**
`mangadex.py`, `mangaupdates.py`, `manganews.py` et `shikimori.py` implémentaient chacun leur
propre heuristique titre-seul, sans comparaison d'auteur — la protection anti-homonyme
(catégorie A) ne s'appliquait donc jamais à eux. Chacun a été migré pour construire un candidat
*complet* (avec `staff`) avant scoring :
- `mangadex.py` : l'endpoint de recherche renvoie déjà l'auteur/artiste via
  `includes[]=author,artist`, donc construire le candidat complet par résultat de recherche ne
  coûte aucune requête HTTP supplémentaire. Une pénalité "oneshot" spécifique à MangaDex (sans
  équivalent dans la matrice partagée) reste appliquée en ajustement local par-dessus le score.
- `mangaupdates.py` : le `record` renvoyé par l'endpoint de recherche a la même forme que celui
  de l'endpoint de détail (mêmes clés `authors`/`associated`/`publishers`), donc
  `_parse_series_record()` est réutilisée directement sur les résultats de recherche — là non
  plus, aucune requête HTTP en plus.
- `shikimori.py` : le staff nécessite un 3ᵉ appel HTTP par candidat (`/roles`). Pour borner le
  coût, un pré-filtre bon marché par titre (sans requête supplémentaire) s'exécute d'abord ;
  `/roles` n'est appelé que pour les candidats qui le passent.
- `manganews.py` : les résultats de recherche HTML ne contiennent aucun auteur (juste titre +
  URL) ; récupérer la fiche détaillée (qui a le staff) pour chaque résultat multiplierait les
  requêtes contre un site protégé par Cloudflare. À la place, seuls les **3** meilleurs
  candidats au pré-filtre de titre voient leur fiche détaillée récupérée et scorée via
  `score_candidate()` — un compromis borné entre précision du matching et charge sur le site.

Voir `tests/test_scraper_score_migration.py` pour la preuve que le staff produit par chaque
scraper est bien dans la forme attendue par `score_candidate()`.

#### C. Qualité de Service (QoS) : Éditeur
L'utilisateur peut imposer la récupération de l'éditeur traduit (ex: *Kurokawa*) ou de l'éditeur d'origine (ex: *Shueisha*). Ce paramètre est injecté localement via l'interrupteur UI directement dans `existing_metadata['publisher_pref']`.

#### C2. Politique des titres localisés (`localized_titles.py`, issue #12 / C53)
Kavita `localizedName` est construit à partir des `titles[{lang,value}]` fournisseurs (repli : `alternative_titles` plats). Modes globaux via `LOCALIZED_TITLE_MODE` (`all` | `prefer` | `none`) et `LOCALIZED_TITLE_LANGS` optionnel. `alt_title_langs` par série (non vide) force `prefer` pour cette série. **Series `name` n'est jamais réécrit** — scope V1 = `localizedName` uniquement. Le défaut `all` conserve la jointure multi-titres historique `" / "`. AniList / MangaDex / Kitsu émettent des titres structurés ; la Complétion intelligente fusionne via `merge_title_entries`.

#### D. Smart Scoring : sélection par score & exécution en deux vagues (`metadata_fetcher.py`)
Pilotulé par l'interrupteur sidebar `SMART_SCORING` (même carte Options que `SMART_COMPLETION`).
Activé **par défaut**. Quand il est **désactivé**, MetaKavita retrouve le fallback classique
séquentiel : le premier provider utile de la liste gagne ; la Complétion intelligente (si
activée) comble les trous dans cet ordre de liste, sans comparaison de scores ni vague parallèle.

Avant la v1.6, la cascade de `fetch_metadata()` interrogeait déjà **tous** les providers
configurés pour chaque série (il n'y a jamais eu de sortie anticipée après le premier succès) —
mais elle retenait aveuglément comme vainqueur celui qui se trouvait **en premier** dans la liste
de fallback de l'utilisateur (`PROVIDER_1/2/3`), même si un provider suivant avait objectivement
un meilleur match pour cette requête précise. Les providers suivants n'intervenaient qu'en
complétion (`SMART_COMPLETION`), dans l'ordre brut de la liste.

Deux améliorations indépendantes ont été ajoutées par-dessus la matrice de scoring unifiée (§6.B) :

1. **Sélection du vainqueur par score.** Chaque scraper qui appelle `score_candidate()` attache
   désormais son propre score gagnant au dict retourné via `attach_match_score()` (clé
   `_match_score`, voir `scrapers/utils.py`). Une résolution directe par ID/URL (`is_id=True`)
   attache `1.0` — une recherche par identifiant explicite n'a par nature aucune ambiguïté à
   scorer. `fetch_metadata()` collecte tous les candidats acceptés, puis les trie par score
   décroissant (égalité → position d'origine dans la liste de fallback) avant de désigner un
   vainqueur. Si `SMART_COMPLETION` est activé, le remplissage des champs manquants suit
   désormais ce même ordre décroissant par score plutôt que l'ordre brut de la liste : c'est le
   candidat le plus digne de confiance qui gagne le droit de combler un champ vide, pas celui qui
   se trouvait juste être exécuté en premier. Un candidat sans `_match_score` (ex : scraper
   communautaire non encore migré vers `score_candidate()`) est traité comme "juste accepté"
   (`MATCH_ACCEPT_THRESHOLD`) plutôt que de faire planter le tri ou d'être injustement favorisé.
2. **Exécution en deux vagues.** Le provider #1 tourne toujours seul et en premier, séquentiel ;
   l'ISBN/les auteurs qu'il trouve sont fusionnés dans `existing_metadata` et transmis aux
   providers **restants**, qui tournent ensuite **en parallèle** (`ThreadPoolExecutor`) contre un
   instantané figé de ce contexte enrichi. C'est un compromis délibéré, pas un "tout en parallèle
   dès t=0" naïf : paralléliser dès le départ perdrait le bénéfice existant de la cascade de
   contexte (l'ISBN/les auteurs du provider #1 alimentant la règle d'or ISBN et la pénalité
   anti-homonyme de `score_candidate()` pour les providers suivants), ce qui compte surtout sur
   les séries "froides" (peu ou pas de métadonnées Kavita pré-existantes). Le rate-limiting par
   provider (`throttle_provider()`) est déjà indexé par `scraper.id` avec son propre verrou
   (voir §3 plus haut), donc paralléliser des providers *différents* ne viole jamais le
   `rate_limit` individuel de chacun. Aucun scraper ne mute `self` pendant `fetch()`, donc
   exécuter des instances de providers distinctes en concurrence est sûr.

Le volume d'appels étant inchangé (tous les providers configurés étaient déjà interrogés), c'est
un gain de latence pur (`max()` au lieu de `sum()` des temps de réponse des providers autres que
P1) et un gain de qualité (le meilleur match gagne, pas le premier). Voir
`tests/test_metadata_fetcher_smart_scoring.py` pour la suite de non-régression complète,
incluant une assertion de timing prouvant que les providers #2+ se recouvrent bien dans le temps.

**Scrapers communautaires :** `BaseScraper.uses_unified_scoring` vaut `False` par défaut (opt-in).
Le déclarer à `True` est informatif — le pipeline ne bloque jamais dessus. La sécurité vient de
`_safe_match_score()` dans `metadata_fetcher.py`, qui coerce/clamp toute valeur `_match_score`
absente ou mal formée pour qu'un scraper communautaire qui oublie `attach_match_score()` (ou
renvoie n'importe quoi) ne puisse pas faire planter l'enrichissement. Voir `CUSTOM_SCRAPERS.md` §4.

---

### 7. Écosystème des Scrapers Actifs (V1.5.7)

| Identifiant | Nom Public | Spécificités & Fonctionnalités |
| :--- | :--- | :--- |
| `ANILIST` | AniList | API GraphQL, scoring des candidats contre les spin-offs. |
| `BEDETHEQUE` | Bédéthèque | Contournement CSRF `curl_cffi`, match exact de séries franco-belges. |
| `COMICVINE` | ComicVine | API Key. Recherche `filter=name:`, priorisation des éditeurs majeurs. |
| `GOOGLEBOOKS` | Google Books | API Key. Replis dynamiques par langue (`langRestrict`), ISBN. |
| `HARDCOVER` | Hardcover (Exp) | API Key. GraphQL Hasura + Moteur Typesense. |
| `KITSU` | Kitsu | JSON:API, rapide, sans clé requise. |
| `MANGANEWS` | Manga-News | Catalogue VF, extrait l'éditeur FR et les visuels HD (webp). |
| `MANGABAKA` | MangaBaka | Manga + Book ; `schema=full`, filtre `type`, Préférence d'Éditeur. |
| `MANGADEX` | MangaDex | Filtres adultes (`erotica`), pénalités Oneshot. |
| `MANGAUPDATES`| MangaUpdates | Scraping par `hit_title`, support de la Préférence d'Éditeur. |
| `OPENLIBRARY` | Open Library | Clés Work (`OL...W`) & ISBNs, contournement Disclaimer Google Books. |
| `SHIKIMORI` | Shikimori | API Multilingue, extraction `/roles` du staff. |

---

### 8. Traduction Résiliente & Titre de Secours
Toutes les traductions sont gérées par `translator.py` avec bascule automatique en cas de quotas dépassés.
L'option **Titre de Secours (Fallback)** permet de traduire automatiquement le nom de l'œuvre (ex: *L'Attaque des Titans*) vers l'anglais pour relancer une seconde cascade de recherche sur les API internationales si la première échoue.

---

### 9. Création de Scrapers via IA (Vibecoding)
Pour permettre à la communauté de créer ses propres scrapers, veuillez vous référer au fichier **`CUSTOM_SCRAPERS.md`** situé à la racine du projet. Il contient le contrat absolu d'intégration et les Prompts IA ("Vibecoding") pour générer un scraper valide en 5 minutes.

---

### 10. Suite de Tests & Débogage Qualité
Des scripts de tests unitaires autonomes (`debug_all_scrapers.py`, `debug_scoring_20.py`, `debug_manga_quality.py`) permettent d'auditer 20 cas limites de scoring mathématique et les performances sans nécessiter d'instance Kavita. L'envoi physique d'image peut être traqué via `debug_cover.py`.

**Benchmark batch (tout allumé) :** `python debug/benchmark_batch.py --limit 10` — enrichissement séquentiel comme le worker réel, avec Smart Scoring / Smart Completion / title fallback / reset-on-force / auto-cover forcés. Demande interactivement le **token / clé API Kavita** (getpass). Défaut = **dry-run** (scrape + traduction réels, écritures Kavita mockées). `--live --i-know` uniquement si tu veux forcer des écritures réelles vers Kavita.

Depuis le refactor d'architecture, il existe également une suite **pytest** automatisée dans `tests/` (voir §12 ci-dessous), exécutée à chaque push/PR via `.github/workflows/tests.yml`. Contrairement aux scripts `debug_*.py` (scripts d'exploration interactifs, destinés à être lus et étendus par un humain), `tests/` est un filet de non-régression rapide, mocké et vérifié par CI, ciblé spécifiquement sur des bugs qui ont déjà touché ce projet une fois (disparition de `publisher_pref`, assainissement des payloads Kavita, mapping de statut MangaBaka) — il doit rester vert en permanence. Lancez-le localement avec `pip install -r requirements-dev.txt && pytest`.

---

### 11. Pièges Critiques & Flux de Contribution

Cette section formalise des bugs réels de production identifiés et corrigés lors d'audits approfondis du code. À lire **avant** de modifier `app.py`, `kavita_api.py`, `db_manager.py`, ou un scraper.

#### A. Développement "Docker-First" — Pas de Hot-Reload
MetaKavita s'exécute exclusivement dans un conteneur Docker (Gunicorn + Eventlet), avec `data/` monté en volume persistant pour `cache.db` et `config.json`. Modifier un fichier `.py` sur le disque n'a **strictement aucun effet** tant que l'image n'a pas été reconstruite et le conteneur redémarré. La cause la plus fréquente d'un "j'ai corrigé mais ça ne marche toujours pas" est une image Docker obsolète. Avant d'enquêter sur une régression qui "devrait" déjà être résolue par un correctif précédent, vérifiez toujours que le conteneur a bien été reconstruit.

#### B. L'API Kavita N'est Pas une API REST Classique — Lire `kavita_api.md` en Priorité
Avant de toucher à un chemin de code qui appelle `kavita_api.py`, lisez intégralement `kavita_api.md`. Deux règles sont non négociables et ont chacune provoqué un incident réel côté utilisateur :

1. **Ne jamais envoyer de payload partiel à `POST /api/Series/update`.** Le `SeriesController`/`UpdateSeriesDto` de Kavita n'a **aucune protection contre les valeurs nulles** sur plusieurs champs — notamment `localizedName`. Si votre logique de mise à jour ne vise à changer que `format` mais omet `localizedName` du corps JSON, le backend C# de Kavita désérialise la clé manquante en `null`, **écrase** la valeur existante en base, et **réinitialise en plus** `nameLocked` / `sortNameLocked` / `localizedNameLocked` à `false` — alors même que ces champs n'étaient pas censés être touchés. Cette régression exacte a silencieusement corrompu les titres alternatifs d'utilisateurs réels et fait planter un client OPDS tiers (l'extension "Kamare" de KOReader), qui supposait que `localizedName` serait toujours une chaîne de caractères et s'est bloqué sur le `null` résultant. **Le motif de correction obligatoire :** toujours faire un `GET /api/Series/{id}` en premier, fusionner le changement voulu dans l'état actuel *complet*, puis seulement ensuite renvoyer l'objet entier en `POST`. Voir `KavitaAPI.update_series_general()` pour l'implémentation de référence de ce motif GET-fusion-POST.
2. **Assainir les champs GET-uniquement / calculés avant chaque `POST`.** Des propriétés comme `created`, `lastModified`, `totalCount`, `maxCount`, `pages` et `wordCount` sont renvoyées par les endpoints `GET` de Kavita mais ne doivent jamais être réinjectées dans un corps `POST` — cela risque de déclencher des exceptions de concurrence d'état côté Entity Framework Core. Cet assainissement est centralisé **une seule fois** dans `KavitaAPI.update_series_metadata()`. Ne réimplémentez pas une version partielle de cette logique dans `app.py` ou dans un scraper — c'est exactement ce type de duplication (ne retirer que `created`/`lastModified` à un endroit en oubliant `maxCount`/`totalCount`) qui a un jour laissé passer un payload `maxCount: -100000` vers Kavita et fait planter une synchronisation.
3. **Respecter le protocole de verrouillage à 2 passages** (`Unlock → Write → Lock`, documenté dans `kavita_api.md` §1.B/1.C) chaque fois que votre code doit écraser un champ que l'utilisateur a pu verrouiller manuellement dans l'interface de Kavita.

#### C. Tracer un Nouveau Réglage sur *Toute* la Chaîne, Pas Seulement un Fichier
L'interrupteur de Préférence d'Éditeur par série (`VF/VA` vs `VO`, v1.5.7) a été livré avec un code entièrement correct dans le template HTML, la construction du payload JS, la logique d'extraction des deux scrapers, *et* le schéma SQLite — et pourtant il n'avait strictement aucun effet en pratique, car une seule route Flask (`/save-override`) lisait la valeur soumise dans une variable locale puis oubliait tout simplement de la transmettre à `save_forced_overrides()`. Aucun fichier n'était fautif isolément ; le bug n'existait que dans l'interstice entre les fichiers. **Chaque fois que vous ajoutez ou modifiez un réglage par série ou global, tracez-le manuellement de bout en bout** : champ HTML → construction du payload dans `script.js` → extraction du paramètre dans la route Flask → écriture dans `db_manager.py` → lecture dans `db_manager.py` → construction de `existing_metadata` dans `app.py` → consommation par le scraper. Un moyen rapide de détecter cette classe de bug consiste à rechercher tous les appels de la fonction de persistance (ex : `save_forced_overrides(`) et à comparer la liste d'arguments avec la signature de la fonction.

#### D. Centraliser, Ne Pas Dupliquer, la Logique d'Assainissement et de Mapping
Plusieurs bugs de ce code partagent la même cause racine : une règle (un mapping d'énumération de statut, une règle d'assainissement de payload, une convention de verrou) est implémentée une fois dans une fonction utilitaire, puis partiellement réimplémentée "par précaution" dans un appelant, et les deux définitions divergent silencieusement avec le temps (ex : le statut brut `"completed"` de MangaBaka qui ne correspondait jamais à la clé interne `"FINISHED"` attendue par `app.py`). Privilégiez l'ajout d'une nouvelle règle à un seul endroit — dans `kavita_api.py` pour tout ce qui concerne le format des payloads Kavita, ou `scrapers/utils.py` pour tout ce qui concerne le contrat des scrapers — et faites dépendre chaque site d'appel de cette source unique de vérité plutôt que de la redériver localement.

#### E. Tester Sans Instance Kavita en Ligne
Utilisez les scripts autonomes `debug_*.py` à la racine du projet pour valider un changement de logique avant de toucher un vrai serveur :
* `debug_all_scrapers.py` / `debug_scoring_20.py` / `debug_manga_quality.py` : tests de non-régression du moteur de scoring et du contrat des scrapers.
* `debug_publisher.py` : extrait le payload brut `publishers` des API MangaBaka/MangaUpdates et exécute la logique d'extraction `LOCALIZED`/`ORIGINAL` en parallèle pour vérifier la fonctionnalité de Préférence d'Éditeur.
* `debug_cover.py` / `debug_concurrency.py` : validation du format du payload d'upload de couverture et détection des races conditions du cache.
* `debug/benchmark_batch.py` : chronométrage batch séquentiel avec options lourdes forcées (`--limit`, `--library-id`, `--ids` ; dry-run par défaut ; `--live --i-know` pour écritures Kavita réelles).

Lors de la correction d'un bug, étendez l'un de ces scripts (ou créez-en un nouveau) pour le reproduire d'abord — c'est le moyen le plus rapide de confirmer qu'un correctif fonctionne réellement, sans reconstruction Docker complète ni parcours manuel dans l'interface Kavita.

#### F. La Documentation Fait Partie du Correctif
Chaque correctif ou fonctionnalité visible par l'utilisateur doit être répercuté à la fois dans `CHANGELOG.md` (bilingue EN/FR, versionné sémantiquement — le premier en-tête `## [X.Y.Z]` est analysé automatiquement par `services/changelog_service.py::get_app_version()` pour piloter le numéro de version affiché dans l'UI) et dans `ROADMAP.md` (entrées courtes bilingues `BFxx`/`Cxx`). Gardez les deux synchronisés : chaque numéro `BF`/`C` référencé dans la section "Dernières Nouveautés" de `ROADMAP.md` doit correspondre à une entrée détaillée dans `CHANGELOG.md`, et la plage de versions affichée en haut de cette section doit toujours correspondre à la plus récente entrée de `CHANGELOG.md`.

### 12. Architecture Modulaire (Plan des Modules Post-Refactor)
Depuis le refactor d'architecture, `app.py` n'est plus qu'un point d'assemblage d'environ 130 lignes : instanciation Flask/SocketIO, middlewares (`ProxyFix`, `ScriptNameStripper`), initialisation du logging, verrou global `require_login`, enregistrement des Blueprints, et démarrage des workers de fond. Toute la logique métier vit désormais dans des modules dédiés :

*   **`kavita_constants.py`** : source unique de vérité pour les mappings d'énumération Kavita (`PUBLICATION_STATUS_MAP`, `AGE_RATING_MAP`, `resolve_kavita_format_enum()`) et la normalisation des statuts bruts fournisseurs (`normalize_provider_status()`, utilisé par `scrapers/mangabaka.py`). Ajoutez tout nouveau mapping ici, jamais en ligne dans une route ou un scraper.
*   **`models.py`** : la dataclass `SeriesOverride`, contrat typé des surcharges par série (ID/provider forcé, titre alternatif, champs ciblés, préférence d'éditeur, `alt_title_langs`). Préférez `db_manager.save_series_override(SeriesOverride(...))` (champs nommés) à l'ancien wrapper positionnel `save_forced_overrides(...)` dans tout nouveau code — c'est une mitigation structurelle directe de la classe de bug décrite au §11.C.
*   **`extensions.py`** : l'instance partagée `socketio = SocketIO()` (créée sans app, `init_app(app)` appelé une seule fois dans `app.py`). Importez-la depuis ce module — jamais depuis `app.py` — dans tout module ayant besoin d'émettre des événements ou de déclarer des handlers `@socketio.on(...)`, pour éviter les imports circulaires.
*   **`services/enrichment_engine.py`** : `enrich_series(series_id, series_name, force_update, targeted_fields_override=None)`, extraction de l'ancien `process_series_logic()`. Logique d'orchestration pure (scraping, mapping des champs, appels Kavita, broadcast télémétrie lifetime) sans aucune dépendance vers Flask ni `app.py`.
*   **`services/background_tasks.py`** : les workers démons (consommateur de `sync_queue` + polling d'auto-sync périodique) et `start_background_workers()`, appelé une seule fois par `app.py` au chargement du module (comportement inchangé, requis pour un déploiement Gunicorn à worker unique `-w 1`). Items de file : 3-tuples `(id, name, force)` ou 4-tuples avec `targeted_fields` éphémère.
*   **`services/stats_service.py`** : métriques `/stats` ludiques + payload Chart.js à partir des compteurs lifetime + snapshot cache.
*   **`services/changelog_service.py`** : `get_app_version()` / `get_current_version()` (mise en cache) / `get_full_changelog_html()`. Importé indépendamment par `app.py` (contexte global des templates) et par `routes/misc.py` (`/api/changelog`) — importer depuis ce module plutôt que l'un depuis l'autre évite un import circulaire.
*   **`routes/*.py`** : un Blueprint Flask par domaine — `auth` (`/login`, `/logout`), `pages` (`/`, `/stats`), `config` (`/save-config`, `/regenerate-webhook-token`), `series` (`/save-override`, `/toggle-ignore`, recherche/application de couverture), `sync` (`/force-sync`, `/batch-sync`, `/stop-batch`, `/reset-errors`, `/export-errors`, `/webhook`), `misc` (`/api/proxy-image`, `/api/changelog`).
*   **`sockets/handlers.py`** : les deux handlers Socket.IO (`connect`, `fetch_covers_stream`), enregistrés en décorant l'instance partagée `extensions.socketio` ; importé une seule fois pour son effet de bord depuis `app.py`.
*   **`static/js/*.js`** : l'ancien `script.js` monolithique est désormais découpé en 7 fichiers `<script>` classiques chargés dans l'ordre de dépendance (`utils.js` → `websocket.js` → `overrides.js` → `covers.js` → `config.js` → `batch.js` → `main.js`). Volontairement sans bundler ni `type="module"` : les templates s'appuient sur des gestionnaires `onclick="..."` inline, qui exigent que chaque fonction reste en portée globale.
*   **`templates/partials/*.html`** : l'ancien `index.html` monolithique est désormais une coquille légère qui `{% include %}` six partials Jinja — `_sidebar.html`, `_toolbar.html`, `_series_row.html`, `_config_modal.html`, `_cover_modal.html`, `_changelog_modal.html` — un par zone d'UI autonome. Modifiez directement le partial concerné plutôt que de faire défiler un template unique de 600+ lignes.
*   **`tests/`** : le filet de sécurité pytest (fixtures `conftest.py` + tests métier dont `test_db_manager.py`, `test_kavita_api.py`, `test_playful_stats.py`, `test_batch_targeted_fields.py`, `test_comic_flexible.py`, `test_scraper_mangabaka.py`, `test_routes_series.py`, `test_max_tags.py`, `test_max_genres.py`, `test_scraper_max_caps.py`, `test_audit_c1_c3.py`, `test_fallback_query.py`, `test_metadata_fetcher_smart_scoring.py`, …). Les fixtures ne touchent jamais au vrai dossier `data/` ni au réseau — `isolated_db` monkeypatch `db_manager.DB_FILE`/`DATA_DIR` vers un fichier SQLite `tmp_path`, `flask_app`/`client` construisent une application Flask minimale n'enregistrant que `routes/series.py` (pas `app.py` en entier, pour éviter de démarrer de vrais workers de fond/logging), et `mock_kavita_api` bouchonne chaque méthode réseau de `KavitaAPI`. Voir §10. Helpers partagés : `url_allowlist.py`, `csrf_utils.py`, `cors_config.py`.

⚠️ **Les noms d'endpoints des Blueprints ont changé.** Flask préfixe toujours l'endpoint d'une route de Blueprint par le nom du Blueprint (ex : la vue `login` de `routes/auth.py`, enregistrée sur le Blueprint `auth`, devient l'endpoint `auth.login` — impossible de désactiver ce préfixage). Chaque appel `url_for(...)` et la liste blanche `request.endpoint in [...]` de `app.py::require_login()` ont été mis à jour en conséquence (`auth.login`, `pages.index`, `pages.stats`, `auth.logout`, `sync.export_errors`, `sync.webhook`). **Si vous renommez un Blueprint ou déplacez une route vers un autre Blueprint, recherchez son ancien nom d'endpoint dans `app.py` et dans chaque template `.html` avant de supposer que `url_for()` fonctionne toujours.**