## [1.6.1] - 2026-07-30 (Auth + Manual Review + Stats + Providers + Sealing + Supporter)

> **Hotfix (same 1.6.1 line):** BF52 + library denylist = auto-sync only + account password change + Manual Review list/bulk-accept + Kavita verification link + batch performance/accuracy/concurrency fixes + typed live status badges. No version bump.

EN
### What's new in 1.6.1
The big picture — details below.

* **Real accounts** — Forced `/setup`, hashed passwords, fail-closed UI + Socket.IO (replaces optional plaintext `ADMIN_PASSWORD`).
* **Manual Review Mode** — Scrape → park → pick / edit / cover → confirm; no auto-write to Kavita until you say so.
* **Playful `/stats`** — Lifetime KPIs, scroll story, Manual Review achievements, live topbar counters.
* **New providers** — Official **MAL** API, **BDTheque.com**, **Wikidata live** (SPARQL / Entity API only — no offline dump mode yet).
* **Comic Flexible** — Kavita library type ID 5: Comic cascade first, then Manga fallback.
* **Needs seal (`NEEDS_RELOCK`)** — Soft-success after a failed Kavita re-lock is visible and retryable, not silently “Completed”.
* **Security & ops** — Non-root Docker, `/healthz` HEALTHCHECK, CVE bumps, webhook header, `config.json` 0600, env seeding fixed.
* **Hotfix BF52** — Fresh installs can save Kavita URL/API key from the Config modal again; Docker Compose paste-play (`host.docker.internal`) documented; library denylist is **auto-sync polling only**.
* **Hotfix follow-ups** — Account password change from the Config modal; Manual Review gets a series list + threshold bulk-accept and a "view in Kavita" verification link; Comic Flexible's Manga fallback behaves the same in Manual Review as in Auto; `/batch-sync` no longer refetches the whole Kavita inventory per chunk; the batch progress bar and the supporter nag no longer misfire on webhook/auto-sync noise or on all-skipped batches; library checkboxes no longer reload the page or silently re-check themselves; Stop batch no longer drops webhook/auto-sync jobs; a second concurrent batch is rejected instead of corrupting the first; bulk-accept surfaces its individual failures; live status badges no longer depend on parsing translated log text.

### 🔒 Security
* **BF46. Dependency CVE bumps (thanks angusmaul)** — `gunicorn` `21.2.0` → `23.0.0` and `requests` `2.31.0` → `2.33.1`. Clears five known advisories: two request-smuggling issues in Gunicorn (`PYSEC-2026-1433`, `PYSEC-2026-1434`, both fixed in 22.0.0) and three in Requests (`PYSEC-2026-1873`, `PYSEC-2026-1872`, `PYSEC-2026-2275`, the last only fixed in 2.33.0). No public API change in either package for the way MetaKavita uses them. `googletrans` is deliberately left at `4.0.0-rc1`.
* **BF47. `/api/proxy-image` size cap (thanks angusmaul)** — The proxy now streams the remote response and refuses anything over **5 MB** with a `413`, instead of buffering the whole body into memory with `res.content`. An allowlisted host serving a very large file could previously exhaust the container's memory, which under `gunicorn -w 1` takes down the whole application. `Content-Length` is checked first as a cheap early reject; the running byte total is what actually enforces the limit, since that header can be absent or untrue. Redirect hops are now closed as they are followed (`url_allowlist.fetch_with_safe_redirects`), which matters once responses are streamed.
* **BF48. Webhook token as a header (thanks angusmaul)** — `/webhook` accepts `X-Webhook-Token` in addition to the existing `?token=` query parameter, which keeps working unchanged. The header is preferred because a query string ends up in reverse-proxy access logs, browser history and `Referer` headers. Token comparison now runs on UTF-8 bytes, so a non-ASCII token returns a clean `401` instead of raising inside `secrets.compare_digest`.
* **BF49. `config.json` written 0600 (thanks angusmaul)** — `save_config()` restricts the file to its owner after every write. It holds `SECRET_KEY`, `WEBHOOK_TOKEN` and every API key, and was previously created with the process umask (0644 — world-readable — on a default Docker image). Applied on every save so a file restored from a backup or written by an older version is repaired too. Best-effort: `chmod` is skipped silently on Windows and on filesystems that refuse it, and can never fail a save.
* **C54. Non-root container with PUID/PGID (thanks angusmaul)** — The image no longer runs as root. It ships a dedicated `metakavita` user defaulting to **1000:1000**, and a linuxserver.io-style entrypoint applies `PUID`/`PGID` at *runtime* before dropping privileges with `gosu`, so a bind-mounted `./data` owned by any uid keeps working. Gunicorn still runs as PID 1, so `docker stop` reaches it directly and shuts down cleanly. **Upgrading:** an existing `data/` is root-owned from previous versions — the entrypoint takes ownership of it automatically on every start, including sideloaded scrapers under `data/scrapers/`. A `HEALTHCHECK` is included; with **C57** it probes `GET /healthz` and requires HTTP **200** (no longer `/login` with a lax status check).
* **C55. `.dockerignore` added (thanks angusmaul)** — `COPY . .` previously copied whatever was in the build context. On any machine where the application had been run, that included `data/config.json` with a live `SECRET_KEY`, `WEBHOOK_TOKEN` and API keys, baked into an image layer. Published `ghcr.io` images were never affected (CI builds from a clean checkout), but local builds were. Also drops local virtualenvs, `.git/` and the test suite from the image — 268 MB → 185 MB.
* **C56. Custom scraper RCE warning (thanks angusmaul)** — `CUSTOM_SCRAPERS.md` now opens with a prominent warning, in French and English, that a `.py` dropped into `data/scrapers/` is imported and executed at startup with the application's full privileges: no sandbox, no validation. Spells out what a malicious scraper can actually reach (`config.json` and therefore `SECRET_KEY` / `WEBHOOK_TOKEN` / every API key, any file the container can see, arbitrary outbound connections, and widening the image-proxy allowlist via `proxy_domains`), gives non-programmers concrete red flags to look for, calls out AI-generated code specifically, and states plainly that no third-party scraper is vetted by anyone until the community repository exists. A short version with a link is added to both README security sections.

### 🧪 Tests
* **BF50. The test suite no longer writes to the real database** — `test_scraper_max_caps.py::test_enrichment_engine_caps_genres_and_tags_before_kavita` is the only test in that file that runs `enrich_series()` end to end, and its success path calls `record_enrichment_telemetry()`. That call was not mocked, and it opens `db_manager.DB_FILE` directly — so every run of the suite wrote into the repository's real `data/cache.db`, incrementing `series_enriched` and `matches_won` and accumulating wins for a fictitious `FAKE` provider that the C7 statistics podium would then display as a genuine scraper. Adding the existing `isolated_db` fixture redirects it to a throwaway database.

