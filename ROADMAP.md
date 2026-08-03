# 🚀 MetaKavita - Roadmap & To-Do List

**Concept:** Metadata scraping and enrichment tool for Kavita (alternative to Komf), designed for lightweight, self-hosted deployment.
**Philosophy:** Lightweight, pragmatic, highly secure, and optimized for Manga, Comics & Literature.

---

## Sommaire / Table of Contents
1. [🇺🇸 English Roadmap](#-english-roadmap)
2. [🇫🇷 Feuille de Route Française](#-feuille-de-route-française)

---

## 🇺🇸 English Roadmap

### 🔮 Backlog & Future Features (To-Do)
- [x] **C29. Interactive Manual Batch Mode (QoS) / Manual Review (v1.6.1):** Park-queue Manual Review shipped — silent scrape → `PENDING_REVIEW` → pick / edit / cover modal; no auto-write until confirm. See Latest Releases. (Event-pause worker variant abandoned — see Parked.)
- [x] **C30. Francophone Book Scrapers (v1.6.3):** Babelio, Decitre, and SensCritique ship in core (no API keys). See Latest Releases.
- [x] **C60. Core comics / manga promotions (v1.6.3):** ANN, LoCG, Planète BD, and Metron (`METRON_API_KEY`) promoted from the community repo into the Docker image.
- [x] **C61. Scraper Manage + Community Store (v1.6.3):** `/manage-scrapers` + `/scraper-store` (Help); registry from `data/scrapers/`; catalog sha256; `DISABLED_SCRAPERS`; hub tabs + community beta notice. See Latest Releases.
- [ ] **C31. Kavita Deduplication Tool:** Dedicated UI panel to detect and merge duplicate series or volumes in Kavita.
- [ ] **C33. Browser Extension "MetaKavita Companion":** Floating widget overlay directly on top of the Kavita Web UI to trigger MetaKavita updates natively.
- [ ] **C39. Offline Scraper Mode (Local DB / Dumps):** Optional local SQLite subset for Wikidata (or similar) when API rate limits or offline labs matter. (Wikidata itself is Magasin-only since v1.6.3.)
- [ ] **Volume / issue metadata (community ask #27):** Per-volume / comic-issue enrichment — `BaseScraper.scopes` already reserves `volume`; pipeline + UI still open.
- [x] **C40. Support the Developer (Donations) (v1.6.1):** Buy Me a Coffee link in the sidebar / topbar / About, rare playful supporter overlays, and café CTA in Manual Review recap (no paywall / license keys).
- [ ] **B4. Narrow `seal_series_locks` scope:** After soft-fail re-lock (`NEEDS_RELOCK`), seal currently sets every `*Locked` + forces `localizedNameLocked` (and often `formatLocked`), including fields MetaKavita never wrote. Rare path — feature exists for very slow hosts; prefer raising `KAVITA_HTTP_TIMEOUT` (up to ~600s) over seal surgery. Ideal later: seal only locks from the last write / active mask.

### 🧊 Parked (no active work)
- [ ] **C29 follow-up. Event-pause worker — parked / superseded:** Original QoS idea (emit candidates over WebSockets, block the worker on `eventlet.event.Event` until pick/skip). **C29 Manual Review** already parks series as `PENDING_REVIEW` and lets the batch continue; the user reviews asynchronously. **C63** durable batch queue covers pause / resume / restart. A synchronous Event-pause path would freeze large batches on every ambiguous match and duplicate that UX — not worth a second mode.
- [ ] **C8. Resiliency & exponential 429 backoff — parked:** Per-provider `throttle_provider` / **C34** already spaces calls by each scraper’s `rate_limit` (idle = no wait). No field reports of systemic 429s on large batches when staying under those delays; Open Library already has a simple 429 pause. Full exponential-backoff machinery deferred unless real bans appear. Optional later: light `Retry-After` / single retry — not a product priority.

---

### ✨ Latest Releases (v1.5.6 to v1.6.5)
- [x] **BF103. Manual Review cover pick hardening (v1.6.5):** Reopen / queue jump restores cover phase when cover pick is on; explicit MR cover upload removes `cover` from `targeted_fields` (parity with `/update-cover` via `protect_manual_cover_field`).
- [x] **C64. Guided first-run setup wizard (v1.6.4):** `/setup` 6-step onboarding (account, Kavita + `ROOT_PATH`, languages, options + Auto-Sync 6 h, API keys, cascades); non-blocking Kavita probe; Skip = ready defaults; logged-in replay without account step (Help menu).
- [x] **C62. Core scrapers `is_core` + boot sync (v1.6.4):** catalog `is_core` from community GitHub → `data/scrapers/` (sha256); image package fallback if offline; `AUTO_UPDATE_CORE_SCRAPERS` (default on) or banner + `POST /api/scrapers/core-updates/apply`.
- [x] **C63. Persistent batch queue (v1.6.4):** SQLite queue + boot hydrate; Add / Pause / Resume / remove / clear; Stop cancels durable queue.
- [x] **BF91. MangaBaka cover CDN allowlist (v1.6.4, issue #31, thanks SqueezedByte):** `proxy_domains` includes `images`/`cdn` `.mangabaka.dev` and `.org`.
- [x] **BF92. MangaBaka cover pick stays on allowlist (v1.6.4):** `_pick_cover_url` / `fetch_covers` fall back to MangaBaka imgproxy when `cover.raw` is third-party.
- [x] **BF93. Dashboard series search no freeze (v1.6.4, issue #30, thanks angusmaul):** `data-search-title` + `is-filtered-out` + 150 ms debounce (no `innerText` / per-item `style.display`).
- [x] **BF94. Visible-only batch + prefix search (v1.6.4):** filter keeps checks; batch/ignore use visible checked only; “select all visible” replaces selection; search prefix by default, optional inside-title.
- [x] **BF95. `ADMIN_PASSWORD` env warning once per boot (v1.6.4, issue #31, thanks SqueezedByte):** actionable deprecation message; no per-request spam.
- [x] **BF96. Lazy Options panels + selection Set (v1.6.4, issue #30, thanks angusmaul):** no per-row override DOM; BF94/C63 selection index; `content-visibility`.
- [x] **BF97. Virtual series list (v1.6.4, issue #30):** ≥120 series → JSON bootstrap + scroll window; filtered selection for batch/queue.
- [x] **BF98. Queue bar labels + Expand-all warning + resume-on-run (v1.6.4):** Run selection / Open queue; mid-batch Add to waiting list; Run clears pause; Expand-all confirms on large filters.
- [x] **BF99. Denser series rows + toolbar layout (v1.6.4):** shorter cards, larger titles, colored Search/Filters groups; Select all in toolbar head (stable vs selected badge).
- [x] **BF100. Compact Options override panel (v1.6.4):** denser main row, chip-style targeted fields; tests `test_override_panel_ui.py`.
- [x] **BF101. Batch progress + virtual list reinit (v1.6.4):** no hide on all-dupe append; resume bump totals; loadLibrary re-inits SeriesList; cumulative offsets for open Options.
- [x] **BF102. SMART_COMPLETION non-adult age fill (v1.6.4):** Auto hole-fills `safe`/`suggestive`/`mature` only; NSFW secondary ages blocked; skip Pending age when Age field active; `log_age_write_diag`.
- [x] **C30 / C60. Seven community scrapers in core (v1.6.3):** Babelio, Decitre, SensCritique, ANN, LoCG, Planète BD, Metron; defaults BOOK_3=Babelio, COMIC_3=LoCG for new installs.
- [x] **C61. Manage scrapers + Magasin (v1.6.3):** Install / update / delete community scrapers; core disable-only; sha256 catalog; retired / off-store flags; hub tabs Manage · Store · Diagnostics + community beta notice.
- [x] **Diagnostics cascade probe (v1.6.3):** `/diagnostics` auto-probes active Config cascade providers after preflight; “Test cascade” / “Test all”; `POST /api/scrapers/probe-all?scope=active|all`.
- [x] **MR Sources may fill `age_rating` (v1.6.3):** Checked Manual Review Sources hole-fill empty age (`fill_age_rating=True`); Auto SMART_COMPLETION kept BF69 (no age backfill) until BF102.
- [x] **BF90 / BF88 / BF87 Magasin + MR Sources hardening (v1.6.3):** install rollback, orphans, atomic registry reload; MR Sources survive reopen/confirm; confirm `include_providers` semantics.
- [x] **BF86 / BF85 / BF84 (v1.6.3):** Registry binds loaded modules; Planète BD bare numeric ID probe; cover display hosts follow `requires_proxy`.
- [x] **BF83. INFO for CSRF reject + lockout-active reject (v1.6.3, thanks angusmaul):** distinguish wrong password / CSRF / lockout in Live Logs.
- [x] **BF82. INFO on every failed login attempt (v1.6.3, thanks angusmaul):** username + IP + counter each try; lockout WARNING unchanged.
- [x] **BF81. Neutral age crans + hentai/futanari → x18 (v1.6.3, #25/#29):** `r18`/`x18` (+ aliases); central escalate-to-x18 on hentai/futanari tags even if provider age set; NSFW demote still Auto-tie only.
- [x] **BF80. Kitsu R → mature / Mature 17+ (v1.6.3, issue #29, thanks angusmaul):** Stop collapsing Kitsu `R`+`R18` into `pornographic`; add `mature→10`; `R→mature`, `R18→pornographic`.
- [x] **BF79. Proxy / lockout boot logs follow `UI_LANG` (v1.6.3, #26, thanks angusmaul):** TRUSTED_PROXY / SECRET_KEY ephemeral / lockout warnings via `get_ui_translations`.
- [x] **BF78. Confirm/MR preview dedupes tags & genres (v1.6.3, #24, thanks angusmaul):** same order-preserving dedupe as Kavita payload before join.
- [x] **BF77. Auto tie-break genre/tag adult signals (v1.6.3, issue #25, thanks angusmaul):** `_is_explicit_adult` also treats `hentai` / `futanari` genres & tags (MangaBaka empty-age mirror); prefer-safe log only if winner is non-adult.
- [x] **C59. Community scrapers repository (v1.6.2):** Official plug-and-play scrapers live in [`community-scraper-metakavita`](https://github.com/raukorim-bot/community-scraper-metakavita). Linked from Help menu, README EN/FR, and `CUSTOM_SCRAPERS.md` (still trust/read before install).
- [x] **Scraper diagnostics UI (v1.6.2):** `/diagnostics` + probe APIs for Internet/Kavita preflight and per-scraper metadata/covers health.
- [x] **BF56. Age safeguarding — no invented Everyone (v1.6.2):** Scrapers without an authoritative age signal omit `age_rating` instead of hardcoding `safe`; BDTheque maps Adulte/Érotique → `erotica` (not Teen), and « Ados - Adultes » stays `suggestive`. Prevents locking wrong Everyone/Teen on adult material (follow-up to BF53).
- [x] **BF58. Format keyword tokens (v1.6.2):** `resolve_kavita_format_enum` no longer uses substring match (`COMIC BOOK`→Novel, `MUST`→Comic); exact scraper tokens + word split, Comic before Book.
- [x] **BF59. Invented FINISHED status omitted (v1.6.2):** ComicVine / Hardcover / Google Books / OpenLibrary no longer hardcode `status: FINISHED`; omit like BF56 age.
- [x] **BF60. Manga-News cover label i18n (v1.6.2):** `(Série)` / `(Tome)` follow `UI_LANG` via `self.t()` (same class as BF55).
- [x] **BF61. Valid int `releaseYear` only (v1.6.2):** Skip write/lock when year is not an int in 1000–2100 (no string years from edit overlay).
- [x] **BF62. Silent scraper/enrichment exceptions logged (v1.6.2):** Business `except Exception: pass` → `logging.debug` + `safe_exc_str` (ComicVine / Google Books / MangaBaka / orphan purge); `session.close()` cleanups stay silent.
- [x] **BF63. Webhook UI prefers header token (v1.6.2, audit B15):** Config Modal shows `/webhook` + separate token (no `?token=` copy-paste); docs mark query as legacy; server still accepts it; once-per-process warning when query used without header.
- [x] **BF64. `TARGET_LANG` from `UI_LANG` when unset (v1.6.2, audit B17):** Default `TARGET_LANG=EN` (was FR vs `UI_LANG=en`); absent file+env → derive `en`→`EN` / `fr`→`FR`; file > env > derived; no migration of existing explicit values.
- [x] **BF65. Dead-code cleanup / orphan batch (v1.6.2):** Removed unused helpers/imports (`increment_provider_win`, `delete_pending_review`, `record_manual_skip_telemetry`, dead scraper helpers/imports), migrated callers off legacy wrappers (`save_pending_review`, `save_forced_overrides`), dropped unused denylist helpers, pruned high-confidence dead i18n keys, and stopped hardcoding Kavita API key in `debug_ultime.py`.
- [x] **BF66. Tag/genre dedupe before MAX caps (v1.6.2, issue #24):** Case-insensitive order-preserving dedupe in `build_kavita_payload` before tag/genre slices.
- [x] **BF67. Soft atomicity for general fields (v1.6.2, issue #24):** `update_series_general` only after successful metadata write.
- [x] **BF68. Score-tie prefers safer age (v1.6.2, issue #25):** Auto demotes pornographic/erotica only on equal score (with log); MR unchanged; CBW+tie → awaiting_pick.
- [x] **BF55. ComicVine summary i18n (v1.6.2 hotfix, thanks ThoughtzThruKeyz, #26):** Decorative summary/cover labels (`[Series]` / `[Synopsis]` / …) follow `UI_LANG` instead of always writing French into Kavita.
- [x] **BF57. Series language gated by targeted fields (v1.6.2):** `language` / `languageLocked` only written when `language` is in the active mask (included in `ALL` by default).
- [x] **BF54. Comic run-year in search title (v1.6.2 hotfix, thanks angusmaul):** Comic `clean_title` now strips Kavita Flexible `(YYYY)` / `(YYYY-)` from the search string; year is re-injected into `existing_metadata` and used by ComicVine `start_year` ranking. Avoids Comic miss → Manga false-positive on names like `Batman (2025)`. Manga fallback not score-penalized.
- [x] **BF53. Age rating enum map (v1.6.2 hotfix, thanks angusmaul):** `AGE_RATING_MAP` wrongly used MangaDex ordinals `1–4` instead of Kavita's `AgeRating` enum, so `pornographic` was written as **G** (and locked). Remapped to Everyone/Teen/R18+/X18+ (`3/8/12/14`); docs + regression test.
- [x] **BF52 follow-ups (v1.6.1, no bump):** Simple account password change (`POST /account/password`, re-verified through `/login`'s check + lockout); library checkboxes save via AJAX instead of forcing a reload (was also re-triggering an over-eager "wipe heal", now removed — a deliberate "disable every library" sticks across reloads); `/batch-sync` reuses one Kavita inventory snapshot per batch instead of refetching it per ~50-series chunk; batch progress bar and the supporter nag now track dedicated counters isolated from webhook/auto-sync queue noise, and the nag skips no-op batches (all series already up to date); Comic Flexible's Manga fallback now triggers the same way in Manual Review as in Auto; Manual Review gets a jump-to-series list + threshold bulk-accept and a "view in Kavita" link; deferred `NEEDS_RELOCK` seal retry now respects the per-series processing lock; draining the Manual Review queue mid-batch shows the waiting mask instead of flashing the recap screen.
- [x] **Full-audit critical/high fixes (v1.6.1, no bump):** Stop batch no longer drains webhook/auto-sync jobs out of the shared sync queue along with the batch (`drain_sync_queue()` now only removes `is_batch=True` items); a second concurrent batch (two tabs, a stray double-click) is now rejected with `409` instead of resetting the progress counters of the batch already running; Manual Review's bulk-accept now surfaces individual write failures by series name instead of hiding them behind the `skipped` count; live dashboard status badges no longer guess from translated log keywords — `enrich_series()` emits a typed `series_status` event for every outcome (`NOT_FOUND`, `PENDING_REVIEW`, already-up-to-date `COMPLETED`), same as it already did for the write path.
- [x] **C58. Full User/Password Authentication (v1.6.1, issue #15):** `users` table + `auth_manager.py`; forced `/setup` on first run; fail-closed gates (HTTP **and** Socket.IO `return False`); legacy plaintext `ADMIN_PASSWORD` never imported — required once as ownership proof on `/setup`, then erased; `TRUSTED_PROXY_COUNT` (0/1) driving both `ProxyFix` and the lockout key; 5-attempt / 15-minute per-IP lockout **plus** global 20/15min backstop against XFF rotation; optional `ADMIN_PASSWORD_HASH` seeding (hash-shape validated) with `debug/hash_password.py`; memoized dummy-hash timing equalization; sid-targeted Socket.IO emits; explicit 7-day session lifetime.
- [x] **C57. Health Endpoint `/healthz` (v1.6.1, issue #15):** Unauthenticated liveness probe returning `{status, version}`; whitelisted in `require_login` so it survives the auth gate. Dockerfile `HEALTHCHECK` retargeted from `/login` (any status < 500) to `/healthz` (strict 200). Reads no config, no DB, never calls Kavita — a Kavita outage must not restart a healthy container.
- [x] **BF51. Env-var seeding before first `config.json` write (v1.6.1):** `load_config()` merges environment *before* generating secrets / writing the file, so `UI_LANG`, `KAVITA_URL`, `PROVIDER_*`, `MAX_TAGS`, … actually take effect on a fresh install. Precedence `config.json` > env > default; `ADMIN_PASSWORD` deliberately not seeded from env.
- [x] **BF52. Hotfix — fresh Config Kavita save + Docker plug-and-play (v1.6.1, no bump):** Empty secret fields in the Config modal (blank POST keeps existing keys); blank `KAVITA_*` no longer block env seeding; specific Kavita auth errors; Compose/README always include `host.docker.internal:host-gateway`. Fixes first-run modal setup that looked like credentials were not written (1.6.0→1.6.1 migrations were already fine).
- [x] **BF50. Test Suite DB Isolation (v1.6.1):** `test_scraper_max_caps.py`'s end-to-end enrichment test reached the real `data/cache.db` through an unmocked `record_enrichment_telemetry()`, inflating the lifetime counters and adding a fake `FAKE` provider to the C7 podium on every run. Now uses the existing `isolated_db` fixture.
- [x] **C29. Manual Review Mode (v1.6.1):** Scrape → pending queue → pick modal (score gradient, keys 1–3, weak red) + optional edit + **cover pick step**, telemetry, session recap + **achievements** on `/stats` — not Event-pause worker. Integrity hardening: UNIQUE `series_id`, atomic park/skip/confirm, batch skips parked series, apply under `_processing_lock`, WAL SQLite, frontend queue sync.
- [x] **Field sealing / `NEEDS_RELOCK` (v1.6.1):** Soft-success after Kavita write + failed re-lock → orange `NEEDS_RELOCK` (not plain COMPLETED); deferred seal retry, 🔒 button, filter, `POST /api/series/<id>/seal-locks` (+ bulk). Seal OK → COMPLETED.
- [x] **Supporter nags / tip overlays (v1.6.1, C40):** Rare playful overlays (caps, honeymoon, honor snooze) after batch end / rich MR recap + café CTA in MR recap + Buy Me a Coffee links in sidebar / topbar / About. No paywall; `.license` class reserved for a future silence hook.
- [x] **C56. Custom Scraper RCE Warning (v1.6.1, issue #15, thanks angusmaul):** Prominent FR + EN warning at the top of `CUSTOM_SCRAPERS.md` — sideloading a `.py` into `data/scrapers/` is arbitrary code execution at startup with the app's privileges (config secrets, filesystem, outbound network, `proxy_domains` allowlist widening). Concrete red flags for non-programmers, explicit caution on AI-generated code, trust model stated. Short linked version in both README security sections.
- [x] **Security hardening BF46–BF49 / C54–C55 (v1.6.1, issue #15, thanks angusmaul):** gunicorn/requests CVE bumps; `/api/proxy-image` 5 MB stream cap; webhook `X-Webhook-Token` header; `config.json` 0600; non-root Docker with PUID/PGID + HEALTHCHECK; `.dockerignore`.
- [x] **BDTheque.com comics provider (v1.6.1):** Provider `BDTHEQUE` for https://www.bdtheque.com/ (distinct from `BEDETHEQUE` / bedetheque.com). AJAX series search, series page scrape, Magic Input, unified scoring, covers.
- [x] **MyAnimeList official API (v1.6.1):** Provider `MAL` via API v2 + `X-MAL-CLIENT-ID` (`MAL_API_KEY` = Client ID). Replaces retired Jikan. Manga/Book, Magic Input, unified scoring.
- [x] **Reliability barometer (v1.6.1):** Sidebar unlock + slider for match accept threshold (`0.30`–`1.00`, default `0.60`); `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD`; runtime via `get_match_accept_threshold()`.
- [x] **Batch progress bar (v1.6.1):** `done / total` above batch buttons; Socket.IO `batch_progress` from worker `qsize()`; hides on finish/Stop.
- [x] **Collapsible Scraping Options (v1.6.1):** Click sidebar title to show/hide the strategy card.
- [x] **Wikidata live provider (v1.6.1 → Magasin in v1.6.3):** Provider `WIKIDATA` (Manga/Comic/Book) via SPARQL + Entity API; Magic Input Q-id; shared `wikidata_map`. Moved to Community Store in 1.6.3 (limited scope). Offline subset (C39) deferred.
- [x] **C35. Native "Comic (Flexible)" Support (v1.6.1):** Kavita Library Type ID 5 is no longer flattened to Comic. Hybrid cascade: `COMIC_PROVIDER_*` first, then `PROVIDER_*` (Manga) if no useful hit. Cover search unions Comic + Manga scrapers.
- [x] **C7. Playful Statistics Dashboard (v1.6.1):** Restyled `/stats` + Chart.js; lifetime `series_enriched` / `matches_won` / `series_missed` + hit-rate; live topbar KPIs + session counter; Socket.IO `enrichment_stats`; ~24 fun cards + Manual Review achievements chapter. `ENABLE_PLAYFUL_STATS` default ON.
- [x] **Batch QoS & Granularity (v1.6.1):** Auto-uncheck on success; `localStorage` selection persist per library; ephemeral batch targeted-fields mask (sidebar `<details>`); Check all / Uncheck all (sidebar + per-series overrides); Stop aborts ×50 enqueue loop + server rejects late chunks; `/stats` scroll fix.
- [x] **C45. Smart Scoring (v1.6.0):** Score-based provider winner selection + two-wave parallel execution (`SMART_SCORING` sidebar toggle), with community-scraper opt-in/`_safe_match_score` hardening.
- [x] **C53. Localized Titles Policy (v1.6.0, issue #12):** Global `LOCALIZED_TITLE_MODE`/`LANGS` + per-series `alt_title_langs` for Kavita `localizedName` only (never rewrite `name`); structured `titles[]` on AniList/MangaDex/Kitsu; default remains multi-title `" / "` join.
- [x] **C52. Topbar Help Menu — About & Documentation (v1.6.0):** Help dropdown with About modal, GitHub doc links, changelog shortcut; Kavita+ support positioning (About copy + topbar Kavita+ beside BMC → instance `settings#admin-kavitaplus`).
- [x] **C47. MangaBaka Book/LN + API Hardening (v1.6.0):** Official MangaBaka Book support with `schema=full`, `type=novel` filter, and related parsing fixes (thanks LazyGeniusMan).
- [x] **C46. CORS Allowed Origins (v1.6.0):** Docker env `CORS_ALLOWED_ORIGINS` (CSV explicit origins) for Flask HTTP + Socket.IO behind Traefik/HTTPS self-hosts.
- [x] **C48. KAVITA_EXTERNAL_URL (v1.6.0):** Separate public Kavita URL for browser UI links vs internal `KAVITA_URL` for Docker API calls (thanks LazyGeniusMan).
- [x] **BF19. Kavita Write Timeout & False-Negative RE-LOCK (v1.6.0):** Configurable `KAVITA_HTTP_TIMEOUT` (default 60s) for write POSTs; metadata/general 2-pass treats write-OK + RE-LOCK failure as soft success; one capped RE-LOCK-only retry (issue SqueezedByte).
- [x] **C49. Configurable MAX_TAGS (v1.6.0):** Env/`config.json` cap on tags written to Kavita (default 15, range 1–100); scrapers + enrichment use `get_max_tags()` — no UI (feedback LazyGeniusMan).
- [x] **C51. Configurable MAX_GENRES (v1.6.0):** Env/`config.json` cap on genres (default 5, range 1–50); dynamic-list scrapers + `enrichment_engine` use `get_max_genres()` — no UI. Homogenized with AniList tags / MangaUpdates categories under `MAX_TAGS`.
- [x] **C32. Flask Blueprints Refactoring (v1.6.0):** Modularized the former monolithic `app.py` into Blueprints under `routes/`, plus `services/`, `models.py`, and a thin composition root.
- [x] **BF20–BF41 + C50. Application Audit Hardening (v1.6.0):** Critical/High/Medium plus Low polish (no hardcoded SECRET_KEY fallback, API key not logged, ComicVine proxy_domains narrowed, `MAX_GENRES` / `get_max_genres()`). Optional empty `ADMIN_PASSWORD` left intentional.
- [x] **BF42–BF45. Post-Audit Follow-ups (v1.6.0):** Credential-safe exception logging; safe cover redirects + CDN `proxy_domains`; private IP block in `url_allowlist`; Escape closes changelog; CODE_REVIEW MAL/Nautiljon cleanup.
- [x] **BF18. Per-Series Publisher Preference Never Saved (v1.6.0):** The `/save-override` endpoint read the per-series Publisher toggle (`Auto`/`VF/VA`/`VO`) but never forwarded it to the database, silently resetting it to `GLOBAL` on every save. The per-series preference is now correctly persisted and respected by the scrapers.
- [x] **BF14. LocalizedName Corruption & KOReader/Kamare Crash Fix (v1.5.8):** `update_series_general()` now always fetches a series' full current state before writing, preventing Kavita from silently nulling `LocalizedName` and force-unlocking `NameLocked`/`SortNameLocked`/`LocalizedNameLocked` on partial updates (e.g. format-only). Root cause of a reported KOReader "Kamare" plugin crash.
- [x] **BF15. Metadata System-Field Leak (v1.5.8):** Centralized sanitization of GET-only computed fields (`totalCount`, `maxCount`, `pages`, `wordCount`) inside `update_series_metadata()`, preventing them from being echoed back into `POST /api/Series/metadata` and risking EF Core concurrency exceptions.
- [x] **BF16. MangaBaka "Completed" Status Mapping (v1.5.8):** Fixed MangaBaka's raw `completed` status never matching MetaKavita's internal `FINISHED` status key, which left completed series silently stuck as "Ongoing" in Kavita.
- [x] **BF17. `BaseScraper` Attribute Typo (v1.5.8):** Corrected `eeds_api_key` to `needs_api_key` on the base scraper class default attribute.
- [x] **C41. Community Scrapers Sideloading (v1.5.7):** MetaKavita now dynamically loads external Python scrapers dropped directly into the user-mapped `data/scrapers/` folder.
- [x] **C42. Publisher Localization Preference (v1.5.7):** Added an elegant per-series segmented toggle (`Auto` | `VF/VA` | `VO`) to let users prioritize Localized/Translated publishers or Original publishers.
- [x] **C15. Title Translation Fallback (v1.5.7):** Experimental safety net that automatically translates unfound localized titles to English to perform a second search pass. Highly useful for massive blind batches.
- [x] **C43. Bulletproof SQLite Schema Migrations (v1.5.7):** Rewrote the database initialization logic (`_ensure_schema`) to gracefully handle column additions one by one without container crashes.
- [x] **C44. Custom Scraper Guide & Vibecoding (v1.5.7):** Released `CUSTOM_SCRAPERS.md` containing strict integration rules and ready-to-use AI Prompts to help users generate their own scrapers.
- [x] **BF10. Pure Base64 Cover Payload (v1.5.6):** Fixed the "Phantom Cover" syndrome where Kavita silently rejected `Data URI` image payloads. Reverted to pure Base64 strings for permanent disk writes.
- [x] **BF11. WebSocket Cover Stream Priority (v1.5.6):** Manual input priority restored in the cover modal; live cover frames are filtered by `series_id`. *(Note: chronological `stream_id` tokens are documented as intended hardening — not yet wired in client/server; tracked as a known gap.)*
- [x] **BF12. Smart Auto-Cover Locking (v1.5.6):** Manually applying a cover from the modal now automatically unchecks the "Cover" targeted field to protect it from background sync overwrites.
- [x] **BF13. True Context Reset (ISBN Purge) (v1.5.6):** Fixed a critical oversight where forcing an update with "Context Reset" still retained the Kavita ISBN, causing persistent false-positive matches. The ISBN is now properly purged to guarantee a true clean slate.

---

### 📦 Archive: Advanced Features & Core Architecture (V1.5.0+)
- [x] **C1. MyAnimeList (MAL) Scraper:** Integrated the public and free Jikan API v4.
- [x] **C2. MangaDex Scraper:** Integrated the official MangaDex REST API v5 for rich metadata tags, content rating filters, and candidate weighting.
- [x] **C3. Baka-Updates (MangaUpdates) Scraper:** Integrated the v1 REST API to retrieve associated alternative titles and keyword penalty scoring.
- [x] **C4. Kitsu Scraper:** Add Kitsu JSON:API as a reliable global fallback source.
- [x] **C5. Manga-News Scraper:** Implemented `curl_cffi` scraping of the French licensing catalog.
- [x] **C6. Scraper Bedethèque:** Scraping BeautifulSoup4 for Franco-Belgian comics.
- [x] **C23. Shikimori Scraper:** Integrated Shikimori REST JSON API with native `MalId` mapping.
- [x] **C24. Open Library Scraper:** Integrated Open Library / Internet Archive API for literature with anti-429 rate-limiting retries.
- [x] **C16. Hardcover Scraper:** Integrated the Hardcover Hasura GraphQL & Typesense endpoints.
- [x] **C6. Western Comics & Books Support (B10):** Integrated Google Books API as production-ready scrapers for Novels.
- [x] **C14. Context-Aware Cover Search:** Dynamically filter the queried providers inside the manual cover selection modal based on the Kavita `libraryType`. 
- [x] **C17. Reverse Proxy & Subpath Support:** Introduced `ROOT_PATH` environment variable and WSGI middleware.
- [x] **C18. The "Magic Input" (Smart URL Routing):** Replaced static ID fields with a universal URL/ID parser.
- [x] **C19. Granular Scraping (Targeted Fields):** Built UI and backend support to individually toggle 12 Kavita metadata fields.
- [x] **C20. Self-Healing Configuration Engine:** Dynamic validation of search cascades.
- [x] **C21. Smart ID Match Engine:** Implemented a title similarity validation engine (>50% ratio threshold).
- [x] **C22. Extended Kavita API Mapping:** Added Editors, Letterers, Inkers, and Localized Language.
- [x] **C25. Live WebSocket Cover Streaming (*Progressive Loading*):** Real-time Socket.IO streaming of manual cover search results.
- [x] **C26. Smart Ignored & Amnesties Expansion:** Override `IGNORED` status for explicitly checked batch items, and reset both `NOT_FOUND` and `IGNORED` via the Amnesties button.
- [x] **C28. Kavita Deep Metadata Extraction & Unified Scoring:** Pre-fetch existing file-level metadata (`authors`, `isbn`) from Kavita to anchor a centralized scoring matrix.
- [x] **C34. Smart Per-Provider Rate Limiter & Dynamic Throttling:** Replaced hardcoded worker delays with a timestamp-based throttler (`LAST_REQUEST_TIMES`).
- [x] **C36. Quality Benchmarking & Unit Testing Suite:** Created standalone diagnostic test scripts to stress-test 20 scoring edge cases.
- [x] **C37. ComicVine Overhaul & Issue #1 Fallback:** Switched to structured `/volumes/?filter=name:` search prioritizing primary US/European publishers.
- [x] **C38. Unrestricted Provider Forcing:** Unlocked all registered scrapers in the Magic Input dropdown.
- [x] **C9. Resilient Multi-API Translator:** Dedicated translation module combining Microsoft Azure Translator and DeepL.
- [x] **C10. Dynamic Library Routing & Factory Pattern:** Automatic extraction of Kavita library types.
- [x] **C11. Hybrid ComicVine Scraper:** Built a two-step lookup cascade mapping individual album titles and resolving parent volumes.
- [x] **C12. Contextual Title Cleaning:** Tailored query cleaning logic based on targeted media type.
- [x] **C13. Provider Purge (Nautiljon):** Completely removed Nautiljon from the default routing map due to abusive Cloudflare IP bans.

### 🐛 Archive: Bug Fixes & Architecture Shifts (V1.4.x / V1.5.x)
- [x] **BF1. Admin Password Env Var Override Bug:** Resolved the issue where clearing the admin password via `docker-compose.yml` failed.
- [x] **BF2. Permanent Auth Cookie Cleansing:** Ensured a hard logout completely destroys the long-lived session cookie via `expires=0`.
- [x] **BF3. Bédéthèque Spin-off Override Bug**: Fixed an issue where searching for a main series would return covers from its spin-offs due to alphabetical sorting.
- [x] **BF4. Context-Aware Cover Fetching**: Fixed a regression where the manual cover search queried all scrapers blindly.
- [x] **BF5. Publisher Metadata Parsing Fix:** Corrected an oversight where publisher metadata wasn't properly scraped.
- [x] **BF6. Disable Translation Option:** Added a configuration setting (`NONE`) to disable the translation pipeline.
- [x] **BF7. Global App Version Jinja Context:** Render `app_version` directly from `CHANGELOG.md` in the UI.
- [x] **BF8. Dynamic API Key Engine:** `BaseScraper` now supports `needs_api_key=True` to auto-generate forms dynamically.
- [x] **BF9. Decentralized Translations (i18n):** Scrapers now encapsulate their own translations via `self.t()`.

### 🏗️ Archive: Ergonomics & Interface Overhaul (V1.4.0)
- [x] **B1 to B6:** Mapped Genres, Tags, localized titles, and extended staff metadata (Writers, Pencillers, Colorists, Translators, Cover Artists) pushing to Kavita.
- [x] **B7 to B9:** "Ignored" series state, Auto-Sync Polling, Smart Fallback Routing, and Data Fusion (Smart Completion).
- [x] **B11. Global Authentication:** UI locking via `ADMIN_PASSWORD` container variable.
- [x] **B14 to B15:** Advanced Cover Selection Modal & MangaBaka V2 API.
- [x] **B16. Ultimate Regex Title Cleaner:** Decentralized `clean_title()` logic.
- [x] **B17. Real-Time AJAX Search Bar:** Instant client-side filtering without reload.
- [x] **B18. Extended Metadata Mapping:** Publishers, Age Ratings, and Origin-based Auto-Reading direction.
- [x] **B19. External IDs & WebLinks:** Automatic mapping of native IDs and clickable direct WebLinks.
- [x] **B20. Split UI Architecture:** Moved all technical config inputs to an Admin Modal.
- [x] **B21. Manual Cover Search:** Enter custom queries directly inside the cover modal.
- [x] **B22. Live Processing Tracker (Pulsing Glow):** Automatically flashes the active sync item in purple (`.is-processing`).
- [x] **B23. AniList Quick Lookup:** Magnolia button to open pre-filled searches on AniList.
- [x] **B24. Persistent Workspace:** Automatically saves active library, status filter, hide ignored state, and search query.

### 🛠️ Archive: Foundations & Security (V1.3+)
- [x] **A1 to A6:** Secure API integration, Live Logs, 100% AJAX, Global Translation bridges, Responsive UI.
- [x] **A7 to A9:** Self-cleaning SQLite cache, explicit connection error indicators, Zero-Setup deployment.
- [x] **A10. Production WSGI Server:** Eventlet + Gunicorn asynchronous stack.
- [x] **A11. Global Security:** SSRF Protection on Image Proxy, Timing-Attack immune authentication (`secrets.compare_digest`), HttpOnly Session cookies, hidden API keys in DOM, Token-protected webhooks.

<br><br>

---

## 🇫🇷 Feuille de Route Française

### 🔮 Backlog & Fonctionnalités Futures (À Faire)
- [x] **C29. Mode Batch Manuel Interactif (QoS) / Review Manuelle (v1.6.1) :** Review Manuelle en file livrée — scrape silencieux → `PENDING_REVIEW` → modale pick / édition / couverture ; pas d'écriture auto tant que l'utilisateur n'a pas confirmé. Voir Dernières Nouveautés. (Variante Event-pause abandonnée — voir En veille.)
- [x] **C30. Scrapers Littéraires Francophones (v1.6.3) :** Babelio, Decitre et SensCritique livrés dans le core (sans clé API). Voir Dernières Nouveautés.
- [x] **C60. Promotions comics / manga core (v1.6.3) :** ANN, LoCG, Planète BD et Metron (`METRON_API_KEY`) promus du dépôt communautaire dans l’image Docker.
- [x] **C61. Manage scrapers + Magasin (v1.6.3) :** `/manage-scrapers` + `/scraper-store` (Aide) ; registre `data/scrapers/` ; catalogue sha256 ; `DISABLED_SCRAPERS` ; onglets hub + avis beta community. Voir Dernières Nouveautés.
- [ ] **C31. Outil de Déduplication Kavita :** Panneau UI pour détecter et fusionner les doublons dans Kavita.
- [ ] **C33. Extension Navigateur "MetaKavita Companion" :** Widget flottant en surcouche directement sur l'interface Web de Kavita pour déclencher les mises à jour MetaKavita nativement.
- [ ] **C39. Mode Scraper Hors-Ligne (Local DB / Dumps) :** Sous-ensemble SQLite Wikidata (ou équivalent) optionnel quand les quotas API ou un labo hors-ligne importent. (Wikidata = Magasin seul depuis v1.6.3.)
- [ ] **Métadonnées volume / issue (demande #27) :** enrichissement par tome / album — `scopes` volume déjà réservé sur `BaseScraper` ; pipeline + UI encore ouverts.
- [x] **C40. Soutien au développeur (Dons) (v1.6.1) :** lien Buy Me a Coffee dans la sidebar / topbar / À propos, overlays supporter ludiques rares, et CTA café dans le récap Review Manuelle (pas de paywall / clé licence).
- [ ] **B4. Restreindre le scope de `seal_series_locks` :** après soft-fail re-lock (`NEEDS_RELOCK`), le seal pose tous les `*Locked` + force `localizedNameLocked` (souvent `formatLocked`), y compris des champs que MetaKavita n'a jamais écrits. Chemin rare — la feature sert aux hôtes très lents ; préférer monter `KAVITA_HTTP_TIMEOUT` (jusqu'à ~600 s) plutôt que de complexifier le seal. Idéal plus tard : ne sceller que les locks du dernier write / masque actif.

### 🧊 En veille (pas de travail actif)
- [ ] **C29 suite. Worker Event-pause — en veille / remplacé :** idée QoS d’origine (candidats en WebSocket, worker bloqué sur `eventlet.event.Event` jusqu’au choix). La **Review Manuelle C29** gare déjà en `PENDING_REVIEW` et laisse le batch continuer ; revue asynchrone. La file **C63** couvre pause / reprise / redémarrage. Un Event-pause synchrone figerait les gros lots à chaque match ambigu et dupliquerait l’UX — pas un second mode utile.
- [ ] **C8. Résilience / backoff exponentiel 429 — en veille :** le throttle par provider (`throttle_provider` / **C34**) espace déjà les appels selon chaque `rate_limit` (idle = pas d’attente). Pas de retours terrain de 429 systémiques sur gros batchs tant qu’on reste sous ces délais ; Open Library a déjà une pause 429 simple. Usine à gaz exponentielle reportée sauf bans réels. Optionnel plus tard : un retry léger / `Retry-After` — pas une priorité produit.

---

### ✨ Dernières Nouveautés (v1.5.6 à v1.6.5)
- [x] **BF103. Durcissement cover pick Manual Review (v1.6.5) :** reopen / jump de file restaure la phase cover si le toggle est on ; upload cover MR explicite retire `cover` de `targeted_fields` (parité `/update-cover` via `protect_manual_cover_field`).
- [x] **C64. Wizard de setup guidé (v1.6.4) :** `/setup` en 6 étapes (compte, Kavita + `ROOT_PATH`, langues, options + Auto-Sync 6 h, clés API, cascades) ; test Kavita non bloquant ; Passer = defaults prêts ; rejeu connecté sans étape compte (menu Aide).
- [x] **C62. Scrapers core `is_core` + sync au boot (v1.6.4) :** catalogue community GitHub `is_core` → `data/scrapers/` (sha256) ; fallback package image si hors-ligne ; `AUTO_UPDATE_CORE_SCRAPERS` (défaut on) ou bannière + `POST /api/scrapers/core-updates/apply`.
- [x] **C63. File batch persistante (v1.6.4) :** file SQLite + hydrate au boot ; Ajouter / Pause / Reprise / retirer / vider ; Stop annule la file durable.
- [x] **BF91. Allowlist CDN covers MangaBaka (v1.6.4, issue #31, merci SqueezedByte) :** `proxy_domains` inclut `images`/`cdn` `.mangabaka.dev` et `.org`.
- [x] **BF92. Sélection cover MangaBaka sur allowlist (v1.6.4) :** `_pick_cover_url` / `fetch_covers` basculent sur l’imgproxy MangaBaka si `cover.raw` est tiers.
- [x] **BF93. Recherche dashboard sans freeze (v1.6.4, issue #30, merci angusmaul) :** `data-search-title` + `is-filtered-out` + debounce 150 ms (plus d’`innerText` / `style.display` par item).
- [x] **BF94. Batch = affichées + recherche préfixe (v1.6.4) :** le filtre garde les coches ; batch/ignore = cochées visibles ; « tout sélectionner (affichés) » remplace la sélection ; recherche préfixe par défaut, case « Dans le titre ».
- [x] **BF95. Warning `ADMIN_PASSWORD` env une fois par boot (v1.6.4, issue #31, merci SqueezedByte) :** message d’obsolescence actionnable ; plus de spam à chaque requête.
- [x] **BF96. Panneaux Options lazy + Set de sélection (v1.6.4, issue #30, merci angusmaul) :** plus de DOM override par ligne ; index BF94/C63 ; `content-visibility`.
- [x] **BF97. Liste virtualisée (v1.6.4, issue #30) :** ≥120 séries → JSON + fenêtre de scroll ; sélection filtrée pour batch/file.
- [x] **BF98. Libellés file + Expand-all + reprise au lancement (v1.6.4) :** Lancer la sélection / Voir la file ; mid-batch Ajouter à la file d’attente ; Lancer lève la pause ; Expand-all confirme sur gros filtres.
- [x] **BF99. Cartouches / toolbar plus denses (v1.6.4) :** cartes plus courtes, titres un peu plus grands, groupes Recherche / Filtres colorés ; Tout sélectionner dans la tête de toolbar.
- [x] **BF100. Panneau Options compact (v1.6.4) :** ligne principale densifiée, champs ciblés en chips ; tests `test_override_panel_ui.py`.
- [x] **BF101. Progression batch + reinit liste virtualisée (v1.6.4) :** barre ne disparaît plus si ajout mid-batch = doublons ; bump totaux resume ; `loadLibrary` ré-init SeriesList ; offsets cumulés si Options ouverts.
- [x] **BF102. SMART_COMPLETION comble âge non-adulte (v1.6.4) :** Auto remplit `safe`/`suggestive`/`mature` seulement ; ages NSFW secondaires bloqués ; pas de skip si Pending + champ Âge ; `log_age_write_diag`.
- [x] **C30 / C60. Sept scrapers communautaires dans le core (v1.6.3) :** Babelio, Decitre, SensCritique, ANN, LoCG, Planète BD, Metron ; défauts BOOK_3=Babelio, COMIC_3=LoCG pour installs neuves.
- [x] **C61. Manage scrapers + Magasin (v1.6.3) :** install / update / delete community ; core = désactivation seule ; catalogue sha256 ; flags retired / hors magasin ; onglets Installés · Magasin · Diagnostic + avis beta.
- [x] **Probe cascade Diagnostics (v1.6.3) :** `/diagnostics` sonde la cascade Config active après préflight ; « Tester la cascade » / « Tester tous » ; `POST /api/scrapers/probe-all?scope=active|all`.
- [x] **Sources MR peuvent combler `age_rating` (v1.6.3) :** Sources cochées comblent un âge vide ; Auto SMART_COMPLETION restait BF69 jusqu’à BF102.
- [x] **BF90 / BF88 / BF87 Magasin + Sources MR (v1.6.3) :** rollback install, orphelins, reload atomique ; Sources survivent réouverture/confirm ; sémantique `include_providers`.
- [x] **BF86 / BF85 / BF84 (v1.6.3) :** bind modules registre ; probe ID Planète BD ; hôtes covers = `requires_proxy`.
- [x] **BF83. INFO CSRF rejeté + refus sous lockout actif (v1.6.3, merci angusmaul) :** distinguer mauvais MDP / CSRF / lockout dans les Live Logs.
- [x] **BF82. INFO à chaque échec de login (v1.6.3, merci angusmaul) :** username + IP + compteur à chaque tentative ; WARNING lockout inchangé.
- [x] **BF81. Crans d’âge neutres + hentai/futanari → x18 (v1.6.3, #25/#29) :** `r18`/`x18` (+ aliases) ; escalade centrale vers x18 si tags hentai/futanari même avec âge provider ; démotion NSFW = égalité Auto seulement.
- [x] **BF80. Kitsu R → mature / Mature 17+ (v1.6.3, issue #29, merci angusmaul) :** plus de fusion `R`+`R18` → `pornographic` ; tier `mature→10` ; `R→mature`, `R18→pornographic`.
- [x] **BF79. Logs proxy / lockout selon `UI_LANG` (v1.6.3, #26, merci angusmaul) :** TRUSTED_PROXY / SECRET_KEY éphémère / lockout via `get_ui_translations`.
- [x] **BF78. Preview confirm/MR déduplique tags & genres (v1.6.3, #24, merci angusmaul) :** même dédup que le payload Kavita avant join.
- [x] **BF77. Tie-break Auto : signaux adult genres/tags (v1.6.3, issue #25, merci angusmaul) :** `_is_explicit_adult` traite aussi `hentai` / `futanari` ; log prefer-safe seulement si le vainqueur est non-adulte.
- [x] **C59. Dépôt scrapers communautaires (v1.6.2) :** scrapers plug-and-play officiels dans [`community-scraper-metakavita`](https://github.com/raukorim-bot/community-scraper-metakavita). Liens menu Aide, README EN/FR et `CUSTOM_SCRAPERS.md` (toujours lire / faire confiance avant install).
- [x] **UI Diagnostic scrapers (v1.6.2) :** page `/diagnostics` + API de probes (préflight Internet/Kavita, santé metadata/covers par scraper).
- [x] **BF56. Safeguarding âge — plus de Everyone inventé (v1.6.2) :** les scrapers sans signal d'âge autoritatif omettent `age_rating` au lieu de forcer `safe` ; BDTheque mappe Adulte/Érotique → `erotica` (pas Teen), et « Ados - Adultes » reste `suggestive`. Évite de verrouiller un faux Everyone/Teen sur du contenu adulte (suite de BF53).
- [x] **BF58. Tokens format (v1.6.2) :** `resolve_kavita_format_enum` ne fait plus de match sous-chaîne (`COMIC BOOK`→Novel, `MUST`→Comic) ; tokens scrapers exacts + split mots, Comic avant Book.
- [x] **BF59. Statut FINISHED inventé omis (v1.6.2) :** ComicVine / Hardcover / Google Books / OpenLibrary n'émettent plus `status: FINISHED` en dur ; omission comme BF56 pour l'âge.
- [x] **BF60. i18n labels covers Manga-News (v1.6.2) :** `(Série)` / `(Tome)` suivent `UI_LANG` via `self.t()` (même classe que BF55).
- [x] **BF61. `releaseYear` int valide seulement (v1.6.2) :** pas d'écriture/lock si l'année n'est pas un int dans 1000–2100 (plus de strings depuis l'overlay d'édition).
- [x] **BF62. Exceptions scrapers/enrichissement silencieuses loguées (v1.6.2) :** `except Exception: pass` métier → `logging.debug` + `safe_exc_str` (ComicVine / Google Books / MangaBaka / purge orpheline) ; cleanups `session.close()` restent silencieux.
- [x] **BF63. UI webhook privilégie l’en-tête (v1.6.2, audit B15) :** Modal Config affiche `/webhook` + jeton à part (plus de `?token=` en copier-coller) ; docs marquent la query en legacy ; le serveur l’accepte encore ; warning unique si query sans en-tête.
- [x] **BF64. `TARGET_LANG` depuis `UI_LANG` si absent (v1.6.2, audit B17) :** défaut `TARGET_LANG=EN` (était FR vs `UI_LANG=en`) ; absent fichier+env → dérive `en`→`EN` / `fr`→`FR` ; fichier > env > dérivé ; pas de migration des valeurs explicites existantes.
- [x] **BF65. Nettoyage dead code / lot orphelins (v1.6.2) :** suppression d’helpers/imports inutilisés (`increment_provider_win`, `delete_pending_review`, `record_manual_skip_telemetry`, helpers scrapers/imports morts), migration hors wrappers legacy (`save_pending_review`, `save_forced_overrides`), helpers dénylist inutilisés retirés, clés i18n mortes haute confiance élaguées, plus de clé API Kavita hardcodée dans `debug_ultime.py`.
- [x] **BF66. Déduplication tags/genres avant plafonds MAX (v1.6.2, issue #24) :** dédup insensible à la casse, ordre conservé, dans `build_kavita_payload` avant les tranches tags/genres.
- [x] **BF67. Atomicité soft des champs généraux (v1.6.2, issue #24) :** `update_series_general` seulement après succès metadata.
- [x] **BF68. Égalité de score : préférence âge plus safe (v1.6.2, issue #25) :** Auto rétrograde pornographic/erotica seulement à score égal (avec log) ; MR inchangé ; CBW+égalité → awaiting_pick.
- [x] **BF55. i18n des labels ComicVine (hotfix v1.6.2, merci angusmaul) :** les préfixes décoratifs des résumés/couvertures (`[Série]` / `[Synopsis]` / …) suivent `UI_LANG` au lieu d'écrire toujours du français dans Kavita.
- [x] **BF57. Langue série gated par champs ciblés (v1.6.2) :** `language` / `languageLocked` n'écrit que si `language` est dans le masque actif (inclus dans `ALL` par défaut).
- [x] **BF54. Année de run Comic dans le titre de recherche (hotfix v1.6.2, merci angusmaul) :** `clean_title` Comic retire désormais les `(YYYY)` / `(YYYY-)` Kavita Flexible de la query ; l'année est réinjectée dans `existing_metadata` et utilisée par le ranking `start_year` ComicVine. Évite miss Comic → faux positif Manga sur des noms comme `Batman (2025)`. Fallback Manga non pénalisé au score.
- [x] **BF53. Mapping enum age rating (hotfix v1.6.2, merci angusmaul) :** `AGE_RATING_MAP` utilisait à tort les ordinaux MangaDex `1–4` au lieu de l'enum `AgeRating` de Kavita, donc `pornographic` était écrit comme **G** (et verrouillé). Remappé vers Everyone/Teen/R18+/X18+ (`3/8/12/14`) ; docs + test de non-régression.
- [x] **Suites BF52 (v1.6.1, pas de bump) :** Changement de mot de passe simple (`POST /account/password`, revérifié par le même contrôle que `/login` + verrouillage) ; les cases bibliothèques sauvegardent en AJAX au lieu de forcer un rechargement (qui redéclenchait aussi un « heal wipe » trop zélé, désormais supprimé — un « tout désactiver » délibéré tient maintenant à travers les rechargements) ; `/batch-sync` réutilise un seul instantané d'inventaire Kavita par batch au lieu de le retélécharger à chaque paquet d'environ 50 séries ; la barre de progression batch et le nagware supporter suivent désormais des compteurs dédiés isolés du bruit webhook/auto-sync, et le nagware ignore les batchs sans effet (tout déjà à jour) ; le fallback Manga de Comic Flexible se déclenche désormais pareil en Review Manuelle qu'en Auto ; la Review Manuelle gagne une liste pour sauter à une série précise + un « tout accepter » par seuil + un lien « voir dans Kavita » ; le retry différé de scellement `NEEDS_RELOCK` respecte désormais le verrou de traitement par série ; vider la file de Review Manuelle en plein batch affiche le masque d'attente au lieu de faire clignoter le récap.
- [x] **Correctifs critiques/hauts de l'audit total (v1.6.1, pas de bump) :** Stop batch ne vide plus les jobs webhook/auto-sync de la file partagée en même temps que le batch (`drain_sync_queue()` ne retire plus que les items `is_batch=True`) ; un second batch concurrent (deux onglets, double-clic malheureux) est désormais refusé en `409` au lieu de remettre à zéro les compteurs de progression du batch déjà en cours ; le tout-accepter de la Review Manuelle affiche désormais les échecs d'écriture individuels par nom de série au lieu de les masquer derrière le compteur `skipped` ; les badges de statut live du dashboard ne devinent plus à partir de mots-clés de log traduits — `enrich_series()` émet un événement `series_status` typé pour chaque issue (`NOT_FOUND`, `PENDING_REVIEW`, `COMPLETED` déjà-à-jour), comme il le faisait déjà pour le chemin d'écriture.
- [x] **C58. Authentification utilisateur/mot de passe complète (v1.6.1, issue #15) :** table `users` + `auth_manager.py` ; `/setup` forcé au premier démarrage ; gates fail-closed (HTTP **et** Socket.IO `return False`) ; ancien `ADMIN_PASSWORD` en clair jamais importé — exigé une fois comme preuve de propriété sur `/setup`, puis effacé ; `TRUSTED_PROXY_COUNT` (0/1) pilotant `ProxyFix` et la clé de verrouillage ; verrouillage par IP 5/15 min **plus** plafond global 20/15 min contre la rotation XFF ; amorçage optionnel `ADMIN_PASSWORD_HASH` (forme de hachage validée) via `debug/hash_password.py` ; égalisation de timing par hachage factice mémoïsé ; emits Socket.IO ciblés sur le `sid` ; durée de session explicite de 7 jours.
- [x] **C57. Endpoint de santé `/healthz` (v1.6.1, issue #15) :** sonde de liveness non authentifiée renvoyant `{status, version}` ; whitelistée dans `require_login` pour survivre au gate d'authentification. `HEALTHCHECK` du Dockerfile repointé de `/login` (tout statut < 500) vers `/healthz` (200 strict). Ne lit aucune config, aucune base, n'appelle jamais Kavita — une panne de Kavita ne doit pas redémarrer un conteneur sain.
- [x] **BF51. Semis des variables d'environnement avant la première écriture de `config.json` (v1.6.1) :** `load_config()` fusionne l'environnement *avant* de générer les secrets / écrire le fichier, pour que `UI_LANG`, `KAVITA_URL`, `PROVIDER_*`, `MAX_TAGS`, … prennent réellement effet sur une install neuve. Précédence `config.json` > env > défaut ; `ADMIN_PASSWORD` volontairement non semé depuis l'env.
- [x] **BF52. Hotfix — sauvegarde Kavita setup frais + Docker plug-and-play (v1.6.1, pas de bump) :** champs secrets vides dans la modal Config (POST vide = conserver) ; `KAVITA_*` vides ne bloquent plus le seed env ; erreurs d'auth Kavita explicites ; Compose/README avec `host.docker.internal:host-gateway`. Corrige le 1er setup modal qui semblait ne pas écrire les credentials (les migrations 1.6.0→1.6.1 étaient déjà OK).
- [x] **BF50. Isolation de la base dans les tests (v1.6.1) :** le test d'enrichissement bout-en-bout de `test_scraper_max_caps.py` atteignait le vrai `data/cache.db` via un `record_enrichment_telemetry()` non mocké, gonflant les compteurs lifetime et ajoutant un provider fictif `FAKE` au podium C7 à chaque exécution. Utilise désormais la fixture existante `isolated_db`.
- [x] **C29. Mode Review Manuelle (v1.6.1) :** scrape → file pending → modale pick (gradient de score, touches 1–3, bande faible rouge) + édition optionnelle + **étape couverture**, télémétrie, récap de session + **hauts-faits** sur `/stats` — pas le worker Event-pause. Durcissement intégrité : UNIQUE `series_id`, park/skip/confirm atomiques, batch sans séries garées, apply sous `_processing_lock`, SQLite WAL, sync file frontend.
- [x] **Scellage des champs / `NEEDS_RELOCK` (v1.6.1) :** soft-success après écriture Kavita + re-lock échoué → `NEEDS_RELOCK` orange (pas COMPLETED simple) ; retry seal différé, bouton 🔒, filtre, `POST /api/series/<id>/seal-locks` (+ bulk). Seal OK → COMPLETED.
- [x] **Pubs supporter / overlays tip (v1.6.1, C40) :** overlays ludiques rares (caps, honeymoon, silence honor) après fin de batch / récap MR riche + CTA café dans le récap MR + liens Buy Me a Coffee sidebar / topbar / À propos. Pas de paywall ; classe `.license` réservée pour un futur silence.
- [x] **C56. Avertissement RCE scrapers personnalisés (v1.6.1, issue #15, merci angusmaul) :** avertissement FR + EN bien visible en tête de `CUSTOM_SCRAPERS.md` — déposer un `.py` dans `data/scrapers/` revient à exécuter du code arbitraire au démarrage avec les droits de l'app (secrets de config, système de fichiers, réseau sortant, élargissement de l'allowlist `proxy_domains`). Signaux d'alarme concrets pour non-développeurs, mise en garde explicite sur le code généré par IA, modèle de confiance énoncé. Version courte avec lien dans les deux sections sécurité du README.
- [x] **Durcissement sécurité BF46–BF49 / C54–C55 (v1.6.1, issue #15, merci angusmaul) :** bumps CVE gunicorn/requests ; plafond 5 Mo stream `/api/proxy-image` ; en-tête webhook `X-Webhook-Token` ; `config.json` 0600 ; Docker non-root PUID/PGID + HEALTHCHECK ; `.dockerignore`.
- [x] **Provider BDTheque.com comics (v1.6.1) :** Provider `BDTHEQUE` pour https://www.bdtheque.com/ (distinct de `BEDETHEQUE` / bedetheque.com). Recherche AJAX, scrape fiche série, Magic Input, scoring unifié, covers.
- [x] **MyAnimeList API officielle (v1.6.1) :** Provider `MAL` via API v2 + `X-MAL-CLIENT-ID` (`MAL_API_KEY` = Client ID). Remplace Jikan. Manga/Book, Magic Input, scoring unifié.
- [x] **Baromètre de fiabilité (v1.6.1) :** case + curseur sidebar pour le seuil d’acceptation (`0.30`–`1.00`, défaut `0.60`) ; `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD` ; runtime via `get_match_accept_threshold()`.
- [x] **Barre de progression batch (v1.6.1) :** jauge `fait / total` au-dessus des boutons ; Socket.IO `batch_progress` depuis le `qsize()` worker ; disparaît en fin de lot / Stop.
- [x] **Options de Scraping pliables (v1.6.1) :** clic sur le titre sidebar pour afficher/masquer la carte stratégie.
- [x] **Provider Wikidata live (v1.6.1 → Magasin en v1.6.3) :** Provider `WIKIDATA` (Manga/Comic/Book) via SPARQL + Entity API ; Magic Input Q-id ; mapping partagé `wikidata_map`. Déplacé vers le Magasin en 1.6.3 (périmètre restreint). Sous-ensemble hors-ligne (C39) reporté.
- [x] **C35. Support natif "Comic (Flexible)" (v1.6.1) :** L'ID Kavita 5 n'est plus aplati en Comic. Cascade hybride : `COMIC_PROVIDER_*` d'abord, puis `PROVIDER_*` (Manga) si aucun hit utile. Recherche de couvertures = union Comic + Manga.
- [x] **C7. Tableau de bord Statistiques ludiques (v1.6.1) :** `/stats` restylée + Chart.js ; compteurs lifetime séries/matchs/ratés + taux de hit ; KPI live topbar + session ; Socket.IO `enrichment_stats` ; ~24 cartes fun + chapitre hauts-faits Review Manuelle. `ENABLE_PLAYFUL_STATS` défaut ON.
- [x] **QoS & granularité batch (v1.6.1) :** décochage auto si OK ; persistance sélection `localStorage` par bibliothèque ; masque champs ciblés batch éphémère (sidebar) ; Tout cocher / Tout décocher ; Stop coupe l’envoi ×50 + rejet des chunks tardifs ; scroll `/stats`.
- [x] **C45. Smart Scoring (v1.6.0) :** Sélection du vainqueur par score + exécution en deux vagues (`SMART_SCORING`), avec opt-in scrapers communautaires / filet `_safe_match_score`.
- [x] **C53. Politique des titres localisés (v1.6.0, issue #12) :** `LOCALIZED_TITLE_MODE`/`LANGS` globaux + `alt_title_langs` par série pour Kavita `localizedName` uniquement (jamais de réécriture de `name`) ; `titles[]` structurés AniList/MangaDex/Kitsu ; défaut = jointure multi-titres `" / "`.
- [x] **C52. Menu Aide topbar — À propos & Documentation (v1.6.0) :** menu Aide avec modal À propos, liens docs GitHub, raccourci nouveautés ; positionnement Kavita+ (texte À propos + bouton topbar à côté du café → `settings#admin-kavitaplus` de l’instance).
- [x] **C47. MangaBaka Book/LN + Durcissement API (v1.6.0) :** Support Book officiel MangaBaka avec `schema=full`, filtre `type=novel`, et correctifs de parsing (merci LazyGeniusMan).
- [x] **C46. Origins CORS autorisées (v1.6.0) :** Variable Docker `CORS_ALLOWED_ORIGINS` (CSV) pour Flask HTTP + Socket.IO derrière Traefik/HTTPS.
- [x] **C48. KAVITA_EXTERNAL_URL (v1.6.0) :** URL publique Kavita séparée pour les liens UI, vs `KAVITA_URL` interne pour les appels API Docker (merci LazyGeniusMan).
- [x] **BF19. Timeout d'écriture Kavita & faux négatif RE-LOCK (v1.6.0) :** `KAVITA_HTTP_TIMEOUT` configurable (défaut 60s) ; soft-success si écriture OK mais RE-LOCK échoue ; un retry plafonné du seul RE-LOCK (issue SqueezedByte).
- [x] **C49. MAX_TAGS configurable (v1.6.0) :** Plafond env/`config.json` des tags écrits dans Kavita (défaut 15, borné 1–100) ; scrapers + enrichissement via `get_max_tags()` — pas d'UI (retour LazyGeniusMan).
- [x] **C51. MAX_GENRES configurable (v1.6.0) :** Plafond env/`config.json` des genres (défaut 5, borné 1–50) ; scrapers à listes dynamiques + `enrichment_engine` via `get_max_genres()` — pas d'UI. Homogénéisé avec tags AniList / categories MangaUpdates sous `MAX_TAGS`.
- [x] **C32. Refonte Flask Blueprints (v1.6.0) :** Découpage de l'ancien `app.py` monolithique en Blueprints `routes/`, plus `services/`, `models.py`, et un point d'assemblage mince.
- [x] **BF20–BF41 + C50. Durcissement suite audit applicatif (v1.6.0) :** Critical/High/Medium + Low polish (plus de fallback SECRET_KEY hardcodé, clé API non loguée, proxy_domains ComicVine restreint, `MAX_GENRES` / `get_max_genres()`). `ADMIN_PASSWORD` vide laissé volontaire.
- [x] **BF42–BF45. Suivi post-audit (v1.6.0) :** logs sans fuite de clés ; redirects couverture + CDN ; blocage IPs privées ; Escape ferme le changelog ; CODE_REVIEW MAL/Nautiljon.
- [x] **BF18. Préférence d'Éditeur par Série Jamais Sauvegardée (v1.6.0) :** L'endpoint `/save-override` lisait bien l'interrupteur d'Éditeur par série (`Auto`/`VF/VA`/`VO`) mais ne le transmettait jamais à la base de données, le réinitialisant silencieusement à `GLOBAL` à chaque sauvegarde. La préférence par série est désormais correctement persistée et respectée par les scrapers.
- [x] **BF14. Correction Corruption LocalizedName & Crash KOReader/Kamare (v1.5.8) :** `update_series_general()` récupère désormais systématiquement l'état complet de la série avant d'écrire, empêchant Kavita d'effacer silencieusement `LocalizedName` et de déverrouiller de force `NameLocked`/`SortNameLocked`/`LocalizedNameLocked` lors de mises à jour partielles (ex: changement du seul format). Cause racine d'un crash signalé sur l'extension KOReader "Kamare".
- [x] **BF15. Fuite de Champs Système dans les Métadonnées (v1.5.8) :** Centralisation de l'assainissement des champs calculés en lecture seule (`totalCount`, `maxCount`, `pages`, `wordCount`) dans `update_series_metadata()`, évitant leur réinjection dans `POST /api/Series/metadata` et le risque d'exceptions de concurrence Entity Framework Core.
- [x] **BF16. Mapping du Statut "Terminé" MangaBaka (v1.5.8) :** Correction du statut brut `completed` de MangaBaka qui ne correspondait jamais à la clé interne `FINISHED`, laissant les séries terminées silencieusement bloquées en "En cours" dans Kavita.
- [x] **BF17. Typo d'Attribut `BaseScraper` (v1.5.8) :** Correction de `eeds_api_key` en `needs_api_key` sur l'attribut par défaut de la classe de base des scrapers.
- [x] **C41. Scrapers Communautaires Sideloadés (v1.5.7) :** Chargement dynamique des scripts Python déposés dans le volume utilisateur `data/scrapers/`. Permet d'ajouter des sites à la volée sans recompiler l'image Docker.
- [x] **C42. Préférence d'Éditeur (v1.5.7) :** Ajout d'un interrupteur segmenté par série (`Auto` | `VF/VA` | `VO`) pour prioriser l'éditeur localisé (ex: *Glénat*) ou l'éditeur d'origine (ex: *Shueisha*).
- [x] **C15. Titre de Secours (Fallback Expérimental) (v1.5.7) :** Filet de sécurité traduisant automatiquement un titre non-trouvé vers l'anglais pour relancer une seconde recherche sur les API.
- [x] **C43. Migrations SQLite Sécurisées (v1.5.7) :** Initialisation robuste (`_ensure_schema`) ajoutant les colonnes manquantes sans provoquer de crash HTTP 500.
- [x] **C44. Guide Scrapers & Vibecoding (v1.5.7) :** Publication de `CUSTOM_SCRAPERS.md` incluant les règles d'intégration et les Prompts IA prêts à l'emploi.
- [x] **BF10. Payload Base64 Pur (v1.5.6) :** Résolution du bug des "couvertures fantômes" où Kavita rejetait les images *Data URI*. Envoi en Base64 pur pour forcer l'écriture permanente sur le disque dur.
- [x] **BF11. Priorité streaming couvertures WebSockets (v1.5.6) :** priorité de la saisie manuelle dans la modal ; filtrage des frames live par `series_id`. *(Note : les jetons chronologiques `stream_id` sont documentés comme durcissement prévu — pas encore branchés client/serveur ; écart connu.)*
- [x] **BF12. Verrouillage Anti-Écrasement (v1.5.6) :** Appliquer une couverture manuellement décoche désormais automatiquement le champ "Couverture" de la série pour la protéger contre les futures synchronisations.
- [x] **BF13. Véritable Purge du Contexte (ISBN) (v1.5.6) :** Correction critique purgeant réellement l'ISBN lors d'une réinitialisation de contexte pour éviter les boucles de faux-positifs lors du forçage de métadonnées.

---

### 📦 Archives : Scrapers Cibles & Nouvelles Fonctionnalités (V1.5.0+)
- [x] **C1. Scraper MyAnimeList (MAL) :** Intégration de l'API publique et gratuite Jikan v4.
- [x] **C2. Scraper MangaDex :** Intégration de l'API REST officielle MangaDex v5.
- [x] **C3. Scraper Baka-Updates (MangaUpdates) :** Exploitation de l'API REST v1.
- [x] **C4. Scraper Kitsu :** Ajout de la source Kitsu comme repli international rapide.
- [x] **C5. Scraper Manga-News :** Scraping `curl_cffi` du catalogue VF.
- [x] **C6. Scraper Bédéthèque :** Scraping BeautifulSoup4 optimisé pour la bande dessinée franco-belge.
- [x] **C23. Scraper Shikimori :** API REST JSON avec évaluation multilingue.
- [x] **C24. Scraper Open Library :** API Internet Archive pour les romans, livres et BDs.
- [x] **C16. Scraper Hardcover :** Intégration des terminaux GraphQL Hasura & Typesense.
- [x] **C6. Support des BD Occidentales & Romans (B10) :** Intégration de l'API Google Books.
- [x] **C14. Recherche de Couvertures Contextuelle :** Filtrer dynamiquement les fournisseurs interrogés dans la modal selon le type de bibliothèque Kavita.
- [x] **C17. Support Reverse Proxy & Subpath :** Ajout de la variable `ROOT_PATH` et d'un middleware WSGI.
- [x] **C18. Le "Champ Magique" (Routage URL Intelligent) :** Remplacement de l'ancien champ d'ID par un analyseur universel d'URL/ID.
- [x] **C19. Scraping Granulaire (Champs Ciblés) :** Prise en charge du ciblage individuel des 12 champs de métadonnées.
- [x] **C20. Auto-Réparation de la Configuration (Self-Healing) :** Validation dynamique des cascades de recherche.
- [x] **C21. Moteur Smart ID Match :** Validateur par similarité de titre (>50%).
- [x] **C22. Mappage API Kavita Étendu :** Ajout des Éditeurs (Staff), Lettreurs, Encreurs et de la Langue native.
- [x] **C25. Streaming de Couvertures par WebSockets (*Progressive Loading*) :** Envoi en direct au fil de l'eau via Socket.IO des images.
- [x] **C26. Forçage des Ignorés & Amnesties Élargies :** Traitement des séries ignorées cochées en batch et réinitialisation conjointe de `NOT_FOUND` et `IGNORED`.
- [x] **C28. Extraction Profonde des Métadonnées Kavita & Scoring Unifié :** Pré-récupérer les métadonnées existantes (`auteurs`, `ISBN`) avant le scraping.
- [x] **C34. Rate-Limiter Intelligente & Throttling Dynamique :** Remplacement des pauses fixes par un régulateur par horodatage (`LAST_REQUEST_TIMES`).
- [x] **C36. Suite de Tests & Benchmarks Qualité :** Scripts unitaires autonomes pour tester 20 cas limites de scoring.
- [x] **C37. Refonte ComicVine & Fallback Tome #1 :** Utilisation de l'endpoint structuré `/volumes/?filter=name:`.
- [x] **C38. Forçage Libre des Fournisseurs :** Déblocage de l'ensemble des scrapers dans le menu déroulant du Champ Magique.
- [x] **C9. Traducteur Multi-API Résilient :** Couche d'abstraction combinant Microsoft Azure Translator et DeepL.
- [x] **C10. Routage Dynamique & Pattern Factory :** Extraction automatique du type de bibliothèque Kavita.
- [x] **C11. Scraper ComicVine Hybride :** Recherche adaptative par album (Issue) et résolution de la série parente (Volume).
- [x] **C12. Nettoyage Contextuel de Titre :** Logique de nettoyage adaptative selon le format du média.
- [x] **C13. Purge de Fournisseur (Nautiljon) :** Retrait définitif de Nautiljon du routage par défaut face aux blocages Cloudflare.

### 🐛 Archives : Corrections de Bugs & Sécurité (V1.4.x / V1.5.x)
- [x] **BF1. Bug de Surcharge de Mot de Passe en Env Var :** Résolution du problème où vider le mot de passe dans le `docker-compose.yml` échouait.
- [x] **BF2. Nettoyage de Session à la Déconnexion :** Le bouton de déconnexion détruit désormais entièrement le cookie de session longue durée.
- [x] **BF3. Recherche de Couvertures Contextuelle** : Correction d'une régression où la recherche manuelle d'images interrogeait tous les fournisseurs.
- [x] **BF4. Bug d'Écrasement par les Spin-offs (Bédéthèque)** : Résolution d'un problème avec le tri alphabétique.
- [x] **BF5. Correction du Parsing des Éditeurs (Publisher) :** Résolution d'un oubli de parsing.
- [x] **BF6. Option de Désactivation de la Traduction :** Ajout d'un paramètre (`NONE`) pour désactiver complètement le pipeline de traduction.
- [x] **BF7. Contexte Jinja Global de Version :** Rendu de la variable `app_version` directement depuis `CHANGELOG.md`.
- [x] **BF8. Moteur Dynamique de Clés API :** Support de `needs_api_key=True` dans `BaseScraper`.
- [x] **BF9. Traductions Décentralisées (i18n) :** Les scrapers encapsulent désormais leurs propres traductions via `self.t()`.

### 🏗️ Archives : Ergonomie & Refonte Visuelle (V1.4.0 / V1.5.0)
- [x] **B1 à B6 :** Mappage et verrouillage des Genres, Tags, titres localisés, et staff étendu dans Kavita.
- [x] **B7 à B9 :** Statut "Ignoré", Polling d'Auto-Sync, routage de repli intelligent, et fusion des données.
- [x] **B11. Authentification globale :** Verrouillage de l'interface par variable d'environnement `ADMIN_PASSWORD`.
- [x] **B14 à B15 :** Modal visuelle de sélection des couvertures & API MangaBaka V2.
- [x] **B16. Nettoyeur Regex Ultime :** Centralisation de `clean_title()`.
- [x] **B17. Barre de recherche AJAX :** Filtrage instantané côté client sans rechargement de page.
- [x] **B18. Métadonnées Étendues :** Éditeurs, classification d'âge, et sens de lecture automatique.
- [x] **B19. Identifiants & Liens Web :** Remplissage des ID natifs et génération automatique de WebLinks cliquables.
- [x] **B20. Refonte de l'Architecture UI :** Déplacement de la configuration technique dans une modal dédiée.
- [x] **B21. Recherche Manuelle de Couvertures :** Saisie libre d'un titre alternatif directement dans la modal.
- [x] **B22. Suivi de Traitement Live (Pulsation Violette) :** Coloration dynamique et défilement automatique vers la ligne active.
- [x] **B23. Recherche d'ID Rapide (Quick Lookup) :** Bouton loupe ouvrant une recherche pré-remplie sur AniList.
- [x] **B24. Persistance de l'Espace de Travail :** Sauvegarde automatique des filtres dans le `localStorage`.

### 🛠️ Archives : Fondations & Sécurité (V1.3+)
- [x] **A1 à A6 :** Intégration de l'API, Live Logs, 100% AJAX, ponts de traductions globaux, UI adaptative.
- [x] **A7 à A9 :** Cache SQLite auto-nettoyant, écrans d'erreurs de connexion explicites, déploiement sans configuration.
- [x] **A10. Serveur WSGI de Production :** Migration vers l'architecture asynchrone Eventlet + Gunicorn.
- [x] **A11. Sécurité Globale :** Proxy d'images anti-SSRF, authentification immunisée contre les attaques temporelles (`compare_digest`), cookies HttpOnly, masquage des clés API, webhooks sécurisés par jeton.
