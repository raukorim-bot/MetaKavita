# MetaKavita

MetaKavita is an automated metadata enricher and manager for [Kavita](https://kavitareader.com/). It automatically detects library types (Manga, Comic, Comic Flexible, Book), scrapes summaries, release years, publication status, genres, tags, staff members, publishers, age ratings, and reading directions from public sources, translates summaries with Azure Translator or DeepL, and pushes them directly into your Kavita instance. 

MetaKavita also features a **Plug & Play Community Scraper** architecture, allowing you to load custom Python scrapers on the fly without rebuilding the Docker image!

> **⭐ If MetaKavita saves you time, please give this repo a star!**  
> It helps other Kavita users discover the tool (and who knows — maybe one day it'll buy the dev a coffee or a beer 🍻).  
> *Si MetaKavita te fait gagner du temps, ajoute une étoile à ce dépôt !*  
> *Ça aide d'autres utilisateurs de Kavita à découvrir l'outil (et qui sait — peut-être qu'un jour ça paiera un café ou une bière au dev 🍻).*

---

## Sommaire / Table of Contents
1. [🇺🇸 English Documentation](#-english-documentation)
   * [User Interface & Ergonomics](#-user-interface--ergonomics-v161)
   * [Enriched Metadata Fields](#-enriched-metadata-fields)
   * [Custom Community Scrapers (Plug & Play)](#-custom-community-scrapers-plug--play)
   * [Quality, Reliability & Benchmarking](#-quality-reliability--engine-benchmarking)
   * [Be Kind to Metadata Providers](#-be-kind-to-metadata-providers)
   * [Installation (Zero-Effort & Source)](#-installation)
   * [Configuration Variables](#-configuration-variables)
   * [Translation APIs & Quotas](#-translation-apis--quotas)
   * [Reverse Proxy & Subpath Hosting](#-reverse-proxy--subpath-hosting)
   * [Auto-Sync & Webhooks](#-auto-sync--webhooks)
   * [Security Disclaimer & Best Practices](#-security-disclaimer--deployment-best-practices)
2. [🇫🇷 Documentation Française](#-documentation-française)
   * [Interface Utilisateur & Ergonomie](#-interface-utilisateur--ergonomie-v161)
   * [Métadonnées Enrichies](#-métadonnées-enrichies)
   * [Scrapers Communautaires Personnalisés](#-scrapers-communautaires-personnalisés-plug--play)
   * [Assurance Qualité & Benchmarks Moteur](#-assurance-qualité--benchmarks-moteur)
   * [Soyez gentils avec les providers](#-soyez-gentils-avec-les-providers)
   * [Installation (Zéro-Effort & Sources)](#-installation-1)
   * [Variables de Configuration](#-variables-de-configuration)
   * [APIs de Traduction & Quotas](#-apis-de-traduction--quotas)
   * [Reverse Proxy & Hébergement en Sous-dossier](#-reverse-proxy--hébergement-en-sous-dossier)
   * [Auto-Sync & Webhooks](#-auto-sync--webhooks-1)
   * [Avertissement de Sécurité & Bonnes Pratiques](#-avertissement-de-sécurité--bonnes-pratiques)
3. [🙌 Contributors / Contributeurs](#-contributors--contributeurs)
4. [⚠️ Notes, Tech Stack & Full Documentation](#-notes-tech-stack--full-documentation)

---

## 🇺🇸 English Documentation

### 🎨 User Interface & Ergonomics (V1.6.1)

MetaKavita has been completely redesigned and heavily refined to separate background configuration from daily operational strategy, offering a zero-reload AJAX experience.

#### 1. Main Dashboard & Workspace Persistence
The interface uses a 100% AJAX layout with zero page reloads. The left sidebar handles active strategic options, while the main panel presents your library. Thanks to local storage persistence, the dashboard automatically remembers your selected library, status filter, hide ignored state, and search query between sessions. **Batch checkboxes** are also remembered per library (`mk_batch_selection:*`) so you can resume after a refresh or network drop.

#### 2. Clean, Dual-Form Architecture (Modal + Sidebar)
Technical infrastructure fields are isolated inside the **Global Configuration Modal** (accessible via the ⚙️ Config button in the topbar), preserving your workspace from configuration clutter. API Keys for metadata providers are neatly grouped in a dedicated section directly under the Kavita connection settings.
The left sidebar contains the **Scraping Options** card (click the title to collapse/expand; open by default) with Smart Scoring, Smart Completion, **Reliability barometer** (optional match threshold `0.30`–`1.00`), Auto-Covers, Auto-Reading Direction, Force Update, Context Reset, a collapsible **Targeted fields (batch)** mask for ephemeral write filters on the next batch, and the download button for your error reports.

#### 3. Unified Filtering & Central Toolbar
The Library Selector, Search bar, and Status Filter are consolidated into a single horizontal toolbar. This puts all target controls on one cohesive line.
To the right, the **Expand/Collapse All** (`📐`) button allows you to toggle open all individual overrides panels for fast mass editing, next to the **Save All Overrides** button.

#### 4. The "Magic Input", Deep Extraction & Advanced Overrides
Each series has an advanced Options panel and relies on a powerful underlying scraping engine:
*   **Deep Kavita Extraction**: Before querying the web, MetaKavita silently reads your existing Kavita metadata (like an embedded ISBN or an existing author). It uses this context in its unified scoring matrix to guarantee exact matches.
*   **Smart Scoring (v1.6+)**: Configured providers are scored against each other — the best match wins (ties keep your fallback order). Provider #1 runs first to seed ISBN/author context, then the others run in parallel. With Smart Completion enabled, missing fields are filled from highest score to lowest.
*   **The "Magic Input" (Smart URL/ID Routing)**: Paste a direct URL (e.g., `https://kitsu.io/manga/attack-on-titan` or a Manga-News link) or a raw ID into this field. MetaKavita will auto-detect the provider, bypass the standard search cascade, and scrape that exact page!
*   **Publisher Preference Toggle**: A dedicated segmented control allows you to force a specific publisher preference (`Auto` | `VF/VA` | `VO`) per series, overriding the global configuration.
*   **Granular Scraping (Targeted Fields)**: Click the "⚙️ Targeted Fields" details menu to individually uncheck specific metadata fields (Summary, Cover, Authors, Tags, Publisher, etc.) you don't want MetaKavita to overwrite. **Check all / Uncheck all** shortcuts are available here and on the sidebar batch mask.
*   **Context Reset on Force Update**: When forcing an update on a mismatched series, a sidebar toggle allows you to completely wipe the existing Kavita context (including the existing ISBN) to break negative feedback loops and start fresh.

#### 5. Live WebSocket Cover Streaming (*Progressive Loading*)
Manual cover searches stream image results live over WebSockets (`Socket.IO`) as each provider responds, rather than blocking until all scrapers finish. Selecting a cover manually automatically unchecks the global `AUTO_COVER` field for that series to permanently lock your choice and protect it against background sync overwrites.

#### 6. Live Processing Tracker, KPIs & WS Logs
During batch execution, the active series being processed pulses with a glowing purple outline (`.is-processing`) and automatically scrolls into view. A **batch progress bar** above the action buttons shows `done / total` (Socket.IO `batch_progress` from the worker queue). Badge statuses update dynamically on completion; successful series **auto-uncheck** so you can relaunch the remaining selection. The topbar shows live lifetime counters (enriched / matches / misses) plus a **session** counter (resets when the tab closes). The console displays real-time, sanitized, human-readable logs streamed via WebSockets.

#### 7. Playful Statistics (`/stats`)
Optional fun dashboard (enabled by default via `ENABLE_PLAYFUL_STATS`): Chart.js donuts/bars, lifetime hit-rate, and ~24 playful cards derived from lifetime enrichment counters (stable even if series leave Kavita).

---

### 📚 Enriched Metadata Fields

MetaKavita adapts its scraping strategy depending on Kavita's library types (`Manga`, `Comic`, `ComicFlexible`, `Book`) and maps the following metadata fields directly into Kavita's database structure:

| Category | Metadata Fields | Mapped Source Details |
| :--- | :--- | :--- |
| **Core Details** | Localized Name / Alternative Titles | Controlled by `LOCALIZED_TITLE_MODE` (default **all** = unique titles joined with `" / "`). Prefer/none + per-series lang override available; never rewrites Series `name`. |
| | Summary / Description | Scraped in source language, preserved as-is or translated via Azure, DeepL, or Google |
| | Release Year | Publication start year |
| | Publication Status | Maps to native codes: Ongoing, On Hiatus, Completed, Cancelled |
| | Language | Localized language translated target (e.g., `fr`, `en`) |
| **Collections & Lore** | Genres | From providers, capped by `MAX_GENRES` (default **5**, env/`config.json`) |
| | Tags | From providers, capped by `MAX_TAGS` (default **15**, env/`config.json`) |
| | Characters | Rich character lists populated in Kavita |
| **Staff & Editing** | Writers | Original Story authors & Scriptwriters |
| | Pencillers | Illustrators & Artists |
| | Colorists | Coloring staff |
| | Translators | Translation credits / Localization groups |
| | Cover Artists | Original cover artists |
| | Editors, Letterers, Inkers | Extended staff roles mapping |
| | Publisher | Official licensing publisher OR Original Publisher (based on user preference) |
| **Classifications** | Reading Direction (Format) | Automatically set to Left-to-Right, Right-to-Left, or Vertical |
| | Age Rating | Maps to native ratings: Safe, Suggestive, Erotica, Pornographic |
| **External IDs** | External Platform IDs | Saves `AniListId`, `MalId`, and `MangaBakaId` |
| | Web Links | Builds active clickable direct URLs to official series pages |

---

### 🔌 Custom Community Scrapers (Plug & Play)

MetaKavita V1.5.7 introduces an **Auto-Discovery Registry** for user-created scrapers.
You no longer need to modify the core code or rebuild the Docker image to add a new metadata source:

1. Drop any valid Python scraper file (e.g., `my_custom_site.py`) directly into your `data/scrapers/` folder.
2. Restart your MetaKavita container (`docker restart metakavita`).
3. The custom scraper will dynamically integrate into the UI dropdowns, automatically generate API key inputs in the Settings Modal if required, and benefit from the built-in SSRF Image Proxy protection!

To fully join **Smart Scoring**, set `uses_unified_scoring = True` and return candidates via `attach_match_score(...)` (see `CUSTOM_SCRAPERS.md` §4). Scrapers that skip this remain usable: they get a neutral score and cannot crash the enrichment pipeline.

> 💡 **Developers**: Please read the `CUSTOM_SCRAPERS.md` file for strict integration contracts and AI Prompts ("Vibecoding") to generate custom scrapers effortlessly.

---

### 🧪 Quality, Reliability & Engine Benchmarking

*   **100% Core Scoring Matrix Accuracy**: Evaluated across 20 complex edge cases including Roman volume numerals (`Tome II` -> `Tome 2`), sub-volume subtitle matching, spin-off penalties (`-35%`), guidebook noise filtering (`-50%`), and strict Anti-Homonym Author mismatch protections.
*   **Smart Scoring Winner Selection (v1.6+)**: Providers compete by match score instead of list order; community scrapers opt in via `uses_unified_scoring` + `attach_match_score()`, with a hardened fallback so malformed scores never crash enrichment.
*   **Pure Base64 Payload Delivery**: Cover uploads use pure Base64 byte strings ensuring that Kavita's C# engine flawlessly writes and saves images permanently to the disk, completely eradicating the "Phantom Cover" syndrome.
*   **High-Speed Per-Provider Rate Limiter**: Uses dynamic timestamp tracking (`LAST_REQUEST_TIMES`) with a per-scraper lock. Idle APIs respond instantly; after provider #1 seeds context, remaining providers run in parallel for Smart Fusion without triggering HTTP 429 rate limits.
*   **Hardened Kavita API Compliance (v1.5.8+)**: All partial updates now perform a GET-merge-POST cycle before writing to Kavita, guaranteeing that untouched fields (like alternate titles) are never silently nulled out or unlocked by the server. This also resolved a real-world crash in third-party OPDS clients (e.g. KOReader's Kamare plugin) that were choking on unexpected `null` values previously introduced by partial payloads.
*   **Configurable Tag & Genre Caps (v1.6+)**: `MAX_TAGS` (default 15) and `MAX_GENRES` (default 5) via env / `config.json` — applied in official scrapers and as a safety net in `enrichment_engine`. No UI (power-user).
*   **Application Audit Hardening (v1.6+)**: Cover/proxy SSRF allowlists (incl. private IPs + safe re-validated redirects), cover-modal XSS hardening, CSRF on mutating POSTs, forced-ID `fallback_query` retry, external-IDs GET-merge, Help/About with Kavita+ support links, and related Critical/High/Medium fixes (see `CHANGELOG.md` BF20–BF45 + C50–C53).
*   **Localized Titles Policy (v1.6+, issue #12)**: Config modal + env for `LOCALIZED_TITLE_MODE`/`LANGS`; per-series `alt_title_langs`; AniList/MangaDex/Kitsu structured `titles[]`. Controls Kavita `localizedName` only — never rewrites `name`.
*   **Comic Flexible (v1.6.1, C35)**: Kavita library type ID 5 uses Comic providers first, then Manga providers if no useful hit; cover search unions both families.
*   **MyAnimeList official API (v1.6.1):** Provider `MAL` via API v2 + Client ID (`MAL_API_KEY` → `X-MAL-CLIENT-ID`). Replaces Jikan. Manga + light novels (Book).
*   **BDTheque.com (v1.6.1):** Provider `BDTHEQUE` for https://www.bdtheque.com/ Franco-Belgian comics (distinct from Bédéthèque / `BEDETHEQUE`).
*   **Kavita library sync filter (v1.6.1):** Config → Planning checkboxes; `DISABLED_LIBRARIES` denylist (empty = all on).
*   **Wikidata (v1.6.1):** Optional `WIKIDATA` provider (Manga/Comic/Book) with live SPARQL/Entity API. Prefer as fallback / ISBN / cross-IDs.
*   **Playful Stats & Batch QoS (v1.6.1, C7+)**: Lifetime counters + live topbar KPIs; ephemeral batch field mask; selection persist / auto-uncheck; batch progress bar; collapsible Scraping Options.
*   **Reliability barometer (v1.6.1)**: Optional sidebar slider for match accept threshold (`MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD`); default remains `0.60` via `get_match_accept_threshold()`.

---

### 🙏 Be Kind to Metadata Providers

MetaKavita talks to **third-party APIs and websites** (AniList, MangaDex, MangaBaka, ComicVine, and many others). Those services are run by people and communities — often for free. Please use them responsibly:

1. **Let MetaKavita pace itself.** Built-in per-provider rate limiting spaces requests correctly. Do not try to “speed things up” by running several MetaKavita instances against the same providers, hammering Sync on the same series, or stacking overlapping giant batches.
2. **Expect ~8 seconds per series with everything on.** With Smart Scoring, Smart Completion, title fallback, auto-cover, and a full provider cascade, a realistic wall-clock benchmark is around **~8 s/series**. That can feel slow — it isn’t: each series triggers many remote calls (search + details + Kavita writes), spaced so providers stay happy. **Want it faster?** Configure only **one** provider (and turn off options you don’t need). Quality vs speed is a dial you control.
3. **Avoid pointless load.** Prefer a single planned enrich pass over endless re-syncs of already-completed series. Keep Smart Completion / Smart Scoring / title fallback on when you need them — but remember each option can mean **more** provider calls per series.
4. **Large libraries → overnight.** For a first full library fill or a huge force-batch (hundreds/thousands of series), start it in the evening and let it run quietly overnight. You’ll wake up to a filled library, and providers won’t take a daytime spike of traffic.
5. **Daily ops stay light.** After the initial fill, prefer Auto-Sync / webhooks for new series instead of re-processing the whole collection every week.

> Being a good neighbor keeps these APIs usable for everyone — including your future self.

---

### 🚀 Installation

> ⚠️ **Security Note**: MetaKavita is designed primarily as an internal management tool (LAN / VPN). Before exposing it publicly to the web, please read the [Security Disclaimer & Best Practices](#-security-disclaimer--deployment-best-practices).

#### Option A: Pull pre-built image (Zero-Effort - Recommended)
No cloning required. Create a `docker-compose.yml` file anywhere on your server with the following content:

```yaml
services:
  metakavita:
    image: ghcr.io/raukorim-bot/metakavita:latest
    container_name: metakavita
    restart: unless-stopped
    ports:
      - "5010:5010"
    environment:
      # First run opens a setup screen where you create your account.
      # To skip it (pre-provisioned deploys), generate a hash with
      # `python debug/hash_password.py` and set:
      # - ADMIN_USERNAME=admin
      # - ADMIN_PASSWORD_HASH=pbkdf2:sha256:...
      # - TRUSTED_PROXY_COUNT=0   # set to 0 if NOT behind a reverse proxy
      # - PUID=1000    # Host user id that should own ./data (run `id -u`)
      # - PGID=1000    # Host group id that should own ./data (run `id -g`)
      # - ROOT_PATH=/metakavita # Optional subpath for reverse proxies
      # - CORS_ALLOWED_ORIGINS=https://metakavita.home.local.ltd # Explicit HTTPS origins for Socket.IO / AJAX
      # - MAX_TAGS=15    # Power-user: max tags written to Kavita (1–100)
      # - MAX_GENRES=5   # Power-user: max genres written to Kavita (1–50)
      # - SESSION_COOKIE_SECURE=1  # Optional: set behind HTTPS reverse proxy
    volumes:
      - ./data:/app/data
```
Run `docker compose up -d` to launch the dashboard instantly on `http://localhost:5010`.

#### Option B: Build from Source
If you want to modify the code or run a custom build:
```bash
git clone https://github.com/raukorim-bot/MetaKavita.git
cd MetaKavita
docker compose up -d --build
```

---

### ⚙️ Configuration Variables

*MetaKavita features a Zero-Hardcode API Key engine. Any scraper declaring `needs_api_key = True` will automatically listen to its corresponding environment variable and dynamically render its input field in the UI.*

| Variable | Description | Default Value |
| :--- | :--- | :--- |
| `ADMIN_USERNAME` | Username for the account seeded from `ADMIN_PASSWORD_HASH`. Ignored if an account already exists. | `admin` |
| `ADMIN_PASSWORD_HASH` | Pre-hashed password used to create the first account at startup, skipping the setup screen. Generate with `python debug/hash_password.py`. Ignored once any account exists, so it can never overwrite a real password. | *(Empty)* |
| `TRUSTED_PROXY_COUNT` | `1` (default) trusts `X-Forwarded-*` from one reverse proxy. **Set to `0` when MetaKavita is reachable directly**, otherwise the header is attacker-controlled and the login lockout can be bypassed by rotating it. | `1` |
| ~~`ADMIN_PASSWORD`~~ | **Removed.** Replaced by the first-run account setup. Any value left in `config.json` is deleted once you create your account. | — |
| `PUID` / `PGID` | User and group id the application runs as, and which owns everything under `/app/data`. Set these to the owner of your bind-mounted `./data` folder (`id -u` / `id -g`) if it is not `1000:1000`. The container starts as root only long enough to apply them, then drops privileges. | `1000` / `1000` |
| `ROOT_PATH` | Custom URL subpath when hosted behind a reverse proxy (e.g. `/metakavita`). | *(Empty)* |
| `CORS_ALLOWED_ORIGINS` | Comma-separated explicit origins allowed for CORS (HTTP + Socket.IO), e.g. `https://metakavita.home.local.ltd`. Empty = Same-Origin only. `*` is rejected. Does not replace proper reverse-proxy WebSocket upgrade config. | *(Empty)* |
| `KAVITA_URL` | Kavita URL used by MetaKavita for API calls (can be an internal Docker hostname, e.g. `http://kavita:5000`). | *(Empty)* |
| `KAVITA_EXTERNAL_URL` | Optional public Kavita URL for browser UI links (e.g. `https://kavita.domain.tld`). If empty, falls back to `KAVITA_URL`. | *(Empty)* |
| `KAVITA_HTTP_TIMEOUT` | HTTP timeout in seconds for Kavita **write** requests (metadata / series update / cover upload). Raise to `90`–`120` on slow disks or large force-update batches. | `60` |
| `MAX_TAGS` | Max number of tags written to Kavita (scrapers + `enrichment_engine` safety net). Env / `config.json` only — no UI. Clamped 1–100. | `15` |
| `MAX_GENRES` | Max number of genres written to Kavita (scrapers + `enrichment_engine` safety net). Env / `config.json` only — no UI. Clamped 1–50. | `5` |
| `KAVITA_API_KEY` | Your Kavita API Key. | *(Empty)* |
| `TRANSLATION_PROVIDER` | Active translation engine (`GOOGLE`, `DEEPL`, `AZURE`, or `NONE` to disable). | `GOOGLE` |
| `AZURE_API_KEY` | Microsoft Azure Translator API Key (Primary Translation Engine). | *(Empty)* |
| `AZURE_REGION` | Microsoft Azure Translator API Region (e.g. `francecentral`). | *(Empty)* |
| `DEEPL_API_KEY` | Your DeepL Translation API Key (Fallback Translation Engine). | *(Empty)* |
| `TARGET_LANG` | Output language for summaries (`FR`, `EN`, `ES`...). Also dynamically changes Google Books search language! | `FR` |
| `UI_LANG` | Dashboard interface language (`fr` or `en`). | `fr` |
| `PUBLISHER_PREFERENCE` | Prefer Translated/Localized Publishers (`LOCALIZED`) or Japanese/Original (`ORIGINAL`). | `LOCALIZED` |
| `LOCALIZED_TITLE_MODE` | How to build Kavita `localizedName`: `all` (join unique titles with `" / "`), `prefer` (filter/order by `LOCALIZED_TITLE_LANGS`), `none` (do not write). Never rewrites Series `name`. Also in Config modal. | `all` |
| `LOCALIZED_TITLE_LANGS` | Comma-separated BCP-47-ish tags when mode is `prefer` (e.g. `en, ja-ro, ja`). Order = priority. Per-series override via `alt_title_langs`. | *(Empty)* |
| `PROVIDER_1` | Primary manga metadata source (`MANGABAKA`, `KITSU`, `ANILIST`, `MAL`, `MANGADEX`, `MANGAUPDATES`, `MANGANEWS`, `SHIKIMORI`, `WIKIDATA`). | `MANGABAKA` |
| `MAL_API_KEY` | MyAnimeList **Client ID** (not a secret token) from https://myanimelist.net/apiconfig — sent as `X-MAL-CLIENT-ID`. | _(empty)_ |
| `PROVIDER_2` | Fallback manga source 1. | `KITSU` |
| `PROVIDER_3` | Fallback manga source 2. | `ANILIST` |
| `COMIC_PROVIDER_1`| Primary comic metadata source (`BEDETHEQUE`, `BDTHEQUE`, `COMICVINE`, `GOOGLEBOOKS`, `OPENLIBRARY`, `HARDCOVER`, `ANILIST`, `WIKIDATA`). | `COMICVINE` |
| `COMIC_PROVIDER_2`| Fallback comic source 1. | `ANILIST` |
| `COMIC_PROVIDER_3`| Fallback comic source 2. | `NONE` |
| `BOOK_PROVIDER_1` | Primary book metadata source (`GOOGLEBOOKS`, `OPENLIBRARY`, `HARDCOVER`, `ANILIST`, `MANGABAKA`, `MAL`, `WIKIDATA`). | `GOOGLEBOOKS` |
| `BOOK_PROVIDER_2` | Fallback book source 1. | `OPENLIBRARY` |
| `BOOK_PROVIDER_3` | Fallback book source 2. | `NONE` |
| `SMART_SCORING`   | Enable Smart Scoring — best match wins (`true` or `false`). Off = classic list-order fallback. | `true` |
| `MATCH_THRESHOLD_CUSTOM` | Unlock custom match accept threshold (Reliability barometer). Off = always `0.60`. | `false` |
| `MATCH_ACCEPT_THRESHOLD` | Accept threshold when custom is on (`0.30`–`1.00`). Ignored when custom is off. | `0.60` |
| `ENABLE_PLAYFUL_STATS` | Show playful `/stats` dashboard (Chart.js + fun cards). | `true` |
| `SMART_COMPLETION`| Enable Data Fusion / Smart Patching (`true` or `false`). | `false` |
| `TITLE_FALLBACK_TRANSLATION`| Experimental: Translates unfound titles to English to force a 2nd search pass. | `false` |
| `AUTO_SYNC_INTERVAL`| Background polling interval in minutes (`0` to disable). | `0` |
| `DISABLED_LIBRARIES` | Comma-separated Kavita library IDs to exclude from sync/UI (denylist). Empty = all enabled. | _(empty)_ |
| `AUTO_COVER` | Automatically upload new covers to Kavita (`true` or `false`). | `false` |
| `AUTO_READING_DIR` | Auto-detect and set Manga/Webtoon reading direction. | `false` |

---

### 🌍 Translation APIs & Quotas

If you want to keep scraped descriptions in their original language without modification, select **Disabled (Keep original)** (`NONE`) as your Translation Provider.

If translation is enabled, keep in mind that the **DeepL Free API** is strictly limited to a **lifetime total of 1,000,000 characters**. MetaKavita integrates **Google Translate** out of the box for a free, zero-config experience. For maximum stability, we recommend setting up **Microsoft Azure Translator** (Free Tier F0 with **2,000,000 characters per month**) as your primary engine, with DeepL or Google as fallbacks.

---

### 🌐 Reverse Proxy & Subpath Hosting

MetaKavita supports subpath hosting (e.g., `https://your-domain.com/metakavita`) natively.

1. Set `ROOT_PATH=/metakavita` in your container environment variables.
2. In your reverse proxy (e.g., Nginx Proxy Manager or Traefik), route requests for `/metakavita` to the container port (`5010`).
3. Ensure WebSockets upgrade headers are passed (`Upgrade $http_upgrade` and `Connection "upgrade"`).

Client AJAX routes and Socket.IO connection paths will automatically adapt to the configured subpath while enforcing Same-Origin security.

> 💡 **Dual-Access Compatibility**: Enabling `ROOT_PATH` does not break direct access. MetaKavita remains accessible both through your reverse proxy subpath (`https://your-domain.com/metakavita`) and via direct local IP (`http://192.168.x.x:5010/`).

---

### 🤖 Auto-Sync & Webhooks

#### 1. Background Polling (Auto-Sync - Recommended)
Since Kavita does not natively provide outgoing Webhooks for library updates, MetaKavita uses background polling. Setting `AUTO_SYNC_INTERVAL` to a value higher than `0` (e.g., `30` minutes) schedules an automated task that periodically queries Kavita to fetch and process new or pending series.

#### 2. Webhook Endpoint for Custom Scripts & External Pipelines
For advanced workflows (e.g., n8n, Node-RED, or custom download post-processing scripts), MetaKavita exposes a dedicated endpoint to trigger instant processing for a specific series:
`POST http://<your-metakavita-ip>:5010/webhook`

The token can be sent two ways. **Prefer the header** — a token in the query string gets written to reverse-proxy access logs, browser history and `Referer` headers, none of which are places a secret should live:

```
X-Webhook-Token: <YOUR_WEBHOOK_TOKEN>
```

The historical query form still works and is not deprecated, so existing integrations keep running untouched:

`POST http://<your-metakavita-ip>:5010/webhook?token=<YOUR_WEBHOOK_TOKEN>`

If both are supplied, the header wins.

You can view your ready-to-use Webhook URL or generate a new token anytime directly inside the **Config Modal** (under the Planning section).

**Payload Example:**
```json
{
  "seriesId": 6827,
  "name": "Chiisakobe",
  "force": true
}
```
*(Setting `"force": true` in the JSON or adding `&force=true` to the URL triggers a forced re-scrape, overwriting existing metadata even if already marked as completed).*

#### 3. Health Endpoint

`GET /healthz` → `{"status": "ok", "version": "1.6.1"}`

A liveness probe for orchestrators — it is what the Docker `HEALTHCHECK` targets, and it works with Kubernetes, Portainer, Uptime Kuma and the like. Unauthenticated by design, so it keeps answering once a password is set. It touches no configuration, no database and never contacts Kavita: it reports only that the application is running and routing, not that its dependencies are up. That is deliberate — a Kavita outage should not make a healthy MetaKavita container restart in a loop.

---

### 🛡️ Security Disclaimer & Deployment Best Practices

#### 🏠 Primary Intended Use: Internal Backoffice
MetaKavita is designed primarily as an **internal management tool (backoffice)** intended to run within a local network (LAN) or a private network environment (such as WireGuard or Tailscale).

#### 🔒 Security Measures Included
Although designed for internal management, several security hardening controls are built into the application to mitigate common risks:
* **Authentication**: Password locking with timing-attack prevention (`secrets.compare_digest`) and artificial anti-brute-force delays.
* **CSRF Protection (v1.6+)**: Session CSRF token validated on state-changing POSTs (`X-CSRF-Token` / form field); frontend injects the header on mutating `fetch` calls. Webhook remains token-auth exempt.
* **Session Security**: Hardened `HttpOnly` and `SameSite=Lax` session cookies (optional `SESSION_COOKIE_SECURE=1` behind HTTPS). `SECRET_KEY` is generated on first boot — never a public hardcoded fallback.
* **SSRF Hardening (v1.6+)**: Shared URL allowlist for cover downloads and `/api/proxy-image` (http(s) only, no credentials/localhost/private IPs; up to 3 redirects with each hop re-validated; safe `image/*` MIME).
* **Cover UI XSS Hardening (v1.6+)**: Cover results built with DOM APIs (`textContent`) — no remote HTML interpolation.
* **Token Protection**: Webhooks require a cryptographically generated authorization token (`WEBHOOK_TOKEN`) with on-demand UI token rotation.
* **Credential Masking**: API keys are censored in the HTML DOM; Kavita auth logs never print API key prefixes.

> #### 🚨 Custom scrapers execute arbitrary code
> A `.py` file placed in `data/scrapers/` is **not configuration** — it is imported and run at
> startup with the application's full privileges. There is no sandbox. A malicious scraper can
> read `config.json` (and with it your `SECRET_KEY`, `WEBHOOK_TOKEN` and every API key), reach
> any file the container can, and open outbound network connections. Only install scrapers whose
> origin you trust, and read them first — including AI-generated ones.
> **See the full warning in [CUSTOM_SCRAPERS.md](CUSTOM_SCRAPERS.md).**

#### ⚠️ Important Notice for Public Web Exposure
The presence of built-in security features **does not guarantee absolute immunity against external threats**. Exposing MetaKavita directly to the open internet is done at your own risk.

**Recommended Security Layers for Public Exposure:**
1. **Reverse Proxy & HTTPS**: Always host MetaKavita behind a Reverse Proxy (Nginx, Traefik, Caddy) enforcing valid HTTPS/TLS encryption.
2. **Secondary Authentication Layer**: Combine the built-in login with an external authentication gateway (e.g., Authelia, Authentik, Cloudflare Access, or HTTP Basic Auth).
3. **Network Restrictions / VPN**: Restrict access to trusted IP ranges or keep access restricted to a private VPN whenever possible.
4. **Strong Passwords**: Choose a long, complex password on the first-run setup screen. Authentication is always enforced — there is no configuration in which the dashboard is served without a login.
5. **Set `TRUSTED_PROXY_COUNT=0` if you are not behind a reverse proxy**, so the brute-force lockout counts the real client address instead of a header the client controls.

> **Disclaimer**: MetaKavita is provided "as-is" without warranty of any kind. The maintainers assume no liability for data loss, unauthorized access, or security incidents resulting from public exposure or network misconfiguration.

<br><br>

---

## 🇫🇷 Documentation Française

### 🎨 Interface Utilisateur & Ergonomie (V1.6.1)

MetaKavita a été entièrement repensé et peaufiné pour séparer la configuration technique de la stratégie de scraping opérationnelle, tout en offrant une navigation fluide sans rechargements de page (AJAX).

#### 1. Tableau de Bord & Persistance de l'Espace de Travail
L'interface utilise une structure 100% AJAX. La barre latérale gauche gère la stratégie active tandis que le panneau central affiche tes œuvres. Grâce au stockage local (`localStorage`), le tableau de bord se souvient automatiquement de tes filtres (bibliothèque sélectionnée, tri de statut, barre de recherche et masquage des ignorés) d'une session à l'autre. Les **cases du batch** sont aussi mémorisées par bibliothèque (`mk_batch_selection:*`) pour reprendre après un refresh ou une coupure réseau.

![Tableau de bord MetaKavita](./assets/dashboard.png)

#### 2. Architecture Double-Formulaire (Modal + Sidebar)
Les champs d'infrastructure technique sont isolés dans la **Configuration Globale** (accessible via le bouton ⚙️ Config dans la barre supérieure), protégeant ton espace de travail de l'encombrement. Les clés d'API des fournisseurs sont proprement regroupées dans un bloc dédié sous la connexion Kavita.
La barre latérale contient la carte **Options de Scraping** (clic sur le titre pour plier/déplier ; ouverte par défaut) avec Smart Scoring, Complétion intelligente, **Baromètre de fiabilité** (seuil de match optionnel `0.30`–`1.00`), Auto-Covers, Sens de lecture auto, Mise à jour forcée, Purge du contexte, un sous-menu pliable **Champs ciblés (batch)** pour un masque d’écriture éphémère sur le prochain lot, et l'export des erreurs.

#### 3. Filtrage Unifié & Toolbar Centrale
Le sélecteur de bibliothèque, la barre de recherche et le filtre de statut sont regroupés dans une seule barre d'outils centrale. Toutes les commandes de ciblage se situent ainsi sur une même ligne horizontale cohérente.
À droite, le bouton **Déplier/Replier tout** (`📐`) permet de basculer l'affichage de tous les panneaux individuels pour des corrections rapides, aux côtés du bouton de sauvegarde globale.

#### 4. Le "Champ Magique", Extraction Profonde & Forçages Avancés
Chaque série dispose d'un volet d'options avancées reposant sur un puissant moteur de scraping :
*   **Extraction Profonde Kavita** : Avant d'interroger le web, MetaKavita lit silencieusement vos métadonnées Kavita actuelles (ISBN, auteurs existants). Il utilise ce contexte dans sa matrice d'évaluation mathématique pour garantir des correspondances parfaites et éliminer les faux positifs.
*   **Smart Scoring (v1.6+)** : les fournisseurs configurés sont comparés entre eux — le meilleur match gagne (égalité → ordre de fallback). Le provider #1 tourne d'abord pour amorcer le contexte ISBN/auteurs, puis les autres en parallèle. Avec la Complétion intelligente, les champs manquants sont comblés du score le plus haut au plus bas.
*   **Le "Champ Magique" (Routage URL & ID)** : Collez une URL directe (ex: `https://mangabaka.org/1234` ou une fiche Manga-News), un slug ou un ID pur dans ce champ. MetaKavita détectera automatiquement le site, contournera la cascade habituelle, et ciblera cette page exacte !
*   **Préférence d'Éditeur (VF/VA vs VO)** : Un interrupteur (pilule) permet d'imposer individuellement à une série la recherche de son éditeur localisé/traduit ou d'origine (Japonais).
*   **Scraping Granulaire (Champs Ciblés)** : Cliquez sur le menu "⚙️ Champs Ciblés" pour décocher individuellement n'importe quelle métadonnée (Résumé, Couvertures, Auteurs, Éditeur, etc.) que vous souhaitez figer. Raccourcis **Tout cocher / Tout décocher** ici et sur le masque batch de la sidebar.
*   **Purge absolue du Contexte (Force Update)** : Lors d'une mise à jour forcée, l'option "Effacer le contexte" permet de purger totalement l'ISBN et les auteurs existants de Kavita pour briser les boucles de faux-positifs et repartir d'une page blanche.

#### 5. Streaming de Couvertures en Temps Réel (*Progressive Loading*)
La recherche manuelle d'images envoie les cartes de couvertures en direct au fil de l'eau via WebSockets (`Socket.IO`) dès qu'un provider répond. 
> 🔒 **Verrouillage Anti-Écrasement :** Appliquer une couverture manuelle depuis cette fenêtre décoche automatiquement l'option "Couverture" de l'œuvre. Cela fige votre choix définitivement et empêche l'Auto-Sync de l'écraser plus tard.

#### 6. Suivi Live, KPI & Logs WebSockets
Pendant l'exécution d'un lot, la série en cours de traitement clignote avec une pulsation violette (`.is-processing`) et défile automatiquement à l'écran. Une **barre de progression batch** au-dessus des boutons affiche `fait / total` (Socket.IO `batch_progress` depuis la file worker). Les badges se mettent à jour dynamiquement ; une série OK se **décoche** pour pouvoir relancer le reste. La topbar affiche les compteurs lifetime (enrichies / matchs / ratés) plus un compteur **session** (remis à 0 à la fermeture de l’onglet). La console affiche en temps réel des logs épurés via WebSockets.

#### 7. Statistiques ludiques (`/stats`)
Tableau de bord optionnel (activé par défaut via `ENABLE_PLAYFUL_STATS`) : donuts/barres Chart.js, taux de hit lifetime, et ~24 cartes fun basées sur les compteurs d’enrichissement lifetime (stables même si des séries quittent Kavita).

---

### 📚 Métadonnées Enrichies

MetaKavita traite et verrouille automatiquement les champs de métadonnées suivants directement dans la structure de données de Kavita selon le type de bibliothèque (`Manga`, `Comic`, `ComicFlexible`, `Book`) :

| Catégorie | Métadonnée Kavita | Détails de la source mappée |
| :--- | :--- | :--- |
| **Identité** | Titre Localisé / Alternatif | Contrôlé par `LOCALIZED_TITLE_MODE` (défaut **all** = titres uniques joints par `" / "`). Modes prefer/none + override langues par série ; ne réécrit jamais Series `name`. |
| | Résumé / Description | Récupère le résumé d'origine et le conserve tel quel ou le traduit via Azure, DeepL ou Google |
| | Année de sortie | Année de début de publication |
| | Statut de publication | Mappe vers les statuts natifs : En cours, En pause, Terminé, Abandonné |
| | Langue (Language) | Calquée automatiquement sur votre langue cible (ex: `fr`, `en`) |
| **Thématiques** | Genres | Depuis les providers, plafonnés par `MAX_GENRES` (défaut **5**, env/`config.json`) |
| | Thèmes (Tags) | Depuis les providers, plafonnés par `MAX_TAGS` (défaut **15**, env/`config.json`) |
| | Personnages | Liste enrichie des personnages secondaires |
| **Staff & Édition** | Scénaristes (Writers) | Auteur de l'œuvre d'origine / Scénaristes |
| | Dessinateurs (Pencillers) | Illustrateurs et artistes principaux |
| | Coloristes | Équipe de colorisation |
| | Traducteurs | Groupes de scantrad / Traducteurs officiels |
| | Dessinateurs de couverture | Artistes des couvertures originales |
| | Éditeurs, Encreurs, Lettreurs | Rôles avancés extraits selon disponibilité des sources |
| | Éditeur (Publisher) | Maison d'édition licenciée VF/VA OU Maison d'origine japonaise (selon le choix utilisateur) |
| **Classifications** | Sens de lecture (Format) | Configuré automatiquement en Gauche-à-Droite, Droite-à-Gauche ou Vertical |
| | Classification d'Âge | Mappage natif : Sûr (Safe), Suggestif, Érotique, Pornographique |
| **ID & Liens** | Identifiants Plateformes | Renseigne directement `AniListId`, `MalId` et `MangaBakaId` |
| | Liens Web (WebLinks) | Génère des URL directes pour afficher les icônes cliquables dans Kavita |

---

### 🔌 Scrapers Communautaires Personnalisés (Plug & Play)

MetaKavita V1.5.7 inaugure un système d'**Auto-Découverte** pour vos propres fournisseurs de données (Scrapers).
Il n'est plus nécessaire de modifier le code source ou de recompiler l'image Docker pour ajouter un nouveau site !

1. Glissez n'importe quel fichier de scraper Python valide (ex: `mon_site_perso.py`) directement dans votre dossier `data/scrapers/`.
2. Redémarrez votre conteneur MetaKavita (`docker restart metakavita`).
3. Votre scraper personnalisé sera automatiquement détecté, s'ajoutera à l'interface graphique, générera ses champs de clé API dans la configuration, et bénéficiera de la protection SSRF du Proxy d'images natif !

Pour participer pleinement au **Smart Scoring**, déclarez `uses_unified_scoring = True` et retournez vos candidats via `attach_match_score(...)` (voir `CUSTOM_SCRAPERS.md` §4). Sans cela, le scraper reste utilisable : il reçoit un score neutre et ne peut pas faire planter le pipeline d'enrichissement.

> 💡 **Développeurs** : Veuillez lire le fichier `CUSTOM_SCRAPERS.md` à la racine du projet pour connaître le contrat technique et récupérer nos Prompts IA ("Vibecoding") pour générer vos scrapers en 5 minutes.

---

### 🧪 Assurance Qualité & Benchmarks Moteur

*   **Précision de Scoring de 100%** : Évaluée sur 20 cas limites complexes incluant les chiffres romains (`Tome II` -> `Tome 2`), les sous-titres d'albums, le filtrage anti-spin-off (`-35%`), l'exclusion des artbooks/guidebooks (`-50%`) et la purge d'ISBN pour contrer les faux-positifs.
*   **Sélection Smart Scoring (v1.6+)** : les fournisseurs sont départagés par score de match plutôt que par ordre de liste ; les scrapers communautaires optent via `uses_unified_scoring` + `attach_match_score()`, avec un filet de sécurité qui empêche tout score mal formé de faire planter l'enrichissement.
*   **Payload Base64 Pur** : Résolution définitive du "Syndrome de la couverture fantôme". Les requêtes n'utilisent plus le *Data URI* mais une chaîne Base64 pure afin que le moteur C# de Kavita écrive physiquement et de manière permanente les images sur le disque dur.
*   **Throttling Dynamique Haute Performance** : régulateur par horodatage (`LAST_REQUEST_TIMES`) avec verrou par scraper. Après l'amorçage du contexte par le provider #1, les autres tournent en parallèle pour la Smart Fusion sans déclencher de HTTP 429.
*   **Conformité Renforcée avec l'API Kavita (v1.5.8+)** : Chaque mise à jour partielle effectue désormais un cycle GET-fusion-POST avant l'écriture, garantissant que les champs non modifiés (ex: titres alternatifs) ne soient jamais silencieusement effacés ou déverrouillés par le serveur. Ce correctif a également résolu un plantage réel constaté sur des lecteurs OPDS tiers (ex: l'extension Kamare de KOReader), qui recevaient des valeurs `null` inattendues suite à d'anciens envois partiels.
*   **Plafonds Tags & Genres configurables (v1.6+)** : `MAX_TAGS` (défaut 15) et `MAX_GENRES` (défaut 5) via env / `config.json` — appliqués dans les scrapers officiels et en filet dans `enrichment_engine`. Pas d'UI (power-user).
*   **Durcissement suite audit applicatif (v1.6+)** : allowlists SSRF couverture/proxy (IPs privées + redirects re-validés), XSS modal couvertures, CSRF sur POST mutatifs, retry `fallback_query` après ID forcé, GET-merge des IDs externes, menu Aide / À propos avec liens Kavita+, et correctifs Critical/High/Medium associés (voir `CHANGELOG.md` BF20–BF45 + C50–C53).
*   **Politique des titres localisés (v1.6+, issue #12)** : modal Config + env `LOCALIZED_TITLE_MODE`/`LANGS` ; override `alt_title_langs` par série ; `titles[]` structurés AniList/MangaDex/Kitsu. Contrôle uniquement `localizedName` — jamais de réécriture de `name`.
*   **Comic Flexible (v1.6.1, C35)** : l’ID Kavita 5 utilise d’abord les providers Comic, puis Manga si aucun hit utile ; recherche de couvertures = union des deux familles.
*   **MyAnimeList API officielle (v1.6.1)** : provider `MAL` via API v2 + Client ID (`MAL_API_KEY` → `X-MAL-CLIENT-ID`). Remplace Jikan. Manga + light novels (Book).
*   **BDTheque.com (v1.6.1)** : provider `BDTHEQUE` pour les BD franco-belges sur https://www.bdtheque.com/ (distinct de Bédéthèque / `BEDETHEQUE`).
*   **Filtre bibliothèques Kavita (v1.6.1)** : cases à cocher Config → Planification ; dénylist `DISABLED_LIBRARIES` (vide = tout actif).
*   **Wikidata (v1.6.1)** : provider optionnel `WIKIDATA` (Manga/Comic/Book) en live SPARQL/Entity API. Idéal en fallback / ISBN / IDs croisés.
*   **Stats ludiques & QoS batch (v1.6.1, C7+)** : compteurs lifetime + KPI live topbar ; masque de champs batch éphémère ; persistance / décochage auto ; barre de progression batch ; Options de Scraping pliables.
*   **Baromètre de fiabilité (v1.6.1)** : curseur sidebar optionnel pour le seuil d’acceptation (`MATCH_THRESHOLD_CUSTOM` / `MATCH_ACCEPT_THRESHOLD`) ; défaut `0.60` via `get_match_accept_threshold()`.

---

### 🙏 Soyez gentils avec les providers

MetaKavita interroge des **API et sites tiers** (AniList, MangaDex, MangaBaka, ComicVine, et bien d’autres). Ces services sont maintenus par des équipes et des communautés — souvent gratuitement. Merci de les utiliser correctement :

1. **Laissez MetaKavita cadencer les requêtes.** Le rate-limiting intégré (par fournisseur) espace déjà les appels. N’essayez pas d’« accélérer » en lançant plusieurs instances MetaKavita sur les mêmes providers, en martelant Sync sur la même série, ou en empilant plusieurs gros batchs qui se chevauchent.
2. **Comptez ~8 secondes par série avec tout activé.** Avec Smart Scoring, Complétion intelligente, title fallback, auto-cover et une cascade complète de providers, un benchmark réaliste tourne autour de **~8 s/série**. Ça peut paraître long — ce n’est pas le cas : chaque série déclenche beaucoup d’appels distants (recherche + fiches + écritures Kavita), espacés pour ne pas malmener les providers. **Vous voulez aller plus vite ?** Ne configurez qu’**un seul** provider (et désactivez les options dont vous n’avez pas besoin). Qualité vs vitesse, c’est vous qui réglez le curseur.
3. **Évitez la charge inutile.** Préférez un passage d’enrichissement planifié à des re-syncs sans fin de séries déjà `COMPLETED`. Smart Completion / Smart Scoring / title fallback sont utiles — mais chaque option peut signifier **plus** d’appels providers par série.
4. **Grosse bibliothèque → la nuit.** Pour un premier remplissage complet ou un force-batch massif (des centaines / milliers de séries), lancez-le le soir et laissez-le tourner tranquillement pendant la nuit. Au réveil, la bibliothèque est remplie — sans pic de trafic diurne chez les providers.
5. **Le quotidien reste léger.** Après le premier remplissage, privilégiez Auto-Sync / webhooks pour les nouvelles séries plutôt que de retraiter toute la collection chaque semaine.

> Être un bon voisin, c’est garder ces API utilisables pour tout le monde — y compris pour vous demain.

---

### 🚀 Installation

> ⚠️ **Note de sécurité** : MetaKavita est conçu en priorité comme un outil de gestion interne (LAN / VPN). Avant toute exposition publique sur Internet, veuillez consulter la section [Avertissement de Sécurité & Bonnes Pratiques](#-avertissement-de-sécurité--bonnes-pratiques).

#### Option A : Télécharger l'image pré-compilée (Zéro effort - Recommandé)
Aucun clonage de dépôt n'est requis. Crée simplement un fichier `docker-compose.yml` sur ton serveur contenant ce bloc :

```yaml
services:
  metakavita:
    image: ghcr.io/raukorim-bot/metakavita:latest
    container_name: metakavita
    restart: unless-stopped
    ports:
      - "5010:5010"
    environment:
      # Au premier démarrage, un écran de configuration vous fait créer votre compte.
      # Pour l'ignorer (déploiements pré-provisionnés), générez un hachage avec
      # `python debug/hash_password.py` puis renseignez :
      # - ADMIN_USERNAME=admin
      # - ADMIN_PASSWORD_HASH=pbkdf2:sha256:...
      # - TRUSTED_PROXY_COUNT=0   # 0 si vous n'êtes PAS derrière un reverse proxy
      # - PUID=1000    # UID hôte qui doit posséder ./data (`id -u`)
      # - PGID=1000    # GID hôte qui doit posséder ./data (`id -g`)
      # - ROOT_PATH=/metakavita # Optionnel : pour hébergement en sous-dossier
      # - CORS_ALLOWED_ORIGINS=https://metakavita.home.local.ltd # Origins HTTPS explicites pour Socket.IO / AJAX
      # - MAX_TAGS=15    # Power-user : max tags écrits dans Kavita (1–100)
      # - MAX_GENRES=5   # Power-user : max genres écrits dans Kavita (1–50)
      # - SESSION_COOKIE_SECURE=1  # Optionnel : derrière un reverse proxy HTTPS
    volumes:
      - ./data:/app/data
```
Lance la commande `docker compose up -d` pour exécuter instantanément MetaKavita sur `http://localhost:5010`.

#### Option B : Compiler depuis les sources
Idéal si tu souhaites modifier le code ou exécuter une build personnalisée :
```bash
git clone https://github.com/raukorim-bot/MetaKavita.git
cd MetaKavita
docker compose up -d --build
```

---

### ⚙️ Variables de Configuration

*MetaKavita dispose d'un moteur de clés d'API dynamique (Zero-Hardcode). Tout scraper déclarant `needs_api_key = True` écoutera automatiquement sa variable d'environnement et affichera son champ de saisie dans l'UI.*

| Variable | Description | Valeur par défaut |
| :--- | :--- | :--- |
| `ADMIN_USERNAME` | Nom du compte amorcé depuis `ADMIN_PASSWORD_HASH`. Ignoré si un compte existe déjà. | `admin` |
| `ADMIN_PASSWORD_HASH` | Mot de passe pré-haché servant à créer le premier compte au démarrage, sans passer par l'écran de configuration. À générer avec `python debug/hash_password.py`. Ignoré dès qu'un compte existe : il ne peut donc jamais écraser un mot de passe réel. | *(Vide)* |
| `TRUSTED_PROXY_COUNT` | `1` (défaut) fait confiance aux en-têtes `X-Forwarded-*` d'un reverse proxy. **Mettre `0` si MetaKavita est joignable directement**, sinon l'en-tête est fourni par le client et le verrouillage de connexion peut être contourné en le faisant varier. | `1` |
| ~~`ADMIN_PASSWORD`~~ | **Supprimé.** Remplacé par la création de compte au premier démarrage. Toute valeur restée dans `config.json` est effacée dès que vous créez votre compte. | — |
| `PUID` / `PGID` | UID et GID sous lesquels tourne l'application, et propriétaires de tout le contenu de `/app/data`. À renseigner avec le propriétaire de votre dossier `./data` monté (`id -u` / `id -g`) s'il n'est pas `1000:1000`. Le conteneur ne démarre en root que le temps de les appliquer, puis abandonne ses privilèges. | `1000` / `1000` |
| `ROOT_PATH` | Sous-chemin d'URL lors de l'exposition derrière un reverse proxy (ex: `/metakavita`). | *(Vide)* |
| `CORS_ALLOWED_ORIGINS` | Origins CORS explicites séparées par des virgules (HTTP + Socket.IO), ex: `https://metakavita.home.local.ltd`. Vide = Same-Origin uniquement. `*` est rejeté. Ne remplace pas une config reverse-proxy correcte pour l'upgrade WebSocket. | *(Vide)* |
| `KAVITA_URL` | URL Kavita utilisée par MetaKavita pour les appels API (peut être un hostname Docker interne, ex: `http://kavita:5000`). | *(Vide)* |
| `KAVITA_EXTERNAL_URL` | URL publique optionnelle de Kavita pour les liens UI (ex: `https://kavita.domain.tld`). Si vide, repli sur `KAVITA_URL`. | *(Vide)* |
| `KAVITA_HTTP_TIMEOUT` | Timeout HTTP (secondes) pour les **écritures** Kavita (métadonnées / update série / couverture). Montez à `90`–`120` sur HDD ou gros force-update. | `60` |
| `MAX_TAGS` | Nombre max de tags écrits dans Kavita (scrapers + filet `enrichment_engine`). Env / `config.json` uniquement — pas d'UI. Borné 1–100. | `15` |
| `MAX_GENRES` | Nombre max de genres écrits dans Kavita (scrapers + filet `enrichment_engine`). Env / `config.json` uniquement — pas d'UI. Borné 1–50. | `5` |
| `KAVITA_API_KEY` | Ta clé API Kavita. | *(Vide)* |
| `TRANSLATION_PROVIDER` | Moteur de traduction actif (`GOOGLE`, `DEEPL`, `AZURE`, ou `NONE` pour désactiver). | `GOOGLE` |
| `AZURE_API_KEY` | Ta clé d'API Microsoft Azure Translator (Moteur principal). | *(Vide)* |
| `AZURE_REGION` | Ta région Azure Translator (ex: `francecentral`). | *(Vide)* |
| `DEEPL_API_KEY` | Ta clé API DeepL pour la traduction (Repli de secours). | *(Vide)* |
| `TARGET_LANG` | Langue cible des résumés (`FR`, `EN`...). Modifie dynamiquement la langue de recherche Google Books ! | `FR` |
| `UI_LANG` | Langue de l'interface MetaKavita (`fr` ou `en`). | `fr` |
| `PUBLISHER_PREFERENCE` | Préférer les Éditeurs Traduits/Licenciés (`LOCALIZED`) ou d'origine Japonaise (`ORIGINAL`). | `LOCALIZED` |
| `LOCALIZED_TITLE_MODE` | Construction de Kavita `localizedName` : `all` (joindre les titres uniques avec `" / "`), `prefer` (filtre/ordre via `LOCALIZED_TITLE_LANGS`), `none` (ne pas écrire). Ne réécrit jamais Series `name`. Aussi dans la modal Config. | `all` |
| `LOCALIZED_TITLE_LANGS` | Tags BCP-47-ish séparés par des virgules en mode `prefer` (ex. `en, ja-ro, ja`). Ordre = priorité. Override par série via `alt_title_langs`. | *(Vide)* |
| `PROVIDER_1` | Source de métadonnées principale Manga (`MANGABAKA`, `KITSU`, `ANILIST`, `MAL`, `MANGADEX`, `MANGAUPDATES`, `MANGANEWS`, `SHIKIMORI`, `WIKIDATA`). | `MANGABAKA` |
| `MAL_API_KEY` | **Client ID** MyAnimeList (pas un token secret) depuis https://myanimelist.net/apiconfig — envoyé en `X-MAL-CLIENT-ID`. | _(vide)_ |
| `PROVIDER_2` | Source de secours 1 Manga. | `KITSU` |
| `PROVIDER_3` | Source de secours 2 Manga. | `ANILIST` |
| `COMIC_PROVIDER_1`| Source de métadonnées principale Comic (`BEDETHEQUE`, `BDTHEQUE`, `COMICVINE`, `GOOGLEBOOKS`, `OPENLIBRARY`, `HARDCOVER`, `ANILIST`, `WIKIDATA`). | `COMICVINE` |
| `COMIC_PROVIDER_2`| Source de secours 1 Comic. | `ANILIST` |
| `COMIC_PROVIDER_3`| Source de secours 2 Comic. | `NONE` |
| `BOOK_PROVIDER_1` | Source de métadonnées principale Roman (`GOOGLEBOOKS`, `OPENLIBRARY`, `HARDCOVER`, `ANILIST`, `MANGABAKA`, `MAL`, `WIKIDATA`). | `GOOGLEBOOKS` |
| `BOOK_PROVIDER_2` | Source de secours 1 Roman. | `OPENLIBRARY` |
| `BOOK_PROVIDER_3` | Source de secours 2 Roman. | `NONE` |
| `SMART_SCORING`   | Activer le Smart Scoring — meilleur match (`true` ou `false`). Off = fallback classique par ordre de liste. | `true` |
| `MATCH_THRESHOLD_CUSTOM` | Déverrouiller le seuil de match personnalisé (Baromètre de fiabilité). Off = toujours `0.60`. | `false` |
| `MATCH_ACCEPT_THRESHOLD` | Seuil d'acceptation si custom ON (`0.30`–`1.00`). Ignoré si custom OFF. | `0.60` |
| `ENABLE_PLAYFUL_STATS` | Afficher le tableau `/stats` ludique (Chart.js + cartes fun). | `true` |
| `SMART_COMPLETION`| Activer la fusion des données (`true` ou `false`). | `false` |
| `TITLE_FALLBACK_TRANSLATION`| Expérimental : Traduit le titre non-trouvé en anglais pour relancer une seconde recherche. | `false` |
| `AUTO_SYNC_INTERVAL`| Intervalle d'Auto-Sync en minutes (`0` pour désactiver). | `0` |
| `DISABLED_LIBRARIES` | IDs de bibliothèques Kavita à exclure (dénylist, virgules). Vide = toutes actives. | _(vide)_ |
| `AUTO_COVER` | Envoyer automatiquement les couvertures à Kavita (`true` ou `false`). | `false` |
| `AUTO_READING_DIR` | Configurer automatiquement le sens de lecture. | `false` |

---

### 🌍 APIs de Traduction & Quotas

Si vous souhaitez conserver les résumés d'origine sans aucune modification ni traduction, choisissez **Désactivé (Conserver l'original)** (`NONE`) dans les paramètres de traduction.

Si la traduction est activée, gardez à l'esprit que l'**API gratuite de DeepL** est strictly limited à **1 000 000 de caractères à vie**. MetaKavita intègre nativement **Google Translate** pour une expérience 100% gratuite et sans configuration. Pour une stabilité maximale, nous vous recommandons de configurer **Microsoft Azure Translator** (généreux niveau gratuit F0 offrant **2 000 000 de caractères par mois**) en traducteur principal, et de garder DeepL ou Google en secours.

---

### 🌐 Reverse Proxy & Hébergement en Sous-dossier

MetaKavita prend en charge le déploiement sous un sous-chemin d'URL (ex: `https://ton-domaine.com/metakavita`).

1. Renseigne `ROOT_PATH=/metakavita` dans les variables d'environnement de ton conteneur.
2. Dans ton Reverse Proxy (Nginx Proxy Manager, Traefik, Caddy), redirige la location `/metakavita` vers le port du conteneur (`5010`).
3. Assure-toi de transmettre les en-têtes de mise à niveau WebSocket (`Upgrade $http_upgrade` et `Connection "upgrade"`).

Toutes les requêtes AJAX et la connexion WebSocket (`Socket.IO`) adapteront automatiquement leurs routes au sous-chemin défini tout en appliquant la sécurité Same-Origin.

> 💡 **Compatibilité d'accès double** : Activer `ROOT_PATH` ne bloque pas l'accès local. MetaKavita reste simultanément accessible via le sous-chemin de votre reverse proxy (`https://ton-domaine.com/metakavita`) et en direct via l'IP locale (`http://192.168.x.x:5010/`).

---

### 🤖 Auto-Sync & Webhooks

#### 1. Polling d'Arrière-Plan (Auto-Sync - Recommandé)
Comme Kavita ne propose pas nativement de Webhooks sortants lors des ajouts de bibliothèques, MetaKavita s'appuie sur le polling. Renseigner une valeur supérieure à `0` pour `AUTO_SYNC_INTERVAL` (ex: `30` minutes) lance une tâche d'arrière-plan qui interroge régulièrement l'API de Kavita pour enrichir automatiquement les nouvelles séries ou fiches en attente.

#### 2. Endpoint Webhook pour Scripts Tiers
Pour les besoins d'automatisation avancés (ex: workflows n8n, Node-RED, ou scripts de post-traitement post-téléchargement), MetaKavita expose un endpoint dédié permettant de forcer l'enrichissement immédiat d'une série spécifique :
`POST http://<ton-ip-metakavita>:5010/webhook`

Le jeton peut être transmis de deux façons. **Privilégiez l'en-tête** : un jeton placé dans la chaîne de requête se retrouve dans les logs d'accès des reverse proxies, l'historique du navigateur et les en-têtes `Referer` — autant d'endroits où un secret n'a pas sa place :

```
X-Webhook-Token: <TON_WEBHOOK_TOKEN>
```

La forme historique en paramètre d'URL reste fonctionnelle et n'est pas dépréciée : les intégrations existantes continuent de marcher sans modification.

`POST http://<ton-ip-metakavita>:5010/webhook?token=<TON_WEBHOOK_TOKEN>`

Si les deux sont fournis, l'en-tête est prioritaire.

Vous pouvez consulter votre URL Webhook prête à l'emploi ou régénérer un jeton à tout moment directement depuis la **Modal Config** (dans la section Planification).

**Exemple de payload :**
```json
{
  "seriesId": 6827,
  "name": "Chiisakobe",
  "force": true
}
```
*(Définir `"force": true` dans le JSON ou ajouter `&force=true` dans l'URL déclenche un ré-enrichissement forcé, écrasant les métadonnées existantes même si la fiche était marquée comme complétée).*

#### 3. Endpoint de santé

`GET /healthz` → `{"status": "ok", "version": "1.6.1"}`

Sonde de liveness pour les orchestrateurs — c'est la cible du `HEALTHCHECK` Docker, et elle fonctionne aussi avec Kubernetes, Portainer, Uptime Kuma, etc. Non authentifiée par conception, afin de continuer à répondre une fois un mot de passe défini. Elle ne lit aucune configuration, n'ouvre aucune base et ne contacte jamais Kavita : elle indique seulement que l'application tourne et route, pas que ses dépendances sont disponibles. C'est délibéré — une panne de Kavita ne doit pas faire redémarrer en boucle un conteneur MetaKavita parfaitement sain.

---

### 🛡️ Avertissement de Sécurité & Bonnes Pratiques

#### 🏠 Usage Principal : Outil de Backoffice Interne
MetaKavita est conçu en priorité comme un **outil de gestion interne (backoffice)** destiné à s'exécuter au sein d'un réseau local (LAN) ou d'un réseau privé (ex: WireGuard, Tailscale).

#### 🔒 Mesures de Sécurité Intégrées
Bien que pensé pour un usage privé, plusieurs mécanismes de protection sont intégrés à l'application pour limiter les risques :
* **Authentification** : Verrouillage par mot de passe protégé contre les attaques temporelles (`secrets.compare_digest`) et ralentissement anti-force brute.
* **Protection CSRF (v1.6+)** : jeton CSRF de session validé sur les POST mutatifs (`X-CSRF-Token` / champ form) ; le frontend injecte le header sur les `fetch` mutatifs. Le webhook reste exempt (auth par jeton).
* **Sécurité des Sessions** : Cookies `HttpOnly` + `SameSite=Lax` (`SESSION_COOKIE_SECURE=1` optionnel derrière HTTPS). `SECRET_KEY` générée au premier démarrage — jamais de fallback public hardcodé.
* **Durcissement SSRF (v1.6+)** : allowlist d'URL partagée pour téléchargement de couvertures et `/api/proxy-image` (http(s) uniquement, pas de credentials/localhost/IPs privées ; jusqu'à 3 redirects avec re-validation à chaque hop ; MIME `image/*`).
* **XSS modal couvertures (v1.6+)** : résultats construits via APIs DOM (`textContent`) — pas d'interpolation HTML distante.
* **Protection Webhook** : Authentification des appels webhook exigeant un jeton cryptographique (`WEBHOOK_TOKEN`) réinitialisable à la demande.
* **Masquage des Identifiants** : Censure des clés API dans l'interface web ; les logs d'auth Kavita n'affichent plus de préfixe de clé.

> #### 🚨 Les scrapers personnalisés exécutent du code arbitraire
> Un fichier `.py` déposé dans `data/scrapers/` **n'est pas de la configuration** : il est importé
> et exécuté au démarrage avec tous les droits de l'application. Il n'y a aucun bac à sable. Un
> scraper malveillant peut lire `config.json` (et donc votre `SECRET_KEY`, votre `WEBHOOK_TOKEN`
> et toutes vos clés d'API), accéder à n'importe quel fichier visible du conteneur et ouvrir des
> connexions réseau sortantes. N'installez que des scrapers dont vous connaissez la provenance,
> et lisez-les avant — y compris ceux générés par une IA.
> **Avertissement complet dans [CUSTOM_SCRAPERS.md](CUSTOM_SCRAPERS.md).**

#### ⚠️ Avertissement en Cas d'Exposition Publique
L'existence de ces protections **ne garantit pas une sécurité absolue**. Si vous choisissez d'exposer directement MetaKavita sur Internet, vous le faites sous votre propre responsabilité.

**Recommandations pour une exposition publique :**
1. **Reverse Proxy & HTTPS** : Hébergez systématiquement l'application derrière un Reverse Proxy (Nginx, Traefik, Caddy) configuré avec un certificat HTTPS/TLS valide.
2. **Authentification Renforcée** : Associez l'accès à un portail de sécurité ou SSO (ex: Authelia, Authentik, Cloudflare Access ou authentification HTTP de base).
3. **Restriction d'Accès / VPN** : Restreignez l'accès aux seules adresses IP de confiance ou privilégiez un accès via VPN.
4. **Mot de Passe Fort** : Choisissez un mot de passe long et complexe sur l'écran de configuration initial. L'authentification est toujours active — il n'existe aucune configuration dans laquelle l'interface est servie sans connexion.
5. **Mettez `TRUSTED_PROXY_COUNT=0` si vous n'êtes pas derrière un reverse proxy**, afin que le verrouillage anti-force-brute compte la véritable adresse du client et non un en-tête qu'il contrôle.

> **Avertissement de responsabilité** : MetaKavita est fourni "en l'état", sans aucune garantie. Les développeurs et contributeurs déclinent toute responsabilité en cas d'altération de données, d'intrusion ou d'incident de sécurité découlant d'une exposition publique ou d'une erreur de configuration.

---

## 🙌 Contributors / Contributeurs

Community feedback that shaped MetaKavita — thank you!  
*(Retours communautaires qui ont fait évoluer MetaKavita — merci !)*

And if you have not already: a ⭐ on GitHub is the cheapest way to say thanks and boost discoverability.  
*(Et si ce n’est pas déjà fait : une ⭐ sur GitHub, c’est le « merci » le moins cher — et ça aide le dépôt à remonter.)*

| Contributor | Contributions |
| :--- | :--- |
| [**LazyGeniusMan**](https://github.com/LazyGeniusMan) | MangaBaka API hardening (`schema=full`, `type=novel` filter, tag/genre & MAL parsing), official Book/LN provider feedback, `KAVITA_EXTERNAL_URL` (Docker internal API vs public UI URL), Traefik / Socket.IO CORS origin reports, configurable `MAX_TAGS` feedback. |
| [**SqueezedByte**](https://github.com/SqueezedByte) | KOReader / Kamare crash report (`localizedName` nulling), Kavita force-update read-timeout reports → `KAVITA_HTTP_TIMEOUT` + 2-pass soft-success. |
| [**ThoughtzThruKeyz**](https://github.com/ThoughtzThruKeyz) | Publisher metadata feature request, ComicVine scraping feedback, disable-translation option (`NONE`), series / localized title configuration ideas. |
| [**randrini**](https://github.com/randrini) | Free Google Translate (`googletrans`) integration request. |

---

## ⚠️ Notes, Tech Stack & Full Documentation

*   **Security First / Sécurité d'abord :** `SECRET_KEY` and `WEBHOOK_TOKEN` are cryptographically generated on first launch (no public hardcoded `SECRET_KEY` fallback). Keep them private. *(Générés de façon cryptographique au premier démarrage, sans fallback public hardcodé — gardez-les secrets.)*
*   **Tech Stack :** Python 3.11, Flask, Gunicorn (Eventlet WSGI), Flask-SocketIO, Curl-Cffi, BeautifulSoup4, Regex.

### 📖 Full Documentation / Documentation Complète
This README covers everyday usage. For deeper dives, check these files at the project root *(Ce README couvre l'usage courant ; pour aller plus loin, consultez ces fichiers à la racine du projet)* :
* [`CHANGELOG.md`](./CHANGELOG.md) — Full bilingual (EN/FR) version-by-version release history. The topmost entry always reflects the version currently displayed in the app footer. *(Historique complet et bilingue de chaque version ; la première entrée reflète toujours la version affichée dans l'application.)*
* [`ROADMAP.md`](./ROADMAP.md) — Bilingual short-form log of every shipped feature (`Cxx`) and bug fix (`BFxx`), plus the backlog of planned features. *(Journal court et bilingue de chaque fonctionnalité et correctif, ainsi que les fonctionnalités prévues.)*
* [`DEVELOPER.md`](./DEVELOPER.md) — Architecture deep-dive (throttling, WebSockets, scraper registry, scoring matrix) and a **Contribution Workflow** section documenting critical pitfalls to avoid when modifying the codebase. *(Analyse approfondie de l'architecture et guide de contribution listant les pièges critiques à éviter.)*
* [`kavita_api.md`](./kavita_api.md) — Internal technical specification of Kavita's REST API quirks (Lock Guard, 2-pass update protocol, DTO contracts) used by `kavita_api.py`. *(Spécification technique interne des particularités de l'API Kavita.)*
* [`CUSTOM_SCRAPERS.md`](./CUSTOM_SCRAPERS.md) — Strict integration contract and ready-to-use AI prompts ("Vibecoding") to build your own community scrapers. *(Contrat d'intégration strict et Prompts IA prêts à l'emploi pour créer vos propres scrapers.)*