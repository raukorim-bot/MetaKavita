# MetaKavita - Developer & Contribution Guide

This guide is designed for developers and AI assistants wishing to understand, maintain, or extend the MetaKavita codebase. 

---

## Sommaire / Table of Contents
1. [🇺🇸 English Developer Guide](#-english-developer-guide)
   * [1. Global Architecture & Security](#1-global-architecture--security)
   * [2. High-Speed Throttling & Rate-Limiting Architecture](#2-high-speed-throttling--rate-limiting-architecture)
   * [3. Reverse Proxy, Subpath & CORS Architecture](#3-reverse-proxy-subpath--cors-architecture)
   * [4. Frontend Mechanics, Batch QoS & WebSockets](#4-frontend-mechanics-batch-qos--websockets)
   * [5. Sideloading Scrapers & Auto-Discovery Registry](#5-sideloading-scrapers--auto-discovery-registry)
   * [6. Deep Extraction, Publisher QoS & Unified Scoring](#6-deep-extraction-publisher-qos--unified-scoring)
   * [7. Active Scraper Ecosystem](#7-active-scraper-ecosystem)
   * [8. Resilient Translation & Title Fallback](#8-resilient-translation--title-fallback)
   * [9. AI-Powered Scraper Creation (Vibecoding)](#9-ai-powered-scraper-creation-vibecoding)
   * [10. Quality Benchmarking & Debugging Suite](#10-quality-benchmarking--debugging-suite)
   * [11. Critical Pitfalls & Contribution Workflow](#11-critical-pitfalls--contribution-workflow)
   * [12. Modular Architecture (Post-Refactor Module Map)](#12-modular-architecture-post-refactor-module-map)
   * [13. MetaKavita Companion (C33)](#13-metakavita-companion-c33)
   * [14. Volume & Album Enrichment (#27)](#14-volume--album-enrichment-27)
   * [15. Invariants From the v1.7.0 Audit Campaign](#15-invariants-from-the-v170-audit-campaign)
   * [16. `CHANGELOG.md` Is a Data Source, Not Just a File (C82)](#16-changelogmd-is-a-data-source-not-just-a-file-c82)
2. [🇫🇷 Guide de Développement Français](#-guide-de-développement-français)
   * [1. Architecture Globale & Sécurité](#1-architecture-globale--sécurité-1)
   * [2. Moteur de Throttling & Régulation Dynamique](#2-moteur-de-throttling--régulation-dynamique-1)
   * [3. Architecture Reverse Proxy, Sous-dossiers & CORS](#3-architecture-reverse-proxy-sous-dossiers--cors-1)
   * [4. Frontend, QoS Batch & WebSockets](#4-frontend-qos-batch--websockets-1)
   * [5. Sideloading de Scrapers & Auto-Découverte](#5-sideloading-de-scrapers--auto-découverte-1)
   * [6. Extraction Profonde, QoS Éditeurs & Scoring](#6-extraction-profonde-qos-éditeurs--scoring-1)
   * [7. Écosystème des Scrapers Actifs](#7-écosystème-des-scrapers-actifs-1)
   * [8. Traduction Résiliente & Titre de Secours](#8-traduction-résiliente--titre-de-secours-1)
   * [9. Création de Scrapers via IA (Vibecoding)](#9-création-de-scrapers-via-ia-vibecoding-1)
   * [10. Suite de Tests & Débogage Qualité](#10-suite-de-tests--débogage-qualité-1)
   * [11. Pièges Critiques & Flux de Contribution](#11-pièges-critiques--flux-de-contribution-1)
   * [12. Architecture Modulaire (Plan des Modules Post-Refactor)](#12-architecture-modulaire-plan-des-modules-post-refactor-1)
   * [13. MetaKavita Companion (C33)](#13-metakavita-companion-c33-1)
   * [14. Enrichissement par tome et par album (#27)](#14-enrichissement-par-tome-et-par-album-27)
   * [15. Invariants issus de la campagne d'audit v1.7.0](#15-invariants-issus-de-la-campagne-daudit-v170)
   * [16. `CHANGELOG.md` est une source de données, pas seulement un fichier (C82)](#16-changelogmd-est-une-source-de-données-pas-seulement-un-fichier-c82)

---

## 🇺🇸 English Developer Guide

### 1. Global Architecture & Security
MetaKavita is an asynchronous Python application powered by a **Gunicorn WSGI server** with **Eventlet** workers to support real-time WebSockets via Flask-SocketIO.

*   **Security Layer:** Global authentication is enforced via `@app.before_request` (`auth_manager.setup_gate` then `login_gate` / `is_authenticated`) and the Socket.IO `connect` handler (`return False` if unauthenticated — Flask-SocketIO's documented reject form; per-event `_reject_unauthenticated` as defense in depth). **Fail-closed** — including when the DB is unreadable (deny, never fall through to an open UI). Account system lives in `auth_manager.py` + `users` table (Werkzeug hash method pinned `pbkdf2:sha256`); first-run `/setup`; optional `ADMIN_PASSWORD_HASH` + `ADMIN_USERNAME` seeding via `debug/hash_password.py` (hash-shape validated; ignored once any account exists). Per-IP lockout (5/15min) plus global backstop (20/15min) against `X-Forwarded-For` rotation (in-memory — sound under `gunicorn -w 1`); timing equalization uses one memoized dummy KDF. Legacy `ADMIN_PASSWORD` in `config.json` is a one-shot ownership proof on `/setup`, then purged — never adopted as the new password. Session cookies are `HttpOnly` + `SameSite=Lax` (optional `SESSION_COOKIE_SECURE=1` behind HTTPS), lifetime 7 days. CSRF tokens (`csrf_utils.py`) on state-changing POSTs; frontend injects `X-CSRF-Token`. `SECRET_KEY` is generated on first boot — never a public hardcoded fallback.
*   **Password change (Config modal):** `POST /account/password` (`routes/auth.py`, `auth_manager.update_password`) re-verifies `current_password` through the same `verify_credentials()` path as `/login` before hashing the new one — an open tab is not exempt from proving the current password. A wrong `current_password` counts as a failed login attempt (`register_failed_attempt`) and is subject to the same per-IP lockout, so the route cannot become a brute-force oracle that bypasses `/login`'s throttling. Three unnamed `<input>` fields in `_config_modal.html` (no `name` attribute) keep this call out of the big `saveConfig()` `FormData` POST to `/save-config`.
*   **Failed-login audit (BF82/BF83):** every `register_failed_attempt` emits an i18n INFO (`log_auth_failed_attempt`) with submitted username + client IP + attempt counter; IP/global lockout WARNINGs unchanged. Password/hash never logged. Optional `username=` keeps unit callers that only pass `ip` working. CSRF rejects log INFO (`log_security_csrf_rejected`: method/path/IP/user, never the token). Already-active lockout rejects log INFO via `log_lockout_reject` (no counter bump).
*   **SSRF Protection:** Shared allowlist helper (`url_allowlist.py`) for cover downloads and `/api/proxy-image` — http(s) only, no credentials/localhost/private IPs, up to 3 redirects with each hop re-validated (`fetch_with_safe_redirects`), safe `image/*` MIME. Domain lists come from `ScraperRegistry.get_all_proxy_domains()` (covers community scrapers too). `/api/proxy-image` streams with a **5 MB** hard cap (`413`).
*   **Credential-safe logging:** Use `secure_logging.safe_exc_str()` / `redact_secrets()` when logging exceptions that may include authenticated URLs (Kavita `apiKey`, ComicVine `api_key`, etc.) — never log raw `str(e)` after such calls.
*   **Webhook Hardening:** Webhooks require a cryptographically secure `WEBHOOK_TOKEN` generated in `data/config.json` (CSRF-exempt; token auth only). Prefer `X-Webhook-Token`; `?token=` still works (legacy / deprecated, BF63) — query strings leak into proxy logs / Referer. Config UI shows base `/webhook` + separate token field.
*   **Liveness `/healthz`:** `GET /healthz` → `{status, version}` only. Whitelisted in both setup/login gates (`misc.healthz`); touches **no** config, DB, or Kavita. Dockerfile `HEALTHCHECK` requires **strict HTTP 200** on this route (not a lax `/login` probe).
*   **Non-root Docker (C54):** Image user `metakavita` (default 1000:1000); entrypoint applies `PUID`/`PGID` then `gosu`. `save_config()` writes `config.json` **0600**.
*   **Safe SQLite Schema Migrations:** Database updates in `db_manager.py` use a safe `_ensure_schema` / `_ensure_pending_reviews_table` path that handles `sqlite3.OperationalError` gracefully, preventing fatal container crashes when introducing new features. All connections go through `_connect()` with **WAL** journal mode and a **30s busy_timeout** to reduce `database is locked` under concurrent worker + REST + Socket.IO writes.
*   **Pure Base64 Kavita Uploads:** Kavita requires cover uploads to be sent as pure Base64 byte strings (`kavita_api.py`). Prepending `Data URI` schemas (`data:image/jpeg;base64,...`) results in silent Kavita C# backend failures (the "Phantom Cover" syndrome).

---

### 2. High-Speed Throttling & Rate-Limiting Architecture
MetaKavita eliminates hardcoded thread sleep delays in favor of a **Timestamp-Based Dynamic Throttler** (`LAST_REQUEST_TIMES`, in `services/provider_throttle.py`; re-exported by `metadata_fetcher` for historical callers).
Idle APIs respond instantly with zero artificial delay, executing 3-provider Smart Fusions in ~1.6s. High-volume batch requests throttle each scraper strictly according to its declared `rate_limit` (e.g., 0.2s for MangaBaka, 1.0s for AniList) at maximum theoretical throughput, providing immunity against HTTP 429 errors.
**Every** path that hits a provider goes through it — enrichment, scraper diagnostics, inventory catalogue counts and **cover search** (`services/cover_search.py::run_cover_job`) — because a provider's quota belongs to the instance, not to the feature: cover search alone fires one parallel request per provider, and opening the picker mid-batch used to double the traffic sent to each API.
⚠️ **v1.7.0: the pace is applied per HTTP request, not per `fetch()`.** Calling `throttle_provider` once at the top of a `fetch()` that then issues 6 to 25 requests is not throttling — it is a burst behind a polite first request, and it is what got the developer's IP banned by Bédéthèque. Scrapers must use `BaseScraper._http_get` / `_http_post`, which apply the pace and a 20 s timeout to each request. `tests/test_scrapers_are_throttled.py` enforces it. See section 15.B.

---

### 3. Reverse Proxy, Subpath & CORS Architecture
MetaKavita natively supports deployment under custom URL subpaths (e.g. `https://domain.com/metakavita`).
Reverse proxy headers (`X-Forwarded-Prefix`, `X-Forwarded-For`, …) are processed via Werkzeug's `ProxyFix`. **`TRUSTED_PROXY_COUNT`** (default `1`) drives both ProxyFix hop count and the client IP used for lockout — set **`0`** if the instance is exposed directly (otherwise an attacker can rotate `X-Forwarded-For` and evade the per-IP lockout; the global 20/15min backstop still applies). Subpath: env `ROOT_PATH` **or** `config.json` `ROOT_PATH` (setup wizard C64); **env wins**. `ScriptNameStripper` WSGI middleware rewrites paths at boot (restart after change). Client-side, `window.ROOT_PATH` dynamically prefixes all AJAX calls.

**CORS whitelist (Docker env `CORS_ALLOWED_ORIGINS`)** — for self-host HTTPS domains (e.g. `https://….local.ltd`) where Same-Origin alone blocks Socket.IO / cross-origin AJAX. Comma-separated **explicit** origins only; empty = Same-Origin (no broad CORS). Applied to both Flask HTTP (`after_request` + OPTIONS preflight, with credentials) and `socketio.init_app(cors_allowed_origins=…)`. `*` is rejected. This does **not** replace reverse-proxy WebSocket upgrade (`Upgrade` / `Connection`) configuration — see `cors_config.py` and `app.py`.

**`KAVITA_URL` vs `KAVITA_EXTERNAL_URL`** — API calls always use `KAVITA_URL` (safe for Docker-internal hostnames like `http://kavita:5000`). Browser series links use `get_kavita_ui_url()` (`config_manager.py`), which prefers `KAVITA_EXTERNAL_URL` (public reverse-proxy URL) and falls back to `KAVITA_URL` when unset. The topbar/About **Kavita+** button uses `get_kavita_plus_url()` → `{ui}/settings#admin-kavitaplus` (wiki fallback if no UI URL is configured).

**Config precedence** — `config.json` > environment variable > default. `load_config()` merges the environment *before* generating `SECRET_KEY` / `WEBHOOK_TOKEN` and writing the file on a fresh install (BF51); otherwise every key would be frozen as a default and env seeding would never apply. `ADMIN_PASSWORD` is **not** seeded from the environment (would re-arm the one-shot `/setup` ownership proof). Blank `KAVITA_URL` / `KAVITA_EXTERNAL_URL` / `KAVITA_API_KEY` in the file still accept env seeding (BF52). When `TARGET_LANG` is absent from both file and env, it is derived from the effective `UI_LANG` (`en`→`EN`, `fr`→`FR`; BF64) — defaults are the aligned pair `UI_LANG=en` / `TARGET_LANG=EN`. Config modal secret inputs always render empty; empty POST keeps the stored secret (never prefill `********`).

**`KAVITA_HTTP_TIMEOUT`** — seconds for Kavita **write** POSTs (metadata 2-pass, series update 2-pass, cover upload). Default `60`. Env or `config.json`. If pass 1 (write) succeeds and pass 2 (re-lock) fails/times out, `update_series_metadata` / `update_series_general` return `(ok, msg, sealed=False)` soft-success; enrichment maps that to status **`NEEDS_RELOCK`** (not plain `COMPLETED`) and schedules `seal_series_locks()` (~2 s). Manual retry: `POST /api/series/<id>/seal-locks` and bulk `POST /api/series/seal-locks-pending` (`routes/series.py`).

**`MAX_TAGS`** — max tags pushed to Kavita. Default `15` (clamped 1–100). Env or `config.json` only — **not** in the Config modal. Use `get_max_tags(config=None)` from `config_manager` in scrapers (`tags[:get_max_tags()]`). In `services/kavita_payload.py` (**BF66**), titles are **deduped** (strip + casefold, order-preserving) **before** the max slice — Kavita UNIQUE on `Tag.NormalizedTitle` rejects duplicate `id:0` inserts with a generic 400.

**`MAX_GENRES`** — max genres pushed to Kavita. Default `5` (clamped 1–50). Env or `config.json` only — **not** in the Config modal. Same pattern as tags: scrapers may truncate early; the payload path dedupes then applies `get_max_genres(config)` (**BF66**).

---

### 4. Frontend Mechanics, Batch QoS & WebSockets

#### A. Live Cover Streaming
Manual cover searches stream image results live over WebSockets via `socketio.start_background_task` and `socketio.sleep(0)`.
Frames are filtered client-side by `series_id`. A chronological `stream_id` token (reject stale frames from a previous search on the same series) is the intended hardening documented historically for BF11 — **not yet implemented** in `covers.js` / `sockets/handlers.py`; do not assume it is present when debugging race conditions.

#### B. Smart Auto-Cover Locking
When a user manually selects a cover from the modal, the client instantly triggers an AJAX call to uncheck the specific "Cover" checkbox in the series override panel. This locks the manual choice and protects it from being overwritten by global `AUTO_COVER` tasks during the next batch.

#### C. Batch selection persist & auto-uncheck (v1.6.1)
* `static/js/batch.js` — `saveBatchSelection()` / `restoreBatchSelection()` store checked series IDs in `localStorage` under `mk_batch_selection:{libraryId|all}`. Filters hide rows without unchecking them.
* `static/js/websocket.js` — `socket.on('series_status', …)` calls `uncheckSeriesForBatchResume()` for `COMPLETED`/`NEEDS_RELOCK`, which clears the checkbox and updates storage.
* **Stop vs chunked enqueue** — Stop aborts the UI ×50 `/batch-sync` loop (`AbortController`) and the server rejects late chunks until the next batch’s first packet (`resume_enqueue=true`).
* **Persistent batch queue (C63 / v1.6.4)** — `services/batch_queue.py` stores jobs in SQLite (`batch_queue` + `batch_queue_meta.paused`). `/batch-sync` persists then `put`s to `sync_queue` only if not paused. Boot: `running→queued`, hydrate if not paused. Pause = `detach_batch_from_ram()` (no SQLite cancel). Stop = drain RAM + `cancel_all_pending()`. UI: Add to queue, modal list (remove/clear), Pause/Resume; Socket.IO `batch_queue_updated`.
* **`drain_sync_queue()` only removes `is_batch=True` items (v1.6.1 hotfix)** — it used to empty `sync_queue` unconditionally on Stop, which silently dropped any webhook/auto-sync item (`is_batch=False`) that happened to be queued at that exact moment, with no retry and no error surfaced anywhere. It now walks the whole queue, `task_done()`s only the batch-tagged items it counts as drained, and re-`put()`s everything else back (offset by a matching `task_done()` so `unfinished_tasks` isn't double-counted for items that were never actually completed).
* **A second concurrent batch is rejected, not silently corrupting (v1.6.1 hotfix)** — `_batch_total`/`_batch_done` are process-wide globals for a single progress bar; a second `/batch-sync` packet with `resume_enqueue=true` while `is_batch_active()` is still true (i.e. a batch already in flight) used to call `register_batch_enqueue(new_batch=True)`, which reset those counters mid-flight and scrambled the first batch's progress bar and `real_sends`. `routes/sync.py::batch_sync` now checks `is_batch_active()` before accepting a new batch and returns `409 {"already_running": true}`; `batch.js::launchBatch()` treats that the same as a Stop for its own enqueue loop, but also calls `hideBatchProgress()` since this tab's batch never actually started.

#### D. Ephemeral batch targeted-fields mask (v1.6.1)
* Sidebar checkboxes `.batch-field-cb` → `getBatchTargetedFieldsMask()` (null if all 12 checked).
* `POST /batch-sync` may include `targeted_fields`; worker unpacks a 3- or 4-tuple and passes `targeted_fields_override` to `enrich_series()`.
* `resolve_active_fields()` in `services/enrichment_engine.py` — override primes over the series cache for that run only (write filter; providers are still fully scraped).

#### E. Lifetime stats & live KPIs (v1.6.1 / C7)
* SQLite `lifetime_stats` keys: `series_enriched`, `matches_won`, `series_missed` via `record_enrichment_telemetry` / `record_enrichment_miss`.
* After record, `_broadcast_enrichment_stats` emits Socket.IO `enrichment_stats` with absolute `lifetime` + deltas.
* Topbar KPIs + session counter (`sessionStorage` key `mk_session_processed`) in `websocket.js`.
* Playful `/stats` (`ENABLE_PLAYFUL_STATS`, default ON): `services/stats_service.py` + Chart.js + Manual Review achievements (`services/mr_achievements.py`).

#### F. Batch progress bar (v1.6.1, isolated counters hotfix)
* Queue items are dicts built by `services/background_tasks.py::make_sync_item(series_id, series_name, force_update, fields_override=None, is_batch=False)` — **not** tuples anymore. `sync_queue` is still shared with webhook and auto-sync producers, so `is_batch` is what lets the worker tell a batch job apart from the others sharing the same queue.
* Dedicated counters `_batch_total` / `_batch_done` / `_batch_real_sends` (module globals under `_batch_progress_lock`, `services/background_tasks.py`) replace the old `sync_queue.qsize()`-based math, which used to jump erratically whenever a webhook or auto-sync item was enqueued mid-batch and inflated/deflated the shared queue size. `register_batch_enqueue(count, new_batch=True)` on the **first** `/batch-sync` packet (`resume_enqueue=true`) resets all three to zero; later packets of the same batch only add to `_batch_total`. `reset_batch_progress()` clears them on Stop/drain.
* `_REAL_SEND_MESSAGES = {"Succès", "NEEDS_RELOCK"}` — only these `enrich_series()` return messages count as an actual Kavita write; skips ("Déjà à jour."), misses, and `PENDING_REVIEW` do not increment `_batch_real_sends`. The final `batch_progress` emit carries `real_sends` so the client can tell "batch finished" apart from "batch finished and actually wrote something" (see §I below).
* `broadcast_batch_progress(remaining, active=…, stopped=…, real_sends=…)` on each worker start and on completion; `static/js/batch.js` still computes `done = total - remaining - (active ? 1 : 0)` client-side from the same payload shape.
* `/batch-sync` inventory cache (`routes/sync.py::_get_batch_inventory`, TTL 900s, keyed by `(kavita.url, kavita.api_key, library_id)`) — the UI chunks a batch into ~50-series `/batch-sync` POSTs; without this cache every chunk re-ran a full `get_all_series()` (and purged `KavitaAPI`'s library-type cache) against Kavita. Only the packet carrying `resume_enqueue=true` forces a fresh fetch; later packets of the same batch reuse that snapshot. Tests clear this cache between runs via the `_clean_batch_inventory_cache` autouse fixture in `conftest.py` — do the same for any new module-level cache you add.

#### G. Reliability barometer (v1.6.1)
* Config keys `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD` (clamped `[0.30, 1.00]`).
* Runtime threshold: `scrapers/utils.py::get_match_accept_threshold()` (custom off → always `0.60`). Official scrapers + `_safe_match_score` / `attach_match_score` fallbacks use the getter — do not hardcode `MATCH_ACCEPT_THRESHOLD` in new scrapers.

#### H. Manual Review Mode (C29)
Park-and-pick instead of auto-writing Kavita. Worker scrapes with `return_candidates=True`, then `create_review_from_candidates` → `park_pending_review` (atomic insert + `PENDING_REVIEW` status). UI consumes the queue over REST + Socket.IO (score gradient, keys 1–3, weak below-threshold band). Confirm path may include an optional **cover pick phase** before `apply_manual_review` (explicit cover upload even when `AUTO_COVER` is off); soft-success re-lock → `NEEDS_RELOCK` (same as auto).

When Manual Review is **off**, the same « Éditer avant confirmation » toggle can enable `CONFIRM_BEFORE_WRITE`: auto scrape parks a preview (`awaiting_confirm`) and opens the edit panel; Kavita is written only on confirm.

| Piece | Role |
| :--- | :--- |
| `services/manual_review.py` | Park helpers, summary translation before pick, skip/confirm/purge emitters |
| `services/enrichment_engine.py` | Manual branch in `enrich_series`, `preview_manual_review` / `apply_manual_review` / `research_manual_review` (apply shares `_processing_lock`); `seal_series_locks` for `NEEDS_RELOCK` |
| `routes/manual_review.py` | `GET/POST /api/manual-reviews…` (list, choice, confirm, research, skip, purge) |
| `db_manager.py` | `pending_reviews` table — **UNIQUE(`series_id`)**, `park_pending_review` / `close_pending_review` single-txn |
| `static/js/manual_review.js` + `_manual_review_modal.html` | Modal: pick / edit / **cover** / recap, Source checkboxes or C86 `field_picks`, C87 send ticks on the recap, keyboard dock, queue sync |

**Integrity rules (do not regress):**
* One pending row per `series_id` — re-park replaces, never stacks.
* Global batch (`routes/sync.py` with empty selection) excludes `PENDING_REVIEW`; auto-sync already did.
* Early “already up to date” must not clobber `PENDING_REVIEW`; on `NEEDS_RELOCK` attempt seal-only then COMPLETED; COMPLETED path purges stray rows.
* Write OK + re-lock fail → `NEEDS_RELOCK` (orange), not plain `COMPLETED`; seal via deferred retry or `POST /api/series/<id>/seal-locks` (+ bulk pending). The deferred retry (`services/kavita_payload.py::_schedule_seal_retry`) now claims the series under the same `_processing_lock` / `_processing_series_ids` as `enrich_series` / `apply_manual_review` before sealing, and skips itself (no-op, no error) if a concurrent re-scrape already claimed that ID — it used to fire unconditionally, which could race a manual re-park of the same series.
* Turning `MANUAL_REVIEW_MODE` off purges the queue (`routes/config.py`).
* Ignore toggle and `clean_orphaned_cache` delete pending rows for that series.
* Frontend: serialize `loadQueue`, re-anchor on `currentReviewId`, in-flight guards on pick/confirm/skip; handle `manual_review_confirmed` / `_skipped` / `_refreshed` / count→0.
* **Draining the queue while a batch is still running shows the waiting mask, not the recap (v1.6.1 hotfix)** — `showRecapIfEmpty()` checks the global `batchProgressTotal` (`batch.js`) before committing to `recap`; if a batch is still active it switches to the existing `waiting` phase instead, and the already-wired `mrOnBatchProgress()` → `settleWaitingAfterWork()` path takes it from there once the batch genuinely finishes (or shows the next parked review first). Without this, an empty queue mid-batch flashed the recap screen for a few seconds before the next scraped series yanked the modal back to `pick`. Guarded by `phase !== "waiting"` so the check isn't re-applied on the call that's already settling out of `waiting` (`batchProgressTotal` only zeroes ~1.5s after real completion — see `applyBatchProgressPayload()`).

**List view & bulk-accept (v1.6.1 hotfix)** — `📋` header button (`mrToggleListView()`) overlays a queue list on top of whatever pick/edit/cover panel is showing (restored as-is via `setPhase(phase)` on close). `mrBulkAccept()` posts to `POST /api/manual-reviews/bulk-accept` (`routes/manual_review.py`), which walks every `awaiting_pick` review, applies the exact "confirm without editing" path (`apply_manual_review(review_id, provider, include_providers=[])`, same as `/choice` when `MANUAL_REVIEW_EDIT` is off) for any whose `above[0]` score clears a user-supplied threshold (default `get_match_accept_threshold()`, clamped `[0.30, 1]`), and leaves everything else — including `awaiting_confirm` rows still being hand-edited — untouched in the queue. It never re-scrapes; `/batch-sync` remains the only automatic scraping entry point. The response's `failed` array (`{review_id, error}`) used to be silently dropped by `mrBulkAccept()`, which only surfaced `accepted`/`skipped` — a Kavita write failing mid-operation disappeared into the "skipped" count with no explanation. It's now rendered in `mrListFeedback`, matched against the freshly-reloaded `queue` to show a series name instead of a bare review id.

**Kavita verification link (v1.6.1 hotfix)** — the pick/cover/edit header shows a "🔗 View in Kavita" link (`updateKavitaLink()` in `manual_review.js`, `window.KAVITA_UI_URL` global) so you can open the candidate's actual Kavita series page before confirming a match. Backed by `pending_reviews.library_id` (nullable column, `NULL` for rows parked before this migration or if the ID was never resolved — the link is simply omitted). Populated for free from `KavitaAPI.get_cached_library_id(series_id)`, a **class-level** cache filled by the same `GET /api/Series/{id}` call `get_library_type_for_series()` already makes — no extra HTTP round-trip. `research_manual_review` does not backfill it (only `candidates_json` changes on re-search); a stale `library_id` (series moved to another Kavita library without a MetaKavita restart) only self-heals on process restart, since `get_all_series()` purges the type cache but not this one.

**C86 field picks** — `/choice` and `/confirm` accept `manual_completion`, `merge_fields`, `field_picks` (`{cover: ["AniList"], tags: ["MAL", "MU"]}`). When `field_picks` is present, `choice_and_merge` uses `apply_field_picks` (overwrite / list concat) instead of Source hole-fill. Preview stores `_field_picks` / `_merge_fields` / `_manual_completion` for reopen. Bulk-accept still sends `include_providers=[]` with no picks. Tests: `tests/test_manual_completion_field_picks.py`.

**C87 send_fields** — `/confirm` accepts `send_fields` (targeted-field tokens: `summary`, `cover`, `age`…). `None` (key omitted) keeps the historical series-mask write — bulk-accept, cover-only confirm, old clients. A list intersects `MR_EDIT_SENDABLE_FIELDS` with the **series** `targeted_fields` (never the sidebar batch mask). `weblinks` / `language` are not on the edit fiche and stay on the series mask. Preview stores `_active_fields` so the recap can lock boxes. Tests: `tests/test_mr_send_fields.py`.

Config flags (sidebar): `MANUAL_REVIEW_MODE`, `MANUAL_REVIEW_EDIT`, `MANUAL_REVIEW_SUPER`, `MANUAL_REVIEW_SOUNDS`. Tests: `tests/test_manual_review.py`, `tests/test_needs_relock.py`, `tests/test_manual_review_bulk_accept.py`, `tests/test_manual_review_queue_api.py`.

#### I. Supporter nags (C40 partial)
* `static/js/license_nag.js` — rare Buy Me a Coffee overlays after hot moments (batch end / rich MR recap). Caps: honeymoon 7d, max 1–2/day, honor snooze 30d. Failures must be no-ops (never block batch/MR). Class `.license` reserved as a future silence hook — no paywall / license keys.
* **`onBatchComplete()` real-send gate (v1.6.1 hotfix)** — the nag no longer fires just because `remaining` hit 0. `services/background_tasks.py` tracks `_batch_real_sends` (see §F) and forwards it as `real_sends` on the final `batch_progress` payload; `batch.js` passes it through, and `license_nag.js::onBatchComplete()` returns early when `real_sends <= 0`. Without this, a batch made entirely of already-up-to-date series (silently skipped, zero Kavita writes) still tripped the donation prompt.

#### J. Library denylist — auto-sync polling only (v1.6.1 hotfix)
`DISABLED_LIBRARIES` (Config → Planning checkboxes) has **exactly one** call site: `services/background_tasks.py::select_auto_sync_candidates()`, which filters the periodic auto-sync poller's own candidate list via `config_manager.is_library_enabled()`. That helper is the **only** denylist filter left — there is no list-level `filter_enabled_libraries()` anymore. `KavitaAPI.get_all_series()` always returns the full inventory and applies no denylist — the dashboard, manual batch (`/batch-sync`), the webhook, and CSV export all see every library regardless of this setting. Do not reintroduce filtering anywhere else; the polling loop used to purge cache entries for every series in a disabled library as if they were orphaned, which is exactly the class of bug this scoping fixes.

The former `config_manager.heal_total_library_denylist()` (auto re-enable all libraries if `DISABLED_LIBRARIES` covered 100% of them) was **intentional dead code** after v1.6.1 — deliberately unhooked from `routes/pages.py` — and has since been **removed** (orphan cleanup). It used to run on *every* dashboard load and could not tell an accidental first-save wipe apart from a user deliberately unchecking every library, so unchecking the last checkbox in the Config modal would silently re-check all of them on the next reload. The write-side fix (only touching `DISABLED_LIBRARIES` when `SYNC_LIBRARIES_PRESENT` / `KNOWN_LIBRARY` markers confirm the full library list was actually rendered — see `routes/config.py`) already prevents the accidental wipe this heal was compensating for, so a deliberate "disable everything" now sticks across reloads (regression-tested in `test_dashboard_renders.py::test_deliberately_disabling_every_library_survives_a_reload`). Library checkboxes call `saveConfig()` on `onchange` (plain AJAX save), not the removed `saveConfigAndReloadLibraries()` — a full page reload after every checkbox click was the other half of the "recheck everything" symptom, since it's what re-triggered the heal.

#### K. Typed live status badges via `series_status` (v1.6.1 hotfix)
`services/kavita_payload.py::_emit_series_status(series_id, status, series_name)` emits a Socket.IO `series_status` event; `static/js/websocket.js`'s handler calls `applySeriesStatusBadge(item, status)` (`batch.js`) to redraw a series row's badge — the same function `manual_review.js::markSeriesStatus` uses. `enrich_series()` (`services/enrichment_engine.py`) now calls it for **every** outcome, not just the write path: the early "already up to date" short-circuit (`COMPLETED`), both `NOT_FOUND` returns (manual-review candidate search and auto-mode fetch), both `PENDING_REVIEW` returns (manual park and `CONFIRM_BEFORE_WRITE` auto-park), and the deferred-seal-retry-still-failing branch (`NEEDS_RELOCK`). `apply_kavita_payload()` already covered the two write outcomes (`COMPLETED` / `NEEDS_RELOCK`).

Before this fix, `websocket.js` guessed `NOT_FOUND`/`PENDING_REVIEW`/skip-`COMPLETED` badges by pattern-matching **translated** keywords inside the raw `log_update` text ("réussi", "déjà à jour", "introuvable"...). That block is now gone — the `log_update` handler only clears the `.is-processing` highlight on a finished-marker emoji, nothing badge-related. Do not resurrect substring matching on log text for anything the badge needs to reflect; add a new `status` value and an `_emit_series_status()` call at the source instead. `uncheckSeriesForBatchResume()` (QoS batch resume) is likewise now driven by the `series_status` handler (`status === 'COMPLETED' || status === 'NEEDS_RELOCK'`), not by log text.

#### L. Topbar menus, the icon sprite & the Companion card (C81)

**Two menus, one closing function.** `toggleTopbarMenu(event, dropdownId)` / `closeTopbarMenus()` in `main.js` replace the single-purpose `toggleHelpMenu` / `closeHelpMenu`. Every menu is a `.topbar-menu` wrapper holding a `.topbar-menu-btn` and a `.help-dropdown`; both panels are anchored `right: 0` in the same corner, so **opening one must close the others** — `toggleTopbarMenu` calls `closeTopbarMenus()` before revealing its own. The only state kept is `aria-expanded` on the button: the CSS reads it to highlight the button and rotate `.mk-caret`, so there is no `is-open` class to keep in sync. The outside-click handler tests `event.target.closest('.topbar-menu')`; renaming that wrapper breaks closing without breaking anything visible, which is why `tests/test_ui_topbar_companion.py` asserts the selector against the CSS.

**What goes in which menu.** **Scrapers** holds what acts (installed scrapers, store, provider cascade) then the repository and authoring guide; **Help** holds what reads (About, release notes, Companion card, setup assistant, docs, diagnostics). Adding a scraper page to the Help menu is the regression the split exists to prevent — a test asserts no `scrapers_manage` route is reachable from `#helpDropdown`.

**The sprite must be parsed before the markup that uses it.** `<use href="#mk-ico-…">` referencing a symbol declared **later** in the document only resolves once parsing completes, so `_icons_sprite.html` is now included at the top of `<body>`, before the topbar: it used to sit next to the modals, which was harmless while every icon lived inside something hidden. Two consequences for new icons: draw them as strokes on `currentColor` (a symbol cloned by `<use>` is not reachable by CSS rules from the page, so tint with `fill="currentColor" fill-opacity=…` attributes), and remember that a typo in an `href` throws nothing and draws nothing — `test_every_icon_used_is_declared` walks every `<use>` under `templates/` and confronts it with the declared symbols.

**The Companion card remembers its dismissal in the browser, deliberately.** `#companionCard` is rendered with `hidden` and revealed by an inline script placed **immediately after it**, not on `DOMContentLoaded`: rendered visible then hidden, someone who closed it would see it flash on every load; revealed later, everyone else would see the page jump. The key is `localStorage.mk_companion_card_dismissed` (`COMPANION_CARD_KEY` in `main.js` — the inline script repeats the literal, so both are asserted together). This is not a config key: the server cannot know whether the extension is installed, and there is no reason to make a promotional card survive a browser change. `showCompanionCard()` (Help menu) removes the key and re-reveals, because a cross with no way back would also take the only in-app pointer to the two sideload archives with it. Tests: `tests/test_ui_topbar_companion.py`.

#### M. The mass-action bar: hierarchy by style, labels in a slot (C83)

**`flex: 1` is not a hierarchy.** The six controls of `.batch-actions` shared the width equally, in spaced-out capitals, so half the labels wrapped to two lines and *Run selection* — the only one that writes to Kavita — looked like the error amnesty next to it. Weight is now carried by the style: `.ba-btn--quiet` (outline) for maintenance, one `.ba-btn--primary` (filled) for the action, `.ba-btn--stop` quiet until `#batchActions[data-state="running"]`. Every button is `white-space: nowrap` and as wide as its label; nothing in the bar is uppercased, since capitals cost about 15 % of width for no information.

⚠️ **The label lives in `.ba-label`, and the JS must write there.** `batch.js` replaces these labels constantly — *Sending…*, *Add to queue*, *⏳...*, *✅ OK* — and it used to assign `btn.innerText`, which now also erases the `<svg>` beside the text: the icon disappears on the first state change and only comes back with a page reload. Go through `setBatchBtnLabel()` / `batchBtnLabel()` (and `setBatchBtnBusy()`, which hides the icon while a transient message with its own emoji is showing). `tests/test_ui_batch_actions.py` reads the body of each of the five functions involved and fails on a direct `btn.innerText`.

**Bar state must not depend on a transient message.** `mainBatchBtnBusy` freezes the *label* while *Sending…* shows; `data-state` and the primary button's `data-mode` are set **before** that early return in `syncMainBatchBtnLabel()`, otherwise the Stop button would stay pale during the very batch it is there to stop.

⚠️ **A `display` in a class beats the browser's `[hidden]`.** `.batch-queue-badge` declared `display: inline-block`, so `badge.hidden = true` did nothing and an empty queue still showed its pill (BF170). Any element a script hides with `hidden` needs its own `[hidden] { display: none; }` rule as soon as a class gives it a `display`.
---

### 5. Sideloading Scrapers & Auto-Discovery Registry

MetaKavita uses a **data-only Auto-Discovery Registry** (`ScraperRegistry`, C61 + C62 in v1.6.4).
On startup, `sync_core_scrapers()` aligns `/app/data/scrapers/` for official scrapers:
1. **GitHub first** — `store/catalog.json` entries with `is_core` (sha256) from
   `community-scraper-metakavita`, so hotfixes ship without a new Docker image;
2. **Image fallback** — AST discovery of `is_core = True` in `/app/scrapers/` when the
   catalog is unreachable, and to seed any core still missing after a partial GitHub sync.
With `AUTO_UPDATE_CORE_SCRAPERS` (default on), stale copies are overwritten at boot; when off,
missing files are still seeded and stale ones surface as a dashboard banner +
`POST /api/scrapers/core-updates/apply`.
Which of the two sources wins is arbitrated by **`BaseScraper.version`** (`major.minor.patch`,
read from the file by AST and published in the catalog): a copy is only replaced by a strictly
newer one, so an image update delivers its fixed core scrapers even when the catalog mirror
lags, and a catalog ahead of the image still wins. Downgrades are refused and logged as a
warning. **A core scraper that gains a capability must bump its `version`** — at equal versions
only the sha256 differs, and the image content stays the reference (BF143). Then `load_all()` loads **only** that data
directory via `importlib.util` (classes inheriting from `BaseScraper`). Core files load as
`scrapers.<stem>` (relative or absolute `scrapers.*` imports); community files load as
`custom_scrapers.<stem>`.

* **Manage UI** (`/manage-scrapers`): enable/disable (`DISABLED_SCRAPERS`), delete community files.
* **Community Store** (`/scraper-store`): install/update from the GitHub catalog with sha256
  verification; `ScraperRegistry.reload()` hot-reloads without container restart.
* Manual filesystem drop-ins still require a restart (or a subsequent Magasin/reload).

If a scraper declares `needs_api_key = True`, MetaKavita generates a password input in the
Config Modal and loads its value without frontend changes.

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
threshold. Prefer `scrapers/utils.py::get_match_accept_threshold()` (v1.6.1 barometer —
§4.G); the constant `MATCH_ACCEPT_THRESHOLD` (`0.60`) remains the default when custom
mode is off. It used to be a literal duplicated in every scraper file (`0.50` for most,
`0.60` for Hardcover/OpenLibrary, even `0.45` for Manga-News/Shikimori) — `0.50` (and a
fortiori `0.45`) was tested in real-world usage and produced too many false positives
(homonyms/spin-offs wrongly accepted), so `0.60` is the single validated default,
centralized so every scraper stays in sync.

**Search-based official scrapers call `score_candidate()`** (including MangaDex /
MangaUpdates / Manga-News / Shikimori migrations below). Newer providers (MAL, BDTheque,
Wikidata, …) must use the same matrix + `get_match_accept_threshold()`. Historical note —
`mangadex.py`, `mangaupdates.py`, `manganews.py` and `shikimori.py` used to implement their
own title-only heuristic with no author cross-check at all — meaning the anti-homonym
protection (category A) never applied to them. Each was migrated to build a *complete*
candidate (including `staff`) before scoring:
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
   candidate, then sorts them by score descending before picking a winner. **Tie-break (BF68/BF77):**
   equal scores → prefer non-explicit-adult, then original fallback-list position. Explicit adult
   = `age_rating` `r18`/`x18` (aliases `erotica`/`pornographic`), **or** genre/tag tokens
   `hentai`/`futanari`. BF81 may set `x18` from those tags before the sort (scores unchanged).
   Auto logs `log_tiebreak_prefer_safe` only when the sorted winner is actually non-adult.
   `mature` is not demoted. Manual Review keeps a **neutral** sort. Confirm-before-write + score
   tie → `awaiting_pick`. If `SMART_COMPLETION` is enabled, gap-filling follows this same sorted
   order —

   the most trustworthy candidate's fields win a "which value fills this gap" contest, not the one
   that merely happened to run first. **Age + SMART_COMPLETION (BF102):** fill holes when a
   secondary has a real age signal. Auto may hole-fill empty `age_rating` from a secondary only
   when the value is `safe` / `suggestive` / `mature` (Everyone / Teen / Mature 17+). NSFW ages
   (`r18` / `x18` / aliases) are **never** Auto-filled from a secondary — correctness guard so an
   empty BF56 winner cannot inherit a false adult lock and undo BF68 prefer-safe (not a content
   filter). Match scores do not use age; prefer-safe tie-break still runs before fusion. Writing
   to Kavita still requires the series **Age** targeted field (or `ALL`). Manual Review Sources
   keep `fill_age_rating=True` (any age). Guards: `tests/test_fusion_age_no_backfill.py`,
   `tests/test_smart_completion_manual_review.py`.
   A candidate with no `_match_score` (e.g. a community scraper
   not yet migrated to `score_candidate()`) is treated as "just barely accepted"
   (`MATCH_ACCEPT_THRESHOLD`) rather than crashing the sort or being unfairly favored.
2. **Two-wave execution.** Provider #1 still runs alone and sequentially first; whatever ISBN/
   authors it finds are merged into `existing_metadata` and handed to the *remaining* providers,
   which then run **in parallel** (`ThreadPoolExecutor`) against a frozen snapshot of that
   enriched context. This is a deliberate compromise, not a naive "fire everything at t=0":
   running everything in parallel from the start would lose the existing context-cascading
   benefit (provider #1's ISBN/authors feeding `score_candidate()`'s ISBN Golden Rule and
   anti-homonym penalty for providers #2/#3), which matters most on "cold" series with little or
   no pre-existing Kavita metadata. Per-provider rate-limiting (`throttle_provider()`) is already
   keyed by `scraper.id` with its own lock (see §2 above), so parallelizing *different* providers
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

### 7. Active Scraper Ecosystem

| Scraper ID | Provider Name | Types | Key Features |
| :--- | :--- | :--- | :--- |
| `ANILIST` | AniList | Manga, Comic, Book | GraphQL API, spin-off penalties, native `AniListId` mapping. |
| `ANN` | Anime News Network | Manga | Encyclopedia XML API, no key; covers + staff. |
| `BABELIO` | Babelio | Book | French literature (HTML); covers + summaries, no key. |
| `BEDETHEQUE` | Bédéthèque | Comic | Franco-Belgian BD scraper, `curl_cffi` CSRF bypass. |
| `BDTHEQUE` | BDTheque.com | Comic | Franco-Belgian BD (bdtheque.com, **not** bedetheque). AJAX search + series page; Magic Input `/series/{id}/{slug}`; covers via `data-echo`. |
| `COMICVINE` | ComicVine | Comic | API Key required. Primary publisher weighting, Issue #1 fallback. |
| `DECITRE` | Decitre | Book | French bookstore HTML + JSON-LD; ISBN + covers. |
| `GOOGLEBOOKS` | Google Books | Book, Comic | API Key required. Dynamic `langRestrict`, ISBN targeting. |
| `HARDCOVER` | Hardcover (Exp) | Book, Comic | API Key required. Hasura GraphQL API & Typesense search. |
| `KITSU` | Kitsu | Manga | JSON:API integration, no API key required. |
| `LOCG` | League of Comic Geeks | Comic | Public XHR/HTML comics (no partner API key); covers. |
| `MANGANEWS` | Manga-News | Manga | VF French catalog scraper, extracts HD webp covers. |
| `MANGABAKA` | MangaBaka | Manga, Book | `schema=full`, `type` filter (novel for Book), Publisher Preference support. |
| `MANGADEX` | MangaDex | Manga | Content rating filters (`erotica`), oneshot penalties. |
| `MANGAUPDATES`| MangaUpdates | Manga | `hit_title` matching, Publisher Preference support. |
| `METRON` | Metron | Comic | API key (`METRON_API_KEY` Bearer or `user:password`); series + issue credits/covers. |
| `OPENLIBRARY` | Open Library | Book, Comic | ISBN support, anti-429 retries, Google Disclaimer bypass. |
| `PLANETEBD` | Planète BD | Comic | French BD + comics (HTML); rich payload + covers. |
| `MAL` | MyAnimeList | Manga, Book | Official API v2 + `X-MAL-CLIENT-ID` (`MAL_API_KEY` = Client ID; no user OAuth). Magic Input `myanimelist.net/manga/{id}`. |
| `SENSCRITIQUE` | SensCritique | Book, Comic | FR GraphQL Apollo; covers, no key. |
| `SHIKIMORI` | Shikimori | Manga | Multilingual title matching, `/roles` staff extraction. |
| `WIKIDATA` | Wikidata (**Magasin**, not core) | Manga, Comic, Book | **Live only** (SPARQL + Entity API) — limited metadata scope; install from Community Store. Magic Input Q-id; mapping helpers in core `wikidata_map`. Best as fallback / ISBN / cross-IDs. |

#### Comic Flexible (C35)
⚠️ **Corrected in v1.7.0: the hybrid type is ID 1, not ID 5.** Kavita's enum names `Comic = 1` (labelled *Comic (Flexible)* in its UI) and `ComicVine = 5` (labelled *Comic*), and MetaKavita had the two the wrong way round — so a flexible library got the strict cascade and vice versa. `kavita_constants.LIBRARY_TYPE_BY_ENUM` is now the only mapping to trust (`_normalize_library_type` reads it); it also re-files `Image = 3` with Manga and `LightNovel = 4` with Book, which were previously swapped as well. ID 1 therefore normalizes to `ComicFlexible`: enrichment runs `COMIC_PROVIDER_*` first, then falls back to Manga `PROVIDER_*` when no useful hit is found, and manual cover search unions Comic + Manga scrapers. ID 5 follows the strict Comic cascade. Tests: `tests/test_comic_flexible.py`, `tests/test_library_type_normalize.py`.

**Run-year hygiene (BF54 / v1.6.2, BF173 / v1.7.1)** — Flexible series names often carry `(YYYY)` / `(YYYY-)` to distinguish comic runs. Comic `clean_title` strips those parens from the **search string** (they used to stay and poison ComicVine `name:` filters). `extract_year_from_title` / `apply_title_year_hint` in `scrapers/utils.py` copy the year into `existing_metadata` before the Comic wave; ComicVine boosts an exact `start_year`, then ±1, then penalises a far year (BF173: ±1 must not tie exact, or a neighbour with more issues wins). The Manga fallback is **not** confidence-penalized — Flexible libs may hold both comics and manga.

**Auto vs Manual Manga fallback (v1.6.1 hotfix + audit B16)** — the paths are **intentionally parallel**, not a single shared helper. **Manual** uses `_apply_comic_flexible_manga_fallback()` in `services/enrichment_engine.py`, gated by `_candidates_have_a_strong_hit()` (true only if `above` is non-empty) rather than "candidates empty". Manual Review runs the Comic cascade with the match threshold forced to `0.0` (so the user can still see weak hits — they land in `below`, not `above`); without the strong-hit gate, a weak-but-non-empty Comic result used to block the Manga fallback in Manual even when Auto would have fallen through. The helper only *replaces* Comic candidates with the Manga wave if Manga returns a non-empty candidate payload — otherwise Manual keeps the weak Comic candidates for the user to pick. **Auto** keeps a separate **inline** Manga fallback: it gates on `_has_useful_provider_data()` against a metadata dict (not above/below candidates), and applies a forced-id provider filter (direct-ID scrapers only when `is_forced_id` and the query is not a URL) that Manual’s helper does not. Do **not** naively unify the two — different return shapes and forced-id behaviour make a blind merge risky.

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

1. **Never send a partial payload to `POST /api/Series/update`.** Kavita's `SeriesController`/`UpdateSeriesDto` has **no null-guard** on several fields — `localizedName` in particular. If your update logic only intends to change `format`, but omits `localizedName` from the JSON body, Kavita's C# backend deserializes the missing key as `null`, **overwrites** the existing value in the database, and additionally **resets** `nameLocked` / `sortNameLocked` / `localizedNameLocked` to `false` — even though those fields were never meant to be touched. This exact regression silently corrupted alternate titles for real users and crashed a third-party OPDS client (KOReader's "Kamare" plugin), which assumed `localizedName` would always be a string and choked on the resulting `null`. **The mandatory fix pattern:** always `GET /api/Series/{id}` first, merge your intended change into the *complete* current state, and only then `POST` the full object back. See `KavitaAPI.update_series_general()` for the reference implementation of this GET-merge-POST pattern. The same trap applies to the **seven external metadata ids** (`SERIES_EXTERNAL_ID_KEYS`: `aniListId`, `malId`, `hardcoverId`, `metronId`, `comicVineId`, `mangaBakaId`, `cbrId`): the controller calls `ExternalMetadataIdHelper.SetExternalMetadataIds(entity, dto)` unconditionally and it writes `entity.X = dto.X ?? 0`, so an absent key resets the id to zero. Every payload sent to `POST /api/Series/update` must carry all seven — use `series_external_ids(current)` — and the same holds for `POST /api/Chapter/update` (`services/kavita_chapter_payload.EXTERNAL_ID_KEYS`).
2. **Sanitize GET-only / computed fields before every `POST`.** Properties like `created`, `lastModified`, `totalCount`, `maxCount`, `pages`, and `wordCount` are returned by Kavita's `GET` endpoints but must never be echoed back in a `POST` body — doing so risks triggering Entity Framework Core concurrency exceptions server-side. This sanitization is centralized **once** inside `KavitaAPI.update_series_metadata()`. Do not re-implement a partial version of it ad-hoc in `app.py` or inside a scraper — that exact kind of duplication (only stripping `created`/`lastModified` in one place while forgetting `maxCount`/`totalCount`) is how a `maxCount: -100000` payload once reached Kavita and crashed a sync.
3. **Respect the 2-pass Lock Guard protocol** (`Unlock → Write → Lock`, documented in `kavita_api.md` §1.B/1.C) whenever your code needs to overwrite a field the user may have manually locked in Kavita's UI. Soft-success on re-lock failure must surface as `NEEDS_RELOCK` + `seal_series_locks`, not silent `COMPLETED`.
4. **Soft atomicity for general fields (BF67).** `apply_kavita_payload()` calls `update_series_general` (localized name / format) **only when** `update_series_metadata` succeeded. A metadata failure must not still write general fields (that was the #24 failure mode: UNIQUE tag reject + `localizedName` still applied).
5. **A `200` from Kavita does not mean Kavita wrote anything.** System.Text.Json silently drops keys the DTO does not declare, so an invented field costs a round-trip and buys nothing while looking like a success in the logs. Before adding a key to a payload, check it exists on the target DTO in `Kavita.Models/DTOs/` — several did not: `format` / `formatLocked` were never on `UpdateSeriesDto` (reading direction is a per-user preference, `AppUserPreferences.ReadingDirection`, not a series property), `dontMatch` is only writable through `POST /api/Series/dont-match`, `coverImageLocked` is not on `UpdateChapterDto`, and `libraryId` is not on `SeriesFilterV2Dto` — that last one made `POST /api/Series/all-v2` return the whole visible catalogue once per library.
6. **Only seal the locks your pass actually wrote.** `SeriesService` assigns every `...Locked` boolean from the DTO unconditionally, so a lock sent as `true` is closed — including on a field the user deliberately left open for the file scan or Kavita+ to fill. `seal_series_locks(series_id, lock_keys=[...])` therefore takes the list of locks the original payload closed; without it, it falls back to sealing only the locks whose field actually carries content, and never reopens one. Conversely, `ChapterController` inspects **no** lock at all: on the chapter path, whatever MetaKavita sends is written, so the fill-only-empty policy has to be applied client-side (see `services/kavita_chapter_payload.credits_to_write`).

#### C. Trace New Settings Through the *Entire* Chain, Not Just One File
The per-series Publisher Preference toggle (`VF/VA` vs `VO`, v1.5.7) shipped with fully correct code in the HTML template, the JS payload builder, both scrapers' extraction logic, *and* the SQLite schema — yet was completely inert in practice, because a single Flask route (`/save-override`) read the submitted value into a local variable and then simply never forwarded it to the persistence call (then `save_forced_overrides()`, since removed in favour of `save_series_override(SeriesOverride(...))`). No single file was wrong in isolation; the bug only existed in the gap between files. **Whenever you add or touch a per-series or global setting, manually trace it end-to-end**: HTML input → `script.js` payload construction → Flask route parameter extraction → `db_manager.py` write → `db_manager.py` read → `existing_metadata` construction in `app.py` → scraper consumption. A fast way to catch this class of bug is to grep every call site of the persistence function (e.g. `save_series_override(`) and diff the `SeriesOverride` fields against the dataclass.

#### D. Centralize, Don't Duplicate, Sanitization & Mapping Logic
Several bugs in this codebase share the same root cause: a rule (a status enum mapping, a payload sanitization rule, a lock-flag convention) gets implemented once in a helper function, then partially re-implemented "just in case" in a caller, and the two definitions silently drift apart over time (e.g. MangaBaka's raw `"completed"` status never matching the internal `"FINISHED"` key expected by `app.py`). Prefer adding new logic exactly once — in `kavita_api.py` for anything Kavita-payload-shaped, or `scrapers/utils.py` for anything scraper-contract-shaped — and make every call site depend on that single source of truth instead of re-deriving it locally.

#### E. Testing Without a Live Kavita Instance
Use the standalone `debug_*.py` scripts at the project root to validate logic changes before touching a real server:
* `debug_all_scrapers.py` / `debug_scoring_20.py` / `debug_manga_quality.py`: scoring engine and scraper-contract regression tests.
* `debug_publisher.py`: dumps the raw `publishers` payload from the MangaBaka/MangaUpdates APIs and runs the `LOCALIZED`/`ORIGINAL` extraction logic side-by-side to verify the Publisher Preference feature.
* `debug_cover.py` / `debug_concurrency.py`: cover upload payload shape validation and cache race-condition checks.
* `debug/benchmark_batch.py`: sequential batch wall-clock with all heavy options forced on (`--limit`, `--library-id`, `--ids`; dry-run by default; `--live --i-know` for real Kavita writes).

When fixing a bug, extend one of these scripts (or add a new one) to reproduce it first — it's the fastest way to confirm a fix is real without a full Docker rebuild and manual click-through in the Kavita UI.
⚠️ Those scripts do hit real providers; **`python -m pytest` may not**. Since v1.7.0 a barrier blocks every outgoing connection during the suite (section 15.D) — write scraper tests against fixtures, and never point a script at a provider to “check the pace”: that is precisely how the developer's IP got banned by Bédéthèque.

#### F. Documentation Is Part of the Change
Every user-facing fix or feature must be reflected in **both** `CHANGELOG.md` (bilingual EN/FR, semantically versioned — the topmost `## [X.Y.Z]` header is parsed automatically by `services/changelog_service.py::get_app_version()` to drive the version number shown in the UI) and `ROADMAP.md` (bilingual short-form `BFxx`/`Cxx` entries). Keep the two in sync: every `BF`/`C` number referenced in `ROADMAP.md`'s "Latest Releases" section should correspond to a detailed entry in `CHANGELOG.md`, and the version range shown at the top of that section should always match the newest `CHANGELOG.md` entry.

### 12. Modular Architecture (Post-Refactor Module Map)
Starting with the architecture refactor, `app.py` is a thin ~130-line assembly point only: Flask/SocketIO instantiation, middlewares (`ProxyFix`, `ScriptNameStripper`), logging bootstrap, the global `require_login` gate, Blueprint registration, and starting the background workers. All business logic lives in dedicated modules:

*   **`kavita_constants.py`**: single source of truth for Kavita enum mappings (`PUBLICATION_STATUS_MAP`, `AGE_RATING_MAP`, `resolve_kavita_format_enum()`) and raw-provider-status normalization (`normalize_provider_status()`, used by `scrapers/mangabaka.py`). Add new enum mappings here, never inline in a route or scraper.
    *   **`AGE_RATING_MAP` (BF53 / BF80 / BF81)** — scrapers emit `safe` / `suggestive` / `mature` / `r18` / `x18` (aliases deprecated: `erotica`→`r18`, `pornographic`→`x18`). Map: `safe→3`, `suggestive→8`, `mature→10`, `r18→12` (R18+), `x18→14` (X18+). `r18` = adult restricted (not necessarily porn); `x18` = explicit sexual. Kitsu: `G→safe`, `PG→suggestive`, `R→mature`, `R18→pornographic` (alias of `x18`). **BF81:** `apply_explicit_label_age` forces `x18` when genres/tags contain `hentai`/`futanari` (fill or escalate; never downgrade), before Auto sort / classic apply — does not change match scores. Guards: `tests/test_age_rating_map.py`, `tests/test_kitsu_age_bf80.py`, `tests/test_age_fill_labels_bf81.py`.
    *   **Age safeguarding (BF56 / v1.6.2)** — never invent `safe` when the provider has no age signal (omit the field). Prefer omit over under-rate. Authoritative mappings only: MAL `nsfw`, MangaDex `contentRating`, Kitsu `ageRating` (known tokens only), Manga-News `#agenumber`, Google Books `maturityRating=MATURE` → `erotica` (alias `r18`), AniList only when `isAdult`, BDTheque `_parse_age` (Adulte/Érotique → `erotica`; « Ados - Adultes » → `suggestive`). Guard: `tests/test_age_safeguarding_bf56.py`.
    *   **SMART_COMPLETION age fill (BF102)** — Fill holes when a secondary has a real age signal: Auto may copy `safe`/`suggestive`/`mature` onto an empty winner age; NSFW secondary ages stay blocked as a **correctness** guard (false X18+ / prefer-safe), not a content filter. Winner age is never overwritten by a secondary. Kavita write still gated by targeted field `age`. Batch skip « already up to date » is skipped when `age` is active and Kavita `ageRating` is missing / `0` / `1` (Pending). Live log: `log_age_write_diag`. See Smart Scoring §D.
*   **`models.py`**: `SeriesOverride` dataclass, the typed contract for per-series overrides (forced ID/provider, alternative title, targeted fields, publisher preference, `alt_title_langs`). Persist via `db_manager.save_series_override(SeriesOverride(...))` (named fields) — the legacy positional `save_forced_overrides(...)` wrapper was removed. This is a direct, structural mitigation for the class of bug described in §11.C.
*   **`extensions.py`**: the shared `socketio = SocketIO()` instance (created without an app, `init_app(app)`'d once in `app.py`). Import from here — never from `app.py` — in any module that needs to emit events or declare `@socketio.on(...)` handlers, to avoid circular imports.
*   **`auth_manager.py`**: account CRUD, Werkzeug hashing (`pbkdf2:sha256`), per-IP + global lockout, legacy `/setup` ownership proof, `ADMIN_PASSWORD_HASH` / `ADMIN_USERNAME` seeding, `TRUSTED_PROXY_COUNT`, session helpers, `setup_gate` / `login_gate`. Fail-closed; never import plaintext `ADMIN_PASSWORD` as the new password.
*   **`config_manager.py`**: `load_config()` / `save_config()` — env merge **before** first-write secrets (BF51); precedence `config.json` > env > default; `config.json` mode 0600.
*   **`services/enrichment_engine.py`**: `enrich_series(series_id, series_name, force_update, targeted_fields_override=None)`, the extracted former `process_series_logic()`. Pure orchestration — scraping, field mapping, Kavita calls, lifetime telemetry broadcast — with zero dependency on Flask or `app.py`. Also hosts Manual Review apply/preview/research paths (C29) and `seal_series_locks` (`NEEDS_RELOCK`). Comic Flexible cascade lives here.
*   **`services/manual_review.py`**: C29 park helpers — `create_review_from_candidates` / `create_confirm_from_auto` (both accept an optional `library_id`, used to build the Kavita verification link — §4.H), `choice_and_merge`, skip/confirm/purge emitters, pre-pick summary translation. Persistence goes through `db_manager.park_pending_review` / `close_pending_review` (atomic).
*   **`services/background_tasks.py`**: the daemon workers (`sync_queue` consumer + periodic auto-sync poller) and `start_background_workers()`, called once from `app.py` at import time (unchanged single-worker-process behavior, required for Gunicorn `-w 1`). Queue items are **dicts** built by `make_sync_item(series_id, series_name, force_update, fields_override=None, is_batch=False)` — no longer 3-/4-tuples. `is_batch` drives the dedicated `_batch_total`/`_batch_done`/`_batch_real_sends` progress counters (§4.F); auto-sync skips `PENDING_REVIEW` and filters candidate libraries through `select_auto_sync_candidates()` — the **only** place `DISABLED_LIBRARIES` applies (§4.J).
*   **`services/stats_service.py`**: playful `/stats` metrics + Chart.js payload from lifetime counters + cache snapshot + Manual Review achievements (`mr_achievements.py`). Gated by `ENABLE_PLAYFUL_STATS`.
*   **`services/changelog_service.py`**: `get_app_version()` / `get_current_version()` (cached) / `get_full_changelog_html()`. Imported independently by both `app.py` (global template context) and `routes/misc.py` (`/api/changelog`) — importing from here instead of from each other avoids a circular import.
*   **`routes/*.py`**: one Flask Blueprint per domain — `auth` (`/setup`, `/setup/test-kavita`, `/login`, `/logout`, `/account/password`), `pages` (`/`, `/stats`), `config` (`/save-config`, `/regenerate-webhook-token`), `series` (`/save-override`, `/toggle-ignore`, cover search/apply, `POST …/seal-locks`, `POST …/seal-locks-pending`), `sync` (`/force-sync` [enqueues at the head of `sync_queue` and answers 202 — no enrichment inside the request], `/batch-sync` [inventory cached per batch, see `_get_batch_inventory` §4.F], `/stop-batch`, `/reset-errors`, `/export-errors`, `/webhook`), `manual_review` (`/api/manual-reviews…` incl. `POST …/bulk-accept`), `companion` (`GET /companion/embed` — C33 MR shell for the browser extension; CSP `frame-ancestors` allows `chrome-extension:` / `moz-extension:` + optional `COMPANION_FRAME_ANCESTORS`), `library_audit` (Inventory scan, duplicates, `POST …/duplicates/script` — C85 renders a bash script and never runs it; no `DELETE /api/Series`), `misc` (`/healthz`, `/api/proxy-image`, `/api/changelog`). First-run `/setup` is a 6-step wizard (C64) that creates the account and merges Kavita / languages / options / cascades into `config.json`.
*   **C33 Companion** — see **§13** below (webhook flags, embed token, queue priority, extension layout). Short note: extension in repo `companion/` (Chrome + Firefox MV3).
*   **`sockets/handlers.py`**: Socket.IO handlers (`connect`, `fetch_covers_stream`), registered on `extensions.socketio`; imported once for side effects from `app.py`. Unauthenticated `connect` → `return False`; successful connect emits `manual_review_pending_count` / `manual_review_queue_summary` **to the connecting `sid` only**.
*   **`static/js/*.js`**: the former monolithic `script.js` is now plain `<script>` files loaded in dependency order (`utils.js` → `websocket.js` → `overrides.js` → `covers.js` → `config.js` → `batch.js` → `manual_review.js` → `license_nag.js` → `main.js`). No bundler and no `type="module"` on purpose: templates rely on inline `onclick="..."` handlers, which require every function to stay in the global scope.
*   **`templates/partials/*.html`**: the former monolithic `index.html` is now a thin shell that `{% include %}`s Jinja partials — including `_manual_review_modal.html` for C29 — one per self-contained UI region. Edit the relevant partial directly instead of scrolling through a single 600+ line template.
*   **`tests/`**: the pytest safety net (`conftest.py` fixtures + domain tests such as `test_auth.py`, `test_healthz.py`, `test_config_env_seeding.py`, `test_db_manager.py`, `test_kavita_api.py`, `test_playful_stats.py`, `test_manual_review.py`, `test_manual_review_bulk_accept.py`, `test_manual_review_queue_api.py`, `test_needs_relock.py`, `test_batch_inventory_cache.py`, `test_batch_progress_isolation.py`, `test_dashboard_renders.py`, `test_supporter_nag_policy.py`, `test_batch_targeted_fields.py`, `test_comic_flexible.py`, `test_scraper_mangabaka.py`, `test_routes_series.py`, `test_max_tags.py`, `test_max_genres.py`, `test_scraper_max_caps.py`, `test_audit_c1_c3.py`, `test_fallback_query.py`, `test_metadata_fetcher_smart_scoring.py`, …). Fixtures never touch the real `data/` folder or the network — `isolated_db` monkeypatches `db_manager.DB_FILE`/`DATA_DIR` to a `tmp_path` SQLite file, `flask_app`/`client` build a minimal Flask app registering only `routes/series.py` (not the full `app.py`, to avoid spinning up real background workers/logging), and `mock_kavita_api` stubs out every `KavitaAPI` network method. See §10. Also note shared helpers: `url_allowlist.py`, `csrf_utils.py`, `cors_config.py`.

⚠️ **Blueprint endpoint names changed.** Flask always prefixes a Blueprint route's endpoint with the Blueprint's name (e.g. the `login` view in `routes/auth.py`, registered on the `auth` Blueprint, becomes endpoint `auth.login` — there is no way to opt out of this prefixing). Every `url_for(...)` call and the whitelist in `auth_manager.setup_gate` / `login_gate` were updated accordingly (`auth.setup`, `auth.login`, `auth.logout`, `pages.index`, `pages.stats`, `misc.healthz`, `sync.export_errors`, `sync.webhook`). **If you rename a Blueprint or move a route to a different Blueprint, grep for its old endpoint string across `auth_manager.py`, `app.py` and every `.html` template before assuming `url_for()` still resolves.**

---

### 13. MetaKavita Companion (C33)

**Status:** beta / early access — **sideload only** (not on Chrome Web Store or Firefox AMO). Requires MetaKavita **1.6.5+**.

End-user install, pairing, and feature overview: [`companion/README.md`](companion/README.md) (EN + FR). Extension-only contributor notes (layout, message protocol, packing): [`companion/DEVELOPER.md`](companion/DEVELOPER.md).

#### What it is

MV3 browser extension under `companion/` that injects a floating action menu on Kavita **series detail** pages (`/library/{lib}/series/{id}` only — not the reader). Actions: Super Review, Auto, Cover pick, Config, Buy me a coffee.

#### Server surface (MetaKavita)

| Piece | Role |
|-------|------|
| `POST /webhook` | Auth via `X-Webhook-Token` (prefer) or legacy `?token=`. Companion may send `seriesId` alone (name resolved via `KavitaAPI.get_series`), plus one-shot flags `auto` / `super_review` (+ usual `force`). |
| `make_sync_item(..., super_review=, force_auto=)` → `enrich_series(..., force_auto=, super_review_override=)` | One-shot overrides; Companion buttons do **not** require global MR/Super toggles. |
| `put_front` (`services/background_tasks.py`) | Priority enqueue: after the in-flight job, ahead of the rest of `sync_queue`; drops pending same `series_id` (RAM + C63 `queued` rows). |
| `GET/POST /companion/embed-token` | Short-lived embed token bound to a `series_id` (`services/companion_embed_auth.py`). |
| `GET /companion/embed` | Manual Review shell for iframe / new-tab Super Review (`routes/companion.py`, `templates/companion_embed.html`). CSP `frame-ancestors`: `chrome-extension:` / `moz-extension:` + optional `COMPANION_FRAME_ANCESTORS`. |
| Cover APIs | Used by the extension background for Cover pick (same allowlisted download / proxy paths as the dashboard). |

#### Manual Review streaming

In Manual Review / Super Review paths used by Companion, enrichment parks an empty review early (`begin_streaming_review`) and appends cards as scrapers finish (`append_streaming_candidate` → Socket.IO), then `finalize_streaming_review`. This lets the embed open before the cascade completes.

#### Mixed content

HTTPS Kavita + HTTP MetaKavita: browsers block the HTTP iframe. Companion opens Super Review in a **new tab** (keep `opener`, no `noopener`) and closes it when the run finishes. Proper fix for in-page MR: serve MetaKavita over HTTPS (or use HTTP Kavita on LAN).

#### Auth / CSRF notes

- Webhook is CSRF-exempt (token auth).
- Embed token can authorize Companion embed + related MR/cover paths without a session cookie (needed inside cross-origin Kavita iframes / tabs). Prefer series-scoped checks where the route has a series id.
- Socket.IO Companion auth follows the same embed-token pattern for cover streams.

#### Tests

- `tests/test_companion_webhook.py` — `seriesId`, `auto` / `super_review`, enrich overrides
- `tests/test_companion_embed.py` / `test_companion_embed_auth.py` — embed shell + token
- `tests/test_companion_i18n.py` — UI strings
- `tests/test_sync_queue_priority.py` — `put_front` / replace pending
- `tests/test_manual_review_streaming.py` — streaming park / finalize

#### Packing the extension

```bash
node companion/scripts/pack.mjs
```

Writes `companion/dist/metakavita-companion-chrome.zip` and `…-firefox.zip`. Bump **both** `manifest.json` and `manifest.firefox.json` `version` when shipping a user-visible change. Do not commit unpacked `dist/_chrome/` / `dist/_firefox/` staging folders (gitignored).

Those zips are what users sideload, so repack in the same commit as the source change: the `companion` job in `tests.yml` runs `node --check` on every script plus three self-checks (`selfcheck-url-match.mjs`, `selfcheck-i18n.mjs`, `verify-dist.mjs`), and `verify-dist.mjs` fails when a zip lags behind its sources. See [companion/DEVELOPER.md](./companion/DEVELOPER.md).

<br><br>

---

### 14. Volume & Album Enrichment (#27)

#### The rule that governs everything: read the chapter before writing it

A Kavita volume has no metadata of its own — the metadata lives on its **chapters**. Writing a volume therefore means writing its chapters, through `POST /api/Chapter/update`.

`UpdateChapterDto` is a **total replacement**. Every field missing from the payload takes its default value, and the controller assigns unconditionally: omit the summary and it is emptied, omit `writers` and every author is erased, `ageRating` falls back to *Unknown*, the twenty locks to `false`, and `sortOrder` to **0** — which destroys the reading order of the whole series.

So: **read the chapter, merge, rewrite the whole thing.** `services/kavita_chapter_payload.build_update_chapter_dto(current, changes)` copies every field of the `ChapterDto` that was read — `sortOrder`, the thirteen people collections, genres, tags, `ageRating`, `language`, `webLinks` and the twenty locks — then applies the changes on top and locks only what it wrote. Never build that payload by hand.

`apply_entry` re-reads the chapter immediately before writing, even when a plan already exists: a preview built ten minutes ago describes a state the user may have edited since. A read that fails is a `FAILED` unit, never an empty dict — an empty dict would pass for a chapter with no metadata and the write would erase everything.

#### Provider contract: `fetch_volume_index`

```python
def fetch_volume_index(self, query, library_type="Comic", series_id=None,
                       existing_metadata=None):
    """Index of a series' volumes/albums: {number: payload}. Default: None."""
```

One network call for the whole series wherever the provider allows it — ComicVine's `/api/issues/?filter=volume:X&limit=100` returns a hundred issues, summaries and covers included, so a 150-issue run costs two calls. `fetch_volume` (one call per volume) only exists for providers that cannot list.

Payload keys: `title`, `summary`, `release_date`, `isbn`, `cover_url`, `provider_ref`. Declare `scopes = {"series", "volume"}` so `ScraperRegistry.get_by_scope("volume")` picks the scraper up. HTML providers must cap their walk (`VOLUME_INDEX_MAX = 50` on Bédéthèque and Planète BD at 2.5 s, **40 on Manga-News at 6 s**): an uncapped index is a quarter of an hour of silent scraping, and on Manga-News it is also how you get Cloudflare to block the address. `fetch_index` does not stop on a cover-only answer: MangaDex listing every volume by its cover must not prevent Manga-News from being asked for titles and summaries.

#### Matching, and Kavita's sentinels

Kavita files chapters without a volume under volume **-100000** (`Parser.LooseLeafVolumeNumber`) and specials under **100000** (`Parser.SpecialVolumeNumber`). `services/volume_enrichment/matching.py` neutralises both: taking them for volume numbers would ask a provider for "album 100000", and — worse — would write volume 1's data onto a spin-off. `number_key` also normalises `3.0`, `"3"` and `"03"` to one key, without which none of the three providers would ever match.

#### Module map

| Module | Role |
|--------|------|
| `services/kavita_chapter_payload.py` | Builds `UpdateChapterDto`, normalises release dates, validates ISBN-10/13 (Kavita silently rejects an invalid one) |
| `services/volume_enrichment/matching.py` | Kavita response → writable units; number matching; sentinels |
| `services/volume_enrichment/plan.py` | Fill-the-blanks policy. Pure — **no I/O**, which is what makes the preview a preview |
| `services/volume_enrichment/apply.py` | Re-read, write, upload cover, persist unit state |
| `services/volume_enrichment/providers.py` | Provider selection, throttling, ISBN cascade, title + number search. `resolve_index()` is the entry point: it is what completes a cover-only index with the cascade instead of stopping there |
| `services/volume_enrichment/translate.py` | Album summaries into the target language, applied **to the plan**, memoised on the source text |
| `services/volume_enrichment/job.py` | Library-wide pass in a dedicated thread |
| `routes/volume_enrichment.py` | Preview / apply / library pass / status / cancel, all behind a 403 guard |

`job.py` does **not** go through `sync_queue`: that queue has a single worker shared by the Kavita webhook, auto-sync and every row button, and a thousand-volume pass would freeze all three for hours. It follows `library_audit/hygiene_scan.py` instead — one thread, one state under a lock, cooperative cancellation between units. The resume filter — `list_enriched_series_ids` at series level, `volume_unit_cache` at unit level — applies only when **no** explicit selection is given (`resume and not series_ids`). Since the toolbar always sends the ticked series, a pass started from the interface never skips: naming a series is an explicit request, and `VOLUME_FORCE_OVERWRITE` is the only lever the interface offers to redo one, so a silent skip would make that switch do nothing. What the cache still serves: the per-unit states shown in the preview, and `POST /api/series/<id>/volume-enrich/reset`.

#### Translation runs on the plan, not on the index

`translate_plan_summaries()` is called **after** `build_plan()`, and only touches summaries whose change carries `write: True`. It first ran on the whole provider index, before matching, which meant one network call per album the provider knows: a hundred ComicVine issues for the ten volumes Kavita holds, and on a series already enriched, every summary translated again on every pass — filled and locked, so written nowhere. The log read as one line per second for minutes. A series already done now costs zero calls. The duplicate that the index grain avoided (one album covering two chapters) is covered anyway, because the memo is keyed on the source text. Two consequences to keep in mind when touching this: `translate_texts(..., quiet=True)` is deliberate — the translator logs one INFO line per request, which drowned the pass's own progress, so this module reports a count instead; and a translation that lands exactly on what Kavita already holds flips the change back to `filled` and the plan's counters are recomputed, otherwise a forced pass would announce a write and rewrite the same sentence.

The summaries then leave in a **single call** for the whole series (`_translate_and_remember`), which is what puts the pass out of a block's reach — see rule B in the audit section. Two things follow: the pending list is gathered before anything is sent, so a series whose summaries are all memoised costs no request at all; and a reply whose length does not match what was sent is dropped rather than distributed, because a shift would lock one album's summary onto another.

#### Two keys, and a series with neither is set aside before the first call

A unit is matched on a **volume number** or, failing that, on its **ISBN** — `matching.unit_key()`. ISBN keys carry the `isbn:` prefix (`ISBN_KEY_PREFIX`), which is not a number, so the two kinds cannot collide inside one index; `index_key()` is the reader side of the same rule, and it is what `normalize_index()` now uses. `fetch_by_isbn` files its results with `unit_key`, so a numbered unit keeps its number (unchanged) and a one-shot gets its own ISBN. The ISBN is the surer of the two keys, not the fallback it looks like: it designates an edition, where a number only assumes we are talking about the same series.

`matching.unmatchable_reason(units, series_name)` runs in both provider paths — `_enrich_one_series_locked` for the pass, `build_series_plan` for the preview and the single-series write — right after the volumes are read and **before** anything hits the network. It returns `oneshot`, `specials` or `""`.

The reasoning is structural, not a heuristic: `fetch_index` filters its index through `normalize_index(index, keys=wanted)`, and `fetch_by_isbn` and `fetch_by_title_volume` skip any unit with no key. So when no unit yields one, no cascade can produce a single writable entry — the search is provably wasted, and on an HTML provider it costs up to two minutes plus a pacing slot for everyone behind it. The pass calls `mark_series_pass_done()` on the way out: the verdict was reached without a call, so there is nothing for a resume to retry.

`resolve_index` takes the matching shortcut from the other end: **no volume number** means the album index has nothing to match, so it goes straight to the ISBN cascade and never asks for an index. Watch the guard — `if units and not matchable_numbers(units)`. An empty `units` means *the caller told us nothing about the series*, which is the convention `_covers_enough` already honours for tools and the single-volume preview; knowing nothing must not close the album index.

Three things here must not drift:

* the predicate keys on the **absence of any key**, never on the number of units. A series you own only volume 1 of yields the key `1`, is searched, and must stay searched — that is the case per-volume writing exists for, and setting it aside would also mark it settled and hide it for good;
* a **title decides nothing**. `one shot` in a series name is just as likely a publisher's collection, and a numbered collection must keep being served. `series_name` stays in the signature for a future reason to need it, not for this one;
* `matchable_numbers` / `matchable_keys` drop **specials only**. The missing `chapter_id` is a different question — where to write — and it belongs to `match_units` and to `unmatchable_reason`, which is why the latter filters on it itself. Fold the two filters together and hand-built units (tools, tests) lose their album index.

`plan_unit` records `matched_key` next to `matched_on`. `matched_on` stays the *number*, because it is what the preview's *Volume* column shows and `isbn:9782800…` does not read as one; `matched_key` is what `_mark_duplicates` groups on, so two files of the same one-shot are flagged through their shared ISBN instead of both being written in silence.

The Inventory deliberately does **not** get the same shortcut. Its catalogue call is what decides one-shot versus incomplete (`catalog_expected == 1` versus `> 1`), so a local short-circuit would classify a manga you hold one loose chapter of as a finished one-shot — the exact opposite of what the Inventory is for.

#### What the log owes the person watching it

Two rules, both enforced by `tests/test_volume_enrichment_journal.py`.

**A series is named, and numbered beside the name.** `secure_logging.series_label()` renders `« Blacksad » (6429)`, falling back to `« series 6429 »` — announced as an identifier — when Kavita returns no title. It lives in `secure_logging` and not in a volume module because the Inventory scan, the volume pass and series enrichment write into the same log, and the reader has no reason to meet three ways of naming the same series. `plan.unit_label()` does the same for a unit: `volume 3`, not the chapter identifier the user has never seen. `apply_plan()` reads the name from `plan["series_name"]` rather than taking a parameter — both callers already fill it, and a signature nobody can forget to pass beats one that logs a number when they do.

**Every phase over a second opens and closes.** The album search, the translation and the write each log a line when they start (`▶ … recherche des albums…`) and a line with their result and duration when they finish; the pass itself frames the whole run. This is not decoration: a series can take a minute, and the failure that led here — a cover download that never returned — was indistinguishable from a pass that had never started, because nothing was logged between the plan and the final tally. The closing line always carries the elapsed time, which is what turns *it's slow* into *the provider took 12 s and the covers 5 s*. The cancelled tally carries its own mark (`⛔`), since a tick on an interrupted pass reads as a pass that went through.

#### Switches

`VOLUME_ENRICHMENT_ENABLED` (off by default — the API answers 403 while it is), `VOLUME_FORCE_OVERWRITE` (lifts the fill-the-blanks rule, danger block), `VOLUME_ENRICH_CREDITS` (one extra request per album), `VOLUME_ENRICH_EXPERIMENTAL` (title + number search, see below).

Provider order is **not** a switch of its own: `volume_providers()` reads the Providers modal cascade for the library type (`COMIC_PROVIDER_1..3`, `BOOK_PROVIDER_1..3`, `PROVIDER_1..3`), the same one series enrichment uses. `ScraperRegistry.get_by_scope()` sorts by display name, which put Bédéthèque ahead of ComicVine on every comics library — and since `fetch_index()` keeps the first non-empty index, a franco-belge namesake was enough to write another work's volumes. Providers the cascade does not name keep the registry order, after the named ones. Two exceptions, both for volumes only, neither touching the series cascade: on a **Manga** library Manga-News is asked first (`MANGA_VOLUME_LEAD`), because it is the only manga index that returns title, summary, ISBN and date rather than covers Kavita already has; on **ComicFlexible** the comic wave still goes first, then Manga-News as the manga last resort, then MangaDex for covers.

**Two families of provider, and `VOLUME_PROVIDER` names either.** `volume_providers()` is built on `get_by_scope("volume")`, so it only ever held the providers that can *list* a series' albums. `UNIT_PROVIDERS` — Google Books, Open Library, Hardcover — answer one unit at a time, by ISBN, and fill what a series index left blank (Manga-News lists VF volumes; MangaDex only covers); they were serving volumes from the start while being invisible to the setting, which logged *forced provider unusable* and resumed the cascade. Forcing one of them now returns `[]` from `volume_providers()` — deliberately, since asking someone else for an index would be the opposite of the setting — and `resolve_index()` reads that through `forced_unit_provider()`: it skips `fetch_index` and passes `provider_ids=[forced]` to `fetch_by_isbn` and `fetch_by_title_volume`. When the forced provider has nothing left to try (no ISBN on the volumes, and it is not in `TITLE_VOLUME_PROVIDERS`) an `INFO` line names the setting, because the preview shows *no provider knows this series* and would otherwise accuse the provider.

⚠️ **Forcing a `TITLE_VOLUME_PROVIDERS` member is itself the permission `VOLUME_ENRICH_EXPERIMENTAL` asks for**, so `resolve_index()` runs the title + number search for a forced Google Books whatever that switch says; the switch keeps governing the automatic cascade, where nobody named a provider. Reading it as an `and` was the whole reported failure on manga: forcing the one provider that can find a volume without an ISBN suppressed the index (see above) *and* refused the only remaining path, so the gesture meant to fill an empty preview guaranteed it stayed empty. Keep the implicit opening tied to `unit_only` — an unforced cascade must not start searching without an identifier on a whole library. `volume_provider_choices()` builds the sidebar menu from the same rule, tagging each entry `index` or `unit` for the two `<optgroup>`s — a flat list would have people forcing Open Library on a library of scanned comics, where it can only ever return nothing.

`provides_volume_index(scraper)` replaced `hasattr(scraper, "fetch_volume_index")`, which answered yes for everyone: `BaseScraper` defines the method and its version returns `None`. It compares the bound `__func__` against the base implementation, so a third-party scraper declaring `scopes = {"volume"}` without writing the method no longer costs a `throttle_provider` slot per series for a guaranteed empty answer.

Two switches narrow that list rather than reorder it. `VOLUME_NO_MANGA_FALLBACK` drops scrapers whose `supported_types` exclude `Comic`, and **only on `ComicFlexible`** — it is the one library type that deliberately chains both cascades, so it is the only one where a fallback can be dropped without leaving a library with no provider. `VOLUME_PROVIDER` keeps one scraper and drops the rest, but only if it is already a candidate for that library type: forcing a comic provider must not leave a manga library with an empty list, which would surface as *no provider knows this series* and accuse the provider instead of the setting, so the cascade resumes there with an `INFO` line. Both belong to `index_cache._cascade_signature()` — they change the list consulted, hence the index, and an entry lives ten minutes.

The feature is independent of the Inventory. The two share the volume report modal, but only `library_audit.series_volume_report_units` — rebuilt from Kavita alone, no provider call — is exempt from the Inventory's 403 guard when `VOLUME_ENRICHMENT_ENABLED` is on. Anything that costs a provider call stays behind the Inventory, and the front end (`_inventoryOff()` in `library_audit.js`) asks only for the detail in that mode. In the toolbar, the pass has its own `.toolbar-group--volumes`: inside `#inventoryPanel` it inherited `body[data-inventory="0"] .toolbar-group--hygiene { display: none }` and vanished with a feature it does not depend on.

#### Sidebar conventions these switches follow

The sidebar saves without reloading (`saveConfig()` posts and returns), so **a `{% raw %}{% if %}{% endraw %}` in the template cannot gate a switch on another switch**: the condition is only re-evaluated on the next page load, which reads as a switch that does nothing. State that crosses the panel is therefore held in CSS, with `:has()`:

| Class | Role |
|-------|------|
| `.so-switch--volumes`, `--lab` | Family colour, like `--smart`, `--review`, `--golden`, `--danger`. Green for the volume family, amber for the experimental path — the only one with no identifier to verify itself |
| `.so-sub--volumes` | Block that depends on a master switch: greyed and `pointer-events: none` while `#sidebar_volume_enrichment` is unchecked. The **Providers** button stays outside it — that cascade also serves series enrichment |
| `.so-sub-note` | Shown only in that state, to say why the block is inert |
| `.so-needs-volumes` | For a dependent setting living in **another** category (`VOLUME_FORCE_OVERWRITE`, in the write danger block). Anchored on `.scraping-options-body`, the only common ancestor: `.so-anim-inner` also dresses each category panel, and the write panel does not contain the master, so anchoring there hides the setting for good |
| `.so-hint` | One-line hint under a switch. The class was used by seven paragraphs with **no CSS rule at all**, so they rendered at body-text size in a column spaced for 2px |

Long explanations belong to the help modal (`scraping_help_*`, one section per sidebar category, behind the **?**), not to `so-hint`. Tests: `tests/test_volume_enrichment_ui.py` asserts the anchor, the orphan-free help keys and the hint length ceiling.

**Showing and hiding a toolbar group takes three parts, and two are not enough.** The sidebar saves without reloading, so a Jinja condition around the group is not a way to gate it: evaluated once at load, it left the Volumes block on screen after unticking and absent from the page after ticking — the switch looked broken both ways (BF169). The contract, the same one `#inventoryPanel` follows: (1) the template renders the group **unconditionally**; (2) `<body>` carries the marker, written by the template at load *and* by `onVolumeEnrichmentToggle()` on every tick; (3) a CSS rule reads the marker and hides the group. Part 3 was the one missing, while the comment above part 2 claimed it existed — so write the assertion on the rule, not only on the function that sets the marker. The volume rule is `body:not([data-volumes="1"])`, not `[data-volumes="0"]` as the Inventory's is: the Inventory is on by default and can obey an explicit `0`, where the volume pass is off by default and its button writes, so a missing marker must keep it hidden. Its one exception is `[data-volume-pass="running"]`, set by `_setVolumeEnrichRunningUi()`: unticking does not stop a running pass — the flag only refuses new ones — and **Cancel** lives in that group, so hiding it would leave a write going with no way to end it.

**Light mode: hiding a category must switch its feature off (C80).** `UI_SHOW_MANUAL_REVIEW`, `UI_SHOW_INVENTORY` and `UI_SHOW_VOLUMES` remove a sidebar category, listed on `<body data-ui-hidden="…">` as space-separated words and read by `[data-ui-hidden~="manual"] .so-cat[data-so-cat="manual"]`. One attribute rather than three because `data-ui-inventory` next to `data-inventory` would not say which one hides and which one switches off. The pairing itself is the load-bearing part: a category that has left the screen commands nothing, and two of these three write to Kavita — a hidden manual review left on fills a queue nothing empties, a hidden volume pass left on keeps a write button in the toolbar whose forced provider can no longer be changed. `config_manager.apply_light_mode()` holds the rule and `LIGHT_MODE_FEATURES` holds the mapping; it runs on **read** (so an environment variable or a hand-edited `config.json` cannot produce a running feature with no reachable switch) and again in `routes/config.py` on save, **before** the manual-review purge, which compares `was_manual` against the final value — otherwise hiding the category would switch the mode off and strand its queue. Dependent manual-review flags are switched off too, because `routes/companion.py` reads `MANUAL_REVIEW_COVER_PICK` on its own; the volume dependents are left as they are, since they only apply inside a pass that no longer starts, and keeping them gives the user their choices back. `onUiSectionToggle()` mirrors the rule on screen: it unticks the sidebar master, sets `data-inventory` / `data-volumes` to `0`, and saves once. It never re-enables anything on the way back — a revealed category comes back off. Tests: `tests/test_ui_light_mode.py`.

#### Six traps this module is built around

**A series matched once must not be matched again.** `build_series_plan` and `enrich_one_series` pass `provider_hints(series)`, which carries the seven external ids of the `SeriesDto` — the ones series enrichment wrote. Without them the volume path fell back on a **title search** every pass, and a title search can land on another edition: the provider answers, the album list is complete and valid, and not one of its numbers matches Kavita's, so the preview comes back empty (*Gaston Lagaffe*, with an Inventory reporting 23 expected volumes from that very provider). The hints are named per provider — `comicvine_id`, `mal_id`… — and never generic: `_resolve_volume_id` also reads `provider_id` and `url`, so filling those would hand ComicVine an id issued by AniList, which is the trap `forced_id_for()` exists to close.

**A forced id belongs to one provider.** `series_cache.forced_id` is meaningless outside the provider that issued it: `30002` is an AniList series, and ComicVine will happily read it as a volume id and return a complete, coherent, wrong index — written volume by volume, locks included, with nothing on screen to say so. `forced_id_for()` hands it over only to the named `forced_provider`, or to the provider a URL's domain designates.

**A volume is not always the unit.** `unit_number()` matches on the volume number only when the volume holds a single file. A volume holding several chapters is a container — the ordinary comics case, where Kavita files a whole run under volume 1 and makes each issue a chapter — and matching on the volume would give issue #1's summary and cover to fifty chapters. That is what `sibling_count` is for.

**`coverImage` is never empty.** Kavita always cuts a thumbnail from the first page, so the fill-the-blanks rule cannot read it: `FIELD_SOURCES["cover_url"]` deliberately has no read key, and only the lock guards covers. Since MetaKavita locks what it uploads, the next pass leaves its own work alone.

**A truncated number is a collision.** Every index loop keeps the first entry it sees for a key, so two albums landing on the same key means one silently takes the other's metadata. French BD publishers number their intercalary one-shots 1.5 or 3.5, and both HTML parsers used to drop the decimal: a 1.5 met before volume 1 took its key, and the real volume 1 left with the one-shot's summary and cover. Album numbers go through `scrapers.utils.album_number_key()`, whose output must stay byte-identical to `matching.number_key()` on the same value — a `1,5` or a `1.50` would match no Kavita volume at all, and would fail without a word.

**A search is not a match.** `fetch_by_title_volume` (behind `VOLUME_ENRICH_EXPERIMENTAL`) is the only path with no identifier at all. The verification lives in the provider — `_title_matches_series` and `_volume_in_title` in `googlebooks.py` — and it must stay strict: the number is only read where a keyword announces it, otherwise `20th Century Boys` reads as volume 20.

#### Tests

The one that matters more than the rest: start from a **fully populated** `ChapterDto`, change only the summary, and check that every other field comes back identical (`tests/test_volume_enrichment_end_to_end.py`, `tests/test_kavita_chapter_payload.py`). Without it, a regression would destroy the reading order and the credits of entire libraries.

### 15. Invariants From the v1.7.0 Audit Campaign

Seven rules the campaign turned into architecture. Each replaced a defect that a test suite had been green through, so each has a test that fails if it comes back.

#### A. Core scrapers are versioned, and a downgrade is refused

What runs in a container is **not** what is in the image: the image seeds `data/scrapers/` on boot, and `services/scraper_manager.py` loads that folder and nothing else. Two sources write there — the community catalogue first, the image only to fill the gaps — and the only comparison used to be an sha256 equality, which tells you that two copies differ but never which one is newer. A scraper fixed in a newer image could therefore never replace the catalogue's older copy, and `get_by_scope("volume")` returned an empty list in production while the tests, which load those scrapers by file path, stayed green.

Every core scraper now declares `version` on its class (`BaseScraper.version`, read by the catalogue generator too). `parse_version` / `version_is_newer` / `file_scraper_version` / `package_scraper_version` / `installed_scraper_version` in `scraper_manager.py` decide replacement by version, and `scraper_store._catalog_core_is_downgrade` refuses a catalogue entry that is older than the installed copy, logging both versions at warning level. **Bump `version` in the same commit as any core scraper fix**, or the image will not be able to deliver it. And when you add a capability to a core scraper, assert it through the **registry** (`get_by_scope(...)`), never by importing the file: `tests/test_core_scrapers_volume_scope.py` and `tests/test_core_scraper_versioning.py` exist because a file-path import hid the whole failure.

Versions arbitrate *which copy is newer*; they say nothing about *whether this image can run it*. A catalogue scraper executes inside the image, against its `BaseScraper` and its `scrapers/utils`, so a copy written for a later release fails at import on an earlier one — `ImportError` on a name that does not exist yet — and the registry unbinds it per scraper, leaving the provider gone from every search. The v1.7.0 core scrapers are exactly that case: all 21 call `self._http_get` and import `response_is_ok`, neither of which exists in 1.6.x. A catalogue entry may therefore declare a floor (`requires_app`, or `min_app_version` / `requires_metakavita`), read by `scraper_store.entry_requires_app` and enforced by `is_entry_too_new` on the three paths that can write a file: `sync_core_from_catalog` skips and logs, `install_from_catalog` refuses with 409, and `enrich_catalog_for_ui` reports `too_new` while suppressing `update_available`. Equality installs — a floor reads *from this version onwards*. **When a core scraper starts using a helper introduced in the current release, its catalogue entry needs that floor**, otherwise publishing it removes the provider from every older install. Tests: `tests/test_scraper_manage_store.py`.

#### B. Pacing belongs to the request, not to `fetch()`

`throttle_provider` (`services/provider_throttle.py`) used to be called once per `fetch()` — while a `fetch()` issues 6 to 25 HTTP requests. Planète BD sent 25 requests back to back against a declared 2.5 s pace, and `locg.py` did not even import `time`. **This is what got the developer's IP banned by Bédéthèque during the campaign**, and a ban then reads as *no results* everywhere.

Scrapers must therefore go through `BaseScraper._http_get` / `_http_post`, which apply the provider's pace **per request** and carry a default 20 s timeout. `tests/test_scrapers_are_throttled.py` walks `scrapers/*.py` and fails on a session call made directly, so a new scraper cannot reintroduce the pattern. Deliberate product decision, recorded in `ROADMAP.md` under Parked: **no global pacing net** around every outgoing request. A community scraper that bypasses the helper can still burst; that is treated as that scraper's bug, in its own repository, rather than paid for by a chokepoint on every request.

**The translator is a provider too, and it had no pace at all.** `translator.py` sent one request per text, back to back. Google is the engine that matters here: `googletrans` and the `translate_a/t` endpoint hit the site's internal API, with no published limit and no contract, and public reports put the block after a few dozen close requests — the same traffic shape as the Bédéthèque ban above. DeepL and Azure do not ban; their limit is a volume (DeepL Developer: 1,000,000 characters **once, never renewed**; legacy Free keys: 500,000 a month, HTTP 456 when spent; Azure F0: 2 M characters a month, throttled at 2 M/hour smoothed, i.e. ~33,300 a minute, 429 above that even with the monthly quota intact).

Two measures, and their invariants. **Grouping**: `translate_texts()` is now the entry point and every engine takes several texts per request — Google up to 20 per POST (`q` repeated; its bulk helper in `googletrans` loops instead, which is exactly the traffic that blocks), DeepL 50, Azure 1,000 within 50,000 characters. A whole series fits in one or two requests instead of forty, and identical texts are sent once. **The number of translations returned is checked against the number sent**: a truncated response would slide one album's summary onto the next, and the volume pass writes *and locks*, so the error would be permanent. On a mismatch the source text is kept. **Pacing**: a minimum interval since the same engine's last request, on `provider_throttle`'s own clock under the key `translate:<ENGINE>` — 5 s plus jitter for Google, 0.5 s for DeepL, and for Azure whichever is longer between 1 s and what the payload costs at 555 characters a second. Because it is a *minimum since the last call*, the series path — one summary between two scrapings — pays nothing.

A 429 is not the same event everywhere: Google's is an address block, so it is never retried (coming back only extends it) and the engine is set aside for 15 minutes; DeepL and Azure are retried at 5 s then 15 s, then set aside for 5 minutes; DeepL's 456 sets the key aside for 6 hours, since a free credit does not come back on its own. A set-aside engine falls through to the cascade instead of being asked again once per volume. Everything degrades to the source text rather than raising — which is precisely why the count check and the set-aside matter more than the retries: **an untranslated summary is written and locked, so it is untranslated for good**. Tests: `tests/test_translator_cadence.py`, which takes over the clock through `real_provider_throttle_sleep` rather than actually sleeping.

#### C. A failure must name its cause

A revoked key, an expired token, an exhausted quota and a 403 ban all returned what an unknown series returns: nothing, and no log line. `scrapers/utils.py` carries the reporting: `provider_error_scope` (a `ContextVar`, so it crosses the thread pool the same way `match_accept_threshold_scope` does — remember `ThreadPoolExecutor.submit()` does not propagate context, submit through `contextvars.copy_context().run(...)`), plus `note_provider_error`, `log_provider_http_error` and `response_is_ok`. Auth failures log at error level (only the operator can fix them), quotas at warning with `Retry-After` when the provider gives one. ComicVine needs `status_code` read from the **body**: it answers HTTP 200 with an application error, which used to pass for an empty catalogue.

#### D. The test suite may not touch the network

`tests/conftest.py` installs a barrier at two levels: `socket` **and** `curl_cffi`, because libcurl bypasses Python's socket layer entirely — patching one only moves the problem. Loopback is allowed (the Flask test client needs it), anything else raises `RealNetworkAccessError`. Since scrapers catch broad exceptions, a blocked call would otherwise be swallowed into a silent *no results*: refusals are recorded in `_NETWORK_REFUSALS` and reported at teardown. A test that genuinely needs the network requests the `real_network_access` fixture, and must never aim at a provider.

Two autouse fixtures come with it: `_no_real_translation` (16 tests were really calling DeepL then Google Translate on every run, errors swallowed — it stubs `translate_texts` as well as `translate_text`, since the batch is a second way out) and `_no_real_provider_throttle_sleep` (the per-request pace of rule B would otherwise add minutes to the run). Never rebind a shared class globally in a test — one test reassigned the HTTP session class and disarmed protection for everything that ran after it; use `monkeypatch` so it is undone.

#### E. One cooperative worker: a long computation must hand back control

`gunicorn -w 1` with the eventlet worker, and `app.py` monkey-patches before anything else, so the `threading.Thread` of the volume pass and the hygiene scan are greenthreads. A pure-computation loop never yields, and for its whole duration **no HTTP request is served and no Socket.IO event is emitted** — including the progress of the very task running, which looks frozen. `services/cooperative.yield_to_worker()` is a `time.sleep(0)`: monkey-patched it goes through the scheduler, outside monkey-patching (pytest, measurement scripts) it costs nothing measurable, so it can be dropped into loops without conditioning the code on the deployment mode.

Duplicate clustering is the worked example (`services/library_audit/duplicates.py`): quadratic, 152.8 s of pure computation on 1,500 series in the worst case measured, zero requests served. It now yields every `_YIELD_EVERY_PAIRS = 2000` pairs, buckets on all distinctive words (`_word_set_key`) instead of the first word when the threshold is high, and unions groups instead of rebuilding them pairwise — same groups, under a second. Any new loop over a whole library must yield the same way.

**`curl_cffi` is libcurl, and its streaming mode is unusable here.** `Session(thread="eventlet")` routes `curl.perform()` through `eventlet.tpool`, a real system thread, so the hub keeps turning during a transfer — but **only on the non-streaming path**. With `stream=True` the setting is ignored: `perform()` is submitted to a `ThreadPoolExecutor` and the body is delivered through a queue, and the `timeout` no longer applies to it. A host that answers and then goes quiet is then waited on with no end, and no deadline checked between two pieces can fire, since it is the wait for the next piece that never returns — measured at 8 s against a 5 s limit (`debug/repro_cover_eventlet.py`); the same request without `stream=True` ends on *Operation timed out after 5007 ms*. That mode also leaks one executor per session, which `Session.close()` does not shut down. So: read the body in one go and cap it afterwards (`kavita_api._cover_http_session`, `_download_cover_base64`). The trade-off is deliberate — an oversized body is received before being refused, bounded by `COVER_FETCH_TIMEOUT_SECONDS` and, for honest hosts, refused on `Content-Length` without reading a byte. `requests` has none of this problem: it is monkey-patched, so `stream=True` stays cooperative and its timeout applies to every read — which is why the image proxy (`routes/misc.py`) keeps it and enforces its cap piece by piece.

#### F. SQLite: keep the connection, memoise the schema

Writing one volume's state cost 19 ms, and the cause was not the DDL: **closing** a connection checkpoints the WAL, so the price was paid at every close. `db_manager._wal_keeper` holds one idle connection open for the process's lifetime, which keeps WAL mode meaningful; with `synchronous=NORMAL` the write is 0.95 ms. `_schema_ready` memoises migrations rather than replaying them on every call (a read path was acquiring a write lock), and `_ensure_schema` inspects `_table_columns` instead of swallowing `OperationalError` — a read-only volume or a full disk used to surface as a 500 with no explanation. Commit a migration that succeeded, or it re-runs for ever.

#### G. Kavita DTOs are total replacements — echo, never assume

Read `kavita_api.md` first, then hold these:

* `UpdateChapterDto` **and** `UpdateSeriesDto` replace the entity. A key absent from the JSON body arrives as `null` in .NET and is written as `0` / empty. Omitting `sortOrder` alone destroys a series' reading order.
* `SERIES_EXTERNAL_ID_KEYS` (`aniListId`, `malId`, `hardcoverId`, `metronId`, `comicVineId`, `mangaBakaId`, `cbrId`) must be echoed by **every** payload sent to `POST /api/Series/update`, including one that claims to touch only locks. `series_external_ids(current)` does it from the read state.
* `Format` / `FormatLocked` **has never existed** in `UpdateSeriesDto` (checked from 0.5.0 to 0.9.0.20; `SeriesDto.Format` is a `MangaFormat` deduced from the file type and unrelated). Do not add it back: the write was dead from day one, and it cost a read plus two writes per series. `resolve_kavita_format_enum` survives for UI display only.
* Library types: Kavita names `Comic = 1` “Comic (Flexible)” and `ComicVine = 5` “Comic”. `kavita_constants.LIBRARY_TYPE_BY_ENUM` is the only mapping to trust — it also files `Image` with manga and `LightNovel` with books.
* Sealing locks: pass `lock_keys` from `lock_keys_from_payload(...)` on automatic paths so the seal closes only what was written. The manual paths (🔒 button, `/api/series/<id>/seal-locks`) deliberately keep the broad seal guarded by `_has_content` — see `ROADMAP.md` B4 for why.
* A chapter write consults **no** lock on Kavita's side. Fill-the-blanks has to be enforced client-side (`filter_people_payload`), or a locked credit collection is replaced and Kavita answers 200.
* Long runs: `_send` replays authentication once on a 401 (a token lives three days, a library pass can outlast it). Covers are measured and type-checked before upload (`_download_cover_base64`): base64 inflates by a third, and an allowed host can answer an HTML error page under a 200.

#### H. Inventory duplicates are a script, not a Kavita delete (C85)

`DELETE /api/Series/{id}` only drops the database row. The files stay; the next library scan recreates the series. Meta does not mount Kavita media and must not remember deletions while Kavita puts the files back. So:

* There is no Delete button and no `POST /api/series/<id>/kavita-delete`. Do not add either back. `KavitaAPI.delete_series` is gone for the same reason.
* `POST /api/libraries/<library_id>/duplicates/script` only renders text. Meta never executes the script.
* The prefix is a POSIX path (`INVENTORY_FOLDER_PATH_PREFIX`, `resolve_script_folder_path` in `services/library_audit/dup_script.py`), not an HTTP URL. Kavita may return `/comics/X` while the disk is `/mnt/media/comics/X` — the prefix is `/mnt/media`. An `http://` is rejected. The old `INVENTORY_FOLDER_URL_PREFIX` migrates only if it is already a path, then is popped.
* Prefix and trash live in the Duplicates modal footer, not the config sidebar.
* The UI keeps at least one series unticked per group (`_enforceDupKeepOne` in `library_audit.js`). A member without a folder path counts as an implicit keep. Dismissing a group (`keepBody: true`) must not clear the remaining Trash ticks.
* Examples stay generic (`/mnt/media`, `/comics/X`). Do not put a LAN IP or a host disk name in user-facing text.
* Tests: `tests/test_dup_folder_script.py`.

### 16. `CHANGELOG.md` Is a Data Source, Not Just a File (C82)

The **What's new** modal is `CHANGELOG.md` rendered by `services/changelog_service.py`, injected with `innerHTML`. That renderer is deliberately **not** a generic markdown converter: it reconstructs the file's structure — release, sections, entries — because that structure is what makes a thousand-line file readable in a 820 px modal. Which means the file has a grammar, and breaking it degrades the modal silently.

* `## [1.7.0] - 2026-08-13 (short title)` opens a release. Version, date and title are read separately; the parenthesised title is optional.
* `EN` / `FR` alone on a line opens a language block (a bare `🇫🇷` is accepted for the old releases that used it). Anything before the first marker belongs to both languages. **Only the requested language is rendered**, `UI_LANG` deciding, with a fallback to everything when a release has no block for it — an English paragraph beats an empty release.
* `### ✨ Label` opens a section, and the leading emoji **types** it: colour, icon and count come from `_SECTION_KINDS` (`warn`, `new`, `fix`, `security`, `limits`, else `plain`), with a keyword fallback for the releases written before the convention. The icon is resolved from the shared sprite, so a new kind needs its `<symbol>` in `_icons_sprite.html` — `<use href="#missing">` draws nothing and reports nothing.
* `* **C69. Title** — body` is an entry. The title is the **leading bold and it may not contain `**`**: the pattern is anchored and non-greedy for that reason, and a bold that spans further would otherwise swallow half the entry. `—`, `:` or nothing are all accepted as the separator. A `C\d+` / `BF\d+` prefix becomes the chip you can cite in an issue. Sub-bullets are indented by exactly two spaces and stay nested.
* A trailing `Tests: \`tests/x.py\`` is **stripped from the render and kept in the file**: it is addressed to the maintainer, and a reader of the release notes has nothing to do with it. A sub-bullet that is only that disappears entirely.
* `_format_inline_markdown` escapes **before** wrapping, and links accept `http(s)` only. Do not reorder it: the file quotes `<script>`, and one unescaped occurrence truncates the rest of the modal in the browser.

Two editorial rules go with it, and `tests/test_changelog_render.py` fails on both. **What's new comes before the fixes**, in both languages, and the two languages carry exactly the same entry codes — a release that says different things depending on the interface language is worse than one that says less. And **a bug introduced and fixed inside the release that ships it has no reader**: nobody ran that code, so it does not belong in the notes. It belongs in section 15 above, where the invariant it produced is worth keeping. Iterations on a feature that has not shipped yet follow the same rule — they are folded into the feature's own entry rather than listed as a history of it.

The same reasoning applies one level up, to a whole release. **A version prepared but never published gets no heading of its own**: it is folded into the version that actually ships it, and the `## [x]` line for it disappears. 1.6.6 is the precedent — it stayed on `dev` and 1.7.0 shipped in its place, so 1.7.0 carries its Library Inventory, its modal pass and its fixes, minus the ones that only repaired 1.6.6's own new code. A lead paragraph in **Before you update** says which version the notes are counted from, because that is the only thing a reader needs in order to know whether a section this long concerns them. Anything outside `CHANGELOG.md` that dated a feature by that version number — `README.md` headings, the `(vx.y.z)` tags in `ROADMAP.md`, the Companion's server floor — is renumbered in the same pass: `get_app_version()` reads the first heading of this file, so a stale number elsewhere is a documentation lie the code cannot contradict.

<br><br>

---

## 🇫🇷 Guide de Développement Français

### 1. Architecture Globale & Sécurité
MetaKavita est une application Python asynchrone fonctionnant derrière un serveur **WSGI Gunicorn** couplé à des workers **Eventlet** pour supporter les WebSockets en temps réel.

*   **Sécurité :** authentification globale via `@app.before_request` (`auth_manager.setup_gate` puis `login_gate` / `is_authenticated`) et le handler Socket.IO `connect` (`return False` si non authentifié — forme documentée Flask-SocketIO ; garde `_reject_unauthenticated` par événement en défense en profondeur). **Fail-closed** — y compris base illisible (refuser, jamais laisser l’UI ouverte). Comptes dans `auth_manager.py` + table `users` (méthode Werkzeug épinglée `pbkdf2:sha256`) ; `/setup` au premier démarrage ; amorçage optionnel `ADMIN_PASSWORD_HASH` + `ADMIN_USERNAME` via `debug/hash_password.py` (forme de hachage validée ; ignoré dès qu’un compte existe). Verrouillage par IP (5/15 min) + plafond global (20/15 min) contre la rotation de `X-Forwarded-For` (en mémoire — sain sous `gunicorn -w 1`) ; égalisation de timing par un seul KDF factice mémoïsé. L'ancien `ADMIN_PASSWORD` dans `config.json` sert de preuve de propriété à usage unique sur `/setup`, puis est purgé — jamais repris comme nouveau mot de passe. Cookies de session `HttpOnly` + `SameSite=Lax` (`SESSION_COOKIE_SECURE=1` optionnel derrière HTTPS), durée 7 jours. CSRF (`csrf_utils.py`) sur les POST mutatifs ; le frontend injecte `X-CSRF-Token`. `SECRET_KEY` générée au boot — pas de fallback public hardcodé.
*   **Changement de mot de passe (modal Config) :** `POST /account/password` (`routes/auth.py`, `auth_manager.update_password`) revérifie `current_password` par le même chemin que `/login` (`verify_credentials()`) avant de hacher le nouveau — un onglet resté ouvert n'est pas dispensé de prouver le mot de passe actuel. Un mauvais `current_password` compte comme un échec de login (`register_failed_attempt`) et subit le même verrouillage par IP, pour que la route ne devienne pas un oracle de brute-force contournant le throttling de `/login`. Trois champs `<input>` sans attribut `name` dans `_config_modal.html` gardent cet appel hors du gros POST `FormData` de `saveConfig()` vers `/save-config`.
*   **Protection SSRF :** Allowlist partagée (`url_allowlist.py`) pour upload de couvertures et `/api/proxy-image` (http(s), pas d'IPs privées, jusqu'à 3 redirects re-validés, MIME image). Les `proxy_domains` des scrapers (y compris communautaires) alimentent la liste. `/api/proxy-image` streame avec plafond dur **5 Mo** (`413`).
*   **Logs sans fuite de clés :** utiliser `secure_logging.safe_exc_str()` / `redact_secrets()` pour les exceptions susceptibles de contenir des URLs authentifiées (ne jamais logger `str(e)` brut après ces appels).
*   **Webhooks :** jeton cryptographique `WEBHOOK_TOKEN` ; préférer `X-Webhook-Token` ; `?token=` fonctionne encore (legacy / déprécié, BF63) — les query strings fuient dans les logs proxy / Referer. L’UI Config affiche `/webhook` de base + jeton à part.
*   **Liveness `/healthz` :** `GET /healthz` → `{status, version}` uniquement. Whitelisté dans les gates setup/login (`misc.healthz`) ; ne touche **ni** config, ni base, ni Kavita. Le `HEALTHCHECK` Dockerfile exige HTTP **200** strict sur cette route (plus de sonde laxiste sur `/login`).
*   **Docker non-root (C54) :** utilisateur image `metakavita` (défaut 1000:1000) ; l’entrypoint applique `PUID`/`PGID` puis `gosu`. `save_config()` écrit `config.json` en **0600**.
*   **Migrations SQLite Sécurisées :** Le `db_manager.py` met à jour les colonnes / tables (`_ensure_schema`, `_ensure_pending_reviews_table`) en interceptant silencieusement les erreurs `sqlite3.OperationalError` pour éviter les crashs de conteneur 500. Toutes les connexions passent par `_connect()` en **WAL** avec un **busy_timeout de 30 s**, pour réduire les `database is locked` sous charge worker + REST + Socket.IO.
*   **Upload Kavita en Base64 Pur :** Le moteur C# de Kavita refuse les uploads d'images commençant par le schéma `Data URI`. L'envoi doit impérativement se faire en chaîne de caractères Base64 pure pour être écrit de manière permanente sur le disque dur.

---

### 2. Moteur de Throttling & Régulation Dynamique
Les pauses fixes ont été remplacées par un **Régulateur Dynamique par Horodatage (`LAST_REQUEST_TIMES`, dans `services/provider_throttle.py` ; réexporté par `metadata_fetcher` pour les appelants historiques)**. Les API inactives répondent à 0.0s de délai, exécutant une fusion de 3 sources en ~1,6s. Lors d'un batch, le système régule parfaitement chaque source à sa vitesse maximale théorique (`rate_limit`).
**Tous** les chemins qui interrogent un fournisseur y passent — enrichissement, diagnostic scrapers, comptage catalogue de l'inventaire et **recherche de couvertures** (`services/cover_search.py::run_cover_job`) : le quota d'un fournisseur appartient à l'instance, pas à la fonctionnalité. La recherche de couvertures lance à elle seule une requête parallèle par fournisseur, et ouvrir le sélecteur en plein batch doublait le trafic envoyé à chaque API.
⚠️ **v1.7.0 : la cadence s'applique par requête HTTP, pas par `fetch()`.** Appeler `throttle_provider` une fois en tête d'un `fetch()` qui émet ensuite 6 à 25 requêtes n'est pas une régulation : c'est une rafale derrière une première requête polie, et c'est ce qui a fait bannir l'IP du développeur par Bédéthèque. Les scrapers doivent utiliser `BaseScraper._http_get` / `_http_post`, qui appliquent la cadence et un timeout de 20 s à chaque requête. `tests/test_scrapers_are_throttled.py` le vérifie. Voir la section 15.B.

---

### 3. Architecture Reverse Proxy, Sous-dossiers & CORS
Le système gère les sous-chemins (ex: `https://domaine.com/metakavita`) via `ProxyFix` pour les headers `X-Forwarded-Prefix`, `X-Forwarded-For`, … **`TRUSTED_PROXY_COUNT`** (défaut `1`) pilote à la fois le hop count de ProxyFix et l’IP client utilisée pour le verrouillage — mettre **`0`** si l’instance est exposée directement (sinon un attaquant peut faire tourner `X-Forwarded-For` et contourner le verrouillage par IP ; le plafond global 20/15 min s’applique toujours). Sous-chemin : env `ROOT_PATH` **ou** `config.json` (wizard C64) ; **l’env prime**. Middleware `ScriptNameStripper` au boot (redémarrage après changement). Côté frontend, `window.ROOT_PATH` préfixe toutes les routes.

**Whitelist CORS (env Docker `CORS_ALLOWED_ORIGINS`)** — pour les self-hosts HTTPS (ex: `https://….local.ltd`) où le Same-Origin seul bloque Socket.IO / AJAX cross-origin. Origins **explicites** séparées par des virgules ; vide = Same-Origin. Appliquée à Flask HTTP (`after_request` + preflight OPTIONS, avec credentials) et à `socketio.init_app(cors_allowed_origins=…)`. `*` est rejeté. Cela ne remplace **pas** la config reverse-proxy d'upgrade WebSocket (`Upgrade` / `Connection`) — voir `cors_config.py` et `app.py`.

**`KAVITA_URL` vs `KAVITA_EXTERNAL_URL`** — les appels API utilisent toujours `KAVITA_URL` (hostname Docker interne OK, ex: `http://kavita:5000`). Les liens série du navigateur passent par `get_kavita_ui_url()` (`config_manager.py`), qui préfère `KAVITA_EXTERNAL_URL` (URL publique / reverse proxy) et se rabat sur `KAVITA_URL` si elle est vide. Le bouton **Kavita+** (topbar / À propos) utilise `get_kavita_plus_url()` → `{ui}/settings#admin-kavitaplus` (repli wiki si aucune URL UI).

**Précédence de config** — `config.json` > variable d'environnement > défaut. `load_config()` fusionne l'environnement *avant* de générer `SECRET_KEY` / `WEBHOOK_TOKEN` et d'écrire le fichier sur une install neuve (BF51) ; sinon chaque clé serait figée au défaut et le semis env ne s'appliquerait jamais. `ADMIN_PASSWORD` n'est **pas** semé depuis l'environnement (réarmerait la preuve de propriété à usage unique sur `/setup`). Un `KAVITA_URL` / `KAVITA_EXTERNAL_URL` / `KAVITA_API_KEY` vide dans le fichier accepte encore le seed env (BF52). Si `TARGET_LANG` est absent du fichier et de l'env, il est dérivé de `UI_LANG` effectif (`en`→`EN`, `fr`→`FR` ; BF64) — défauts alignés `UI_LANG=en` / `TARGET_LANG=EN`. Les champs secrets de la modal Config s'affichent toujours vides ; POST vide = conserver le secret (jamais de préremplissage `********`).

**`KAVITA_HTTP_TIMEOUT`** — secondes pour les POST d'**écriture** Kavita (metadata 2-pass, update série 2-pass, upload couverture). Défaut `60`. Env ou `config.json`. Si le passage 1 (écriture) réussit et le passage 2 (re-lock) échoue/timeout, `update_series_metadata` / `update_series_general` renvoient `(ok, msg, sealed=False)` soft-success ; l’enrichissement mappe ça en statut **`NEEDS_RELOCK`** (pas un simple `COMPLETED`) et planifie `seal_series_locks()` (~2 s). Retry manuel : `POST /api/series/<id>/seal-locks` et bulk `POST /api/series/seal-locks-pending` (`routes/series.py`).

**`MAX_TAGS`** — nombre max de tags poussés vers Kavita. Défaut `15` (borné 1–100). Env ou `config.json` uniquement — **pas** dans la modal Config. Utiliser `get_max_tags(config=None)` depuis `config_manager` dans les scrapers (`tags[:get_max_tags()]`). Dans `services/kavita_payload.py` (**BF66**), les titres sont **dédupliqués** (strip + casefold, ordre conservé) **avant** le slice max — Kavita UNIQUE sur `Tag.NormalizedTitle` refuse les inserts `id:0` en double avec un 400 générique.

**`MAX_GENRES`** — nombre max de genres poussés vers Kavita. Défaut `5` (borné 1–50). Env ou `config.json` uniquement — **pas** dans la modal Config. Même schéma que les tags : les scrapers peuvent tronquer tôt ; le chemin payload déduplique puis applique `get_max_genres(config)` (**BF66**).

---

### 4. Frontend, QoS Batch & WebSockets

#### A. Streaming de couvertures
Les recherches manuelles de couvertures streamment les images via `socketio.start_background_task` et `socketio.sleep(0)`.
Les frames sont filtrées côté client par `series_id`. Un jeton chronologique `stream_id` (rejeter les frames d’une recherche précédente sur la même série) est le durcissement historiquement documenté pour BF11 — **pas encore implémenté** dans `covers.js` / `sockets/handlers.py` ; ne pas l’assumer en debug de courses.

#### B. Verrouillage Anti-Écrasement
Appliquer une couverture manuellement via l'interface envoie un second signal AJAX qui décoche la case "Couverture" dans les options de la série. Cela protège la série en empêchant l'option globale `AUTO_COVER` de l'écraser lors des batchs ultérieurs.

#### C. Persistance de sélection & décochage auto (v1.6.1)
* `static/js/batch.js` — `saveBatchSelection()` / `restoreBatchSelection()` stockent les IDs cochés dans `localStorage` sous `mk_batch_selection:{libraryId|all}`. Les filtres masquent sans décocher.
* `static/js/websocket.js` — `socket.on('series_status', …)` appelle `uncheckSeriesForBatchResume()` pour `COMPLETED`/`NEEDS_RELOCK`, ce qui décoche et met à jour le stockage.
* **Stop vs envoi par paquets** — Stop coupe la boucle UI ×50 `/batch-sync` (`AbortController`) et le serveur rejette les chunks tardifs jusqu’au premier paquet du prochain batch (`resume_enqueue=true`).
* **`drain_sync_queue()` ne retire que les items `is_batch=True` (hotfix v1.6.1)** — elle vidait auparavant `sync_queue` sans condition sur Stop, ce qui jetait silencieusement tout item webhook/auto-sync (`is_batch=False`) présent en file à cet instant précis, sans retry ni erreur visible nulle part. Elle parcourt désormais toute la file, ne fait `task_done()` que sur les items de batch comptés comme drainés, et remet le reste en file via `put()` (compensé par un `task_done()` correspondant pour ne pas doubler `unfinished_tasks` sur des items jamais réellement terminés).
* **Un second batch concurrent est refusé, pas silencieusement corrupteur (hotfix v1.6.1)** — `_batch_total`/`_batch_done` sont des globaux de process pour une seule barre de progression ; un second paquet `/batch-sync` avec `resume_enqueue=true` alors que `is_batch_active()` est encore vrai (un batch déjà en vol) appelait `register_batch_enqueue(new_batch=True)`, qui remettait ces compteurs à zéro en plein milieu et faussait la barre et le `real_sends` du premier batch. `routes/sync.py::batch_sync` vérifie désormais `is_batch_active()` avant d'accepter un nouveau batch et renvoie `409 {"already_running": true}` ; `batch.js::launchBatch()` traite ça comme un Stop pour sa propre boucle d'envoi, mais appelle aussi `hideBatchProgress()` puisque le batch de cet onglet n'a jamais réellement démarré.

#### D. Masque éphémère de champs ciblés batch (v1.6.1)
* Cases sidebar `.batch-field-cb` → `getBatchTargetedFieldsMask()` (null si les 12 sont cochées).
* `POST /batch-sync` peut inclure `targeted_fields` ; le worker dépile un 3- ou 4-tuple et passe `targeted_fields_override` à `enrich_series()`.
* `resolve_active_fields()` dans `services/enrichment_engine.py` — l’override prime sur le cache série pour ce run uniquement (filtre d’écriture ; les providers sont toujours scrapés en entier).

#### E. Stats lifetime & KPI live (v1.6.1 / C7)
* Clés SQLite `lifetime_stats` : `series_enriched`, `matches_won`, `series_missed` via `record_enrichment_telemetry` / `record_enrichment_miss`.
* Après enregistrement, `_broadcast_enrichment_stats` émet Socket.IO `enrichment_stats` (lifetime absolu + deltas).
* KPI topbar + compteur session (`sessionStorage` `mk_session_processed`) dans `websocket.js`.
* `/stats` ludique (`ENABLE_PLAYFUL_STATS`, défaut ON) : `services/stats_service.py` + Chart.js + hauts-faits Manual Review (`services/mr_achievements.py`).

#### F. Barre de progression batch (v1.6.1, hotfix compteurs isolés)
* Les items de file sont désormais des dicts construits par `services/background_tasks.py::make_sync_item(series_id, series_name, force_update, fields_override=None, is_batch=False)` — plus des tuples. `sync_queue` reste partagée avec le webhook et l'auto-sync ; `is_batch` permet au worker de distinguer un job de batch des autres qui partagent la même file.
* Compteurs dédiés `_batch_total` / `_batch_done` / `_batch_real_sends` (globaux de module sous `_batch_progress_lock`, `services/background_tasks.py`) remplacent l'ancien calcul basé sur `sync_queue.qsize()`, qui faisait des bonds erratiques dès qu'un item webhook ou auto-sync s'ajoutait à la file pendant un batch et faussait sa taille. `register_batch_enqueue(count, new_batch=True)` sur le **premier** paquet `/batch-sync` (`resume_enqueue=true`) remet les trois à zéro ; les paquets suivants du même batch n'additionnent que `_batch_total`. `reset_batch_progress()` les vide au Stop/drain.
* `_REAL_SEND_MESSAGES = {"Succès", "NEEDS_RELOCK"}` — seuls ces messages de retour d'`enrich_series()` comptent comme une vraie écriture Kavita ; skips (« Déjà à jour. »), ratés et `PENDING_REVIEW` n'incrémentent pas `_batch_real_sends`. L'émission finale de `batch_progress` porte `real_sends`, pour que le client distingue « batch terminé » de « batch terminé et ayant réellement écrit quelque chose » (voir §I ci-dessous).
* `broadcast_batch_progress(remaining, active=…, stopped=…, real_sends=…)` à chaque démarrage worker et à la fin ; `static/js/batch.js` calcule toujours `done = total - remaining - (active ? 1 : 0)` côté client depuis le même format de payload.
* Cache d'inventaire `/batch-sync` (`routes/sync.py::_get_batch_inventory`, TTL 900s, clé `(kavita.url, kavita.api_key, library_id)`) — l'UI découpe un batch en paquets d'environ 50 séries via `/batch-sync` ; sans ce cache, chaque paquet refaisait un `get_all_series()` complet (et purgeait le cache de types de bibliothèque de `KavitaAPI`) vers Kavita. Seul le paquet portant `resume_enqueue=true` force un nouvel appel ; les paquets suivants du même batch réutilisent cet instantané. Les tests vident ce cache entre les runs via la fixture autouse `_clean_batch_inventory_cache` de `conftest.py` — fais de même pour tout nouveau cache de module que tu ajoutes.

#### G. Baromètre de fiabilité (v1.6.1)
* Clés config `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD` (clamp `[0.30, 1.00]`).
* Seuil runtime : `scrapers/utils.py::get_match_accept_threshold()` (custom off → toujours `0.60`). Scrapers officiels + fallbacks `_safe_match_score` / `attach_match_score` via le getter — ne pas hardcoder `MATCH_ACCEPT_THRESHOLD` dans un nouveau scraper.

#### H. Mode Review Manuelle (C29)
Park-and-pick au lieu d’écrire automatiquement dans Kavita. Le worker scrape avec `return_candidates=True`, puis `create_review_from_candidates` → `park_pending_review` (insert atomique + statut `PENDING_REVIEW`). L’UI consomme la file via REST + Socket.IO (gradient de score, touches 1–3, bande faible sous seuil). Le confirm peut inclure une **phase couverture** avant `apply_manual_review` (upload explicite même si `AUTO_COVER` est off) ; soft-success re-lock → `NEEDS_RELOCK` (comme en auto).

Quand Manual Review est **off**, la même case « Éditer avant confirmation » peut activer `CONFIRM_BEFORE_WRITE` : le scrape auto gare un preview (`awaiting_confirm`) et ouvre le panneau d’édition ; Kavita n’est écrit qu’au confirm.

| Pièce | Rôle |
| :--- | :--- |
| `services/manual_review.py` | Helpers de park, traduction des résumés avant pick, émetteurs skip/confirm/purge |
| `services/enrichment_engine.py` | Branche manuelle dans `enrich_series`, `preview_manual_review` / `apply_manual_review` / `research_manual_review` (apply partage `_processing_lock`) ; `seal_series_locks` pour `NEEDS_RELOCK` |
| `routes/manual_review.py` | `GET/POST /api/manual-reviews…` (liste, choice, confirm, research, skip, purge) |
| `db_manager.py` | Table `pending_reviews` — **UNIQUE(`series_id`)**, `park_pending_review` / `close_pending_review` en une txn |
| `static/js/manual_review.js` + `_manual_review_modal.html` | Modale pick / edit / **cover** / recap, fusion, dock clavier, sync file ; C87 cases d'envoi sur la fiche |

**Règles d’intégrité (ne pas régresser) :**
* Une seule ligne par `series_id` — un re-park remplace, n’empile jamais.
* Le batch global (`routes/sync.py` sans sélection) exclut `PENDING_REVIEW` ; l’auto-sync le faisait déjà.
* Le court-circuit « déjà à jour » ne doit pas clobber `PENDING_REVIEW` ; sur `NEEDS_RELOCK` tenter seal seul puis COMPLETED ; le chemin COMPLETED purge les orphelins.
* Écriture OK + re-lock échoué → `NEEDS_RELOCK` (orange), pas un simple `COMPLETED` ; seal via retry différé ou `POST /api/series/<id>/seal-locks` (+ bulk pending).
* Désactiver `MANUAL_REVIEW_MODE` purge la file (`routes/config.py`).
* Ignore et `clean_orphaned_cache` effacent les reviews de la série.
* Frontend : sérialiser `loadQueue`, ancrer sur `currentReviewId`, gardes in-flight ; gérer `manual_review_confirmed` / `_skipped` / `_refreshed` / compteur→0.
* **Vider la file pendant qu'un batch tourne encore affiche le masque d'attente, pas le récap (hotfix v1.6.1)** — `showRecapIfEmpty()` vérifie le global `batchProgressTotal` (`batch.js`) avant de basculer sur `recap` ; si un batch est encore actif, elle bascule sur la phase `waiting` déjà existante, et le chemin déjà câblé `mrOnBatchProgress()` → `settleWaitingAfterWork()` prend le relais une fois le batch réellement terminé (ou affiche d'abord la prochaine review garée). Sans ça, une file vide en plein batch affichait le récap quelques secondes avant que la série suivante scrapée ne ramène brutalement la modale sur `pick`. Garde `phase !== "waiting"` pour ne pas se réappliquer sur l'appel qui sort déjà de `waiting` (`batchProgressTotal` ne retombe à 0 qu'~1,5 s après la fin réelle — voir `applyBatchProgressPayload()`).

**C87 `send_fields`** — `/confirm` accepte `send_fields`. Clé absente = écriture historique (masque série seul). Une liste s'intersecte avec l'override série, jamais le masque batch sidebar. Tests : `tests/test_mr_send_fields.py`.

Flags config (sidebar) : `MANUAL_REVIEW_MODE`, `MANUAL_REVIEW_EDIT`, `MANUAL_REVIEW_SUPER`, `MANUAL_REVIEW_SOUNDS`. Tests : `tests/test_manual_review.py`, `tests/test_needs_relock.py`.

#### I. Pubs supporter (C40 partiel)
* `static/js/license_nag.js` — overlays Buy Me a Coffee rares après moments chauds (fin de batch / récap MR riche). Caps : honeymoon 7 j, max 1–2/j, silence honor 30 j. Les échecs doivent être no-op (jamais bloquer batch/MR). Classe `.license` réservée pour un futur silence — pas de paywall / clé licence.
* **Garde-fou « vrai envoi » sur `onBatchComplete()` (hotfix v1.6.1)** — le nagware ne se déclenche plus juste parce que `remaining` est tombé à 0. `services/background_tasks.py` compte `_batch_real_sends` (voir §F) et le transmet en `real_sends` dans le payload final `batch_progress` ; `batch.js` le relaie, et `license_nag.js::onBatchComplete()` sort tôt si `real_sends <= 0`. Sans ça, un batch entièrement composé de séries déjà à jour (skip silencieux, aucune écriture Kavita) déclenchait quand même l'invite au don.

#### J. Dénylist de bibliothèques — auto-sync polling uniquement (hotfix v1.6.1)
`DISABLED_LIBRARIES` (cases à cocher Config → Planification) n'a **qu'un seul** point d'appel : `services/background_tasks.py::select_auto_sync_candidates()`, qui filtre la liste de candidats du poller auto-sync périodique via `config_manager.is_library_enabled()`. Ce helper est le **seul** filtre dénylist restant — il n'existe plus de `filter_enabled_libraries()` au niveau liste. `KavitaAPI.get_all_series()` renvoie toujours l'inventaire complet et n'applique aucune dénylist — le dashboard, le batch manuel (`/batch-sync`), le webhook et l'export CSV voient toujours toutes les bibliothèques, quel que soit ce réglage. Ne réintroduis jamais de filtre ailleurs ; la boucle de polling purgeait auparavant le cache de chaque série d'une bibliothèque désactivée comme si elle était orpheline, exactement la classe de bug que ce cadrage corrige.

L'ancien `config_manager.heal_total_library_denylist()` (réactivation automatique de toutes les bibliothèques si `DISABLED_LIBRARIES` en couvrait 100 %) était du **code mort volontaire** après v1.6.1 — débranché à dessein de `routes/pages.py` — et a depuis été **supprimé** (nettoyage orphelins). Il tournait à *chaque* chargement du dashboard et ne pouvait pas distinguer un wipe accidentel du premier save d'un choix délibéré de tout décocher : décocher la dernière case dans la modal Config recochait donc silencieusement tout au rechargement suivant. Le correctif côté écriture (ne toucher `DISABLED_LIBRARIES` que quand les marqueurs `SYNC_LIBRARIES_PRESENT` / `KNOWN_LIBRARY` confirment que la liste complète des bibliothèques a bien été rendue — voir `routes/config.py`) prévient déjà le wipe accidentel que ce heal compensait, donc un « tout désactiver » délibéré tient maintenant à travers les rechargements (test de non-régression `test_dashboard_renders.py::test_deliberately_disabling_every_library_survives_a_reload`). Les cases à cocher appellent `saveConfig()` en `onchange` (simple sauvegarde AJAX), plus l'ancien `saveConfigAndReloadLibraries()` supprimé — un rechargement complet de page après chaque clic était l'autre moitié du symptôme « tout se recoche », puisque c'est lui qui redéclenchait le heal.

#### K. Badges de statut live typés via `series_status` (hotfix v1.6.1)
`services/kavita_payload.py::_emit_series_status(series_id, status, series_name)` émet un événement Socket.IO `series_status` ; le handler de `static/js/websocket.js` appelle `applySeriesStatusBadge(item, status)` (`batch.js`) pour redessiner le badge d'une ligne de série — la même fonction utilisée par `manual_review.js::markSeriesStatus`. `enrich_series()` (`services/enrichment_engine.py`) l'appelle désormais pour **chaque** issue, pas seulement le chemin d'écriture : le court-circuit précoce « déjà à jour » (`COMPLETED`), les deux retours `NOT_FOUND` (recherche de candidats en review manuelle et fetch en mode auto), les deux retours `PENDING_REVIEW` (park manuel et auto-park `CONFIRM_BEFORE_WRITE`), et la branche où le retry de scellement différé échoue encore (`NEEDS_RELOCK`). `apply_kavita_payload()` couvrait déjà les deux issues d'écriture (`COMPLETED` / `NEEDS_RELOCK`).

Avant ce correctif, `websocket.js` devinait les badges `NOT_FOUND`/`PENDING_REVIEW`/`COMPLETED`-skip en cherchant des mots-clés **traduits** dans le texte brut de `log_update` (« réussi », « déjà à jour », « introuvable »...). Ce bloc a disparu — le handler `log_update` ne fait plus que retirer le highlight `.is-processing` sur un émoji de fin, rien de lié au badge. Ne réintroduis jamais de matching sur du texte de log pour ce que le badge doit refléter ; ajoute plutôt une nouvelle valeur de `status` et un appel `_emit_series_status()` à la source. `uncheckSeriesForBatchResume()` (reprise QoS batch) est désormais elle aussi pilotée par le handler `series_status` (`status === 'COMPLETED' || status === 'NEEDS_RELOCK'`), pas par du texte de log.

#### L. Menus de la barre du haut, sprite d'icônes & encart Companion (C81)

**Deux menus, une seule fonction de fermeture.** `toggleTopbarMenu(event, dropdownId)` / `closeTopbarMenus()` dans `main.js` remplacent les `toggleHelpMenu` / `closeHelpMenu` mono-usage. Chaque menu est un conteneur `.topbar-menu` portant un `.topbar-menu-btn` et une `.help-dropdown` ; les deux panneaux sont ancrés `right: 0` dans le même coin, donc **ouvrir l'un doit fermer les autres** — `toggleTopbarMenu` appelle `closeTopbarMenus()` avant de dévoiler le sien. Le seul état conservé est `aria-expanded` sur le bouton : le CSS le lit pour surligner le bouton et faire pivoter `.mk-caret`, il n'y a donc aucune classe `is-open` à maintenir en parallèle. Le clic extérieur teste `event.target.closest('.topbar-menu')` ; renommer ce conteneur casse la fermeture sans rien casser de visible, d'où l'assertion de `tests/test_ui_topbar_companion.py` qui confronte le sélecteur au CSS.

**Ce qui va dans quel menu.** **Scrapers** réunit ce qui agit (scrapers installés, magasin, cascade des fournisseurs) puis le dépôt et le guide d'écriture ; **Aide** réunit ce qui se lit (À propos, nouveautés, encart Companion, assistant de configuration, documentation, diagnostic). Remettre une page de scrapers dans le menu Aide est précisément la régression que la séparation empêche — un test vérifie qu'aucune route `scrapers_manage` n'est joignable depuis `#helpDropdown`.

**Le sprite doit être analysé avant le balisage qui s'en sert.** Un `<use href="#mk-ico-…">` qui vise un symbole déclaré **plus bas** ne se résout qu'à la fin de l'analyse : `_icons_sprite.html` est donc inclus en tête de `<body>`, avant la barre du haut — il siégeait jusqu'ici à côté des modales, ce qui était sans conséquence tant que chaque icône vivait dans un élément masqué. Deux règles pour les nouvelles icônes : les dessiner au trait sur `currentColor` (un symbole cloné par `<use>` échappe aux règles CSS de la page, donc teinter avec des attributs `fill="currentColor" fill-opacity=…`), et se souvenir qu'une faute de frappe dans un `href` ne lève rien et ne dessine rien — `test_every_icon_used_is_declared` parcourt tous les `<use>` de `templates/` et les confronte aux symboles déclarés.

**L'encart Companion retient sa fermeture dans le navigateur, volontairement.** `#companionCard` est rendu avec `hidden` puis dévoilé par un script en ligne placé **juste après lui**, et non au `DOMContentLoaded` : rendu visible puis masqué, celui qui l'a fermé le verrait clignoter à chaque chargement ; dévoilé plus tard, tous les autres verraient la page sauter. La clé est `localStorage.mk_companion_card_dismissed` (`COMPANION_CARD_KEY` dans `main.js` — le script en ligne répète le littéral, les deux sont donc vérifiés ensemble). Ce n'est pas une clé de configuration : le serveur ne peut pas savoir si l'extension est installée, et rien ne justifie qu'un encart promotionnel survive à un changement de navigateur. `showCompanionCard()` (menu Aide) retire la clé et redévoile, parce qu'une croix sans retour emporterait avec elle le seul endroit de l'interface qui désigne les deux archives à installer. Tests : `tests/test_ui_topbar_companion.py`.

#### M. La barre d'actions de masse : la hiérarchie par le style, le libellé dans un slot (C83)

**`flex: 1` ne fait pas une hiérarchie.** Les six contrôles de `.batch-actions` se partageaient la largeur à parts égales, en majuscules interlettrées : la moitié des libellés passait à la ligne, et *Lancer la sélection* — le seul qui écrit dans Kavita — ressemblait à l'amnistie d'erreurs posée à côté. Le poids passe désormais par le style : `.ba-btn--quiet` (contour) pour l'entretien, un seul `.ba-btn--primary` (aplat) pour l'action, `.ba-btn--stop` discret jusqu'à `#batchActions[data-state="running"]`. Chaque bouton est en `white-space: nowrap` et fait la largeur de son libellé ; rien n'est mis en majuscules dans la barre, une capitale coûtant environ 15 % de largeur pour aucune information.

⚠️ **Le libellé vit dans `.ba-label`, et le JS doit y écrire.** `batch.js` remplace ces libellés en permanence — *Envoi…*, *Ajouter à la file*, *⏳...*, *✅ OK* — et il assignait `btn.innerText`, ce qui effacerait maintenant aussi le `<svg>` posé à côté du texte : le pictogramme disparaît au premier changement d'état et ne revient qu'au rechargement. Passer par `setBatchBtnLabel()` / `batchBtnLabel()` (et `setBatchBtnBusy()`, qui masque le pictogramme le temps d'un message passager portant son propre émoji). `tests/test_ui_batch_actions.py` lit le corps des cinq fonctions concernées et échoue sur un `btn.innerText` direct.

**L'état de la barre ne doit pas dépendre d'un message passager.** `mainBatchBtnBusy` gèle le *libellé* pendant l'affichage d'*Envoi…* ; `data-state` et le `data-mode` du bouton principal sont posés **avant** ce retour anticipé dans `syncMainBatchBtnLabel()`, sans quoi le bouton d'arrêt resterait pâle pendant le lot même qu'il est là pour arrêter.

⚠️ **Un `display` porté par une classe l'emporte sur le `[hidden]` du navigateur.** `.batch-queue-badge` déclarait `display: inline-block` : `badge.hidden = true` ne faisait donc rien, et une file vide affichait quand même sa pastille (BF170). Tout élément qu'un script masque par `hidden` a besoin de sa propre règle `[hidden] { display: none; }` dès qu'une classe lui donne un `display`.

---

### 5. Sideloading de Scrapers & Auto-Découverte

MetaKavita utilise un Registre **data-only** (C61 + C62 en v1.6.4). Au démarrage, `sync_core_scrapers()` aligne `/app/data/scrapers/` : (1) catalogue GitHub `is_core` en priorité (hotfixes sans nouvelle image), (2) fallback package image (`is_core = True`, AST) si le réseau échoue ou pour combler les absents. Selon `AUTO_UPDATE_CORE_SCRAPERS` (si off → bannière + `POST /api/scrapers/core-updates/apply`), puis `load_all()` charge **uniquement** ce dossier data. Fichiers core → `scrapers.<stem>` ; community → `custom_scrapers.<stem>`.

L'arbitrage entre les deux sources se fait sur **`BaseScraper.version`** (`major.minor.patch`, lu par AST et publié dans le catalogue) : une copie n'est remplacée que par une version strictement plus récente. Une mise à jour d'image livre donc ses scrapers core corrigés même si le miroir du catalogue est en retard, et un catalogue en avance sur l'image continue de l'emporter ; tout downgrade est refusé et journalisé en WARNING. **Un scraper core qui gagne une capacité doit monter sa `version`** — à version égale, seul le sha256 diffère et le contenu de l'image reste la référence (BF143).

Si le fichier déposé par un utilisateur déclare `needs_api_key = True`, MetaKavita génère automatiquement le champ dans l’UI et gère sa sauvegarde.

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
partagé. Préférer `scrapers/utils.py::get_match_accept_threshold()` (baromètre v1.6.1 —
§4.G) ; la constante `MATCH_ACCEPT_THRESHOLD` (`0.60`) reste le défaut quand le mode custom
est off. Cette valeur était autrefois un literal dupliqué dans chaque fichier de scraper
(`0.50` pour la plupart, `0.60` pour Hardcover/OpenLibrary, et même `0.45` pour
Manga-News/Shikimori) — `0.50` (et a fortiori `0.45`) a été testé en usage réel et générait
trop de faux positifs (homonymes/spin-offs acceptés à tort), donc `0.60` est la seule valeur
validée par défaut, centralisée pour que tous les scrapers restent synchronisés.

**Les scrapers officiels basés sur une recherche appellent `score_candidate()`** (y compris
les migrations MangaDex / MangaUpdates / Manga-News / Shikimori ci-dessous). Les providers
plus récents (MAL, BDTheque, Wikidata, …) doivent utiliser la même matrice +
`get_match_accept_threshold()`. Note historique — `mangadex.py`, `mangaupdates.py`,
`manganews.py` et `shikimori.py` implémentaient chacun leur propre heuristique titre-seul,
sans comparaison d'auteur — la protection anti-homonyme (catégorie A) ne s'appliquait donc
jamais à eux. Chacun a été migré pour construire un candidat *complet* (avec `staff`) avant
scoring :
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
   décroissant avant de désigner un vainqueur. **Départage (BF68/BF77/BF81) :** scores égaux →
   préférence non-adulte explicite, puis position d'origine. Adulte explicite = `r18`/`x18`
   (aliases `erotica`/`pornographic`) **ou** tokens `hentai`/`futanari`. BF81 peut poser `x18`
   depuis ces tags avant le tri (scores inchangés). `mature` n'est pas rétrogradé. Auto journalise
   `log_tiebreak_prefer_safe` seulement si le vainqueur trié est non-adulte. Manual Review :
   tri neutre. Confirm-before-write + égalité → `awaiting_pick`. SMART_COMPLETION suit le même
   ordre trié. **Âge + SMART_COMPLETION (BF102) :** combler les trous dès qu’une source a un vrai
   signal d’âge. En Auto, comble un `age_rating` vide depuis un secondaire seulement si
   `safe` / `suggestive` / `mature` ; ages NSFW (`r18` / `x18` / aliases) jamais comblés depuis
   un secondaire — garde-fou de **justesse** (éviter un faux verrou X18+ / annulation BF68),
   pas un filtre moral. Les scores de match n’utilisent pas l’âge. L’écriture Kavita exige
   toujours le champ ciblé **Âge** (ou `ALL`). MR Sources : `fill_age_rating=True` (tout âge).
   Gardes : `tests/test_fusion_age_no_backfill.py`, `tests/test_smart_completion_manual_review.py`.
   Candidat sans `_match_score` → traité comme juste accepté (`MATCH_ACCEPT_THRESHOLD`).

2. **Exécution en deux vagues.** Le provider #1 tourne toujours seul et en premier, séquentiel ;
   l'ISBN/les auteurs qu'il trouve sont fusionnés dans `existing_metadata` et transmis aux
   providers **restants**, qui tournent ensuite **en parallèle** (`ThreadPoolExecutor`) contre un
   instantané figé de ce contexte enrichi. C'est un compromis délibéré, pas un "tout en parallèle
   dès t=0" naïf : paralléliser dès le départ perdrait le bénéfice existant de la cascade de
   contexte (l'ISBN/les auteurs du provider #1 alimentant la règle d'or ISBN et la pénalité
   anti-homonyme de `score_candidate()` pour les providers suivants), ce qui compte surtout sur
   les séries "froides" (peu ou pas de métadonnées Kavita pré-existantes). Le rate-limiting par
   provider (`throttle_provider()`) est déjà indexé par `scraper.id` avec son propre verrou
   (voir §2 plus haut), donc paralléliser des providers *différents* ne viole jamais le
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

### 7. Écosystème des Scrapers Actifs

| Identifiant | Nom Public | Types | Spécificités & Fonctionnalités |
| :--- | :--- | :--- | :--- |
| `ANILIST` | AniList | Manga, Comic, Book | API GraphQL, scoring des candidats contre les spin-offs. |
| `ANN` | Anime News Network | Manga | Encyclopédie XML publique, sans clé ; covers + staff. |
| `BABELIO` | Babelio | Book | Littérature FR (HTML) ; covers + résumés, sans clé. |
| `BEDETHEQUE` | Bédéthèque | Comic | Contournement CSRF `curl_cffi`, match exact de séries franco-belges. |
| `BDTHEQUE` | BDTheque.com | Comic | BD franco-belge (bdtheque.com, **pas** bedetheque). Recherche AJAX + parse fiche ; Magic Input `/series/{id}/{slug}` ; covers via `data-echo`. |
| `COMICVINE` | ComicVine | Comic | API Key. Recherche `filter=name:`, priorisation des éditeurs majeurs. |
| `DECITRE` | Decitre | Book | Librairie FR HTML + JSON-LD ; ISBN + covers. |
| `GOOGLEBOOKS` | Google Books | Book, Comic | API Key. Replis dynamiques par langue (`langRestrict`), ISBN. |
| `HARDCOVER` | Hardcover (Exp) | Book, Comic | API Key. GraphQL Hasura + Moteur Typesense. |
| `KITSU` | Kitsu | Manga | JSON:API, rapide, sans clé requise. |
| `LOCG` | League of Comic Geeks | Comic | Comics via XHR/HTML public (pas de clé partenaire) ; covers. |
| `MANGANEWS` | Manga-News | Manga | Catalogue VF, extrait l'éditeur FR et les visuels HD (webp). |
| `MANGABAKA` | MangaBaka | Manga, Book | Manga + Book ; `schema=full`, filtre `type`, Préférence d'Éditeur. |
| `MANGADEX` | MangaDex | Manga | Filtres adultes (`erotica`), pénalités Oneshot. |
| `MANGAUPDATES`| MangaUpdates | Manga | Scraping par `hit_title`, support de la Préférence d'Éditeur. |
| `METRON` | Metron | Comic | Clé API (`METRON_API_KEY` Bearer ou `user:password`) ; série + crédits/covers issues. |
| `OPENLIBRARY` | Open Library | Book, Comic | Clés Work (`OL...W`) & ISBNs, contournement Disclaimer Google Books. |
| `PLANETEBD` | Planète BD | Comic | BD FR + comics (HTML) ; payload riche + covers. |
| `MAL` | MyAnimeList | Manga, Book | API officielle v2 + `X-MAL-CLIENT-ID` (`MAL_API_KEY` = Client ID ; pas d’OAuth utilisateur). Magic Input `myanimelist.net/manga/{id}`. |
| `SENSCRITIQUE` | SensCritique | Book, Comic | GraphQL Apollo FR ; covers, sans clé. |
| `SHIKIMORI` | Shikimori | Manga | API Multilingue, extraction `/roles` du staff. |
| `WIKIDATA` | Wikidata (**Magasin**, hors core) | Manga, Comic, Book | **Live uniquement** (SPARQL + Entity API) — périmètre restreint ; installer via le Magasin. Magic Input Q-id ; mapping dans le core `wikidata_map`. Idéal en fallback / ISBN / IDs croisés. |

#### Comic Flexible (C35)
⚠️ **Corrigé en v1.7.0 : le type hybride est l'ID 1, pas l'ID 5.** L'énumération Kavita nomme `Comic = 1` (affiché « Comic (Flexible) » dans son interface) et `ComicVine = 5` (affiché « Comic »), et MetaKavita prenait les deux à l'envers — une bibliothèque flexible recevait donc la cascade stricte, et inversement. `kavita_constants.LIBRARY_TYPE_BY_ENUM` est désormais la seule correspondance fiable (`_normalize_library_type` la lit) ; elle reclasse aussi `Image = 3` avec les mangas et `LightNovel = 4` avec les livres, eux aussi inversés jusque-là. L'ID 1 se normalise donc en `ComicFlexible` : l'enrichissement lance d'abord `COMIC_PROVIDER_*`, puis bascule sur les `PROVIDER_*` Manga si aucun hit utile, et la recherche manuelle de couvertures unionne Comic + Manga. L'ID 5 suit la cascade Comic stricte. Tests : `tests/test_comic_flexible.py`, `tests/test_library_type_normalize.py`.

**Hygiène année de run (BF54 / v1.6.2, BF173 / v1.7.1)** — les noms Flexible portent souvent `(YYYY)` / `(YYYY-)` pour distinguer les runs comics. `clean_title` Comic retire ces parenthèses de la **query** (elles restaient et empoisonnaient les filtres `name:` ComicVine). `extract_year_from_title` / `apply_title_year_hint` dans `scrapers/utils.py` recopient l'année dans `existing_metadata` avant la vague Comic ; ComicVine booste un `start_year` exact, puis ±1, puis pénalise une année lointaine (BF173 : ±1 ne doit pas égaler l'exact, sinon un voisin plus fourni gagne). Le fallback Manga **n'est pas** pénalisé en confiance — une lib Flexible peut contenir comics et mangas.

**Fallback Manga Auto vs Manuel (hotfix v1.6.1 + audit B16)** — chemins **volontairement parallèles**, pas un helper unique partagé. Le **Manuel** utilise `_apply_comic_flexible_manga_fallback()` dans `services/enrichment_engine.py`, déclenché par `_candidates_have_a_strong_hit()` (vrai seulement si `above` est non-vide) plutôt que « candidats vides ». La Review Manuelle exécute la cascade Comic avec le seuil forcé à `0.0` (les hits faibles atterrissent dans `below`, pas `above`) ; sans ce garde-fou, un résultat Comic faible mais non-vide bloquait le fallback Manga en Manuel alors qu'Auto basculait. Le helper ne *remplace* les candidats Comic par la vague Manga que si Manga renvoie un payload de candidats non vide — sinon le Manuel conserve les Comic faibles pour choix utilisateur. **Auto** garde un fallback Manga **inline** séparé : il se bascule via `_has_useful_provider_data()` sur un dict de métadonnées (pas above/below), et applique un filtre forced-id (scrapers à ID direct seulement si `is_forced_id` et que la query n'est pas une URL) que le helper Manuel n'a pas. Ne **pas** unifier naïvement — formes de retour et forced-id différents rendent une fusion aveugle risquée.

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

1. **Ne jamais envoyer de payload partiel à `POST /api/Series/update`.** Le `SeriesController`/`UpdateSeriesDto` de Kavita n'a **aucune protection contre les valeurs nulles** sur plusieurs champs — notamment `localizedName`. Si votre logique de mise à jour ne vise à changer que `format` mais omet `localizedName` du corps JSON, le backend C# de Kavita désérialise la clé manquante en `null`, **écrase** la valeur existante en base, et **réinitialise en plus** `nameLocked` / `sortNameLocked` / `localizedNameLocked` à `false` — alors même que ces champs n'étaient pas censés être touchés. Cette régression exacte a silencieusement corrompu les titres alternatifs d'utilisateurs réels et fait planter un client OPDS tiers (l'extension "Kamare" de KOReader), qui supposait que `localizedName` serait toujours une chaîne de caractères et s'est bloqué sur le `null` résultant. **Le motif de correction obligatoire :** toujours faire un `GET /api/Series/{id}` en premier, fusionner le changement voulu dans l'état actuel *complet*, puis seulement ensuite renvoyer l'objet entier en `POST`. Voir `KavitaAPI.update_series_general()` pour l'implémentation de référence de ce motif GET-fusion-POST. Le même piège vaut pour les **sept identifiants de correspondance externe** (`SERIES_EXTERNAL_ID_KEYS` : `aniListId`, `malId`, `hardcoverId`, `metronId`, `comicVineId`, `mangaBakaId`, `cbrId`) : le contrôleur appelle `ExternalMetadataIdHelper.SetExternalMetadataIds(entity, dto)` sans condition, et celui-ci écrit `entity.X = dto.X ?? 0` — une clé absente remet donc l'identifiant à zéro. Tout payload envoyé à `POST /api/Series/update` doit porter les sept clés (utiliser `series_external_ids(current)`), et il en va de même pour `POST /api/Chapter/update` (`services/kavita_chapter_payload.EXTERNAL_ID_KEYS`).
2. **Assainir les champs GET-uniquement / calculés avant chaque `POST`.** Des propriétés comme `created`, `lastModified`, `totalCount`, `maxCount`, `pages` et `wordCount` sont renvoyées par les endpoints `GET` de Kavita mais ne doivent jamais être réinjectées dans un corps `POST` — cela risque de déclencher des exceptions de concurrence d'état côté Entity Framework Core. Cet assainissement est centralisé **une seule fois** dans `KavitaAPI.update_series_metadata()`. Ne réimplémentez pas une version partielle de cette logique dans `app.py` ou dans un scraper — c'est exactement ce type de duplication (ne retirer que `created`/`lastModified` à un endroit en oubliant `maxCount`/`totalCount`) qui a un jour laissé passer un payload `maxCount: -100000` vers Kavita et fait planter une synchronisation.
3. **Respecter le protocole de verrouillage à 2 passages** (`Unlock → Write → Lock`, documenté dans `kavita_api.md` §1.B/1.C) chaque fois que votre code doit écraser un champ que l'utilisateur a pu verrouiller manuellement dans l'interface de Kavita. Un soft-success sur échec de re-lock doit remonter en `NEEDS_RELOCK` + `seal_series_locks`, pas en `COMPLETED` silencieux.
4. **Atomicité soft des champs généraux (BF67).** `apply_kavita_payload()` n'appelle `update_series_general` (nom localisé / format) **que si** `update_series_metadata` a réussi. Un échec metadata ne doit plus écrire les champs généraux (mode de panne #24 : rejet UNIQUE des tags + `localizedName` quand même appliqué).
5. **Un `200` de Kavita ne veut pas dire que Kavita a écrit quelque chose.** System.Text.Json ignore silencieusement les clés que le DTO ne déclare pas : un champ inventé coûte un aller-retour, n'écrit rien, et ressemble à un succès dans les journaux. Avant d'ajouter une clé à un payload, vérifiez qu'elle existe sur le DTO visé dans `Kavita.Models/DTOs/` — plusieurs n'y étaient pas : `format` / `formatLocked` n'ont jamais figuré sur `UpdateSeriesDto` (le sens de lecture est une préférence par utilisateur, `AppUserPreferences.ReadingDirection`, pas une propriété de série), `dontMatch` ne s'écrit que par `POST /api/Series/dont-match`, `coverImageLocked` n'est pas sur `UpdateChapterDto`, et `libraryId` n'est pas sur `SeriesFilterV2Dto` — cette dernière faisait rendre tout le catalogue visible à `POST /api/Series/all-v2`, une fois par bibliothèque.
6. **Ne sceller que les verrous que la passe a réellement posés.** `SeriesService` assigne tous les booléens `...Locked` depuis le DTO sans condition : un verrou envoyé à `true` est fermé, y compris sur un champ que l'utilisateur avait laissé ouvert exprès pour que le scan de fichiers ou Kavita+ le remplisse. `seal_series_locks(series_id, lock_keys=[...])` reçoit donc la liste des verrous fermés par le payload d'origine ; sans elle, le repli ne scelle que les verrous dont le champ porte réellement du contenu, et n'en rouvre jamais aucun. À l'inverse, `ChapterController` ne consulte **aucun** verrou : sur le chemin chapitre, ce que MetaKavita envoie est écrit, donc la politique « on ne comble que les vides » doit être appliquée côté client (voir `services/kavita_chapter_payload.credits_to_write`).

#### C. Tracer un Nouveau Réglage sur *Toute* la Chaîne, Pas Seulement un Fichier
L'interrupteur de Préférence d'Éditeur par série (`VF/VA` vs `VO`, v1.5.7) a été livré avec un code entièrement correct dans le template HTML, la construction du payload JS, la logique d'extraction des deux scrapers, *et* le schéma SQLite — et pourtant il n'avait strictement aucun effet en pratique, car une seule route Flask (`/save-override`) lisait la valeur soumise dans une variable locale puis oubliait tout simplement de la transmettre à l'appel de persistance (alors `save_forced_overrides()`, depuis retiré au profit de `save_series_override(SeriesOverride(...))`). Aucun fichier n'était fautif isolément ; le bug n'existait que dans l'interstice entre les fichiers. **Chaque fois que vous ajoutez ou modifiez un réglage par série ou global, tracez-le manuellement de bout en bout** : champ HTML → construction du payload dans `script.js` → extraction du paramètre dans la route Flask → écriture dans `db_manager.py` → lecture dans `db_manager.py` → construction de `existing_metadata` dans `app.py` → consommation par le scraper. Un moyen rapide de détecter cette classe de bug consiste à rechercher tous les appels de la fonction de persistance (ex : `save_series_override(`) et à comparer les champs du `SeriesOverride` avec la dataclass.

#### D. Centraliser, Ne Pas Dupliquer, la Logique d'Assainissement et de Mapping
Plusieurs bugs de ce code partagent la même cause racine : une règle (un mapping d'énumération de statut, une règle d'assainissement de payload, une convention de verrou) est implémentée une fois dans une fonction utilitaire, puis partiellement réimplémentée "par précaution" dans un appelant, et les deux définitions divergent silencieusement avec le temps (ex : le statut brut `"completed"` de MangaBaka qui ne correspondait jamais à la clé interne `"FINISHED"` attendue par `app.py`). Privilégiez l'ajout d'une nouvelle règle à un seul endroit — dans `kavita_api.py` pour tout ce qui concerne le format des payloads Kavita, ou `scrapers/utils.py` pour tout ce qui concerne le contrat des scrapers — et faites dépendre chaque site d'appel de cette source unique de vérité plutôt que de la redériver localement.

#### E. Tester Sans Instance Kavita en Ligne
Utilisez les scripts autonomes `debug_*.py` à la racine du projet pour valider un changement de logique avant de toucher un vrai serveur :
* `debug_all_scrapers.py` / `debug_scoring_20.py` / `debug_manga_quality.py` : tests de non-régression du moteur de scoring et du contrat des scrapers.
* `debug_publisher.py` : extrait le payload brut `publishers` des API MangaBaka/MangaUpdates et exécute la logique d'extraction `LOCALIZED`/`ORIGINAL` en parallèle pour vérifier la fonctionnalité de Préférence d'Éditeur.
* `debug_cover.py` / `debug_concurrency.py` : validation du format du payload d'upload de couverture et détection des races conditions du cache.
* `debug/benchmark_batch.py` : chronométrage batch séquentiel avec options lourdes forcées (`--limit`, `--library-id`, `--ids` ; dry-run par défaut ; `--live --i-know` pour écritures Kavita réelles).

Lors de la correction d'un bug, étendez l'un de ces scripts (ou créez-en un nouveau) pour le reproduire d'abord — c'est le moyen le plus rapide de confirmer qu'un correctif fonctionne réellement, sans reconstruction Docker complète ni parcours manuel dans l'interface Kavita.
⚠️ Ces scripts interrogent de vrais fournisseurs ; **`python -m pytest` ne le peut pas**. Depuis la v1.7.0, une barrière bloque toute connexion sortante pendant la suite (section 15.D) — écrivez les tests de scraper sur des fixtures, et ne pointez jamais un script vers un fournisseur pour « vérifier la cadence » : c'est exactement comme cela que l'IP du développeur s'est fait bannir par Bédéthèque.

#### F. La Documentation Fait Partie du Correctif
Chaque correctif ou fonctionnalité visible par l'utilisateur doit être répercuté à la fois dans `CHANGELOG.md` (bilingue EN/FR, versionné sémantiquement — le premier en-tête `## [X.Y.Z]` est analysé automatiquement par `services/changelog_service.py::get_app_version()` pour piloter le numéro de version affiché dans l'UI) et dans `ROADMAP.md` (entrées courtes bilingues `BFxx`/`Cxx`). Gardez les deux synchronisés : chaque numéro `BF`/`C` référencé dans la section "Dernières Nouveautés" de `ROADMAP.md` doit correspondre à une entrée détaillée dans `CHANGELOG.md`, et la plage de versions affichée en haut de cette section doit toujours correspondre à la plus récente entrée de `CHANGELOG.md`.

### 12. Architecture Modulaire (Plan des Modules Post-Refactor)
Depuis le refactor d'architecture, `app.py` n'est plus qu'un point d'assemblage d'environ 130 lignes : instanciation Flask/SocketIO, middlewares (`ProxyFix`, `ScriptNameStripper`), initialisation du logging, verrou global `require_login`, enregistrement des Blueprints, et démarrage des workers de fond. Toute la logique métier vit désormais dans des modules dédiés :

*   **`kavita_constants.py`** : source unique de vérité pour les mappings d'énumération Kavita (`PUBLICATION_STATUS_MAP`, `AGE_RATING_MAP`, `resolve_kavita_format_enum()`) et la normalisation des statuts bruts fournisseurs (`normalize_provider_status()`, utilisé par `scrapers/mangabaka.py`). Ajoutez tout nouveau mapping ici, jamais en ligne dans une route ou un scraper.
    *   **`AGE_RATING_MAP` (BF53 / BF80 / BF81)** — scrapers émettent `safe` / `suggestive` / `mature` / `r18` / `x18` (aliases dépréciés : `erotica`→`r18`, `pornographic`→`x18`). Map : `safe→3`, `suggestive→8`, `mature→10`, `r18→12`, `x18→14`. `r18` = 18+ restreint (pas forcément porno) ; `x18` = sexuel explicite. Kitsu : `G→safe`, `PG→suggestive`, `R→mature`, `R18→pornographic`. **BF81 :** `apply_explicit_label_age` force `x18` si genres/tags `hentai`/`futanari` (remplit ou escalade ; jamais downgrade), avant tri Auto / apply classique — sans changer les scores. Gardes : `tests/test_age_rating_map.py`, `tests/test_kitsu_age_bf80.py`, `tests/test_age_fill_labels_bf81.py`.
    *   **Safeguarding âge (BF56 / v1.6.2)** — ne jamais inventer `safe` sans signal d'âge provider (omettre le champ). Préférer omettre plutôt qu'under-rater. Mappings autoritatifs uniquement : MAL `nsfw`, MangaDex `contentRating`, Kitsu `ageRating` (tokens connus seulement), Manga-News `#agenumber`, Google Books `maturityRating=MATURE` → `erotica` (alias `r18`), AniList seulement si `isAdult`, BDTheque `_parse_age` (Adulte/Érotique → `erotica` ; « Ados - Adultes » → `suggestive`). Garde-fou : `tests/test_age_safeguarding_bf56.py`.
    *   **Comblement âge SMART_COMPLETION (BF102)** — combler les trous dès qu’une source a un vrai signal : fusion Auto `safe`/`suggestive`/`mature` → âge vainqueur vide ; ages NSFW secondaires bloqués pour la **justesse** (faux X18+ / prefer-safe), pas un filtre moral. L’âge du vainqueur n’est pas écrasé. Écriture Kavita toujours filtrée par le champ ciblé `age`. Skip « déjà à jour » annulé si `age` actif et `ageRating` Kavita absent / `0` / `1` (Pending). Log : `log_age_write_diag`. Voir Smart Scoring §D.
*   **`models.py`** : la dataclass `SeriesOverride`, contrat typé des surcharges par série (ID/provider forcé, titre alternatif, champs ciblés, préférence d'éditeur, `alt_title_langs`). Persistez via `db_manager.save_series_override(SeriesOverride(...))` (champs nommés) — l'ancien wrapper positionnel `save_forced_overrides(...)` a été retiré. C'est une mitigation structurelle directe de la classe de bug décrite au §11.C.
*   **`extensions.py`** : l'instance partagée `socketio = SocketIO()` (créée sans app, `init_app(app)` appelé une seule fois dans `app.py`). Importez-la depuis ce module — jamais depuis `app.py` — dans tout module ayant besoin d'émettre des événements ou de déclarer des handlers `@socketio.on(...)`, pour éviter les imports circulaires.
*   **`auth_manager.py`** : CRUD comptes, hachage Werkzeug (`pbkdf2:sha256`), verrouillage par IP + plafond global, preuve de propriété legacy sur `/setup`, amorçage `ADMIN_PASSWORD_HASH` / `ADMIN_USERNAME`, `TRUSTED_PROXY_COUNT`, helpers de session, `setup_gate` / `login_gate`. Fail-closed ; ne jamais importer un `ADMIN_PASSWORD` en clair comme nouveau mot de passe.
*   **`config_manager.py`** : `load_config()` / `save_config()` — fusion env **avant** la première écriture des secrets (BF51) ; précédence `config.json` > env > défaut ; `config.json` en mode 0600.
*   **`services/enrichment_engine.py`** : `enrich_series(series_id, series_name, force_update, targeted_fields_override=None)`, extraction de l'ancien `process_series_logic()`. Logique d'orchestration pure (scraping, mapping des champs, appels Kavita, broadcast télémétrie lifetime) sans aucune dépendance vers Flask ni `app.py`. Héberge aussi les chemins apply/preview/research de la Review Manuelle (C29) et `seal_series_locks` (`NEEDS_RELOCK`). Cascade Comic Flexible ici.
*   **`services/manual_review.py`** : helpers de park C29 — `create_review_from_candidates` / `create_confirm_from_auto` (acceptent tous les deux un `library_id` optionnel, utilisé pour le lien de vérification Kavita — §4.H), `choice_and_merge`, émetteurs skip/confirm/purge, traduction des résumés avant pick. Persistance via `db_manager.park_pending_review` / `close_pending_review` (atomique).
*   **`services/background_tasks.py`** : les workers démons (consommateur de `sync_queue` + polling d'auto-sync périodique) et `start_background_workers()`, appelé une seule fois par `app.py` au chargement du module (comportement inchangé, requis pour un déploiement Gunicorn à worker unique `-w 1`). Items de file : des **dicts** construits par `make_sync_item(series_id, series_name, force_update, fields_override=None, is_batch=False)` — plus des tuples 3-/4-. `is_batch` pilote les compteurs de progression dédiés `_batch_total`/`_batch_done`/`_batch_real_sends` (§4.F) ; l'auto-sync ignore `PENDING_REVIEW` et filtre ses candidats par bibliothèque via `select_auto_sync_candidates()` — le **seul** endroit où `DISABLED_LIBRARIES` s'applique (§4.J).
*   **`services/stats_service.py`** : métriques `/stats` ludiques + payload Chart.js à partir des compteurs lifetime + snapshot cache + hauts-faits Manual Review (`mr_achievements.py`). Piloté par `ENABLE_PLAYFUL_STATS`.
*   **`services/changelog_service.py`** : `get_app_version()` / `get_current_version()` (mise en cache) / `get_full_changelog_html()`. Importé indépendamment par `app.py` (contexte global des templates) et par `routes/misc.py` (`/api/changelog`) — importer depuis ce module plutôt que l'un depuis l'autre évite un import circulaire.
*   **`routes/*.py`** : un Blueprint Flask par domaine — `auth` (`/setup`, `/setup/test-kavita`, `/login`, `/logout`, `/account/password`), `pages` (`/`, `/stats`), `config` (`/save-config`, `/regenerate-webhook-token`), `series` (`/save-override`, `/toggle-ignore`, recherche/application de couverture, `POST …/seal-locks`, `POST …/seal-locks-pending`), `sync` (`/force-sync` [enfile en tête de `sync_queue` et répond 202 — aucun enrichissement dans la requête], `/batch-sync` [inventaire mis en cache par batch, voir `_get_batch_inventory` §4.F], `/stop-batch`, `/reset-errors`, `/export-errors`, `/webhook`), `manual_review` (`/api/manual-reviews…` dont `POST …/bulk-accept`), `companion` (`GET /companion/embed` — shell MR C33 pour l’extension ; CSP `frame-ancestors` : `chrome-extension:` / `moz-extension:` + `COMPANION_FRAME_ANCESTORS` optionnel), `library_audit` (scan Inventaire, doublons, `POST …/duplicates/script` — C85 rend un script bash et ne l'exécute jamais ; pas de `DELETE /api/Series`), `misc` (`/healthz`, `/api/proxy-image`, `/api/changelog`). Le `/setup` first-run est un wizard 6 étapes (C64) qui crée le compte et fusionne Kavita / langues / options / cascades dans `config.json`.
*   **Companion C33** — voir **§13** ci-dessous (flags webhook, embed token, priorité de file, layout extension). Rappel : extension dans `companion/` (Chrome + Firefox MV3).
*   **`sockets/handlers.py`** : handlers Socket.IO (`connect`, `fetch_covers_stream`), enregistrés sur `extensions.socketio` ; importé une seule fois pour son effet de bord depuis `app.py`. `connect` non authentifié → `return False` ; connect réussi émet `manual_review_pending_count` / `manual_review_queue_summary` **uniquement vers le `sid` connecté**.
*   **`static/js/*.js`** : l'ancien `script.js` monolithique est désormais découpé en fichiers `<script>` classiques chargés dans l'ordre de dépendance (`utils.js` → `websocket.js` → `overrides.js` → `covers.js` → `config.js` → `batch.js` → `manual_review.js` → `license_nag.js` → `main.js`). Volontairement sans bundler ni `type="module"` : les templates s'appuient sur des gestionnaires `onclick="..."` inline, qui exigent que chaque fonction reste en portée globale.
*   **`templates/partials/*.html`** : l'ancien `index.html` monolithique est désormais une coquille légère qui `{% include %}` des partials Jinja — dont `_manual_review_modal.html` pour C29 — un par zone d'UI autonome. Modifiez directement le partial concerné plutôt que de faire défiler un template unique de 600+ lignes.
*   **`tests/`** : le filet de sécurité pytest (fixtures `conftest.py` + tests métier dont `test_auth.py`, `test_healthz.py`, `test_config_env_seeding.py`, `test_db_manager.py`, `test_kavita_api.py`, `test_playful_stats.py`, `test_manual_review.py`, `test_manual_review_bulk_accept.py`, `test_manual_review_queue_api.py`, `test_needs_relock.py`, `test_batch_inventory_cache.py`, `test_batch_progress_isolation.py`, `test_dashboard_renders.py`, `test_supporter_nag_policy.py`, `test_batch_targeted_fields.py`, `test_comic_flexible.py`, `test_scraper_mangabaka.py`, `test_routes_series.py`, `test_max_tags.py`, `test_max_genres.py`, `test_scraper_max_caps.py`, `test_audit_c1_c3.py`, `test_fallback_query.py`, `test_metadata_fetcher_smart_scoring.py`, …). Les fixtures ne touchent jamais au vrai dossier `data/` ni au réseau — `isolated_db` monkeypatch `db_manager.DB_FILE`/`DATA_DIR` vers un fichier SQLite `tmp_path`, `flask_app`/`client` construisent une application Flask minimale n'enregistrant que `routes/series.py` (pas `app.py` en entier, pour éviter de démarrer de vrais workers de fond/logging), et `mock_kavita_api` bouchonne chaque méthode réseau de `KavitaAPI`. Voir §10. Helpers partagés : `url_allowlist.py`, `csrf_utils.py`, `cors_config.py`.

⚠️ **Les noms d'endpoints des Blueprints ont changé.** Flask préfixe toujours l'endpoint d'une route de Blueprint par le nom du Blueprint (ex : la vue `login` de `routes/auth.py`, enregistrée sur le Blueprint `auth`, devient l'endpoint `auth.login` — impossible de désactiver ce préfixage). Chaque appel `url_for(...)` et les listes blanches de `auth_manager.setup_gate` / `login_gate` ont été mis à jour en conséquence (`auth.setup`, `auth.login`, `auth.logout`, `pages.index`, `pages.stats`, `misc.healthz`, `sync.export_errors`, `sync.webhook`). **Si vous renommez un Blueprint ou déplacez une route vers un autre Blueprint, recherchez son ancien nom d'endpoint dans `auth_manager.py`, `app.py` et dans chaque template `.html` avant de supposer que `url_for()` fonctionne toujours.**

---

### 13. MetaKavita Companion (C33)

**Statut :** bêta / early access — **sideload uniquement** (pas sur Chrome Web Store ni Firefox AMO). Nécessite MetaKavita **1.6.5+**.

Install utilisateur, branchement et fonctions : [`companion/README.md`](companion/README.md) (EN + FR). Notes contributeurs côté extension (layout, protocole messages, pack) : [`companion/DEVELOPER.md`](companion/DEVELOPER.md).

#### Rôle

Extension MV3 sous `companion/` qui injecte un menu flottant sur les **fiches série** Kavita (`/library/{lib}/series/{id}` uniquement — pas le reader). Actions : Super Review, Auto, Cover, Config, Buy me a coffee.

#### Surface serveur (MetaKavita)

| Élément | Rôle |
|---------|------|
| `POST /webhook` | Auth via `X-Webhook-Token` (préféré) ou `?token=` legacy. Companion peut envoyer `seriesId` seul (nom via `KavitaAPI.get_series`), plus flags one-shot `auto` / `super_review` (+ `force` habituel). |
| `make_sync_item(..., super_review=, force_auto=)` → `enrich_series(..., force_auto=, super_review_override=)` | Overrides one-shot ; les boutons Companion **n’exigent pas** les toggles MR/Super globaux. |
| `put_front` (`services/background_tasks.py`) | Enfile en priorité : après le job en cours, devant le reste de `sync_queue` ; retire les pending même `series_id` (RAM + lignes C63 `queued`). |
| `GET/POST /companion/embed-token` | Jeton embed court, lié à un `series_id` (`services/companion_embed_auth.py`). |
| `GET /companion/embed` | Shell Manual Review pour iframe / nouvel onglet (`routes/companion.py`, `templates/companion_embed.html`). CSP `frame-ancestors` : `chrome-extension:` / `moz-extension:` + `COMPANION_FRAME_ANCESTORS` optionnel. |
| APIs covers | Utilisées par le background de l’extension pour Cover pick (mêmes chemins allowlist / proxy que le dashboard). |

#### Streaming Manual Review

Sur les chemins MR / Super Review utilisés par Companion, l’enrichissement parque une review vide tôt (`begin_streaming_review`), ajoute les cartes au fil des scrapers (`append_streaming_candidate` → Socket.IO), puis `finalize_streaming_review`. L’embed peut s’ouvrir avant la fin de la cascade.

#### Contenu mixte

HTTPS Kavita + HTTP MetaKavita : le navigateur bloque l’iframe HTTP. Companion ouvre Super Review dans un **nouvel onglet** (garder `opener`, pas de `noopener`) et le ferme en fin de parcours. Vrai correctif pour le MR in-page : servir MetaKavita en HTTPS (ou Kavita en HTTP sur le LAN).

#### Auth / CSRF

- Webhook exempt CSRF (auth par jeton).
- Le jeton embed peut autoriser l’embed Companion + chemins MR/cover associés sans cookie de session (nécessaire dans les iframes / onglets Kavita cross-origin). Préférer les checks scopés série quand la route a un `series_id`.
- L’auth Socket.IO Companion suit le même modèle de jeton embed pour les streams de covers.

#### Tests

- `tests/test_companion_webhook.py` — `seriesId`, `auto` / `super_review`, overrides enrich
- `tests/test_companion_embed.py` / `test_companion_embed_auth.py` — shell embed + jeton
- `tests/test_companion_i18n.py` — chaînes UI
- `tests/test_sync_queue_priority.py` — `put_front` / remplacement pending
- `tests/test_manual_review_streaming.py` — park streaming / finalize

#### Pack de l’extension

```bash
node companion/scripts/pack.mjs
```

Produit `companion/dist/metakavita-companion-chrome.zip` et `…-firefox.zip`. Incrémenter **les deux** `version` (`manifest.json` et `manifest.firefox.json`) pour un changement visible. Ne pas committer les dossiers de staging `dist/_chrome/` / `dist/_firefox/` (gitignorés).

Ces zips sont ce que les utilisateurs installent : repacker dans le même commit que la modification des sources. Le job `companion` de `tests.yml` passe `node --check` sur chaque script et lance trois self-checks (`selfcheck-url-match.mjs`, `selfcheck-i18n.mjs`, `verify-dist.mjs`), et `verify-dist.mjs` échoue dès qu'un zip est en retard sur ses sources. Voir [companion/DEVELOPER.md](./companion/DEVELOPER.md).

<br><br>

---

### 14. Enrichissement par tome et par album (#27)

#### La règle qui gouverne tout : relire le chapitre avant de l'écrire

Un tome Kavita n'a pas de métadonnées propres : elles vivent sur ses **chapitres**. Écrire un tome revient donc à écrire ses chapitres, via `POST /api/Chapter/update`.

`UpdateChapterDto` est un **remplacement total**. Tout champ absent de l'envoi prend sa valeur par défaut, et le contrôleur assigne sans condition : omettre le résumé le vide, omettre `writers` efface tous les auteurs, `ageRating` retombe à *Unknown*, les vingt verrous à `false`, et `sortOrder` à **0** — ce qui détruit l'ordre de lecture de la série entière.

D'où la règle : **lire le chapitre, fusionner, réécrire l'intégralité.** `services/kavita_chapter_payload.build_update_chapter_dto(current, changes)` recopie tous les champs du `ChapterDto` lu — `sortOrder`, les treize collections de personnes, genres, tags, `ageRating`, `language`, `webLinks` et les vingt verrous — puis applique les changements par-dessus et ne verrouille que ce qu'il a écrit. Ne jamais construire ce payload à la main.

`apply_entry` relit le chapitre juste avant d'écrire, même quand un plan existe déjà : un aperçu bâti il y a dix minutes décrit un état que l'utilisateur a pu éditer depuis. Une lecture qui échoue donne une unité `FAILED`, jamais un dictionnaire vide — un dictionnaire vide passerait pour un chapitre sans métadonnées et l'écriture effacerait tout.

#### Contrat fournisseur : `fetch_volume_index`

```python
def fetch_volume_index(self, query, library_type="Comic", series_id=None,
                       existing_metadata=None):
    """Index des tomes/albums d'une série : {numero: payload}. Défaut : None."""
```

Un seul appel réseau pour toute la série quand le fournisseur le permet — `/api/issues/?filter=volume:X&limit=100` chez ComicVine ramène cent albums, résumés et couvertures compris, si bien qu'une série de 150 numéros coûte deux appels. `fetch_volume` (un appel par tome) ne sert qu'aux fournisseurs incapables de lister.

Clés du payload : `title`, `summary`, `release_date`, `isbn`, `cover_url`, `provider_ref`. Déclarer `scopes = {"series", "volume"}` pour que `ScraperRegistry.get_by_scope("volume")` retienne le scraper. Les fournisseurs HTML doivent plafonner leur parcours (`VOLUME_INDEX_MAX = 50` sur Bédéthèque et Planète BD à 2,5 s, **40 sur Manga-News à 6 s**) : un index sans plafond, c'est un quart d'heure de scraping muet, et chez Manga-News c'est aussi le profil qui fait bloquer l'adresse. `fetch_index` ne s'arrête plus sur un index de seules couvertures : MangaDex qui liste tous les tomes par leur jaquette ne doit pas empêcher Manga-News d'être interrogé pour les titres et les résumés.

#### Appariement, et les sentinelles de Kavita

Kavita range les chapitres sans tome dans le volume **-100000** (`Parser.LooseLeafVolumeNumber`) et les hors-série dans le volume **100000** (`Parser.SpecialVolumeNumber`). `services/volume_enrichment/matching.py` neutralise les deux : les prendre pour des numéros de tome demanderait « l'album 100000 » à un fournisseur et, pire, écrirait les données du tome 1 sur un spin-off. `number_key` normalise aussi `3.0`, `"3"` et `"03"` en une seule clé, sans quoi aucun des trois fournisseurs ne s'apparierait jamais.

#### Plan des modules

| Module | Rôle |
|--------|------|
| `services/kavita_chapter_payload.py` | Construit `UpdateChapterDto`, normalise les dates, valide l'ISBN-10/13 (Kavita rejette silencieusement un ISBN invalide) |
| `services/volume_enrichment/matching.py` | Réponse Kavita → unités écrivables ; appariement des numéros ; sentinelles |
| `services/volume_enrichment/plan.py` | Politique de comblement. Pur — **aucune E/S**, c'est ce qui fait de l'aperçu un aperçu |
| `services/volume_enrichment/apply.py` | Relecture, écriture, upload de couverture, état d'unité |
| `services/volume_enrichment/providers.py` | Choix du fournisseur, cadence, cascade ISBN, recherche titre + numéro. `resolve_index()` est le point d'entrée : c'est lui qui complète un index de couvertures par la cascade au lieu de s'y arrêter |
| `services/volume_enrichment/translate.py` | Résumés d'album dans la langue cible, appliqué **au plan**, mémoïsé sur le texte source |
| `services/volume_enrichment/job.py` | Passe de bibliothèque en thread dédié |
| `routes/volume_enrichment.py` | Aperçu / application / passe / statut / annulation, tous derrière une garde 403 |

`job.py` ne passe **pas** par `sync_queue` : cette file n'a qu'un worker, partagé par le webhook Kavita, l'auto-sync et le bouton de chaque ligne, et une passe de mille tomes gèlerait les trois pendant des heures. Elle suit `library_audit/hygiene_scan.py` — un thread, un état sous verrou, une annulation coopérative entre deux unités. Le filtre de reprise — `list_enriched_series_ids` à la maille série, `volume_unit_cache` à la maille tome — ne s'applique que si **aucune** sélection explicite n'est donnée (`resume and not series_ids`). Comme la barre d'outils envoie toujours les séries cochées, une passe lancée depuis l'interface ne saute rien : nommer une série est une demande explicite, et `VOLUME_FORCE_OVERWRITE` est le seul levier que l'interface offre pour en refaire une — un saut silencieux rendrait donc cet interrupteur inopérant. Ce à quoi le cache sert encore : les états par unité affichés dans l'aperçu, et `POST /api/series/<id>/volume-enrich/reset`.

#### La traduction porte sur le plan, pas sur l'index

`translate_plan_summaries()` est appelé **après** `build_plan()` et ne touche que les résumés dont le changement porte `write: True`. Elle portait d'abord sur l'index entier du fournisseur, en amont de l'appariement : un appel réseau par album connu du fournisseur, soit cent numéros ComicVine pour les dix tomes que Kavita détient — et, sur une série déjà enrichie, tous les résumés retraduits à chaque passe alors qu'ils sont remplis et verrouillés, donc écrits nulle part. Le journal se lisait comme une ligne par seconde pendant des minutes. Une série déjà faite ne coûte plus aucun appel. Le doublon que le grain de l'index évitait — un album couvrant deux chapitres — reste couvert : la clé de la mémoïsation est le texte source. Deux points à garder en tête si l'on y touche : `translate_texts(..., quiet=True)` est voulu — le traducteur journalise une ligne par requête, ce qui noyait la progression de la passe, d'où le décompte rendu à la place ; et une traduction qui retombe exactement sur ce que Kavita détient déjà repasse le champ en `filled`, compteurs du plan recalculés, sans quoi une passe forcée annoncerait une écriture pour réécrire la même phrase.

Les résumés partent ensuite en **un seul appel** pour toute la série (`_translate_and_remember`), ce qui met la passe hors de portée d'un blocage — voir la règle B de la section d'audit. Deux conséquences : la liste des textes à traduire est constituée avant tout envoi, donc une série dont les résumés sont tous mémoïsés ne coûte aucune requête ; et une réponse dont la longueur ne correspond pas à l'envoi est abandonnée plutôt que distribuée, un décalage verrouillant le résumé d'un album sur un autre.

#### Deux clés, et une série qui n'en a aucune est écartée avant le premier appel

Une unité s'apparie sur un **numéro de tome** ou, à défaut, sur son **ISBN** — `matching.unit_key()`. Les clés ISBN portent le préfixe `isbn:` (`ISBN_KEY_PREFIX`), qui n'est pas un nombre : les deux sortes ne peuvent donc pas se confondre dans un même index. `index_key()` est le côté lecture de la même règle, et c'est ce que `normalize_index()` utilise désormais. `fetch_by_isbn` classe ses résultats avec `unit_key` : une unité numérotée garde son numéro (inchangé), un one-shot reçoit son propre ISBN. L'ISBN est la plus sûre des deux clés, pas le pis-aller qu'il paraît : il désigne une édition, quand un numéro suppose seulement qu'on parle bien de la même série.

`matching.unmatchable_reason(units, series_name)` s'exécute dans les deux chemins qui interrogent un fournisseur — `_enrich_one_series_locked` pour la passe, `build_series_plan` pour l'aperçu et l'écriture d'une série — juste après la lecture des tomes et **avant** tout accès réseau. Il rend `oneshot`, `specials` ou `""`.

Le raisonnement est structurel, pas heuristique : `fetch_index` filtre son index par `normalize_index(index, keys=wanted)`, et `fetch_by_isbn` comme `fetch_by_title_volume` sautent l'unité sans clé. Quand aucune unité n'en rend, aucune cascade ne peut donc produire la moindre entrée écrivable — la recherche est démontrablement perdue, et chez un fournisseur HTML elle coûte jusqu'à deux minutes plus un tour de cadence pour tous ceux qui viennent derrière. La passe appelle `mark_series_pass_done()` en sortant : le verdict a été rendu sans appel, une reprise n'a rien à réessayer.

`resolve_index` prend le même raccourci par l'autre bout : **aucun numéro de tome** signifie qu'un index par série n'a rien à quoi s'apparier, donc il part directement en cascade ISBN et ne demande aucun index. Attention à la garde — `if units and not matchable_numbers(units)`. Un `units` vide veut dire *l'appelant n'a rien dit de la série*, convention que `_covers_enough` honore déjà pour les outils et l'aperçu d'un seul tome : ne rien savoir ne doit pas fermer l'index par série.

Trois choses ne doivent pas dériver ici :

* le prédicat s'appuie sur l'**absence de toute clé**, jamais sur le nombre d'unités. Une série dont on ne possède que le tome 1 rend la clé `1`, elle est cherchée, et elle doit le rester — c'est le cas pour lequel l'écriture par tome existe, et l'écarter la marquerait close, donc invisible pour de bon ;
* un **titre ne décide de rien**. « One shot » dans un nom de série est tout aussi bien un nom de collection, et un recueil numéroté doit rester servi. `series_name` reste dans la signature pour un motif futur qui en aurait besoin, pas pour celui-ci ;
* `matchable_numbers` / `matchable_keys` ne retirent **que les hors-série**. L'absence de `chapter_id` est une autre question — où écrire — et elle appartient à `match_units` et à `unmatchable_reason`, qui filtre donc lui-même dessus. Fusionner les deux filtres, et les unités assemblées à la main (outils, tests) perdent leur index par série.

`plan_unit` note `matched_key` à côté de `matched_on`. `matched_on` reste le *numéro*, parce que c'est lui que la colonne « Tome » de l'aperçu affiche et qu'« isbn:9782800… » ne s'y lit pas ; `matched_key` est ce sur quoi `_mark_duplicates` regroupe, de sorte que deux fichiers d'un même one-shot sont signalés par leur ISBN commun au lieu de s'écrire tous les deux en silence.

L'Inventaire ne reçoit **volontairement pas** le même raccourci. C'est son appel catalogue qui décide du one-shot contre l'incomplet (`catalog_expected == 1` contre `> 1`) : un court-circuit local classerait un manga dont on possède un seul chapitre en one-shot terminé — exactement l'inverse de ce à quoi l'Inventaire sert.

#### Ce que le journal doit à celui qui le regarde

Deux règles, tenues par `tests/test_volume_enrichment_journal.py`.

**Une série se nomme, et porte son identifiant à côté.** `secure_logging.series_label()` rend `« Blacksad » (6429)`, et `« série 6429 »` — annoncé comme un identifiant — quand Kavita ne rend aucun titre. Il vit dans `secure_logging` et non dans un module de tomes parce que le scan d'Inventaire, la passe par tome et l'enrichissement série écrivent dans le même journal, et que le lecteur n'a aucune raison d'y rencontrer trois façons de nommer la même série. `plan.unit_label()` fait de même pour une unité : `tome 3`, et non l'identifiant de chapitre que l'utilisateur n'a jamais vu. `apply_plan()` lit le nom dans `plan["series_name"]` plutôt que de le prendre en paramètre — les deux appelants le remplissent déjà, et une signature qu'on ne peut pas oublier vaut mieux qu'une signature qui journalise un numéro quand on l'oublie.

**Toute phase de plus d'une seconde s'ouvre et se referme.** La recherche des albums, la traduction et l'écriture ouvrent chacune sur une ligne (`▶ … recherche des albums…`) et se referment sur une ligne portant leur résultat et leur durée ; la passe elle-même encadre l'ensemble. Ce n'est pas de l'ornement : une série peut prendre une minute, et la panne qui a mené ici — un téléchargement de couverture qui ne revenait jamais — était indiscernable d'une passe jamais démarrée, faute de la moindre ligne entre le plan et le bilan. La ligne de clôture porte toujours la durée écoulée : c'est ce qui transforme « c'est lent » en « le fournisseur a pris 12 s et les couvertures 5 s ». Le bilan d'une passe annulée porte sa propre marque (`⛔`), une coche sur une passe interrompue se lisant comme une passe allée au bout.

#### Interrupteurs

`VOLUME_ENRICHMENT_ENABLED` (éteint par défaut — l'API répond 403 tant qu'il l'est), `VOLUME_FORCE_OVERWRITE` (lève la règle de comblement, bloc rouge), `VOLUME_ENRICH_CREDITS` (un appel de plus par album), `VOLUME_ENRICH_EXPERIMENTAL` (recherche titre + numéro, voir plus bas).

L'ordre des fournisseurs n'est **pas** un réglage de plus : `volume_providers()` lit la cascade de la modale Fournisseurs pour le type de bibliothèque (`COMIC_PROVIDER_1..3`, `BOOK_PROVIDER_1..3`, `PROVIDER_1..3`), la même que l'enrichissement par série. `ScraperRegistry.get_by_scope()` trie par nom d'affichage, ce qui plaçait Bédéthèque avant ComicVine sur toute bibliothèque de comics — et comme `fetch_index()` garde le premier index non vide, un homonyme franco-belge suffisait à écrire les tomes d'une autre œuvre. Les fournisseurs que la cascade ne nomme pas gardent l'ordre du registre, après ceux qu'elle nomme. Deux exceptions, toutes deux pour les tomes seulement, sans toucher la cascade série : sur une bibliothèque **Manga**, Manga-News passe devant (`MANGA_VOLUME_LEAD`), parce que c'est le seul index manga qui rende titre, résumé, ISBN et date plutôt que des jaquettes que Kavita a déjà ; sur **ComicFlexible**, la vague comics reste première, puis Manga-News en dernier recours manga, puis MangaDex pour les couvertures.

**Deux familles de fournisseurs, et `VOLUME_PROVIDER` peut nommer l'une ou l'autre.** `volume_providers()` est bâti sur `get_by_scope("volume")` : il n'a donc jamais contenu que les fournisseurs capables de *lister* les albums d'une série. `UNIT_PROVIDERS` — Google Books, Open Library, Hardcover — répondent à l'unité, par ISBN, et complètent ce que l'index n'a pas couvert (Manga-News liste les tomes VF ; MangaDex, les couvertures) ; ils servaient les tomes depuis le début tout en restant invisibles au réglage, qui journalisait « fournisseur imposé inutilisable » avant de reprendre la cascade. Imposer l'un d'eux fait maintenant rendre `[]` à `volume_providers()` — volontairement, demander un index à quelqu'un d'autre serait l'inverse du réglage — et `resolve_index()` le lit par `forced_unit_provider()` : il saute `fetch_index` et passe `provider_ids=[imposé]` à `fetch_by_isbn` et `fetch_by_title_volume`. Quand le fournisseur imposé n'a plus rien à tenter (aucun ISBN sur les tomes, et il n'est pas dans `TITLE_VOLUME_PROVIDERS`), une ligne `INFO` désigne le réglage : l'aperçu affiche « aucun fournisseur ne connaît cette série » et accuserait sinon le fournisseur.

⚠️ **Imposer un membre de `TITLE_VOLUME_PROVIDERS` *est* l'autorisation que réclame `VOLUME_ENRICH_EXPERIMENTAL`** : `resolve_index()` lance donc la recherche titre + numéro pour un Google Books imposé quoi que dise l'interrupteur, lequel continue de régir la cascade automatique, où personne n'a nommé de fournisseur. Lire les deux conditions comme un « et » est toute la panne remontée sur les mangas : imposer le seul fournisseur capable de trouver un tome sans ISBN supprimait l'index (voir plus haut) *et* refusait le seul chemin restant — le geste fait pour remplir un aperçu vide garantissait qu'il le reste. Gardez l'ouverture implicite liée à `unit_only` : une cascade que personne n'a forcée ne doit pas se mettre à chercher sans identifiant sur une bibliothèque entière. `volume_provider_choices()` bâtit le menu de la barre latérale sur la même règle, en étiquetant chaque entrée `index` ou `unit` pour les deux `<optgroup>` — une liste plate ferait imposer Open Library sur une bibliothèque de comics scannés, où il ne peut rien rendre.

`provides_volume_index(scraper)` remplace `hasattr(scraper, "fetch_volume_index")`, qui répondait oui pour tout le monde : `BaseScraper` définit la méthode et sa version rend `None`. La comparaison porte sur le `__func__` de la méthode liée contre l'implémentation de base, si bien qu'un scraper tiers déclarant `scopes = {"volume"}` sans l'écrire ne coûte plus un tour de `throttle_provider` par série pour une réponse vide garantie.

Deux interrupteurs rétrécissent cette liste au lieu de la réordonner. `VOLUME_NO_MANGA_FALLBACK` écarte les scrapers dont `supported_types` ne contient pas `Comic`, et **seulement sur `ComicFlexible`** — c'est le seul type qui enchaîne volontairement les deux cascades, donc le seul où couper un repli ne laisse pas une bibliothèque sans fournisseur. `VOLUME_PROVIDER` n'en garde qu'un et écarte les autres, mais seulement s'il est déjà candidat pour ce type de bibliothèque : imposer un fournisseur de comics ne doit pas laisser une bibliothèque manga avec une liste vide, ce qui se lirait « aucun fournisseur ne connaît cette série » et accuserait le fournisseur au lieu du réglage — la cascade y reprend, avec une ligne `INFO`. Les deux appartiennent à `index_cache._cascade_signature()` : ils changent la liste consultée, donc l'index, et une entrée vit dix minutes.

La fonctionnalité est indépendante de l'Inventaire. Les deux partagent la modale de rapport de tomes, mais seule `library_audit.series_volume_report_units` — reconstruite depuis Kavita seul, sans appel de fournisseur — échappe à la garde 403 de l'Inventaire quand `VOLUME_ENRICHMENT_ENABLED` est allumé. Tout ce qui coûte un appel de fournisseur reste derrière l'Inventaire, et le front (`_inventoryOff()` dans `library_audit.js`) ne demande alors que le détail. Dans la barre d'outils, la passe a son propre `.toolbar-group--volumes` : logée dans `#inventoryPanel`, elle héritait de `body[data-inventory="0"] .toolbar-group--hygiene { display: none }` et disparaissait avec une fonctionnalité dont elle ne dépend pas.

#### Conventions de la barre latérale que ces interrupteurs suivent

La barre latérale enregistre sans recharger (`saveConfig()` poste et rend la main) : **un `{% raw %}{% if %}{% endraw %}` de gabarit ne peut donc pas conditionner un interrupteur à un autre**, puisque la condition n'est réévaluée qu'au chargement suivant — ce qui se lit comme un interrupteur qui ne fait rien. L'état qui traverse le panneau est tenu par le CSS, avec `:has()` :

| Classe | Rôle |
|--------|------|
| `.so-switch--volumes`, `--lab` | Couleur de famille, comme `--smart`, `--review`, `--golden`, `--danger`. Vert pour la famille des tomes, ambre pour le chemin expérimental — le seul sans aucun identifiant pour se vérifier |
| `.so-sub--volumes` | Bloc dépendant d'un interrupteur maître : grisé et `pointer-events: none` tant que `#sidebar_volume_enrichment` n'est pas coché. Le bouton **Fournisseurs** reste dehors — cette cascade sert aussi l'enrichissement par série |
| `.so-sub-note` | Ne s'affiche que dans cet état, pour dire pourquoi le bloc est inerte |
| `.so-needs-volumes` | Pour un réglage dépendant logé dans une **autre** catégorie (`VOLUME_FORCE_OVERWRITE`, dans le bloc rouge de l'écriture). Ancré sur `.scraping-options-body`, le seul ancêtre commun : `.so-anim-inner` habille aussi chaque panneau de catégorie, et celui de l'écriture ne contient pas le maître — s'y ancrer masquerait le réglage pour toujours |
| `.so-hint` | Indice d'une ligne sous un interrupteur. La classe était employée par sept paragraphes **sans aucune règle CSS**, affichés à la taille du texte courant dans une colonne réglée à 2 px |

Les explications longues appartiennent à la modale d'aide (`scraping_help_*`, une section par catégorie de la barre latérale, derrière le **?**), pas à `so-hint`. Tests : `tests/test_volume_enrichment_ui.py` vérifie l'ancre, l'absence de clé d'aide orpheline et le plafond de longueur des indices.

**Afficher et masquer un groupe de la barre d'outils demande trois pièces, et deux ne suffisent pas.** La barre latérale enregistre sans recharger : une condition Jinja autour du groupe n'est donc pas un moyen de le commander. Évaluée une fois au chargement, elle laissait le cartouche des tomes à l'écran après qu'on l'ait décoché, et absent de la page après qu'on l'ait coché — l'interrupteur paraissait cassé dans les deux sens (BF169). Le contrat, celui que `#inventoryPanel` suit déjà : (1) le gabarit rend le groupe **sans condition** ; (2) le `<body>` porte le marqueur, écrit par le gabarit au chargement *et* par `onVolumeEnrichmentToggle()` à chaque bascule ; (3) une règle CSS lit le marqueur et masque le groupe. C'est la pièce 3 qui manquait, alors que le commentaire au-dessus de la pièce 2 affirmait qu'elle existait — d'où la règle à suivre : écrire l'assertion sur la règle CSS, pas seulement sur la fonction qui pose le marqueur. La règle des tomes est `body:not([data-volumes="1"])`, et non `[data-volumes="0"]` comme celle de l'Inventaire : l'Inventaire est allumé par défaut et peut n'obéir qu'à un « 0 » explicite, là où la passe par tome est éteinte par défaut et que son bouton écrit — un marqueur absent doit donc la laisser masquée. Son unique exception est `[data-volume-pass="running"]`, posé par `_setVolumeEnrichRunningUi()` : décocher n'arrête pas une passe en cours — le réglage refuse seulement d'en démarrer — et **Annuler** vit dans ce groupe, si bien que le masquer laisserait une écriture courir sans moyen d'y mettre fin.

**Mode léger : masquer une catégorie doit éteindre sa fonctionnalité (C80).** `UI_SHOW_MANUAL_REVIEW`, `UI_SHOW_INVENTORY` et `UI_SHOW_VOLUMES` retirent une catégorie de la barre latérale ; elles sont listées sur `<body data-ui-hidden="…">` sous forme de mots séparés par des espaces, lus par `[data-ui-hidden~="manual"] .so-cat[data-so-cat="manual"]`. Un attribut plutôt que trois, parce que `data-ui-inventory` à côté de `data-inventory` ne dirait pas lequel masque et lequel éteint. C'est l'appariement lui-même qui porte tout : une catégorie qui a quitté l'écran ne commande plus rien, et deux de ces trois-là écrivent dans Kavita — une relecture manuelle masquée mais allumée remplit une file que rien ne vide, une passe par tome masquée mais allumée laisse dans la barre d'outils un bouton d'écriture dont le fournisseur imposé ne se règle plus. `config_manager.apply_light_mode()` porte la règle et `LIGHT_MODE_FEATURES` la table ; elle tourne à la **lecture** (une variable d'environnement ou un `config.json` retouché à la main ne peut donc pas produire une fonctionnalité active sans interrupteur joignable) et de nouveau dans `routes/config.py` à l'enregistrement, **avant** la purge de la file de relecture, qui compare `was_manual` à la valeur finale — sans quoi masquer la catégorie éteindrait le mode en abandonnant sa file. Les réglages dépendants de la relecture manuelle sont éteints eux aussi, parce que `routes/companion.py` lit `MANUAL_REVIEW_COVER_PICK` seul ; ceux des tomes sont laissés tels quels, puisqu'ils ne servent qu'à l'intérieur d'une passe qui ne part plus, et les garder rend ses choix à l'utilisateur. `onUiSectionToggle()` reproduit la règle à l'écran : elle décoche le maître de la barre latérale, pose `data-inventory` / `data-volumes` à `0`, et enregistre une seule fois. Elle ne rallume jamais rien au retour — une catégorie réaffichée revient éteinte. Tests : `tests/test_ui_light_mode.py`.

#### Les six pièges autour desquels ce module est bâti

**Une série appariée une fois ne doit pas l'être une seconde.** `build_series_plan` et `enrich_one_series` transmettent `provider_hints(series)`, qui porte les sept identifiants externes du `SeriesDto` — ceux qu'a écrits l'enrichissement par série. Sans eux, le chemin par tome repartait d'une **recherche par titre** à chaque passe, et une recherche par titre peut tomber sur une autre édition : le fournisseur répond, la liste d'albums est complète et valide, et aucun de ses numéros n'apparie ceux de Kavita, donc l'aperçu revient vide (*Gaston Lagaffe*, dont l'Inventaire annonçait 23 tomes attendus via ce fournisseur même). Les indices sont nommés par fournisseur — `comicvine_id`, `mal_id`… — et jamais génériques : `_resolve_volume_id` lit aussi `provider_id` et `url`, donc les remplir donnerait à ComicVine un identifiant émis par AniList, ce qui est précisément le piège que `forced_id_for()` existe pour fermer.

**Un identifiant forcé appartient à un fournisseur.** `series_cache.forced_id` ne veut rien dire hors du fournisseur qui l'a émis : `30002` désigne une série AniList, et ComicVine le lira sans broncher comme un identifiant de volume et rendra un index complet, cohérent, et faux — écrit tome par tome, verrous compris, sans rien à l'écran pour le signaler. `forced_id_for()` ne le transmet qu'au `forced_provider` nommé, ou à celui que le domaine d'une URL désigne.

**Le tome n'est pas toujours l'unité.** `unit_number()` n'apparie sur le numéro de tome que si le tome tient en un seul fichier. Un tome à plusieurs chapitres est un conteneur — le cas courant en comics, où Kavita range tout un run sous le volume 1 et fait de chaque numéro un chapitre — et apparier sur le tome donnerait le résumé et la couverture du numéro #1 à cinquante chapitres. C'est à cela que sert `sibling_count`.

**`coverImage` n'est jamais vide.** Kavita découpe toujours une vignette dans la première page : la règle de comblement ne peut pas la lire. `FIELD_SOURCES["cover_url"]` n'a donc volontairement pas de clé de lecture, et seul le verrou protège les couvertures. Comme MetaKavita verrouille ce qu'il envoie, la passe suivante épargne son propre travail.

**Un numéro tronqué est une collision.** Chaque boucle d'index garde la première entrée vue pour une clé : deux albums qui tombent sur la même clé, et l'un prend silencieusement les métadonnées de l'autre. Les éditeurs de BD numérotent leurs one-shots intercalaires 1.5 ou 3.5, et les deux parseurs HTML perdaient la décimale : un 1.5 rencontré avant le tome 1 lui prenait sa clé, et le vrai tome 1 repartait avec le résumé et la couverture du one-shot. Les numéros d'album passent par `scrapers.utils.album_number_key()`, dont la sortie doit rester identique octet pour octet à `matching.number_key()` sur la même valeur — un `1,5` ou un `1.50` n'apparierait aucun tome Kavita, et échouerait sans un mot.

**Une recherche n'est pas un appariement.** `fetch_by_title_volume` (derrière `VOLUME_ENRICH_EXPERIMENTAL`) est le seul chemin sans le moindre identifiant. La vérification vit chez le fournisseur — `_title_matches_series` et `_volume_in_title` dans `googlebooks.py` — et doit rester stricte : le numéro n'est lu que là où un mot-clé l'annonce, faute de quoi `20th Century Boys` passe pour le tome 20.

#### Tests

Celui qui compte plus que les autres : partir d'un `ChapterDto` **entièrement rempli**, ne changer que le résumé, et vérifier que chaque autre champ revient identique (`tests/test_volume_enrichment_end_to_end.py`, `tests/test_kavita_chapter_payload.py`). Sans lui, une régression détruirait l'ordre de lecture et les crédits de bibliothèques entières.

### 15. Invariants issus de la campagne d'audit v1.7.0

Sept règles que la campagne a transformées en architecture. Chacune remplace un défaut qu'une suite verte laissait passer : chacune a donc un test qui échoue s'il revient.

#### A. Les scrapers core sont versionnés, et un downgrade est refusé

Ce qui tourne dans un conteneur n'est **pas** ce qui est dans l'image : l'image alimente `data/scrapers/` au démarrage, et `services/scraper_manager.py` ne charge que ce dossier. Deux sources y écrivent — le catalogue communautaire d'abord, l'image seulement pour combler les trous — et la seule comparaison était une égalité de sha256, qui dit que deux copies diffèrent mais jamais laquelle est la plus récente. Un scraper corrigé dans une image plus récente ne pouvait donc jamais remplacer la copie plus ancienne du catalogue, et `get_by_scope("volume")` rendait une liste vide en production pendant que les tests, qui chargent ces scrapers par chemin de fichier, restaient verts.

Chaque scraper core déclare désormais `version` sur sa classe (`BaseScraper.version`, que le générateur du catalogue lit aussi). `parse_version` / `version_is_newer` / `file_scraper_version` / `package_scraper_version` / `installed_scraper_version` dans `scraper_manager.py` décident le remplacement par version, et `scraper_store._catalog_core_is_downgrade` refuse une entrée de catalogue plus ancienne que la copie installée, en journalisant les deux versions en avertissement. **Incrémentez `version` dans le même commit que toute correction d'un scraper core**, sinon l'image ne pourra pas la livrer. Et quand vous ajoutez une capacité à un scraper core, vérifiez-la par le **registre** (`get_by_scope(...)`), jamais en important le fichier : `tests/test_core_scrapers_volume_scope.py` et `tests/test_core_scraper_versioning.py` existent parce qu'un import par chemin masquait la panne entière.

Les versions arbitrent *laquelle des deux copies est la plus récente* ; elles ne disent rien de *si cette image sait l'exécuter*. Un scraper du catalogue s'exécute dans l'image, contre son `BaseScraper` et son `scrapers/utils` : une copie écrite pour une version ultérieure échoue à l'import sur une antérieure — `ImportError` sur un nom qui n'existe pas encore — et le registre la délie scraper par scraper, le fournisseur disparaissant de toutes les recherches. Les scrapers core de la 1.7.0 sont précisément ce cas : les 21 appellent `self._http_get` et importent `response_is_ok`, deux choses absentes de la 1.6.x. Une entrée de catalogue peut donc déclarer un plancher (`requires_app`, ou `min_app_version` / `requires_metakavita`), lu par `scraper_store.entry_requires_app` et appliqué par `is_entry_too_new` sur les trois chemins capables d'écrire un fichier : `sync_core_from_catalog` ignore et journalise, `install_from_catalog` refuse en 409, et `enrich_catalog_for_ui` remonte `too_new` en supprimant `update_available`. À égalité on installe — un plancher se lit « à partir de cette version ». **Quand un scraper core commence à utiliser un helper introduit par la version courante, son entrée de catalogue a besoin de ce plancher**, sans quoi le publier retire le fournisseur de tous les installs plus anciens. Tests : `tests/test_scraper_manage_store.py`.

#### B. La cadence appartient à la requête, pas à `fetch()`

`throttle_provider` (`services/provider_throttle.py`) n'était appelé qu'une fois par `fetch()` — alors qu'un `fetch()` émet 6 à 25 requêtes HTTP. Planète BD envoyait 25 requêtes coup sur coup pour une cadence déclarée de 2,5 s, et `locg.py` n'importait même pas `time`. **C'est ce qui a fait bannir l'IP du développeur par Bédéthèque pendant la campagne**, et un bannissement se lit ensuite partout comme « aucun résultat ».

Les scrapers doivent donc passer par `BaseScraper._http_get` / `_http_post`, qui appliquent la cadence du fournisseur **par requête** et portent un timeout de 20 s par défaut. `tests/test_scrapers_are_throttled.py` parcourt `scrapers/*.py` et échoue sur un appel de session direct : un nouveau scraper ne peut pas réintroduire le motif. Décision produit assumée, consignée dans `ROADMAP.md` sous En veille : **pas de filet de cadence global** autour de toute requête sortante. Un scraper communautaire qui contourne le helper peut encore partir en rafale ; c'est traité comme un bug de ce scraper, dans son propre dépôt, plutôt que payé par un goulot sur chaque requête.

**Le traducteur est un fournisseur aussi, et il n'avait aucune cadence.** `translator.py` envoyait une requête par texte, coup sur coup. Google est le moteur qui compte ici : `googletrans` et le point d'entrée `translate_a/t` tapent l'API interne du site, sans limite publiée ni contrat, et les rapports publics situent le blocage après quelques dizaines de requêtes rapprochées — le profil de trafic du bannissement Bédéthèque ci-dessus. DeepL et Azure ne bannissent pas ; leur limite est un volume (DeepL Developer : 1 000 000 de caractères **une fois, jamais renouvelés** ; anciennes clés Free : 500 000 par mois, HTTP 456 à l'épuisement ; Azure F0 : 2 M de caractères par mois, étranglés à 2 M/heure lissés, soit ~33 300 par minute, 429 au-delà même avec le quota mensuel intact).

Deux mesures, et leurs invariants. **Le regroupement** : `translate_texts()` est désormais le point d'entrée et chaque moteur prend plusieurs textes par requête — Google jusqu'à 20 par POST (`q` répété ; sa méthode de lot dans `googletrans` boucle à la place, ce qui est exactement le trafic qui fait bloquer), DeepL 50, Azure 1 000 dans 50 000 caractères. Une série entière tient en une ou deux requêtes au lieu de quarante, et les textes identiques ne partent qu'une fois. **Le nombre de traductions rendues est comparé au nombre envoyé** : une réponse tronquée décalerait le résumé d'un album sur le suivant, et la passe de tomes écrit *et verrouille* — l'erreur serait définitive. En cas d'écart, le texte d'origine est conservé. **La cadence** : un intervalle minimum depuis la dernière requête du même moteur, sur l'horloge de `provider_throttle` sous la clé `translate:<MOTEUR>` — 5 s plus une gigue pour Google, 0,5 s pour DeepL, et pour Azure le plus long entre 1 s et ce que coûte le contenu à 555 caractères par seconde. Comme c'est un *minimum depuis le dernier appel*, le chemin série — un résumé entre deux scrapings — ne paie rien.

Un 429 n'est pas le même événement partout : celui de Google est un blocage d'adresse, il n'est donc jamais réessayé (y revenir ne fait que l'allonger) et le moteur est écarté un quart d'heure ; DeepL et Azure sont réessayés à 5 puis 15 s, puis écartés cinq minutes ; le 456 de DeepL écarte la clé six heures, un crédit gratuit ne revenant pas de lui-même. Un moteur écarté bascule sur la cascade au lieu d'être redemandé une fois par tome. Tout dégrade vers le texte d'origine au lieu de lever — et c'est précisément pour cela que le contrôle du nombre et la mise à l'écart comptent plus que les réessais : **un résumé non traduit est écrit et verrouillé, donc non traduit pour de bon**. Tests : `tests/test_translator_cadence.py`, qui reprend l'horloge à son compte via `real_provider_throttle_sleep` au lieu de dormir réellement.

#### C. Un échec doit nommer sa cause

Une clé révoquée, un jeton expiré, un quota épuisé et un 403 de bannissement rendaient tous ce que rend une série inconnue : rien, et aucune ligne de journal. `scrapers/utils.py` porte la remontée : `provider_error_scope` (un `ContextVar`, il traverse donc le pool de threads comme `match_accept_threshold_scope` — rappel : `ThreadPoolExecutor.submit()` ne propage pas le contexte, soumettez via `contextvars.copy_context().run(...)`), plus `note_provider_error`, `log_provider_http_error` et `response_is_ok`. Les échecs d'authentification sont journalisés en erreur (seul l'exploitant peut y remédier), les quotas en avertissement avec le `Retry-After` quand le fournisseur le donne. ComicVine demande de lire son `status_code` dans le **corps** : il répond HTTP 200 avec une erreur applicative, ce qui passait pour un catalogue vide.

#### D. La suite de tests ne touche pas au réseau

`tests/conftest.py` installe une barrière à deux niveaux : `socket` **et** `curl_cffi`, parce que libcurl contourne entièrement la couche socket de Python — n'en patcher qu'un déplace le problème. La loopback est autorisée (le client de test Flask en a besoin), tout le reste lève `RealNetworkAccessError`. Comme les scrapers rattrapent des exceptions larges, un appel bloqué serait sinon avalé en un « aucun résultat » silencieux : les refus sont enregistrés dans `_NETWORK_REFUSALS` et signalés au teardown. Un test qui a réellement besoin du réseau demande la fixture `real_network_access`, et ne doit jamais viser un fournisseur.

Deux fixtures autouse l'accompagnent : `_no_real_translation` (16 tests appelaient réellement DeepL puis Google Translate à chaque exécution, erreurs avalées — elle bouchonne `translate_texts` autant que `translate_text`, le lot étant une seconde porte de sortie) et `_no_real_provider_throttle_sleep` (la cadence par requête de la règle B ajouterait sinon des minutes à la suite). Ne réassignez jamais globalement une classe partagée dans un test — l'un réassignait la classe de session HTTP et désarmait la protection pour tout ce qui suivait ; passez par `monkeypatch`, qui défait.

#### E. Un seul worker coopératif : un calcul long doit rendre la main

`gunicorn -w 1` avec le worker eventlet, et `app.py` monkey-patche avant tout le reste : les `threading.Thread` de la passe par tome et du scan d'hygiène sont des greenthreads. Une boucle de calcul pur ne rend jamais la main, et pendant toute sa durée **aucune requête HTTP n'est servie et aucun événement Socket.IO n'est émis** — y compris la progression de la tâche en cours, qui paraît figée. `services/cooperative.yield_to_worker()` est un `time.sleep(0)` : sous monkey-patch il repasse par l'ordonnanceur, hors monkey-patch (pytest, scripts de mesure) il ne coûte rien de mesurable, on peut donc en poser dans les boucles sans conditionner le code au mode de déploiement.

Le regroupement des doublons est le cas d'école (`services/library_audit/duplicates.py`) : quadratique, 152,8 s de calcul pur sur 1 500 séries au pire cas mesuré, zéro requête servie. Il rend maintenant la main tous les `_YIELD_EVERY_PAIRS = 2000` couples, regroupe sur tous les mots distinctifs (`_word_set_key`) au lieu du premier mot quand le seuil est haut, et unit les groupes au lieu de les reconstruire par paires — mêmes groupes, moins d'une seconde. Toute nouvelle boucle sur une bibliothèque entière doit rendre la main de la même façon.

**`curl_cffi` est libcurl, et son mode flux est inutilisable ici.** `Session(thread="eventlet")` fait passer `curl.perform()` par `eventlet.tpool`, un vrai thread système, si bien que le hub continue de tourner pendant un transfert — mais **seulement sur le chemin non-flux**. Avec `stream=True` le réglage est ignoré : `perform()` est soumis à un `ThreadPoolExecutor` et le corps est livré par une file, à laquelle le `timeout` ne s'applique plus. Un hôte qui répond puis se tait est alors attendu sans fin, et aucune échéance vérifiée entre deux morceaux ne peut se déclencher, puisque c'est l'attente du morceau suivant qui ne rend pas la main — mesuré à 8 s contre une limite de 5 s (`debug/repro_cover_eventlet.py`) ; la même requête sans `stream=True` se termine sur *Operation timed out after 5007 ms*. Ce mode laisse en plus fuir un exécuteur par session, que `Session.close()` ne ferme pas. Donc : lire le corps d'un coup et le plafonner après (`kavita_api._cover_http_session`, `_download_cover_base64`). Le compromis est assumé — un corps trop gros est reçu avant d'être refusé, borné par `COVER_FETCH_TIMEOUT_SECONDS` et, pour les hôtes honnêtes, refusé sur le `Content-Length` sans lire un octet. `requests` n'a rien de ce problème : il est monkey-patché, donc `stream=True` y reste coopératif et son délai s'applique à chaque lecture — c'est pourquoi le proxy d'images (`routes/misc.py`) le garde et applique son plafond morceau par morceau.

#### F. SQLite : garder la connexion, mémoïser le schéma

Écrire l'état d'un tome coûtait 19 ms, et la cause n'était pas le DDL : c'est la **fermeture** d'une connexion qui checkpointe le WAL, le prix était donc payé à chaque fermeture. `db_manager._wal_keeper` maintient une connexion oisive ouverte pour la vie du process, ce qui redonne son sens au mode WAL ; avec `synchronous=NORMAL` l'écriture tombe à 0,95 ms. `_schema_ready` mémoïse les migrations au lieu de les rejouer à chaque appel (un chemin de lecture prenait un verrou d'écriture), et `_ensure_schema` interroge `_table_columns` au lieu d'avaler `OperationalError` — un volume en lecture seule ou un disque plein ressortait en 500 sans explication. Commitez une migration réussie, sinon elle se rejoue indéfiniment.

#### G. Les DTO Kavita sont des remplacements totaux — réinjecter, jamais supposer

Lire `kavita_api.md` d'abord, puis tenir ceci :

* `UpdateChapterDto` **et** `UpdateSeriesDto` remplacent l'entité. Une clé absente du corps JSON arrive en `null` côté .NET et s'écrit `0` / vide. Omettre le seul `sortOrder` détruit l'ordre de lecture d'une série.
* `SERIES_EXTERNAL_ID_KEYS` (`aniListId`, `malId`, `hardcoverId`, `metronId`, `comicVineId`, `mangaBakaId`, `cbrId`) doit être réinjecté par **tout** payload envoyé à `POST /api/Series/update`, y compris celui qui ne prétend toucher qu'aux verrous. `series_external_ids(current)` le fait depuis l'état lu.
* `Format` / `FormatLocked` **n'a jamais existé** dans `UpdateSeriesDto` (vérifié de la 0.5.0 à la 0.9.0.20 ; `SeriesDto.Format` est un `MangaFormat` déduit du type de fichier, sans rapport). Ne le remettez pas : l'écriture était morte depuis le premier jour, et elle coûtait une lecture et deux écritures par série. `resolve_kavita_format_enum` ne survit que pour l'affichage UI.
* Types de bibliothèque : Kavita nomme `Comic = 1` « Comic (Flexible) » et `ComicVine = 5` « Comic ». `kavita_constants.LIBRARY_TYPE_BY_ENUM` est la seule correspondance fiable — elle range aussi `Image` avec les mangas et `LightNovel` avec les livres.
* Scellement des verrous : passez les `lock_keys` de `lock_keys_from_payload(...)` sur les chemins automatiques, pour que le seal ne ferme que ce qui a été écrit. Les chemins manuels (bouton 🔒, `/api/series/<id>/seal-locks`) gardent volontairement le seal large, gardé par `_has_content` — voir `ROADMAP.md` B4 pour le pourquoi.
* L'écriture d'un chapitre ne consulte **aucun** verrou côté Kavita. Le comblement doit donc être imposé côté client (`filter_people_payload`), sinon une collection de crédits verrouillée est remplacée et Kavita répond 200.
* Passes longues : `_send` rejoue l'authentification une fois sur 401 (un jeton vit trois jours, une passe de bibliothèque peut durer plus). Les couvertures sont mesurées et leur type vérifié avant l'envoi (`_download_cover_base64`) : le base64 gonfle d'un tiers, et un hébergeur autorisé peut répondre une page d'erreur HTML sous un 200.

#### H. Les doublons de l'Inventaire sont un script, pas un delete Kavita (C85)

`DELETE /api/Series/{id}` n'enlève que la fiche. Les fichiers restent ; le scan suivant recrée la série. Meta ne monte pas les médias Kavita et ne doit pas se souvenir des suppressions pendant que Kavita remet les fichiers. Donc :

* Pas de bouton Supprimer et pas de `POST /api/series/<id>/kavita-delete`. Ne les remettez pas. `KavitaAPI.delete_series` a disparu pour la même raison.
* `POST /api/libraries/<library_id>/duplicates/script` ne rend que du texte. Meta n'exécute jamais le script.
* Le préfixe est un chemin POSIX (`INVENTORY_FOLDER_PATH_PREFIX`, `resolve_script_folder_path` dans `services/library_audit/dup_script.py`), pas une URL HTTP. Kavita peut renvoyer `/comics/X` alors que le disque est `/mnt/media/comics/X` — le préfixe est `/mnt/media`. Un `http://` est refusé. L'ancien `INVENTORY_FOLDER_URL_PREFIX` n'est migré que s'il est déjà un chemin, puis retiré.
* Le préfixe et la corbeille vivent dans le pied de la modale Doublons, pas dans la barre latérale de configuration.
* L'UI garde au moins une série décochée par groupe (`_enforceDupKeepOne` dans `library_audit.js`). Un membre sans chemin de dossier compte comme un garder implicite. Ignorer un groupe (`keepBody: true`) ne doit pas effacer les cases Jeter des groupes qui restent.
* Les exemples restent génériques (`/mnt/media`, `/comics/X`). Pas d'IP LAN ni de nom de disque hôte dans un texte visible.
* Tests : `tests/test_dup_folder_script.py`.

### 16. `CHANGELOG.md` est une source de données, pas seulement un fichier (C82)

La modale **Nouveautés** est `CHANGELOG.md` rendu par `services/changelog_service.py`, injecté en `innerHTML`. Ce rendu n'est volontairement **pas** un convertisseur markdown générique : il reconstruit la structure du fichier — version, sections, entrées — parce que c'est cette structure qui rend un fichier de mille lignes lisible dans une modale de 820 px. Le fichier a donc une grammaire, et s'en écarter dégrade la modale en silence.

* `## [1.7.0] - 2026-08-13 (titre court)` ouvre une version. Numéro, date et titre sont lus séparément ; le titre entre parenthèses est facultatif.
* `EN` / `FR` seul sur sa ligne ouvre un bloc de langue (un `🇫🇷` seul est accepté pour les anciennes versions qui l'employaient). Ce qui précède le premier marqueur appartient aux deux langues. **Seule la langue demandée est rendue**, `UI_LANG` décidant, avec un repli sur tout le contenu quand une version n'a pas le bloc voulu — un paragraphe anglais vaut mieux qu'une version vide.
* `### ✨ Libellé` ouvre une section, et l'émoji de tête la **type** : couleur, pictogramme et compteur viennent de `_SECTION_KINDS` (`warn`, `new`, `fix`, `security`, `limits`, sinon `plain`), avec un repli par mot-clé pour les versions écrites avant la convention. Le pictogramme est résolu dans le sprite commun : un nouveau type exige son `<symbol>` dans `_icons_sprite.html`, car `<use href="#absent">` ne dessine rien et ne signale rien.
* `* **C69. Titre** — corps` est une entrée. Le titre est le **gras de tête, et il ne peut pas contenir `**`** : le motif est ancré et non gourmand pour cette raison, un gras qui s'étendrait plus loin avalant sinon la moitié de l'entrée. `—`, `:` ou rien du tout sont acceptés comme séparateur. Un préfixe `C\d+` / `BF\d+` devient la pastille que l'on peut citer dans une issue. Les sous-puces s'indentent de deux espaces exactement et restent imbriquées.
* Une queue `Tests : \`tests/x.py\`` est **retirée du rendu et conservée dans le fichier** : elle s'adresse au mainteneur, et celui qui lit les notes de version n'en a rien à faire. Une sous-puce qui ne dit que cela disparaît entièrement.
* `_format_inline_markdown` échappe **avant** d'habiller, et les liens n'acceptent que `http(s)`. Ne réordonnez pas : le fichier cite `<script>`, et une seule occurrence non échappée tronque tout le reste de la modale dans le navigateur.

Deux règles éditoriales vont avec, et `tests/test_changelog_render.py` échoue sur les deux. **Les nouveautés passent avant les correctifs**, dans les deux langues, et les deux langues portent exactement les mêmes codes d'entrée — une version qui ne dit pas la même chose selon la langue de l'interface est pire qu'une version qui en dit moins. Et **un bug introduit puis corrigé dans la version qui le livre n'a aucun lecteur** : personne n'a exécuté ce code, il n'a donc rien à faire dans les notes. Sa place est à la section 15 ci-dessus, où l'invariant qu'il a produit mérite d'être gardé. Les itérations d'une fonctionnalité pas encore publiée suivent la même règle : elles sont fondues dans l'entrée de la fonctionnalité au lieu d'en raconter l'historique.

Le même raisonnement s'applique un cran au-dessus, à une version entière. **Une version préparée mais jamais publiée n'a pas de titre à elle** : elle est fondue dans celle qui la livre réellement, et sa ligne `## [x]` disparaît. La 1.6.6 en est le précédent — restée sur `dev`, la 1.7.0 est sortie à sa place et porte donc son Inventaire, sa passe de modales et ses correctifs, moins ceux qui ne réparaient que du code propre à la 1.6.6. Un paragraphe de tête dans **Avant de mettre à jour** dit depuis quelle version les notes sont comptées, parce que c'est la seule chose dont un lecteur a besoin pour savoir si une section aussi longue le concerne. Tout ce qui, hors de `CHANGELOG.md`, datait une fonctionnalité par ce numéro — les titres du `README.md`, les étiquettes `(vx.y.z)` du `ROADMAP.md`, le plancher serveur du Companion — est renuméroté dans la même passe : `get_app_version()` lit le premier titre de ce fichier, et un numéro périmé ailleurs est un mensonge de documentation que le code ne peut pas démentir.