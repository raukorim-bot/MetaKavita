# Providers & scrapers

[English](README.md) · [Français](../fr/scrapers.md)

← [Documentation](README.md)

## Provider cascades

**Scrapers → Provider cascades** (or the sidebar **Scraper cascades** button) sets search order per library type. #1 is primary; #2 and #3 are fallbacks, and Smart Scoring / Smart Completion sources. Inventory (missing volumes / expected count) reuses these cascades; if no expected count is found, backup scrapers (AniList, MAL, ComicVine) run automatically.

![Provider Cascades modal](../../assets/docs-provider-cascades.png)

Keys: `PROVIDER_1`–`3`, `COMIC_PROVIDER_1`–`3`, `BOOK_PROVIDER_1`–`3` — see [Configuration](configuration.md).

## Built-in sources

Built-in (v1.6.3): Babelio, Decitre, SensCritique, ANN, LoCG, Planète BD, and Metron (`METRON_API_KEY`) ship in the image alongside AniList, ComicVine, Bédéthèque, and the rest. Prefer Config provider slots over sideloading duplicates of these seven.

Typical grouping:

* **Manga:** MangaDex, AniList, Kitsu, Shikimori, MangaBaka, MangaUpdates, Manga-News, MyAnimeList, Anime News Network
* **Comics / BD:** ComicVine, Bédéthèque, BDTheque, Planète BD, Metron, League of Comic Geeks
* **Books:** Google Books, Open Library, Hardcover, Babelio, Decitre, SensCritique

Some sources also serve a second library type (AniList, MAL, MangaBaka, Google Books, Open Library, Hardcover, SensCritique).

**Comic Flexible (corrected in v1.7.0):** hybrid cascade = Comic providers first, then Manga if no useful hit. It applies to Kavita library type **ID 1** (*Comic (Flexible)*), not ID 5 (*Comic*, strict Comic cascade). See `CHANGELOG.md` 1.7.0.

**Wikidata** is Magasin-only (limited scope — fallback / ISBN / cross-IDs, not a primary).

## Community Store

Help → **Manage scrapers** (`/manage-scrapers`) and **Community Store** (`/scraper-store`). Tabs: **Installed**, **Store**, **Diagnostics**. The Installed grid is Core vs Store, Enabled / Disabled, media tags (Manga / Comic / Book / Series / Volume). Search and filters, **Open store**. Core cards stay installed — **Disable** only (`DISABLED_SCRAPERS`); Store cards can be deleted. Community scrapers are marked as a testing phase.

![Manage scrapers](../../assets/docs-scrapers-manage.png)

The **Store** tab (`/scraper-store`) lists the community catalog: sha256-checked installs, search and filters (type / scope / status / grade / covers), **Refresh**, **View installed**. Each card: **Install**, **View code**, **Docs**, plus tags (**Covers OK** / **No covers**). Same testing-phase notice.

![Community store](../../assets/docs-scrapers-store.png)

The registry loads from `data/scrapers/`. On boot, core modules refresh from the community catalog (Docker-image fallback if GitHub is unreachable; `AUTO_UPDATE_CORE_SCRAPERS` default on).

* Community scrapers install / update / delete from the Store (sha256-checked GitHub catalog) with hot reload — no container restart.
* A file dropped in by hand still needs a restart (or a later store/reload action).

1. Prefer [community-scraper-metakavita](https://github.com/raukorim-bot/community-scraper-metakavita) via the Store.
2. Or drop a valid `.py` into `data/scrapers/` and restart.
3. The scraper joins provider dropdowns, API-key fields when `needs_api_key` is set, and the SSRF image-proxy allowlist via `proxy_domains`.

To join **Smart Scoring**, set `uses_unified_scoring = True` and return candidates via `attach_match_score(...)` (see [`CUSTOM_SCRAPERS.md`](../../CUSTOM_SCRAPERS.md) §4). Otherwise the scraper stays usable with a neutral score.

A `.py` in `data/scrapers/` is executed with the application's privileges. Read [Security](security.md) and `CUSTOM_SCRAPERS.md` before installing anything — including AI-generated scrapers.

## Diagnostics

The **Diagnostics** tab (`/diagnostics`, also from Help → **Scraper diagnostics**). **Is everything answering?** runs preflight first: **Internet** and **Kavita** (latency, HTTP status, library count) — **Re-run preflight** to repeat.

**Scraper health** then calls `fetch()` and `fetch_covers()` on a known-good query, without changing scraper code. On load, only the Config cascade is probed; others stay listed until you add them to a Providers slot or press **Test all**. **Test cascade** re-runs the slots. Legend: green OK, amber partial, red down / ban / schema, gray missing API key.

![Scraper diagnostics](../../assets/docs-scrapers-diagnostics.png)

## Be kind to metadata providers

Those APIs and sites are often run for free. Please:

1. Let MetaKavita pace itself. Do not run several instances against the same providers, hammer Sync, or stack overlapping giant batches.
2. Expect ~**8 s/series** with Smart Scoring, Smart Completion, title fallback, auto-cover, and a full cascade. Want it faster? Configure **one** provider and turn off options you do not need.
3. Prefer one planned enrich pass over endless re-syncs of completed series.
4. First full fill or huge force-batch: run it overnight.
5. Afterwards, prefer Auto-Sync / webhooks for new series.

## Engine notes

* Smart Scoring: best match wins; malformed community scores cannot crash enrichment.
* Cover uploads use pure Base64 (no phantom-cover Data URI).
* Per-provider rate limiter; after provider #1 seeds context, the others run in parallel.
* Partial Kavita updates use a GET-merge-POST cycle so untouched fields are not nulled.
* `MAX_TAGS` (default 15) and `MAX_GENRES` (default 5) via env / `config.json` — no UI.
