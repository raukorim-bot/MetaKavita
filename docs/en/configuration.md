# Configuration variables

[English](README.md) · [Français](../fr/configuration.md)

← [Documentation](README.md)

Most settings below are also editable in the **Global Configuration** modal (⚙️ Config in the topbar): Kavita URL and API key, provider keys, translation, languages, and planning.

![Global Configuration modal](../../assets/docs-config-modal.png)

*MetaKavita features a Zero-Hardcode API Key engine. Any scraper declaring `needs_api_key = True` will automatically listen to its corresponding environment variable and dynamically render its input field in the UI.*

> **Precedence: `config.json` > environment variable > default.** An environment variable **seeds** a setting the configuration file does not hold yet — it never overrides one you have already changed in the Web UI. On a first run, the variables you set are written into `config.json`, so they both take effect and become editable from the interface; from then on, the interface has the last word.

| Variable | Description | Default Value |
| :--- | :--- | :--- |
| `ADMIN_USERNAME` | Username for the account seeded from `ADMIN_PASSWORD_HASH`. Ignored if an account already exists. | `admin` |
| `ADMIN_PASSWORD_HASH` | Pre-hashed password used to create the first account at startup, skipping the setup screen. Generate with `python debug/hash_password.py`. Ignored once any account exists, so it can never overwrite a real password. A value that is not a hash — a plaintext password, for instance — is refused with an error in the log instead of creating an account no password can open. | *(Empty)* |
| `TRUSTED_PROXY_COUNT` | `1` (default) trusts `X-Forwarded-*` from one reverse proxy. **Set to `0` when MetaKavita is reachable directly**, otherwise the header is attacker-controlled and the *per-IP* lockout can be evaded by rotating it. A global cap (20 failed logins per 15 minutes, all addresses combined) applies in every configuration, so brute-force stays bounded either way — but when it trips it locks the login screen for everyone, including you. | `1` |
| ~~`ADMIN_PASSWORD`~~ | **Removed.** Replaced by the first-run account setup. If a value is still in `config.json`, the setup screen asks for it once as proof that you already had access to this instance — so an upgrade never leaves a protected instance open to whoever reaches `/setup` first. It is deleted as soon as your account is created. Lost it? Blank that line in `data/config.json` and reload the page. | — |
| `PUID` / `PGID` | User and group id the application runs as, and which owns everything under `/app/data`. Set these to the owner of your bind-mounted `./data` folder (`id -u` / `id -g`) if it is not `1000:1000`. The container starts as root only long enough to apply them, then drops privileges. | `1000` / `1000` |
| `ROOT_PATH` | Custom URL subpath when hosted behind a reverse proxy (e.g. `/metakavita`). Env wins over the value saved in setup/`config.json`. Restart required after changing. | *(Empty)* |
| `CORS_ALLOWED_ORIGINS` | Comma-separated explicit origins allowed for CORS (HTTP + Socket.IO), e.g. `https://metakavita.home.local.ltd`. Empty = Same-Origin only. `*` is rejected. Does not replace proper reverse-proxy WebSocket upgrade config. | *(Empty)* |
| `KAVITA_URL` | Kavita URL **as seen from the MetaKavita container** — never `localhost`. Examples: `http://host.docker.internal:5001` (Kavita published on the host), `http://kavita:5000` (same Docker network), or a public `https://…` URL. Empty strings in `config.json` do not block env seeding for this key. | *(Empty)* |
| `KAVITA_EXTERNAL_URL` | Optional public Kavita URL for browser UI links (e.g. `https://kavita.domain.tld`). If empty, falls back to `KAVITA_URL`. | *(Empty)* |
| `KAVITA_HTTP_TIMEOUT` | HTTP timeout in seconds for Kavita **write** requests (metadata / series update / cover upload). Raise to `90`–`120` on slow disks or large force-update batches. | `60` |
| `MAX_TAGS` | Max number of tags written to Kavita (scrapers + `enrichment_engine` safety net). Env / `config.json` only — no UI. Clamped 1–100. | `15` |
| `MAX_GENRES` | Max number of genres written to Kavita (scrapers + `enrichment_engine` safety net). Env / `config.json` only — no UI. Clamped 1–50. | `5` |
| `KAVITA_API_KEY` | Your Kavita API Key. | *(Empty)* |
| `TRANSLATION_PROVIDER` | Active translation engine (`GOOGLE`, `DEEPL`, `AZURE`, or `NONE` to disable). | `GOOGLE` |
| `AZURE_API_KEY` | Microsoft Azure Translator API Key (Primary Translation Engine). | *(Empty)* |
| `AZURE_REGION` | Microsoft Azure Translator API Region (e.g. `francecentral`). | *(Empty)* |
| `DEEPL_API_KEY` | Your DeepL Translation API Key (Fallback Translation Engine). | *(Empty)* |
| `TARGET_LANG` | Output language for summaries (`FR`, `EN`, `ES`...). Also dynamically changes Google Books search language! When absent from `config.json` and env, derived from `UI_LANG` (`en`→`EN`, `fr`→`FR`). | `EN` |
| `UI_LANG` | Dashboard interface language (`fr` or `en`). On a fresh install you can set `UI_LANG=fr` in Compose before opening the UI. Language can also be changed in Settings without filling Kavita credentials first. | `en` |
| `PUBLISHER_PREFERENCE` | Prefer Translated/Localized Publishers (`LOCALIZED`) or Japanese/Original (`ORIGINAL`). | `LOCALIZED` |
| `LOCALIZED_TITLE_MODE` | How to build Kavita `localizedName`: `all` (join unique titles with `" / "`), `prefer` (filter/order by `LOCALIZED_TITLE_LANGS`), `none` (do not write). Never rewrites Series `name`. Also in Config modal. | `all` |
| `LOCALIZED_TITLE_LANGS` | Comma-separated BCP-47-ish tags when mode is `prefer` (e.g. `en, ja-ro, ja`). Order = priority. Per-series override via `alt_title_langs`. | *(Empty)* |
| `PROVIDER_1` | Primary manga metadata source (`MANGABAKA`, `KITSU`, `ANILIST`, `MAL`, `MANGADEX`, `MANGAUPDATES`, `MANGANEWS`, `SHIKIMORI`, plus Magasin e.g. `WIKIDATA`). | `MANGABAKA` |
| `MAL_API_KEY` | MyAnimeList **Client ID** (not a secret token) from https://myanimelist.net/apiconfig — sent as `X-MAL-CLIENT-ID`. | _(empty)_ |
| `PROVIDER_2` | Fallback manga source 1. | `KITSU` |
| `PROVIDER_3` | Fallback manga source 2. | `ANILIST` |
| `COMIC_PROVIDER_1`| Primary comic metadata source (`BEDETHEQUE`, `BDTHEQUE`, `COMICVINE`, `GOOGLEBOOKS`, `OPENLIBRARY`, `HARDCOVER`, `ANILIST`, plus Magasin e.g. `WIKIDATA`). | `COMICVINE` |
| `COMIC_PROVIDER_2`| Fallback comic source 1. | `ANILIST` |
| `COMIC_PROVIDER_3`| Fallback comic source 2. | `NONE` |
| `BOOK_PROVIDER_1` | Primary book metadata source (`GOOGLEBOOKS`, `OPENLIBRARY`, `HARDCOVER`, `ANILIST`, `MANGABAKA`, `MAL`, plus Magasin e.g. `WIKIDATA`). | `GOOGLEBOOKS` |
| `BOOK_PROVIDER_2` | Fallback book source 1. | `OPENLIBRARY` |
| `BOOK_PROVIDER_3` | Fallback book source 2. | `NONE` |
| `SMART_SCORING`   | Enable Smart Scoring — best match wins (`true` or `false`). Off = classic list-order fallback. | `true` |
| `MATCH_THRESHOLD_CUSTOM` | Unlock custom match accept threshold (Reliability barometer). Off = always `0.60`. | `false` |
| `MATCH_ACCEPT_THRESHOLD` | Accept threshold when custom is on (`0.30`–`1.00`). Ignored when custom is off. | `0.60` |
| `ENABLE_PLAYFUL_STATS` | Show playful `/stats` dashboard (Chart.js + fun cards). | `true` |
| `SMART_COMPLETION`| Enable Data Fusion / Smart Patching (`true` or `false`). Auto may backfill age `safe`/`suggestive`/`mature` from secondaries; never NSFW ages. Targeted field **Age** must be on to write Kavita. | `false` |
| `MANUAL_REVIEW_MODE` | Park scrape candidates as `PENDING_REVIEW` for pick/edit/confirm instead of auto-writing Kavita. Sidebar toggle. Turning off purges the queue. | `false` |
| `MANUAL_REVIEW_EDIT` | After pick, show an edit form before Kavita write. | `true` |
| `MANUAL_REVIEW_SUPER` | Super Review: expand all usable scrapers (not only the three cascade slots). Requires Manual Review Mode. | `false` |
| `MANUAL_REVIEW_SOUNDS` | Short UI tones on pick / confirm / skip. | `false` |
| `TITLE_FALLBACK_TRANSLATION`| Experimental: Translates unfound titles to English to force a 2nd search pass. | `false` |
| `AUTO_SYNC_INTERVAL`| Background polling interval in minutes (`0` to disable). | `0` |
| `DISABLED_LIBRARIES` | Comma-separated Kavita library IDs to exclude from **auto-sync polling** only. Empty = all enabled. Dashboard, manual batch, and webhook are not filtered. | _(empty)_ |
| `AUTO_COVER` | Automatically upload new covers to Kavita (`true` or `false`). | `false` |
| `COVER_FORCE_OVERWRITE` | Let automatic scrapes overwrite covers you picked by hand (the 🔒 chip). Leave off to keep manual picks. | `false` |
| `LIBRARY_INVENTORY_ENABLED` | Show the Inventory panel (missing volumes / chapters, duplicates, series without external id). | `true` |
| `INVENTORY_FOLDER_PATH_PREFIX` | POSIX prefix glued in front of Kavita's `folderPath` in the bash script (e.g. `/mnt/media`). Set in the Duplicates modal. Empty = Kavita path as-is. | _(empty)_ |
| `INVENTORY_FOLDER_TRASH` | POSIX trash folder for the generated `mv` script, outside Kavita library roots (e.g. `/mnt/media/corbeille-doublons`). Set in the Duplicates modal. | _(empty)_ |
| `VOLUME_ENRICHMENT_ENABLED` | Write metadata onto each volume / album (title, summary, release date, ISBN, cover). Off means the buttons are hidden and the API answers 403. | `false` |
| `VOLUME_FORCE_OVERWRITE` | Let volume enrichment overwrite fields that are already filled or locked in Kavita. Leave off to only fill the blanks. | `false` |
| `VOLUME_ENRICH_CREDITS` | Also fetch author credits per album — one extra provider request per volume. | `false` |
| `VOLUME_ENRICH_EXPERIMENTAL` | For manga with neither a provider volume list nor an ISBN: look each volume up on Google Books by series title plus number. The result's title and number are re-checked before writing, but no identifier proves it is the right volume. | `false` |
| `VOLUME_PROVIDER` | Ask one provider only for volumes, cascade dropped. Honoured only where that provider can serve the library, so forcing a comic provider does not leave your manga libraries without one. Empty = let the cascade decide. | _(empty)_ |
| `VOLUME_NO_MANGA_FALLBACK` | On a **Comic (Flexible)** library, stop falling back to the manga providers after the comic ones. Useful when you only keep comics there; no effect on other library types. | `false` |
| `UI_SHOW_MANUAL_REVIEW` | Show the manual review settings in the sidebar. Off hides the category **and** switches the mode off, queue emptied. | `true` |
| `UI_SHOW_INVENTORY` | Show the Inventory settings in the sidebar. Off hides the category **and** switches the Inventory off. | `true` |
| `UI_SHOW_VOLUMES` | Show the volume enrichment settings in the sidebar. Off hides the category **and** switches the pass off. | `true` |
| `UI_SHOW_FIELD_MAPPING` | Show the per-field mapping settings in the sidebar. Off hides the category **and** switches mapping off (Auto falls back to the current cascade). Hidden by default. | `false` |
| `FIELD_MAPPING_ENABLED` | Use the per-field map on Auto / batch. Ignored when the category is hidden, when Manual Review is on, or when a series has a forced provider. | `false` |
| `FIELD_MAPPING_DEFAULT_MANGA` | Default source for manga Auto fields: `CASCADE` or a manga provider id. | `CASCADE` |
| `FIELD_MAPPING_DEFAULT_COMIC` | Default source for strict-comic Auto fields. | `CASCADE` |
| `FIELD_MAPPING_DEFAULT_BOOK` | Default source for book Auto fields. | `CASCADE` |
| `FIELD_MAPPING_DEFAULT_COMICFLEXIBLE` | Default source for the comics wave of Comic (Flexible). | `CASCADE` |
| `FIELD_MAPPING_DEFAULT_COMICFLEXIBLE_MANGA` | Default source for the manga fallback wave of Comic (Flexible). | `CASCADE` |
| `FIELD_PROVIDER_MAP_MANGA` | Per-field overrides for manga (`cover` → `ANILIST`, …). Empty key = follow the default. | `{}` |
| `FIELD_PROVIDER_MAP_COMIC` | Per-field overrides for strict comic libraries. | `{}` |
| `FIELD_PROVIDER_MAP_BOOK` | Per-field overrides for book libraries. | `{}` |
| `FIELD_PROVIDER_MAP_COMICFLEXIBLE` | Per-field overrides for the Flexible comics wave. | `{}` |
| `FIELD_PROVIDER_MAP_COMICFLEXIBLE_MANGA` | Per-field overrides for the Flexible manga fallback wave. | `{}` |
---
