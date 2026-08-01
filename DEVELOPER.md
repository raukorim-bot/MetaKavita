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

---

## 🇺🇸 English Developer Guide

### 1. Global Architecture & Security
MetaKavita is an asynchronous Python application powered by a **Gunicorn WSGI server** with **Eventlet** workers to support real-time WebSockets via Flask-SocketIO.

*   **Security Layer:** Global authentication is enforced via `@app.before_request` (`auth_manager.setup_gate` then `login_gate` / `is_authenticated`) and the Socket.IO `connect` handler (`return False` if unauthenticated — Flask-SocketIO's documented reject form; per-event `_reject_unauthenticated` as defense in depth). **Fail-closed** — including when the DB is unreadable (deny, never fall through to an open UI). Account system lives in `auth_manager.py` + `users` table (Werkzeug hash method pinned `pbkdf2:sha256`); first-run `/setup`; optional `ADMIN_PASSWORD_HASH` + `ADMIN_USERNAME` seeding via `debug/hash_password.py` (hash-shape validated; ignored once any account exists). Per-IP lockout (5/15min) plus global backstop (20/15min) against `X-Forwarded-For` rotation (in-memory — sound under `gunicorn -w 1`); timing equalization uses one memoized dummy KDF. Legacy `ADMIN_PASSWORD` in `config.json` is a one-shot ownership proof on `/setup`, then purged — never adopted as the new password. Session cookies are `HttpOnly` + `SameSite=Lax` (optional `SESSION_COOKIE_SECURE=1` behind HTTPS), lifetime 7 days. CSRF tokens (`csrf_utils.py`) on state-changing POSTs; frontend injects `X-CSRF-Token`. `SECRET_KEY` is generated on first boot — never a public hardcoded fallback.
*   **Password change (Config modal):** `POST /account/password` (`routes/auth.py`, `auth_manager.update_password`) re-verifies `current_password` through the same `verify_credentials()` path as `/login` before hashing the new one — an open tab is not exempt from proving the current password. A wrong `current_password` counts as a failed login attempt (`register_failed_attempt`) and is subject to the same per-IP lockout, so the route cannot become a brute-force oracle that bypasses `/login`'s throttling. Three unnamed `<input>` fields in `_config_modal.html` (no `name` attribute) keep this call out of the big `saveConfig()` `FormData` POST to `/save-config`.
*   **SSRF Protection:** Shared allowlist helper (`url_allowlist.py`) for cover downloads and `/api/proxy-image` — http(s) only, no credentials/localhost/private IPs, up to 3 redirects with each hop re-validated (`fetch_with_safe_redirects`), safe `image/*` MIME. Domain lists come from `ScraperRegistry.get_all_proxy_domains()` (covers community scrapers too). `/api/proxy-image` streams with a **5 MB** hard cap (`413`).
*   **Credential-safe logging:** Use `secure_logging.safe_exc_str()` / `redact_secrets()` when logging exceptions that may include authenticated URLs (Kavita `apiKey`, ComicVine `api_key`, etc.) — never log raw `str(e)` after such calls.
*   **Webhook Hardening:** Webhooks require a cryptographically secure `WEBHOOK_TOKEN` generated in `data/config.json` (CSRF-exempt; token auth only). Prefer `X-Webhook-Token`; `?token=` still works (legacy / deprecated, BF63) — query strings leak into proxy logs / Referer. Config UI shows base `/webhook` + separate token field.
*   **Liveness `/healthz`:** `GET /healthz` → `{status, version}` only. Whitelisted in both setup/login gates (`misc.healthz`); touches **no** config, DB, or Kavita. Dockerfile `HEALTHCHECK` requires **strict HTTP 200** on this route (not a lax `/login` probe).
*   **Non-root Docker (C54):** Image user `metakavita` (default 1000:1000); entrypoint applies `PUID`/`PGID` then `gosu`. `save_config()` writes `config.json` **0600**.
*   **Safe SQLite Schema Migrations:** Database updates in `db_manager.py` use a safe `_ensure_schema` / `_ensure_pending_reviews_table` path that handles `sqlite3.OperationalError` gracefully, preventing fatal container crashes when introducing new features. All connections go through `_connect()` with **WAL** journal mode and a **30s busy_timeout** to reduce `database is locked` under concurrent worker + REST + Socket.IO writes.
*   **Pure Base64 Kavita Uploads:** Kavita requires cover uploads to be sent as pure Base64 byte strings (`kavita_api.py`). Prepending `Data URI` schemas (`data:image/jpeg;base64,...`) results in silent Kavita C# backend failures (the "Phantom Cover" syndrome).

---

### 2. High-Speed Throttling & Rate-Limiting Architecture
MetaKavita eliminates hardcoded thread sleep delays in favor of a **Timestamp-Based Dynamic Throttler** (`LAST_REQUEST_TIMES`).
Idle APIs respond instantly with zero artificial delay, executing 3-provider Smart Fusions in ~1.6s. High-volume batch requests throttle each scraper strictly according to its declared `rate_limit` (e.g., 0.2s for MangaBaka, 1.0s for AniList) at maximum theoretical throughput, providing immunity against HTTP 429 errors.

---

### 3. Reverse Proxy, Subpath & CORS Architecture
MetaKavita natively supports deployment under custom URL subpaths (e.g. `https://domain.com/metakavita`).
Reverse proxy headers (`X-Forwarded-Prefix`, `X-Forwarded-For`, …) are processed via Werkzeug's `ProxyFix`. **`TRUSTED_PROXY_COUNT`** (default `1`) drives both ProxyFix hop count and the client IP used for lockout — set **`0`** if the instance is exposed directly (otherwise an attacker can rotate `X-Forwarded-For` and evade the per-IP lockout; the global 20/15min backstop still applies). In addition, if a user specifies an explicit subpath using the `ROOT_PATH` environment variable in Docker, a custom `ScriptNameStripper` WSGI middleware handles path rewriting. Client-side, `window.ROOT_PATH` dynamically prefixes all AJAX calls.

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
| `static/js/manual_review.js` + `_manual_review_modal.html` | Modal: pick / edit / **cover** / recap, fusion checkboxes, keyboard dock, queue sync |

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
   candidate, then sorts them by score descending before picking a winner. **Tie-break (BF68):**
   equal scores → prefer non-explicit-adult (`age_rating` not `pornographic`/`erotica`), then
   original fallback-list position. Auto logs `log_tiebreak_prefer_safe` when that NSFW demotion
   fires. A single adult winner is unchanged. Manual Review `return_candidates` keeps a **neutral**
   sort (all cards, no NSFW demotion). Confirm-before-write + score tie → `awaiting_pick` (not
   silent confirm). If `SMART_COMPLETION` is enabled, gap-filling follows this same sorted order —
   the most trustworthy candidate's fields win a "which value fills this gap" contest, not the one
   that merely happened to run first. A candidate with no `_match_score` (e.g. a community scraper
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
| `BEDETHEQUE` | Bédéthèque | Comic | Franco-Belgian BD scraper, `curl_cffi` CSRF bypass. |
| `BDTHEQUE` | BDTheque.com | Comic | Franco-Belgian BD (bdtheque.com, **not** bedetheque). AJAX search + series page; Magic Input `/series/{id}/{slug}`; covers via `data-echo`. |
| `COMICVINE` | ComicVine | Comic | API Key required. Primary publisher weighting, Issue #1 fallback. |
| `GOOGLEBOOKS` | Google Books | Book, Comic | API Key required. Dynamic `langRestrict`, ISBN targeting. |
| `HARDCOVER` | Hardcover (Exp) | Book, Comic | API Key required. Hasura GraphQL API & Typesense search. |
| `KITSU` | Kitsu | Manga | JSON:API integration, no API key required. |
| `MANGANEWS` | Manga-News | Manga | VF French catalog scraper, extracts HD webp covers. |
| `MANGABAKA` | MangaBaka | Manga, Book | `schema=full`, `type` filter (novel for Book), Publisher Preference support. |
| `MANGADEX` | MangaDex | Manga | Content rating filters (`erotica`), oneshot penalties. |
| `MANGAUPDATES`| MangaUpdates | Manga | `hit_title` matching, Publisher Preference support. |
| `OPENLIBRARY` | Open Library | Book, Comic | ISBN support, anti-429 retries, Google Disclaimer bypass. |
| `MAL` | MyAnimeList | Manga, Book | Official API v2 + `X-MAL-CLIENT-ID` (`MAL_API_KEY` = Client ID; no user OAuth). Magic Input `myanimelist.net/manga/{id}`. |
| `SHIKIMORI` | Shikimori | Manga | Multilingual title matching, `/roles` staff extraction. |
| `WIKIDATA` | Wikidata | Manga, Comic, Book | **Live only** (SPARQL + Entity API) — no offline dump/SQLite mode yet. Magic Input Q-id; shared `wikidata_map`. Best as fallback / ISBN / cross-IDs. |

#### Comic Flexible (C35)
Kavita library type **ID 5** normalizes to `ComicFlexible` (`kavita_api._normalize_library_type`) — it is **not** flattened to Comic. Enrichment runs `COMIC_PROVIDER_*` first, then falls back to Manga `PROVIDER_*` when no useful hit is found. Manual cover search unions Comic + Manga scrapers. Tests: `tests/test_comic_flexible.py`, `tests/test_library_type_normalize.py`.

**Run-year hygiene (BF54 / v1.6.2)** — Flexible series names often carry `(YYYY)` / `(YYYY-)` to distinguish comic runs. Comic `clean_title` strips those parens from the **search string** (they used to stay and poison ComicVine `name:` filters). `extract_year_from_title` / `apply_title_year_hint` in `scrapers/utils.py` copy the year into `existing_metadata` before the Comic wave; ComicVine boosts matching `start_year`. The Manga fallback is **not** confidence-penalized — Flexible libs may hold both comics and manga.

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

1. **Never send a partial payload to `POST /api/Series/update`.** Kavita's `SeriesController`/`UpdateSeriesDto` has **no null-guard** on several fields — `localizedName` in particular. If your update logic only intends to change `format`, but omits `localizedName` from the JSON body, Kavita's C# backend deserializes the missing key as `null`, **overwrites** the existing value in the database, and additionally **resets** `nameLocked` / `sortNameLocked` / `localizedNameLocked` to `false` — even though those fields were never meant to be touched. This exact regression silently corrupted alternate titles for real users and crashed a third-party OPDS client (KOReader's "Kamare" plugin), which assumed `localizedName` would always be a string and choked on the resulting `null`. **The mandatory fix pattern:** always `GET /api/Series/{id}` first, merge your intended change into the *complete* current state, and only then `POST` the full object back. See `KavitaAPI.update_series_general()` for the reference implementation of this GET-merge-POST pattern.
2. **Sanitize GET-only / computed fields before every `POST`.** Properties like `created`, `lastModified`, `totalCount`, `maxCount`, `pages`, and `wordCount` are returned by Kavita's `GET` endpoints but must never be echoed back in a `POST` body — doing so risks triggering Entity Framework Core concurrency exceptions server-side. This sanitization is centralized **once** inside `KavitaAPI.update_series_metadata()`. Do not re-implement a partial version of it ad-hoc in `app.py` or inside a scraper — that exact kind of duplication (only stripping `created`/`lastModified` in one place while forgetting `maxCount`/`totalCount`) is how a `maxCount: -100000` payload once reached Kavita and crashed a sync.
3. **Respect the 2-pass Lock Guard protocol** (`Unlock → Write → Lock`, documented in `kavita_api.md` §1.B/1.C) whenever your code needs to overwrite a field the user may have manually locked in Kavita's UI. Soft-success on re-lock failure must surface as `NEEDS_RELOCK` + `seal_series_locks`, not silent `COMPLETED`.
4. **Soft atomicity for general fields (BF67).** `apply_kavita_payload()` calls `update_series_general` (localized name / format) **only when** `update_series_metadata` succeeded. A metadata failure must not still write general fields (that was the #24 failure mode: UNIQUE tag reject + `localizedName` still applied).

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

#### F. Documentation Is Part of the Change
Every user-facing fix or feature must be reflected in **both** `CHANGELOG.md` (bilingual EN/FR, semantically versioned — the topmost `## [X.Y.Z]` header is parsed automatically by `services/changelog_service.py::get_app_version()` to drive the version number shown in the UI) and `ROADMAP.md` (bilingual short-form `BFxx`/`Cxx` entries). Keep the two in sync: every `BF`/`C` number referenced in `ROADMAP.md`'s "Latest Releases" section should correspond to a detailed entry in `CHANGELOG.md`, and the version range shown at the top of that section should always match the newest `CHANGELOG.md` entry.

### 12. Modular Architecture (Post-Refactor Module Map)
Starting with the architecture refactor, `app.py` is a thin ~130-line assembly point only: Flask/SocketIO instantiation, middlewares (`ProxyFix`, `ScriptNameStripper`), logging bootstrap, the global `require_login` gate, Blueprint registration, and starting the background workers. All business logic lives in dedicated modules:

*   **`kavita_constants.py`**: single source of truth for Kavita enum mappings (`PUBLICATION_STATUS_MAP`, `AGE_RATING_MAP`, `resolve_kavita_format_enum()`) and raw-provider-status normalization (`normalize_provider_status()`, used by `scrapers/mangabaka.py`). Add new enum mappings here, never inline in a route or scraper.
    *   **`AGE_RATING_MAP` (BF53 / v1.6.2)** — scrapers emit the internal strings `safe` / `suggestive` / `erotica` / `pornographic` (MangaDex-shaped vocabulary). **Only this dict** converts them to Kavita's real `AgeRating` integers (`GET /api/metadata/age-ratings` / `AgeRating.cs`): `safe→3` (Everyone), `suggestive→8` (Teen), `erotica→12` (R18+), `pornographic→14` (X18+). Do **not** map 1–4 — those are MangaDex content-rating ordinals and collide with Kavita's Rating Pending / Early Childhood / G. `services/kavita_payload.py` writes the mapped int and sets `ageRatingLocked=True`. Source of truth for the enum table: `kavita_api.md` §3.B. Regression guard: `tests/test_age_rating_map.py`.
    *   **Age safeguarding (BF56 / v1.6.2)** — never invent `safe` when the provider has no age signal (omit the field so SMART_COMPLETION cannot hole-fill Everyone onto a primary match and lock it). Prefer omit over under-rate. Authoritative mappings only: MAL `nsfw`, MangaDex `contentRating`, Kitsu `ageRating`, Manga-News `#agenumber`, Google Books `maturityRating=MATURE` → `erotica`, AniList only when `isAdult`, BDTheque `_parse_age` (Adulte/Érotique → `erotica`; « Ados - Adultes » → `suggestive`). Guard: `tests/test_age_safeguarding_bf56.py`.
*   **`models.py`**: `SeriesOverride` dataclass, the typed contract for per-series overrides (forced ID/provider, alternative title, targeted fields, publisher preference, `alt_title_langs`). Persist via `db_manager.save_series_override(SeriesOverride(...))` (named fields) — the legacy positional `save_forced_overrides(...)` wrapper was removed. This is a direct, structural mitigation for the class of bug described in §11.C.
*   **`extensions.py`**: the shared `socketio = SocketIO()` instance (created without an app, `init_app(app)`'d once in `app.py`). Import from here — never from `app.py` — in any module that needs to emit events or declare `@socketio.on(...)` handlers, to avoid circular imports.
*   **`auth_manager.py`**: account CRUD, Werkzeug hashing (`pbkdf2:sha256`), per-IP + global lockout, legacy `/setup` ownership proof, `ADMIN_PASSWORD_HASH` / `ADMIN_USERNAME` seeding, `TRUSTED_PROXY_COUNT`, session helpers, `setup_gate` / `login_gate`. Fail-closed; never import plaintext `ADMIN_PASSWORD` as the new password.
*   **`config_manager.py`**: `load_config()` / `save_config()` — env merge **before** first-write secrets (BF51); precedence `config.json` > env > default; `config.json` mode 0600.
*   **`services/enrichment_engine.py`**: `enrich_series(series_id, series_name, force_update, targeted_fields_override=None)`, the extracted former `process_series_logic()`. Pure orchestration — scraping, field mapping, Kavita calls, lifetime telemetry broadcast — with zero dependency on Flask or `app.py`. Also hosts Manual Review apply/preview/research paths (C29) and `seal_series_locks` (`NEEDS_RELOCK`). Comic Flexible cascade lives here.
*   **`services/manual_review.py`**: C29 park helpers — `create_review_from_candidates` / `create_confirm_from_auto` (both accept an optional `library_id`, used to build the Kavita verification link — §4.H), `choice_and_merge`, skip/confirm/purge emitters, pre-pick summary translation. Persistence goes through `db_manager.park_pending_review` / `close_pending_review` (atomic).
*   **`services/background_tasks.py`**: the daemon workers (`sync_queue` consumer + periodic auto-sync poller) and `start_background_workers()`, called once from `app.py` at import time (unchanged single-worker-process behavior, required for Gunicorn `-w 1`). Queue items are **dicts** built by `make_sync_item(series_id, series_name, force_update, fields_override=None, is_batch=False)` — no longer 3-/4-tuples. `is_batch` drives the dedicated `_batch_total`/`_batch_done`/`_batch_real_sends` progress counters (§4.F); auto-sync skips `PENDING_REVIEW` and filters candidate libraries through `select_auto_sync_candidates()` — the **only** place `DISABLED_LIBRARIES` applies (§4.J).
*   **`services/stats_service.py`**: playful `/stats` metrics + Chart.js payload from lifetime counters + cache snapshot + Manual Review achievements (`mr_achievements.py`). Gated by `ENABLE_PLAYFUL_STATS`.
*   **`services/changelog_service.py`**: `get_app_version()` / `get_current_version()` (cached) / `get_full_changelog_html()`. Imported independently by both `app.py` (global template context) and `routes/misc.py` (`/api/changelog`) — importing from here instead of from each other avoids a circular import.
*   **`routes/*.py`**: one Flask Blueprint per domain — `auth` (`/setup`, `/login`, `/logout`, `/account/password`), `pages` (`/`, `/stats`), `config` (`/save-config`, `/regenerate-webhook-token`), `series` (`/save-override`, `/toggle-ignore`, cover search/apply, `POST …/seal-locks`, `POST …/seal-locks-pending`), `sync` (`/force-sync`, `/batch-sync` [inventory cached per batch, see `_get_batch_inventory` §4.F], `/stop-batch`, `/reset-errors`, `/export-errors`, `/webhook`), `manual_review` (`/api/manual-reviews…` incl. `POST …/bulk-accept`), `misc` (`/healthz`, `/api/proxy-image`, `/api/changelog`).
*   **`sockets/handlers.py`**: Socket.IO handlers (`connect`, `fetch_covers_stream`), registered on `extensions.socketio`; imported once for side effects from `app.py`. Unauthenticated `connect` → `return False`; successful connect emits `manual_review_pending_count` / `manual_review_queue_summary` **to the connecting `sid` only**.
*   **`static/js/*.js`**: the former monolithic `script.js` is now plain `<script>` files loaded in dependency order (`utils.js` → `websocket.js` → `overrides.js` → `covers.js` → `config.js` → `batch.js` → `manual_review.js` → `license_nag.js` → `main.js`). No bundler and no `type="module"` on purpose: templates rely on inline `onclick="..."` handlers, which require every function to stay in the global scope.
*   **`templates/partials/*.html`**: the former monolithic `index.html` is now a thin shell that `{% include %}`s Jinja partials — including `_manual_review_modal.html` for C29 — one per self-contained UI region. Edit the relevant partial directly instead of scrolling through a single 600+ line template.
*   **`tests/`**: the pytest safety net (`conftest.py` fixtures + domain tests such as `test_auth.py`, `test_healthz.py`, `test_config_env_seeding.py`, `test_db_manager.py`, `test_kavita_api.py`, `test_playful_stats.py`, `test_manual_review.py`, `test_manual_review_bulk_accept.py`, `test_manual_review_queue_api.py`, `test_needs_relock.py`, `test_batch_inventory_cache.py`, `test_batch_progress_isolation.py`, `test_dashboard_renders.py`, `test_supporter_nag_policy.py`, `test_batch_targeted_fields.py`, `test_comic_flexible.py`, `test_scraper_mangabaka.py`, `test_routes_series.py`, `test_max_tags.py`, `test_max_genres.py`, `test_scraper_max_caps.py`, `test_audit_c1_c3.py`, `test_fallback_query.py`, `test_metadata_fetcher_smart_scoring.py`, …). Fixtures never touch the real `data/` folder or the network — `isolated_db` monkeypatches `db_manager.DB_FILE`/`DATA_DIR` to a `tmp_path` SQLite file, `flask_app`/`client` build a minimal Flask app registering only `routes/series.py` (not the full `app.py`, to avoid spinning up real background workers/logging), and `mock_kavita_api` stubs out every `KavitaAPI` network method. See §10. Also note shared helpers: `url_allowlist.py`, `csrf_utils.py`, `cors_config.py`.

⚠️ **Blueprint endpoint names changed.** Flask always prefixes a Blueprint route's endpoint with the Blueprint's name (e.g. the `login` view in `routes/auth.py`, registered on the `auth` Blueprint, becomes endpoint `auth.login` — there is no way to opt out of this prefixing). Every `url_for(...)` call and the whitelist in `auth_manager.setup_gate` / `login_gate` were updated accordingly (`auth.setup`, `auth.login`, `auth.logout`, `pages.index`, `pages.stats`, `misc.healthz`, `sync.export_errors`, `sync.webhook`). **If you rename a Blueprint or move a route to a different Blueprint, grep for its old endpoint string across `auth_manager.py`, `app.py` and every `.html` template before assuming `url_for()` still resolves.**

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
Les pauses fixes ont été remplacées par un **Régulateur Dynamique par Horodatage (`LAST_REQUEST_TIMES`)**. Les API inactives répondent à 0.0s de délai, exécutant une fusion de 3 sources en ~1,6s. Lors d'un batch, le système régule parfaitement chaque source à sa vitesse maximale théorique (`rate_limit`).

---

### 3. Architecture Reverse Proxy, Sous-dossiers & CORS
Le système gère les sous-chemins (ex: `https://domaine.com/metakavita`) via `ProxyFix` pour les headers `X-Forwarded-Prefix`, `X-Forwarded-For`, … **`TRUSTED_PROXY_COUNT`** (défaut `1`) pilote à la fois le hop count de ProxyFix et l’IP client utilisée pour le verrouillage — mettre **`0`** si l’instance est exposée directement (sinon un attaquant peut faire tourner `X-Forwarded-For` et contourner le verrouillage par IP ; le plafond global 20/15 min s’applique toujours). Un middleware `ScriptNameStripper` gère `ROOT_PATH`. Côté frontend, `window.ROOT_PATH` préfixe toutes les routes.

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
| `static/js/manual_review.js` + `_manual_review_modal.html` | Modale pick / edit / **cover** / recap, fusion, dock clavier, sync file |

**Règles d’intégrité (ne pas régresser) :**
* Une seule ligne par `series_id` — un re-park remplace, n’empile jamais.
* Le batch global (`routes/sync.py` sans sélection) exclut `PENDING_REVIEW` ; l’auto-sync le faisait déjà.
* Le court-circuit « déjà à jour » ne doit pas clobber `PENDING_REVIEW` ; sur `NEEDS_RELOCK` tenter seal seul puis COMPLETED ; le chemin COMPLETED purge les orphelins.
* Écriture OK + re-lock échoué → `NEEDS_RELOCK` (orange), pas un simple `COMPLETED` ; seal via retry différé ou `POST /api/series/<id>/seal-locks` (+ bulk pending).
* Désactiver `MANUAL_REVIEW_MODE` purge la file (`routes/config.py`).
* Ignore et `clean_orphaned_cache` effacent les reviews de la série.
* Frontend : sérialiser `loadQueue`, ancrer sur `currentReviewId`, gardes in-flight ; gérer `manual_review_confirmed` / `_skipped` / `_refreshed` / compteur→0.
* **Vider la file pendant qu'un batch tourne encore affiche le masque d'attente, pas le récap (hotfix v1.6.1)** — `showRecapIfEmpty()` vérifie le global `batchProgressTotal` (`batch.js`) avant de basculer sur `recap` ; si un batch est encore actif, elle bascule sur la phase `waiting` déjà existante, et le chemin déjà câblé `mrOnBatchProgress()` → `settleWaitingAfterWork()` prend le relais une fois le batch réellement terminé (ou affiche d'abord la prochaine review garée). Sans ça, une file vide en plein batch affichait le récap quelques secondes avant que la série suivante scrapée ne ramène brutalement la modale sur `pick`. Garde `phase !== "waiting"` pour ne pas se réappliquer sur l'appel qui sort déjà de `waiting` (`batchProgressTotal` ne retombe à 0 qu'~1,5 s après la fin réelle — voir `applyBatchProgressPayload()`).

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
   décroissant avant de désigner un vainqueur. **Départage (BF68) :** scores égaux → préférence
   non-adulte explicite (`age_rating` hors `pornographic`/`erotica`), puis position d'origine
   dans la liste de fallback. Auto journalise `log_tiebreak_prefer_safe` quand cette démotion
   NSFW s'applique. Un seul vainqueur adulte n'est pas modifié. Manual Review `return_candidates`
   garde un tri **neutre** (toutes les cartes, pas de démotion NSFW). Confirm-before-write +
   égalité de score → `awaiting_pick` (pas de confirm silencieux). Si `SMART_COMPLETION` est
   activé, le remplissage des champs manquants suit ce même ordre trié : c'est le candidat le
   plus digne de confiance qui gagne le droit de combler un champ vide, pas celui qui se
   trouvait juste être exécuté en premier. Un candidat sans `_match_score` (ex : scraper
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
| `BEDETHEQUE` | Bédéthèque | Comic | Contournement CSRF `curl_cffi`, match exact de séries franco-belges. |
| `BDTHEQUE` | BDTheque.com | Comic | BD franco-belge (bdtheque.com, **pas** bedetheque). Recherche AJAX + parse fiche ; Magic Input `/series/{id}/{slug}` ; covers via `data-echo`. |
| `COMICVINE` | ComicVine | Comic | API Key. Recherche `filter=name:`, priorisation des éditeurs majeurs. |
| `GOOGLEBOOKS` | Google Books | Book, Comic | API Key. Replis dynamiques par langue (`langRestrict`), ISBN. |
| `HARDCOVER` | Hardcover (Exp) | Book, Comic | API Key. GraphQL Hasura + Moteur Typesense. |
| `KITSU` | Kitsu | Manga | JSON:API, rapide, sans clé requise. |
| `MANGANEWS` | Manga-News | Manga | Catalogue VF, extrait l'éditeur FR et les visuels HD (webp). |
| `MANGABAKA` | MangaBaka | Manga, Book | Manga + Book ; `schema=full`, filtre `type`, Préférence d'Éditeur. |
| `MANGADEX` | MangaDex | Manga | Filtres adultes (`erotica`), pénalités Oneshot. |
| `MANGAUPDATES`| MangaUpdates | Manga | Scraping par `hit_title`, support de la Préférence d'Éditeur. |
| `OPENLIBRARY` | Open Library | Book, Comic | Clés Work (`OL...W`) & ISBNs, contournement Disclaimer Google Books. |
| `MAL` | MyAnimeList | Manga, Book | API officielle v2 + `X-MAL-CLIENT-ID` (`MAL_API_KEY` = Client ID ; pas d’OAuth utilisateur). Magic Input `myanimelist.net/manga/{id}`. |
| `SHIKIMORI` | Shikimori | Manga | API Multilingue, extraction `/roles` du staff. |
| `WIKIDATA` | Wikidata | Manga, Comic, Book | **Live uniquement** (SPARQL + Entity API) — pas de mode dump/SQLite hors-ligne pour l’instant. Magic Input Q-id ; `wikidata_map`. Idéal en fallback / ISBN / IDs croisés. |

#### Comic Flexible (C35)
Le type de bibliothèque Kavita **ID 5** se normalise en `ComicFlexible` (`kavita_api._normalize_library_type`) — **pas** aplati en Comic. L’enrichissement lance d’abord `COMIC_PROVIDER_*`, puis bascule sur les `PROVIDER_*` Manga si aucun hit utile. La recherche manuelle de couvertures unionne Comic + Manga. Tests : `tests/test_comic_flexible.py`, `tests/test_library_type_normalize.py`.

**Hygiène année de run (BF54 / v1.6.2)** — les noms Flexible portent souvent `(YYYY)` / `(YYYY-)` pour distinguer les runs comics. `clean_title` Comic retire ces parenthèses de la **query** (elles restaient et empoisonnaient les filtres `name:` ComicVine). `extract_year_from_title` / `apply_title_year_hint` dans `scrapers/utils.py` recopient l'année dans `existing_metadata` avant la vague Comic ; ComicVine booste le `start_year` correspondant. Le fallback Manga **n'est pas** pénalisé en confiance — une lib Flexible peut contenir comics et mangas.

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

1. **Ne jamais envoyer de payload partiel à `POST /api/Series/update`.** Le `SeriesController`/`UpdateSeriesDto` de Kavita n'a **aucune protection contre les valeurs nulles** sur plusieurs champs — notamment `localizedName`. Si votre logique de mise à jour ne vise à changer que `format` mais omet `localizedName` du corps JSON, le backend C# de Kavita désérialise la clé manquante en `null`, **écrase** la valeur existante en base, et **réinitialise en plus** `nameLocked` / `sortNameLocked` / `localizedNameLocked` à `false` — alors même que ces champs n'étaient pas censés être touchés. Cette régression exacte a silencieusement corrompu les titres alternatifs d'utilisateurs réels et fait planter un client OPDS tiers (l'extension "Kamare" de KOReader), qui supposait que `localizedName` serait toujours une chaîne de caractères et s'est bloqué sur le `null` résultant. **Le motif de correction obligatoire :** toujours faire un `GET /api/Series/{id}` en premier, fusionner le changement voulu dans l'état actuel *complet*, puis seulement ensuite renvoyer l'objet entier en `POST`. Voir `KavitaAPI.update_series_general()` pour l'implémentation de référence de ce motif GET-fusion-POST.
2. **Assainir les champs GET-uniquement / calculés avant chaque `POST`.** Des propriétés comme `created`, `lastModified`, `totalCount`, `maxCount`, `pages` et `wordCount` sont renvoyées par les endpoints `GET` de Kavita mais ne doivent jamais être réinjectées dans un corps `POST` — cela risque de déclencher des exceptions de concurrence d'état côté Entity Framework Core. Cet assainissement est centralisé **une seule fois** dans `KavitaAPI.update_series_metadata()`. Ne réimplémentez pas une version partielle de cette logique dans `app.py` ou dans un scraper — c'est exactement ce type de duplication (ne retirer que `created`/`lastModified` à un endroit en oubliant `maxCount`/`totalCount`) qui a un jour laissé passer un payload `maxCount: -100000` vers Kavita et fait planter une synchronisation.
3. **Respecter le protocole de verrouillage à 2 passages** (`Unlock → Write → Lock`, documenté dans `kavita_api.md` §1.B/1.C) chaque fois que votre code doit écraser un champ que l'utilisateur a pu verrouiller manuellement dans l'interface de Kavita. Un soft-success sur échec de re-lock doit remonter en `NEEDS_RELOCK` + `seal_series_locks`, pas en `COMPLETED` silencieux.
4. **Atomicité soft des champs généraux (BF67).** `apply_kavita_payload()` n'appelle `update_series_general` (nom localisé / format) **que si** `update_series_metadata` a réussi. Un échec metadata ne doit plus écrire les champs généraux (mode de panne #24 : rejet UNIQUE des tags + `localizedName` quand même appliqué).

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

#### F. La Documentation Fait Partie du Correctif
Chaque correctif ou fonctionnalité visible par l'utilisateur doit être répercuté à la fois dans `CHANGELOG.md` (bilingue EN/FR, versionné sémantiquement — le premier en-tête `## [X.Y.Z]` est analysé automatiquement par `services/changelog_service.py::get_app_version()` pour piloter le numéro de version affiché dans l'UI) et dans `ROADMAP.md` (entrées courtes bilingues `BFxx`/`Cxx`). Gardez les deux synchronisés : chaque numéro `BF`/`C` référencé dans la section "Dernières Nouveautés" de `ROADMAP.md` doit correspondre à une entrée détaillée dans `CHANGELOG.md`, et la plage de versions affichée en haut de cette section doit toujours correspondre à la plus récente entrée de `CHANGELOG.md`.

### 12. Architecture Modulaire (Plan des Modules Post-Refactor)
Depuis le refactor d'architecture, `app.py` n'est plus qu'un point d'assemblage d'environ 130 lignes : instanciation Flask/SocketIO, middlewares (`ProxyFix`, `ScriptNameStripper`), initialisation du logging, verrou global `require_login`, enregistrement des Blueprints, et démarrage des workers de fond. Toute la logique métier vit désormais dans des modules dédiés :

*   **`kavita_constants.py`** : source unique de vérité pour les mappings d'énumération Kavita (`PUBLICATION_STATUS_MAP`, `AGE_RATING_MAP`, `resolve_kavita_format_enum()`) et la normalisation des statuts bruts fournisseurs (`normalize_provider_status()`, utilisé par `scrapers/mangabaka.py`). Ajoutez tout nouveau mapping ici, jamais en ligne dans une route ou un scraper.
    *   **`AGE_RATING_MAP` (BF53 / v1.6.2)** — les scrapers émettent les chaînes internes `safe` / `suggestive` / `erotica` / `pornographic` (vocabulaire façon MangaDex). **Seul ce dict** les convertit vers les entiers `AgeRating` réels de Kavita (`GET /api/metadata/age-ratings` / `AgeRating.cs`) : `safe→3` (Everyone), `suggestive→8` (Teen), `erotica→12` (R18+), `pornographic→14` (X18+). **Ne pas** mapper en 1–4 — ce sont les ordinaux MangaDex, qui coïncident avec Rating Pending / Early Childhood / G côté Kavita. `services/kavita_payload.py` écrit l'entier mappé et pose `ageRatingLocked=True`. Source de vérité du tableau d'enum : `kavita_api.md` §3.B. Garde-fou : `tests/test_age_rating_map.py`.
    *   **Safeguarding âge (BF56 / v1.6.2)** — ne jamais inventer `safe` sans signal d'âge provider (omettre le champ pour que SMART_COMPLETION ne comble pas Everyone sur un match primaire puis le verrouille). Préférer omettre plutôt qu'under-rater. Mappings autoritatifs uniquement : MAL `nsfw`, MangaDex `contentRating`, Kitsu `ageRating`, Manga-News `#agenumber`, Google Books `maturityRating=MATURE` → `erotica`, AniList seulement si `isAdult`, BDTheque `_parse_age` (Adulte/Érotique → `erotica` ; « Ados - Adultes » → `suggestive`). Garde-fou : `tests/test_age_safeguarding_bf56.py`.
*   **`models.py`** : la dataclass `SeriesOverride`, contrat typé des surcharges par série (ID/provider forcé, titre alternatif, champs ciblés, préférence d'éditeur, `alt_title_langs`). Persistez via `db_manager.save_series_override(SeriesOverride(...))` (champs nommés) — l'ancien wrapper positionnel `save_forced_overrides(...)` a été retiré. C'est une mitigation structurelle directe de la classe de bug décrite au §11.C.
*   **`extensions.py`** : l'instance partagée `socketio = SocketIO()` (créée sans app, `init_app(app)` appelé une seule fois dans `app.py`). Importez-la depuis ce module — jamais depuis `app.py` — dans tout module ayant besoin d'émettre des événements ou de déclarer des handlers `@socketio.on(...)`, pour éviter les imports circulaires.
*   **`auth_manager.py`** : CRUD comptes, hachage Werkzeug (`pbkdf2:sha256`), verrouillage par IP + plafond global, preuve de propriété legacy sur `/setup`, amorçage `ADMIN_PASSWORD_HASH` / `ADMIN_USERNAME`, `TRUSTED_PROXY_COUNT`, helpers de session, `setup_gate` / `login_gate`. Fail-closed ; ne jamais importer un `ADMIN_PASSWORD` en clair comme nouveau mot de passe.
*   **`config_manager.py`** : `load_config()` / `save_config()` — fusion env **avant** la première écriture des secrets (BF51) ; précédence `config.json` > env > défaut ; `config.json` en mode 0600.
*   **`services/enrichment_engine.py`** : `enrich_series(series_id, series_name, force_update, targeted_fields_override=None)`, extraction de l'ancien `process_series_logic()`. Logique d'orchestration pure (scraping, mapping des champs, appels Kavita, broadcast télémétrie lifetime) sans aucune dépendance vers Flask ni `app.py`. Héberge aussi les chemins apply/preview/research de la Review Manuelle (C29) et `seal_series_locks` (`NEEDS_RELOCK`). Cascade Comic Flexible ici.
*   **`services/manual_review.py`** : helpers de park C29 — `create_review_from_candidates` / `create_confirm_from_auto` (acceptent tous les deux un `library_id` optionnel, utilisé pour le lien de vérification Kavita — §4.H), `choice_and_merge`, émetteurs skip/confirm/purge, traduction des résumés avant pick. Persistance via `db_manager.park_pending_review` / `close_pending_review` (atomique).
*   **`services/background_tasks.py`** : les workers démons (consommateur de `sync_queue` + polling d'auto-sync périodique) et `start_background_workers()`, appelé une seule fois par `app.py` au chargement du module (comportement inchangé, requis pour un déploiement Gunicorn à worker unique `-w 1`). Items de file : des **dicts** construits par `make_sync_item(series_id, series_name, force_update, fields_override=None, is_batch=False)` — plus des tuples 3-/4-. `is_batch` pilote les compteurs de progression dédiés `_batch_total`/`_batch_done`/`_batch_real_sends` (§4.F) ; l'auto-sync ignore `PENDING_REVIEW` et filtre ses candidats par bibliothèque via `select_auto_sync_candidates()` — le **seul** endroit où `DISABLED_LIBRARIES` s'applique (§4.J).
*   **`services/stats_service.py`** : métriques `/stats` ludiques + payload Chart.js à partir des compteurs lifetime + snapshot cache + hauts-faits Manual Review (`mr_achievements.py`). Piloté par `ENABLE_PLAYFUL_STATS`.
*   **`services/changelog_service.py`** : `get_app_version()` / `get_current_version()` (mise en cache) / `get_full_changelog_html()`. Importé indépendamment par `app.py` (contexte global des templates) et par `routes/misc.py` (`/api/changelog`) — importer depuis ce module plutôt que l'un depuis l'autre évite un import circulaire.
*   **`routes/*.py`** : un Blueprint Flask par domaine — `auth` (`/setup`, `/login`, `/logout`, `/account/password`), `pages` (`/`, `/stats`), `config` (`/save-config`, `/regenerate-webhook-token`), `series` (`/save-override`, `/toggle-ignore`, recherche/application de couverture, `POST …/seal-locks`, `POST …/seal-locks-pending`), `sync` (`/force-sync`, `/batch-sync` [inventaire mis en cache par batch, voir `_get_batch_inventory` §4.F], `/stop-batch`, `/reset-errors`, `/export-errors`, `/webhook`), `manual_review` (`/api/manual-reviews…` dont `POST …/bulk-accept`), `misc` (`/healthz`, `/api/proxy-image`, `/api/changelog`).
*   **`sockets/handlers.py`** : handlers Socket.IO (`connect`, `fetch_covers_stream`), enregistrés sur `extensions.socketio` ; importé une seule fois pour son effet de bord depuis `app.py`. `connect` non authentifié → `return False` ; connect réussi émet `manual_review_pending_count` / `manual_review_queue_summary` **uniquement vers le `sid` connecté**.
*   **`static/js/*.js`** : l'ancien `script.js` monolithique est désormais découpé en fichiers `<script>` classiques chargés dans l'ordre de dépendance (`utils.js` → `websocket.js` → `overrides.js` → `covers.js` → `config.js` → `batch.js` → `manual_review.js` → `license_nag.js` → `main.js`). Volontairement sans bundler ni `type="module"` : les templates s'appuient sur des gestionnaires `onclick="..."` inline, qui exigent que chaque fonction reste en portée globale.
*   **`templates/partials/*.html`** : l'ancien `index.html` monolithique est désormais une coquille légère qui `{% include %}` des partials Jinja — dont `_manual_review_modal.html` pour C29 — un par zone d'UI autonome. Modifiez directement le partial concerné plutôt que de faire défiler un template unique de 600+ lignes.
*   **`tests/`** : le filet de sécurité pytest (fixtures `conftest.py` + tests métier dont `test_auth.py`, `test_healthz.py`, `test_config_env_seeding.py`, `test_db_manager.py`, `test_kavita_api.py`, `test_playful_stats.py`, `test_manual_review.py`, `test_manual_review_bulk_accept.py`, `test_manual_review_queue_api.py`, `test_needs_relock.py`, `test_batch_inventory_cache.py`, `test_batch_progress_isolation.py`, `test_dashboard_renders.py`, `test_supporter_nag_policy.py`, `test_batch_targeted_fields.py`, `test_comic_flexible.py`, `test_scraper_mangabaka.py`, `test_routes_series.py`, `test_max_tags.py`, `test_max_genres.py`, `test_scraper_max_caps.py`, `test_audit_c1_c3.py`, `test_fallback_query.py`, `test_metadata_fetcher_smart_scoring.py`, …). Les fixtures ne touchent jamais au vrai dossier `data/` ni au réseau — `isolated_db` monkeypatch `db_manager.DB_FILE`/`DATA_DIR` vers un fichier SQLite `tmp_path`, `flask_app`/`client` construisent une application Flask minimale n'enregistrant que `routes/series.py` (pas `app.py` en entier, pour éviter de démarrer de vrais workers de fond/logging), et `mock_kavita_api` bouchonne chaque méthode réseau de `KavitaAPI`. Voir §10. Helpers partagés : `url_allowlist.py`, `csrf_utils.py`, `cors_config.py`.

⚠️ **Les noms d'endpoints des Blueprints ont changé.** Flask préfixe toujours l'endpoint d'une route de Blueprint par le nom du Blueprint (ex : la vue `login` de `routes/auth.py`, enregistrée sur le Blueprint `auth`, devient l'endpoint `auth.login` — impossible de désactiver ce préfixage). Chaque appel `url_for(...)` et les listes blanches de `auth_manager.setup_gate` / `login_gate` ont été mis à jour en conséquence (`auth.setup`, `auth.login`, `auth.logout`, `pages.index`, `pages.stats`, `misc.healthz`, `sync.export_errors`, `sync.webhook`). **Si vous renommez un Blueprint ou déplacez une route vers un autre Blueprint, recherchez son ancien nom d'endpoint dans `auth_manager.py`, `app.py` et dans chaque template `.html` avant de supposer que `url_for()` fonctionne toujours.**