### 🔐 Authentication
* **C58. Full user/password authentication (issue #15)** — Replaces the single optional plaintext `ADMIN_PASSWORD` with a real account system. A `users` table in `cache.db` stores a username and a Werkzeug hash (`pbkdf2:sha256`, method pinned explicitly rather than following Werkzeug's shifting default). On first run every route redirects to a `/setup` screen that creates the account; `/setup` closes permanently once an account exists, so it cannot become an unauthenticated way to add a second one.
* **Fails closed.** The old gate only protected the application *if* `ADMIN_PASSWORD` happened to be set, which meant the default install served the dashboard to anyone. There is now no configuration in which the UI is reachable without a session — including when the database is unreadable, where access is denied rather than falling through to "no account, let them in". The Socket.IO handshake is gated too: it bypasses Flask's `before_request` stack, so without that the live log, batch progress and cover streams would have stayed readable without an account.
* **Forced migration, no silent import.** An existing plaintext `ADMIN_PASSWORD` is never adopted as the new password — it lived in cleartext on disk, so hashing it would only protect an already-compromised secret. It is deleted from `config.json` once the real account is created.
* **`TRUSTED_PROXY_COUNT`** — `1` by default (unchanged behaviour behind a reverse proxy); `0` makes MetaKavita ignore `X-Forwarded-*` and count the real TCP peer. This matters: `ProxyFix` takes `remote_addr` from `X-Forwarded-For`, so on a directly-exposed instance an attacker could rotate that header and the per-IP lockout would never trigger.
* **Brute-force lockout** — 5 failed attempts from one IP locks that IP for 15 minutes, checked before any password hashing so attempts stay cheap. Temporary by design, so a typo cannot permanently lock anyone out. Held in memory, which is sound because Gunicorn runs `-w 1`; writing to SQLite on every failed attempt would hand an unauthenticated attacker unlimited disk writes.
* **Global lockout backstop** — 20 failed logins in 15 minutes across *all* addresses also locks the login screen. Closes the hole where `TRUSTED_PROXY_COUNT=1` on a directly-exposed instance let an attacker rotate `X-Forwarded-For` and never trip the per-IP counter. When it fires it locks everyone for up to 15 minutes — intentional; the per-IP lockout is what stops an attacker without delaying you.
* **Legacy ownership proof on `/setup`** — if `ADMIN_PASSWORD` is still in `config.json`, setup asks for it once before creating the account, then deletes it. Closes the upgrade claim window where an empty `users` table would otherwise let the first network visitor own a previously password-protected instance. Fresh installs (no legacy password) stay first-come-first-served; pre-provision with `ADMIN_PASSWORD_HASH` if that matters.
* **`ADMIN_PASSWORD_HASH` / `ADMIN_USERNAME`** — optional pre-hashed seeding for docker-compose deployments, generated by the new `debug/hash_password.py`. A separate variable rather than overloading `ADMIN_PASSWORD`, since telling a hash from a plaintext by inspection is exactly the ambiguity that produces auth bugs. Ignored once an account exists, so a forgotten variable can never overwrite a real password. A value that is not a Werkzeug hash shape is refused with a log error — never written — so a plaintext pasted by mistake cannot create an account no password can open.
* **Timing equalization** — unknown usernames and wrong passwords both pay exactly one memoized KDF against a dummy hash (not a fresh `generate_password_hash` per miss, which previously cost *two* KDFs and inverted the timing signal).
* **Socket.IO handshake** — unauthenticated connects are rejected with `return False` (documented Flask-SocketIO form). Per-event `_reject_unauthenticated` guard as defense in depth; queue/cover emits target the connecting `sid` only.
* **Sessions** — keyed on `user_id`; `PERMANENT_SESSION_LIFETIME` set explicitly to 7 days (Flask's silent default was 31).

### 🩺 Operations
* **C57. `GET /healthz` liveness endpoint** — Returns `{"status": "ok", "version": …}` and nothing else. Whitelisted in `require_login`, so it keeps answering `200` once a password is set, which is what makes it usable as the container's `HEALTHCHECK` target — that check previously had to hit `/login` and accept any status below 500, because no route reliably returned `200`. It now demands exactly `200`, so a routing regression is caught instead of passing as a `404`. The endpoint reads no configuration, opens no database connection and never contacts Kavita: it reports that the application is alive and routing, not that its dependencies are up, so a Kavita outage cannot put a healthy container into a restart loop.
* **BF51. Environment variables seed a fresh install again** — `load_config()` used to generate `SECRET_KEY` / `WEBHOOK_TOKEN` and write `config.json` *before* merging the environment, so every key landed as a default and the `os.getenv` fallback was never reached on the next boot (`UI_LANG`, `KAVITA_URL`, `PROVIDER_1`, `MAX_TAGS`, …). Env merge now runs first; precedence is `config.json` > environment > default. `ADMIN_PASSWORD` is intentionally *not* seeded from the environment (would re-arm the one-shot ownership proof forever).

### 🩹 Hotfix (1.6.1 — no version bump)
* **BF52. Fresh Config modal + Docker Kavita plug-and-play** — Upgrading 1.6.0→1.6.1 kept working (credentials already in `config.json`), but a **brand-new** instance configured only from the Config modal often looked like Kavita settings were “not written”. Root causes: API key inputs were prefilled with the `********` sentinel (browser password-managers / empty sidebar `saveConfig()` posts could wipe or never persist the first-run key), blank `KAVITA_*` strings in `config.json` blocked Compose env seeding, and `localhost` URLs from inside Docker pointed at MetaKavita itself. Fix: secret fields always render empty (blank POST = keep existing); modal Save reloads, sidebar toggles save without reload; empty `KAVITA_URL` / `KAVITA_API_KEY` fall back to env; auth errors are specific (localhost / 401 / timeout / DNS / connection / SSL); `/save-config` logs persistence and returns a Kavita probe; Compose example + README Option A always ship `extra_hosts: host.docker.internal:host-gateway` and document never-use-localhost. **Follow-up:** `DATA_DIR`/`CONFIG_FILE` are absolute (cwd-independent); `save_config()` is atomic (tmp+replace) with post-write verify; API keys use `type=text` + CSS mask (not `password`) and JS forces `FormData.set` for Kavita fields.
* **Library denylist scope** — `DISABLED_LIBRARIES` applies to **auto-sync polling only** (not dashboard, manual batch, or webhook). The denylist no longer lives in `KavitaAPI.get_all_series()`, which always returns the full inventory; the auto-sync worker filters its own candidates (`select_auto_sync_candidates`). Side effect fixed: the polling loop used to purge the cache of every series in a disabled library as if it were orphaned. Series now always carry `libraryId`, so that filter can't silently miss. After each `:dev` push: `docker pull` + `compose up -d --force-recreate --pull always`.
* **Library checkboxes no longer reload or self-recheck** — Config → Planning checkboxes now save via plain AJAX (`saveConfig()`) instead of forcing a full page reload on every click. That reload was also what re-triggered the old auto-heal below, so unchecking the very last library used to make the reload silently re-check every box again.
* **Removed the "wipe heal" auto re-enable** — The previous hotfix line above healed a `DISABLED_LIBRARIES` covering 100% of libraries on every dashboard load, to undo an accidental first-save wipe. It could not tell that apart from someone *deliberately* disabling every library, so a fully-unchecked denylist never survived a reload. The write-side fix (only touching `DISABLED_LIBRARIES` when the full library list was actually rendered) already prevents the accidental wipe; the heal is removed so a deliberate "disable everything" now sticks.
* **Simple password change** — Config modal gets a 3-field "Account" section (`POST /account/password`) to change the password without leaving the app. Re-verifies the current password through the same check as `/login`; a wrong one counts as a failed login attempt under the existing brute-force lockout.
* **`/batch-sync` no longer refetches the whole Kavita inventory per chunk** — The UI splits a batch into ~50-series packets; each one used to call `get_all_series()` again (and purge the library-type cache with it). Only the first packet of a batch now fetches a fresh inventory; the rest reuse that snapshot for up to 15 minutes.
* **Batch progress bar accuracy** — The bar used to derive `remaining` from the shared sync queue's size, which also holds webhook and auto-sync jobs — a webhook firing mid-batch made the bar jump. Dedicated counters now track batch progress in isolation from the rest of the queue.
* **Supporter nag no longer fires on a no-op batch** — The donation prompt used to appear even when every series in the batch was already up to date and nothing was actually sent to Kavita. It now only fires when at least one series was really written.
* **Comic Flexible consistency (Manual vs Auto)** — In Manual Review, a weak (below-threshold) Comic hit used to block the Manga fallback that Auto mode would have triggered for the exact same result. Both modes now use the same "no strong hit" trigger; Manual mode still keeps the weak Comic candidates on hand if the Manga fallback also comes up empty.
* **Manual Review: series list + bulk-accept + Kavita link** — A new list view lets you jump straight to a specific pending series instead of paging through the queue one at a time, plus a "confirm all above threshold" bulk action (default `0.60`, same "confirm without editing" path as a single manual pick — never a new scraping trigger). The pick/edit screen also gets a "view in Kavita" link to double-check you're matching the right series before confirming.
* **Deferred seal retry race fix** — The background retry that seals a `NEEDS_RELOCK` series now claims the same per-series lock as a manual re-scrape, and skips itself if that series is already being processed elsewhere, instead of potentially racing it.
* **No more recap flash while a batch is still running** — Finishing the current Manual Review queue while its batch was still scraping other series used to show the recap screen for a few seconds, then yank you back to a "pick" screen the moment the next series landed. The recap now only shows once the batch has actually finished; until then, an empty queue shows the existing waiting mask instead.
* **Stop batch no longer drops webhook/auto-sync jobs** — `drain_sync_queue()` used to empty the shared sync queue entirely, so a webhook event or an auto-sync candidate that happened to be queued at the exact moment you clicked Stop silently vanished with the rest of the batch. It now only removes batch-tagged items and puts everything else back.
* **A second concurrent batch is now rejected instead of corrupting the first** — Launching a batch from two tabs (or a stray double-click) at once used to reset the progress counters of the batch already running, scrambling its progress bar and its supporter-nag `real_sends` count. `/batch-sync` now returns `409` for a new batch while one is still active.
* **Manual Review bulk-accept surfaces individual failures** — The bulk-accept feedback used to only report an `accepted`/`skipped` count; a series that failed to write to Kavita during the operation disappeared silently into "skipped". Failures are now listed by name with their error.
* **Live status badges no longer parse translated log text** — The dashboard used to guess a series' live badge by matching French/English keywords inside the raw log line ("réussi", "déjà à jour", "introuvable"...), which could silently stop working if the wording or language changed. `enrich_series()` now emits a typed `series_status` event for every outcome (`NOT_FOUND`, `PENDING_REVIEW`, already-up-to-date `COMPLETED`), and the dashboard badge logic relies on that exclusively.

### ✨ Highlights
* **Manual Review Mode (C29)** — Silent scrape queue: candidates land as PENDING_REVIEW without writing to Kavita. Pick modal with score gradient, keys 1–3, weak (below-threshold) band in red; optional edit-before-confirm; **cover pick step** before confirm; lifetime telemetry + session recap + **achievements** on `/stats`. Integrity follow-up: one review per series, atomic park/skip/confirm, batch skips parked series, apply under the per-series lock, WAL SQLite, queue sync on Socket.IO.
* **Reliability barometer** — Sidebar checkbox unlocks a match-accept threshold slider (`0.30`–`1.00`, default `0.60`). Off = fixed tested default. Config: `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD`; scrapers use `get_match_accept_threshold()`.
* **BDTheque.com (comics)** — New `BDTHEQUE` scraper for https://www.bdtheque.com/ (not Bédéthèque / bedetheque.com): AJAX series search, series page parse (staff, publisher, genres, status, cover), Magic Input `/series/{id}/{slug}`, unified scoring, cover search. Distinct from existing `BEDETHEQUE`. Cover URLs: always `/repupload/T/{couv}` (site typeahead); series page reads `data-echo` (echo.js lazy-load) instead of `placeholder.png`.
* **Kavita library sync filter** — Config → Planning: checkboxes for `DISABLED_LIBRARIES`. Empty = all enabled for auto-sync; new libraries stay on by default. Applies to **auto-sync polling only** (dashboard, manual batch, and webhook always see every library).
* **MyAnimeList official API** — New `MAL` scraper (replaces dead Jikan path): `X-MAL-CLIENT-ID` auth via `MAL_API_KEY` (Client ID from https://myanimelist.net/apiconfig). Manga + Book (light novels), Magic Input `myanimelist.net/manga/{id}`, unified scoring, covers CDN. No user OAuth required for search/details.
* **Wikidata provider (live only)** — New `WIKIDATA` scraper for Manga / Comic / Book via SPARQL + Entity API, Magic Input `Q…` / wikidata.org URLs, unified scoring, Commons covers. Shared claim→MetaKavita mapping in `scrapers/wikidata_map.py`. Best as fallback / ISBN / cross-IDs (AniList, MAL), not a replacement for AniList. **Live API only for now** — no offline SQLite / dump mode in this release.
* **Comic (Flexible) / ID 5 (C35)** — Kavita's mixed Comic Flexible libraries are no longer treated as strict Comic. MetaKavita runs `COMIC_PROVIDER_*` first, then falls back to Manga `PROVIDER_*` when no useful metadata is found. Manual cover search queries Comic + Manga scrapers.
* **Playful Statistics (C7)** — Restyled `/stats` with Chart.js (donut + bars), lifetime counters (`series_enriched` / `matches_won` / `series_missed`), hit-rate KPI, ~24 fun cards, **Manual Review achievements** chapter. `ENABLE_PLAYFUL_STATS` on by default (disable in config modal). Live topbar KPIs on the dashboard (3 lifetime counters + session counter reset on tab close via `sessionStorage`). Socket.IO `enrichment_stats` keeps counters live during batch.
* **`/stats` scroll story** — Premium chapter-per-viewport layout (Leetify / GPU-landing vibe): hero score, lifetime, time saved, cache health, manual craft, providers + podium, then a full summary table. Intersection Observer reveals + count-up; color accents per chapter.
* **Dashboard visual polish** — Same design language as `/stats` (**Bricolage Grotesque**, teal/sky accents, glass topbar, softer series rows) without changing workflow density.
* **Organic playful estimates** — Time saved no longer stuck at `0 min` when lifetime telemetry lags behind the cache: fun metrics use `max(lifetime, completed / provider wins)`. Time model = ~6 min/series + ~1.5 min/useful match; duration can show days.
* **Field sealing / `NEEDS_RELOCK`** — When Kavita write succeeds but the C# Lock Guard re-lock pass fails (soft-success / BF19), the series is no longer marked plain `COMPLETED`. Status **`NEEDS_RELOCK`** (orange “Needs seal” badge), deferred seal retry (~2 s, no re-scrape), manual 🔒 button, filter, and `POST /api/series/<id>/seal-locks` (+ bulk pending). Successful seal → `COMPLETED`.
* **Supporter nags (tip → Buy Me a Coffee)** — Rare playful overlays (max 1–2/day, 7-day honeymoon, honor snooze 30 days) after hot moments (batch end / rich Manual Review recap), plus a native café CTA in the MR recap. No paywall, no license keys. Class `.license` kept as a future silence hook.

### 🧰 Batch QoS & Granularity
* **Resume-friendly selection** — Successful series (✅ / already up to date) auto-uncheck. Checked series IDs persist in `localStorage` per library (`mk_batch_selection:*`) so a refresh or network drop does not wipe the selection; filters no longer clear hidden checkboxes.
* **Stop vs chunked enqueue** — Stop aborts the UI ×50 `/batch-sync` loop (`AbortController`) and disables server enqueue until the next batch’s first packet (`resume_enqueue=true`), so late in-flight chunks cannot refill the queue after a drain.
* **Batch progress bar** — Above the batch action buttons: `done / total` fill driven by Socket.IO `batch_progress` (`remaining` + active title from the worker `qsize()`). Total is set at launch from the UI selection; bar hides on completion (~1.5s) or Stop/drain.
* **Batch targeted-fields mask** — Collapsible sidebar panel “Targeted fields (batch)”: ephemeral write filter for the next batch only (does not persist overrides). Leave all 12 checked = respect each series’ saved mask. Uncheck any field → CSV sent to `/batch-sync` as a 4-tuple queue item (`targeted_fields_override`).
* **Check all / Uncheck all** — Same controls on the sidebar batch mask and on each series’ targeted-fields override panel.

### 🐛 UI polish
* **Collapsible Scraping Options** — Click the sidebar “Scraping Options” title to show/hide the whole strategy card (open by default; open/closed state persisted in `localStorage` as `mk_scraping_options_open`).
* **`/stats` page scroll** — Dashboard `100vh` + `overflow: hidden` overrides so the playful stats page scrolls on desktop again.

### 🛠️ Manual Review integrity (C29 follow-up)
* **Confirm before write (auto batch)** — With Manual Review **off**, the same « Éditer avant confirmation » toggle can enable `CONFIRM_BEFORE_WRITE`: auto scrape parks a preview (`awaiting_confirm`) and opens the edit panel; Kavita is written only on confirm. Worker stays non-blocking; turning the option off purges auto-confirm parks only.
* **One pending review per series** — `pending_reviews.series_id` is uniquely indexed; parking replaces any existing row for that series instead of stacking duplicates on re-batch.
* **Atomic park / skip / confirm** — `park_pending_review` and `close_pending_review` write the queue row and `series_cache.status` in a single SQLite transaction (no more COMPLETED/PENDING with an orphan queue row after a crash).
* **Early “already up to date” path** — Leaves `PENDING_REVIEW` series alone; on `NEEDS_RELOCK` attempts seal-only then COMPLETED; otherwise marks COMPLETED and purges any stray pending row.
* **Global batch skips parked series** — Unchecked batch no longer re-scrapes `PENDING_REVIEW` (explicitly checked series can still be re-queued; park stays idempotent).
* **Apply under the per-series lock** — `apply_manual_review` shares `_processing_lock` with `enrich_series` / research, so confirm cannot race a concurrent scrape of the same ID.
* **SQLite WAL + busy_timeout** — All `db_manager` connections use WAL and a 30s busy timeout to cut intermittent `database is locked` under worker + REST + Socket.IO load.
* **Mode off / ignore / orphan cleanup** — Turning `MANUAL_REVIEW_MODE` off purges the queue; ignoring a series deletes its pending row; `clean_orphaned_cache` also deletes orphaned reviews.
* **Frontend queue sync** — Serialized `loadQueue`, `currentReviewId` re-anchoring, in-flight guards on pick/confirm/skip, and handlers for `confirmed` / `skipped` / `refreshed` / count-to-zero keep the modal aligned with the server.
* **Cover pick phase** — Optional step after provider pick to search/select a cover before confirm; explicit cover upload even when `AUTO_COVER` is off.
* **Tests** — `tests/test_manual_review.py` covers park idempotency, early-skip preservation, orphan purge, and orphaned-cache cleanup; `tests/test_needs_relock.py` covers soft-fail → `NEEDS_RELOCK`.

---

FR
### Nouveautés de la 1.6.1
Les grosses évolutions — le détail suit.

* **Vrais comptes** — `/setup` forcé, mots de passe hachés, UI + Socket.IO fail-closed (remplace l’ancien `ADMIN_PASSWORD` optionnel en clair).
* **Mode Review Manuelle** — Scrape → file → pick / édition / couverture → confirm ; rien n’écrit dans Kavita tant que tu ne valides pas.
* **`/stats` ludiques** — KPI lifetime, récit scroll, hauts-faits Manual Review, compteurs live en topbar.
* **Nouveaux providers** — API officielle **MAL**, **BDTheque.com**, **Wikidata live** (SPARQL / Entity API uniquement — pas de mode dump hors-ligne pour l’instant).
* **Comic Flexible** — Type de bibliothèque Kavita ID 5 : cascade Comic d’abord, repli Manga ensuite.
* **À sceller (`NEEDS_RELOCK`)** — Soft-success après échec de re-lock Kavita visible et rejouable, plus un « Terminé » silencieux.
* **Sécurité & exploitation** — Docker non-root, HEALTHCHECK `/healthz`, bumps CVE, en-tête webhook, `config.json` 0600, semis env corrigé.
* **Hotfix BF52** — Setup neuf : sauvegarde URL/clé Kavita depuis la modal Config de nouveau fiable ; Compose paste-play (`host.docker.internal`) documenté ; dénylist biblios = **auto-sync only**.
* **Suites du hotfix** — Changement de mot de passe compte depuis la modal Config ; Review Manuelle avec liste de séries + tout accepter par seuil + lien de vérification Kavita ; le fallback Manga de Comic Flexible se comporte pareil en Manuel qu'en Auto ; `/batch-sync` ne retélécharge plus tout l'inventaire Kavita à chaque paquet ; la barre de progression batch et le nagware supporter ne se déclenchent plus sur le bruit webhook/auto-sync ni sur un batch entièrement skip ; les cases bibliothèques ne rechargent plus la page et ne se recochent plus toutes seules ; Stop batch ne jette plus les jobs webhook/auto-sync ; un second batch concurrent est refusé plutôt que de corrompre le premier ; le tout-accepter de la Review Manuelle affiche ses échecs ; les badges de statut live ne dépendent plus d'un parsing de texte de log traduit.

### 🔒 Sécurité
* **BF46. Montée de versions (CVE, merci angusmaul)** — `gunicorn` `21.2.0` → `23.0.0` et `requests` `2.31.0` → `2.33.1`. Corrige cinq vulnérabilités connues : deux failles de *request smuggling* dans Gunicorn (`PYSEC-2026-1433`, `PYSEC-2026-1434`, corrigées en 22.0.0) et trois dans Requests (`PYSEC-2026-1873`, `PYSEC-2026-1872`, `PYSEC-2026-2275`, cette dernière uniquement corrigée en 2.33.0). Aucun changement d'API publique pour l'usage qu'en fait MetaKavita. `googletrans` reste volontairement en `4.0.0-rc1`.
* **BF47. Plafond de taille sur `/api/proxy-image` (merci angusmaul)** — Le proxy lit désormais la réponse distante en flux et refuse au-delà de **5 Mo** avec un `413`, au lieu de charger tout le corps en mémoire via `res.content`. Un hôte autorisé servant un très gros fichier pouvait épuiser la mémoire du conteneur — ce qui, sous `gunicorn -w 1`, emporte toute l'application. Le `Content-Length` sert de refus précoce peu coûteux ; c'est le total courant des octets lus qui applique réellement la limite, cet en-tête pouvant être absent ou mensonger. Les hops de redirection sont maintenant fermés au fil de leur suivi (`url_allowlist.fetch_with_safe_redirects`), ce qui compte dès lors que les réponses sont streamées.
* **BF48. Jeton du webhook en en-tête (merci angusmaul)** — `/webhook` accepte `X-Webhook-Token` en plus du paramètre `?token=` existant, qui continue de fonctionner à l'identique. L'en-tête est recommandé car une chaîne de requête se retrouve dans les logs d'accès des reverse proxies, l'historique du navigateur et les en-têtes `Referer`. La comparaison se fait désormais sur les octets UTF-8 : un jeton non-ASCII renvoie un `401` propre au lieu de faire lever `secrets.compare_digest`.
* **BF49. `config.json` écrit en 0600 (merci angusmaul)** — `save_config()` restreint le fichier à son propriétaire après chaque écriture. Il contient `SECRET_KEY`, `WEBHOOK_TOKEN` et toutes les clés d'API, et était créé avec l'umask du processus (0644 — lisible par tous — sur une image Docker par défaut). Réappliqué à chaque sauvegarde, afin de corriger aussi un fichier restauré d'une sauvegarde ou écrit par une version antérieure. Best-effort : le `chmod` est ignoré silencieusement sous Windows et sur les systèmes de fichiers qui le refusent, et ne peut jamais faire échouer une sauvegarde.
* **C54. Conteneur non-root avec PUID/PGID (merci angusmaul)** — L'image ne tourne plus en root. Elle embarque un utilisateur dédié `metakavita` par défaut en **1000:1000**, et un entrypoint façon linuxserver.io applique `PUID`/`PGID` au *démarrage* avant d'abandonner les privilèges via `gosu` : un `./data` monté et possédé par n'importe quel uid continue donc de fonctionner. Gunicorn reste PID 1, donc `docker stop` l'atteint directement et l'arrêt est propre. **Mise à jour :** un `data/` existant appartient à root depuis les versions précédentes — l'entrypoint en reprend la propriété automatiquement à chaque démarrage, y compris les scrapers sideloadés dans `data/scrapers/`. Un `HEALTHCHECK` est fourni ; avec **C57** il interroge `GET /healthz` et exige HTTP **200** (plus `/login` avec un contrôle de statut laxiste).
* **C55. Ajout d'un `.dockerignore` (merci angusmaul)** — `COPY . .` copiait auparavant tout le contenu du contexte de build. Sur une machine où l'application avait déjà tourné, cela incluait `data/config.json` avec un `SECRET_KEY`, un `WEBHOOK_TOKEN` et des clés d'API réels, figés dans une couche d'image. Les images publiées sur `ghcr.io` n'ont jamais été concernées (la CI build depuis un checkout propre), mais les builds locaux l'étaient. Exclut aussi les virtualenvs locaux, `.git/` et la suite de tests — 268 Mo → 185 Mo.
* **C56. Avertissement RCE sur les scrapers personnalisés (merci angusmaul)** — `CUSTOM_SCRAPERS.md` s'ouvre désormais sur un avertissement bien visible, en français et en anglais : un `.py` déposé dans `data/scrapers/` est importé et exécuté au démarrage avec tous les droits de l'application, sans bac à sable ni validation. Détaille ce qu'un scraper malveillant peut réellement atteindre (`config.json` et donc `SECRET_KEY` / `WEBHOOK_TOKEN` / toutes les clés d'API, n'importe quel fichier visible du conteneur, des connexions sortantes arbitraires, et l'élargissement de l'allowlist du proxy d'images via `proxy_domains`), donne des signaux d'alarme concrets pour les non-développeurs, vise explicitement le code généré par IA, et précise sans détour qu'aucun scraper tiers n'est vérifié tant que le dépôt communautaire n'existe pas. Une version courte avec lien est ajoutée aux deux sections sécurité du README.

### 🧪 Tests
* **BF50. La suite de tests n’écrit plus dans la vraie base** — `test_scraper_max_caps.py::test_enrichment_engine_caps_genres_and_tags_before_kavita` est le seul test du fichier à traverser `enrich_series()` de bout en bout, et son chemin de succès appelle `record_enrichment_telemetry()`. Cet appel n’était pas mocké et ouvre directement `db_manager.DB_FILE` : chaque exécution de la suite écrivait donc dans le vrai `data/cache.db` du dépôt, incrémentant `series_enriched` et `matches_won` et accumulant des victoires pour un provider fictif `FAKE` que le podium des statistiques C7 affichait ensuite comme un vrai scraper. L’ajout de la fixture existante `isolated_db` le redirige vers une base jetable.

### 🔐 Authentification
* **C58. Authentification utilisateur/mot de passe complète (issue #15)** — Remplace l'unique `ADMIN_PASSWORD` optionnel en clair par un vrai système de comptes. Une table `users` dans `cache.db` stocke un identifiant et un hachage Werkzeug (`pbkdf2:sha256`, méthode épinglée explicitement plutôt que de suivre le défaut mouvant de Werkzeug). Au premier démarrage, toutes les routes redirigent vers un écran `/setup` qui crée le compte ; `/setup` se ferme définitivement dès qu'un compte existe, pour ne pas devenir un moyen non authentifié d'en créer un second.
* **Fail-closed.** L'ancien gate ne protégeait l'application *que si* `ADMIN_PASSWORD` était renseigné : l'installation par défaut servait donc l'interface à tout le monde. Il n'existe plus aucune configuration dans laquelle l'UI est joignable sans session — y compris base illisible, où l'accès est refusé au lieu de retomber sur « aucun compte, laisse passer ». Le handshake Socket.IO est protégé aussi : il contourne la pile `before_request` de Flask, donc sans cela les flux de logs, de progression des batchs et de couvertures seraient restés lisibles sans compte.
* **Migration forcée, aucune reprise silencieuse.** Un `ADMIN_PASSWORD` en clair existant n'est jamais adopté comme nouveau mot de passe — il a vécu en clair sur le disque, le hacher ne protégerait qu'un secret déjà compromis. Il est supprimé de `config.json` dès que le vrai compte est créé.
* **`TRUSTED_PROXY_COUNT`** — `1` par défaut (comportement inchangé derrière un reverse proxy) ; `0` fait ignorer les en-têtes `X-Forwarded-*` et impute la tentative au vrai pair TCP. C'est important : `ProxyFix` tire `remote_addr` de `X-Forwarded-For`, donc sur une instance exposée directement un attaquant pourrait faire varier cet en-tête et le verrouillage par IP ne se déclencherait jamais.
* **Verrouillage anti-force-brute** — 5 échecs depuis une IP la verrouillent 15 minutes, vérifié AVANT tout hachage pour que les tentatives restent peu coûteuses. Temporaire par conception, pour qu'une faute de frappe ne bannisse personne définitivement. Gardé en mémoire, ce qui est sain car Gunicorn tourne en `-w 1` ; écrire en SQLite à chaque échec offrirait à un attaquant non authentifié des écritures disque illimitées.
* **Plafond global** — 20 échecs de connexion en 15 minutes, toutes adresses confondues, verrouillent aussi l'écran de login. Ferme le trou où `TRUSTED_PROXY_COUNT=1` sur une instance exposée directement permettait de faire tourner `X-Forwarded-For` sans jamais atteindre le compteur par IP. Quand il se déclenche, tout le monde est bloqué jusqu'à 15 minutes — voulu ; c'est le verrouillage par IP qui arrête un attaquant sans vous retarder.
* **Preuve de propriété legacy sur `/setup`** — si `ADMIN_PASSWORD` est encore dans `config.json`, le setup le demande une fois avant de créer le compte, puis l'efface. Ferme la fenêtre de revendication à la mise à niveau, où une table `users` vide aurait laissé le premier visiteur du réseau s'approprier une instance auparavant protégée. Une installation neuve (pas d'ancien mot de passe) reste au premier arrivé ; pré-provisionnez avec `ADMIN_PASSWORD_HASH` si ça compte.
* **`ADMIN_PASSWORD_HASH` / `ADMIN_USERNAME`** — amorçage pré-haché optionnel pour les déploiements docker-compose, généré par le nouveau `debug/hash_password.py`. Variable distincte plutôt que de surcharger `ADMIN_PASSWORD` : distinguer un hachage d'un texte en clair à l'inspection est exactement l'ambiguïté qui produit des failles d'authentification. Ignoré dès qu'un compte existe, une variable oubliée ne peut donc jamais écraser un mot de passe réel. Une valeur qui n'a pas la forme d'un hachage Werkzeug est refusée avec une erreur de journal — jamais écrite — pour qu'un mot de passe en clair collé par erreur ne crée pas un compte qu'aucun mot de passe n'ouvre.
* **Égalisation de timing** — nom inconnu et mauvais mot de passe paient exactement un KDF mémoïsé contre un hachage factice (plus de `generate_password_hash` frais à chaque miss, qui coûtait *deux* KDF et inversait le signal temporel).
* **Handshake Socket.IO** — connexions non authentifiées refusées par `return False` (forme documentée Flask-SocketIO). Garde `_reject_unauthenticated` par événement en défense en profondeur ; les emits file/couvertures ciblent uniquement le `sid` connecté.
* **Sessions** — indexées sur `user_id` ; `PERMANENT_SESSION_LIFETIME` fixé explicitement à 7 jours (le défaut silencieux de Flask était 31).

### 🩺 Exploitation
* **C57. Endpoint de liveness `GET /healthz`** — Renvoie `{"status": "ok", "version": …}` et rien d’autre. Whitelisté dans `require_login`, il continue donc de répondre `200` une fois un mot de passe défini — c’est ce qui le rend utilisable comme cible du `HEALTHCHECK` du conteneur, lequel devait auparavant interroger `/login` et accepter tout statut inférieur à 500, faute de route renvoyant `200` de façon fiable. Il exige désormais exactement `200`, ce qui permet d’attraper une régression de routage au lieu de la laisser passer pour un `404`. L’endpoint ne lit aucune configuration, n’ouvre aucune base et ne contacte jamais Kavita : il signale que l’application est vivante et route, pas que ses dépendances sont disponibles — une panne de Kavita ne peut donc pas placer un conteneur sain en boucle de redémarrage.
* **BF51. Les variables d'environnement sèment à nouveau une installation neuve** — `load_config()` générait `SECRET_KEY` / `WEBHOOK_TOKEN` et écrivait `config.json` *avant* de fusionner l'environnement : chaque clé tombait donc à sa valeur par défaut et le repli `os.getenv` n'était plus jamais atteint au boot suivant (`UI_LANG`, `KAVITA_URL`, `PROVIDER_1`, `MAX_TAGS`, …). La fusion env passe désormais en premier ; précédence `config.json` > environnement > défaut. `ADMIN_PASSWORD` n'est volontairement *pas* semé depuis l'environnement (réarmerait à jamais la preuve de propriété à usage unique).

### 🩹 Hotfix (1.6.1 — pas de montée de version)
* **BF52. Modal Config setup frais + Docker Kavita plug-and-play** — La migration 1.6.0→1.6.1 restait OK (credentials déjà dans `config.json`), mais une instance **neuve** configurée uniquement depuis la modal Config donnait souvent l’impression que les réglages Kavita « n’étaient pas écrits ». Causes : champs clé préremplis avec le sentinel `********` (autofill navigateur / `saveConfig()` sidebar à champ vide pouvaient effacer ou ne jamais poser la clé au 1er lancement), chaînes `KAVITA_*` vides dans `config.json` bloquant le seed Compose, et `localhost` depuis Docker = MetaKavita lui-même. Correctif : secrets toujours vides à l’affichage (POST vide = conserver) ; Save modale recharge, toggles sidebar sans reload ; `KAVITA_URL` / `KAVITA_API_KEY` vides replient sur l’env ; erreurs d’auth explicites (localhost / 401 / timeout / DNS / connexion / SSL) ; `/save-config` journalise et renvoie un test Kavita ; Compose + README Option A avec `extra_hosts: host.docker.internal:host-gateway` et consignes never-localhost. **Suite :** `DATA_DIR`/`CONFIG_FILE` absolus ; `save_config()` atomique (tmp+replace) + vérif post-écriture ; clés API en `type=text` + masque CSS (plus `password`) et `FormData.set` forcé côté JS.
* **Périmètre dénylist** — `DISABLED_LIBRARIES` ne s’applique plus qu’au **polling auto-sync** (pas au dashboard, batch manuel ni webhook). La dénylist ne vit plus dans `KavitaAPI.get_all_series()`, qui renvoie toujours l’inventaire complet : c’est le worker auto-sync qui filtre ses propres candidats (`select_auto_sync_candidates`). Effet de bord corrigé : le polling purgeait du cache les séries des biblios exclues comme si elles étaient orphelines. Les séries portent désormais toujours `libraryId`, pour que ce filtre ne puisse pas passer à côté. Après chaque push `:dev` : `docker pull` + `compose up -d --force-recreate --pull always`.
* **Les cases à cocher bibliothèques ne rechargent/recochent plus toutes seules** — Les cases Config → Planification sauvegardent désormais en AJAX simple (`saveConfig()`) au lieu de forcer un rechargement complet de page à chaque clic. Ce rechargement était aussi ce qui redéclenchait l'ancien auto-heal ci-dessous : décocher la dernière bibliothèque recochait donc silencieusement toutes les cases au rechargement.
* **Suppression du « heal wipe » automatique** — Le hotfix précédent réactivait automatiquement toutes les bibliothèques dès qu'une dénylist couvrait 100 % d'entre elles, à chaque chargement du dashboard, pour annuler un wipe accidentel du 1er save. Il ne pouvait pas distinguer ça d'un choix *délibéré* de tout désactiver, donc une dénylist totale volontaire ne survivait jamais à un rechargement. Le correctif côté écriture (ne toucher `DISABLED_LIBRARIES` que quand la liste complète des bibliothèques a bien été rendue) prévient déjà le wipe accidentel ; le heal est supprimé pour qu'un « tout désactiver » délibéré tienne désormais.
* **Changement de mot de passe simple** — La modal Config gagne une section « Compte » à 3 champs (`POST /account/password`) pour changer de mot de passe sans quitter l'application. Revérifie le mot de passe actuel par le même contrôle que `/login` ; un mauvais mot de passe compte comme un échec de connexion sous le verrouillage anti-brute-force existant.
* **`/batch-sync` ne retélécharge plus tout l'inventaire Kavita à chaque paquet** — L'UI découpe un batch en paquets d'environ 50 séries ; chacun rappelait `get_all_series()` (et purgeait le cache de types de bibliothèque avec). Seul le premier paquet d'un batch va désormais chercher un inventaire frais ; les suivants réutilisent cet instantané jusqu'à 15 minutes.
* **Précision de la barre de progression batch** — La barre calculait `remaining` à partir de la taille de la file de sync partagée, qui contient aussi les jobs webhook et auto-sync — un webhook déclenché en plein batch faisait bondir la barre. Des compteurs dédiés suivent désormais la progression du batch isolément du reste de la file.
* **Le nagware supporter ne se déclenche plus sur un batch sans effet** — L'invite au don apparaissait même quand toutes les séries du batch étaient déjà à jour et que rien n'avait réellement été envoyé à Kavita. Elle ne se déclenche plus que si au moins une série a vraiment été écrite.
* **Cohérence Comic Flexible (Manuel vs Auto)** — En Review Manuelle, un hit Comic faible (sous le seuil) bloquait le fallback Manga que le mode Auto aurait déclenché pour le même résultat exact. Les deux modes utilisent désormais le même critère « aucun hit fort » ; le mode Manuel garde quand même les candidats Comic faibles sous la main si le fallback Manga ne trouve rien non plus.
* **Review Manuelle : liste de séries + tout accepter + lien Kavita** — Une nouvelle vue liste permet de sauter directement à une série en attente précise au lieu de parcourir la file une par une, plus une action de masse « confirmer tout ce qui dépasse un seuil » (défaut `0.60`, même chemin « confirmer sans éditer » qu'un pick manuel — jamais un nouveau déclencheur de scraping). L'écran pick/édition gagne aussi un lien « voir dans Kavita » pour vérifier qu'on valide la bonne série avant de confirmer.
* **Correction de la course sur le retry de scellement différé** — Le retry en arrière-plan qui scelle une série `NEEDS_RELOCK` réclame désormais le même verrou par série qu'un re-scrape manuel, et s'annule si cette série est déjà traitée ailleurs, au lieu de risquer une course avec elle.
* **Plus de flash du récap pendant qu'un batch tourne encore** — Terminer la file de Review Manuelle en cours alors que son batch scrapait encore d'autres séries affichait le récap pendant quelques secondes, avant d'être brutalement ramené sur l'écran « pick » dès l'arrivée de la série suivante. Le récap ne s'affiche désormais qu'une fois le batch réellement terminé ; en attendant, une file vide affiche le masque d'attente existant.
* **Stop batch ne jette plus les jobs webhook/auto-sync** — `drain_sync_queue()` vidait entièrement la file de sync partagée : un événement webhook ou un candidat auto-sync présent en file au moment précis du clic sur Stop disparaissait silencieusement avec le reste du batch. Seuls les items tagués batch sont désormais retirés ; le reste est remis en file.
* **Un second batch concurrent est refusé au lieu de corrompre le premier** — Lancer un batch depuis deux onglets (ou un double-clic malheureux) remettait à zéro les compteurs de progression du batch déjà en cours, faussant sa barre et le `real_sends` de son nagware. `/batch-sync` renvoie désormais `409` pour un nouveau batch tant qu'un autre est encore actif.
* **Le tout-accepter de la Review Manuelle affiche ses échecs individuels** — Le retour du bulk-accept ne donnait qu'un compteur `accepted`/`skipped` ; une série dont l'écriture Kavita échouait pendant l'opération disparaissait silencieusement dans le « skipped ». Les échecs sont désormais listés par nom avec leur erreur.
* **Les badges de statut live ne parsent plus du texte de log traduit** — Le dashboard devinait le badge live d'une série en cherchant des mots-clés français/anglais dans la ligne de log brute (« réussi », « déjà à jour », « introuvable »...), un mécanisme qui pouvait cesser de fonctionner silencieusement si le wording ou la langue changeait. `enrich_series()` émet désormais un événement `series_status` typé pour chaque issue (`NOT_FOUND`, `PENDING_REVIEW`, `COMPLETED` déjà-à-jour), et le dashboard s'appuie exclusivement là-dessus.

### ✨ Points forts
* **Mode Review Manuelle (C29)** — File de scrape silencieuse : les candidats arrivent en PENDING_REVIEW sans écrire dans Kavita. Modale de pick avec gradient de score, touches 1–3, bande faible (sous seuil) en rouge ; édition optionnelle avant confirm ; **étape choix de couverture** avant confirm ; télémétrie lifetime + récap de session + **hauts-faits** sur `/stats`. Suite intégrité : une review par série, park/skip/confirm atomiques, batch sans séries garées, apply sous verrou, SQLite WAL, sync file Socket.IO.
* **Baromètre de fiabilité** — Case sidebar + curseur de seuil d’acceptation (`0.30`–`1.00`, défaut `0.60`). Off = défaut testé fixe. Config : `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD` ; scrapers via `get_match_accept_threshold()`.
* **BDTheque.com (comics)** — Nouveau scraper `BDTHEQUE` pour https://www.bdtheque.com/ (pas Bédéthèque / bedetheque.com) : recherche AJAX séries, parse fiche (staff, éditeur, genres, statut, couverture), Magic Input `/series/{id}/{slug}`, scoring unifié, recherche de covers. Distinct de `BEDETHEQUE`. Couvertures : toujours `/repupload/T/{couv}` (typeahead site) ; fiche série lit `data-echo` (lazy-load echo.js) au lieu de `placeholder.png`.
* **Filtre de bibliothèques Kavita** — Config → Planification : cases `DISABLED_LIBRARIES`. Vide = auto-sync toutes ; nouvelles biblios actives. S’applique au **polling auto-sync uniquement** (dashboard, batch manuel et webhook voient toutes les biblios).
* **MyAnimeList API officielle** — Nouveau scraper `MAL` (remplace Jikan mort) : auth `X-MAL-CLIENT-ID` via `MAL_API_KEY` (Client ID sur https://myanimelist.net/apiconfig). Manga + Book (light novels), Magic Input `myanimelist.net/manga/{id}`, scoring unifié, couvertures CDN. Pas d’OAuth utilisateur pour search/details.
* **Provider Wikidata (live uniquement)** — Nouveau scraper `WIKIDATA` pour Manga / Comic / Book via SPARQL + Entity API, Magic Input `Q…` / URLs wikidata.org, scoring unifié, couvertures Commons. Mapping claims→MetaKavita partagé (`scrapers/wikidata_map.py`). Utile en fallback / ISBN / IDs croisés — pas un remplacement d’AniList. **API live seulement pour le moment** — pas de mode SQLite / dump hors-ligne dans cette release.
* **Comic (Flexible) / ID 5 (C35)** — Les bibliothèques mixtes Kavita « Comic Flexible » ne sont plus traitées comme du Comic strict. MetaKavita interroge d’abord `COMIC_PROVIDER_*`, puis bascule sur les providers Manga (`PROVIDER_*`) si aucun hit utile. La recherche manuelle de couvertures interroge Comic + Manga.
* **Statistiques ludiques (C7)** — `/stats` restylée avec Chart.js (donut + barres), compteurs lifetime (`series_enriched` / `matches_won` / `series_missed`), KPI taux de hit, ~24 cartes fun, chapitre **hauts-faits Manual Review**. `ENABLE_PLAYFUL_STATS` ON par défaut. Compteurs live dans la topbar (3 KPI lifetime + session remise à 0 à la fermeture d’onglet via `sessionStorage`). Événement Socket.IO `enrichment_stats` pendant les batchs.
* **`/stats` en récit scroll** — Parcours premium chapitre par viewport (esprit Leetify / landing GPU) : score hero, lifetime, temps gagné, santé du cache, craft manuel, providers + podium, puis tableau récapitulatif. Reveals + count-up ; accents couleur par chapitre.
* **Polish dashboard** — Même langage visuel que `/stats` (**Bricolage Grotesque**, accents teal/sky, topbar glass, lignes de séries plus nettes) sans alourdir le workflow.
* **Estimations organiques** — Le temps gagné ne reste plus à `0 min` si la télémétrie lifetime est en retard sur le cache : les métriques fun utilisent `max(lifetime, completed / wins providers)`. Modèle = ~6 min/série + ~1,5 min/match utile ; affichage possible en jours.
* **Scellage des champs / `NEEDS_RELOCK`** — Si l’écriture Kavita réussit mais que le re-lock C# Lock Guard échoue (soft-success / BF19), la série n’est plus marquée simplement `COMPLETED`. Statut **`NEEDS_RELOCK`** (badge orange « À sceller »), retry seal différé (~2 s, sans re-scrape), bouton 🔒, filtre, et `POST /api/series/<id>/seal-locks` (+ bulk). Seal OK → `COMPLETED`.
* **Pubs supporter (tip → Buy Me a Coffee)** — Overlays ludiques rares (max 1–2/j, honeymoon 7 j, silence honor 30 j) après moments chauds (fin de batch / récap MR riche), plus CTA café natif dans le récap MR. Pas de paywall, pas de clé licence. Classe `.license` conservée pour un futur silence.

### 🧰 QoS & granularité batch
* **Sélection reprise-friendly** — Une série OK (✅ / déjà à jour) se décoche automatiquement. Les IDs cochés sont persistés en `localStorage` par bibliothèque (`mk_batch_selection:*`) : refresh / coupure réseau ne vident plus la sélection ; les filtres ne décochent plus les lignes masquées.
* **Stop vs envoi par paquets** — Stop coupe la boucle UI ×50 `/batch-sync` (`AbortController`) et désarme l’enqueue serveur jusqu’au premier paquet du prochain batch (`resume_enqueue=true`), pour qu’un chunk encore en vol ne remplisse plus la file après le drain.
* **Barre de progression batch** — Au-dessus des boutons d’actions : jauge `fait / total` pilotée par Socket.IO `batch_progress` (`remaining` + titre actif depuis le `qsize()` du worker). Le total est fixé au lancement (sélection UI) ; la barre disparaît en fin de lot (~1,5 s) ou au Stop/drain.
* **Masque de champs ciblés (batch)** — Sous-menu sidebar pliable : filtre d’écriture éphémère pour le prochain batch uniquement (ne modifie pas les overrides série). Tout laisser coché = respecter le masque de chaque série. Décocher un champ → CSV envoyé à `/batch-sync` (4-tuple file, `targeted_fields_override`).
* **Tout cocher / Tout décocher** — Sidebar (masque batch) et panneau override de chaque série.

### 🐛 Polish UI
* **Options de Scraping pliables** — Clic sur le titre sidebar pour afficher/masquer toute la carte stratégie (ouverte par défaut ; état ouvert/fermé persisté en `localStorage` sous `mk_scraping_options_open`).
* **Scroll `/stats`** — Contournement du layout dashboard `100vh` + `overflow: hidden` pour que la page stats scrolle à nouveau sur desktop.

### 🛠️ Intégrité Review Manuelle (suite C29)
* **Confirmer avant écriture (batch auto)** — Avec Manual Review **off**, la même case « Éditer avant confirmation » active `CONFIRM_BEFORE_WRITE` : le scrape auto gare un preview (`awaiting_confirm`) et ouvre le panneau d’édition ; Kavita n’est écrit qu’au confirm. Le worker n’est pas bloqué ; désactiver l’option purge uniquement les parks auto-confirm.
* **Une review par série** — index unique sur `pending_reviews.series_id` ; le park remplace la ligne existante au lieu d’empiler des doublons au re-batch.
* **Park / skip / confirm atomiques** — `park_pending_review` et `close_pending_review` écrivent la file et `series_cache.status` dans une seule transaction SQLite (plus de COMPLETED/PENDING avec une ligne orpheline après un crash).
* **Court-circuit « déjà à jour »** — Laisse les séries `PENDING_REVIEW` intactes ; sur `NEEDS_RELOCK` tente un seal seul puis COMPLETED ; sinon passe en COMPLETED et purge toute review orpheline.
* **Batch global sans séries garées** — Un batch sans sélection explicite ne re-scrape plus `PENDING_REVIEW` (une série cochée peut toujours être rejouée ; le park reste idempotent).
* **Apply sous le verrou par série** — `apply_manual_review` partage `_processing_lock` avec `enrich_series` / research, pour qu’un confirm ne course plus un scrape concurrent du même ID.
* **SQLite WAL + busy_timeout** — Toutes les connexions `db_manager` passent en WAL avec un busy timeout de 30 s, ce qui réduit les `database is locked` intermittents sous charge worker + REST + Socket.IO.
* **Mode off / ignore / orphelins** — Désactiver `MANUAL_REVIEW_MODE` purge la file ; ignorer une série efface sa review ; `clean_orphaned_cache` nettoie aussi les reviews orphelines.
* **Sync file côté frontend** — `loadQueue` sérialisé, ancrage `currentReviewId`, gardes in-flight sur pick/confirm/skip, et handlers `confirmed` / `skipped` / `refreshed` / compteur à 0 alignent la modale sur le serveur.
* **Phase couverture** — Étape optionnelle après le pick pour chercher/sélectionner une cover avant confirm ; upload explicite même si `AUTO_COVER` est off.
* **Tests** — `tests/test_manual_review.py` couvre l’idempotence du park, la préservation au skip anticipé, la purge d’orphelins, le clean cache et le flow auto-confirm ; `tests/test_needs_relock.py` couvre soft-fail → `NEEDS_RELOCK`.

---

## [1.6.0] - 2026-07-26 (Smart Scoring, Localized Titles, Help Menu, Self-Host Polish & Hardening)

EN
### ✨ Highlights
* **Smart Scoring (C45)** — Providers compete by match score; the best match wins (sidebar toggle). Provider #1 seeds ISBN/author context, then the others run in parallel. Smart Completion fills gaps from highest score to lowest. Off = classic list-order fallback.
* **Localized Titles Policy (C53, issue #12)** — Control Kavita `localizedName` only (never rewrite Series `name`). Modes: `all` (default, titles joined with `" / "`), `prefer` (language tags), `none`. Global config + per-series `alt_title_langs`. AniList / MangaDex / Kitsu emit structured `titles[]`.
* **Help / About / Docs (C52)** — Topbar Help menu: About modal, GitHub documentation links, in-app release notes. Kavita+ support next to Buy me a coffee (opens this instance’s `settings#admin-kavitaplus`).
* **MangaBaka Book / LN (C47, thanks LazyGeniusMan)** — Official Book support (`schema=full`, `type=novel`), stronger tag/genre/MAL parsing.
* **Self-host & Docker** — `CORS_ALLOWED_ORIGINS` (C46), `KAVITA_EXTERNAL_URL` (C48), configurable `KAVITA_HTTP_TIMEOUT` + soft-success on RE-LOCK timeout (BF19), `MAX_TAGS` / `MAX_GENRES` caps (C49 / C51).

### 🧠 Matching & Scrapers
* **Unified scoring matrix** — MangaDex, MangaUpdates, Manga-News, Shikimori, Kitsu, ComicVine, and Bédéthèque now use `score_candidate()` + author cross-check (fewer false positives). Centralized `MATCH_ACCEPT_THRESHOLD = 0.60`.
* **Community scrapers** — Opt-in `uses_unified_scoring`; `_safe_match_score()` never crashes enrichment on a bad score. Sideload example kept under `data/scrapers/`.
* **Registry hardening** — No re-registration of imported classes; explicit warning on duplicate scraper IDs.
* **Forced-ID fallback (BF22)** — After a failed direct ID/URL lookup, MetaKavita automatically retries a title search.

### 🏠 Self-Hosting & Power-User Settings
* **`CORS_ALLOWED_ORIGINS`** — CSV of explicit origins for Flask + Socket.IO (HTTPS self-hosts / Traefik). Empty = Same-Origin; `*` rejected.
* **`KAVITA_EXTERNAL_URL`** — Public UI link to Kavita vs internal `KAVITA_URL` for Docker API calls.
* **`KAVITA_HTTP_TIMEOUT` (default 60s)** — If the write succeeds but RE-LOCK times out, count as success with a warning; one capped RE-LOCK-only retry.
* **`MAX_TAGS` / `MAX_GENRES`** — Caps via env / `config.json` (defaults 15 / 5). No UI — power-user only (`get_max_tags()` / `get_max_genres()`).
* **`debug/benchmark_batch.py`** — Wall-clock batch benchmark (dry-run by default; `--live --i-know` for real writes).

### 🏗️ Architecture & Reliability
* **Modular backend** — Blueprints (`routes/`), `services/`, `models.py` (`SeriesOverride`), thin `app.py` composition root (C32).
* **Modular frontend** — Seven plain `<script>` files + Jinja partials (no bundler). Legacy `script.js` removed.
* **pytest + CI** — Full non-regression suite with GitHub Actions on every push/PR.
* **Concurrency** — Per-series enrich lock; `CONFIG_LOCK` on config RMW; atomic scraper rate-limiter.

### 🐛 Bug Fixes
* **Publisher preference never saved (BF18)** — Per-series `publisher_pref` is now persisted and respected.
* **Manual cover vs auto-cover** — Cover checkbox unchecks after manual apply; cover-only saves no longer reset status to `PENDING` / un-ignore series; targeted-fields membership uses a real list split.
* **Partial Kavita payloads (BF20)** — External-ID updates GET-merge like `localizedName` (no alt-title wipe / lock reset).
* **Silent general-update failure (BF26)** — Metadata OK + general fail is reported, not a fake `COMPLETED`.
* **Wrong DTO for `localizedName` (BF30)** — Deep metadata reads it from `GET /api/Series/{id}`.
* **Comic/Book env ignored (BF23)** — `COMIC_PROVIDER_*` / `BOOK_PROVIDER_*` / `RESET_CONTEXT_ON_FORCE` load from Docker env again.
* **Characters / frontend / queue / config** — Defensive character parsing (BF27); fetch `res.ok` handling (BF31); sync `task_done()` (BF32); corrupt `config.json` no longer overwritten (BF34); `TARGET_LANG` not forced every enrich (BF35); changelog modal HTML-escaped (BF28).

### 🔒 Security & Hardening
Full application audit (BF20–BF45 + C50). Empty `ADMIN_PASSWORD` for open LAN backoffice remains intentional.
* **CSRF + session cookies (C50)** — Token on mutating POSTs; `SameSite=Lax` + `HttpOnly` (`SESSION_COOKIE_SECURE` optional).
* **SSRF / covers / proxy** — Shared URL allowlist; private IPs blocked; up to 3 redirects with hop re-validation; safe `image/*` only (BF21/BF25 → BF43/BF44).
* **XSS** — Cover modal built with DOM APIs / `textContent` (BF24).
* **Secrets** — No hardcoded `SECRET_KEY` fallback (BF37); API key prefix not logged (BF38); credential-safe exception logs (BF42); revoked hardcoded Hardcover debug token.
* **Cleanup** — Dead MAL / Nautiljon modules removed (BF36); ComicVine `proxy_domains` narrowed (BF40).

---

FR
### ✨ Points forts
* **Smart Scoring (C45)** — Les fournisseurs sont départagés par score ; le meilleur match gagne (interrupteur sidebar). Le provider #1 amorce le contexte ISBN/auteurs, puis les autres tournent en parallèle. La Complétion intelligente comble les trous du score le plus haut au plus bas. Désactivé = fallback classique par ordre de liste.
* **Politique des titres localisés (C53, issue #12)** — Contrôle de Kavita `localizedName` uniquement (jamais de réécriture de Series `name`). Modes : `all` (défaut, titres joints par `" / "`), `prefer` (tags de langue), `none`. Config globale + `alt_title_langs` par série. AniList / MangaDex / Kitsu émettent des `titles[]` structurés.
* **Aide / À propos / Docs (C52)** — Menu Aide du topbar : modal À propos, liens documentation GitHub, nouveautés in-app. Soutien Kavita+ à côté de Buy me a coffee (ouvre `settings#admin-kavitaplus` de *cette* instance).
* **MangaBaka Book / LN (C47, merci LazyGeniusMan)** — Support Book officiel (`schema=full`, `type=novel`), parsing tags/genres/MAL renforcé.
* **Self-host & Docker** — `CORS_ALLOWED_ORIGINS` (C46), `KAVITA_EXTERNAL_URL` (C48), `KAVITA_HTTP_TIMEOUT` configurable + soft-success si RE-LOCK timeout (BF19), plafonds `MAX_TAGS` / `MAX_GENRES` (C49 / C51).

### 🧠 Matching & Scrapers
* **Matrice de scoring unifiée** — MangaDex, MangaUpdates, Manga-News, Shikimori, Kitsu, ComicVine et Bédéthèque passent par `score_candidate()` + contrôle d’auteur (moins de faux positifs). Seuil centralisé `MATCH_ACCEPT_THRESHOLD = 0.60`.
* **Scrapers communautaires** — Opt-in `uses_unified_scoring` ; `_safe_match_score()` empêche tout plantage sur un score mal formé. Exemple sideload conservé dans `data/scrapers/`.
* **Registre** — Plus de ré-enregistrement des classes importées ; avertissement explicite en cas d’ID en double.
* **Repli après ID forcé (BF22)** — Échec d’un lookup ID/URL → nouvelle tentative automatique en recherche titre.

### 🏠 Self-hosting & réglages avancés
* **`CORS_ALLOWED_ORIGINS`** — Origins CSV pour Flask + Socket.IO (self-host HTTPS / Traefik). Vide = Same-Origin ; `*` rejeté.
* **`KAVITA_EXTERNAL_URL`** — Lien UI public vers Kavita vs `KAVITA_URL` interne pour l’API Docker.
* **`KAVITA_HTTP_TIMEOUT` (défaut 60s)** — Écriture OK mais RE-LOCK en timeout → succès avec warning ; un retry plafonné du seul RE-LOCK.
* **`MAX_TAGS` / `MAX_GENRES`** — Plafonds via env / `config.json` (défauts 15 / 5). Pas d’UI — power-user (`get_max_tags()` / `get_max_genres()`).
* **`debug/benchmark_batch.py`** — Benchmark wall-clock de batch (dry-run par défaut ; `--live --i-know` pour écritures réelles).

### 🏗️ Architecture & fiabilité
* **Backend modulaire** — Blueprints (`routes/`), `services/`, `models.py` (`SeriesOverride`), `app.py` mince (C32).
* **Frontend modulaire** — Sept fichiers `<script>` + partials Jinja (sans bundler). Ancien `script.js` retiré.
* **pytest + CI** — Suite de non-régression + GitHub Actions à chaque push/PR.
* **Concurrence** — Verrou d’enrichissement par série ; `CONFIG_LOCK` sur la config ; rate-limiter scrapers atomique.

### 🐛 Correctifs
* **Préférence d’éditeur jamais sauvée (BF18)** — `publisher_pref` par série désormais persisté et respecté.
* **Couverture manuelle vs auto-cover** — Case « Couverture » décochée après choix manuel ; une appli couverture seule ne remet plus le statut en `PENDING` / ne désignore plus ; appartenance des champs ciblés via découpage en liste.
* **Payloads Kavita partiels (BF20)** — Mise à jour des IDs externes en GET-merge (plus de wipe de titres alt / verrous).
* **Échec silencieux de l’update général (BF26)** — Metadata OK + général KO → erreur signalée, pas de faux `COMPLETED`.
* **Mauvais DTO pour `localizedName` (BF30)** — Lecture via `GET /api/Series/{id}`.
* **Env Comic/Book ignorée (BF23)** — `COMIC_PROVIDER_*` / `BOOK_PROVIDER_*` / `RESET_CONTEXT_ON_FORCE` rechargés depuis Docker.
* **Personnages / frontend / file / config** — Parsing personnages défensif (BF27) ; gestion `res.ok` (BF31) ; `task_done()` sync (BF32) ; `config.json` corrompu non écrasé (BF34) ; `TARGET_LANG` non forcé à chaque enrich (BF35) ; changelog échappé HTML (BF28).

### 🔒 Sécurité & durcissement
Audit applicatif complet (BF20–BF45 + C50). `ADMIN_PASSWORD` vide (backoffice LAN ouvert) reste un choix volontaire.
* **CSRF + cookies de session (C50)** — Jeton sur les POST mutatifs ; `SameSite=Lax` + `HttpOnly` (`SESSION_COOKIE_SECURE` optionnel).
* **SSRF / couvertures / proxy** — Allowlist d’URL partagée ; IPs privées bloquées ; jusqu’à 3 redirects re-validés ; MIME `image/*` uniquement (BF21/BF25 → BF43/BF44).
* **XSS** — Modal couvertures via APIs DOM / `textContent` (BF24).
* **Secrets** — Plus de fallback `SECRET_KEY` hardcodé (BF37) ; préfixe de clé API non logué (BF38) ; logs d’exceptions sans fuite (BF42) ; jeton Hardcover debug révoqué.
* **Nettoyage** — Modules morts MAL / Nautiljon retirés (BF36) ; `proxy_domains` ComicVine restreint (BF40).

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