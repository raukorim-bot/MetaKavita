# ðŸš€ MetaKavita - Roadmap & To-Do List

**Concept:** Metadata scraping and enrichment tool for Kavita (alternative to Komf), designed for lightweight, self-hosted deployment.
**Philosophy:** Lightweight, pragmatic, highly secure, and optimized for Manga, Comics & Literature.

---

## Sommaire / Table of Contents
1. [ðŸ‡ºðŸ‡¸ English Roadmap](#-english-roadmap)
2. [ðŸ‡«ðŸ‡· Feuille de Route FranÃ§aise](#-feuille-de-route-franÃ§aise)

---

## ðŸ‡ºðŸ‡¸ English Roadmap

### ðŸ”® Backlog & Future Features (To-Do)
- [ ] **C29. Interactive Manual Batch Mode (QoS):** Add an "Automatic / Manual (QoS)" toggle for batch processing.
    - In Manual mode, the backend queries metadata providers and emits candidate choices over WebSockets.
    - The frontend opens an interactive selection modal and pauses the worker using `eventlet.event.Event`.
    - The user selects the exact match or skips, sending the decision back to resume the queue.
- [ ] **C30. Francophone Book Scrapers:** Integrate dedicated French literature sources (Babelio, SensCritique) without requiring API keys.
- [ ] **C31. Kavita Deduplication Tool:** Dedicated UI panel to detect and merge duplicate series or volumes in Kavita.
- [ ] **C33. Browser Extension "MetaKavita Companion":** Floating widget overlay directly on top of the Kavita Web UI to trigger MetaKavita updates natively.
- [ ] **C8. Resiliency & Rate-Limiting Control:** Add an automatic exponential backoff retry mechanism to prevent API blocks (429 errors) during very large batches.
- [ ] **C39. Offline Scraper Mode (Local DB / Dumps):** Optional local SQLite subset for Wikidata (or similar) when API rate limits or offline labs matter.
- [ ] **C40. Support the Developer (Donations):** Add a non-intrusive "Buy Me a Coffee" or "Ko-fi" link in the GitHub README and the application's sidebar footer to allow the community to support the project.

---

### âœ¨ Latest Releases (v1.5.6 to v1.6.1)
- [x] **BF46. Dependency CVE bumps (unreleased):** `gunicorn` `21.2.0` â†’ `23.0.0` (two request-smuggling advisories) and `requests` `2.31.0` â†’ `2.33.1` (three advisories, the most recent only fixed in `2.33.0`). `googletrans` deliberately unchanged.
- [x] **BF47â€“BF49. Misc Hardening (unreleased, issue #15):** 5 MB streamed cap on `/api/proxy-image` (413 past the limit, redirect hops closed as followed); webhook accepts `X-Webhook-Token` with `?token=` kept working and byte-wise token comparison; `config.json` written 0600 on every save, best-effort.
- [x] **BDTheque.com comics provider (v1.6.1):** Provider `BDTHEQUE` for https://www.bdtheque.com/ (distinct from `BEDETHEQUE` / bedetheque.com). AJAX series search, series page scrape, Magic Input, unified scoring, covers.
- [x] **MyAnimeList official API (v1.6.1):** Provider `MAL` via API v2 + `X-MAL-CLIENT-ID` (`MAL_API_KEY` = Client ID). Replaces retired Jikan. Manga/Book, Magic Input, unified scoring.
- [x] **Reliability barometer (v1.6.1):** Sidebar unlock + slider for match accept threshold (`0.30`â€“`1.00`, default `0.60`); `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD`; runtime via `get_match_accept_threshold()`.
- [x] **Batch progress bar (v1.6.1):** `done / total` above batch buttons; Socket.IO `batch_progress` from worker `qsize()`; hides on finish/Stop.
- [x] **Collapsible Scraping Options (v1.6.1):** Click sidebar title to show/hide the strategy card.
- [x] **Wikidata live provider (v1.6.1):** Provider `WIKIDATA` (Manga/Comic/Book) via SPARQL + Entity API; Magic Input Q-id; shared `wikidata_map`. Offline subset (C39) deferred.
- [x] **C35. Native "Comic (Flexible)" Support (v1.6.1):** Kavita Library Type ID 5 is no longer flattened to Comic. Hybrid cascade: `COMIC_PROVIDER_*` first, then `PROVIDER_*` (Manga) if no useful hit. Cover search unions Comic + Manga scrapers.
- [x] **C7. Playful Statistics Dashboard (v1.6.1):** Restyled `/stats` + Chart.js; lifetime `series_enriched` / `matches_won` / `series_missed` + hit-rate; live topbar KPIs + session counter; Socket.IO `enrichment_stats`; ~24 fun cards. `ENABLE_PLAYFUL_STATS` default ON.
- [x] **Batch QoS & Granularity (v1.6.1):** Auto-uncheck on success; `localStorage` selection persist per library; ephemeral batch targeted-fields mask (sidebar `<details>`); Check all / Uncheck all (sidebar + per-series overrides); Stop aborts Ã—50 enqueue loop + server rejects late chunks; `/stats` scroll fix.
- [x] **C45. Smart Scoring (v1.6.0):** Score-based provider winner selection + two-wave parallel execution (`SMART_SCORING` sidebar toggle), with community-scraper opt-in/`_safe_match_score` hardening.
- [x] **C53. Localized Titles Policy (v1.6.0, issue #12):** Global `LOCALIZED_TITLE_MODE`/`LANGS` + per-series `alt_title_langs` for Kavita `localizedName` only (never rewrite `name`); structured `titles[]` on AniList/MangaDex/Kitsu; default remains multi-title `" / "` join.
- [x] **C52. Topbar Help Menu â€” About & Documentation (v1.6.0):** Help dropdown with About modal, GitHub doc links, changelog shortcut; Kavita+ support positioning (About copy + topbar Kavita+ beside BMC â†’ instance `settings#admin-kavitaplus`).
- [x] **C47. MangaBaka Book/LN + API Hardening (v1.6.0):** Official MangaBaka Book support with `schema=full`, `type=novel` filter, and related parsing fixes (thanks LazyGeniusMan).
- [x] **C46. CORS Allowed Origins (v1.6.0):** Docker env `CORS_ALLOWED_ORIGINS` (CSV explicit origins) for Flask HTTP + Socket.IO behind Traefik/HTTPS self-hosts.
- [x] **C48. KAVITA_EXTERNAL_URL (v1.6.0):** Separate public Kavita URL for browser UI links vs internal `KAVITA_URL` for Docker API calls (thanks LazyGeniusMan).
- [x] **BF19. Kavita Write Timeout & False-Negative RE-LOCK (v1.6.0):** Configurable `KAVITA_HTTP_TIMEOUT` (default 60s) for write POSTs; metadata/general 2-pass treats write-OK + RE-LOCK failure as soft success; one capped RE-LOCK-only retry (issue SqueezedByte).
- [x] **C49. Configurable MAX_TAGS (v1.6.0):** Env/`config.json` cap on tags written to Kavita (default 15, range 1â€“100); scrapers + enrichment use `get_max_tags()` â€” no UI (feedback LazyGeniusMan).
- [x] **C51. Configurable MAX_GENRES (v1.6.0):** Env/`config.json` cap on genres (default 5, range 1â€“50); dynamic-list scrapers + `enrichment_engine` use `get_max_genres()` â€” no UI. Homogenized with AniList tags / MangaUpdates categories under `MAX_TAGS`.
- [x] **C32. Flask Blueprints Refactoring (v1.6.0):** Modularized the former monolithic `app.py` into Blueprints under `routes/`, plus `services/`, `models.py`, and a thin composition root.
- [x] **BF20â€“BF41 + C50. Application Audit Hardening (v1.6.0):** Critical/High/Medium plus Low polish (no hardcoded SECRET_KEY fallback, API key not logged, ComicVine proxy_domains narrowed, `MAX_GENRES` / `get_max_genres()`). Optional empty `ADMIN_PASSWORD` left intentional.
- [x] **BF42â€“BF45. Post-Audit Follow-ups (v1.6.0):** Credential-safe exception logging; safe cover redirects + CDN `proxy_domains`; private IP block in `url_allowlist`; Escape closes changelog; CODE_REVIEW MAL/Nautiljon cleanup.
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
- [x] **BF11. WebSocket Cover Stream Priority (v1.5.6):** Manual input priority restored in the cover modal; live cover frames are filtered by `series_id`. *(Note: chronological `stream_id` tokens are documented as intended hardening â€” not yet wired in client/server; tracked as a known gap.)*
- [x] **BF12. Smart Auto-Cover Locking (v1.5.6):** Manually applying a cover from the modal now automatically unchecks the "Cover" targeted field to protect it from background sync overwrites.
- [x] **BF13. True Context Reset (ISBN Purge) (v1.5.6):** Fixed a critical oversight where forcing an update with "Context Reset" still retained the Kavita ISBN, causing persistent false-positive matches. The ISBN is now properly purged to guarantee a true clean slate.

---

### ðŸ“¦ Archive: Advanced Features & Core Architecture (V1.5.0+)
- [x] **C1. MyAnimeList (MAL) Scraper:** Integrated the public and free Jikan API v4.
- [x] **C2. MangaDex Scraper:** Integrated the official MangaDex REST API v5 for rich metadata tags, content rating filters, and candidate weighting.
- [x] **C3. Baka-Updates (MangaUpdates) Scraper:** Integrated the v1 REST API to retrieve associated alternative titles and keyword penalty scoring.
- [x] **C4. Kitsu Scraper:** Add Kitsu JSON:API as a reliable global fallback source.
- [x] **C5. Manga-News Scraper:** Implemented `curl_cffi` scraping of the French licensing catalog.
- [x] **C6. Scraper BedethÃ¨que:** Scraping BeautifulSoup4 for Franco-Belgian comics.
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

### ðŸ› Archive: Bug Fixes & Architecture Shifts (V1.4.x / V1.5.x)
- [x] **BF1. Admin Password Env Var Override Bug:** Resolved the issue where clearing the admin password via `docker-compose.yml` failed.
- [x] **BF2. Permanent Auth Cookie Cleansing:** Ensured a hard logout completely destroys the long-lived session cookie via `expires=0`.
- [x] **BF3. BÃ©dÃ©thÃ¨que Spin-off Override Bug**: Fixed an issue where searching for a main series would return covers from its spin-offs due to alphabetical sorting.
- [x] **BF4. Context-Aware Cover Fetching**: Fixed a regression where the manual cover search queried all scrapers blindly.
- [x] **BF5. Publisher Metadata Parsing Fix:** Corrected an oversight where publisher metadata wasn't properly scraped.
- [x] **BF6. Disable Translation Option:** Added a configuration setting (`NONE`) to disable the translation pipeline.
- [x] **BF7. Global App Version Jinja Context:** Render `app_version` directly from `CHANGELOG.md` in the UI.
- [x] **BF8. Dynamic API Key Engine:** `BaseScraper` now supports `needs_api_key=True` to auto-generate forms dynamically.
- [x] **BF9. Decentralized Translations (i18n):** Scrapers now encapsulate their own translations via `self.t()`.

### ðŸ—ï¸ Archive: Ergonomics & Interface Overhaul (V1.4.0)
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

### ðŸ› ï¸ Archive: Foundations & Security (V1.3+)
- [x] **A1 to A6:** Secure API integration, Live Logs, 100% AJAX, Global Translation bridges, Responsive UI.
- [x] **A7 to A9:** Self-cleaning SQLite cache, explicit connection error indicators, Zero-Setup deployment.
- [x] **A10. Production WSGI Server:** Eventlet + Gunicorn asynchronous stack.
- [x] **A11. Global Security:** SSRF Protection on Image Proxy, Timing-Attack immune authentication (`secrets.compare_digest`), HttpOnly Session cookies, hidden API keys in DOM, Token-protected webhooks.

<br><br>

---

## ðŸ‡«ðŸ‡· Feuille de Route FranÃ§aise

### ðŸ”® Backlog & FonctionnalitÃ©s Futures (Ã€ Faire)
- [ ] **C29. Mode Batch Manuel Interactif (QoS) :** Ajouter un sÃ©lecteur "Automatique / Manuel (QoS)" pour les traitements par lots.
    - En mode Manuel, le backend rÃ©cupÃ¨re les candidats et les envoie via WebSockets.
    - Le frontend affiche une modale de choix et met le worker en pause via `eventlet.event.Event`.
    - L'utilisateur valide le bon rÃ©sultat ou passe, dÃ©bloquant le worker pour le fichier suivant.
- [ ] **C30. Scrapers LittÃ©raires Francophones :** IntÃ©grer des sources spÃ©cialisÃ©es en littÃ©rature franÃ§aise (Babelio, SensCritique) sans clÃ© API.
- [ ] **C31. Outil de DÃ©duplication Kavita :** Panneau UI pour dÃ©tecter et fusionner les doublons dans Kavita.
- [ ] **C33. Extension Navigateur "MetaKavita Companion" :** Widget flottant en surcouche directement sur l'interface Web de Kavita pour dÃ©clencher les mises Ã  jour MetaKavita nativement.
- [ ] **C8. Gestion de la RÃ©silience d'API :** SystÃ¨me de retry automatique avec attente exponentielle pour contourner le rate limiting lors des trÃ¨s gros batchs.
- [ ] **C39. Mode Scraper Hors-Ligne (Local DB / Dumps) :** Sous-ensemble SQLite Wikidata (ou Ã©quivalent) optionnel quand les quotas API ou un labo hors-ligne importent.
- [ ] **C40. Soutien au dÃ©veloppeur (Dons) :** Ajouter un lien discret "Buy Me a Coffee" ou "Ko-fi" dans le README GitHub et le pied de page de l'interface pour permettre Ã  la communautÃ© de soutenir le projet.

---

### âœ¨ DerniÃ¨res NouveautÃ©s (v1.5.6 Ã  v1.6.1)
- [x] **BF46. MontÃ©e de versions CVE (non publiÃ©) :** `gunicorn` `21.2.0` â†’ `23.0.0` (deux failles de *request smuggling*) et `requests` `2.31.0` â†’ `2.33.1` (trois failles, la plus rÃ©cente corrigÃ©e seulement en `2.33.0`). `googletrans` volontairement inchangÃ©.
- [x] **BF47â€“BF49. Durcissements divers (non publiÃ©, issue #15) :** plafond de 5 Mo en flux sur `/api/proxy-image` (413 au-delÃ , hops de redirection fermÃ©s au fil de l'eau) ; webhook acceptant `X-Webhook-Token` avec `?token=` conservÃ© et comparaison du jeton en octets ; `config.json` Ã©crit en 0600 Ã  chaque sauvegarde, best-effort.
- [x] **Provider BDTheque.com comics (v1.6.1) :** Provider `BDTHEQUE` pour https://www.bdtheque.com/ (distinct de `BEDETHEQUE` / bedetheque.com). Recherche AJAX, scrape fiche sÃ©rie, Magic Input, scoring unifiÃ©, covers.
- [x] **MyAnimeList API officielle (v1.6.1) :** Provider `MAL` via API v2 + `X-MAL-CLIENT-ID` (`MAL_API_KEY` = Client ID). Remplace Jikan. Manga/Book, Magic Input, scoring unifiÃ©.
- [x] **BaromÃ¨tre de fiabilitÃ© (v1.6.1) :** case + curseur sidebar pour le seuil dâ€™acceptation (`0.30`â€“`1.00`, dÃ©faut `0.60`) ; `MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD` ; runtime via `get_match_accept_threshold()`.
- [x] **Barre de progression batch (v1.6.1) :** jauge `fait / total` au-dessus des boutons ; Socket.IO `batch_progress` depuis le `qsize()` worker ; disparaÃ®t en fin de lot / Stop.
- [x] **Options de Scraping pliables (v1.6.1) :** clic sur le titre sidebar pour afficher/masquer la carte stratÃ©gie.
- [x] **Provider Wikidata live (v1.6.1) :** Provider `WIKIDATA` (Manga/Comic/Book) via SPARQL + Entity API ; Magic Input Q-id ; mapping partagÃ© `wikidata_map`. Sous-ensemble hors-ligne (C39) reportÃ©.
- [x] **C35. Support natif "Comic (Flexible)" (v1.6.1) :** L'ID Kavita 5 n'est plus aplati en Comic. Cascade hybride : `COMIC_PROVIDER_*` d'abord, puis `PROVIDER_*` (Manga) si aucun hit utile. Recherche de couvertures = union Comic + Manga.
- [x] **C7. Tableau de bord Statistiques ludiques (v1.6.1) :** `/stats` restylÃ©e + Chart.js ; compteurs lifetime sÃ©ries/matchs/ratÃ©s + taux de hit ; KPI live topbar + session ; Socket.IO `enrichment_stats` ; ~24 cartes fun. `ENABLE_PLAYFUL_STATS` dÃ©faut ON.
- [x] **QoS & granularitÃ© batch (v1.6.1) :** dÃ©cochage auto si OK ; persistance sÃ©lection `localStorage` par bibliothÃ¨que ; masque champs ciblÃ©s batch Ã©phÃ©mÃ¨re (sidebar) ; Tout cocher / Tout dÃ©cocher ; Stop coupe lâ€™envoi Ã—50 + rejet des chunks tardifs ; scroll `/stats`.
- [x] **C45. Smart Scoring (v1.6.0) :** SÃ©lection du vainqueur par score + exÃ©cution en deux vagues (`SMART_SCORING`), avec opt-in scrapers communautaires / filet `_safe_match_score`.
- [x] **C53. Politique des titres localisÃ©s (v1.6.0, issue #12) :** `LOCALIZED_TITLE_MODE`/`LANGS` globaux + `alt_title_langs` par sÃ©rie pour Kavita `localizedName` uniquement (jamais de rÃ©Ã©criture de `name`) ; `titles[]` structurÃ©s AniList/MangaDex/Kitsu ; dÃ©faut = jointure multi-titres `" / "`.
- [x] **C52. Menu Aide topbar â€” Ã€ propos & Documentation (v1.6.0) :** menu Aide avec modal Ã€ propos, liens docs GitHub, raccourci nouveautÃ©s ; positionnement Kavita+ (texte Ã€ propos + bouton topbar Ã  cÃ´tÃ© du cafÃ© â†’ `settings#admin-kavitaplus` de lâ€™instance).
- [x] **C47. MangaBaka Book/LN + Durcissement API (v1.6.0) :** Support Book officiel MangaBaka avec `schema=full`, filtre `type=novel`, et correctifs de parsing (merci LazyGeniusMan).
- [x] **C46. Origins CORS autorisÃ©es (v1.6.0) :** Variable Docker `CORS_ALLOWED_ORIGINS` (CSV) pour Flask HTTP + Socket.IO derriÃ¨re Traefik/HTTPS.
- [x] **C48. KAVITA_EXTERNAL_URL (v1.6.0) :** URL publique Kavita sÃ©parÃ©e pour les liens UI, vs `KAVITA_URL` interne pour les appels API Docker (merci LazyGeniusMan).
- [x] **BF19. Timeout d'Ã©criture Kavita & faux nÃ©gatif RE-LOCK (v1.6.0) :** `KAVITA_HTTP_TIMEOUT` configurable (dÃ©faut 60s) ; soft-success si Ã©criture OK mais RE-LOCK Ã©choue ; un retry plafonnÃ© du seul RE-LOCK (issue SqueezedByte).
- [x] **C49. MAX_TAGS configurable (v1.6.0) :** Plafond env/`config.json` des tags Ã©crits dans Kavita (dÃ©faut 15, bornÃ© 1â€“100) ; scrapers + enrichissement via `get_max_tags()` â€” pas d'UI (retour LazyGeniusMan).
- [x] **C51. MAX_GENRES configurable (v1.6.0) :** Plafond env/`config.json` des genres (dÃ©faut 5, bornÃ© 1â€“50) ; scrapers Ã  listes dynamiques + `enrichment_engine` via `get_max_genres()` â€” pas d'UI. HomogÃ©nÃ©isÃ© avec tags AniList / categories MangaUpdates sous `MAX_TAGS`.
- [x] **C32. Refonte Flask Blueprints (v1.6.0) :** DÃ©coupage de l'ancien `app.py` monolithique en Blueprints `routes/`, plus `services/`, `models.py`, et un point d'assemblage mince.
- [x] **BF20â€“BF41 + C50. Durcissement suite audit applicatif (v1.6.0) :** Critical/High/Medium + Low polish (plus de fallback SECRET_KEY hardcodÃ©, clÃ© API non loguÃ©e, proxy_domains ComicVine restreint, `MAX_GENRES` / `get_max_genres()`). `ADMIN_PASSWORD` vide laissÃ© volontaire.
- [x] **BF42â€“BF45. Suivi post-audit (v1.6.0) :** logs sans fuite de clÃ©s ; redirects couverture + CDN ; blocage IPs privÃ©es ; Escape ferme le changelog ; CODE_REVIEW MAL/Nautiljon.
- [x] **BF18. PrÃ©fÃ©rence d'Ã‰diteur par SÃ©rie Jamais SauvegardÃ©e (v1.6.0) :** L'endpoint `/save-override` lisait bien l'interrupteur d'Ã‰diteur par sÃ©rie (`Auto`/`VF/VA`/`VO`) mais ne le transmettait jamais Ã  la base de donnÃ©es, le rÃ©initialisant silencieusement Ã  `GLOBAL` Ã  chaque sauvegarde. La prÃ©fÃ©rence par sÃ©rie est dÃ©sormais correctement persistÃ©e et respectÃ©e par les scrapers.
- [x] **BF14. Correction Corruption LocalizedName & Crash KOReader/Kamare (v1.5.8) :** `update_series_general()` rÃ©cupÃ¨re dÃ©sormais systÃ©matiquement l'Ã©tat complet de la sÃ©rie avant d'Ã©crire, empÃªchant Kavita d'effacer silencieusement `LocalizedName` et de dÃ©verrouiller de force `NameLocked`/`SortNameLocked`/`LocalizedNameLocked` lors de mises Ã  jour partielles (ex: changement du seul format). Cause racine d'un crash signalÃ© sur l'extension KOReader "Kamare".
- [x] **BF15. Fuite de Champs SystÃ¨me dans les MÃ©tadonnÃ©es (v1.5.8) :** Centralisation de l'assainissement des champs calculÃ©s en lecture seule (`totalCount`, `maxCount`, `pages`, `wordCount`) dans `update_series_metadata()`, Ã©vitant leur rÃ©injection dans `POST /api/Series/metadata` et le risque d'exceptions de concurrence Entity Framework Core.
- [x] **BF16. Mapping du Statut "TerminÃ©" MangaBaka (v1.5.8) :** Correction du statut brut `completed` de MangaBaka qui ne correspondait jamais Ã  la clÃ© interne `FINISHED`, laissant les sÃ©ries terminÃ©es silencieusement bloquÃ©es en "En cours" dans Kavita.
- [x] **BF17. Typo d'Attribut `BaseScraper` (v1.5.8) :** Correction de `eeds_api_key` en `needs_api_key` sur l'attribut par dÃ©faut de la classe de base des scrapers.
- [x] **C41. Scrapers Communautaires SideloadÃ©s (v1.5.7) :** Chargement dynamique des scripts Python dÃ©posÃ©s dans le volume utilisateur `data/scrapers/`. Permet d'ajouter des sites Ã  la volÃ©e sans recompiler l'image Docker.
- [x] **C42. PrÃ©fÃ©rence d'Ã‰diteur (v1.5.7) :** Ajout d'un interrupteur segmentÃ© par sÃ©rie (`Auto` | `VF/VA` | `VO`) pour prioriser l'Ã©diteur localisÃ© (ex: *GlÃ©nat*) ou l'Ã©diteur d'origine (ex: *Shueisha*).
- [x] **C15. Titre de Secours (Fallback ExpÃ©rimental) (v1.5.7) :** Filet de sÃ©curitÃ© traduisant automatiquement un titre non-trouvÃ© vers l'anglais pour relancer une seconde recherche sur les API.
- [x] **C43. Migrations SQLite SÃ©curisÃ©es (v1.5.7) :** Initialisation robuste (`_ensure_schema`) ajoutant les colonnes manquantes sans provoquer de crash HTTP 500.
- [x] **C44. Guide Scrapers & Vibecoding (v1.5.7) :** Publication de `CUSTOM_SCRAPERS.md` incluant les rÃ¨gles d'intÃ©gration et les Prompts IA prÃªts Ã  l'emploi.
- [x] **BF10. Payload Base64 Pur (v1.5.6) :** RÃ©solution du bug des "couvertures fantÃ´mes" oÃ¹ Kavita rejetait les images *Data URI*. Envoi en Base64 pur pour forcer l'Ã©criture permanente sur le disque dur.
- [x] **BF11. PrioritÃ© streaming couvertures WebSockets (v1.5.6) :** prioritÃ© de la saisie manuelle dans la modal ; filtrage des frames live par `series_id`. *(Note : les jetons chronologiques `stream_id` sont documentÃ©s comme durcissement prÃ©vu â€” pas encore branchÃ©s client/serveur ; Ã©cart connu.)*
- [x] **BF12. Verrouillage Anti-Ã‰crasement (v1.5.6) :** Appliquer une couverture manuellement dÃ©coche dÃ©sormais automatiquement le champ "Couverture" de la sÃ©rie pour la protÃ©ger contre les futures synchronisations.
- [x] **BF13. VÃ©ritable Purge du Contexte (ISBN) (v1.5.6) :** Correction critique purgeant rÃ©ellement l'ISBN lors d'une rÃ©initialisation de contexte pour Ã©viter les boucles de faux-positifs lors du forÃ§age de mÃ©tadonnÃ©es.

---

### ðŸ“¦ Archives : Scrapers Cibles & Nouvelles FonctionnalitÃ©s (V1.5.0+)
- [x] **C1. Scraper MyAnimeList (MAL) :** IntÃ©gration de l'API publique et gratuite Jikan v4.
- [x] **C2. Scraper MangaDex :** IntÃ©gration de l'API REST officielle MangaDex v5.
- [x] **C3. Scraper Baka-Updates (MangaUpdates) :** Exploitation de l'API REST v1.
- [x] **C4. Scraper Kitsu :** Ajout de la source Kitsu comme repli international rapide.
- [x] **C5. Scraper Manga-News :** Scraping `curl_cffi` du catalogue VF.
- [x] **C6. Scraper BÃ©dÃ©thÃ¨que :** Scraping BeautifulSoup4 optimisÃ© pour la bande dessinÃ©e franco-belge.
- [x] **C23. Scraper Shikimori :** API REST JSON avec Ã©valuation multilingue.
- [x] **C24. Scraper Open Library :** API Internet Archive pour les romans, livres et BDs.
- [x] **C16. Scraper Hardcover :** IntÃ©gration des terminaux GraphQL Hasura & Typesense.
- [x] **C6. Support des BD Occidentales & Romans (B10) :** IntÃ©gration de l'API Google Books.
- [x] **C14. Recherche de Couvertures Contextuelle :** Filtrer dynamiquement les fournisseurs interrogÃ©s dans la modal selon le type de bibliothÃ¨que Kavita.
- [x] **C17. Support Reverse Proxy & Subpath :** Ajout de la variable `ROOT_PATH` et d'un middleware WSGI.
- [x] **C18. Le "Champ Magique" (Routage URL Intelligent) :** Remplacement de l'ancien champ d'ID par un analyseur universel d'URL/ID.
- [x] **C19. Scraping Granulaire (Champs CiblÃ©s) :** Prise en charge du ciblage individuel des 12 champs de mÃ©tadonnÃ©es.
- [x] **C20. Auto-RÃ©paration de la Configuration (Self-Healing) :** Validation dynamique des cascades de recherche.
- [x] **C21. Moteur Smart ID Match :** Validateur par similaritÃ© de titre (>50%).
- [x] **C22. Mappage API Kavita Ã‰tendu :** Ajout des Ã‰diteurs (Staff), Lettreurs, Encreurs et de la Langue native.
- [x] **C25. Streaming de Couvertures par WebSockets (*Progressive Loading*) :** Envoi en direct au fil de l'eau via Socket.IO des images.
- [x] **C26. ForÃ§age des IgnorÃ©s & Amnesties Ã‰largies :** Traitement des sÃ©ries ignorÃ©es cochÃ©es en batch et rÃ©initialisation conjointe de `NOT_FOUND` et `IGNORED`.
- [x] **C28. Extraction Profonde des MÃ©tadonnÃ©es Kavita & Scoring UnifiÃ© :** PrÃ©-rÃ©cupÃ©rer les mÃ©tadonnÃ©es existantes (`auteurs`, `ISBN`) avant le scraping.
- [x] **C34. Rate-Limiter Intelligente & Throttling Dynamique :** Remplacement des pauses fixes par un rÃ©gulateur par horodatage (`LAST_REQUEST_TIMES`).
- [x] **C36. Suite de Tests & Benchmarks QualitÃ© :** Scripts unitaires autonomes pour tester 20 cas limites de scoring.
- [x] **C37. Refonte ComicVine & Fallback Tome #1 :** Utilisation de l'endpoint structurÃ© `/volumes/?filter=name:`.
- [x] **C38. ForÃ§age Libre des Fournisseurs :** DÃ©blocage de l'ensemble des scrapers dans le menu dÃ©roulant du Champ Magique.
- [x] **C9. Traducteur Multi-API RÃ©silient :** Couche d'abstraction combinant Microsoft Azure Translator et DeepL.
- [x] **C10. Routage Dynamique & Pattern Factory :** Extraction automatique du type de bibliothÃ¨que Kavita.
- [x] **C11. Scraper ComicVine Hybride :** Recherche adaptative par album (Issue) et rÃ©solution de la sÃ©rie parente (Volume).
- [x] **C12. Nettoyage Contextuel de Titre :** Logique de nettoyage adaptative selon le format du mÃ©dia.
- [x] **C13. Purge de Fournisseur (Nautiljon) :** Retrait dÃ©finitif de Nautiljon du routage par dÃ©faut face aux blocages Cloudflare.

### ðŸ› Archives : Corrections de Bugs & SÃ©curitÃ© (V1.4.x / V1.5.x)
- [x] **BF1. Bug de Surcharge de Mot de Passe en Env Var :** RÃ©solution du problÃ¨me oÃ¹ vider le mot de passe dans le `docker-compose.yml` Ã©chouait.
- [x] **BF2. Nettoyage de Session Ã  la DÃ©connexion :** Le bouton de dÃ©connexion dÃ©truit dÃ©sormais entiÃ¨rement le cookie de session longue durÃ©e.
- [x] **BF3. Recherche de Couvertures Contextuelle** : Correction d'une rÃ©gression oÃ¹ la recherche manuelle d'images interrogeait tous les fournisseurs.
- [x] **BF4. Bug d'Ã‰crasement par les Spin-offs (BÃ©dÃ©thÃ¨que)** : RÃ©solution d'un problÃ¨me avec le tri alphabÃ©tique.
- [x] **BF5. Correction du Parsing des Ã‰diteurs (Publisher) :** RÃ©solution d'un oubli de parsing.
- [x] **BF6. Option de DÃ©sactivation de la Traduction :** Ajout d'un paramÃ¨tre (`NONE`) pour dÃ©sactiver complÃ¨tement le pipeline de traduction.
- [x] **BF7. Contexte Jinja Global de Version :** Rendu de la variable `app_version` directement depuis `CHANGELOG.md`.
- [x] **BF8. Moteur Dynamique de ClÃ©s API :** Support de `needs_api_key=True` dans `BaseScraper`.
- [x] **BF9. Traductions DÃ©centralisÃ©es (i18n) :** Les scrapers encapsulent dÃ©sormais leurs propres traductions via `self.t()`.

### ðŸ—ï¸ Archives : Ergonomie & Refonte Visuelle (V1.4.0 / V1.5.0)
- [x] **B1 Ã  B6 :** Mappage et verrouillage des Genres, Tags, titres localisÃ©s, et staff Ã©tendu dans Kavita.
- [x] **B7 Ã  B9 :** Statut "IgnorÃ©", Polling d'Auto-Sync, routage de repli intelligent, et fusion des donnÃ©es.
- [x] **B11. Authentification globale :** Verrouillage de l'interface par variable d'environnement `ADMIN_PASSWORD`.
- [x] **B14 Ã  B15 :** Modal visuelle de sÃ©lection des couvertures & API MangaBaka V2.
- [x] **B16. Nettoyeur Regex Ultime :** Centralisation de `clean_title()`.
- [x] **B17. Barre de recherche AJAX :** Filtrage instantanÃ© cÃ´tÃ© client sans rechargement de page.
- [x] **B18. MÃ©tadonnÃ©es Ã‰tendues :** Ã‰diteurs, classification d'Ã‚ge, et sens de lecture automatique.
- [x] **B19. Identifiants & Liens Web :** Remplissage des ID natifs et gÃ©nÃ©ration automatique de WebLinks cliquables.
- [x] **B20. Refonte de l'Architecture UI :** DÃ©placement de la configuration technique dans une modal dÃ©diÃ©e.
- [x] **B21. Recherche Manuelle de Couvertures :** Saisie libre d'un titre alternatif directement dans la modal.
- [x] **B22. Suivi de Traitement Live (Pulsation Violette) :** Coloration dynamique et dÃ©filement automatique vers la ligne active.
- [x] **B23. Recherche d'ID Rapide (Quick Lookup) :** Bouton loupe ouvrant une recherche prÃ©-remplie sur AniList.
- [x] **B24. Persistance de l'Espace de Travail :** Sauvegarde automatique des filtres dans le `localStorage`.

### ðŸ› ï¸ Archives : Fondations & SÃ©curitÃ© (V1.3+)
- [x] **A1 Ã  A6 :** IntÃ©gration de l'API, Live Logs, 100% AJAX, ponts de traductions globaux, UI adaptative.
- [x] **A7 Ã  A9 :** Cache SQLite auto-nettoyant, Ã©crans d'erreurs de connexion explicites, dÃ©ploiement sans configuration.
- [x] **A10. Serveur WSGI de Production :** Migration vers l'architecture asynchrone Eventlet + Gunicorn.
- [x] **A11. SÃ©curitÃ© Globale :** Proxy d'images anti-SSRF, authentification immunisÃ©e contre les attaques temporelles (`compare_digest`), cookies HttpOnly, masquage des clÃ©s API, webhooks sÃ©curisÃ©s par jeton.